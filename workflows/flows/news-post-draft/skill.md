# Draft a Post Tying a News Item to the Business

**One-line description:** Write what happened, what it changes for customers and what to do, with the owner's own detail.

**Execution Pattern:** Phase Pipeline

**Runs:** by Claude in the chat; the workflow pauses here and resumes with the outputs.

---

## Inputs

- `news_item` (object, required): Output of `news-anchor`.
- `owner_notes` (string, optional): The owner's take and numbers.

---

## Outputs

- `post_draft` (object): `{title, slug, body, money_page_url}`.

---

## Phase 1: Draft

### Entry Criteria
- `news_item` is present.

### Actions
1. Open with what happened, its date and source; then the customer consequence and what to do, using `owner_notes`.

### Output
A draft.

### Quality Gate
- The item is cited with date and link.

---

## Phase 2: Tie

### Entry Criteria
- A draft exists.

### Actions
1. Link the money page the post supports once.

### Output
`post_draft`.

### Quality Gate
- The post names one next step.

---

## Exit Criteria

- `post_draft` is ready for the copy gate.

## Error Handling

- **No owner notes:** Keep to the item's facts and the business's listed services.

## Worked Example

The rebate post explains eligibility and links the heat-pump page.

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
