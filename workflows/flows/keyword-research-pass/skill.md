# Research, Cluster and Trend a Set of Seed Keywords

**One-line description:** Expand seed keywords with volume and intent, group the results into themes, and read the trend of the top terms.

**Execution Pattern:** Phase Pipeline

**Runs:** by the MCP; every action below is a tool call.

---

## Inputs

- `seed_keywords` (string[], required): Seed terms, comma separated.
- `locations` (string[], optional): Towns, cities or states to target.

---

## Outputs

- `keyword_data` (object): Results keyed `research`, `clusters`, `trends`.

---

## Phase 1: Run the Tools

### Entry Criteria
- Inputs present: `seed_keywords`, `locations`.

### Actions
1. Call `keyword_research`(seed_keywords=`seed_keywords`, locations=`locations`) and keep the result as `research`.
2. Call `cluster_keywords`(keywords=`research`) and keep the result as `clusters`.
3. Call `trend_index`(keywords=`research`) and keep the result as `trends` (optional: a refusal or missing setup is recorded and the flow continues).

### Output
One result per call.

### Quality Gate
- Research and clusters are present; trends may be absent when the trends service refuses.
- A required call that cannot run stops the workflow and names the setup tool.

---

## Phase 2: Assemble

### Entry Criteria
- Every required call ran.

### Actions
1. Build `keyword_data` from the call results.

### Output
`keyword_data`.

### Quality Gate
- Every output is built from a call result, never estimated.

---

## Exit Criteria

- `keyword_data` is returned.

## Error Handling

- **Google Ads not connected:** The run stops and names connect_google_ads.

## Worked Example

Seeds 'roof repair, roof replacement' in Austin return 180 terms in 9 themes.

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
