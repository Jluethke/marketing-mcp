# Summarize a Client Portfolio

**One-line description:** Write the portfolio summary: which clients moved, which platforms need setup, and the one action per client that matters most.

**Execution Pattern:** Phase Pipeline

**Runs:** by Claude in the chat; the workflow pauses here and resumes with the outputs.

---

## Inputs

- `portfolio` (object, required): Output of `portfolio-kpis`.

---

## Outputs

- `rollup` (object): `{movers, needs_setup, actions}`.

---

## Phase 1: Read

### Entry Criteria
- `portfolio` is present.

### Actions
1. List each client's change on calls, leads and spend; list platforms returning needs setup.

### Output
Per-client changes.

### Quality Gate
- Every client appears.

---

## Phase 2: Decide

### Entry Criteria
- Per-client changes exist.

### Actions
1. Write one action per client tied to the number that motivates it.

### Output
`rollup`.

### Quality Gate
- Each action cites its number.

---

## Exit Criteria

- `rollup` covers every client.

## Error Handling

- **A platform failed for every client:** Lead the summary with the setup step.

## Worked Example

Client B: calls down 18 percent while spend held; action: check the landing page form.

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
