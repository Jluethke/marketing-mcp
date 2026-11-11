# Copyright (c) 2026 The Wayfinder Trust - Jonathan Luethke
# All Rights Reserved. Proprietary and Confidential.
"""Build the marketing MCP's workflows in skill-chain format from one contract.

Every flow and chain is declared below. Manifests, chain wiring, edges, entry
inputs and terminal outputs are computed from the contract so they cannot drift,
and tool flows get their skill.md phases from their calls. Run after editing:

    python workflows/build_workflows.py

then `python test_workflows.py` validates every chain against the server's tools.
"""
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
FLOWS_DIR = os.path.join(HERE, "flows")
CHAINS_DIR = os.path.join(HERE, "chains")
FOOTER = "Copyright 2024-present The Wayfinder Trust. All rights reserved."


def tool_flow(name, title, desc, tags, inputs, outputs, calls, output_map, gate, example, errors):
    return dict(name=name, title=title, desc=desc, tags=tags, inputs=inputs, outputs=outputs,
                runner="tool", calls=calls, output_map=output_map, gate=gate, example=example,
                errors=errors)


def assistant_flow(name, title, desc, tags, inputs, outputs, phases, example, errors, exit_):
    return dict(name=name, title=title, desc=desc, tags=tags, inputs=inputs, outputs=outputs,
                runner="assistant", phases=phases, example=example, errors=errors, exit=exit_)


def call(tool, as_, optional=False, **args):
    c = {"tool": tool, "as": as_, "args": args}
    if optional:
        c["optional"] = True
    return c


