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

  SEARCH CONSOLE (organic search; Search Console API, same key as GA4)
    gsc_top_queries / gsc_top_pages / gsc_search_analytics / gsc_list_sites
    gsc_inspect_url             URL Inspection: indexed? coverage, last crawl
    gsc_list_sitemaps / gsc_submit_sitemap

  SEO / SITE (no auth; httpx + beautifulsoup4)
    seo_audit / pagespeed       on-page audit; Lighthouse scores + Core Web Vitals
    http_check                  redirect chain, HTTPS, security headers, timing
    content_analysis            Flesch readability, keyword density, outline
    validate_schema             JSON-LD structured-data validation
    robots_sitemap              robots.txt rules + sitemap URL discovery
    crawl_site                  multi-page crawl + aggregated issues
    check_links                 broken-link checker
    seo_score                   one 0-100 health score + grade

Auth'd tools return a clear setup error until their credentials are configured;
the no-auth tools run with no setup. Run: python server.py  (stdio transport).
"""
from __future__ import annotations

import datetime
import json
import os
import re
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
_UA = "Mozilla/5.0 (compatible; marketing-mcp/1.0; +https://github.com/Jluethke/marketing-mcp)"


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


# ---- keyword helpers: locations, intent, CSV ------------------------------

def _chunks(seq, n):
    seq = list(seq)
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


# Commercial / transactional intent markers vs informational ones. A keyword's
# intent score is (high markers) minus (low markers); higher means more likely to
# convert, which is what "high intent" means when picking keywords to bid on.
_INTENT_HIGH = ("buy", "price", "pricing", "cost", "quote", "hire", "near me",
                "for sale", "service", "services", "company", "companies", "agency",
                "consultant", "best", "top", "cheap", "affordable", "deal", "discount",
                "review", "reviews", "vs", "alternative", "software", "tool", "platform",
                "solution", "provider", "contractor", "installer", "repair", "emergency",
                "book", "order", "shop", "store", "rental", "rent", "lease", "estimate")
_INTENT_LOW = ("what is", "how to", "why", "meaning", "definition", "examples",
               "ideas", "diy", "tutorial", "guide", "learn", "history", "vs.")


def _intent_score(kw: str) -> int:
    t = kw.lower()
    return sum(1 for m in _INTENT_HIGH if m in t) - sum(1 for m in _INTENT_LOW if m in t)


def _priority(volume, intent, comp_index) -> float:
    """Rank weight: search volume scaled up by commercial intent, lightly
    discounted by competition. Sorting by this surfaces high-intent keywords that
    are getting volume."""
    comp = (comp_index or 0) / 100.0
    return round((volume or 0) * (1 + max(0, intent)) * (1.0 - 0.3 * comp), 1)


def _resolve_geo_targets(client, locations, country_code="US"):
    """Map location items (each a numeric geo id, or a place name like
    'Austin, Texas') to geoTargetConstants resource names. Returns
    (resource_names, human) where human lists the resolved name/id/reach per place."""
    res, human, names = [], [], []
    for loc in locations:
        s = str(loc).strip()
        if not s:
            continue
        if s.isdigit():
            res.append("geoTargetConstants/" + s)
            human.append({"id": s, "name": s, "type": "id"})
        else:
            names.append(s)
    if names:
        svc = client.get_service("GeoTargetConstantService")
        req = client.get_type("SuggestGeoTargetConstantsRequest")
        req.locale = "en"
        req.country_code = country_code
        req.location_names.names.extend(names)
        resp = svc.suggest_geo_target_constants(request=req)
        best = {}  # one best match per requested name (highest reach)
        for s in resp.geo_target_constant_suggestions:
            key = s.search_term or s.geo_target_constant.name
            if key not in best or s.reach > best[key].reach:
                best[key] = s
        for s in best.values():
            g = s.geo_target_constant
            res.append(g.resource_name)
            human.append({"id": g.resource_name.split("/")[-1], "name": g.name,
                          "type": g.target_type, "country": g.country_code, "reach": s.reach})
    return res, human


def _geo_targets_for(client, geo, locations, location_set, country_code):
    """Resolve the geo targets for a keyword call from a saved location_set and/or
    an explicit locations list, else fall back to the single `geo`."""
    names = []
    if location_set:
        ls = _load_locsets().get("sets", {}).get(location_set, {})
        names += list(ls.get("locations", []))
        country_code = ls.get("country_code", country_code)
    if locations:
        names += list(locations)
    if names:
        return _resolve_geo_targets(client, names, country_code)
    gid = _GEO.get(str(geo).upper(), str(geo))
    return [_geo_res(geo)], [{"id": gid, "name": str(geo), "type": "geo"}]


_LOCSETS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "location_sets.json")


def _load_locsets() -> dict:
    try:
        d = json.load(open(_LOCSETS_PATH, encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _save_locsets(d: dict) -> None:
    json.dump(d, open(_LOCSETS_PATH, "w", encoding="utf-8"), indent=2, ensure_ascii=False)


# ==== KEYWORD RESEARCH =====================================================

@mcp.tool()
def keyword_ideas(seed_keywords: list[str] | None = None, page_url: str | None = None,
                  geo: str = "US", language: str = "en", limit: int = 200,
                  include_adult: bool = False, locations: list[str] | None = None,
                  location_set: str | None = None, country_code: str = "US") -> dict:
    """Keyword ideas from seed keywords and/or a landing-page URL, with average
    monthly searches, competition, and top-of-page bid range. Target one country
    via `geo`, or many specific places via `locations` (town/city/state names or
    geo ids) or a saved `location_set`. Without active ad spend, volumes come back
    as Google's coarse ranges, not exact numbers."""
    try:
        client = _ads_client()
        cid = _customer_id()
    except RuntimeError as e:
        return {"needs_setup": str(e)}
    svc = client.get_service("KeywordPlanIdeaService")
    req = client.get_type("GenerateKeywordIdeasRequest")
    req.customer_id = cid
    req.language = _lang_res(language)
    try:
        geo_targets, _h = _geo_targets_for(client, geo, locations, location_set, country_code)
    except Exception as e:  # noqa: BLE001
        return {"error": "Google Ads API error (locations): " + str(e)}
    for g in geo_targets:
        req.geo_target_constants.append(g)
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
                               language: str = "en", locations: list[str] | None = None,
                               location_set: str | None = None,
                               country_code: str = "US") -> dict:
    """Historical monthly search volume (12-month series), competition score, and
    bid range for a specific list of keywords. Target one country via `geo`, or
    many specific places via `locations` (names or ids) or a saved `location_set`."""
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
    try:
        geo_targets, _h = _geo_targets_for(client, geo, locations, location_set, country_code)
    except Exception as e:  # noqa: BLE001
        return {"error": "Google Ads API error (locations): " + str(e)}
    for g in geo_targets:
        req.geo_target_constants.append(g)
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
def resolve_locations(location_names: list[str], country_code: str = "US") -> dict:
    """Resolve place names (towns, cities, counties, states) to Google Ads geo
    target ids with their reach, so you can target specific areas instead of the
    whole country. Pass the returned ids (or the names) to the keyword tools'
    `locations` arg, or save them with add_location_set."""
    try:
        client = _ads_client()
        _customer_id()
    except RuntimeError as e:
        return {"needs_setup": str(e)}
    try:
        _rn, human = _resolve_geo_targets(client, location_names, country_code)
    except Exception as e:  # noqa: BLE001
        return {"error": "Google Ads API error: " + str(e)}
    return {"count": len(human), "locations": human}


