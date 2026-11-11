# Copyright (c) 2026 The Wayfinder Trust - Jonathan Luethke
# All Rights Reserved. Proprietary and Confidential.
"""Skill-chain workflows inside the marketing MCP.

The workflows are written in the skill-chain format: one folder per flow under
workflows/flows/<flow>/ holding skill.md (the instructions, in phases with quality
gates) and manifest.json (inputs, outputs, and how the flow runs), and one
workflows/chains/<chain>.chain.json per workflow wiring flows into steps.

A flow runs one of two ways, named in its manifest's "runner":

  tool       the MCP runs it: each entry in "calls" invokes one of this server's
             tools with arguments resolved from the flow's inputs and from earlier
             calls in the same flow, and "output_map" builds the flow's outputs.
  assistant  Claude runs it in the chat: the run pauses, hands Claude the flow's
             skill.md and its resolved inputs, and resumes when Claude sends the
             outputs back with continue_workflow.

No step is handed to a person to do by hand. A tool step that cannot run (a
platform not connected) stops the run and says which setup tool fixes it, unless
the call is marked optional, in which case the result is recorded and the run
continues.

Argument references. A string that starts with "$" is a reference:
  $name                 a flow input, or the result of an earlier call stored "as" name
  $name.key.sub         a field inside it
  $name.items[*].field  that field from every element of a list
  $name.items[:5]       the first five elements (works after [*] too)
Lists and dicts in "args" are resolved element by element; anything else is a literal.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WF_DIR = os.path.join(HERE, "workflows")
FLOWS_DIR = os.path.join(WF_DIR, "flows")
CHAINS_DIR = os.path.join(WF_DIR, "chains")

# ---- validation rules (the skill-chain checker's rules) ----------------------
PHASE = re.compile(r"^##\s+(?:Phase\s+\d+[:.]\s*|(\d+)\.\s*)(.+)", re.I)
BANNED = ["—"]
HYPE = ["compelling", "transformative", "powerful", "comprehensive", "robust", "cutting-edge",
        "leverages", "empowers", "unlocks", "seamless", "seamlessly", "game-changing"]
BRIT = ["colour", "behaviour", "optimis", "centre", "metre", "favour", "modell",
        "initialis", "serialis", "normalis", "licence"]
BRIT_RE = [re.compile(r"analyse(?!s)")]
FOOTER = "Copyright 2024-present The Wayfinder Trust. All rights reserved."
CORE_SECTIONS = ("## Inputs", "## Outputs")
PHASE_SECTIONS = ("## Worked Example", "## Exit Criteria", "## Error Handling",
                  "### Entry Criteria", "### Actions", "### Output")
VALID_PATTERNS = {"phase_pipeline", "orpa", "linear", "iterative", "branching"}
VALID_LICENSES = {"OPEN", "COMMERCIAL", "PRIVATE"}
RUNNERS = {"tool", "assistant"}
ALLOWED_FILES = {"skill.md", "manifest.json", "tests.json", "provenance.json", "examples"}
USER_SOURCES = ("from_user_input", "from_user_input_optional")


def _io_names(lst):
    return [x if isinstance(x, str) else x.get("name", str(x)) for x in (lst or [])]


def data_dir() -> str:
    """Where run state is kept: MARKETING_MCP_DATA_DIR, else next to this module."""
    return os.environ.get("MARKETING_MCP_DATA_DIR") or HERE


def runs_path() -> str:
    return os.path.join(data_dir(), "workflow_runs.json")


# ---- loading -------------------------------------------------------------------

def load_flow(name: str, flows_dir: str = FLOWS_DIR):
    """Return (manifest, skill_md) for a flow, or raise FileNotFoundError."""
    d = os.path.join(flows_dir, name)
    with open(os.path.join(d, "manifest.json"), encoding="utf-8") as fh:
        manifest = json.load(fh)
    with open(os.path.join(d, "skill.md"), encoding="utf-8") as fh:
        skill = fh.read()
    return manifest, skill


def list_chain_names(chains_dir: str = CHAINS_DIR) -> list[str]:
    if not os.path.isdir(chains_dir):
        return []
    return sorted(f[:-len(".chain.json")] for f in os.listdir(chains_dir) if f.endswith(".chain.json"))


def load_chain(name: str, chains_dir: str = CHAINS_DIR) -> dict:
    with open(os.path.join(chains_dir, name + ".chain.json"), encoding="utf-8") as fh:
        return json.load(fh)


# ---- validation ----------------------------------------------------------------

def check_flow(name: str, flows_dir: str = FLOWS_DIR, tools: set | None = None):
    """Validate one flow folder. Returns (manifest or None, problems list)."""
    d = os.path.join(flows_dir, name)
    sk, mf = os.path.join(d, "skill.md"), os.path.join(d, "manifest.json")
    if not (os.path.exists(sk) and os.path.exists(mf)):
        return None, ["missing skill.md or manifest.json"]
    prob = []
    try:
        with open(mf, encoding="utf-8") as fh:
            m = json.load(fh)
    except ValueError as e:
        return None, ["manifest not valid JSON: %s" % e]
    with open(sk, encoding="utf-8") as fh:
        s = fh.read()
    low = s.lower()
    if m.get("name") != name:
        prob.append("manifest name %r != dir name" % m.get("name"))
    ep = m.get("execution_pattern", "")
    if ep not in VALID_PATTERNS:
        prob.append("manifest execution_pattern=%r" % ep)
    lic = m.get("license", "")
    if lic not in VALID_LICENSES:
        prob.append("manifest license=%r" % lic)
    if m.get("price") is None:
        prob.append("manifest missing price")
    elif lic == "OPEN" and str(m.get("price")) != "0":
        prob.append("OPEN license must be price '0'")
    if not m.get("domain"):
        prob.append("manifest missing domain")
    for k in ("version", "tags", "inputs", "outputs", "description"):
        if k not in m:
            prob.append("manifest missing %s" % k)
    phases = [ln for ln in s.splitlines() if PHASE.match(ln)]
    gates = len(re.findall(r"^### Quality Gate", s, re.M))
    if ep == "phase_pipeline":
        if not 2 <= len(phases) <= 4:
            prob.append("phases=%d (need 2 to 4)" % len(phases))
        if gates != len(phases):
            prob.append("quality gate count %d != phase count %d" % (gates, len(phases)))
        for sec in PHASE_SECTIONS:
            if sec not in s:
                prob.append("missing section '%s'" % sec)
    for sec in CORE_SECTIONS:
        if sec not in s:
            prob.append("missing section '%s'" % sec)
    for io in _io_names(m.get("inputs")) + _io_names(m.get("outputs")):
        if "`%s`" % io not in s:
            prob.append("io name `%s` never appears backticked in skill.md" % io)
    combined = s + json.dumps(m, ensure_ascii=False)
    prob += ["banned text %r" % b for b in BANNED if b in combined]
    prob += ["hype word %r" % h for h in HYPE if re.search(r"\b%s\b" % re.escape(h), low)]
    prob += ["British spelling %r" % b for b in BRIT if b in low]
    prob += ["British spelling %r" % p.pattern for p in BRIT_RE if p.search(low)]
    if FOOTER not in s:
        prob.append("license footer missing")
    extra = [x for x in os.listdir(d) if x not in ALLOWED_FILES]
    if extra:
        prob.append("unexpected files in flow dir: %s" % extra)
    # The MCP's own extension: how the flow runs.
    runner = m.get("runner")
    if runner not in RUNNERS:
        prob.append("manifest runner=%r, want one of %s" % (runner, sorted(RUNNERS)))
    if runner == "tool":
        calls = m.get("calls") or []
        if not calls:
            prob.append("tool flow has no calls")
        names = set(_io_names(m.get("inputs")))
        for c in calls:
            if tools is not None and c.get("tool") not in tools:
                prob.append("call to unknown tool %r" % c.get("tool"))
            if not c.get("as"):
                prob.append("call to %r has no 'as' name" % c.get("tool"))
            names.add(c.get("as"))
        for out in _io_names(m.get("outputs")):
            if out not in (m.get("output_map") or {}):
                prob.append("output %r missing from output_map" % out)
        for ref in _refs_in(m.get("output_map") or {}) + [r for c in calls for r in _refs_in(c.get("args") or {})]:
            if ref not in names:
                prob.append("reference $%s names no input or earlier call" % ref)
    return m, prob


def _refs_in(obj) -> list[str]:
    out = []
    if isinstance(obj, str) and obj.startswith("$"):
        out.append(re.split(r"[.\[]", obj[1:], maxsplit=1)[0])
    elif isinstance(obj, dict):
        for v in obj.values():
            out += _refs_in(v)
    elif isinstance(obj, list):
        for v in obj:
            out += _refs_in(v)
    return out


def check_chain(name: str, chains_dir: str = CHAINS_DIR, flows_dir: str = FLOWS_DIR,
                tools: set | None = None) -> list[str]:
    """Validate one chain and every flow it uses. Returns the list of problems (empty when clean)."""
    fails = []
    p = os.path.join(chains_dir, name + ".chain.json")
    if not os.path.exists(p):
        return ["no chain file %s" % p]
    with open(p, encoding="utf-8") as fh:
        raw = fh.read()
    try:
        c = json.loads(raw)
    except ValueError as e:
        return ["chain not valid JSON: %s" % e]
    if "—" in raw:
        fails.append("chain: em-dash")
    for k in ("name", "description", "steps", "edges", "entry_inputs", "terminal_outputs",
              "parallel_groups", "estimated_cost", "critical_path"):
        if k not in c:
            fails.append("chain missing key %s" % k)
    if c.get("name") != name:
        fails.append("chain name %r != file name" % c.get("name"))
    steps = c.get("steps", [])
    if not 1 <= len(steps) <= 45:
        fails.append("chain has %d steps, need 1 to 45" % len(steps))
    ids, user_inputs = {}, set()
    for st in steps:
        sid = st.get("id")
        if sid in ids:
            fails.append("duplicate step id %s" % sid)
        m, prob = check_flow(st.get("skill_name", ""), flows_dir, tools)
        fails += ["%s: %s" % (st.get("skill_name"), x) for x in prob]
        ids[sid] = st
        if m is None:
            continue
        if list(st.get("inputs", {})) != _io_names(m.get("inputs")) or \
                list(st.get("outputs", {})) != _io_names(m.get("outputs")):
            fails.append("%s: step inputs/outputs keys must equal manifest lists in order" % sid)
    order = list(ids)
    for sid, st in ids.items():
        for k, v in st.get("inputs", {}).items():
            if not isinstance(v, str):
                continue
            if v in USER_SOURCES:
                user_inputs.add(k)
                continue
            src, _, field = v.partition(".")
            if src not in ids:
                fails.append("%s.%s: refers to unknown step %r" % (sid, k, src))
            elif field not in ids[src].get("outputs", {}):
                fails.append("%s.%s: step %s has no output %r" % (sid, k, src, field))
            elif order.index(src) >= order.index(sid):
                fails.append("%s.%s: reads from a later step %s" % (sid, k, src))
    entry = {e if isinstance(e, str) else e.get("name", "") for e in c.get("entry_inputs", [])}
    if user_inputs and not user_inputs.issubset(entry):
        fails.append("entry_inputs missing user-supplied inputs %s" % sorted(user_inputs - entry))
    all_out = {o for st in ids.values() for o in st.get("outputs", {})}
    for t in c.get("terminal_outputs", []):
        if t not in all_out:
            fails.append("terminal output %r produced by no step" % t)
    for e in c.get("edges", []):
        if e.get("from_step") not in ids or e.get("to_step") not in ids:
            fails.append("bad edge %s->%s" % (e.get("from_step"), e.get("to_step")))
        for k in ("data_type", "field_mapping"):
            if k not in e:
                fails.append("edge %s->%s missing %s" % (e.get("from_step"), e.get("to_step"), k))
    grouped = {x for g in c.get("parallel_groups", []) for x in g}
    if grouped - set(ids):
        fails.append("parallel_groups references unknown steps: %s" % sorted(grouped - set(ids)))
    for x in c.get("critical_path", []):
        if x not in ids:
            fails.append("critical_path has unknown step %s" % x)
    return fails


def check_all(tools: set | None = None) -> dict:
    """Validate every chain. Returns {chain: [problems]} with an entry per chain."""
    return {n: check_chain(n, tools=tools) for n in list_chain_names()}


# ---- reference resolution ----------------------------------------------------------

_TOKEN = re.compile(r"\.([A-Za-z_][\w-]*)|\[\*\]|\[:(\d+)\]|\[(\d+)\]")


def resolve_ref(expr: str, scope: dict):
    """Resolve a $reference against scope. Missing keys resolve to None."""
    body = expr[1:]
    m = re.match(r"[A-Za-z_][\w-]*", body)
    if not m:
        raise ValueError("bad reference %r" % expr)
    value = scope.get(m.group(0))
    rest, mapped = body[m.end():], False
    pos = 0
    while pos < len(rest):
        t = _TOKEN.match(rest, pos)
        if not t:
            raise ValueError("bad reference %r at %r" % (expr, rest[pos:]))
        pos = t.end()
        if t.group(0) == "[*]":
            mapped = True
            value = list(value) if isinstance(value, (list, tuple)) else []
            continue
        if t.group(2) is not None:
            value = list(value or [])[:int(t.group(2))]
            continue
        if t.group(3) is not None:
            seq = list(value or [])
            i = int(t.group(3))
            value = seq[i] if i < len(seq) else None
            continue
        key = t.group(1)
        if mapped:
            value = [v.get(key) if isinstance(v, dict) else None for v in value]
            value = [v for v in value if v is not None]
        else:
            value = value.get(key) if isinstance(value, dict) else None
    return value


def resolve(obj, scope: dict):
    if isinstance(obj, str) and obj.startswith("$"):
        return resolve_ref(obj, scope)
    if isinstance(obj, dict):
        return {k: resolve(v, scope) for k, v in obj.items()}
    if isinstance(obj, list):
        return [resolve(v, scope) for v in obj]
    return obj


def coerce_input(value, typ: str):
    """Accept the shapes a chat prompt produces: a comma list for a list input, a
    numeric string for a number, a JSON string for an object."""
    if value is None:
        return None
    t = (typ or "").strip()
    if t.endswith("[]") and isinstance(value, str):
        s = value.strip()
        if s.startswith("["):
            try:
                return json.loads(s)
            except ValueError:
                pass
        return [p.strip() for p in s.split(",") if p.strip()]
    if t == "number" and isinstance(value, str):
        try:
            return int(value) if value.strip().lstrip("-").isdigit() else float(value)
        except ValueError:
            return value
    if t in ("object", "object[]") and isinstance(value, str) and value.strip()[:1] in "[{":
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def _input_types(manifest: dict, skill: str) -> dict:
    """Read each input's declared type from the skill.md Inputs list ("- `name` (type, ...)")."""
    types = {}
    for name in _io_names(manifest.get("inputs")):
        m = re.search(r"`%s`\s*\(([^,)]+)" % re.escape(name), skill)
        types[name] = m.group(1).strip() if m else ""
    return types


