# Draft a Weekly Newsletter on One Through-Line

**One-line description:** Take the posts from a recent window, find the one point they share, and draft the newsletter.

**Execution Pattern:** Phase Pipeline

**Runs:** by Claude in the chat; the workflow pauses here and resumes with the outputs.

---

## Inputs

- `site_pages` (object, required): Output of `site-pages`.
- `window_days` (number, optional): Days back to include (default 7).

---

## Outputs

- `newsletter_draft` (object): `{subject, body}`.

---

## Phase 1: Select

### Entry Criteria
- `site_pages` is present.

### Actions
1. Keep posts published in the last `window_days` days, reading each post's date from the page or the sitemap lastmod.

### Output
Recent posts.

### Quality Gate
- Each kept post has a date source.

---

## Phase 2: Draft

### Entry Criteria
- Recent posts exist.

### Actions
1. Lead with the shared point in two sentences, then one short paragraph per post with its link; a subject line naming the point.

### Output
`newsletter_draft`.

### Quality Gate
- Every recent post appears with its link.

---

## Exit Criteria

- `newsletter_draft` is ready for the copy gate.

## Error Handling

- **No recent posts:** Return a draft that says there is nothing new this week.

## Worked Example

Through-line: this is the cheapest month to replace a water heater.

---

Copyright 2024-present The Wayfinder Trust. All rights reserved.