S = "string"
# ------------------------------------------------------------------ flows ----
FLOWS = [
    # ---- site diagnosis
    tool_flow("site-foundation-check", "Check That Search Engines and AI Assistants Can Find and Read a Site",
              "Read robots.txt, the sitemap, HTTPS, click depth, the analytics tag, AI crawler access and the "
              "Search Console sitemap status for a site, and return every result with its evidence.",
              ["seo", "technical-seo", "audit"],
              [("site_url", S, True, "The site's homepage URL.")],
              [("foundation_report", "object", "Results keyed `sitemap`, `http`, `depth`, `stack`, `search_console`.")],
              [call("sitemap_hygiene", "sitemap", url="$site_url"),
               call("http_check", "http", url="$site_url"),
               call("crawl_depth", "depth", start_url="$site_url", max_pages=100),
               call("growth_signals", "stack", url="$site_url"),
               call("gsc_list_sitemaps", "search_console", optional=True, site_url="$site_url")],
              {"foundation_report": {"sitemap": "$sitemap", "http": "$http", "depth": "$depth",
                                     "stack": "$stack", "search_console": "$search_console"}},
              "Each of the five results is present; Search Console may read needs setup when it is not connected.",
              "A plumber's site: every sitemap lastmod is one build date, the water-heater page sits four clicks "
              "deep, and no analytics tag is present.",
              [("Site behind a bot wall", "The page tools report the wall; the report carries it as found.")]),
    assistant_flow("foundation-fix-plan", "Turn a Foundation Report Into an Ordered Fix Plan",
                   "Order the failures in a foundation report by what blocks discovery first, and write each fix "
                   "as one action with where it is done and the tool result that confirms it.",
                   ["seo", "planning"],
                   [("foundation_report", "object", True, "Output of `site-foundation-check`.")],
                   [("fix_plan", "object[]", "Ordered rows: `fix`, `where`, `confirm_with`.")],
                   [("Order", ["`foundation_report` is present."],
                     ["List every failure: crawlers blocked, sitemap missing or invalid, lastmod stamped, noindex "
                      "or canonical conflicts, HTTPS or redirect faults, pages deeper than two clicks, orphan "
                      "pages, no analytics tag, Search Console not set up or sitemap not submitted.",
                      "Order them: discovery blockers first, then reach, then measurement."],
                     "An ordered list.", ["Every failure in `foundation_report` appears once."]),
                    ("Write", ["The ordered list exists."],
                     ["Write each `fix` as one action, `where` it is done (host, CMS, DNS, robots.txt), and "
                      "`confirm_with`: the tool to rerun and the result that means done."],
                     "`fix_plan`.", ["Every row names a tool or an observable result in `confirm_with`."])],
                   "Depth failure: link the water-heater page from the services menu; confirm with crawl_depth "
                   "showing depth 1.",
                   [("No failures", "Return an empty `fix_plan` and state that the foundations pass.")],
                   ["`fix_plan` covers every failure."]),
    # ---- full SEO review
    tool_flow("seo-review-checks", "Run the On-Page Checks for One URL",
              "Score a page and read its on-page audit, technical health, readability and broken links.",
              ["seo", "audit"],
              [("url", S, True, "The page to review.")],
              [("review_findings", "object", "Results keyed `score`, `audit`, `http`, `content`, `links`.")],
              [call("seo_score", "score", url="$url"), call("seo_audit", "audit", url="$url"),
               call("http_check", "http", url="$url"), call("content_analysis", "content", url="$url"),
               call("check_links", "links", url="$url")],
              {"review_findings": {"score": "$score", "audit": "$audit", "http": "$http", "content": "$content",
                                   "links": "$links"}},
              "All five results are present.",
              "A service page scores 71 (C): no meta description, two images without alt text, one broken link.",
              [("Page unreadable", "Each check reports the wall or the status code and the review says so.")]),
    assistant_flow("seo-fix-list", "Rank the Fixes From an On-Page Review",
                   "Turn the on-page review results into the five fixes that matter most, each tied to its finding.",
                   ["seo", "planning"],
                   [("review_findings", "object", True, "Output of `seo-review-checks`.")],
                   [("fix_list", "object[]", "Five rows: `fix`, `finding`, `impact`.")],
                   [("Collect", ["`review_findings` is present."],
                     ["Gather every issue across the score, audit, technical, readability and link results."],
                     "The issue list.", ["Each issue names the result it came from."]),
                    ("Rank", ["The issue list exists."],
                     ["Rank by effect on ranking and on a reader: missing keyword or title first, then crawl and "
                      "HTTPS faults, then readability, then minor tags.", "Keep the top five."],
                     "`fix_list`.", ["Each fix cites its `finding`."])],
                   "Fix 1: add a meta description stating the service and town (audit: meta description missing).",
                   [("Page unreadable", "Return one row saying the page could not be read and why.")],
                   ["`fix_list` holds five ranked fixes."]),
    # ---- keyword plan
    tool_flow("keyword-research-pass", "Research, Cluster and Trend a Set of Seed Keywords",
              "Expand seed keywords with volume and intent, group the results into themes, and read the trend of "
              "the top terms.",
              ["seo", "keyword-research", "paid-search"],
              [("seed_keywords", "string[]", True, "Seed terms, comma separated."),
               ("locations", "string[]", False, "Towns, cities or states to target.")],
              [("keyword_data", "object", "Results keyed `research`, `clusters`, `trends`.")],
              [call("keyword_research", "research", seed_keywords="$seed_keywords", locations="$locations"),
               call("cluster_keywords", "clusters", keywords="$research.keywords[*].keyword"),
               call("trend_index", "trends", optional=True, keywords="$research.keywords[*].keyword[:5]")],
              {"keyword_data": {"research": "$research", "clusters": "$clusters", "trends": "$trends"}},
              "Research and clusters are present; trends may be absent when the trends service refuses.",
              "Seeds 'roof repair, roof replacement' in Austin return 180 terms in 9 themes.",
              [("Google Ads not connected", "The run stops and names connect_google_ads.")]),
    assistant_flow("keyword-plan-writeup", "Write a Keyword Plan From Research Results",
                   "Turn researched, clustered keywords into a plan: the themes, the priority terms per theme, the "
                   "trending themes, and the paid or organic split.",
                   ["seo", "planning", "keyword-research"],
                   [("keyword_data", "object", True, "Output of `keyword-research-pass`.")],
                   [("keyword_plan", "object", "`{themes, priority_terms, trending, split}`.")],
                   [("Prioritize", ["`keyword_data` is present."],
                     ["Per theme, list the top terms by the research priority (volume and intent).",
                      "Mark themes whose trend is rising."],
                     "Themes with priority terms.", ["Every theme has at least one priority term."]),
                    ("Split", ["Themes exist."],
                     ["Call `paid_vs_organic` on the research rows and attach each term's box."],
                     "`keyword_plan`.", ["Terms without difficulty are listed as unclassified, never guessed."])],
                   "Theme 'roof repair': 'emergency roof repair austin' leads; the box is ads now, SEO long-term.",
                   [("No research rows", "Return the plan empty and name the missing connection.")],
                   ["`keyword_plan` is complete."]),
    # ---- client rollup
    tool_flow("portfolio-kpis", "Pull KPIs for Every Configured Client",
              "Read per-client KPIs across ads, analytics and search, with a combined total.",
              ["reporting", "agency"],
              [("days", "number", False, "The reporting window in days (default 30).")],
              [("portfolio", "object", "The clients overview result.")],
              [call("clients_overview", "overview", days="$days")],
              {"portfolio": "$overview"},
              "The overview is present.",
              "Four clients: two up on calls week over week, one with Meta needing setup.",
              [("No clients configured", "The result says so; add clients with add_client.")]),
    assistant_flow("rollup-summary", "Summarize a Client Portfolio",
                   "Write the portfolio summary: which clients moved, which platforms need setup, and the one "
                   "action per client that matters most.",
                   ["reporting", "agency"],
                   [("portfolio", "object", True, "Output of `portfolio-kpis`.")],
                   [("rollup", "object", "`{movers, needs_setup, actions}`.")],
                   [("Read", ["`portfolio` is present."],
                     ["List each client's change on calls, leads and spend; list platforms returning needs setup."],
                     "Per-client changes.", ["Every client appears."]),
                    ("Decide", ["Per-client changes exist."],
                     ["Write one action per client tied to the number that motivates it."],
                     "`rollup`.", ["Each action cites its number."])],
                   "Client B: calls down 18 percent while spend held; action: check the landing page form.",
                   [("A platform failed for every client", "Lead the summary with the setup step.")],
                   ["`rollup` covers every client."]),
    # ---- connect
    tool_flow("platform-status", "Read Which Marketing Platforms Are Connected",
              "Report which platforms are ready and the next step for each one that is not.",
              ["setup"],
              [("live_check", "boolean", False, "Also make a live call to each connected platform.")],
              [("platform_status", "object", "The setup check result.")],
              [call("setup_check", "status", live="$live_check")],
              {"platform_status": "$status"},
              "The status is present.",
              "Search tools ready; Google Ads missing a developer token; Meta not connected.",
              [("Library missing", "The status names the package to install.")]),
    assistant_flow("connect-walkthrough", "Connect the Missing Platforms From Chat",
                   "Walk through connecting each platform that is not ready, asking only for the one credential "
                   "each connect tool needs.",
                   ["setup"],
                   [("platform_status", "object", True, "Output of `platform-status`.")],
                   [("connections", "object[]", "Rows: `platform`, `tool`, `result`.")],
                   [("Plan", ["`platform_status` is present."],
                     ["For each platform not ready, name the connect tool: connect_google_ads, connect_meta, "
                      "connect_analytics, set_pagespeed_key, set_anthropic_key."],
                     "The connect list.", ["Every platform not ready has a tool."]),
                    ("Connect", ["The connect list exists."],
                     ["Ask for one credential at a time in plain language, call the tool, record the result.",
                      "Run `setup_check` at the end."],
                     "`connections`.", ["The final setup check is recorded."])],
                   "Meta: ask for the access token, call connect_meta, setup check shows Meta ready.",
                   [("A credential is rejected", "Record the error and move to the next platform.")],
                   ["`connections` lists every attempt."]),
    # ---- growth blueprint
    tool_flow("growth-evidence", "Collect the Evidence of How a Company Grew",
              "Read the dated timeline of a company's growth moves from archived copies of its site, the stack "
              "it runs today, brand search interest, and its live ads.",
              ["growth", "competitive-analysis"],
              [("company", S, True, "The company name."), ("domain", S, True, "Its primary domain.")],
              [("growth_evidence", "object", "Results keyed `teardown`, `today`, `interest`, `ads`.")],
              [call("growth_teardown", "teardown", domain="$domain"),
               call("growth_signals", "today", url="$domain"),
               call("trend_index", "interest", optional=True, keywords=["$company"], timeframe="today 5-y"),
               call("meta_ad_library", "ads", optional=True, search_terms="$company")],
              {"growth_evidence": {"teardown": "$teardown", "today": "$today", "interest": "$interest",
                                   "ads": "$ads"}},
              "The teardown and today's stack are present; interest and ads may be absent.",
              "A software company: affiliate program first seen between two captures in 2024.",
              [("Archive slow", "The teardown reports the snapshots it skipped.")]),
    assistant_flow("growth-timeline", "Lay Out a Company's Growth Timeline by Lane",
                   "Turn growth evidence into one dated timeline by lane, each row tied to its source, and name the "
                   "moves a small team can copy.",
                   ["growth", "competitive-analysis"],
                   [("growth_evidence", "object", True, "Output of `growth-evidence`."),
                    ("company", S, True, "The company name.")],
                   [("growth_timeline", "object", "`{rows, copyable_moves}`.")],
                   [("Lay Out", ["`growth_evidence` is present."],
                     ["Lanes: ads and tracking, social, search, AI search, affiliates and referral, fundraising.",
                      "Search the web for the funding rounds and launch dates of `company`, one link per date.",
                      "Where a tool lists something as not covered, the cell reads no public signal."],
                     "Timeline rows.", ["Every row carries a date or date bracket and its source."]),
                    ("Conclude", ["Rows exist."],
                     ["Name the three moves before the steepest growth in new pages or brand interest, and which a "
                      "small team can copy."],
                     "`growth_timeline`.", ["No estimate fills a cell without a source."])],
                   "Affiliates lane: program first seen between March and June 2024 (archive captures).",
                   [("Thin archive", "State how many captures were read.")],
                   ["`growth_timeline` is complete."]),
    # ---- weekly loop
    assistant_flow("owner-interview-post", "Draft a Post From the Owner's Answers to One Customer Question",
                   "Draft a post of 750 words or more that answers one real customer question in its first "
                   "sentence, built from the owner's own answers.",
                   ["content", "seo", "blogging"],
                   [("business_site", S, True, "The business's site URL."),
                    ("service", S, True, "The service the post supports."),
                    ("owner_answers", "object", True, "The owner's answers on the question: the short answer, "
                     "common mistakes, a real job with its numbers, what changes price or timing, when not to hire."),
                    ("city", S, False, "The main town served.")],
                   [("post_draft", "object", "`{title, slug, body, money_page_url}`.")],
                   [("Frame", ["`owner_answers` is present."],
                     ["Take the customer question the answers address and write it as the title in searcher wording."],
                     "The title.", ["The title is a question a customer asks."]),
                    ("Draft", ["The title exists."],
                     ["Answer the title in the first sentence; question-shaped H2s with a 40 to 60 word answer under "
                      "each; 750 words or more; every number from `owner_answers` or with a source.",
                      "Find the money page for `service` on `business_site` (call `assistants_index` if needed) and "
                      "link it once."],
                     "`post_draft`.", ["The first sentence answers the title."])],
                   "Question: how long does a water heater last. The post opens with the owner's range from his jobs.",
                   [("Answers too thin", "Draft only what the answers support and list the gaps in the draft.")],
                   ["`post_draft` is ready for the copy gate."]),
    assistant_flow("copy-gate", "Gate a Draft for Plain Language and Sourced Numbers",
                   "Run the copy check on a draft, rewrite every failing line, and rerun until it passes.",
                   ["editing", "quality-gate", "content"],
                   [("draft", "object", True, "Any draft with a `body` field."),
                    ("house_rules", "object", False, "Extra banned words or rules.")],
                   [("gated_draft", "object", "The draft with failing lines rewritten and `verdict` pass."),
                    ("copy_report", "object[]", "Rows: `line`, `rule`, `before`, `after`.")],
                   [("Scan", ["`draft` has a body."],
                     ["Call `copy_check` on the body with `house_rules`."],
                     "The issue list.", ["Every issue names its rule and line."]),
                    ("Rewrite", ["The issue list exists."],
                     ["Rewrite each failing line to state the fact plainly; give each number its source or remove it.",
                      "Call `copy_check` again until it passes."],
                     "`gated_draft` and `copy_report`.", ["The last check passes."])],
                   "A line praising the team with hype adjectives becomes 'two licensed plumbers answer from 7 a.m.'",
                   [("A number has no source", "Remove it and keep the sentence true.")],
                   ["`gated_draft` passes `copy_check`."]),
    tool_flow("money-page-evidence", "Collect the Evidence for This Week's Money Page",
              "List the page topics competitors have and the site lacks, check one money page for its keyword, and "
              "compare it with the competitors' matching pages.",
              ["seo", "competitive-analysis"],
              [("business_site", S, True, "The business's site URL."),
               ("competitor_sites", "string[]", True, "The top three competitors' sites."),
               ("money_page_url", S, True, "The money page under review."),
               ("target_keyword", S, True, "Its service and city phrase."),
               ("competitor_pages", "string[]", True, "The competitors' pages for the same service.")],
              [("money_page_evidence", "object", "Results keyed `missing`, `page_check`, `gap`.")],
              [call("missing_pages", "missing", site="$business_site", competitor_sites="$competitor_sites"),
               call("money_page_check", "page_check", url="$money_page_url", keyword="$target_keyword"),
               call("competitor_page_gap", "gap", url="$money_page_url", competitor_urls="$competitor_pages",
                    keyword="$target_keyword")],
              {"money_page_evidence": {"missing": "$missing", "page_check": "$page_check", "gap": "$gap"}},
              "All three results are present.",
              "Two of three competitors have a tankless page; the replacement page never states its town.",
              [("Competitor blocks readers", "The gap lists it as unreadable and compares the rest.")]),
    assistant_flow("money-page-decision", "Choose This Week's Money Page Work",
                   "From the money page evidence, choose one page to build or fix this week and list its changes.",
                   ["seo", "planning"],
                   [("money_page_evidence", "object", True, "Output of `money-page-evidence`.")],
                   [("money_page_actions", "object", "`{this_week, changes, later}`.")],
                   [("Weigh", ["`money_page_evidence` is present."],
                     ["A keyword missing from the page's visible text is the first fix.",
                      "Compare that with the missing page most competitors have."],
                     "Candidates.", ["Each candidate cites its evidence."]),
                    ("Choose", ["Candidates exist."],
                     ["Pick one; list the changes using only facts the owner has approved; queue the rest."],
                     "`money_page_actions`.", ["`this_week` names one page."])],
                   "This week: build the tankless page; later: add the town to the replacement page.",
                   [("Evidence empty", "Choose the page with the keyword missing.")],
                   ["`money_page_actions` names one page and its changes."]),
    assistant_flow("share-captions", "Write the Share Captions for a Post",
                   "Write one caption with the link for each public profile the business has and for its Business "
                   "Profile, each passing the copy check.",
                   ["social-media", "content"],
                   [("gated_draft", "object", True, "The post as it will be published."),
                    ("profiles", "string[]", True, "The business's public profiles."),
                    ("post_url", S, False, "The post's URL once live.")],
                   [("captions", "object[]", "Rows: `profile`, `caption`.")],
                   [("Write", ["`gated_draft` is present."],
                     ["One caption stating the question the post answers and one fact from it, adapted per profile "
                      "in `profiles`; include `post_url` when given."],
                     "Draft captions.", ["One caption per profile."]),
                    ("Check", ["Draft captions exist."], ["Call `copy_check` on each caption."],
                     "`captions`.", ["Every caption passes."])],
                   "Facebook: 'How long does a water heater last? From our last 200 replacements: 8 to 12 years.'",
                   [("No profiles", "Write the Business Profile caption only.")],
                   ["`captions` covers every profile."]),
    # ---- new post links
    tool_flow("new-post-links", "Plan the Internal Links for a Published Post",
              "Find the posts and money page a new post should link to and the older posts that should link to it, "
              "each with its anchor sentence.",
              ["seo", "internal-linking"],
              [("business_site", S, True, "The business's site URL."),
               ("post_url", S, True, "The new post's live URL.")],
              [("link_plan", "object", "The internal link plan.")],
              [call("internal_link_plan", "plan", site="$business_site", new_post_url="$post_url")],
              {"link_plan": "$plan"},
              "The plan is present.",
              "A post on water heater lifespan: link out to the replacement page; three leak posts link in.",
              [("Fewer than three posts", "The plan links what exists.")]),
    # ---- client expectations
    assistant_flow("client-expectations", "Write the SEO Expectations Note a Client Signs",
                   "Write a one-page note that sets SEO timing and success measures at signing, with every figure "
                   "sourced and dated.",
                   ["client-management", "seo"],
                   [("service", S, True, "The engagement, for example SEO or SEO with paid search.")],
                   [("expectations_note", "object", "`{title, body}`.")],
                   [("Draft", ["`service` is named."],
                     ["Weeks 1 to 4: indexing and fixes, no ranking movement. Months 2 and 3: long-tail terms "
                      "appear, impressions before clicks. Months 3 to 6: competitive terms move if reviews and links "
                      "move. Months 6 to 12: compounding.",
                      "Paid search converts from day one; organic does not. Success is calls, bookings and qualified "
                      "leads, judged monthly."],
                     "A draft.", ["Every window states what happens and what is reported."]),
                    ("Source", ["A draft exists."],
                     ["Search the web for any industry figure before it goes in; cite it with date and link, or drop it."],
                     "`expectations_note`.", ["No figure lacks a dated source."])],
                   "Month 2 report line: impressions for 14 new question terms; clicks follow.",
                   [("Guarantee requested", "State what is promised instead: the work, the cadence and the report.")],
                   ["`expectations_note` is ready to sign."]),
    # ---- prospect pipeline
    tool_flow("find-businesses", "Pull Local Businesses From Open Map Data",
              "Pull independent businesses of one category in one area from OpenStreetMap, with website and phone "
              "where listed and chains dropped.",
              ["lead-generation", "prospecting"],
              [("area", S, True, "A town, county or city."), ("category", S, True, "A business category.")],
              [("prospects", "object[]", "Business rows."), ("source_counts", "object", "Counts and attribution.")],
              [call("find_businesses", "found", area="$area", category="$category")],
              {"prospects": "$found.businesses",
               "source_counts": {"found": "$found.found", "with_website": "$found.with_website",
                                 "with_phone": "$found.with_phone", "attribution": "$found.attribution"}},
              "Rows are present or the result states none were found.",
              "Bakeries in Hoboken: 31 found, 19 with a website, 22 with a phone.",
              [("Area does not resolve", "The result says so; use a county or city name.")]),
    tool_flow("call-sheet", "Turn Prospects Into a Call Sheet With Real Findings",
              "Audit each prospect's site for one graded finding with evidence and write an opener per prospect that "
              "claims nothing the audit did not show.",
              ["lead-generation", "sales"],
              [("prospects", "object[]", True, "Business rows."), ("your_offer", S, True, "One sentence offer.")],
              [("call_sheet", "object", "The call sheet.")],
              [call("call_sheet", "sheet", prospects="$prospects", your_offer="$your_offer")],
              {"call_sheet": "$sheet"},
              "The sheet is present with callable, no phone, clean and unreadable sections.",
              "Grade A opener: 'I looked at your site and your service pages never name your town.'",
              [("Most sites unreadable", "The sheet lists them separately; nothing is guessed.")]),
    # ---- AI visibility
    tool_flow("visibility-questions", "Write the Buyer Questions That Measure AI Visibility",
              "Generate a fixed set of buyer questions for a business so the same set can be asked every month.",
              ["ai-search", "measurement"],
              [("business_name", S, True, "The business's name."), ("service", S, True, "The main service."),
               ("city", S, False, "The main town served."), ("competitors", "string[]", False, "Competitor names.")],
              [("question_set", "object", "The question set.")],
              [call("visibility_questions", "qs", business="$business_name", service="$service", city="$city",
                    competitors="$competitors")],
              {"question_set": "$qs"},
              "The set holds about fifteen questions.",
              "'Who is the best water heater installer in Hoboken?'",
              [("No competitors", "The set has no comparison questions.")]),
    assistant_flow("visibility-ask", "Ask the Buyer Questions in Clean Sessions",
                   "Have each buyer question answered in a session that has never seen this chat, with web search "
                   "on, and keep each answer with the links it relied on.",
                   ["ai-search", "measurement"],
                   [("question_set", "object", True, "Output of `visibility-questions`.")],
                   [("answers", "object[]", "Rows: `question`, `answer`, `cited_urls`.")],
                   [("Ask", ["`question_set` holds the questions."],
                     ["The answers must not come from this chat, which already knows the business. In Claude Code, "
                      "hand the questions to fresh subagents (the Agent tool with the Explore type, which starts "
                      "without this conversation or the project's instructions), at most five questions per subagent "
                      "and at most three subagents. Tell each subagent only: answer each question as a helpful "
                      "assistant would answer anyone, search the web for each, name the companies the searches "
                      "support, list the source URLs, and read no local files. Never mention which business is "
                      "being measured.",
                      "Where subagents are not available and an Anthropic API key is saved, call `ask_assistant` "
                      "with the questions instead; it asks each one in a fresh API session with web search on."],
                     "One answer per question.", ["Every question in `question_set` has an answer."]),
                    ("Collect", ["Answers exist."],
                     ["Build `answers` as rows of `question`, the full `answer` text as given, and `cited_urls`."],
                     "`answers`.", ["No answer is edited or summarized."])],
                   "Fifteen questions over three subagents; each answer names three to eight vendors with its sources.",
                   [("A subagent fails", "Ask its questions again in a new subagent.")],
                   ["`answers` covers every question."]),
    tool_flow("visibility-record", "Record an AI Visibility Run and Compare It",
              "Log whether each answer named the business, its position and the competitors named, then compare "
              "with earlier runs.",
              ["ai-search", "reporting"],
              [("business_name", S, True, "The business's name."), ("answers", "object[]", True, "The answers."),
               ("competitors", "string[]", False, "Competitor names.")],
              [("visibility_run", "object", "Results keyed `run`, `history`.")],
              [call("visibility_record", "run", business="$business_name", answers="$answers",
                    competitors="$competitors"),
               call("visibility_report", "history", business="$business_name")],
              {"visibility_run": {"run": "$run", "history": "$history"}},
              "The run and the history are present.",
              "Named in 4 of 15 answers, average position 2; a competitor named in 9.",
              [("First run", "The history holds this run only.")]),
    assistant_flow("visibility-gap-pages", "Map Each Unanswered Buyer Question to a Page",
                   "For each buyer question where the business was never named, name the page that should answer it, "
                   "check it, and write the change.",
                   ["ai-search", "seo", "content"],
                   [("visibility_run", "object", True, "Output of `visibility-record`."),
                    ("business_site", S, True, "The business's site URL.")],
                   [("page_actions", "object[]", "Rows: `question`, `page`, `action`.")],
                   [("Match", ["`visibility_run` lists never-named questions."],
                     ["Call `assistants_index` on `business_site`; match each question to a page or mark a page to build."],
                     "Question-to-page rows.", ["Every never-named question has a row."]),
                    ("Check", ["Rows exist."],
                     ["Call `money_page_check` on each existing page with the question's service and town phrase.",
                      "Write the action: a 40 to 60 word answer under a question heading, plus facts only the "
                      "business can state."],
                     "`page_actions`.", ["Each action is specific to its page."])],
                   "'How much does tankless installation cost' maps to the tankless page; add the price range.",
                   [("No never-named questions", "Return an empty list.")],
                   ["`page_actions` covers every never-named question."]),
    # ---- content coverage
    tool_flow("content-inventory", "Inventory a Site's Pages and Their Overlap",
              "List every page with its title and description by section, and find pages that duplicate each other.",
              ["content", "audit"],
              [("business_site", S, True, "The business's site URL.")],
              [("content_inventory", "object", "Results keyed `index`, `duplicates`.")],
              [call("assistants_index", "index", url="$business_site"),
               call("duplicate_audit", "duplicates", start_url="$business_site")],
              {"content_inventory": {"index": "$index", "duplicates": "$duplicates"}},
              "Both results are present.",
              "Two lifespan posts are 0.86 similar.",
              [("No sitemap", "Both tools crawl from the homepage and say so.")]),
    assistant_flow("topic-gap-plan", "Plan the Next Posts From Topic Gaps",
                   "Group pages into topics tied to money pages, list the buyer questions no page answers, and order "
                   "the next eight posts.",
                   ["content", "planning"],
                   [("content_inventory", "object", True, "Output of `content-inventory`.")],
                   [("coverage_map", "object[]", "Rows: `topic`, `pages`, `money_page`, `gap`."),
                    ("post_queue", "object[]", "Eight posts in order.")],
                   [("Map", ["`content_inventory` is present."],
                     ["Group pages into topics; name each topic's money page; merge or redirect the weaker page of "
                      "each duplicate group."],
                     "`coverage_map`.", ["Every page belongs to one topic."]),
                    ("Queue", ["`coverage_map` exists."],
                     ["List unanswered questions on cost, comparisons, problems, reviews and best-of; order eight "
                      "posts by closeness to a hire."],
                     "`post_queue`.", ["Each post names its money page."])],
                   "Gap: tank versus tankless for a family of four; queued first.",
                   [("Inventory empty", "Start the queue from the services list.")],
                   ["`coverage_map` and `post_queue` are complete."]),
    # ---- news anchored post
    assistant_flow("news-anchor", "Find One Recent Dated News Item to Anchor a Post",
                   "Search for news on a topic from the last fourteen days and pick one dated item, from its primary "
                   "source, that changes something for customers.",
                   ["content", "research"],
                   [("topic", S, True, "The topic.")],
                   [("news_item", "object", "`{headline, date, link, what_changes}`.")],
                   [("Search", ["`topic` is named."],
                     ["Search the web for dated news on `topic` from the last fourteen days; open each primary source."],
                     "Candidates.", ["Each candidate has a date and a primary link."]),
                    ("Pick", ["Candidates exist."],
                     ["Pick the one that changes a cost, a rule, a risk or a choice for customers."],
                     "`news_item`.", ["`what_changes` states the customer consequence."])],
                   "A state rebate for heat-pump water heaters announced nine days ago.",
                   [("Nothing in fourteen days", "Widen to thirty and say so.")],
                   ["`news_item` is dated and linked."]),
    assistant_flow("news-post-draft", "Draft a Post Tying a News Item to the Business",
                   "Write what happened, what it changes for customers and what to do, with the owner's own detail.",
                   ["content", "blogging"],
                   [("news_item", "object", True, "Output of `news-anchor`."),
                    ("owner_notes", S, False, "The owner's take and numbers.")],
                   [("post_draft", "object", "`{title, slug, body, money_page_url}`.")],
                   [("Draft", ["`news_item` is present."],
                     ["Open with what happened, its date and source; then the customer consequence and what to do, "
                      "using `owner_notes`."],
                     "A draft.", ["The item is cited with date and link."]),
                    ("Tie", ["A draft exists."], ["Link the money page the post supports once."],
                     "`post_draft`.", ["The post names one next step."])],
                   "The rebate post explains eligibility and links the heat-pump page.",
                   [("No owner notes", "Keep to the item's facts and the business's listed services.")],
                   ["`post_draft` is ready for the copy gate."]),
    # ---- newsletter
    tool_flow("site-pages", "List a Site's Pages With Titles and Descriptions",
              "Read every page of a site with its title and description, grouped by section.",
              ["content", "newsletter"],
              [("business_site", S, True, "The business's site URL.")],
              [("site_pages", "object", "The page index.")],
              [call("assistants_index", "index", url="$business_site")],
              {"site_pages": "$index"},
              "The index is present.",
              "42 pages in 4 sections.",
              [("No sitemap", "The index crawls from the homepage.")]),
    assistant_flow("newsletter-draft", "Draft a Weekly Newsletter on One Through-Line",
                   "Take the posts from a recent window, find the one point they share, and draft the newsletter.",
                   ["newsletter", "email-marketing"],
                   [("site_pages", "object", True, "Output of `site-pages`."),
                    ("window_days", "number", False, "Days back to include (default 7).")],
                   [("newsletter_draft", "object", "`{subject, body}`.")],
                   [("Select", ["`site_pages` is present."],
                     ["Keep posts published in the last `window_days` days, reading each post's date from the page or "
                      "the sitemap lastmod."],
                     "Recent posts.", ["Each kept post has a date source."]),
                    ("Draft", ["Recent posts exist."],
                     ["Lead with the shared point in two sentences, then one short paragraph per post with its link; "
                      "a subject line naming the point."],
                     "`newsletter_draft`.", ["Every recent post appears with its link."])],
                   "Through-line: this is the cheapest month to replace a water heater.",
                   [("No recent posts", "Return a draft that says there is nothing new this week.")],
                   ["`newsletter_draft` is ready for the copy gate."]),
]

