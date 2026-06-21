# Marketing MCP

One MCP server that combines Google Ads (keyword research, GAQL reporting, and
campaign management), Meta Ads, GA4, Google Search Console, and a no-setup
SEO/site toolkit (on-page audit, site crawl, broken-link and structured-data
checks, technical-health check, PageSpeed, one-number score), plus a multi-client
rollup. Works with Claude Desktop and Claude Code.
Each platform is independent: a tool returns a clear "needs setup" note until its
credentials are present, and several tools work with no setup at all.

## Install

**macOS / Linux** (needs Python 3.10+; on macOS `brew install python@3.11`):

```
git clone https://github.com/Jluethke/marketing-mcp.git
cd marketing-mcp
bash install.sh
```

**Windows** (needs Python 3.10+ from python.org):

```
git clone https://github.com/Jluethke/marketing-mcp.git
cd marketing-mcp
install.bat
```

The installer creates a `.venv`, installs the dependencies, and registers
`marketing-mcp` into your Claude config (Claude Desktop if installed, and Claude
Code). Restart Claude so it loads the server.

To register without the installer (you already have a venv or Python):
`python register.py`.

## Try it now (no setup)

These tools work the moment the server is installed, with no accounts or keys.
Start here to confirm it runs, before connecting anything:

- `seo_score` — paste a URL, get one 0-100 health score and letter grade with the
  top fixes. The fastest "how's this page doing". Try: "seo_score for https://example.com".
- `seo_audit` — full on-page audit (title, meta, headings, word count, links,
  images missing alt, issues). Try: "seo_audit for https://example.com".
- `crawl_site` — crawl up to N pages and aggregate the most common issues across
  the site (the multi-page version of seo_audit).
- `check_links` — find broken (4xx/5xx) links on a page.
- `content_analysis` — Flesch readability, keyword density, heading outline; pass a
  focus keyword to see where it appears.
- `http_check` — redirect chain, HTTPS, security headers, response time, mixed content.
- `validate_schema` — open the page's JSON-LD and flag missing recommended fields.
- `robots_sitemap` — read robots.txt and discover the sitemap's URLs.
- `autocomplete_suggestions` — Google autocomplete for a phrase. Try:
  "autocomplete_suggestions for 'plumber near me'".
- `cluster_keywords` — group a keyword list into themes.
- `trend_index` — Google Trends interest and related queries for up to 5 terms.
- `pagespeed` — Lighthouse scores and Core Web Vitals for a URL. Works without a
  key but shares a small quota; add a free `PAGESPEED_API_KEY` for reliable use
  (see below).

Everything else (live Google Ads / Meta / GA4 / Search Console data) needs that
platform connected. Run `setup_check` any time to see what is connected.

## Connecting your accounts

There are two ways. Both write the same `.env` file; pick whichever is easier.

### Option A: connect from chat (easiest, no file editing)

Just talk to the assistant. Ask it to run `setup_instructions` for the steps,
then connect each platform by pasting your values into chat:

- Google Ads: say "connect google ads oauth" and paste your OAuth client id and
  secret (a browser opens to approve), then "connect google ads" with your
  developer token and 10-digit account id.
- Meta Ads: say "connect meta" and paste your access token.
- GA4 + Search Console: say "connect analytics" and paste the contents of your
  service-account JSON key.
- PageSpeed (optional): say "set pagespeed key" and paste a free API key.

Each `connect_*` tool writes the `.env` for you, applies it immediately (no
restart), and confirms by pinging the platform. Tokens are masked in the reply,
and `.env` is gitignored, so nothing is shown in full or committed.

### Option B: edit the .env file yourself

The `.env` file lives in the `marketing-mcp` folder you cloned. It is a hidden
file (the name starts with a dot), so create and open it from a terminal in that
folder rather than hunting for it in Finder.

1. Make it from the template:
   - macOS / Linux: `cp .env.example .env`
   - Windows: `copy .env.example .env`
2. Open it to edit:
   - macOS: `open -e .env` (opens in TextEdit)
   - Windows: `notepad .env`
3. Each line is `NAME=value`. Put your value right after the `=`, with no quotes
   and no spaces around it. Fill only the platforms you want; leave the rest
   blank. Example:
   ```
   META_ACCESS_TOKEN=EAAG...your token...
   ```
4. Save the file, then restart Claude (the server reads `.env` when it starts).

Run `python doctor.py` to see which platforms are configured, or `python doctor.py
--live` to also ping them.

## How to get each credential

Get a value from the platform, then either paste it in chat (Option A) or put it
on the matching `.env` line (Option B). You only need the platforms you plan to
use.

### Google Ads (keyword research, reporting, campaign management)