@mcp.tool()
def add_location_set(name: str, locations: list[str], country_code: str = "US") -> dict:
    """Save a reusable named set of target locations (town/city/state names or geo
    ids), so you can pass location_set='<name>' to the keyword tools instead of
    re-typing the list every time. Stored in location_sets.json (gitignored)."""
    d = _load_locsets()
    d.setdefault("sets", {})
    items = [str(x).strip() for x in (locations or []) if str(x).strip()]
    d["sets"][name] = {"locations": items, "country_code": country_code}
    _save_locsets(d)
    return {"saved": name, "count": len(items), "locations": items}


@mcp.tool()
def list_location_sets() -> dict:
    """List the saved location sets (see add_location_set)."""
    sets = _load_locsets().get("sets", {})
    return {"count": len(sets),
            "sets": {k: {"count": len(v.get("locations", [])),
                         "country_code": v.get("country_code", "US"),
                         "locations": v.get("locations", [])}
                     for k, v in sets.items()}}


@mcp.tool()
def keyword_research(seed_keywords: list[str] | None = None, keywords: list[str] | None = None,
                     locations: list[str] | None = None, location_set: str | None = None,
                     geo: str = "US", language: str = "en", country_code: str = "US",
                     limit: int = 500, min_searches: int = 0) -> dict:
    """Bulk keyword research in one call, the whole keyword-planner workflow without
    leaving chat. Expand `seed_keywords` into ideas and/or pull metrics for an
    explicit `keywords` list, across many places at once (`locations` names/ids or
    a saved `location_set`, else `geo`), then rank by search volume and commercial
    intent. Returns decision-ready structured rows (each with avg_monthly_searches,
    competition, intent_score, and a priority that floats the high-intent keywords
    getting volume to the top), so you decide in the same turn, no CSV export or
    upload. Chunks under the Google Ads 20-seed cap, so pass a long list at once
    instead of entering keywords one at a time."""
    try:
        client = _ads_client()
        cid = _customer_id()
    except RuntimeError as e:
        return {"needs_setup": str(e)}
    try:
        geo_targets, human = _geo_targets_for(client, geo, locations, location_set, country_code)
    except Exception as e:  # noqa: BLE001
        return {"error": "Google Ads API error (locations): " + str(e)}
    svc = client.get_service("KeywordPlanIdeaService")
    net = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH
    rows: dict = {}
    try:
        for chunk in _chunks([k for k in (keywords or []) if k], 1000):
            req = client.get_type("GenerateKeywordHistoricalMetricsRequest")
            req.customer_id = cid
            req.keywords.extend(chunk)
            req.language = _lang_res(language)
            for g in geo_targets:
                req.geo_target_constants.append(g)
            req.keyword_plan_network = net
            for r in svc.generate_keyword_historical_metrics(request=req).results:
                m = r.keyword_metrics
                rows[r.text.lower()] = {
                    "keyword": r.text, "avg_monthly_searches": m.avg_monthly_searches,
                    "competition": m.competition.name, "competition_index": m.competition_index,
                    "low_bid": _dollars(m.low_top_of_page_bid_micros),
                    "high_bid": _dollars(m.high_top_of_page_bid_micros)}
        for chunk in _chunks([s for s in (seed_keywords or []) if s], 20):
            req = client.get_type("GenerateKeywordIdeasRequest")
            req.customer_id = cid
            req.language = _lang_res(language)
            for g in geo_targets:
                req.geo_target_constants.append(g)
            req.keyword_plan_network = net
            req.keyword_seed.keywords.extend(chunk)
            for idea in svc.generate_keyword_ideas(request=req):
                k = idea.text.lower()
                if k in rows:
                    continue
                m = idea.keyword_idea_metrics
                rows[k] = {
                    "keyword": idea.text, "avg_monthly_searches": m.avg_monthly_searches,
                    "competition": m.competition.name, "competition_index": m.competition_index,
                    "low_bid": _dollars(m.low_top_of_page_bid_micros),
                    "high_bid": _dollars(m.high_top_of_page_bid_micros)}
                if len(rows) >= limit * 4:
                    break
    except Exception as e:  # noqa: BLE001
        return {"error": "Google Ads API error: " + str(e)}
    out = []
    for r in rows.values():
        vol = r["avg_monthly_searches"] or 0
        if vol < min_searches:
            continue
        intent = _intent_score(r["keyword"])
        r = dict(r)
        r["intent_score"] = intent
        r["priority"] = _priority(vol, intent, r["competition_index"])
        out.append(r)
    out.sort(key=lambda x: (-x["priority"], -(x["avg_monthly_searches"] or 0)))
    out = out[:limit]
    return {"locations": human, "count": len(out), "keywords": out}


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


# ==== SITE / SEO (no auth; PageSpeed is a free Google API) ==================

@mcp.tool()
def seo_audit(url: str) -> dict:
    """On-page SEO audit of a URL (no credentials). Fetches the page and reports
    title, meta description, headings, word count, canonical, robots, open-graph
    and twitter tags, JSON-LD schema presence, images missing alt text, internal
    and external link counts, and a list of issues found."""
    try:
        r, soup = _fetch_soup(url)
    except ImportError:
        return {"error": "beautifulsoup4 not installed. Run: pip install beautifulsoup4"}
    except Exception as e:  # noqa: BLE001
        return {"error": "fetch failed: " + str(e)}
    return _page_audit(r, soup)


def _fetch_soup(url: str):
    """Fetch a URL and parse the HTML. Returns (response, soup). Raises ImportError
    if beautifulsoup4 is missing, or a network error, so callers surface a clean
    message. Shared by the on-page tools below."""
    import httpx
    from bs4 import BeautifulSoup
    r = httpx.get(url, timeout=20.0, follow_redirects=True,
                  headers={"User-Agent": _UA})
    return r, BeautifulSoup(r.text, "html.parser")