# ------------------------------------------------------------------ chains ----
# (name, description, [(step_id, flow, {input: "user" | "user?" | "<step>.<output>"})])
CHAINS = [
    ("site-diagnosis", "Check that search engines and AI assistants can find and read a site, then order the fixes.",
     [("s1_check", "site-foundation-check", {"site_url": "user"}),
      ("s2_plan", "foundation-fix-plan", {"foundation_report": "s1_check.foundation_report"})]),
    ("full-seo-review", "Review one URL with the on-page checks and rank the five fixes that matter most.",
     [("s1_checks", "seo-review-checks", {"url": "user"}),
      ("s2_fixes", "seo-fix-list", {"review_findings": "s1_checks.review_findings"})]),
    ("keyword-plan", "Research seed keywords, cluster and trend them, and write the plan with the paid or organic split.",
     [("s1_research", "keyword-research-pass", {"seed_keywords": "user", "locations": "user?"}),
      ("s2_plan", "keyword-plan-writeup", {"keyword_data": "s1_research.keyword_data"})]),
    ("client-rollup", "Pull KPIs for every configured client and summarize who moved and what to do.",
     [("s1_kpis", "portfolio-kpis", {"days": "user?"}),
      ("s2_summary", "rollup-summary", {"portfolio": "s1_kpis.portfolio"})]),
    ("connect-what-i-have", "Find out which platforms are connected and connect the rest from chat.",
     [("s1_status", "platform-status", {"live_check": "user?"}),
      ("s2_connect", "connect-walkthrough", {"platform_status": "s1_status.platform_status"})]),
    ("growth-blueprint", "Reverse-engineer how a company grew: a dated timeline by lane, every row tied to its source.",
     [("s1_evidence", "growth-evidence", {"company": "user", "domain": "user"}),
      ("s2_timeline", "growth-timeline", {"growth_evidence": "s1_evidence.growth_evidence", "company": "user"})]),
    ("weekly-seo-loop", "The weekly loop for a local business: a post from the owner's answers, the copy gate, this "
     "week's money page, and the share captions.",
     [("s1_post", "owner-interview-post", {"business_site": "user", "service": "user", "owner_answers": "user",
                                           "city": "user?"}),
      ("s2_gate", "copy-gate", {"draft": "s1_post.post_draft", "house_rules": "user?"}),
      ("s3_evidence", "money-page-evidence", {"business_site": "user", "competitor_sites": "user",
                                              "money_page_url": "user", "target_keyword": "user",
                                              "competitor_pages": "user"}),
      ("s4_decide", "money-page-decision", {"money_page_evidence": "s3_evidence.money_page_evidence"}),
      ("s5_share", "share-captions", {"gated_draft": "s2_gate.gated_draft", "profiles": "user", "post_url": "user?"})]),
    ("new-post-links", "Plan the internal links for a post that just went live.",
     [("s1_links", "new-post-links", {"business_site": "user", "post_url": "user"})]),
    ("client-timeline", "Write the SEO expectations note a client signs, sourced and gated for plain language.",
     [("s1_note", "client-expectations", {"service": "user"}),
      ("s2_gate", "copy-gate", {"draft": "s1_note.expectations_note", "house_rules": "user?"})]),
    ("prospect-pipeline", "From an area and a category to a call sheet where every opener rests on a real finding.",
     [("s1_find", "find-businesses", {"area": "user", "category": "user"}),
      ("s2_sheet", "call-sheet", {"prospects": "s1_find.prospects", "your_offer": "user"})]),
    ("ai-visibility-baseline", "Ask an AI assistant the buyer questions in clean sessions, record how often the "
     "business is named, and map every unanswered question to a page.",
     [("s1_questions", "visibility-questions", {"business_name": "user", "service": "user", "city": "user?",
                                                "competitors": "user?"}),
      ("s2_ask", "visibility-ask", {"question_set": "s1_questions.question_set"}),
      ("s3_record", "visibility-record", {"business_name": "user", "answers": "s2_ask.answers",
                                          "competitors": "user?"}),
      ("s4_gaps", "visibility-gap-pages", {"visibility_run": "s3_record.visibility_run", "business_site": "user"})]),
    ("content-coverage-map", "Inventory a site's pages, find overlap, map topics to money pages and queue eight posts.",
     [("s1_inventory", "content-inventory", {"business_site": "user"}),
      ("s2_plan", "topic-gap-plan", {"content_inventory": "s1_inventory.content_inventory"})]),
    ("news-anchored-post", "Anchor a post to one dated news item, tie it to the business, and gate it.",
     [("s1_news", "news-anchor", {"topic": "user"}),
      ("s2_draft", "news-post-draft", {"news_item": "s1_news.news_item", "owner_notes": "user?"}),
      ("s3_gate", "copy-gate", {"draft": "s2_draft.post_draft", "house_rules": "user?"})]),
    ("newsletter-rollup", "Roll the week's posts into one newsletter on a single through-line, gated.",
     [("s1_pages", "site-pages", {"business_site": "user"}),
      ("s2_draft", "newsletter-draft", {"site_pages": "s1_pages.site_pages", "window_days": "user?"}),
      ("s3_gate", "copy-gate", {"draft": "s2_draft.newsletter_draft", "house_rules": "user?"})]),
]


