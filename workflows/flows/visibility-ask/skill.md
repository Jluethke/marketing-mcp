# Ask the Buyer Questions in Clean Sessions

**One-line description:** Have each buyer question answered in a session that has never seen this chat, with web search on, and keep each answer with the links it relied on.

**Execution Pattern:** Phase Pipeline

**Runs:** by Claude in the chat; the workflow pauses here and resumes with the outputs.

---

## Inputs

- `question_set` (object, required): Output of `visibility-questions`.

---

## Outputs

- `answers` (object[]): Rows: `question`, `answer`, `cited_urls`.

---

## Phase 1: Ask

### Entry Criteria
- `question_set` holds the questions.

### Actions
1. The answers must not come from this chat, which already knows the business. In Claude Code, hand the questions to fresh subagents (the Agent tool with the Explore type, which starts without this conversation or the project's instructions), at most five questions per subagent and at most three subagents. Tell each subagent only: answer each question as a helpful assistant would answer anyone, search the web for each, name the companies the searches support, list the source URLs, and read no local files. Never mention which business is being measured.
2. Where subagents are not available and an Anthropic API key is saved, call `ask_assistant` with the questions instead; it asks each one in a fresh API session with web search on.

### Output
One answer per question.

### Quality Gate
- Every question in `question_set` has an answer.

---

## Phase 2: Collect

### Entry Criteria
- Answers exist.

### Actions
1. Build `answers` as rows of `question`, the full `answer` text as given, and `cited_urls`.

### Output
`answers`.

### Quality Gate
- No answer is edited or summarized.

---

## Exit Criteria

- `answers` covers every question.

## Error Handling

- **A subagent fails:** Ask its questions again in a new subagent.

## Worked Example

Fifteen questions over three subagents; each answer names three to eight vendors with its sources.

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