def _page_audit(r, soup) -> dict:
    """On-page audit of an already-fetched page; returns the seo_audit payload.
    Factored so seo_audit, crawl_site, and seo_score share one auditor."""
    from urllib.parse import urlparse

    def meta(name=None, prop=None):
        t = soup.find("meta", attrs={"name": name} if name else {"property": prop})
        return (t.get("content") or "").strip() if t and t.get("content") else None

    title = soup.title.string.strip() if (soup.title and soup.title.string) else None
    desc = meta(name="description")
    h1 = [h.get_text(strip=True) for h in soup.find_all("h1")]
    words = len(soup.get_text(" ", strip=True).split())
    canon = soup.find("link", rel="canonical")
    canonical = canon.get("href") if canon else None
    imgs = soup.find_all("img")
    imgs_no_alt = sum(1 for i in imgs if not (i.get("alt") or "").strip())
    host = urlparse(str(r.url)).netloc
    internal = external = 0
    for a in soup.find_all("a", href=True):
        h = a["href"]
        if h.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        netloc = urlparse(h).netloc
        if netloc in ("", host):
            internal += 1
        else:
            external += 1
    issues = []
    if not title:
        issues.append("missing <title>")
    elif len(title) > 60:
        issues.append("title too long (%d chars; aim <=60)" % len(title))
    elif len(title) < 15:
        issues.append("title very short (%d chars)" % len(title))
    if not desc:
        issues.append("missing meta description")
    elif len(desc) > 160:
        issues.append("meta description too long (%d chars; aim <=160)" % len(desc))
    if len(h1) == 0:
        issues.append("no H1")
    elif len(h1) > 1:
        issues.append("multiple H1s (%d)" % len(h1))
    if words < 300:
        issues.append("thin content (%d words)" % words)
    if not canonical:
        issues.append("no canonical link")
    if imgs_no_alt:
        issues.append("%d image(s) missing alt text" % imgs_no_alt)
    if not meta(prop="og:title"):
        issues.append("no open-graph tags")
    return {
        "url": str(r.url), "status_code": r.status_code,
        "title": title, "title_length": len(title) if title else 0,
        "meta_description": desc, "meta_description_length": len(desc) if desc else 0,
        "h1": h1, "h2_count": len(soup.find_all("h2")), "word_count": words,
        "canonical": canonical, "robots": meta(name="robots"),
        "lang": soup.html.get("lang") if soup.html else None,
        "has_viewport": bool(meta(name="viewport")),
        "open_graph": bool(meta(prop="og:title")),
        "twitter_card": bool(meta(name="twitter:card")),
        "schema_jsonld_blocks": len(soup.find_all("script", attrs={"type": "application/ld+json"})),
        "images": len(imgs), "images_missing_alt": imgs_no_alt,
        "internal_links": internal, "external_links": external,
        "issues": issues,
    }


@mcp.tool()
def pagespeed(url: str, strategy: str = "mobile") -> dict:
    """Google PageSpeed Insights (Lighthouse) for a URL: performance, SEO,
    accessibility, and best-practices scores (0-100) plus Core Web Vitals
    (LCP, CLS, TBT, INP). strategy = mobile or desktop. No credentials; set
    PAGESPEED_API_KEY for higher quota."""
    import httpx
    params = [("url", url), ("strategy", strategy)]
    for c in ("performance", "seo", "accessibility", "best-practices"):
        params.append(("category", c))
    key = os.environ.get("PAGESPEED_API_KEY")
    if key:
        params.append(("key", key))
    try:
        d = httpx.get("https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
                      params=params, timeout=60.0).json()
    except Exception as e:  # noqa: BLE001
        return {"error": "pagespeed request failed: " + str(e)}
    if "error" in d:
        return {"error": "PageSpeed API error: " + str(d["error"].get("message", d["error"]))}
    lh = d.get("lighthouseResult", {})
    scores = {k: round((v.get("score") or 0) * 100) for k, v in lh.get("categories", {}).items()}
    audits = lh.get("audits", {})

    def disp(aid):
        return audits.get(aid, {}).get("displayValue")

    cwv = {"LCP": disp("largest-contentful-paint"), "CLS": disp("cumulative-layout-shift"),
           "TBT": disp("total-blocking-time"), "INP": disp("interaction-to-next-paint"),
           "FCP": disp("first-contentful-paint"), "speed_index": disp("speed-index")}
    field = {}
    for k, label in (("LARGEST_CONTENTFUL_PAINT_MS", "LCP"), ("CUMULATIVE_LAYOUT_SHIFT_SCORE", "CLS"),
                     ("INTERACTION_TO_NEXT_PAINT", "INP")):
        m = d.get("loadingExperience", {}).get("metrics", {}).get(k)
        if m:
            field[label] = m.get("category")
    return {"url": url, "strategy": strategy, "scores": scores,
            "core_web_vitals": cwv, "field_data_real_users": field}


@mcp.tool()
def http_check(url: str) -> dict:
    """Technical health check for a URL (no credentials): the redirect chain, final
    status, HTTPS enforcement, key security headers, response time, server, and any
    mixed content (http resources loaded on an https page). Complements seo_audit
    (content) and pagespeed (speed)."""
    import httpx
    from urllib.parse import urljoin, urlparse
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return {"error": "beautifulsoup4 not installed. Run: pip install beautifulsoup4"}
    chain, cur, elapsed_ms, final = [], url, 0.0, None
    try:
        with httpx.Client(timeout=20.0, follow_redirects=False,
                          headers={"User-Agent": _UA}) as client:
            for _ in range(10):
                resp = client.get(cur)
                elapsed_ms += resp.elapsed.total_seconds() * 1000
                chain.append({"url": cur, "status": resp.status_code})
                loc = resp.headers.get("location")
                if resp.is_redirect and loc:
                    cur = urljoin(cur, loc)
                    continue
                final = resp
                break
    except Exception as e:  # noqa: BLE001
        return {"error": "fetch failed: " + str(e)}
    if final is None:
        return {"error": "too many redirects (>10)", "redirect_chain": chain}
    h = {k.lower(): v for k, v in final.headers.items()}
    is_https = urlparse(cur).scheme == "https"
    https_redirect = None
    if urlparse(url).scheme == "http":
        https_redirect = any(urlparse(c["url"]).scheme == "https" for c in chain)
    sec = {
        "strict_transport_security": h.get("strict-transport-security"),
        "content_security_policy": bool(h.get("content-security-policy")),
        "x_content_type_options": h.get("x-content-type-options"),
        "x_frame_options": h.get("x-frame-options"),
        "referrer_policy": h.get("referrer-policy"),
    }
    mixed = []
    if is_https:
        try:
            soup = BeautifulSoup(final.text, "html.parser")
            for tag, attr in (("img", "src"), ("script", "src"), ("link", "href"),
                              ("iframe", "src"), ("source", "src")):
                for el in soup.find_all(tag):
                    v = (el.get(attr) or "").strip()
                    if v.startswith("http://"):
                        mixed.append(v)
        except Exception:  # noqa: BLE001
            pass
    issues = []
    if not is_https:
        issues.append("not served over HTTPS")
    if urlparse(url).scheme == "http" and not https_redirect:
        issues.append("http does not redirect to https")
    if is_https and not sec["strict_transport_security"]:
        issues.append("no HSTS (Strict-Transport-Security) header")
    if not sec["x_content_type_options"]:
        issues.append("no X-Content-Type-Options header")
    if not sec["x_frame_options"] and not sec["content_security_policy"]:
        issues.append("no clickjacking protection (X-Frame-Options or CSP)")
    if mixed:
        issues.append("%d mixed-content (http) resource(s) on an https page" % len(mixed))
    if len(chain) > 2:
        issues.append("redirect chain has %d hops" % (len(chain) - 1))
    return {
        "url": url, "final_url": cur, "status_code": final.status_code,
        "https": is_https, "http_to_https_redirect": https_redirect,
        "redirect_chain": chain, "response_time_ms": round(elapsed_ms, 1),
        "server": h.get("server"), "content_type": h.get("content-type"),
        "security_headers": sec, "mixed_content": mixed[:20],
        "mixed_content_count": len(mixed), "issues": issues,
    }


