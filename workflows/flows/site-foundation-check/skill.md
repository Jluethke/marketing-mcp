# Check That Search Engines and AI Assistants Can Find and Read a Site

**One-line description:** Read robots.txt, the sitemap, HTTPS, click depth, the analytics tag, AI crawler access and the Search Console sitemap status for a site, and return every result with its evidence.

**Execution Pattern:** Phase Pipeline

**Runs:** by the MCP; every action below is a tool call.

---

## Inputs

- `site_url` (string, required): The site's homepage URL.

---

## Outputs

- `foundation_report` (object): Results keyed `sitemap`, `http`, `depth`, `stack`, `search_console`.

---

## Phase 1: Run the Tools

### Entry Criteria
- Inputs present: `site_url`.

### Actions
1. Call `sitemap_hygiene`(url=`site_url`) and keep the result as `sitemap`.
2. Call `http_check`(url=`site_url`) and keep the result as `http`.
3. Call `crawl_depth`(start_url=`site_url`, max_pages=100) and keep the result as `depth`.
4. Call `growth_signals`(url=`site_url`) and keep the result as `stack`.
5. Call `gsc_list_sitemaps`(site_url=`site_url`) and keep the result as `search_console` (optional: a refusal or missing setup is recorded and the flow continues).

### Output
One result per call.

### Quality Gate
- Each of the five results is present; Search Console may read needs setup when it is not connected.
- A required call that cannot run stops the workflow and names the setup tool.

---

## Phase 2: Assemble

### Entry Criteria
- Every required call ran.

### Actions
1. Build `foundation_report` from the call results.

### Output
`foundation_report`.

### Quality Gate
- Every output is built from a call result, never estimated.

---

## Exit Criteria

- `foundation_report` is returned.

## Error Handling

- **Site behind a bot wall:** The page tools report the wall; the report carries it as found.

## Worked Example

A plumber's site: every sitemap lastmod is one build date, the water-heater page sits four clicks deep, and no analytics tag is present.

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
