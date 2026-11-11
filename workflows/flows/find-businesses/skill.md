# Pull Local Businesses From Open Map Data

**One-line description:** Pull independent businesses of one category in one area from OpenStreetMap, with website and phone where listed and chains dropped.

**Execution Pattern:** Phase Pipeline

**Runs:** by the MCP; every action below is a tool call.

---

## Inputs

- `area` (string, required): A town, county or city.
- `category` (string, required): A business category.

---

## Outputs

- `prospects` (object[]): Business rows.
- `source_counts` (object): Counts and attribution.

---

## Phase 1: Run the Tools

### Entry Criteria
- Inputs present: `area`, `category`.

### Actions
1. Call `find_businesses`(area=`area`, category=`category`) and keep the result as `found`.

### Output
One result per call.

### Quality Gate
- Rows are present or the result states none were found.
- A required call that cannot run stops the workflow and names the setup tool.

---

## Phase 2: Assemble

### Entry Criteria
- Every required call ran.

### Actions
1. Build `prospects`, `source_counts` from the call results.

### Output
`prospects`, `source_counts`.

### Quality Gate
- Every output is built from a call result, never estimated.

---

## Exit Criteria

- `prospects`, `source_counts` is returned.

## Error Handling

- **Area does not resolve:** The result says so; use a county or city name.

## Worked Example

Bakeries in Hoboken: 31 found, 19 with a website, 22 with a phone.

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
