# Rank the Fixes From an On-Page Review

**One-line description:** Turn the on-page review results into the five fixes that matter most, each tied to its finding.

**Execution Pattern:** Phase Pipeline

**Runs:** by Claude in the chat; the workflow pauses here and resumes with the outputs.

---

## Inputs

- `review_findings` (object, required): Output of `seo-review-checks`.

---

## Outputs

- `fix_list` (object[]): Five rows: `fix`, `finding`, `impact`.

---

## Phase 1: Collect

### Entry Criteria
- `review_findings` is present.

### Actions
1. Gather every issue across the score, audit, technical, readability and link results.

### Output
The issue list.

### Quality Gate
- Each issue names the result it came from.

---

## Phase 2: Rank

### Entry Criteria
- The issue list exists.

### Actions
1. Rank by effect on ranking and on a reader: missing keyword or title first, then crawl and HTTPS faults, then readability, then minor tags.
2. Keep the top five.

### Output
`fix_list`.

### Quality Gate
- Each fix cites its `finding`.

---

## Exit Criteria

- `fix_list` holds five ranked fixes.

## Error Handling

- **Page unreadable:** Return one row saying the page could not be read and why.

## Worked Example

Fix 1: add a meta description stating the service and town (audit: meta description missing).

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
