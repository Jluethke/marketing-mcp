# Choose This Week's Money Page Work

**One-line description:** From the money page evidence, choose one page to build or fix this week and list its changes.

**Execution Pattern:** Phase Pipeline

**Runs:** by Claude in the chat; the workflow pauses here and resumes with the outputs.

---

## Inputs

- `money_page_evidence` (object, required): Output of `money-page-evidence`.

---

## Outputs

- `money_page_actions` (object): `{this_week, changes, later}`.

---

## Phase 1: Weigh

### Entry Criteria
- `money_page_evidence` is present.

### Actions
1. A keyword missing from the page's visible text is the first fix.
2. Compare that with the missing page most competitors have.

### Output
Candidates.

### Quality Gate
- Each candidate cites its evidence.

---

## Phase 2: Choose

### Entry Criteria
- Candidates exist.

### Actions
1. Pick one; list the changes using only facts the owner has approved; queue the rest.

### Output
`money_page_actions`.

### Quality Gate
- `this_week` names one page.

---

## Exit Criteria

- `money_page_actions` names one page and its changes.

## Error Handling

- **Evidence empty:** Choose the page with the keyword missing.

## Worked Example

This week: build the tankless page; later: add the town to the replacement page.

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