def _arg_text(v):
    if isinstance(v, str):
        return "`%s`" % v[1:].split(".")[0].split("[")[0] if v.startswith("$") else repr(v)
    if isinstance(v, list):
        return "[" + ", ".join(_arg_text(x) for x in v) + "]"
    return repr(v)


def skill_md(f):
    out = ["# " + f["title"], "", "**One-line description:** " + f["desc"], "",
           "**Execution Pattern:** Phase Pipeline", "",
           "**Runs:** " + ("by the MCP; every action below is a tool call." if f["runner"] == "tool"
                            else "by Claude in the chat; the workflow pauses here and resumes with the outputs."),
           "", "---", "", "## Inputs", ""]
    for n, t, req, d in f["inputs"]:
        out.append("- `%s` (%s, %s): %s" % (n, t, "required" if req else "optional", d))
    out += ["", "---", "", "## Outputs", ""]
    for n, t, d in f["outputs"]:
        out.append("- `%s` (%s): %s" % (n, t, d))
    out += ["", "---", ""]
    if f["runner"] == "tool":
        names = ", ".join("`%s`" % i[0] for i in f["inputs"])
        acts = []
        for c in f["calls"]:
            args = ", ".join("%s=%s" % (k, _arg_text(v)) for k, v in c["args"].items())
            acts.append("Call `%s`(%s) and keep the result as `%s`%s." % (
                c["tool"], args, c["as"], " (optional: a refusal or missing setup is recorded and the flow "
                                          "continues)" if c.get("optional") else ""))
        phases = [("Run the Tools", ["Inputs present: %s." % names], acts,
                   "One result per call.", [f["gate"], "A required call that cannot run stops the workflow and "
                                                       "names the setup tool."]),
                  ("Assemble", ["Every required call ran."],
                   ["Build %s from the call results." % ", ".join("`%s`" % o[0] for o in f["outputs"])],
                   ", ".join("`%s`" % o[0] for o in f["outputs"]) + ".",
                   ["Every output is built from a call result, never estimated."])]
        exit_ = ["%s is returned." % ", ".join("`%s`" % o[0] for o in f["outputs"])]
    else:
        phases, exit_ = f["phases"], f["exit"]
    for i, (title, entry, actions, output, gates) in enumerate(phases, 1):
        out += ["## Phase %d: %s" % (i, title), "", "### Entry Criteria"] + ["- " + e for e in entry]
        out += ["", "### Actions"] + ["%d. %s" % (k, a) for k, a in enumerate(actions, 1)]
        out += ["", "### Output", output, "", "### Quality Gate"] + ["- " + g for g in gates] + ["", "---", ""]
    out += ["## Exit Criteria", ""] + ["- " + e for e in exit_]
    out += ["", "## Error Handling", ""] + ["- **%s:** %s" % (a, b) for a, b in f["errors"]]
    out += ["", "## Worked Example", "", f["example"], "", "---", "", FOOTER, ""]
    return "\n".join(out)