_STOPWORDS = set("a an and are as at be by for from has have in is it its of on or "
                 "that the to was were will with this you your we our they their he "
                 "she his her not but if then so do does can could would should i "
                 "all also more most other some such no only own same than too very".split())


def _syllables(word: str) -> int:
    word = re.sub(r"[^a-z]", "", word.lower())
    if not word:
        return 0
    n = len(re.findall(r"[aeiouy]+", word))
    if word.endswith("e") and n > 1:
        n -= 1
    return max(1, n)


@mcp.tool()
def content_analysis(url: str, focus_keyword: str | None = None) -> dict:
    """Readability and content analysis of a URL (no credentials): Flesch reading
    ease, word and sentence counts, top keyword density, the heading outline, and a
    thin-content flag. Pass focus_keyword to also get that term's density and where
    it appears (title, H1, first paragraph, URL)."""
    try:
        r, soup = _fetch_soup(url)
    except ImportError:
        return {"error": "beautifulsoup4 not installed. Run: pip install beautifulsoup4"}
    except Exception as e:  # noqa: BLE001
        return {"error": "fetch failed: " + str(e)}
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    title = soup.title.string.strip() if (soup.title and soup.title.string) else ""
    h1 = " ".join(h.get_text(" ", strip=True) for h in soup.find_all("h1"))
    first_p = soup.find("p")
    first_para = first_p.get_text(" ", strip=True) if first_p else ""
    text = (soup.body or soup).get_text(" ", strip=True)
    words_list = re.findall(r"[a-zA-Z']+", text.lower())
    word_count = len(words_list)
    sentences = max(1, len(re.findall(r"[.!?]+", text)))
    syl = sum(_syllables(w) for w in words_list) or 1
    flesch = (round(206.835 - 1.015 * (word_count / sentences) - 84.6 * (syl / word_count), 1)
              if word_count else None)

    def band(f):
        if f is None:
            return None
        for thr, lab in ((90, "very easy"), (70, "easy"), (60, "standard"),
                         (50, "fairly hard"), (30, "hard")):
            if f >= thr:
                return lab
        return "very hard"

    counts = Counter(w for w in words_list if w not in _STOPWORDS and len(w) > 2)
    density = ([{"term": t, "count": c, "density_pct": round(100 * c / word_count, 2)}
                for t, c in counts.most_common(15)] if word_count else [])
    outline = [{"level": int(h.name[1]), "text": h.get_text(" ", strip=True)}
               for h in soup.find_all(["h1", "h2", "h3", "h4"])]
    issues = []
    if word_count < 300:
        issues.append("thin content (%d words)" % word_count)
    if flesch is not None and flesch < 30:
        issues.append("hard to read (Flesch %.0f; aim 50+)" % flesch)
    out = {
        "url": str(r.url), "word_count": word_count, "sentence_count": sentences,
        "avg_words_per_sentence": round(word_count / sentences, 1) if word_count else 0,
        "flesch_reading_ease": flesch, "reading_level": band(flesch),
        "keyword_density": density, "heading_outline": outline, "issues": issues,
    }
    if focus_keyword:
        fk = focus_keyword.lower().strip()
        occ = text.lower().count(fk)
        u = str(r.url).lower()
        out["focus_keyword"] = {
            "term": focus_keyword, "occurrences": occ,
            "density_pct": round(100 * occ / word_count, 2) if word_count else 0,
            "in_title": fk in title.lower(), "in_h1": fk in h1.lower(),
            "in_first_paragraph": fk in first_para.lower(),
            "in_url": fk.replace(" ", "-") in u or fk.replace(" ", "") in u,
        }
    return out


_SCHEMA_RECOMMENDED = {
    "Organization": ["name", "url", "logo"],
    "LocalBusiness": ["name", "address", "telephone"],
    "Product": ["name", "image", "offers"],
    "Article": ["headline", "image", "datePublished", "author"],
    "NewsArticle": ["headline", "image", "datePublished", "author"],
    "BlogPosting": ["headline", "image", "datePublished", "author"],
    "BreadcrumbList": ["itemListElement"],
    "FAQPage": ["mainEntity"],
    "Event": ["name", "startDate", "location"],
    "Recipe": ["name", "recipeIngredient", "recipeInstructions"],
    "VideoObject": ["name", "thumbnailUrl", "uploadDate"],
    "Person": ["name"],
    "WebSite": ["name", "url"],
}


@mcp.tool()
def validate_schema(url: str) -> dict:
    """Parse and validate the JSON-LD structured data on a page (no credentials).
    Lists each schema block's @type, flags malformed JSON, and for common types
    (Organization, LocalBusiness, Product, Article, BreadcrumbList, FAQPage, Event,
    Recipe and more) reports recommended properties that are missing. seo_audit only
    counts schema blocks; this opens and checks them."""
    try:
        r, soup = _fetch_soup(url)
    except ImportError:
        return {"error": "beautifulsoup4 not installed. Run: pip install beautifulsoup4"}
    except Exception as e:  # noqa: BLE001
        return {"error": "fetch failed: " + str(e)}
    blocks = soup.find_all("script", attrs={"type": "application/ld+json"})
    items, invalid = [], 0

    def visit(node):
        if isinstance(node, list):
            for n in node:
                visit(n)
            return
        if not isinstance(node, dict):
            return
        if isinstance(node.get("@graph"), list):
            for n in node["@graph"]:
                visit(n)
        t = node.get("@type")
        if not t:
            return
        for ty in (t if isinstance(t, list) else [t]):
            rec = _SCHEMA_RECOMMENDED.get(ty, [])
            items.append({"type": ty,
                          "missing_recommended": [k for k in rec if k not in node],
                          "properties": sorted(k for k in node if not k.startswith("@"))})

    for b in blocks:
        raw = b.string or b.get_text() or ""
        try:
            visit(json.loads(raw))
        except Exception:  # noqa: BLE001
            invalid += 1
    issues = []
    if not blocks:
        issues.append("no JSON-LD structured data found")
    if invalid:
        issues.append("%d JSON-LD block(s) are not valid JSON" % invalid)
    for it in items:
        if it["missing_recommended"]:
            issues.append("%s missing: %s" % (it["type"], ", ".join(it["missing_recommended"])))
    return {"url": str(r.url), "jsonld_blocks": len(blocks), "invalid_blocks": invalid,
            "types_found": sorted({it["type"] for it in items}),
            "items": items, "issues": issues}


