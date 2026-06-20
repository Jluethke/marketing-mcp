# SPDX-License-Identifier: MIT
"""Marketing MCP server.

One MCP server combining the full feature surface of the public Google Ads /
Keyword Planner / Meta Ads / GA4 servers, across three platforms plus no-auth
keyword research:

  KEYWORD RESEARCH (Google Ads API + no-auth)
    keyword_ideas               generateKeywordIdeas (seed words or a URL)
    keyword_historical_metrics  12-month volume series + competition + bid range
    forecast_keywords           projected impressions / clicks / cost at a max CPC
    autocomplete_suggestions    Google Suggest completions          (no auth)
    trend_index                 Google Trends interest + related     (pytrends)
    cluster_keywords            group a keyword list into themes      (no auth)

  GOOGLE ADS (reporting + management; Google Ads API)
    list_ads_accounts           accessible customer ids
    ads_query                   run any GAQL query (full reporting surface)
    campaign_performance        per-campaign metrics over a date range
    search_terms_report         search terms + metrics
    set_campaign_status         pause / enable a campaign
    set_campaign_budget         change a campaign budget amount

  META ADS (reporting + management; Graph Marketing API)
    meta_list_ad_accounts / meta_list_campaigns / meta_list_adsets / meta_list_ads
    meta_insights               spend / impressions / clicks / ctr / cpc / actions
    meta_set_campaign_status    pause / activate a campaign

  GA4 (analytics; Analytics Data API)
    ga4_run_report              any dimensions x metrics over a date range
    ga4_realtime                realtime report
    ga4_traffic_sources / ga4_top_pages   convenience reports

Auth'd tools return a clear setup error until their credentials are configured;
the no-auth tools run with no setup. Run: python server.py  (stdio transport).
"""
from __future__ import annotations

import datetime
import json
import os
from collections import Counter, defaultdict

from mcp.server.fastmcp import FastMCP

# Auto-load a .env placed next to this server, so credentials need no manual
# wiring into the MCP config. No-op if python-dotenv or the file is absent.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except Exception:  # noqa: BLE001
    pass

mcp = FastMCP("marketing-mcp")

# ---- shared helpers -------------------------------------------------------

_GEO = {"US": "2840", "CA": "2124", "GB": "2826", "UK": "2826", "AU": "2036",
        "IN": "2356", "DE": "2276", "FR": "2250", "ES": "2724", "IE": "2372"}
_LANG = {"en": "1000", "es": "1003", "fr": "1002", "de": "1001", "pt": "1014", "it": "1004"}


def _geo_res(geo: str) -> str:
    return "geoTargetConstants/" + _GEO.get(str(geo).upper(), str(geo))


def _lang_res(lang: str) -> str:
    return "languageConstants/" + _LANG.get(str(lang).lower(), str(lang))


def _dollars(micros) -> float:
    return round((micros or 0) / 1_000_000, 2)


def _date_range(days: int) -> tuple[str, str]:
    end = datetime.date.today()
    start = end - datetime.timedelta(days=max(1, days))
    return start.isoformat(), end.isoformat()


def _ads_client():
    try:
        from google.ads.googleads.client import GoogleAdsClient
    except ImportError:
        raise RuntimeError("google-ads not installed. Run: pip install google-ads")
    need = ["GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_ID",
            "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_REFRESH_TOKEN"]
    missing = [k for k in need if not os.environ.get(k)]
    if missing:
        raise RuntimeError("Missing Google Ads credentials: " + ", ".join(missing)
                           + ". See README.md (Setup -> Google Ads).")
    cfg = {
        "developer_token": os.environ["GOOGLE_ADS_DEVELOPER_TOKEN"],
        "client_id": os.environ["GOOGLE_ADS_CLIENT_ID"],
        "client_secret": os.environ["GOOGLE_ADS_CLIENT_SECRET"],
        "refresh_token": os.environ["GOOGLE_ADS_REFRESH_TOKEN"],
        "use_proto_plus": True,
    }
    lcid = os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID")
    if lcid:
        cfg["login_customer_id"] = lcid.replace("-", "")
    return GoogleAdsClient.load_from_dict(cfg)


