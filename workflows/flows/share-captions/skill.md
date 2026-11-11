# Write the Share Captions for a Post

**One-line description:** Write one caption with the link for each public profile the business has and for its Business Profile, each passing the copy check.

**Execution Pattern:** Phase Pipeline

**Runs:** by Claude in the chat; the workflow pauses here and resumes with the outputs.

---

## Inputs

- `gated_draft` (object, required): The post as it will be published.
- `profiles` (string[], required): The business's public profiles.
- `post_url` (string, optional): The post's URL once live.

---

## Outputs

- `captions` (object[]): Rows: `profile`, `caption`.

---

## Phase 1: Write

### Entry Criteria
- `gated_draft` is present.

### Actions
1. One caption stating the question the post answers and one fact from it, adapted per profile in `profiles`; include `post_url` when given.

### Output
Draft captions.

### Quality Gate
- One caption per profile.

---

## Phase 2: Check

### Entry Criteria
- Draft captions exist.

### Actions
1. Call `copy_check` on each caption.

### Output
`captions`.

### Quality Gate
- Every caption passes.

---

## Exit Criteria

- `captions` covers every profile.

## Error Handling

- **No profiles:** Write the Business Profile caption only.

## Worked Example

Facebook: 'How long does a water heater last? From our last 200 replacements: 8 to 12 years.'

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