def _site_root(url: str) -> str:
    from urllib.parse import urlparse
    p = urlparse(url if "://" in url else "https://" + url)
    return "%s://%s" % (p.scheme or "https", p.netloc)


def _parse_robots(root: str):
    """Return (rules, sitemaps) for a site root. rules has disallow/allow path lists
    for the * user-agent; sitemaps is the list of declared Sitemap: URLs."""
    import httpx
    sitemaps, disallow, allow = [], [], []
    try:
        r = httpx.get(root + "/robots.txt", timeout=15.0, follow_redirects=True,
                      headers={"User-Agent": _UA})
        if r.status_code < 400:
            agent_star = False
            for line in r.text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                low = line.lower()
                if low.startswith("sitemap:"):
                    sitemaps.append(line.split(":", 1)[1].strip())
                elif low.startswith("user-agent:"):
                    agent_star = line.split(":", 1)[1].strip() == "*"
                elif agent_star and low.startswith("disallow:"):
                    disallow.append(line.split(":", 1)[1].strip())
                elif agent_star and low.startswith("allow:"):
                    allow.append(line.split(":", 1)[1].strip())
    except Exception:  # noqa: BLE001
        pass
    return {"disallow": disallow, "allow": allow}, sitemaps


def _parse_sitemap(xml_text):
    """Return (child_sitemaps, page_urls) from a sitemap body. A <sitemapindex>
    yields child sitemaps; a <urlset> yields page URLs."""
    import xml.etree.ElementTree as ET
    locs = []
    try:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except Exception:  # noqa: BLE001
        return [], []
    for el in root.iter():
        if el.tag.rsplit("}", 1)[-1] == "loc" and el.text:
            locs.append(el.text.strip())
    if root.tag.rsplit("}", 1)[-1] == "sitemapindex":
        return locs, []
    return [], locs


def _collect_sitemap_urls(root: str, declared_sitemaps, limit: int = 200):
    """Discover up to `limit` page URLs for a site from its sitemap(s), following
    one level of sitemap-index nesting. Returns (urls, info)."""
    import httpx
    queue = list(declared_sitemaps) or [root + "/sitemap.xml"]
    seen_sm, pages = set(), []
    info = {"sitemaps_read": [], "is_index": False}
    while queue and len(pages) < limit:
        sm = queue.pop(0)
        if sm in seen_sm:
            continue
        seen_sm.add(sm)
        try:
            r = httpx.get(sm, timeout=20.0, follow_redirects=True,
                          headers={"User-Agent": _UA})
            if r.status_code >= 400:
                continue
        except Exception:  # noqa: BLE001
            continue
        children, urls = _parse_sitemap(r.text)
        info["sitemaps_read"].append(sm)
        if children:
            info["is_index"] = True
            queue.extend(c for c in children if c not in seen_sm)
        for u in urls:
            if len(pages) >= limit:
                break
            pages.append(u)
    return pages, info


@mcp.tool()
def robots_sitemap(url: str) -> dict:
    """Fetch and parse robots.txt and the XML sitemap(s) for a site (no
    credentials). Reports the robots Disallow rules for all crawlers, any declared
    Sitemap: URLs, and for the sitemap the discovered page-URL count and a sample
    (follows a sitemap index one level). Pass any URL on the site; the root is
    derived."""
    root = _site_root(url)
    rules, declared = _parse_robots(root)
    pages, info = _collect_sitemap_urls(root, declared, limit=500)
    issues = []
    if not declared:
        issues.append("no Sitemap: directive in robots.txt")
    if not pages:
        issues.append("no sitemap URLs discovered (tried robots + /sitemap.xml)")
    return {
        "site": root, "robots_disallow": rules["disallow"], "robots_allow": rules["allow"],
        "declared_sitemaps": declared, "sitemaps_read": info["sitemaps_read"],
        "is_sitemap_index": info["is_index"], "discovered_url_count": len(pages),
        "sample_urls": pages[:25], "issues": issues,
    }


def _disallowed(path_url: str, disallow) -> bool:
    from urllib.parse import urlparse
    p = urlparse(path_url).path or "/"
    return any(d and p.startswith(d) for d in disallow)


@mcp.tool()
def crawl_site(start_url: str, max_pages: int = 20, use_sitemap: bool = True) -> dict:
    """Crawl up to max_pages pages of a site and audit each, then aggregate (no
    credentials). Seeds from the sitemap when available, otherwise follows internal
    links from start_url. Respects robots.txt Disallow for all crawlers. Returns a
    per-page row (status, title, words, issue count) and a site-wide rollup of the
    most common issues. The multi-page version of seo_audit."""
    from urllib.parse import urljoin, urlparse
    max_pages = max(1, min(int(max_pages), 100))
    root = _site_root(start_url)
    host = urlparse(root).netloc
    rules, declared = _parse_robots(root)
    disallow = rules["disallow"]
    seeds = []
    if use_sitemap:
        seeds, _ = _collect_sitemap_urls(root, declared, limit=max_pages * 3)
    queue = list(seeds) if seeds else [start_url]
    mode = "sitemap" if seeds else "link-follow"
    visited, rows, all_issues, errors = set(), [], Counter(), 0
    while queue and len(rows) < max_pages:
        u = queue.pop(0).split("#", 1)[0]
        if u in visited or urlparse(u).netloc not in ("", host) or _disallowed(u, disallow):
            continue
        visited.add(u)
        try:
            r, soup = _fetch_soup(u)
        except Exception:  # noqa: BLE001
            errors += 1
            rows.append({"url": u, "status_code": None, "error": "fetch failed"})
            continue
        a = _page_audit(r, soup)
        rows.append({"url": a["url"], "status_code": a["status_code"], "title": a["title"],
                     "word_count": a["word_count"], "issue_count": len(a["issues"]),
                     "issues": a["issues"]})
        for iss in a["issues"]:
            all_issues[re.sub(r"\d+", "N", iss)] += 1
        if mode == "link-follow":
            for tag in soup.find_all("a", href=True):
                nxt = urljoin(u, tag["href"]).split("#", 1)[0]
                if urlparse(nxt).netloc == host and nxt not in visited and len(queue) < max_pages * 4:
                    queue.append(nxt)
    return {
        "site": root, "seed_mode": mode, "pages_crawled": len(rows), "fetch_errors": errors,
        "common_issues": [{"issue": k, "pages": c} for k, c in all_issues.most_common()],
        "pages": rows,
    }


