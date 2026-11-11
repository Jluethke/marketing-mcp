# List a Site's Pages With Titles and Descriptions

**One-line description:** Read every page of a site with its title and description, grouped by section.

**Execution Pattern:** Phase Pipeline

**Runs:** by the MCP; every action below is a tool call.

---

## Inputs

- `business_site` (string, required): The business's site URL.

---

## Outputs

- `site_pages` (object): The page index.

---

## Phase 1: Run the Tools

### Entry Criteria
- Inputs present: `business_site`.

### Actions
1. Call `assistants_index`(url=`business_site`) and keep the result as `index`.

### Output
One result per call.

### Quality Gate
- The index is present.
- A required call that cannot run stops the workflow and names the setup tool.

---

## Phase 2: Assemble

### Entry Criteria
- Every required call ran.

### Actions
1. Build `site_pages` from the call results.

### Output
`site_pages`.

### Quality Gate
- Every output is built from a call result, never estimated.

---

## Exit Criteria

- `site_pages` is returned.

## Error Handling

- **No sitemap:** The index crawls from the homepage.

## Worked Example

42 pages in 4 sections.

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