def _customer_id(override: str | None = None, client: str | None = None) -> str:
    cid = (override or _client_field(client, "google_ads_customer_id")
           or os.environ.get("GOOGLE_ADS_CUSTOMER_ID")
           or os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID"))
    if not cid:
        raise RuntimeError("Set GOOGLE_ADS_CUSTOMER_ID, pass customer_id, or pass a client "
                           "that has google_ads_customer_id in clients.json.")
    return cid.replace("-", "")


def _row_to_dict(row) -> dict:
    from google.protobuf.json_format import MessageToDict
    return MessageToDict(row._pb, preserving_proto_field_name=True)


_META_API = "https://graph.facebook.com/v20.0"


def _meta_token() -> str:
    t = os.environ.get("META_ACCESS_TOKEN")
    if not t:
        raise RuntimeError("Set META_ACCESS_TOKEN (Meta Marketing API token). See README.md (Setup -> Meta).")
    return t


def _meta_get(path: str, params: dict | None = None) -> dict:
    import httpx
    p = dict(params or {})
    p["access_token"] = _meta_token()
    r = httpx.get(_META_API + "/" + path.lstrip("/"), params=p, timeout=30.0)
    data = r.json()
    if isinstance(data, dict) and "error" in data:
        raise RuntimeError("Meta API error: " + str(data["error"].get("message", data["error"])))
    return data


def _meta_post(path: str, data: dict) -> dict:
    import httpx
    d = dict(data)
    d["access_token"] = _meta_token()
    r = httpx.post(_META_API + "/" + path.lstrip("/"), data=d, timeout=30.0)
    j = r.json()
    if isinstance(j, dict) and "error" in j:
        raise RuntimeError("Meta API error: " + str(j["error"].get("message", j["error"])))
    return j


def _ga4_client():
    try:
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
    except ImportError:
        raise RuntimeError("google-analytics-data not installed. Run: pip install google-analytics-data")
    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        raise RuntimeError("Set GOOGLE_APPLICATION_CREDENTIALS to a GA4 service-account json path. "
                           "See README.md (Setup -> GA4).")
    return BetaAnalyticsDataClient()


# ---- client registry (multi-account) --------------------------------------
# clients.json (gitignored; holds account ids) maps a client name to its account
# ids per platform, so a tool can target one client granularly or roll up across
# all of them. clients.example.json is the template.

_CLIENTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clients.json")


def _load_clients() -> dict:
    try:
        with open(_CLIENTS_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _save_clients(d: dict) -> None:
    with open(_CLIENTS_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _client_record(name: str | None = None) -> dict:
    d = _load_clients()
    clients = d.get("clients", {}) or {}
    if name:
        return clients.get(name, {}) or {}
    default = d.get("default")
    return (clients.get(default, {}) or {}) if default else {}


def _client_field(name: str | None, field: str):
    return (_client_record(name).get(field) or None) if name else None


def _meta_account(client: str | None = None, override: str | None = None):
    return override or _client_field(client, "meta_ad_account_id")


def _ga4_property(client: str | None = None, override: str | None = None):
    return override or _client_field(client, "ga4_property_id")


# ==== KEYWORD RESEARCH =====================================================

@mcp.tool()
def keyword_ideas(seed_keywords: list[str] | None = None, page_url: str | None = None,
                  geo: str = "US", language: str = "en", limit: int = 200,
                  include_adult: bool = False) -> dict:
    """Keyword ideas from seed keywords and/or a landing-page URL, with average
    monthly searches, competition, and top-of-page bid range. Without active ad
    spend, volumes come back as Google's coarse ranges, not exact numbers."""
    try:
        client = _ads_client()
        cid = _customer_id()
    except RuntimeError as e:
        return {"needs_setup": str(e)}
    svc = client.get_service("KeywordPlanIdeaService")
    req = client.get_type("GenerateKeywordIdeasRequest")
    req.customer_id = cid
    req.language = _lang_res(language)
    req.geo_target_constants.append(_geo_res(geo))
    req.include_adult_keywords = include_adult
    req.keyword_plan_network = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
    seeds = [s for s in (seed_keywords or []) if s]
    if seeds and page_url:
        req.keyword_and_url_seed.url = page_url
        req.keyword_and_url_seed.keywords.extend(seeds)
    elif seeds:
        req.keyword_seed.keywords.extend(seeds)
    elif page_url:
        req.url_seed.url = page_url
    else:
        return {"error": "provide seed_keywords and/or page_url"}
    out = []
    try:
        for idea in svc.generate_keyword_ideas(request=req):
            m = idea.keyword_idea_metrics
            out.append({
                "keyword": idea.text,
                "avg_monthly_searches": m.avg_monthly_searches,
                "competition": m.competition.name,
                "competition_index": m.competition_index,
                "low_top_of_page_bid": _dollars(m.low_top_of_page_bid_micros),
                "high_top_of_page_bid": _dollars(m.high_top_of_page_bid_micros),
            })
            if len(out) >= limit:
                break
    except Exception as e:  # noqa: BLE001
        return {"error": "Google Ads API error: " + str(e)}
    return {"count": len(out), "ideas": out}


@mcp.tool()
def keyword_historical_metrics(keywords: list[str], geo: str = "US",
                               language: str = "en") -> dict:
    """Historical monthly search volume (12-month series), competition score, and
    bid range for a specific list of keywords."""
    try:
        client = _ads_client()
        cid = _customer_id()
    except RuntimeError as e:
        return {"needs_setup": str(e)}
    svc = client.get_service("KeywordPlanIdeaService")
    req = client.get_type("GenerateKeywordHistoricalMetricsRequest")
    req.customer_id = cid
    req.keywords.extend([k for k in keywords if k])
    req.language = _lang_res(language)
    req.geo_target_constants.append(_geo_res(geo))
    req.keyword_plan_network = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
    try:
        resp = svc.generate_keyword_historical_metrics(request=req)
    except Exception as e:  # noqa: BLE001
        return {"error": "Google Ads API error: " + str(e)}
    out = []
    for r in resp.results:
        m = r.keyword_metrics
        out.append({
            "keyword": r.text,
            "close_variants": list(r.close_variants),
            "avg_monthly_searches": m.avg_monthly_searches,
            "competition": m.competition.name,
            "competition_index": m.competition_index,
            "low_top_of_page_bid": _dollars(m.low_top_of_page_bid_micros),
            "high_top_of_page_bid": _dollars(m.high_top_of_page_bid_micros),
            "monthly_volumes": [
                {"year": v.year, "month": v.month.name, "searches": v.monthly_searches}
                for v in m.monthly_search_volumes
            ],
        })
    return {"count": len(out), "metrics": out}


@mcp.tool()
def forecast_keywords(keywords: list[str], max_cpc_bid: float = 1.0,
                      geo: str = "US", language: str = "en") -> dict:
    """Forecast projected impressions, clicks, cost, CTR, and average CPC for a
    set of keywords at a given max CPC bid (dollars)."""
    try:
        client = _ads_client()
        cid = _customer_id()
    except RuntimeError as e:
        return {"needs_setup": str(e)}
    svc = client.get_service("KeywordPlanIdeaService")
    req = client.get_type("GenerateKeywordForecastMetricsRequest")
    req.customer_id = cid
    bid_micros = int(max_cpc_bid * 1_000_000)
    campaign = req.campaign
    campaign.keyword_plan_network = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
    campaign.bidding_strategy.manual_cpc_bidding_strategy.max_cpc_bid_micros = bid_micros
    geo_mod = client.get_type("CriterionBidModifier")
    geo_mod.geo_target_constant = _geo_res(geo)
    campaign.geo_modifiers.append(geo_mod)
    campaign.language_constants.append(_lang_res(language))
    ad_group = client.get_type("ForecastAdGroup")
    for kw in [k for k in keywords if k]:
        bk = client.get_type("BiddableKeyword")
        bk.max_cpc_bid_micros = bid_micros
        bk.keyword.text = kw
        bk.keyword.match_type = client.enums.KeywordMatchTypeEnum.BROAD
        ad_group.biddable_keywords.append(bk)
    campaign.ad_groups.append(ad_group)
    try:
        resp = svc.generate_keyword_forecast_metrics(request=req)
    except Exception as e:  # noqa: BLE001
        return {"error": "Google Ads API error: " + str(e)}
    f = resp.campaign_forecast_metrics
    return {"max_cpc_bid": max_cpc_bid, "impressions": round(f.impressions, 1),
            "clicks": round(f.clicks, 1), "cost": _dollars(f.cost_micros),
            "ctr": round(f.ctr, 4), "average_cpc": _dollars(f.average_cpc_micros)}


@mcp.tool()
def autocomplete_suggestions(query: str, geo: str = "us", lang: str = "en",
                             limit: int = 15) -> dict:
    """Google Suggest autocomplete completions for a query. No credentials."""
    import httpx
    try:
        r = httpx.get("https://suggestqueries.google.com/complete/search",
                      params={"client": "firefox", "q": query, "hl": lang, "gl": geo},
                      timeout=10.0, headers={"User-Agent": "Mozilla/5.0"})
        data = r.json()
    except Exception as e:  # noqa: BLE001
        return {"error": "autocomplete request failed: " + str(e)}
    sugg = data[1] if isinstance(data, list) and len(data) > 1 else []
    return {"query": query, "suggestions": list(sugg)[:limit]}


@mcp.tool()
def trend_index(keywords: list[str], timeframe: str = "today 12-m", geo: str = "US") -> dict:
    """Google Trends relative interest over time plus top and rising related
    queries, up to 5 keywords. Needs pytrends (pip install pytrends)."""
    try:
        from pytrends.request import TrendReq
    except ImportError:
        return {"error": "pytrends not installed. Run: pip install pytrends"}
    kws = [k for k in keywords if k][:5]
    if not kws:
        return {"error": "provide 1-5 keywords"}
    try:
        py = TrendReq(hl="en-US")
        py.build_payload(kws, timeframe=timeframe, geo=geo)
        iot = py.interest_over_time()
        rel = py.related_queries()
    except Exception as e:  # noqa: BLE001
        return {"error": "trends request failed: " + str(e)}
    series = {}
    if iot is not None and not iot.empty:
        for k in kws:
            if k in iot:
                series[k] = {"mean": round(float(iot[k].mean()), 1),
                             "max": int(iot[k].max()), "latest": int(iot[k].iloc[-1])}
    related = {}
    for k in kws:
        rq = rel.get(k) or {}
        top, rising = rq.get("top"), rq.get("rising")
        related[k] = {
            "top": [row["query"] for row in top.to_dict("records")][:8] if top is not None else [],
            "rising": [row["query"] for row in rising.to_dict("records")][:8] if rising is not None else [],
        }
    return {"timeframe": timeframe, "geo": geo, "interest": series, "related_queries": related}


_STOP = {"the", "a", "an", "for", "to", "of", "and", "or", "in", "on", "with", "best",
         "how", "what", "why", "near", "me", "my", "your", "is", "are", "vs", "top",
         "free", "online", "service", "services", "company"}


@mcp.tool()
def cluster_keywords(keywords: list[str], max_clusters: int = 0) -> dict:
    """Group a keyword list into themes by the most-shared significant token, so a
    long idea list becomes a small set of topic clusters. No credentials."""
    tokens: dict[str, list[str]] = {}
    freq: Counter = Counter()
    for kw in keywords:
        norm = "".join(c.lower() if (c.isalnum() or c == " ") else " " for c in kw)
        t = [w for w in norm.split() if w not in _STOP and len(w) > 1]
        tokens[kw] = t
        freq.update(set(t))
    clusters: dict[str, list[str]] = defaultdict(list)
    for kw, t in tokens.items():
        if not t:
            clusters["(misc)"].append(kw)
            continue
        head = max(t, key=lambda w: (freq[w], -len(w)))
        clusters[head].append(kw)
    out = [{"theme": k, "size": len(v), "keywords": sorted(v)} for k, v in clusters.items()]
    out.sort(key=lambda c: (-c["size"], c["theme"]))
    if max_clusters > 0:
        out = out[:max_clusters]
    return {"n_clusters": len(out), "clusters": out}


# ==== GOOGLE ADS reporting + management ====================================

@mcp.tool()
def list_ads_accounts() -> dict:
    """List the Google Ads customer ids the configured credentials can access."""
    try:
        client = _ads_client()
    except RuntimeError as e:
        return {"needs_setup": str(e)}
    try:
        svc = client.get_service("CustomerService")
        res = svc.list_accessible_customers()
        return {"accounts": [r.split("/")[-1] for r in res.resource_names]}
    except Exception as e:  # noqa: BLE001
        return {"error": "Google Ads API error: " + str(e)}


@mcp.tool()
def ads_query(gaql: str, customer_id: str | None = None, client: str | None = None,
              limit: int = 1000) -> dict:
    """Run any GAQL query against Google Ads and return the rows. This is the full
    reporting surface: campaign, ad_group, ad_group_ad, keyword_view,
    search_term_view, and the metrics/segments on each. Target an account by
    `customer_id`, or by `client` name (resolved from clients.json). Example:
    'SELECT campaign.name, metrics.clicks FROM campaign WHERE segments.date DURING LAST_7_DAYS'."""
    try:
        gclient = _ads_client()
        cid = _customer_id(customer_id, client)
    except RuntimeError as e:
        return {"needs_setup": str(e)}
    try:
        svc = gclient.get_service("GoogleAdsService")
        rows = []
        for batch in svc.search_stream(customer_id=cid, query=gaql):
            for row in batch.results:
                rows.append(_row_to_dict(row))
                if len(rows) >= limit:
                    break
            if len(rows) >= limit:
                break
        return {"row_count": len(rows), "rows": rows}
    except Exception as e:  # noqa: BLE001
        return {"error": "Google Ads API error: " + str(e)}


@mcp.tool()
def campaign_performance(days: int = 30, customer_id: str | None = None,
                         client: str | None = None) -> dict:
    """Per-campaign performance (impressions, clicks, cost, conversions, CTR, avg
    CPC) over the last N days, highest spend first. Target one account by
    customer_id or one `client` from clients.json."""
    start, end = _date_range(days)
    gaql = ("SELECT campaign.id, campaign.name, campaign.status, metrics.impressions, "
            "metrics.clicks, metrics.cost_micros, metrics.conversions, metrics.ctr, "
            "metrics.average_cpc FROM campaign WHERE segments.date BETWEEN '%s' AND '%s' "
            "ORDER BY metrics.cost_micros DESC" % (start, end))
    return ads_query(gaql, customer_id=customer_id, client=client)


@mcp.tool()
def search_terms_report(days: int = 30, customer_id: str | None = None,
                        client: str | None = None, limit: int = 200) -> dict:
    """The search terms that triggered ads, with impressions, clicks, cost, and
    conversions over the last N days. Target one account by customer_id or one
    `client` from clients.json."""
    start, end = _date_range(days)
    gaql = ("SELECT search_term_view.search_term, campaign.name, metrics.impressions, "
            "metrics.clicks, metrics.cost_micros, metrics.conversions "
            "FROM search_term_view WHERE segments.date BETWEEN '%s' AND '%s' "
            "ORDER BY metrics.impressions DESC" % (start, end))
    return ads_query(gaql, customer_id=customer_id, client=client, limit=limit)


@mcp.tool()
def set_campaign_status(campaign_id: str, status: str = "PAUSED",
                        customer_id: str | None = None, client: str | None = None) -> dict:
    """Pause or enable a Google Ads campaign. status = PAUSED or ENABLED. Target one
    account by customer_id or one `client` from clients.json."""
    try:
        gclient = _ads_client()
        cid = _customer_id(customer_id, client)
    except RuntimeError as e:
        return {"needs_setup": str(e)}
    try:
        from google.api_core import protobuf_helpers
        svc = gclient.get_service("CampaignService")
        op = gclient.get_type("CampaignOperation")
        c = op.update
        c.resource_name = svc.campaign_path(cid, campaign_id)
        c.status = gclient.enums.CampaignStatusEnum[status.upper()]
        gclient.copy_from(op.update_mask, protobuf_helpers.field_mask(None, c._pb))
        resp = svc.mutate_campaigns(customer_id=cid, operations=[op])
        return {"updated": resp.results[0].resource_name, "status": status.upper()}
    except Exception as e:  # noqa: BLE001
        return {"error": "Google Ads API error: " + str(e)}


@mcp.tool()
def set_campaign_budget(campaign_budget_id: str, amount: float,
                        customer_id: str | None = None, client: str | None = None) -> dict:
    """Change a campaign budget's daily amount (dollars). Pass the campaign budget
    id (from campaign.campaign_budget), not the campaign id. Target one account by
    customer_id or one `client` from clients.json."""
    try:
        gclient = _ads_client()
        cid = _customer_id(customer_id, client)
    except RuntimeError as e:
        return {"needs_setup": str(e)}
    try:
        from google.api_core import protobuf_helpers
        svc = gclient.get_service("CampaignBudgetService")
        op = gclient.get_type("CampaignBudgetOperation")
        b = op.update
        b.resource_name = svc.campaign_budget_path(cid, campaign_budget_id)
        b.amount_micros = int(amount * 1_000_000)
        gclient.copy_from(op.update_mask, protobuf_helpers.field_mask(None, b._pb))
        resp = svc.mutate_campaign_budgets(customer_id=cid, operations=[op])
        return {"updated": resp.results[0].resource_name, "amount": amount}
    except Exception as e:  # noqa: BLE001
        return {"error": "Google Ads API error: " + str(e)}


# ==== META ADS reporting + management ======================================

@mcp.tool()
def meta_list_ad_accounts() -> dict:
    """List the Meta ad accounts the access token can reach."""
    try:
        data = _meta_get("me/adaccounts", {"fields": "account_id,name,account_status,currency"})
    except RuntimeError as e:
        return {"needs_setup": str(e)}
    return {"accounts": data.get("data", [])}


@mcp.tool()
def meta_list_campaigns(ad_account_id: str | None = None, client: str | None = None,
                        limit: int = 100) -> dict:
    """Campaigns under a Meta ad account (act_<id> or <id>), or one `client` from
    clients.json (uses its meta_ad_account_id)."""
    acct_id = _meta_account(client, ad_account_id)
    if not acct_id:
        return {"needs_setup": "provide ad_account_id or a client with meta_ad_account_id in clients.json"}
    acct = str(acct_id) if str(acct_id).startswith("act_") else "act_" + str(acct_id)
    try:
        data = _meta_get(acct + "/campaigns",
                         {"fields": "id,name,objective,status,daily_budget,lifetime_budget", "limit": limit})
    except RuntimeError as e:
        return {"needs_setup": str(e)}
    return {"campaigns": data.get("data", [])}


@mcp.tool()
def meta_list_adsets(campaign_id: str, limit: int = 100) -> dict:
    """Ad sets under a Meta campaign."""
    try:
        data = _meta_get(campaign_id + "/adsets",
                         {"fields": "id,name,status,daily_budget,optimization_goal", "limit": limit})
    except RuntimeError as e:
        return {"needs_setup": str(e)}
    return {"adsets": data.get("data", [])}


@mcp.tool()
def meta_list_ads(adset_id: str, limit: int = 100) -> dict:
    """Ads under a Meta ad set."""
    try:
        data = _meta_get(adset_id + "/ads", {"fields": "id,name,status,creative", "limit": limit})
    except RuntimeError as e:
        return {"needs_setup": str(e)}
    return {"ads": data.get("data", [])}


@mcp.tool()
def meta_insights(object_id: str | None = None, level: str = "campaign", days: int = 30,
                  client: str | None = None, date_preset: str | None = None,
                  fields: str = "impressions,clicks,spend,ctr,cpc,cpm,reach,actions") -> dict:
    """Meta Ads insights (performance) over the last `days` days (or a Meta
    date_preset like last_7d). Pass object_id (ad account act_<id>, campaign, ad
    set, or ad), or a `client` from clients.json (uses its ad account at account
    level). level = account|campaign|adset|ad."""
    oid = object_id
    if not oid and client:
        acct = _meta_account(client)
        if acct:
            oid = str(acct) if str(acct).startswith("act_") else "act_" + str(acct)
            level = "account"
    if not oid:
        return {"needs_setup": "provide object_id or a client with meta_ad_account_id in clients.json"}
    params = {"level": level, "fields": fields}
    if date_preset:
        params["date_preset"] = date_preset
    else:
        start, end = _date_range(days)
        params["time_range"] = '{"since":"%s","until":"%s"}' % (start, end)
    try:
        data = _meta_get(oid + "/insights", params)
    except RuntimeError as e:
        return {"needs_setup": str(e)}
    return {"insights": data.get("data", [])}


@mcp.tool()
def meta_set_campaign_status(campaign_id: str, status: str = "PAUSED") -> dict:
    """Pause or activate a Meta campaign. status = PAUSED or ACTIVE."""
    try:
        j = _meta_post(campaign_id, {"status": status.upper()})
    except RuntimeError as e:
        return {"needs_setup": str(e)}
    return {"campaign_id": campaign_id, "status": status.upper(), "result": j}


# ==== GA4 analytics ========================================================

def _ga4_report(property_id, dimensions, metrics, start_date, end_date, limit, realtime=False):
    client = _ga4_client()  # raises the actionable RuntimeError if lib/creds missing
    from google.analytics.data_v1beta.types import (
        RunReportRequest, RunRealtimeReportRequest, Dimension, Metric, DateRange)
    prop = "properties/" + str(property_id).replace("properties/", "")
    if realtime:
        req = RunRealtimeReportRequest(
            property=prop, dimensions=[Dimension(name=d) for d in dimensions],
            metrics=[Metric(name=m) for m in metrics], limit=limit)
        resp = client.run_realtime_report(req)
    else:
        req = RunReportRequest(
            property=prop, dimensions=[Dimension(name=d) for d in dimensions],
            metrics=[Metric(name=m) for m in metrics],
            date_ranges=[DateRange(start_date=start_date, end_date=end_date)], limit=limit)
        resp = client.run_report(req)
    dims = [h.name for h in resp.dimension_headers]
    mets = [h.name for h in resp.metric_headers]
    rows = []
    for r in resp.rows:
        row = {dims[i]: r.dimension_values[i].value for i in range(len(dims))}
        for i in range(len(mets)):
            row[mets[i]] = r.metric_values[i].value
        rows.append(row)
    return {"dimensions": dims, "metrics": mets, "row_count": len(rows), "rows": rows}


@mcp.tool()
def ga4_run_report(property_id: str | None = None, days: int = 28,
                   dimensions: list[str] | None = None, metrics: list[str] | None = None,
                   start_date: str | None = None, end_date: str = "today",
                   limit: int = 100, client: str | None = None) -> dict:
    """Run any GA4 report over the last `days` days (the consistent date control,
    same as the Ads and Meta tools), or pass an explicit start_date/end_date.
    Target a property by property_id or one `client` from clients.json. Defaults
    to sessions and users by default channel group. Dimensions/metrics are GA4
    API names (e.g. sessionSource, pagePath; sessions, totalUsers)."""
    prop = _ga4_property(client, property_id)
    if not prop:
        return {"needs_setup": "provide property_id or a client with ga4_property_id in clients.json"}
    sd = start_date or ("%ddaysAgo" % days)
    try:
        return _ga4_report(prop, dimensions or ["sessionDefaultChannelGroup"],
                           metrics or ["sessions", "totalUsers"], sd, end_date, limit)
    except RuntimeError as e:
        return {"needs_setup": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"error": "GA4 API error: " + str(e)}


@mcp.tool()
def ga4_realtime(property_id: str, dimensions: list[str] | None = None,
                 metrics: list[str] | None = None, limit: int = 50) -> dict:
    """GA4 realtime report (last 30 minutes). Defaults to active users by country."""
    try:
        return _ga4_report(property_id, dimensions or ["country"],
                           metrics or ["activeUsers"], None, None, limit, realtime=True)
    except RuntimeError as e:
        return {"needs_setup": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"error": "GA4 API error: " + str(e)}


@mcp.tool()
def ga4_traffic_sources(property_id: str | None = None, days: int = 28, limit: int = 25,
                        client: str | None = None) -> dict:
    """GA4 sessions, users, and conversions by acquisition channel over N days.
    Target a property by property_id or one `client` from clients.json."""
    prop = _ga4_property(client, property_id)
    if not prop:
        return {"needs_setup": "provide property_id or a client with ga4_property_id in clients.json"}
    try:
        return _ga4_report(prop, ["sessionDefaultChannelGroup", "sessionSource"],
                           ["sessions", "totalUsers", "conversions"],
                           "%ddaysAgo" % days, "today", limit)
    except RuntimeError as e:
        return {"needs_setup": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"error": "GA4 API error: " + str(e)}


@mcp.tool()
def ga4_top_pages(property_id: str | None = None, days: int = 28, limit: int = 25,
                  client: str | None = None) -> dict:
    """GA4 most-viewed pages by views and users over N days. Target a property by
    property_id or one `client` from clients.json."""
    prop = _ga4_property(client, property_id)
    if not prop:
        return {"needs_setup": "provide property_id or a client with ga4_property_id in clients.json"}
    try:
        return _ga4_report(prop, ["pagePath", "pageTitle"],
                           ["screenPageViews", "totalUsers"],
                           "%ddaysAgo" % days, "today", limit)
    except RuntimeError as e:
        return {"needs_setup": str(e)}
    except Exception as e:  # noqa: BLE001
        return {"error": "GA4 API error: " + str(e)}


# ==== clients: multi-account (granular + rollup) ===========================

@mcp.tool()
def list_clients() -> dict:
    """List configured clients and which platforms each has an account id for.
    Clients live in clients.json (template: clients.example.json). Pass a client
    name to any reporting tool's `client` arg to target it."""
    reg = _load_clients()
    clients = reg.get("clients", {}) or {}
    out = [{"client": name, "label": rec.get("label", name),
            "google_ads": bool(rec.get("google_ads_customer_id")),
            "meta": bool(rec.get("meta_ad_account_id")),
            "ga4": bool(rec.get("ga4_property_id"))}
           for name, rec in clients.items()]
    return {"default": reg.get("default"), "count": len(out), "clients": out}


@mcp.tool()
def add_client(name: str, label: str | None = None, google_ads_customer_id: str = "",
               meta_ad_account_id: str = "", ga4_property_id: str = "",
               make_default: bool = False) -> dict:
    """Add or update a client in clients.json with its per-platform account ids.
    Any id left blank is not set for that platform. The first client added (or
    make_default=true) becomes the default used when no `client` is passed."""
    reg = _load_clients()
    reg.setdefault("clients", {})
    rec = reg["clients"].get(name, {})
    rec["label"] = label or rec.get("label") or name
    if google_ads_customer_id:
        rec["google_ads_customer_id"] = google_ads_customer_id.replace("-", "")
    if meta_ad_account_id:
        rec["meta_ad_account_id"] = meta_ad_account_id
    if ga4_property_id:
        rec["ga4_property_id"] = str(ga4_property_id).replace("properties/", "")
    reg["clients"][name] = rec
    if make_default or not reg.get("default"):
        reg["default"] = name
    _save_clients(reg)
    return {"saved": name, "record": rec, "default": reg.get("default")}


def _ads_account_totals(days: int, customer_id: str) -> dict:
    start, end = _date_range(days)
    gaql = ("SELECT metrics.cost_micros, metrics.clicks, metrics.conversions "
            "FROM customer WHERE segments.date BETWEEN '%s' AND '%s'" % (start, end))
    r = ads_query(gaql, customer_id=customer_id, limit=1)
    if "rows" not in r:
        return {"ads_error": r.get("needs_setup") or r.get("error")}
    cost = clicks = conv = 0.0
    for row in r["rows"]:
        m = row.get("metrics", {})
        cost += int(m.get("costMicros", 0) or 0) / 1_000_000
        clicks += int(m.get("clicks", 0) or 0)
        conv += float(m.get("conversions", 0) or 0)
    return {"ads_cost": round(cost, 2), "ads_clicks": int(clicks), "ads_conversions": round(conv, 1)}


def _meta_account_totals(days: int, ad_account_id: str) -> dict:
    acct = str(ad_account_id) if str(ad_account_id).startswith("act_") else "act_" + str(ad_account_id)
    r = meta_insights(object_id=acct, level="account", days=days, fields="spend,clicks,impressions")
    if "insights" not in r:
        return {"meta_error": r.get("needs_setup") or r.get("error")}
    spend = clicks = 0.0
    for row in r["insights"]:
        spend += float(row.get("spend", 0) or 0)
        clicks += int(row.get("clicks", 0) or 0)
    return {"meta_spend": round(spend, 2), "meta_clicks": int(clicks)}


def _ga4_totals(days: int, property_id: str) -> dict:
    r = ga4_run_report(property_id=property_id, days=days, dimensions=[],
                       metrics=["sessions", "conversions"], limit=1)
    if "rows" not in r:
        return {"ga4_error": r.get("needs_setup") or r.get("error")}
    sess = conv = 0.0
    for row in r["rows"]:
        sess += int(row.get("sessions", 0) or 0)
        conv += float(row.get("conversions", 0) or 0)
    return {"ga4_sessions": int(sess), "ga4_conversions": round(conv, 1)}


@mcp.tool()
def clients_overview(days: int = 30, clients: list[str] | None = None) -> dict:
    """Granular per-client KPIs across all platforms PLUS a rolled-up total. For
    each client it pulls Google Ads (cost, clicks, conversions), Meta (spend,
    clicks), and GA4 (sessions, conversions) for the last N days using that
    client's account ids from clients.json. A platform a client has not connected
    shows an *_error note instead of a number. Pass `clients` to limit the set."""
    reg = _load_clients().get("clients", {}) or {}
    names = clients or list(reg.keys())
    if not names:
        return {"needs_setup": "no clients defined. Use add_client or edit clients.json (see clients.example.json)."}
    rows = []
    roll = {"ads_cost": 0.0, "ads_clicks": 0, "ads_conversions": 0.0,
            "meta_spend": 0.0, "meta_clicks": 0, "ga4_sessions": 0, "ga4_conversions": 0.0}
    for name in names:
        rec = reg.get(name, {})
        row = {"client": name, "label": rec.get("label", name)}
        if rec.get("google_ads_customer_id"):
            row.update(_ads_account_totals(days, rec["google_ads_customer_id"]))
        if rec.get("meta_ad_account_id"):
            row.update(_meta_account_totals(days, rec["meta_ad_account_id"]))
        if rec.get("ga4_property_id"):
            row.update(_ga4_totals(days, rec["ga4_property_id"]))
        for k in roll:
            if isinstance(row.get(k), (int, float)):
                roll[k] += row[k]
        rows.append(row)
    roll = {k: (round(v, 2) if isinstance(v, float) else v) for k, v in roll.items()}
    return {"days": days, "per_client": rows, "rollup": roll}


# ==== setup / health check ================================================

def _has_module(mod: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(mod) is not None
    except Exception:  # noqa: BLE001
        return False


def _platform_status(live: bool = False) -> dict:
    """Per-platform readiness: library installed, credentials present, and (if
    live) a real ping. The visibility-of-status surface the setup flow needs."""
    ga_need = ["GOOGLE_ADS_DEVELOPER_TOKEN", "GOOGLE_ADS_CLIENT_ID",
               "GOOGLE_ADS_CLIENT_SECRET", "GOOGLE_ADS_REFRESH_TOKEN"]
    ga_missing = [k for k in ga_need if not os.environ.get(k)]
    ga_cust = bool(os.environ.get("GOOGLE_ADS_CUSTOMER_ID") or os.environ.get("GOOGLE_ADS_LOGIN_CUSTOMER_ID"))
    ga = {"library_installed": _has_module("google.ads.googleads"),
          "missing_env": ga_missing, "customer_id_set": ga_cust}
    ga["ready"] = ga["library_installed"] and not ga_missing and ga_cust
    if not ga["ready"]:
        ga["next_step"] = ("pip install google-ads" if not ga["library_installed"]
                           else ("set " + ", ".join(ga_missing)) if ga_missing
                           else "set GOOGLE_ADS_CUSTOMER_ID")

    meta = {"token_present": bool(os.environ.get("META_ACCESS_TOKEN"))}
    meta["ready"] = meta["token_present"]
    if not meta["ready"]:
        meta["next_step"] = "set META_ACCESS_TOKEN"

    cred = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    ga4 = {"library_installed": _has_module("google.analytics.data_v1beta"),
           "credentials_path_set": bool(cred),
           "credentials_file_exists": bool(cred and os.path.exists(cred))}
    ga4["ready"] = ga4["library_installed"] and ga4["credentials_file_exists"]
    if not ga4["ready"]:
        ga4["next_step"] = ("pip install google-analytics-data" if not ga4["library_installed"]
                            else "set GOOGLE_APPLICATION_CREDENTIALS to an existing service-account json")

    pyt = _has_module("pytrends")
    status = {
        "keyword_no_auth": {"ready": True, "tools": ["autocomplete_suggestions", "cluster_keywords"]},
        "trends": {"ready": pyt, "next_step": None if pyt else "pip install pytrends"},
        "google_ads": ga, "meta_ads": meta, "ga4": ga4,
    }
    if live:
        if ga["ready"]:
            r = list_ads_accounts()
            ga["live_check"] = ("ok (%d accounts)" % len(r["accounts"])) if "accounts" in r else r.get("error")
        if meta["ready"]:
            r = meta_list_ad_accounts()
            ga_ok = "accounts" in r
            meta["live_check"] = ("ok (%d accounts)" % len(r["accounts"])) if ga_ok else r.get("error")
        if ga4["ready"]:
            ga4["live_check"] = "configured (call ga4_run_report with a property_id to confirm)"
    return status


@mcp.tool()
def setup_check(live: bool = False) -> dict:
    """Report which platforms are configured and ready (keyword research, trends,
    Google Ads, Meta, GA4) and the next step for any that are not. Pass live=true
    to also ping the configured platforms (list their accounts) to confirm the
    credentials actually work. Run this first when setting up."""
    return _platform_status(live)


if __name__ == "__main__":
    mcp.run()