`GOOGLE_ADS_DEVELOPER_TOKEN`
1. Sign in at ads.google.com. The account must have a billing/payment method on
   file (you do not have to spend).
2. Click the tools icon (wrench) at the top, then Setup -> API Center.
3. Apply for a developer token; choose Basic access. Approval can take up to a day.

`GOOGLE_ADS_CLIENT_ID` and `GOOGLE_ADS_CLIENT_SECRET`
1. Go to console.cloud.google.com and create or pick a project.
2. APIs & Services -> Library -> search "Google Ads API" -> Enable.
3. APIs & Services -> Credentials -> Create Credentials -> OAuth client ID.
4. Application type: Desktop app -> Create. Copy the client ID and client secret.

`GOOGLE_ADS_REFRESH_TOKEN`
- Easiest: in chat say "connect google ads oauth" and paste the client id/secret;
  a browser opens, you approve, and it saves the token.
- Or in a terminal: `python oauth_setup.py <CLIENT_ID> <CLIENT_SECRET>`, approve
  in the browser, and copy the `GOOGLE_ADS_REFRESH_TOKEN=...` it prints.

`GOOGLE_ADS_CUSTOMER_ID`
- The 10-digit account number shown at the top of ads.google.com (format
  123-456-7890). Enter it without dashes: `1234567890`.

`GOOGLE_ADS_LOGIN_CUSTOMER_ID` (only if you use a manager account)
- The 10-digit id of your manager (MCC) account, digits only. If you have a single
  Ads account and no manager, leave this blank.

Note: without active ad spend on the account, keyword search volumes come back as
ranges (for example 1K-10K), not exact numbers. That is Google's limit.

### Meta Ads (reporting, management, ad library)

`META_ACCESS_TOKEN`
1. Go to developers.facebook.com -> My Apps -> Create App (type: Business).
2. Add the "Marketing API" product to the app.
3. Quick token (expires in 1-2 hours, fine for testing): Tools -> Graph API
   Explorer, pick your app, add the permission `ads_read` (and `ads_management`
   if you want the pause/activate tools), then Generate Access Token.
4. Long-lived token (does not expire): business.facebook.com -> Business Settings
   -> Users -> System Users -> create a system user -> Generate New Token, select
   your app and the `ads_read` permission.

### GA4 and Search Console (one service-account key serves both)

`GOOGLE_APPLICATION_CREDENTIALS` (a path to a JSON file)
1. console.cloud.google.com -> create or pick a project.
2. APIs & Services -> Library -> enable both "Google Analytics Data API" and
   "Google Search Console API".
3. APIs & Services -> Credentials -> Create Credentials -> Service account. Give
   it a name and click Done.
4. Click the new service account -> Keys -> Add Key -> Create new key -> JSON.
   A `.json` file downloads. Note the service-account email (it looks like
   `name@project-id.iam.gserviceaccount.com`).
5. In GA4: Admin -> Property Access Management -> add that email as a Viewer.
6. In Search Console: Settings -> Users and permissions -> add that email as a user
   (Restricted is enough for reading and URL inspection; choose Full only if you
   want `gsc_submit_sitemap` to be able to submit sitemaps).
