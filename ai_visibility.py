# Copyright (c) 2026 The Wayfinder Trust - Jonathan Luethke
# All Rights Reserved. Proprietary and Confidential.
"""AI search visibility: is an assistant naming this business, and who else?

There is no rank tracker for answer engines. The method: ask an assistant about
fifteen buyer questions, each in a clean session, log whether the business is named,
where it sits, and who else appears, and watch the share of answer move over time.
This module generates the question set and scores the answers; ai_ask.ask_all asks
the questions, one fresh API session each with web search on, so no step is done by
hand.

  visibility_questions   a balanced, deterministic buyer-question set plus the
                         instructions for running it
  visibility_record      score a run of answers (named, position, competitors,
                         a link to the business), append it to the local store, and
                         return that run's share of answer
  visibility_report      the store over time: share of answer per run, the change
                         since the first run, and the questions never won

The store is ai_visibility.json next to this module, or under MARKETING_MCP_DATA_DIR
when that environment variable is set.
"""
from __future__ import annotations

import datetime
import json
import os
import re
from collections import OrderedDict

STORE_NAME = "ai_visibility.json"


def _data_dir() -> str:
    return os.environ.get("MARKETING_MCP_DATA_DIR") or os.path.dirname(os.path.abspath(__file__))


def _store_path() -> str:
    return os.path.join(_data_dir(), STORE_NAME)


