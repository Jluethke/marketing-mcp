# Marketing MCP

One MCP server that combines Google Ads (keyword research, GAQL reporting, and
campaign management), Meta Ads, GA4, Google Search Console, and a no-setup
SEO/site toolkit (on-page audit, site crawl, broken-link and structured-data
checks, technical-health check, PageSpeed, one-number score), plus local-SEO checks,
prospecting, email and copy checks, site hygiene, AI-assistant visibility, and a
multi-client rollup. Fourteen workflows, written as skill chains, run whole jobs
end to end. Works with Claude Desktop and Claude Code.
Each platform is independent: a tool returns a clear "needs setup" note until its
credentials are present, and several tools work with no setup at all.

## License

Proprietary and confidential. Copyright (c) 2026 The Wayfinder Trust. See
`LICENSE`. Licensed only under a separate written agreement. There is no public
distribution, and possession of a copy conveys no rights.

## Install

Supplied to licensees as a source archive or through a private repository grant.
Python 3.10+ required.

**macOS / Linux** (on macOS `brew install python@3.11`):

```
cd marketing-mcp
bash install.sh
```

**Windows** (Python 3.10+ from python.org):

```
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

- `seo_score`: paste a URL, get one 0-100 health score and letter grade with the
  top fixes. The fastest "how's this page doing". Try: "seo_score for https://example.com".
- `seo_audit`: full on-page audit (title, meta, headings, word count, links,
  images missing alt, issues). Try: "seo_audit for https://example.com".
- `crawl_site`: crawl up to N pages and aggregate the most common issues across
  the site (the multi-page version of seo_audit).
- `check_links`: find broken (4xx/5xx) links on a page.
- `content_analysis`: Flesch readability, keyword density, heading outline; pass a
  focus keyword to see where it appears.
- `http_check`: redirect chain, HTTPS, security headers, response time, mixed content.
- `validate_schema`: open the page's JSON-LD and flag missing recommended fields.
- `robots_sitemap`: read robots.txt and discover the sitemap's URLs.
- `growth_signals`: the growth stack a site runs today: ad pixels, affiliate and
  analytics tools, social profiles, and what its robots.txt tells each AI crawler.
  Try: "growth_signals for https://example.com".
- `growth_teardown`: name a company's domain, get a dated timeline of its growth
  moves read from archived copies of its homepage. Try: "growth_teardown for example.com".
- `autocomplete_suggestions`: Google autocomplete for a phrase. Try:
  "autocomplete_suggestions for 'plumber near me'".
- `cluster_keywords`: group a keyword list into themes.
- `trend_index`: Google Trends interest and related queries for up to 5 terms.
- `pagespeed`: Lighthouse scores and Core Web Vitals for a URL. Works without a
  key but shares a small quota; add a free `PAGESPEED_API_KEY` for reliable use
  (see below).

- `money_page_check`, `competitor_page_gap`, `missing_pages`, `crawl_depth`,
  `internal_link_plan`, `image_check`: the weekly local-SEO checks (see Tools).
- `find_businesses`, `prospect_finding`, `call_sheet`: a prospect list from open
  map data and a call sheet whose openers rest on real findings.
- `email_auth_check`, `verify_email`, `copy_check`: check a sending domain, an
  address, or a draft before it goes out.
- `sitemap_hygiene`, `duplicate_audit`, `assistants_index`, `schema_build`: site
  hygiene and the llms.txt index for AI assistants.

Everything else (live Google Ads / Meta / GA4 / Search Console data, and asking
Claude buyer questions for AI visibility) needs that platform connected. Run
`setup_check` any time to see what is connected.

## Workflows

The workflows live in `workflows/` in skill-chain format: each step is a flow folder
(`workflows/flows/<flow>/skill.md` with phases and quality gates, plus
`manifest.json`), and each workflow is a chain (`workflows/chains/<name>.chain.json`).
A step either runs on this server (it calls the tools its manifest lists) or is done
by Claude in the chat (writing, judging, choosing). No step is handed to a person.

Run one from chat with its prompt (each workflow is also an MCP prompt of the same
name), or with the tools:

- `list_workflows`: every workflow with its inputs and steps
- `run_workflow`: start one; tool steps run at once, and the run pauses at a step
  Claude does, returning that step's instructions and inputs
- `continue_workflow`: send that step's outputs and keep going; with no outputs it
  retries a step that was blocked on setup

| Workflow | What it does |
|---|---|
| `site-diagnosis` | robots, sitemap, HTTPS, click depth, analytics, AI crawlers, Search Console, then an ordered fix plan |
| `full-seo-review` | on-page checks for one URL, then the five fixes that matter most |
| `keyword-plan` | research, cluster and trend seed keywords, then the plan with the paid or organic split |
| `client-rollup` | KPIs for every client, then who moved and what to do |
| `connect-what-i-have` | what is connected, then connect the rest from chat |
| `growth-blueprint` | a company's growth moves by lane, dated and sourced |
| `weekly-seo-loop` | a post from the owner's answers, the copy gate, this week's money page, the share captions |
| `new-post-links` | internal links for a post that just went live |
| `client-timeline` | the SEO expectations note a client signs |
| `prospect-pipeline` | businesses in an area, then a call sheet with real findings |
| `ai-visibility-baseline` | ask Claude the buyer questions in clean sessions, record who is named, map gaps to pages |
| `content-coverage-map` | page inventory and overlap, then topics, gaps and the next eight posts |
| `news-anchored-post` | a post anchored to a dated news item, gated |
| `newsletter-rollup` | the week's posts in one newsletter, gated |

To change a workflow, edit the contract in `workflows/build_workflows.py`, run it to
regenerate the files, and run `python test_workflows.py`, which checks every chain
against the skill-chain rules and against the tools this server registers.

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

### Anthropic (for AI visibility: asking buyer questions in clean sessions)

`ANTHROPIC_API_KEY`
1. platform.claude.com -> API keys -> Create key. Copy it.
2. In chat: "set_anthropic_key with <key>". Each buyer question then goes to Claude
   as a fresh conversation with web search on and no history, so the answer is not
   shaped by the chat you are in. Model: `claude-opus-5-5` unless
   `MARKETING_MCP_ASK_MODEL` names another.

## Tools (86)

**Local SEO (no setup; the weekly checks of a local-business SEO practice)**
- `money_page_check`: is the target keyword in the page's visible text, title, H1,
  URL slug, first 100 words and meta description; a keyword missing from the visible
  text is flagged first.
- `competitor_page_gap`: your page against up to three competitor pages: title,
  meta, H1, H2s, word count, keyword placement, schema types and trust facts; flags
  over-use of the keyword and lists what every competitor says that you do not.
- `missing_pages`: page topics competitors have and your site lacks, ranked by how
  many competitors have each.
- `crawl_depth`: clicks from the homepage to every page; money pages deeper than
  two clicks and sitemap pages no link reaches.
- `internal_link_plan`: for a new post: 3 to 5 posts and 1 money page to link to,
  and 3 older posts to link from, each with its anchor sentence.
- `paid_vs_organic`: split keyword rows into SEO first, ads now with SEO long-term,
  ads for speed, or ads only, by click cost and difficulty; difficulty is never
  invented.
- `image_check`: file names, alt text, format, lazy loading, dimensions, and images
  per 250 words.

**Prospecting (no setup)**
- `find_businesses`: independent businesses in an area by category from
  OpenStreetMap, chains dropped, with website and phone where listed.
- `prospect_finding`: one graded finding (A, B, or C for clean) per site with the
  evidence it rests on; never invented on a clean site.
- `call_sheet`: prospects into a call sheet with a two-sentence opener built only
  from the finding and your offer, plus a voice-agent list and CSV.
- `agency_score`: score an agency as a reseller partner, with what to ask on the call.

**Email and copy (no setup; nothing is ever sent)**
- `email_auth_check`: SPF, DKIM, DMARC and MX for a sending domain, with fixes.
- `verify_email`: syntax, mail server, role, free and disposable flags, and an
  optional SMTP probe that never sends.
- `dmarc_report`: read a DMARC aggregate report into sources, results and pass rate.
- `classify_replies`: sort replies into dead address, policy block, out of office,
  address change, unsubscribe, other auto-reply, or human reply.
- `send_window`: each recipient's local mid-morning send time, batched.
- `copy_check`: AI tells, hype words, hedges, long sentences, spelling locale, and
  numbers without a source.

**Site hygiene (no setup)**
- `duplicate_audit`: exact and near duplicates, shared titles and H1s, orphans,
  broken internal links, redirects owed.
- `sitemap_hygiene`: robots.txt and sitemap checks, lastmod, noindex and canonical
  conflicts, mixed hosts, and the AI crawler rules.
- `schema_build`: JSON-LD for a local business, its services, FAQs and founder.
- `assistants_index`: an llms.txt index for AI assistants from a site's own pages.
- `cover_image`: a title card PNG checked against the area social previews keep.
- `strip_metadata`: remove author, template and provenance metadata from Office
  files, PNG and JPEG before publishing.

**AI visibility**
- `visibility_questions`: a fixed set of buyer questions for a business.
- `ask_assistant`: ask Claude each question in a fresh API session with web search
  on; needs `ANTHROPIC_API_KEY`.
- `visibility_record`: whether each answer named the business, its position, and
  the competitors named; kept in a local file.
- `visibility_report`: share of answer over time and the questions never won.

**Workflows**
- `list_workflows`, `run_workflow`, `continue_workflow`: see Workflows above.

**Growth teardown (no setup; reads the site and the Internet Archive from your machine)**
- `growth_signals`: read a site's homepage, tag-manager container, robots.txt and
  llms.txt, and report by lane: ads and tracking (Google Ads, Meta, TikTok, LinkedIn,
  Reddit, Microsoft, X, Pinterest pixels and attribution tools), affiliates and
  referral programs, analytics, lifecycle and CRM tools, experimentation, social
  profiles, site sections grouped by growth play, AI-search readiness (llms.txt,
  per-crawler robots rules, answer schema), the numbers the site states about itself,
  and the sitemap by section. A site behind a bot wall is read from its newest
  archived copy, and `source` says so.
- `growth_teardown`: sample archived copies of a domain's homepage across `years`
  (up to `max_snapshots`), run the same reading on each, and return a timeline: each
  signal with the snapshot it was first seen in and the last snapshot it was absent
  from, plus homepage title changes, the first archive capture of llms.txt and of
  each named section's own page (`page_first_archived`, an exact date), and new
  URLs per quarter when the archive index returns the site's URL list. Every
  first-seen date is a bracket between two snapshots. Funding, revenue and ad spend are listed under
  `not_covered`, never estimated.
- `growth-blueprint` (workflow): chains `growth_teardown`, `growth_signals`,
  `trend_index`, `meta_ad_library` and a news search for funding dates into one
  timeline by lane, each row tied to its source.

**SEO / site (no setup; PageSpeed is a free Google API)**
- `seo_score`: one 0-100 health score and letter grade, rolled up from the
  on-page audit, technical health, and readability, with the top fixes. Zero setup.
- `seo_audit`: fetch a URL and grade it: title, meta description, headings, word
  count, canonical, og/twitter tags, JSON-LD schema, images missing alt, link
  counts, and an issues list. Zero setup.
- `crawl_site`: crawl up to `max_pages` (sitemap-seeded or link-following,
  respecting robots.txt) and aggregate the most common issues site-wide.
- `check_links`: request every link on a page and report the broken (4xx/5xx)
  ones; scope = all / internal / external.
- `content_analysis`: Flesch reading ease, word/sentence counts, keyword density,
  heading outline, thin-content flag, and optional focus-keyword placement.
- `http_check`: redirect chain, HTTPS enforcement, security headers (HSTS, CSP,
  X-Content-Type-Options, X-Frame-Options), response time, server, mixed content.
- `validate_schema`: parse the page's JSON-LD, list each `@type`, flag invalid
  JSON, and report missing recommended properties for common schema types.
- `robots_sitemap`: parse robots.txt (Disallow rules + Sitemap directives) and
  walk the XML sitemap (handles a sitemap index) to count and sample page URLs.
- `pagespeed`: Lighthouse performance / SEO / accessibility scores plus Core Web
  Vitals (LCP, CLS, INP) for a URL. Set `PAGESPEED_API_KEY` (free) for quota.

**Search Console (organic search)**
- `gsc_top_queries` / `gsc_top_pages`: top organic queries and pages by clicks,
  impressions, CTR, and position over N days
- `gsc_search_analytics`: any dimensions (query, page, country, device, date)
- `gsc_list_sites`: properties the service account can read
- `gsc_inspect_url`: URL Inspection: is a page indexed, its coverage state, last
  crawl time, Google-chosen canonical, mobile usability, rich-results status
- `gsc_list_sitemaps` / `gsc_submit_sitemap`: list submitted sitemaps with their
  errors/warnings, and submit a new sitemap (submit needs full-user permission)

**Keyword research (bulk + locations)**
- `keyword_research`: one call: expand seed keywords and/or pull metrics for a
  keyword list, across many places at once, ranked by search volume and
  commercial intent, returned as decision-ready rows you act on in the same chat
  turn. Chunks under the API's 20-seed cap.
- `resolve_locations`: turn town/city/state names into Google Ads geo target ids
  with reach, so you target specific areas instead of the whole country
- `add_location_set` / `list_location_sets`: save a reusable named list of target
  areas; pass `location_set="<name>"` to the keyword tools
- `keyword_ideas` / `keyword_historical_metrics` also take `locations` / `location_set`
- `forecast_keywords`: projected impressions / clicks / cost at a max CPC bid
- `autocomplete_suggestions`: Google Suggest completions (no setup)
- `trend_index`: Google Trends interest + related queries
- `cluster_keywords`: group a keyword list into themes (no setup)

**Google Ads (reporting + management)**
- `list_ads_accounts`: accessible customer ids
- `ads_query`: run any GAQL query (the full reporting surface)
- `campaign_performance`: per-campaign metrics over N days
- `search_terms_report`: search terms + metrics
- `set_campaign_status` / `set_campaign_budget`: pause/enable, change budget

**Meta Ads (reporting + management)**
- `meta_list_ad_accounts`, `meta_list_campaigns`, `meta_list_adsets`, `meta_list_ads`
- `meta_insights`: spend / impressions / clicks / ctr / cpc / actions at any level
- `meta_ad_library`: search Meta's public Ad Library for competitor ads
- `meta_set_campaign_status`: pause / activate a campaign

**GA4 (analytics)**
- `ga4_run_report`: any dimensions x metrics over a date range
- `ga4_realtime`: realtime report
- `ga4_traffic_sources`, `ga4_top_pages`: convenience reports

**Clients (multi-account: granular + rollup)**
- `list_clients` / `add_client`: register clients in `clients.json`, each with its
  Google Ads, Meta, and GA4 account ids
- `clients_overview`: per-client KPIs across all platforms plus a rolled-up total
- every reporting tool also takes a `client` argument to target one client

**Setup**
- `setup_check`: which platforms are connected and the next step for the rest
- `setup_instructions`: the from-chat steps
- `connect_google_ads`, `connect_google_ads_oauth`, `connect_meta`,
  `connect_analytics`, `set_pagespeed_key`, `set_anthropic_key`: connect from chat

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
  gitignored, so credentials never get committed. So are the local stores the newer
  tools keep: `ai_visibility.json`, `workflow_runs.json`, and the `covers/` folder.
  Set `MARKETING_MCP_DATA_DIR` to keep the stores elsewhere.
- Tests: `test_growth.py`, `test_seo_rules.py`, `test_prospecting.py`,
  `test_email_checks.py`, `test_copy_check.py`, `test_site_hygiene.py`,
  `test_ai_visibility.py`, `test_workflows.py`; each runs offline and ends with
  "all checks passed".
