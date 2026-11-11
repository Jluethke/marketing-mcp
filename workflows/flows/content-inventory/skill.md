# Inventory a Site's Pages and Their Overlap

**One-line description:** List every page with its title and description by section, and find pages that duplicate each other.

**Execution Pattern:** Phase Pipeline

**Runs:** by the MCP; every action below is a tool call.

---

## Inputs

- `business_site` (string, required): The business's site URL.

---

## Outputs

- `content_inventory` (object): Results keyed `index`, `duplicates`.

---

## Phase 1: Run the Tools

### Entry Criteria
- Inputs present: `business_site`.

### Actions
1. Call `assistants_index`(url=`business_site`) and keep the result as `index`.
2. Call `duplicate_audit`(start_url=`business_site`) and keep the result as `duplicates`.

### Output
One result per call.

### Quality Gate
- Both results are present.
- A required call that cannot run stops the workflow and names the setup tool.

---

## Phase 2: Assemble

### Entry Criteria
- Every required call ran.

### Actions
1. Build `content_inventory` from the call results.

### Output
`content_inventory`.

### Quality Gate
- Every output is built from a call result, never estimated.

---

## Exit Criteria

- `content_inventory` is returned.

## Error Handling

- **No sitemap:** Both tools crawl from the homepage and say so.

## Worked Example

Two lifespan posts are 0.86 similar.

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