def manifest(f, related):
    m = {"name": f["name"], "version": "1.0.0", "domain": "marketing", "tags": f["tags"],
         "inputs": [i[0] for i in f["inputs"]], "outputs": [o[0] for o in f["outputs"]],
         "execution_pattern": "phase_pipeline", "price": "0", "license": "PRIVATE",
         "description": f["desc"], "runner": f["runner"], "related_flows": related}
    if f["runner"] == "tool":
        m["calls"] = f["calls"]
        m["output_map"] = f["output_map"]
    return m


def chain_json(name, desc, steps, flows):
    flow_of = {s[0]: s[1] for s in steps}
    jsteps, edges, entry, consumed = [], [], [], set()
    for gi, (sid, flow, wiring) in enumerate(steps, 1):
        f = flows[flow]
        inputs = {}
        for n, _t, _r, _d in f["inputs"]:
            src = wiring[n]
            if src in ("user", "user?"):
                inputs[n] = "from_user_input" if src == "user" else "from_user_input_optional"
                if n not in entry:
                    entry.append(n)
            else:
                inputs[n] = src
                frm, _, field = src.partition(".")
                consumed.add((frm, field))
                edges.append({"from_step": frm, "to_step": sid, "data_type": flow_of[frm],
                              "field_mapping": {n: field}})
        jsteps.append({"id": sid, "skill_name": flow, "inputs": inputs,
                       "outputs": {o[0]: o[0] for o in f["outputs"]}, "parallel_group": gi})
    terminal = [o for s in jsteps for o in s["outputs"] if (s["id"], o) not in consumed]
    ids = [s[0] for s in steps]
    return {"name": name, "description": desc, "steps": jsteps, "edges": edges, "entry_inputs": entry,
            "terminal_outputs": terminal, "parallel_groups": [[i] for i in ids], "estimated_cost": len(ids),
            "critical_path": ids,
            "chain_links": {"prerequisites": [], "next_chains": [],
                            "related_chains": [{"chain_name": c[0], "relationship": "complement"}
                                               for c in CHAINS if c[0] != name]}}


