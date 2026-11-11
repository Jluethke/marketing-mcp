# Turn Prospects Into a Call Sheet With Real Findings

**One-line description:** Audit each prospect's site for one graded finding with evidence and write an opener per prospect that claims nothing the audit did not show.

**Execution Pattern:** Phase Pipeline

**Runs:** by the MCP; every action below is a tool call.

---

## Inputs

- `prospects` (object[], required): Business rows.
- `your_offer` (string, required): One sentence offer.

---

## Outputs

- `call_sheet` (object): The call sheet.

---

## Phase 1: Run the Tools

### Entry Criteria
- Inputs present: `prospects`, `your_offer`.

### Actions
1. Call `call_sheet`(prospects=`prospects`, your_offer=`your_offer`) and keep the result as `sheet`.

### Output
One result per call.

### Quality Gate
- The sheet is present with callable, no phone, clean and unreadable sections.
- A required call that cannot run stops the workflow and names the setup tool.

---

## Phase 2: Assemble

### Entry Criteria
- Every required call ran.

### Actions
1. Build `call_sheet` from the call results.

### Output
`call_sheet`.

### Quality Gate
- Every output is built from a call result, never estimated.

---

## Exit Criteria

- `call_sheet` is returned.

## Error Handling

- **Most sites unreadable:** The sheet lists them separately; nothing is guessed.

## Worked Example

Grade A opener: 'I looked at your site and your service pages never name your town.'

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
