# Copyright (c) 2026 The Wayfinder Trust - Jonathan Luethke
# All Rights Reserved. Proprietary and Confidential.
"""Offline checks for the workflow engine and every chain in workflows/.

Run: python test_workflows.py
"""
import json
import os
import tempfile

os.environ["MARKETING_MCP_DATA_DIR"] = tempfile.mkdtemp(prefix="wf_test_")

import workflows as wf  # noqa: E402


def ok(name):
    print("ok  " + name)


# ---- references ---------------------------------------------------------------
scope = {"r": {"keywords": [{"keyword": "a", "v": 1}, {"keyword": "b"}, {"x": 1}, {"keyword": "c"}]},
         "s": "site", "n": None}
assert wf.resolve_ref("$s", scope) == "site"
assert wf.resolve_ref("$r.keywords[*].keyword", scope) == ["a", "b", "c"]
assert wf.resolve_ref("$r.keywords[*].keyword[:2]", scope) == ["a", "b"]
assert wf.resolve_ref("$r.keywords[0].v", scope) == 1
assert wf.resolve_ref("$r.missing.deeper", scope) is None
assert wf.resolve_ref("$n.x", scope) is None
assert wf.resolve({"k": ["$s", "lit", 3], "m": {"z": "$s"}}, scope) == {"k": ["site", "lit", 3], "m": {"z": "site"}}
ok("references resolve fields, lists, slices and missing keys")

assert wf.coerce_input("a, b ,c", "string[]") == ["a", "b", "c"]
assert wf.coerce_input('["x"]', "string[]") == ["x"]
assert wf.coerce_input("30", "number") == 30
assert wf.coerce_input('{"a": 1}', "object") == {"a": 1}
assert wf.coerce_input("plain", "string") == "plain"
ok("prompt inputs are coerced to declared types")

# ---- tool flow runner -----------------------------------------------------------
calls_seen = []


def t_list(site):
    calls_seen.append(("t_list", site))
    return {"pages": [{"url": site + "/a"}, {"url": site + "/b"}]}


def t_count(urls):
    calls_seen.append(("t_count", urls))
    return {"count": len(urls)}


def t_setup():
    return {"needs_setup": "connect it"}


def t_boom():
    raise RuntimeError("down")


reg = {"t_list": t_list, "t_count": t_count, "t_setup": t_setup, "t_boom": t_boom}
m = {"calls": [{"tool": "t_list", "as": "listed", "args": {"site": "$site"}},
               {"tool": "t_setup", "as": "opt", "optional": True, "args": {}},
               {"tool": "t_count", "as": "counted", "args": {"urls": "$listed.pages[*].url"}}],
     "output_map": {"report": {"n": "$counted.count", "first": "$listed.pages[0].url", "opt": "$opt"}}}
res = wf.run_tool_flow(m, {"site": "https://x.test"}, reg)
assert res["ok"] and res["outputs"]["report"]["n"] == 2
assert res["outputs"]["report"]["first"] == "https://x.test/a"
assert res["outputs"]["report"]["opt"] == {"needs_setup": "connect it"}
assert calls_seen[1] == ("t_count", ["https://x.test/a", "https://x.test/b"])
assert [c["ok"] for c in res["calls"]] == [True, False, True]
ok("tool flow chains call results and records an optional call that could not run")

res = wf.run_tool_flow({"calls": [{"tool": "t_setup", "as": "a", "args": {}}], "output_map": {}}, {}, reg)
assert not res["ok"] and "connect it" in res["blocked"]
res = wf.run_tool_flow({"calls": [{"tool": "t_boom", "as": "a", "args": {}}], "output_map": {}}, {}, reg)
assert not res["ok"] and "RuntimeError" in res["blocked"]
res = wf.run_tool_flow({"calls": [{"tool": "nope", "as": "a", "args": {}}], "output_map": {}}, {}, reg)
assert not res["ok"] and "not registered" in res["blocked"]
ok("a required call that cannot run blocks the flow with the reason")

# ---- every shipped chain is valid against the server's tools --------------------------
import server  # noqa: E402

tools = set(server._tool_registry())
names = wf.list_chain_names()
assert len(names) >= 14, names
problems = {n: p for n, p in wf.check_all(tools=tools).items() if p}
assert not problems, json.dumps(problems, indent=1)
ok("all %d chains pass the skill-chain checks and call only registered tools" % len(names))

for n in names:
    d = wf.describe(n)
    assert d["steps"] and d["terminal_outputs"], n
    for st in d["steps"]:
        assert st["runner"] in ("tool", "assistant"), (n, st)
ok("every chain describes its inputs, steps and outputs")

skill_dirs = os.listdir(wf.FLOWS_DIR)
for f in skill_dirs:
    with open(os.path.join(wf.FLOWS_DIR, f, "skill.md"), encoding="utf-8") as fh:
        text = fh.read().lower()
    for phrase in ("by hand", "manually", "ask the owner to run", "copy and paste the answer"):
        assert phrase not in text, (f, phrase)
ok("no flow hands a step to a person to do by hand")

# ---- a full run with a fake registry: tool step, assistant step, resume, block, retry ----
import shutil  # noqa: E402

tmp_root = tempfile.mkdtemp(prefix="wf_chain_")
flows_dir, chains_dir = os.path.join(tmp_root, "flows"), os.path.join(tmp_root, "chains")
os.makedirs(chains_dir)
for name in ("site-foundation-check", "foundation-fix-plan"):
    shutil.copytree(os.path.join(wf.FLOWS_DIR, name), os.path.join(flows_dir, name))
shutil.copy(os.path.join(wf.CHAINS_DIR, "site-diagnosis.chain.json"), chains_dir)
wf.FLOWS_DIR, wf.CHAINS_DIR = flows_dir, chains_dir

state = {"gsc": {"needs_setup": "connect analytics"}, "http_fail": True}
fake = {
    "sitemap_hygiene": lambda url: {"sitemap": "ok", "url": url},
    "http_check": lambda url: ({"needs_setup": "network"} if state["http_fail"] else {"https": True}),
    "crawl_depth": lambda start_url, max_pages: {"max_depth": 3},
    "growth_signals": lambda url: {"analytics_product": []},
    "gsc_list_sitemaps": lambda site_url: state["gsc"],
}
r = wf.start("site-diagnosis", {}, fake)
assert "missing required inputs" in r["error"]
r = wf.start("site-diagnosis", {"site_url": "https://x.test"}, fake)
assert r["status"] == "blocked" and "http_check" in r["blocked"]["reason"]
state["http_fail"] = False
r = wf.resume(r["run_id"], None, None, fake)
assert r["status"] == "needs_assistant", r
assert r["next"]["flow"] == "foundation-fix-plan"
rep = r["next"]["inputs"]["foundation_report"]
assert rep["sitemap"]["url"] == "https://x.test" and rep["search_console"] == {"needs_setup": "connect analytics"}
assert "Phase 1" in r["next"]["instructions"]
bad = wf.resume(r["run_id"], r["next"]["step"], {}, fake)
assert "outputs missing" in bad["error"]
done = wf.resume(r["run_id"], r["next"]["step"], {"fix_plan": [{"fix": "add analytics"}]}, fake)
assert done["status"] == "complete" and done["outputs"]["fix_plan"][0]["fix"] == "add analytics"
again = wf.resume(r["run_id"], None, None, fake)
assert again["status"] == "complete"
ok("a run blocks, retries, pauses for the assistant step, rejects missing outputs and completes")

print("all checks passed")