def main():
    flows = {f["name"]: f for f in FLOWS}
    related = {n: [] for n in flows}
    for _n, _d, steps in CHAINS:
        flow_of = {s[0]: s[1] for s in steps}
        for _sid, flow, wiring in steps:
            for inp, src in wiring.items():
                if src in ("user", "user?"):
                    continue
                frm = flow_of[src.partition(".")[0]]
                for a, b, rel, text in ((flow, frm, "fed_by", "provides %s needed here" % inp),
                                        (frm, flow, "feeds_into", "outputs consumed by %s" % flow)):
                    row = {"flow_name": b, "relationship": rel, "description": text}
                    if row not in related[a]:
                        related[a].append(row)
    for d in (FLOWS_DIR, CHAINS_DIR):
        if os.path.isdir(d):
            shutil.rmtree(d)
        os.makedirs(d)
    for f in FLOWS:
        d = os.path.join(FLOWS_DIR, f["name"])
        os.makedirs(d)
        with open(os.path.join(d, "skill.md"), "w", encoding="utf-8", newline="\n") as fh:
            fh.write(skill_md(f))
        with open(os.path.join(d, "manifest.json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(manifest(f, related[f["name"]]), fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    for name, desc, steps in CHAINS:
        with open(os.path.join(CHAINS_DIR, name + ".chain.json"), "w", encoding="utf-8", newline="\n") as fh:
            json.dump(chain_json(name, desc, steps, flows), fh, indent=2, ensure_ascii=False)
            fh.write("\n")
    print("flows: %d, chains: %d" % (len(FLOWS), len(CHAINS)))


if __name__ == "__main__":
    main()
