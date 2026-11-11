# Write a Keyword Plan From Research Results

**One-line description:** Turn researched, clustered keywords into a plan: the themes, the priority terms per theme, the trending themes, and the paid or organic split.

**Execution Pattern:** Phase Pipeline

**Runs:** by Claude in the chat; the workflow pauses here and resumes with the outputs.

---

## Inputs

- `keyword_data` (object, required): Output of `keyword-research-pass`.

---

## Outputs

- `keyword_plan` (object): `{themes, priority_terms, trending, split}`.

---

## Phase 1: Prioritize

### Entry Criteria
- `keyword_data` is present.

### Actions
1. Per theme, list the top terms by the research priority (volume and intent).
2. Mark themes whose trend is rising.

### Output
Themes with priority terms.

### Quality Gate
- Every theme has at least one priority term.

---

## Phase 2: Split

### Entry Criteria
- Themes exist.

### Actions
1. Call `paid_vs_organic` on the research rows and attach each term's box.

### Output
`keyword_plan`.

### Quality Gate
- Terms without difficulty are listed as unclassified, never guessed.

---

## Exit Criteria

- `keyword_plan` is complete.

## Error Handling

- **No research rows:** Return the plan empty and name the missing connection.

## Worked Example

Theme 'roof repair': 'emergency roof repair austin' leads; the box is ads now, SEO long-term.

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