def _load_store() -> dict:
    try:
        with open(_store_path(), encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {"runs": []}
    except Exception:  # noqa: BLE001
        return {"runs": []}


def _save_store(d: dict) -> None:
    path = _store_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(d, f, indent=2, ensure_ascii=False)
        f.write("\n")


# ---- 7. visibility_questions ----------------------------------------------

def build_questions(business: str, service: str, city: str | None = None,
                    competitors=None, extra_questions=None, count: int = 15) -> list:
    """A balanced, deterministic buyer-question set. Best/top provider questions,
    cost, how to choose, comparisons with any named competitors, problem-first
    questions, and 'near' phrasings using the city."""
    svc = (service or "").strip()
    where = (" in " + city.strip()) if city else ""
    comp = [c for c in (competitors or []) if c and c.strip()]
    q = []
    # Best / top provider.
    q.append("What is the best %s%s?" % (svc, where))
    q.append("Who are the top %s companies%s?" % (svc, where))
    q.append("Who should I call for %s%s?" % (svc, where))
    # Cost.
    q.append("How much does %s cost%s?" % (svc, where))
    q.append("What is a fair price for %s%s?" % (svc, where))
    # How to choose.
    q.append("How do I choose a good %s%s?" % (svc, where))
    q.append("What should I look for when hiring a %s?" % svc)
    # Problem-first.
    q.append("I need help with %s%s, where do I start?" % (svc, where))
    q.append("Who is a reliable %s%s?" % (svc, where))
    # Near phrasings using the city.
    if city:
        q.append("%s near me in %s" % (svc, city.strip()))
        q.append("Is there a highly rated %s in %s?" % (svc, city.strip()))
    else:
        q.append("%s near me" % svc)
        q.append("Is there a highly rated %s nearby?" % svc)
    # Comparisons with named competitors.
    for c in comp[:3]:
        q.append("Is %s or %s better for %s?" % (business, c.strip(), svc))
    # The brand's own reputation.
    q.append("%s reviews" % business)
    q.append("Is %s any good?" % business)
    # Caller-supplied extras take priority after the brand questions.
    for extra in (extra_questions or []):
        if extra and extra.strip():
            q.append(extra.strip())

    # Dedupe preserving order, then fit to count.
    out, seen = [], set()
    for item in q:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out[:count]


def visibility_questions(business: str, service: str, city: str | None = None,
                         competitors=None, extra_questions=None, count: int = 15) -> dict:
    """Generate the buyer-question set and the instructions for running it. The
    questions are deterministic, so two runs a quarter apart ask the same thing."""
    questions = build_questions(business, service, city, competitors, extra_questions, count)
    instructions = [
        "Call ask_assistant with these questions: each is asked in its own fresh API session "
        "with web search on and no history or memory, so the answers reflect the open web.",
        "Record the run with visibility_record, passing ask_assistant's answers.",
        "Re-run the same set every month. A single snapshot is noise; the trend is the "
        "finding.",
    ]
    return {"business": business, "service": service, "city": city,
            "count": len(questions), "questions": questions,
            "competitors": [c for c in (competitors or []) if c],
            "instructions": instructions}


# ---- 8. visibility_record -------------------------------------------------

# A capitalized multi-word name: two or more capitalized tokens in a row. This is
# how a business name surfaces in prose when it is not one the caller named.
_NAME_RE = re.compile(r"\b([A-Z][A-Za-z0-9&'.]+(?:\s+(?:of|and|the|for|&|[A-Z][A-Za-z0-9&'.]+))*"
                      r"\s+[A-Z][A-Za-z0-9&'.]+)\b")
_LIST_RE = re.compile(r"^\s*(?:\d+[.)]|[-*•])\s+(.+)$")
_URL_RE = re.compile(r"https?://[^\s)\]}>\"']+", re.I)
_DOMAIN_RE = re.compile(r"\b(?:[a-z0-9-]+\.)+[a-z]{2,}\b", re.I)


def _norm_name(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().strip(".,:;!?").lower())


def _slug_variants(business: str) -> set:
    base = re.sub(r"[^a-z0-9]+", "", (business or "").lower())
    hyph = re.sub(r"[^a-z0-9]+", "-", (business or "").lower()).strip("-")
    words = [w for w in re.split(r"[^a-z0-9]+", (business or "").lower()) if w]
    variants = {v for v in (base, hyph) if len(v) >= 4}
    if len(words) >= 2:
        variants.add("".join(words[:2]))
    return variants


def detect_businesses(answer: str, known=None) -> list:
    """Ordered list of business names mentioned in an answer, by first mention.
    Starts from the known names (the business, its aliases, named competitors),
    then adds list-item leads and capitalized multi-word names found in the text."""
    text = answer or ""
    found = {}  # normalized name -> (first_index, display)

    def consider(display, idx):
        key = _norm_name(display)
        if not key or len(key) < 3:
            return
        if key not in found or idx < found[key][0]:
            found[key] = (idx, display.strip().strip(".,:;!?"))

    for name in (known or []):
        if not name:
            continue
        m = re.search(re.escape(name), text, re.I)
        if m:
            consider(name, m.start())

    for line in text.splitlines():
        m = _LIST_RE.match(line)
        if m:
            lead = m.group(1)
            # The bold/plain name at the head of a list item, up to a separator.
            head = re.split(r"[:–—.,()]|\s-\s", lead, 1)[0]
            head = re.sub(r"[*_`#]+", "", head).strip()
            if head and head[0].isupper():
                idx = text.find(line)
                consider(head, idx if idx >= 0 else 0)

    for m in _NAME_RE.finditer(text):
        consider(m.group(1), m.start())

    ordered = sorted(found.values(), key=lambda t: t[0])
    return [display for _idx, display in ordered]


def _link_to_business(answer: str, business: str, aliases=None) -> bool:
    """True when the answer carries a link or domain that points at the business."""
    text = answer or ""
    variants = _slug_variants(business)
    for alias in (aliases or []):
        if alias and "." in alias:
            if re.search(re.escape(alias), text, re.I):
                return True
    for url in _URL_RE.findall(text):
        host = re.sub(r"^https?://", "", url, flags=re.I).split("/")[0].lower()
        bare = re.sub(r"[^a-z0-9]", "", host)
        if any(v and v in bare for v in variants):
            return True
    for dom in _DOMAIN_RE.findall(text):
        bare = re.sub(r"[^a-z0-9]", "", dom.lower())
        if any(v and v in bare for v in variants):
            return True
    return False


def analyze_answer(question: str, answer: str, business: str, aliases=None,
                   competitors=None) -> dict:
    """Score one answer: is the business named, at what position among the named
    businesses, which competitors appear, and is there a link to the business."""
    text = answer or ""
    names = [business] + [a for a in (aliases or []) if a]
    comp = [c for c in (competitors or []) if c]
    biz_norms = {_norm_name(n) for n in names if _norm_name(n)}

    # Where the business is first mentioned.
    biz_idx = None
    for n in names:
        if not n:
            continue
        m = re.search(re.escape(n), text, re.I)
        if m:
            biz_idx = m.start() if biz_idx is None else min(biz_idx, m.start())
    named = biz_idx is not None

    def _overlaps_business(name) -> bool:
        nn = _norm_name(name)
        return nn in biz_norms or any(b in nn or nn in b for b in biz_norms)

    # Position: how many OTHER businesses are mentioned before the business.
    position = None
    if named:
        before, seen = 0, set()
        for name in detect_businesses(text, known=comp):
            nn = _norm_name(name)
            if not nn or nn in seen or _overlaps_business(name):
                continue
            m = re.search(re.escape(name), text, re.I)
            if m and m.start() < biz_idx:
                before += 1
                seen.add(nn)
        position = before + 1

    low = text.lower()
    comp_present = [c for c in comp if _norm_name(c) in low and _norm_name(c) not in biz_norms]

    return {
        "question": question,
        "named": named,
        "position": position,
        "businesses_named_count": len(detect_businesses(text, known=names + comp)),
        "competitors_present": comp_present,
        "link_to_business": _link_to_business(text, business, aliases),
    }


def visibility_record(business: str, answers: list, assistant: str = "claude",
                      run_date: str | None = None, competitors=None, aliases=None) -> dict:
    """Score a run of pasted answers and append it to the local store. `answers` is
    a list of {question, answer}. Returns the run's share of answer (named over
    asked), the average position when named, and a competitor share table."""
    run_date = run_date or datetime.date.today().isoformat()
    comp = [c for c in (competitors or []) if c]
    per = []
    for item in (answers or []):
        q = (item or {}).get("question", "")
        a = (item or {}).get("answer", "")
        per.append(analyze_answer(q, a, business, aliases, comp))

    asked = len(per)
    named_rows = [r for r in per if r["named"]]
    positions = [r["position"] for r in named_rows if r["position"]]
    share = round(len(named_rows) / asked, 3) if asked else 0.0
    avg_pos = round(sum(positions) / len(positions), 2) if positions else None

    comp_share = OrderedDict()
    for c in comp:
        n = sum(1 for r in per if c in r["competitors_present"])
        comp_share[c] = {"answers": n, "share": round(n / asked, 3) if asked else 0.0}

    run = {
        "business": business, "assistant": assistant, "run_date": run_date,
        "asked": asked, "named": len(named_rows),
        "share_of_answer": share, "avg_position_when_named": avg_pos,
        "links_to_business": sum(1 for r in per if r["link_to_business"]),
        "competitor_share": comp_share,
        "per_question": per,
    }
    store = _load_store()
    store.setdefault("runs", []).append(run)
    _save_store(store)

    return {
        "business": business, "assistant": assistant, "run_date": run_date,
        "asked": asked, "named": len(named_rows), "share_of_answer": share,
        "avg_position_when_named": avg_pos,
        "competitor_share": comp_share,
        "never_named_questions": [r["question"] for r in per if not r["named"]],
        "store": _store_path(),
    }


# ---- 9. visibility_report -------------------------------------------------

def visibility_report(business: str, assistant: str | None = None) -> dict:
    """Read the store and return the runs for a business over time: share of answer
    per run, the change since the first run, and the questions it has never won."""
    store = _load_store()
    bnorm = _norm_name(business)
    runs = [r for r in store.get("runs", [])
            if _norm_name(r.get("business", "")) == bnorm
            and (assistant is None or r.get("assistant") == assistant)]
    runs.sort(key=lambda r: (r.get("run_date", ""), r.get("assistant", "")))
    if not runs:
        return {"business": business, "assistant": assistant, "runs": 0,
                "message": "no runs recorded for this business yet"}

    over_time = [{"run_date": r.get("run_date"), "assistant": r.get("assistant"),
                  "asked": r.get("asked"), "named": r.get("named"),
                  "share_of_answer": r.get("share_of_answer"),
                  "avg_position_when_named": r.get("avg_position_when_named")}
                 for r in runs]
    first, last = runs[0], runs[-1]
    change = round((last.get("share_of_answer") or 0) - (first.get("share_of_answer") or 0), 3)

    # Questions never named across every run of this business.
    ever_named, all_questions = set(), []
    for r in runs:
        for pq in r.get("per_question", []):
            key = _norm_name(pq.get("question", ""))
            if key not in [_norm_name(q) for q in all_questions]:
                all_questions.append(pq.get("question", ""))
            if pq.get("named"):
                ever_named.add(key)
    never = [q for q in all_questions if _norm_name(q) not in ever_named]

    return {
        "business": business, "assistant": assistant, "runs": len(runs),
        "over_time": over_time,
        "first_run": first.get("run_date"), "latest_run": last.get("run_date"),
        "share_of_answer_first": first.get("share_of_answer"),
        "share_of_answer_latest": last.get("share_of_answer"),
        "share_change_since_first": change,
        "never_named_questions": never,
        "store": _store_path(),
    }
