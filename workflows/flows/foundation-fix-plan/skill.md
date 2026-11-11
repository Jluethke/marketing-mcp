# Turn a Foundation Report Into an Ordered Fix Plan

**One-line description:** Order the failures in a foundation report by what blocks discovery first, and write each fix as one action with where it is done and the tool result that confirms it.

**Execution Pattern:** Phase Pipeline

**Runs:** by Claude in the chat; the workflow pauses here and resumes with the outputs.

---

## Inputs

- `foundation_report` (object, required): Output of `site-foundation-check`.

---

## Outputs

- `fix_plan` (object[]): Ordered rows: `fix`, `where`, `confirm_with`.

---

## Phase 1: Order

### Entry Criteria
- `foundation_report` is present.

### Actions
1. List every failure: crawlers blocked, sitemap missing or invalid, lastmod stamped, noindex or canonical conflicts, HTTPS or redirect faults, pages deeper than two clicks, orphan pages, no analytics tag, Search Console not set up or sitemap not submitted.
2. Order them: discovery blockers first, then reach, then measurement.

### Output
An ordered list.

### Quality Gate
- Every failure in `foundation_report` appears once.

---

## Phase 2: Write

### Entry Criteria
- The ordered list exists.

### Actions
1. Write each `fix` as one action, `where` it is done (host, CMS, DNS, robots.txt), and `confirm_with`: the tool to rerun and the result that means done.

### Output
`fix_plan`.

### Quality Gate
- Every row names a tool or an observable result in `confirm_with`.

---

## Exit Criteria

- `fix_plan` covers every failure.

## Error Handling

- **No failures:** Return an empty `fix_plan` and state that the foundations pass.

## Worked Example

Depth failure: link the water-heater page from the services menu; confirm with crawl_depth showing depth 1.

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
