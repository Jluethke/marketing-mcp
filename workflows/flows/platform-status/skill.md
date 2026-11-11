# Read Which Marketing Platforms Are Connected

**One-line description:** Report which platforms are ready and the next step for each one that is not.

**Execution Pattern:** Phase Pipeline

**Runs:** by the MCP; every action below is a tool call.

---

## Inputs

- `live_check` (boolean, optional): Also make a live call to each connected platform.

---

## Outputs

- `platform_status` (object): The setup check result.

---

## Phase 1: Run the Tools

### Entry Criteria
- Inputs present: `live_check`.

### Actions
1. Call `setup_check`(live=`live_check`) and keep the result as `status`.

### Output
One result per call.

### Quality Gate
- The status is present.
- A required call that cannot run stops the workflow and names the setup tool.

---

## Phase 2: Assemble

### Entry Criteria
- Every required call ran.

### Actions
1. Build `platform_status` from the call results.

### Output
`platform_status`.

### Quality Gate
- Every output is built from a call result, never estimated.

---

## Exit Criteria

- `platform_status` is returned.

## Error Handling

- **Library missing:** The status names the package to install.

## Worked Example

Search tools ready; Google Ads missing a developer token; Meta not connected.

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
