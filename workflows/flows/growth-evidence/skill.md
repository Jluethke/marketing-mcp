# Collect the Evidence of How a Company Grew

**One-line description:** Read the dated timeline of a company's growth moves from archived copies of its site, the stack it runs today, brand search interest, and its live ads.

**Execution Pattern:** Phase Pipeline

**Runs:** by the MCP; every action below is a tool call.

---

## Inputs

- `company` (string, required): The company name.
- `domain` (string, required): Its primary domain.

---

## Outputs

- `growth_evidence` (object): Results keyed `teardown`, `today`, `interest`, `ads`.

---

## Phase 1: Run the Tools

### Entry Criteria
- Inputs present: `company`, `domain`.

### Actions
1. Call `growth_teardown`(domain=`domain`) and keep the result as `teardown`.
2. Call `growth_signals`(url=`domain`) and keep the result as `today`.
3. Call `trend_index`(keywords=[`company`], timeframe='today 5-y') and keep the result as `interest` (optional: a refusal or missing setup is recorded and the flow continues).
4. Call `meta_ad_library`(search_terms=`company`) and keep the result as `ads` (optional: a refusal or missing setup is recorded and the flow continues).

### Output
One result per call.

### Quality Gate
- The teardown and today's stack are present; interest and ads may be absent.
- A required call that cannot run stops the workflow and names the setup tool.

---

## Phase 2: Assemble

### Entry Criteria
- Every required call ran.

### Actions
1. Build `growth_evidence` from the call results.

### Output
`growth_evidence`.

### Quality Gate
- Every output is built from a call result, never estimated.

---

## Exit Criteria

- `growth_evidence` is returned.

## Error Handling

- **Archive slow:** The teardown reports the snapshots it skipped.

## Worked Example

A software company: affiliate program first seen between two captures in 2024.

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
