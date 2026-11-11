# Write the SEO Expectations Note a Client Signs

**One-line description:** Write a one-page note that sets SEO timing and success measures at signing, with every figure sourced and dated.

**Execution Pattern:** Phase Pipeline

**Runs:** by Claude in the chat; the workflow pauses here and resumes with the outputs.

---

## Inputs

- `service` (string, required): The engagement, for example SEO or SEO with paid search.

---

## Outputs

- `expectations_note` (object): `{title, body}`.

---

## Phase 1: Draft

### Entry Criteria
- `service` is named.

### Actions
1. Weeks 1 to 4: indexing and fixes, no ranking movement. Months 2 and 3: long-tail terms appear, impressions before clicks. Months 3 to 6: competitive terms move if reviews and links move. Months 6 to 12: compounding.
2. Paid search converts from day one; organic does not. Success is calls, bookings and qualified leads, judged monthly.

### Output
A draft.

### Quality Gate
- Every window states what happens and what is reported.

---

## Phase 2: Source

### Entry Criteria
- A draft exists.

### Actions
1. Search the web for any industry figure before it goes in; cite it with date and link, or drop it.

### Output
`expectations_note`.

### Quality Gate
- No figure lacks a dated source.

---

## Exit Criteria

- `expectations_note` is ready to sign.

## Error Handling

- **Guarantee requested:** State what is promised instead: the work, the cadence and the report.

## Worked Example

Month 2 report line: impressions for 14 new question terms; clicks follow.

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
