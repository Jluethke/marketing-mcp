# Ask an AI Assistant the Buyer Questions in a Clean Session

**One-line description:** Ask each buyer question in its own fresh API session with web search on, and keep each answer with the links it cited.

**Execution Pattern:** Phase Pipeline

**Runs:** by the MCP; every action below is a tool call.

---

## Inputs

- `question_set` (object, required): Output of `visibility-questions`.

---

## Outputs

- `answers` (object[]): Rows: `question`, `answer`, `cited_urls`.

---

## Phase 1: Run the Tools

### Entry Criteria
- Inputs present: `question_set`.

### Actions
1. Call `ask_assistant`(questions=`question_set`) and keep the result as `asked`.

### Output
One result per call.

### Quality Gate
- Every question has an answer or a recorded error.
- A required call that cannot run stops the workflow and names the setup tool.

---

## Phase 2: Assemble

### Entry Criteria
- Every required call ran.

### Actions
1. Build `answers` from the call results.

### Output
`answers`.

### Quality Gate
- Every output is built from a call result, never estimated.

---

## Exit Criteria

- `answers` is returned.

## Error Handling

- **No API key:** The run stops and names set_anthropic_key.

## Worked Example

Fifteen questions asked, fifteen answers with 3 to 6 cited links each.

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