def _failed(result) -> str | None:
    """Why a tool result counts as not run, or None when it ran."""
    if not isinstance(result, dict):
        return None
    if result.get("needs_setup"):
        return "needs setup: " + str(result["needs_setup"])
    if result.get("error") and len(result) <= 4:
        return str(result["error"])
    return None


def run_tool_flow(manifest: dict, inputs: dict, registry: dict) -> dict:
    """Run a tool flow. Returns {"ok": bool, "outputs": {...}, "calls": [...], "blocked": reason|None}."""
    scope = dict(inputs)
    log = []
    for c in manifest.get("calls") or []:
        tool = c["tool"]
        fn = registry.get(tool)
        args = {k: v for k, v in resolve(c.get("args") or {}, scope).items() if v is not None}
        started = time.time()
        if fn is None:
            result = {"error": "tool %s is not registered" % tool}
        else:
            try:
                result = fn(**args)
            except Exception as e:  # noqa: BLE001
                result = {"error": "%s: %s" % (type(e).__name__, str(e)[:300])}
        why = _failed(result)
        log.append({"tool": tool, "as": c["as"], "ok": why is None, "seconds": round(time.time() - started, 2),
                    **({"reason": why} if why else {})})
        scope[c["as"]] = result
        if why and not c.get("optional"):
            return {"ok": False, "outputs": {}, "calls": log,
                    "blocked": "%s did not run (%s)" % (tool, why)}
    outputs = {k: resolve(v, scope) for k, v in (manifest.get("output_map") or {}).items()}
    return {"ok": True, "outputs": outputs, "calls": log, "blocked": None}


