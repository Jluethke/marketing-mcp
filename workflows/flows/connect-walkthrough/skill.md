# Connect the Missing Platforms From Chat

**One-line description:** Walk through connecting each platform that is not ready, asking only for the one credential each connect tool needs.

**Execution Pattern:** Phase Pipeline

**Runs:** by Claude in the chat; the workflow pauses here and resumes with the outputs.

---

## Inputs

- `platform_status` (object, required): Output of `platform-status`.

---

## Outputs

- `connections` (object[]): Rows: `platform`, `tool`, `result`.

---

## Phase 1: Plan

### Entry Criteria
- `platform_status` is present.

### Actions
1. For each platform not ready, name the connect tool: connect_google_ads, connect_meta, connect_analytics, set_pagespeed_key, set_anthropic_key.

### Output
The connect list.

### Quality Gate
- Every platform not ready has a tool.

---

## Phase 2: Connect

### Entry Criteria
- The connect list exists.

### Actions
1. Ask for one credential at a time in plain language, call the tool, record the result.
2. Run `setup_check` at the end.

### Output
`connections`.

### Quality Gate
- The final setup check is recorded.

---

## Exit Criteria

- `connections` lists every attempt.

## Error Handling

- **A credential is rejected:** Record the error and move to the next platform.

## Worked Example

Meta: ask for the access token, call connect_meta, setup check shows Meta ready.

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
