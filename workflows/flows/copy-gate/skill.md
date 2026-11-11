# Gate a Draft for Plain Language and Sourced Numbers

**One-line description:** Run the copy check on a draft, rewrite every failing line, and rerun until it passes.

**Execution Pattern:** Phase Pipeline

**Runs:** by Claude in the chat; the workflow pauses here and resumes with the outputs.

---

## Inputs

- `draft` (object, required): Any draft with a `body` field.
- `house_rules` (object, optional): Extra banned words or rules.

---

## Outputs

- `gated_draft` (object): The draft with failing lines rewritten and `verdict` pass.
- `copy_report` (object[]): Rows: `line`, `rule`, `before`, `after`.

---

## Phase 1: Scan

### Entry Criteria
- `draft` has a body.

### Actions
1. Call `copy_check` on the body with `house_rules`.

### Output
The issue list.

### Quality Gate
- Every issue names its rule and line.

---

## Phase 2: Rewrite

### Entry Criteria
- The issue list exists.

### Actions
1. Rewrite each failing line to state the fact plainly; give each number its source or remove it.
2. Call `copy_check` again until it passes.

### Output
`gated_draft` and `copy_report`.

### Quality Gate
- The last check passes.

---

## Exit Criteria

- `gated_draft` passes `copy_check`.

## Error Handling

- **A number has no source:** Remove it and keep the sentence true.

## Worked Example

A line praising the team with hype adjectives becomes 'two licensed plumbers answer from 7 a.m.'

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