@mcp.tool()
def check_links(url: str, scope: str = "all", limit: int = 50) -> dict:
    """Check the links on a page for breakage (no credentials). Fetches the page,
    extracts up to `limit` unique links, requests each, and reports those that
    return 4xx/5xx or fail to connect. scope = all | internal | external."""
    import httpx
    from urllib.parse import urljoin, urlparse
    try:
        r, soup = _fetch_soup(url)
    except ImportError:
        return {"error": "beautifulsoup4 not installed. Run: pip install beautifulsoup4"}
    except Exception as e:  # noqa: BLE001
        return {"error": "fetch failed: " + str(e)}
    host = urlparse(str(r.url)).netloc
    seen_set, targets = set(), []
    for a in soup.find_all("a", href=True):
        h = a["href"]
        if h.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
            continue
        absu = urljoin(str(r.url), h).split("#", 1)[0]
        if not absu.startswith("http"):
            continue
        internal = urlparse(absu).netloc == host
        if (scope == "internal" and not internal) or (scope == "external" and internal):
            continue
        if absu in seen_set:
            continue
        seen_set.add(absu)
        targets.append((absu, internal))
        if len(targets) >= limit:
            break
    broken, checked = [], 0
    with httpx.Client(timeout=8.0, follow_redirects=True, headers={"User-Agent": _UA}) as client:
        for absu, internal in targets:
            checked += 1
            try:
                resp = client.head(absu)
                if resp.status_code >= 400:
                    resp = client.get(absu)  # some servers reject HEAD; confirm with GET
                code = resp.status_code
            except Exception as e:  # noqa: BLE001
                broken.append({"url": absu, "internal": internal, "status": None, "error": str(e)[:80]})
                continue
            if code >= 400:
                broken.append({"url": absu, "internal": internal, "status": code})
    return {"url": str(r.url), "scope": scope, "links_checked": checked,
            "broken_count": len(broken), "broken": broken}


@mcp.tool()
def seo_score(url: str) -> dict:
    """One 0-100 SEO health score and letter grade for a URL (no credentials),
    rolled up from the on-page audit, technical health (HTTPS, headers, redirects),
    and content readability. Returns the overall score, the grade, the three
    component sub-scores, and the top fixes. The single-number summary on top of
    seo_audit, http_check, and content_analysis."""
    on = seo_audit(url)
    if "error" in on:
        return on
    tech = http_check(url)
    con = content_analysis(url)
    onpage_issues = on.get("issues", [])
    tech_issues = tech.get("issues", []) if "error" not in tech else []
    con_issues = con.get("issues", []) if "error" not in con else []
    onpage = max(0, 100 - 8 * len(onpage_issues))
    technical = 100
    for iss in tech_issues:
        technical -= 25 if "https" in iss.lower() else 8
    technical = max(0, technical)
    content = 100
    if con.get("word_count", 300) < 300:
        content -= 25
    fl = con.get("flesch_reading_ease")
    if fl is not None and fl < 30:
        content -= 15
    content = max(0, content)
    overall = round(0.5 * onpage + 0.3 * technical + 0.2 * content)
    grade = ("A" if overall >= 90 else "B" if overall >= 80 else "C" if overall >= 70
             else "D" if overall >= 60 else "F")
    fixes = ["[%s] %s" % (label, iss)
             for label, lst in (("on-page", onpage_issues), ("technical", tech_issues),
                                ("content", con_issues)) for iss in lst]
    return {
        "url": on.get("url", url), "score": overall, "grade": grade,
        "components": {"onpage": onpage, "technical": technical, "content": content},
        "weights": {"onpage": 0.5, "technical": 0.3, "content": 0.2},
        "top_fixes": fixes[:12],
    }


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


@mcp.tool()
def meta_ad_library(search_terms: str | None = None, page_ids: list[str] | None = None,
                    countries: list[str] | None = None, active_status: str = "ACTIVE",
                    limit: int = 25) -> dict:
    """Search Meta's public Ad Library for running ads, by keyword (`search_terms`)
    or advertiser page id (`page_ids`). Returns the advertiser, creative text,
    platforms, run dates, and a snapshot url, for competitor ad intel. Uses
    META_ACCESS_TOKEN; `countries` defaults to ['US']. active_status =
    ACTIVE | INACTIVE | ALL. Coverage of non-political ads is limited by Meta to
    some regions and may require app identity verification."""
    if not search_terms and not page_ids:
        return {"error": "provide search_terms or page_ids"}
    params = {
        "ad_reached_countries": json.dumps(countries or ["US"]),
        "ad_active_status": active_status,
        "ad_type": "ALL",
        "fields": ("id,page_name,ad_creative_bodies,ad_creative_link_titles,"
                   "ad_creative_link_captions,publisher_platforms,"
                   "ad_delivery_start_time,ad_delivery_stop_time,ad_snapshot_url"),
        "limit": limit,
    }
    if search_terms:
        params["search_terms"] = search_terms
    if page_ids:
        params["search_page_ids"] = json.dumps([str(p) for p in page_ids])
    try:
        data = _meta_get("ads_archive", params)
    except RuntimeError as e:
        return {"needs_setup": str(e)}
    return {"count": len(data.get("data", [])), "ads": data.get("data", [])}


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


# ==== GOOGLE SEARCH CONSOLE (organic search) ===============================

def _gsc_service(write: bool = False):
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError:
        raise RuntimeError("google-api-python-client not installed. Run: pip install google-api-python-client")
    path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not path:
        raise RuntimeError("Set GOOGLE_APPLICATION_CREDENTIALS to a service-account json (the same key "
                           "as GA4) and add that service account to the Search Console property. "
                           "See README.md (Setup -> Search Console).")
    # readonly covers analytics + URL Inspection + sitemap listing; sitemap submit
    # needs the full webmasters scope (and the SA must be a full property user).
    scope = ("https://www.googleapis.com/auth/webmasters" if write
             else "https://www.googleapis.com/auth/webmasters.readonly")
    creds = service_account.Credentials.from_service_account_file(path, scopes=[scope])
    return build("searchconsole", "v1", credentials=creds, cache_discovery=False)


@mcp.tool()
def gsc_list_sites() -> dict:
    """List the sites the configured service account can read in Google Search
    Console. If empty, add the service-account email as a user on the property."""
    try:
        svc = _gsc_service()
    except RuntimeError as e:
        return {"needs_setup": str(e)}
    try:
        resp = svc.sites().list().execute()
    except Exception as e:  # noqa: BLE001
        return {"error": "Search Console API error: " + str(e)}
    return {"sites": [s.get("siteUrl") for s in resp.get("siteEntry", [])]}


@mcp.tool()
def gsc_search_analytics(site_url: str, days: int = 28, dimensions: list[str] | None = None,
                         limit: int = 100) -> dict:
    """Google Search Console performance for a verified site: clicks, impressions,
    CTR, and average position, grouped by `dimensions` (query, page, country,
    device, date) over the last N days. site_url is the exact property string,
    e.g. 'https://example.com/' or 'sc-domain:example.com'."""
    try:
        svc = _gsc_service()
    except RuntimeError as e:
        return {"needs_setup": str(e)}
    start, end = _date_range(days)
    dims = dimensions or ["query"]
    body = {"startDate": start, "endDate": end, "dimensions": dims, "rowLimit": limit}
    try:
        resp = svc.searchanalytics().query(siteUrl=site_url, body=body).execute()
    except Exception as e:  # noqa: BLE001
        return {"error": "Search Console API error: " + str(e)}
    rows = []
    for r in resp.get("rows", []):
        row = {dims[i]: r["keys"][i] for i in range(len(dims))}
        row.update({"clicks": r.get("clicks"), "impressions": r.get("impressions"),
                    "ctr": round(r.get("ctr", 0), 4), "position": round(r.get("position", 0), 1)})
        rows.append(row)
    return {"site": site_url, "days": days, "dimensions": dims, "count": len(rows), "rows": rows}


