# Write the Buyer Questions That Measure AI Visibility

**One-line description:** Generate a fixed set of buyer questions for a business so the same set can be asked every month.

**Execution Pattern:** Phase Pipeline

**Runs:** by the MCP; every action below is a tool call.

---

## Inputs

- `business_name` (string, required): The business's name.
- `service` (string, required): The main service.
- `city` (string, optional): The main town served.
- `competitors` (string[], optional): Competitor names.

---

## Outputs

- `question_set` (object): The question set.

---

## Phase 1: Run the Tools

### Entry Criteria
- Inputs present: `business_name`, `service`, `city`, `competitors`.

### Actions
1. Call `visibility_questions`(business=`business_name`, service=`service`, city=`city`, competitors=`competitors`) and keep the result as `qs`.

### Output
One result per call.

### Quality Gate
- The set holds about fifteen questions.
- A required call that cannot run stops the workflow and names the setup tool.

---

## Phase 2: Assemble

### Entry Criteria
- Every required call ran.

### Actions
1. Build `question_set` from the call results.

### Output
`question_set`.

### Quality Gate
- Every output is built from a call result, never estimated.

---

## Exit Criteria

- `question_set` is returned.

## Error Handling

- **No competitors:** The set has no comparison questions.

## Worked Example

'Who is the best water heater installer in Hoboken?'

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
