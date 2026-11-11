# Lay Out a Company's Growth Timeline by Lane

**One-line description:** Turn growth evidence into one dated timeline by lane, each row tied to its source, and name the moves a small team can copy.

**Execution Pattern:** Phase Pipeline

**Runs:** by Claude in the chat; the workflow pauses here and resumes with the outputs.

---

## Inputs

- `growth_evidence` (object, required): Output of `growth-evidence`.
- `company` (string, required): The company name.

---

## Outputs

- `growth_timeline` (object): `{rows, copyable_moves}`.

---

## Phase 1: Lay Out

### Entry Criteria
- `growth_evidence` is present.

### Actions
1. Lanes: ads and tracking, social, search, AI search, affiliates and referral, fundraising.
2. Search the web for the funding rounds and launch dates of `company`, one link per date.
3. Where a tool lists something as not covered, the cell reads no public signal.

### Output
Timeline rows.

### Quality Gate
- Every row carries a date or date bracket and its source.

---

## Phase 2: Conclude

### Entry Criteria
- Rows exist.

### Actions
1. Name the three moves before the steepest growth in new pages or brand interest, and which a small team can copy.

### Output
`growth_timeline`.

### Quality Gate
- No estimate fills a cell without a source.

---

## Exit Criteria

- `growth_timeline` is complete.

## Error Handling

- **Thin archive:** State how many captures were read.

## Worked Example

Affiliates lane: program first seen between March and June 2024 (archive captures).

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
