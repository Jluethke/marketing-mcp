# Plan the Next Posts From Topic Gaps

**One-line description:** Group pages into topics tied to money pages, list the buyer questions no page answers, and order the next eight posts.

**Execution Pattern:** Phase Pipeline

**Runs:** by Claude in the chat; the workflow pauses here and resumes with the outputs.

---

## Inputs

- `content_inventory` (object, required): Output of `content-inventory`.

---

## Outputs

- `coverage_map` (object[]): Rows: `topic`, `pages`, `money_page`, `gap`.
- `post_queue` (object[]): Eight posts in order.

---

## Phase 1: Map

### Entry Criteria
- `content_inventory` is present.

### Actions
1. Group pages into topics; name each topic's money page; merge or redirect the weaker page of each duplicate group.

### Output
`coverage_map`.

### Quality Gate
- Every page belongs to one topic.

---

## Phase 2: Queue

### Entry Criteria
- `coverage_map` exists.

### Actions
1. List unanswered questions on cost, comparisons, problems, reviews and best-of; order eight posts by closeness to a hire.

### Output
`post_queue`.

### Quality Gate
- Each post names its money page.

---

## Exit Criteria

- `coverage_map` and `post_queue` are complete.

## Error Handling

- **Inventory empty:** Start the queue from the services list.

## Worked Example

Gap: tank versus tankless for a family of four; queued first.

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