7. Set `GOOGLE_APPLICATION_CREDENTIALS` to the full path of the downloaded JSON
   (in chat, "connect analytics" + paste the file's contents does this for you).

To use the tools you also need:
- GA4 property id: GA4 Admin -> Property Settings, a number like `123456789`. Pass
  it as `property_id`.
- Search Console site: the exact property string, e.g. `https://example.com/` or
  `sc-domain:example.com`. Pass it as `site_url`.

### PageSpeed (optional, for the pagespeed tool's quota)

`PAGESPEED_API_KEY`
1. console.cloud.google.com -> APIs & Services -> Library -> enable "PageSpeed
   Insights API".
2. APIs & Services -> Credentials -> Create Credentials -> API key. Copy it.

## Tools (53)

**SEO / site (no setup; PageSpeed is a free Google API)**
- `seo_score` — one 0-100 health score and letter grade, rolled up from the
  on-page audit, technical health, and readability, with the top fixes. Zero setup.
- `seo_audit` — fetch a URL and grade it: title, meta description, headings, word
  count, canonical, og/twitter tags, JSON-LD schema, images missing alt, link
  counts, and an issues list. Zero setup.
- `crawl_site` — crawl up to `max_pages` (sitemap-seeded or link-following,
  respecting robots.txt) and aggregate the most common issues site-wide.
- `check_links` — request every link on a page and report the broken (4xx/5xx)
  ones; scope = all / internal / external.
- `content_analysis` — Flesch reading ease, word/sentence counts, keyword density,
  heading outline, thin-content flag, and optional focus-keyword placement.
- `http_check` — redirect chain, HTTPS enforcement, security headers (HSTS, CSP,
  X-Content-Type-Options, X-Frame-Options), response time, server, mixed content.
- `validate_schema` — parse the page's JSON-LD, list each `@type`, flag invalid
  JSON, and report missing recommended properties for common schema types.
- `robots_sitemap` — parse robots.txt (Disallow rules + Sitemap directives) and
  walk the XML sitemap (handles a sitemap index) to count and sample page URLs.
- `pagespeed` — Lighthouse performance / SEO / accessibility scores plus Core Web
  Vitals (LCP, CLS, INP) for a URL. Set `PAGESPEED_API_KEY` (free) for quota.

**Search Console (organic search)**
- `gsc_top_queries` / `gsc_top_pages` — top organic queries and pages by clicks,
  impressions, CTR, and position over N days
- `gsc_search_analytics` — any dimensions (query, page, country, device, date)
- `gsc_list_sites` — properties the service account can read
- `gsc_inspect_url` — URL Inspection: is a page indexed, its coverage state, last
  crawl time, Google-chosen canonical, mobile usability, rich-results status
- `gsc_list_sitemaps` / `gsc_submit_sitemap` — list submitted sitemaps with their
  errors/warnings, and submit a new sitemap (submit needs full-user permission)

**Keyword research (bulk + locations)**
- `keyword_research` — one call: expand seed keywords and/or pull metrics for a
  keyword list, across many places at once, ranked by search volume and
  commercial intent, returned as decision-ready rows you act on in the same chat
  turn. Chunks under the API's 20-seed cap.
- `resolve_locations` — turn town/city/state names into Google Ads geo target ids
  with reach, so you target specific areas instead of the whole country
- `add_location_set` / `list_location_sets` — save a reusable named list of target
  areas; pass `location_set="<name>"` to the keyword tools
- `keyword_ideas` / `keyword_historical_metrics` also take `locations` / `location_set`
- `forecast_keywords` — projected impressions / clicks / cost at a max CPC bid
- `autocomplete_suggestions` — Google Suggest completions (no setup)
- `trend_index` — Google Trends interest + related queries
- `cluster_keywords` — group a keyword list into themes (no setup)

**Google Ads (reporting + management)**
- `list_ads_accounts` — accessible customer ids
- `ads_query` — run any GAQL query (the full reporting surface)
- `campaign_performance` — per-campaign metrics over N days
- `search_terms_report` — search terms + metrics
- `set_campaign_status` / `set_campaign_budget` — pause/enable, change budget

**Meta Ads (reporting + management)**
- `meta_list_ad_accounts`, `meta_list_campaigns`, `meta_list_adsets`, `meta_list_ads`
- `meta_insights` — spend / impressions / clicks / ctr / cpc / actions at any level
- `meta_ad_library` — search Meta's public Ad Library for competitor ads
- `meta_set_campaign_status` — pause / activate a campaign

**GA4 (analytics)**
- `ga4_run_report` — any dimensions x metrics over a date range
- `ga4_realtime` — realtime report
- `ga4_traffic_sources`, `ga4_top_pages` — convenience reports

**Clients (multi-account: granular + rollup)**
- `list_clients` / `add_client` — register clients in `clients.json`, each with its
  Google Ads, Meta, and GA4 account ids
- `clients_overview` — per-client KPIs across all platforms plus a rolled-up total
- every reporting tool also takes a `client` argument to target one client

**Setup**
- `setup_check` — which platforms are connected and the next step for the rest
- `setup_instructions` — the from-chat steps
- `connect_google_ads`, `connect_google_ads_oauth`, `connect_meta`,
  `connect_analytics`, `set_pagespeed_key` — connect from chat

The power tools (`ads_query` GAQL, `meta_insights`, `ga4_run_report`,
`gsc_search_analytics`) expose each platform's whole API surface, so the server
is not limited to the convenience tools.

## Multiple clients

Define each client once with `add_client` (or in `clients.json`, copy
`clients.example.json`) with its Google Ads customer id, Meta ad account id, and
GA4 property id. Then:

- granular: pass `client="acme"` to any reporting tool to scope it to that
  client's accounts.
- rollup: `clients_overview` returns a per-client KPI row for every client plus a
  single rolled-up total across all of them.

A platform a client has not connected shows an `*_error` note in the rollup
instead of a number. `clients.json` is gitignored, so client account ids never get
committed.

## Notes

- The Google Ads tools target the `google-ads` Python library v24+ (API v17+).
- Meta uses the Graph API v20.0 directly, so it needs only a token, no SDK.
- `.env`, `clients.json`, `location_sets.json`, and any service-account JSON are
  gitignored, so credentials never get committed.