# ---- run state ------------------------------------------------------------------

def _load_runs() -> dict:
    try:
        with open(runs_path(), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def _save_runs(runs: dict) -> None:
    # Keep the newest 50 runs.
    keep = dict(sorted(runs.items(), key=lambda kv: kv[1].get("started", 0))[-50:])
    tmp = runs_path() + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(keep, fh, indent=1, ensure_ascii=False, default=str)
    os.replace(tmp, runs_path())


def describe(name: str) -> dict:
    """A chain's description, its inputs (required and optional, with types), and its steps."""
    c = load_chain(name)
    required, optional, types = [], [], {}
    steps = []
    for st in c["steps"]:
        m, skill = load_flow(st["skill_name"])
        t = _input_types(m, skill)
        for k, v in st["inputs"].items():
            if v == "from_user_input" and k not in required:
                required.append(k)
            elif v == "from_user_input_optional" and k not in optional and k not in required:
                optional.append(k)
            types.setdefault(k, t.get(k, ""))
        steps.append({"id": st["id"], "flow": st["skill_name"], "runner": m.get("runner"),
                      "tools": [x["tool"] for x in m.get("calls") or []]})
    optional = [o for o in optional if o not in required]
    return {"name": name, "description": c["description"], "required_inputs": required,
            "optional_inputs": optional, "input_types": types, "steps": steps,
            "terminal_outputs": c["terminal_outputs"]}


def _advance(run: dict, registry: dict) -> dict:
    """Run steps from the run's cursor until an assistant step, a block, or the end."""
    c = load_chain(run["chain"])
    steps = c["steps"]
    while run["cursor"] < len(steps):
        st = steps[run["cursor"]]
        m, skill = load_flow(st["skill_name"])
        types = _input_types(m, skill)
        resolved = {}
        for k, v in st["inputs"].items():
            if v in USER_SOURCES:
                resolved[k] = coerce_input(run["inputs"].get(k), types.get(k, ""))
            else:
                src, _, field = v.partition(".")
                resolved[k] = run["steps"].get(src, {}).get("outputs", {}).get(field)
        if m.get("runner") == "tool":
            res = run_tool_flow(m, resolved, registry)
            run["steps"][st["id"]] = {"flow": st["skill_name"], "runner": "tool", "calls": res["calls"],
                                      "outputs": res["outputs"]}
            if not res["ok"]:
                run["status"] = "blocked"
                run["blocked"] = {"step": st["id"], "reason": res["blocked"],
                                  "fix": "run setup_check, connect the platform it names, then "
                                         "continue_workflow with this run_id to retry the step"}
                return run
            run["cursor"] += 1
            continue
        run["status"] = "needs_assistant"
        run["pending"] = {"step": st["id"], "flow": st["skill_name"], "inputs": resolved,
                          "expected_outputs": list(st["outputs"]), "instructions": skill}
        return run
    run["status"] = "complete"
    run.pop("pending", None)
    run.pop("blocked", None)
    run["terminal_outputs"] = {}
    for t in c["terminal_outputs"]:
        for sid in reversed([s["id"] for s in steps]):
            outs = run["steps"].get(sid, {}).get("outputs", {})
            if t in outs:
                run["terminal_outputs"][t] = outs[t]
                break
    return run


def _public(run: dict) -> dict:
    out = {"run_id": run["run_id"], "workflow": run["chain"], "status": run["status"],
           "steps_done": [{"step": k, "runner": v.get("runner"),
                           **({"calls": v["calls"]} if v.get("calls") else {})}
                          for k, v in run["steps"].items()]}
    if run["status"] == "needs_assistant":
        p = run["pending"]
        out["next"] = {"step": p["step"], "flow": p["flow"], "inputs": p["inputs"],
                       "expected_outputs": p["expected_outputs"], "instructions": p["instructions"],
                       "then": "do this step in the chat, then call continue_workflow with run_id=%s, "
                               "step=%s and outputs holding %s" % (run["run_id"], p["step"],
                                                                    ", ".join(p["expected_outputs"]))}
    elif run["status"] == "blocked":
        out["blocked"] = run["blocked"]
    elif run["status"] == "complete":
        out["outputs"] = run["terminal_outputs"]
    return out


def start(name: str, inputs: dict | None, registry: dict) -> dict:
    """Start a workflow run. Tool steps run now; the run pauses at the first assistant step."""
    if name not in list_chain_names():
        return {"error": "no workflow named %r" % name, "workflows": list_chain_names()}
    info = describe(name)
    inputs = dict(inputs or {})
    missing = [k for k in info["required_inputs"] if inputs.get(k) in (None, "", [])]
    if missing:
        return {"error": "missing required inputs: %s" % ", ".join(missing),
                "required_inputs": info["required_inputs"], "optional_inputs": info["optional_inputs"],
                "input_types": info["input_types"]}
    run = {"run_id": time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3), "chain": name,
           "inputs": inputs, "steps": {}, "cursor": 0, "status": "running", "started": time.time()}
    run = _advance(run, registry)
    runs = _load_runs()
    runs[run["run_id"]] = run
    _save_runs(runs)
    return _public(run)


def resume(run_id: str, step: str | None, outputs: dict | None, registry: dict) -> dict:
    """Record an assistant step's outputs (or retry a blocked step) and keep running."""
    runs = _load_runs()
    run = runs.get(run_id)
    if run is None:
        return {"error": "no run %r" % run_id}
    if run["status"] == "complete":
        return _public(run)
    if run["status"] == "needs_assistant":
        p = run["pending"]
        if step and step != p["step"]:
            return {"error": "run is waiting on step %s, not %s" % (p["step"], step)}
        outputs = outputs or {}
        missing = [o for o in p["expected_outputs"] if o not in outputs]
        if missing:
            return {"error": "outputs missing: %s" % ", ".join(missing),
                    "expected_outputs": p["expected_outputs"]}
        run["steps"][p["step"]] = {"flow": p["flow"], "runner": "assistant",
                                   "outputs": {k: outputs[k] for k in p["expected_outputs"]}}
        run["cursor"] += 1
        run.pop("pending", None)
    run["status"] = "running"
    run = _advance(run, registry)
    runs[run_id] = run
    _save_runs(runs)
    return _public(run)
