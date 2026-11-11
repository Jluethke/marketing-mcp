# Record an AI Visibility Run and Compare It

**One-line description:** Log whether each answer named the business, its position and the competitors named, then compare with earlier runs.

**Execution Pattern:** Phase Pipeline

**Runs:** by the MCP; every action below is a tool call.

---

## Inputs

- `business_name` (string, required): The business's name.
- `answers` (object[], required): The answers.
- `competitors` (string[], optional): Competitor names.

---

## Outputs

- `visibility_run` (object): Results keyed `run`, `history`.

---

## Phase 1: Run the Tools

### Entry Criteria
- Inputs present: `business_name`, `answers`, `competitors`.

### Actions
1. Call `visibility_record`(business=`business_name`, answers=`answers`, competitors=`competitors`) and keep the result as `run`.
2. Call `visibility_report`(business=`business_name`) and keep the result as `history`.

### Output
One result per call.

### Quality Gate
- The run and the history are present.
- A required call that cannot run stops the workflow and names the setup tool.

---

## Phase 2: Assemble

### Entry Criteria
- Every required call ran.

### Actions
1. Build `visibility_run` from the call results.

### Output
`visibility_run`.

### Quality Gate
- Every output is built from a call result, never estimated.

---

## Exit Criteria

- `visibility_run` is returned.

## Error Handling

- **First run:** The history holds this run only.

## Worked Example

Named in 4 of 15 answers, average position 2; a competitor named in 9.

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
