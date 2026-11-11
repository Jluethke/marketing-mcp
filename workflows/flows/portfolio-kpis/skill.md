# Pull KPIs for Every Configured Client

**One-line description:** Read per-client KPIs across ads, analytics and search, with a combined total.

**Execution Pattern:** Phase Pipeline

**Runs:** by the MCP; every action below is a tool call.

---

## Inputs

- `days` (number, optional): The reporting window in days (default 30).

---

## Outputs

- `portfolio` (object): The clients overview result.

---

## Phase 1: Run the Tools

### Entry Criteria
- Inputs present: `days`.

### Actions
1. Call `clients_overview`(days=`days`) and keep the result as `overview`.

### Output
One result per call.

### Quality Gate
- The overview is present.
- A required call that cannot run stops the workflow and names the setup tool.

---

## Phase 2: Assemble

### Entry Criteria
- Every required call ran.

### Actions
1. Build `portfolio` from the call results.

### Output
`portfolio`.

### Quality Gate
- Every output is built from a call result, never estimated.

---

## Exit Criteria

- `portfolio` is returned.

## Error Handling

- **No clients configured:** The result says so; add clients with add_client.

## Worked Example

Four clients: two up on calls week over week, one with Meta needing setup.

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
