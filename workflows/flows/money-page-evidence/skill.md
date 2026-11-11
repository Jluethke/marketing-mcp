# Collect the Evidence for This Week's Money Page

**One-line description:** List the page topics competitors have and the site lacks, check one money page for its keyword, and compare it with the competitors' matching pages.

**Execution Pattern:** Phase Pipeline

**Runs:** by the MCP; every action below is a tool call.

---

## Inputs

- `business_site` (string, required): The business's site URL.
- `competitor_sites` (string[], required): The top three competitors' sites.
- `money_page_url` (string, required): The money page under review.
- `target_keyword` (string, required): Its service and city phrase.
- `competitor_pages` (string[], required): The competitors' pages for the same service.

---

## Outputs

- `money_page_evidence` (object): Results keyed `missing`, `page_check`, `gap`.

---

## Phase 1: Run the Tools

### Entry Criteria
- Inputs present: `business_site`, `competitor_sites`, `money_page_url`, `target_keyword`, `competitor_pages`.

### Actions
1. Call `missing_pages`(site=`business_site`, competitor_sites=`competitor_sites`) and keep the result as `missing`.
2. Call `money_page_check`(url=`money_page_url`, keyword=`target_keyword`) and keep the result as `page_check`.
3. Call `competitor_page_gap`(url=`money_page_url`, competitor_urls=`competitor_pages`, keyword=`target_keyword`) and keep the result as `gap`.

### Output
One result per call.

### Quality Gate
- All three results are present.
- A required call that cannot run stops the workflow and names the setup tool.

---

## Phase 2: Assemble

### Entry Criteria
- Every required call ran.

### Actions
1. Build `money_page_evidence` from the call results.

### Output
`money_page_evidence`.

### Quality Gate
- Every output is built from a call result, never estimated.

---

## Exit Criteria

- `money_page_evidence` is returned.

## Error Handling

- **Competitor blocks readers:** The gap lists it as unreadable and compares the rest.

## Worked Example

Two of three competitors have a tankless page; the replacement page never states its town.

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
