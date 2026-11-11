# Draft a Post From the Owner's Answers to One Customer Question

**One-line description:** Draft a post of 750 words or more that answers one real customer question in its first sentence, built from the owner's own answers.

**Execution Pattern:** Phase Pipeline

**Runs:** by Claude in the chat; the workflow pauses here and resumes with the outputs.

---

## Inputs

- `business_site` (string, required): The business's site URL.
- `service` (string, required): The service the post supports.
- `owner_answers` (object, required): The owner's answers on the question: the short answer, common mistakes, a real job with its numbers, what changes price or timing, when not to hire.
- `city` (string, optional): The main town served.

---

## Outputs

- `post_draft` (object): `{title, slug, body, money_page_url}`.

---

## Phase 1: Frame

### Entry Criteria
- `owner_answers` is present.

### Actions
1. Take the customer question the answers address and write it as the title in searcher wording.

### Output
The title.

### Quality Gate
- The title is a question a customer asks.

---

## Phase 2: Draft

### Entry Criteria
- The title exists.

### Actions
1. Answer the title in the first sentence; question-shaped H2s with a 40 to 60 word answer under each; 750 words or more; every number from `owner_answers` or with a source.
2. Find the money page for `service` on `business_site` (call `assistants_index` if needed) and link it once.

### Output
`post_draft`.

### Quality Gate
- The first sentence answers the title.

---

## Exit Criteria

- `post_draft` is ready for the copy gate.

## Error Handling

- **Answers too thin:** Draft only what the answers support and list the gaps in the draft.

## Worked Example

Question: how long does a water heater last. The post opens with the owner's range from his jobs.

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
