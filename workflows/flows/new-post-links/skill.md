# Plan the Internal Links for a Published Post

**One-line description:** Find the posts and money page a new post should link to and the older posts that should link to it, each with its anchor sentence.

**Execution Pattern:** Phase Pipeline

**Runs:** by the MCP; every action below is a tool call.

---

## Inputs

- `business_site` (string, required): The business's site URL.
- `post_url` (string, required): The new post's live URL.

---

## Outputs

- `link_plan` (object): The internal link plan.

---

## Phase 1: Run the Tools

### Entry Criteria
- Inputs present: `business_site`, `post_url`.

### Actions
1. Call `internal_link_plan`(site=`business_site`, new_post_url=`post_url`) and keep the result as `plan`.

### Output
One result per call.

### Quality Gate
- The plan is present.
- A required call that cannot run stops the workflow and names the setup tool.

---

## Phase 2: Assemble

### Entry Criteria
- Every required call ran.

### Actions
1. Build `link_plan` from the call results.

### Output
`link_plan`.

### Quality Gate
- Every output is built from a call result, never estimated.

---

## Exit Criteria

- `link_plan` is returned.

## Error Handling

- **Fewer than three posts:** The plan links what exists.

## Worked Example

A post on water heater lifespan: link out to the replacement page; three leak posts link in.

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
