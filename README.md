# Marketing MCP

One MCP server that combines the full feature surface found across the public
Google Ads / Keyword Planner / Meta Ads / GA4 MCP servers, across three
platforms plus no-auth keyword research. Built so each platform is independent:
the tools that need credentials report a clear setup error until those
credentials are present, and the no-auth tools work with zero setup.

## Quick start

**macOS / Linux** (needs Python 3.10+; on macOS `brew install python@3.11`):

```
git clone <REPO_URL> marketing-mcp
cd marketing-mcp
bash install.sh
```

**Windows** (needs Python 3.10+ from python.org):

```
git clone <REPO_URL> marketing-mcp
cd marketing-mcp
install.bat
```

The installer creates a `.venv`, installs the dependencies, and registers
`marketing-mcp` into your Claude config (Claude Desktop if installed, and Claude
Code). Restart Claude, then try a no-auth tool: "use autocomplete_suggestions for
'ppc agency'". Connecting Google Ads / Meta / GA4 is optional and covered in
[SETUP.md](SETUP.md); copy `.env.example` to `.env` and the server auto-loads it.

To register without the installer (already have a venv or Python): `python register.py`.

## Tools (26)

**Clients (multi-account: granular + rollup)**
- `list_clients` / `add_client` — register clients in `clients.json`, each with its
  Google Ads, Meta, and GA4 account ids
- `clients_overview` — per-client KPIs across all platforms plus a rolled-up total
- every reporting tool also takes a `client` argument to target one client

**Keyword research**
- `keyword_ideas` — ideas from seed words and/or a URL (volume, competition, bid range)
- `keyword_historical_metrics` — 12-month volume series + competition + bid range
- `forecast_keywords` — projected impressions / clicks / cost at a max CPC bid
- `autocomplete_suggestions` — Google Suggest completions (no auth)
- `trend_index` — Google Trends interest + top/rising related queries (pytrends)
- `cluster_keywords` — group a keyword list into themes (no auth)

**Google Ads (reporting + management)**
- `list_ads_accounts` — accessible customer ids
- `ads_query` — run any GAQL query (the full reporting surface)
- `campaign_performance` — per-campaign metrics over N days
- `search_terms_report` — search terms + metrics
- `set_campaign_status` — pause / enable a campaign
- `set_campaign_budget` — change a campaign budget amount

**Meta Ads (reporting + management)**
- `meta_list_ad_accounts`, `meta_list_campaigns`, `meta_list_adsets`, `meta_list_ads`
- `meta_insights` — spend / impressions / clicks / ctr / cpc / actions at any level
- `meta_set_campaign_status` — pause / activate a campaign

**GA4 (analytics)**
- `ga4_run_report` — any dimensions x metrics over a date range
- `ga4_realtime` — realtime report
- `ga4_traffic_sources`, `ga4_top_pages` — convenience reports

The three power tools (`ads_query` GAQL, `meta_insights`, `ga4_run_report`)
expose each platform's whole API surface, so the server is not limited to the
fixed convenience tools above.

## Multiple clients

Define each client once in `clients.json` (copy `clients.example.json`) with its
Google Ads customer id, Meta ad account id, and GA4 property id. Then:

- granular: pass `client="acme"` to any reporting tool (`campaign_performance`,
  `meta_insights`, `ga4_run_report`, etc.) to scope it to that client's accounts.
- rollup: `clients_overview` returns a per-client KPI row for every client plus a
  single rolled-up total across all of them.

A platform a client has not connected shows an `*_error` note in the rollup
instead of a number, so a partially-configured client still reports. `clients.json`
is gitignored, so client account ids never get committed.

## Install

```
pip install -r requirements.txt
```

`mcp` and `httpx` cover the no-auth tools. `google-ads`, `pytrends`, and
`google-analytics-data` are needed only for their respective platforms.

## Setup

Copy `.env.example` to `.env` and fill only the platforms you use.

**Google Ads** — needs four OAuth values plus the account ids:
1. Apply for a developer token in the Google Ads account (API Center). Basic
   access is enough; the account needs a payment method on file.
2. Create an OAuth client (Desktop) in Google Cloud, then run the standard
   `google-ads` refresh-token flow to get `GOOGLE_ADS_REFRESH_TOKEN`.
3. Set `GOOGLE_ADS_LOGIN_CUSTOMER_ID` (manager/MCC) and `GOOGLE_ADS_CUSTOMER_ID`
   (the account to query), digits only.
   Note: without active ad spend, keyword volumes return as ranges, not exact
   numbers. Any minimal spend unlocks exact volumes.

**Meta Ads** — set `META_ACCESS_TOKEN` to a Marketing API token with `ads_read`
(and `ads_management` for the pause/activate tools). System-user tokens are
longest-lived; user tokens expire and need refresh.

**GA4** — create a service account, download its JSON key, add the service
account email as a Viewer on the GA4 property, and point
`GOOGLE_APPLICATION_CREDENTIALS` at the JSON path.

## Register with Claude Code / Claude Desktop

Add to your MCP config (`.mcp.json` or the desktop config), with the env block
holding your credentials:

```json
{
  "mcpServers": {
    "marketing-mcp": {
      "command": "python",
      "args": ["path/to/marketing-mcp/server.py"],
      "env": {
        "GOOGLE_ADS_DEVELOPER_TOKEN": "...",
        "GOOGLE_ADS_CLIENT_ID": "...",
        "GOOGLE_ADS_CLIENT_SECRET": "...",
        "GOOGLE_ADS_REFRESH_TOKEN": "...",
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "...",
        "GOOGLE_ADS_CUSTOMER_ID": "...",
        "META_ACCESS_TOKEN": "...",
        "GOOGLE_APPLICATION_CREDENTIALS": "C:/path/to/ga4-service-account.json"
      }
    }
  }
}
```

The no-auth tools (`autocomplete_suggestions`, `cluster_keywords`) work even with
an empty env block.

## Notes

- The Google Ads tools target the `google-ads` Python library v24+ (API v17+).
  The forecast tool uses `generate_keyword_forecast_metrics`; if your library
  version differs, the API error message will say so.
- Meta uses the Graph API v20.0 directly over HTTPS, so it needs only a token,
  no SDK.