@mcp.tool()
def gsc_top_queries(site_url: str, days: int = 28, limit: int = 50) -> dict:
    """Top organic search queries bringing clicks and impressions to a site (Google
    Search Console), over the last N days."""
    return gsc_search_analytics(site_url, days, ["query"], limit)


@mcp.tool()
def gsc_top_pages(site_url: str, days: int = 28, limit: int = 50) -> dict:
    """Top landing pages by organic clicks and impressions (Google Search Console),
    over the last N days."""
    return gsc_search_analytics(site_url, days, ["page"], limit)


@mcp.tool()
def gsc_inspect_url(page_url: str, site_url: str | None = None) -> dict:
    """Google Search Console URL Inspection for one page: whether it is indexed, its
    coverage state, last crawl time, Googlebot crawl/robots state, the Google-chosen
    canonical, mobile usability, and rich-results status. site_url is the property
    the page belongs to (e.g. 'https://example.com/' or 'sc-domain:example.com'); if
    omitted it is derived from page_url. Same service account as the other gsc_*
    tools."""
    try:
        svc = _gsc_service()
    except RuntimeError as e:
        return {"needs_setup": str(e)}
    if not site_url:
        from urllib.parse import urlparse
        p = urlparse(page_url)
        site_url = "%s://%s/" % (p.scheme, p.netloc)
    try:
        resp = svc.urlInspection().index().inspect(
            body={"inspectionUrl": page_url, "siteUrl": site_url}).execute()
    except Exception as e:  # noqa: BLE001
        return {"error": "URL Inspection API error: " + str(e)}
    res = resp.get("inspectionResult", {})
    idx = res.get("indexStatusResult", {})
    mob = res.get("mobileUsabilityResult", {})
    rich = res.get("richResultsResult", {})
    return {
        "url": page_url, "site": site_url,
        "verdict": idx.get("verdict"), "coverage_state": idx.get("coverageState"),
        "indexing_state": idx.get("indexingState"), "robots_txt_state": idx.get("robotsTxtState"),
        "page_fetch_state": idx.get("pageFetchState"), "last_crawl_time": idx.get("lastCrawlTime"),
        "crawled_as": idx.get("crawledAs"), "google_canonical": idx.get("googleCanonical"),
        "user_canonical": idx.get("userCanonical"),
        "mobile_usable": mob.get("verdict"), "rich_results": rich.get("verdict"),
        "inspect_link": res.get("inspectionResultLink"),
    }


@mcp.tool()
def gsc_list_sitemaps(site_url: str) -> dict:
    """List the sitemaps submitted for a Search Console property, with each one's
    last-downloaded time, type, pending state, and warning/error counts. Same
    service account as the other gsc_* tools."""
    try:
        svc = _gsc_service()
    except RuntimeError as e:
        return {"needs_setup": str(e)}
    try:
        resp = svc.sitemaps().list(siteUrl=site_url).execute()
    except Exception as e:  # noqa: BLE001
        return {"error": "Search Console API error: " + str(e)}
    out = []
    for s in resp.get("sitemap", []):
        contents = s.get("contents") or []
        out.append({"path": s.get("path"), "last_downloaded": s.get("lastDownloaded"),
                    "type": s.get("type"), "is_pending": s.get("isPending"),
                    "is_sitemaps_index": s.get("isSitemapsIndex"),
                    "warnings": s.get("warnings"), "errors": s.get("errors"),
                    "submitted_urls": contents[0].get("submitted") if contents else None})
    return {"site": site_url, "count": len(out), "sitemaps": out}


@mcp.tool()
def gsc_submit_sitemap(site_url: str, sitemap_url: str) -> dict:
    """Submit a sitemap to Google Search Console for a property. The service account
    must be a full user (not restricted) on the property. sitemap_url is the full
    URL of the sitemap, e.g. 'https://example.com/sitemap.xml'."""
    try:
        svc = _gsc_service(write=True)
    except RuntimeError as e:
        return {"needs_setup": str(e)}
    try:
        svc.sitemaps().submit(siteUrl=site_url, feedpath=sitemap_url).execute()
    except Exception as e:  # noqa: BLE001
        return {"error": "Search Console API error (submit needs full-user permission): " + str(e)}
    return {"submitted": True, "site": site_url, "sitemap": sitemap_url}


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


# ==== connect from chat (no .env editing) ==================================

def _env_path() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")


def _write_env(updates: dict) -> None:
    """Merge key=value updates into the .env next to this server AND into the live
    process environment, so a credential set from chat persists for next time and
    takes effect immediately, without editing a file or restarting."""
    path = _env_path()
    lines, seen = [], set()
    if os.path.exists(path):
        for raw in open(path, encoding="utf-8").read().splitlines():
            key = raw.split("=", 1)[0].strip()
            if key in updates:
                lines.append("%s=%s" % (key, updates[key]))
                seen.add(key)
            else:
                lines.append(raw)
    for k, v in updates.items():
        if k not in seen:
            lines.append("%s=%s" % (k, v))
    open(path, "w", encoding="utf-8").write("\n".join(lines) + "\n")
    for k, v in updates.items():
        os.environ[k] = str(v)


def _mask(v: str) -> str:
    v = str(v)
    return ("*" * max(0, len(v) - 4) + v[-4:]) if len(v) > 4 else "****"


@mcp.tool()
def setup_instructions(platform: str | None = None) -> dict:
    """Plain-language, no-terminal setup you can do entirely in chat. Returns what
    to get from each platform and the exact phrase to say to connect it. Call with
    a platform (google_ads, meta, analytics, pagespeed) for one, or no argument for
    all. The .env file is written for you; you never edit it by hand."""
    steps = {
        "works_now": "seo_audit, autocomplete_suggestions, cluster_keywords, and trend_index "
                     "need no setup. pagespeed works too (a free key raises its quota).",
        "google_ads": [
            "In Google Ads -> Tools -> API Center, apply for a developer token (basic access; "
            "the account needs a payment method on file).",
            "In Google Cloud -> APIs & Services -> Credentials, create an OAuth client of type "
            "Desktop. Copy its client id and client secret.",
            "Say: 'connect google ads oauth' and paste the client id and client secret. A browser "
            "opens; approve with the Google account that has Ads access.",
            "Say: 'connect google ads' and paste your developer token and your 10-digit Ads "
            "customer id. Done.",
        ],
        "meta": [
            "At developers.facebook.com create an app, add the Marketing API, and generate an "
            "access token with the ads_read permission.",
            "Say: 'connect meta' and paste the access token.",
        ],
        "analytics": [
            "In Google Cloud create a service account and download its JSON key. Enable the "
            "Analytics Data API and the Search Console API on the project.",
            "Say: 'connect analytics' and paste the entire contents of the JSON key file.",
            "Add the service-account email it gives back as a Viewer on your GA4 property, and as "
            "a user on your Search Console property.",
        ],
        "pagespeed": [
            "Optional. Create a free API key in Google Cloud, then say: 'set pagespeed key' and "
            "paste it.",
        ],
    }
    if platform and platform in steps:
        return {platform: steps[platform]}
    return steps


