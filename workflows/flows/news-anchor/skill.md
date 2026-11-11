# Find One Recent Dated News Item to Anchor a Post

**One-line description:** Search for news on a topic from the last fourteen days and pick one dated item, from its primary source, that changes something for customers.

**Execution Pattern:** Phase Pipeline

**Runs:** by Claude in the chat; the workflow pauses here and resumes with the outputs.

---

## Inputs

- `topic` (string, required): The topic.

---

## Outputs

- `news_item` (object): `{headline, date, link, what_changes}`.

---

## Phase 1: Search

### Entry Criteria
- `topic` is named.

### Actions
1. Search the web for dated news on `topic` from the last fourteen days; open each primary source.

### Output
Candidates.

### Quality Gate
- Each candidate has a date and a primary link.

---

## Phase 2: Pick

### Entry Criteria
- Candidates exist.

### Actions
1. Pick the one that changes a cost, a rule, a risk or a choice for customers.

### Output
`news_item`.

### Quality Gate
- `what_changes` states the customer consequence.

---

## Exit Criteria

- `news_item` is dated and linked.

## Error Handling

- **Nothing in fourteen days:** Widen to thirty and say so.

## Worked Example

A state rebate for heat-pump water heaters announced nine days ago.

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
