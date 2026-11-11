# Run the On-Page Checks for One URL

**One-line description:** Score a page and read its on-page audit, technical health, readability and broken links.

**Execution Pattern:** Phase Pipeline

**Runs:** by the MCP; every action below is a tool call.

---

## Inputs

- `url` (string, required): The page to review.

---

## Outputs

- `review_findings` (object): Results keyed `score`, `audit`, `http`, `content`, `links`.

---

## Phase 1: Run the Tools

### Entry Criteria
- Inputs present: `url`.

### Actions
1. Call `seo_score`(url=`url`) and keep the result as `score`.
2. Call `seo_audit`(url=`url`) and keep the result as `audit`.
3. Call `http_check`(url=`url`) and keep the result as `http`.
4. Call `content_analysis`(url=`url`) and keep the result as `content`.
5. Call `check_links`(url=`url`) and keep the result as `links`.

### Output
One result per call.

### Quality Gate
- All five results are present.
- A required call that cannot run stops the workflow and names the setup tool.

---

## Phase 2: Assemble

### Entry Criteria
- Every required call ran.

### Actions
1. Build `review_findings` from the call results.

### Output
`review_findings`.

### Quality Gate
- Every output is built from a call result, never estimated.

---

## Exit Criteria

- `review_findings` is returned.

## Error Handling

- **Page unreadable:** Each check reports the wall or the status code and the review says so.

## Worked Example

A service page scores 71 (C): no meta description, two images without alt text, one broken link.

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