@mcp.tool()
def connect_google_ads(developer_token: str, customer_id: str, client_id: str = "",
                       client_secret: str = "", refresh_token: str = "",
                       login_customer_id: str = "") -> dict:
    """Connect Google Ads from chat (no .env editing). Saves the credentials to the
    local .env, applies them immediately, and confirms by listing accounts. You can
    omit client_id/secret/refresh_token if you already ran connect_google_ads_oauth.
    customer_id is the 10-digit Ads account id."""
    up = {"GOOGLE_ADS_DEVELOPER_TOKEN": developer_token,
          "GOOGLE_ADS_CUSTOMER_ID": str(customer_id).replace("-", "")}
    if client_id:
        up["GOOGLE_ADS_CLIENT_ID"] = client_id
    if client_secret:
        up["GOOGLE_ADS_CLIENT_SECRET"] = client_secret
    if refresh_token:
        up["GOOGLE_ADS_REFRESH_TOKEN"] = refresh_token
    if login_customer_id:
        up["GOOGLE_ADS_LOGIN_CUSTOMER_ID"] = str(login_customer_id).replace("-", "")
    _write_env(up)
    chk = list_ads_accounts()
    ok = "accounts" in chk
    return {"saved": True, "developer_token": _mask(developer_token),
            "customer_id": up["GOOGLE_ADS_CUSTOMER_ID"], "verified": ok,
            "check": ("ok, %d accounts reachable" % len(chk["accounts"])) if ok
                     else chk.get("needs_setup") or chk.get("error")}


@mcp.tool()
def connect_google_ads_oauth(client_id: str, client_secret: str) -> dict:
    """Get the Google Ads refresh token by approving in a browser, with no terminal
    command. A browser window opens; approve with the Google account that has Ads
    access, and the client id, secret, and refresh token are saved to .env. Then
    call connect_google_ads with your developer token and customer id."""
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        return {"error": "google-auth-oauthlib not installed. Run: pip install google-auth-oauthlib"}
    try:
        flow = InstalledAppFlow.from_client_config(
            {"installed": {"client_id": client_id, "client_secret": client_secret,
                           "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                           "token_uri": "https://oauth2.googleapis.com/token",
                           "redirect_uris": ["http://localhost"]}},
            scopes=["https://www.googleapis.com/auth/adwords"])
        creds = flow.run_local_server(port=0, prompt="consent")
    except Exception as e:  # noqa: BLE001
        return {"error": "OAuth failed: " + str(e)}
    if not creds.refresh_token:
        return {"error": "No refresh token returned. Revoke the app's prior access and retry."}
    _write_env({"GOOGLE_ADS_CLIENT_ID": client_id, "GOOGLE_ADS_CLIENT_SECRET": client_secret,
                "GOOGLE_ADS_REFRESH_TOKEN": creds.refresh_token})
    return {"saved": True, "refresh_token": _mask(creds.refresh_token),
            "next": "say 'connect google ads' and paste your developer token and 10-digit customer id"}


@mcp.tool()
def connect_meta(access_token: str) -> dict:
    """Connect Meta Ads from chat (no .env editing). Saves the access token, applies
    it immediately, and confirms by listing ad accounts."""
    _write_env({"META_ACCESS_TOKEN": access_token})
    chk = meta_list_ad_accounts()
    ok = "accounts" in chk
    return {"saved": True, "token": _mask(access_token), "verified": ok,
            "check": ("ok, %d ad accounts reachable" % len(chk["accounts"])) if ok
                     else chk.get("needs_setup") or chk.get("error")}


@mcp.tool()
def connect_analytics(service_account_json: str) -> dict:
    """Connect GA4 and Search Console from chat by pasting the service-account JSON
    key contents (no file handling). Writes the key to a local file, points
    GOOGLE_APPLICATION_CREDENTIALS at it, and returns the service-account email to
    add as a Viewer on the GA4 property and a user on the Search Console property."""
    try:
        data = json.loads(service_account_json)
        email = data.get("client_email", "")
    except Exception as e:  # noqa: BLE001
        return {"error": "that does not look like valid service-account JSON: " + str(e)}
    if not email:
        return {"error": "no client_email in the JSON; paste the full service-account key file"}
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ga4-service-account.json")
    open(path, "w", encoding="utf-8").write(service_account_json)
    _write_env({"GOOGLE_APPLICATION_CREDENTIALS": path})
    return {"saved": True, "service_account_email": email,
            "next": "add %s as a Viewer on your GA4 property, and as a user on your Search "
                    "Console property" % email}


@mcp.tool()
def set_pagespeed_key(api_key: str) -> dict:
    """Save a free PageSpeed Insights API key from chat (raises the pagespeed quota)."""
    _write_env({"PAGESPEED_API_KEY": api_key})
    return {"saved": True, "key": _mask(api_key)}


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

    gsc_lib = _has_module("googleapiclient")
    gsc = {"library_installed": gsc_lib, "credentials_file_exists": bool(cred and os.path.exists(cred))}
    gsc["ready"] = gsc_lib and gsc["credentials_file_exists"]
    gsc["tools"] = ["gsc_top_queries", "gsc_top_pages", "gsc_search_analytics", "gsc_list_sites",
                    "gsc_inspect_url", "gsc_list_sitemaps", "gsc_submit_sitemap"]
    if not gsc["ready"]:
        gsc["next_step"] = ("pip install google-api-python-client" if not gsc_lib
                            else "set GOOGLE_APPLICATION_CREDENTIALS (same key as GA4) and add the "
                                 "service account to the Search Console property")

    bs4_ok = _has_module("bs4")
    pyt = _has_module("pytrends")
    status = {
        "keyword_no_auth": {"ready": True, "tools": ["autocomplete_suggestions", "cluster_keywords"]},
        "trends": {"ready": pyt, "next_step": None if pyt else "pip install pytrends"},
        "site_audit": {"ready": bs4_ok,
                       "tools": ["seo_audit", "pagespeed", "http_check", "content_analysis",
                                 "validate_schema", "robots_sitemap", "crawl_site", "check_links",
                                 "seo_score"],
                       "next_step": None if bs4_ok else "pip install beautifulsoup4"},
        "google_ads": ga, "meta_ads": meta, "ga4": ga4, "search_console": gsc,
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
