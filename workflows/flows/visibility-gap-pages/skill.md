# Map Each Unanswered Buyer Question to a Page

**One-line description:** For each buyer question where the business was never named, name the page that should answer it, check it, and write the change.

**Execution Pattern:** Phase Pipeline

**Runs:** by Claude in the chat; the workflow pauses here and resumes with the outputs.

---

## Inputs

- `visibility_run` (object, required): Output of `visibility-record`.
- `business_site` (string, required): The business's site URL.

---

## Outputs

- `page_actions` (object[]): Rows: `question`, `page`, `action`.

---

## Phase 1: Match

### Entry Criteria
- `visibility_run` lists never-named questions.

### Actions
1. Call `assistants_index` on `business_site`; match each question to a page or mark a page to build.

### Output
Question-to-page rows.

### Quality Gate
- Every never-named question has a row.

---

## Phase 2: Check

### Entry Criteria
- Rows exist.

### Actions
1. Call `money_page_check` on each existing page with the question's service and town phrase.
2. Write the action: a 40 to 60 word answer under a question heading, plus facts only the business can state.

### Output
`page_actions`.

### Quality Gate
- Each action is specific to its page.

---

## Exit Criteria

- `page_actions` covers every never-named question.

## Error Handling

- **No never-named questions:** Return an empty list.

## Worked Example

'How much does tankless installation cost' maps to the tankless page; add the price range.

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
