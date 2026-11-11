# Copyright (c) 2026 The Wayfinder Trust - Jonathan Luethke
# All Rights Reserved. Proprietary and Confidential.
"""Check marketing copy for the things that make it read as machine-written,
overblown, or unsupported.

One function, copy_check, runs a set of rules over a block of text and returns
each problem with its line, column, the matched text, the rule it broke, and a
suggested fix. The rules:

  AI tells        em/en dashes used as punctuation, stock openers ("In today's
                  fast-paced world", "delve", "game-changer"), closing tics
                  ("Let me know if you have any questions")
  hype            adjectives that assert instead of showing (compelling,
                  transformative, powerful, cutting-edge, robust, comprehensive,
                  revolutionary, seamless)
  hedges          we believe, perhaps, in many cases, arguably
  punctuation     exclamation marks in business copy
  readability     sentences over 35 words, a passive-voice estimate
  spelling        British spellings when the locale is en-US
  claims          every number, percentage, dollar amount or superlative, unless
                  the same sentence or the next one carries a source cue

The caller can add banned words and extra phrase rules, or lift the claim pass.
Everything is pure text work; there is no network and no state.
"""
from __future__ import annotations

import re

# ---- rule tables ----------------------------------------------------------

# Stock openers and filler that mark machine-written prose. Matched as phrases,
# case-insensitive.
_AI_PHRASES = [
    "in today's fast-paced world", "in today's digital age", "in today's world",
    "in the ever-evolving", "in the realm of", "when it comes to",
    "it's important to note", "it is important to note", "it's worth noting",
    "needless to say", "at the end of the day", "navigating the",
    "unlock the power", "unlock the potential", "harness the power",
    "in conclusion", "last but not least", "a testament to", "a tapestry of",
    "delve", "delving", "game-changer", "game changer", "take it to the next level",
    "the world of", "ever-changing landscape", "look no further",
]
# Sign-offs and transitions that read as filler.
_AI_CLOSERS = [
    "let me know if you have any questions", "feel free to reach out",
    "don't hesitate to reach out", "don't hesitate to contact",
    "i hope this email finds you well", "i hope this finds you well",
    "hope this helps", "please don't hesitate", "thanks in advance",
    "looking forward to hearing from you",
]
_HYPE = ["compelling", "transformative", "powerful", "cutting-edge", "cutting edge",
         "robust", "comprehensive", "revolutionary", "seamless", "world-class",
         "best-in-class", "state-of-the-art", "next-generation", "groundbreaking",
         "unparalleled", "innovative", "synergy", "synergistic"]
_HEDGES = ["we believe", "perhaps", "in many cases", "arguably", "sort of",
           "kind of", "we think", "it seems", "somewhat", "more or less",
           "to some extent", "fairly confident", "broadly speaking"]

# British spelling -> American spelling. Matched whole-word, case-insensitive.
_BRITISH = {
    r"\bcolour(s|ed|ing|ful)?\b": "color",
    r"\bfavour(s|ed|ing|ite|ites|able)?\b": "favor",
    r"\bhonour(s|ed|ing|able)?\b": "honor",
    r"\bbehaviour(s|al)?\b": "behavior",
    r"\bflavour(s|ed|ing|ful)?\b": "flavor",
    r"\blabour(s|ed|ing)?\b": "labor",
    r"\bneighbour(s|hood|ing)?\b": "neighbor",
    r"\borganis(e|es|ed|ing|ation|ational)\b": "organize",
    r"\brealis(e|es|ed|ing)\b": "realize",
    r"\brecognis(e|es|ed|ing)\b": "recognize",
    r"\boptimis(e|es|ed|ing|ation)\b": "optimize",
    r"\bprioritis(e|es|ed|ing)\b": "prioritize",
    r"\bcustomis(e|es|ed|ing|ation)\b": "customize",
    r"\banalys(e|es|ed|ing)\b": "analyze",
    r"\bcatalogue(s|d)?\b": "catalog",
    r"\bcentre(s|d)?\b": "center",
    r"\bmetre(s)?\b": "meter",
    r"\btheatre(s)?\b": "theater",
    r"\blicence(s|d)?\b": "license",
    r"\bdefence(s)?\b": "defense",
    r"\boffence(s)?\b": "offense",
    r"\bprogramme(s|d)?\b": "program",
    r"\benrol(ment|led|ling)\b": "enroll-",
    r"\bfulfil(ment|led|ling)?\b": "fulfill",
    r"\btravell(ed|ing|er|ers)\b": "travel-",
    r"\bcancell(ation|ations)\b": "cancel-",
}

# A source cue in the same or the next sentence vouches for a claim.
_SOURCE_CUE = re.compile(
    r"https?://\S+|www\.\S+|according to|\bsource\b\s*[:\-]|\bper\b\s+[A-Z]|"
    r"\bcites?\b|\breported? by\b|\bstudy\b|\bsurvey\b|\[\d+\]|\([12]\d{3}\)|"
    r"\bdata from\b|\bas measured\b|\bbenchmark\b", re.I)

# A claim: a number, a percentage, a currency amount, or a named superlative.
_CLAIM = re.compile(
    r"[$€£]\s?\d[\d,]*(?:\.\d+)?|"
    r"\b\d[\d,]*(?:\.\d+)?\s?%|"
    r"\b\d[\d,]*(?:\.\d+)?\s?(?:x|times|percent)\b|"
    r"\b\d[\d,]{2,}(?:\.\d+)?\b|"
    r"#1\b|\bnumber one\b|\bbest\b|\bonly\b|\bfirst\b", re.I)

# Passive-voice estimate: a be-verb followed (optionally via an adverb) by a
# past participle.
_PASSIVE = re.compile(
    r"\b(am|is|are|was|were|be|been|being)\b\s+(?:\w+ly\s+)?"
    r"(\w+ed|written|done|made|given|taken|seen|known|shown|held|built|sent|kept|"
    r"found|told|brought|bought|caught|taught|sold|paid|driven|chosen|run)\b", re.I)

_SENTENCE_SPLIT = re.compile(r"[.!?]+[\"')\]]*(?:\s+|$)")


def _line_col(text: str, offset: int) -> tuple:
    """1-based (line, column) for a character offset."""
    line = text.count("\n", 0, offset) + 1
    col = offset - (text.rfind("\n", 0, offset) + 1) + 1
    return line, col


def _split_sentences(text: str) -> list:
    """List of (sentence_text, start, end) over the whole text."""
    out = []
    pos = 0
    for m in _SENTENCE_SPLIT.finditer(text):
        end = m.end()
        seg = text[pos:end]
        if seg.strip():
            out.append((seg, pos, end))
        pos = end
    if pos < len(text) and text[pos:].strip():
        out.append((text[pos:], pos, len(text)))
    return out


def _add(issues, text, start, match_text, rule, suggestion):
    line, col = _line_col(text, start)
    issues.append({"line": line, "column": col, "match": match_text,
                   "rule": rule, "suggestion": suggestion})


def _scan_phrases(issues, text, phrases, rule, suggestion):
    low = text.lower()
    for phrase in phrases:
        p = phrase.lower()
        i = low.find(p)
        while i != -1:
            _add(issues, text, i, text[i:i + len(phrase)], rule, suggestion)
            i = low.find(p, i + len(p))


def copy_check(text: str, banned_words: list | None = None,
               extra_rules: dict | None = None, check_claims: bool = True,
               locale: str = "en-US") -> dict:
    """Check a block of marketing copy and return every problem found.

    banned_words: extra words or phrases to flag under the 'banned_word' rule.
    extra_rules: a dict of {rule_name: [phrases]} added to the phrase scan, so a
    caller can extend the defaults with its own house rules.
    check_claims: when True, flag numbers, percentages, currency amounts and
    superlatives that no nearby source cue supports.
    locale: when it starts with 'en-US', British spellings are flagged.

    Returns issues (each with line, column, match, rule, suggestion), counts by
    rule, an issue_count, and a pass flag (True when nothing was flagged).
    """
    text = text or ""
    issues: list[dict] = []

    # AI tells: dashes used as punctuation. An en-dash between digits is a range
    # and is left alone; an em-dash is always a tell.
    for m in re.finditer("—", text):  # em-dash
        _add(issues, text, m.start(), "—", "ai_tell_dash",
             "replace the em-dash with a comma, colon, or period")
    for m in re.finditer(r"(?<!\d)\s*–\s*(?!\d)", text):  # en-dash, not a numeric range
        _add(issues, text, m.start(), m.group().strip() or "–", "ai_tell_dash",
             "replace the en-dash with a comma or 'to'")

    _scan_phrases(issues, text, _AI_PHRASES, "ai_tell_phrase",
                  "cut the stock phrase; say the specific thing instead")
    _scan_phrases(issues, text, _AI_CLOSERS, "ai_tell_closer",
                  "cut the filler sign-off")
    _scan_phrases(issues, text, _HYPE, "hype_adjective",
                  "drop the adjective and show the fact that would earn it")
    _scan_phrases(issues, text, _HEDGES, "hedge",
                  "cut the hedge and state the claim plainly, or drop the claim")

    # Exclamation marks in business copy.
    for m in re.finditer(r"!", text):
        _add(issues, text, m.start(), "!", "exclamation",
             "replace the exclamation mark with a period")

    # Passive-voice estimate.
    for m in _PASSIVE.finditer(text):
        _add(issues, text, m.start(), m.group(), "passive_voice",
             "rewrite in the active voice (name who does the action)")

    # Sentences over 35 words.
    for seg, start, _end in _split_sentences(text):
        words = re.findall(r"\b[\w'-]+\b", seg)
        if len(words) > 35:
            _add(issues, text, start, seg.strip()[:60] + ("..." if len(seg.strip()) > 60 else ""),
                 "long_sentence",
                 "split this %d-word sentence; aim for 35 words or fewer" % len(words))

    # British spellings when the locale is American.
    if (locale or "").lower().startswith("en-us"):
        for pat, american in _BRITISH.items():
            for m in re.finditer(pat, text, re.I):
                _add(issues, text, m.start(), m.group(), "british_spelling",
                     "American spelling: %s" % american.rstrip("-"))

    # Caller-supplied banned words and extra phrase rules.
    if banned_words:
        _scan_phrases(issues, text, [str(w) for w in banned_words], "banned_word",
                      "remove this banned word")
    if extra_rules:
        for rule_name, phrases in extra_rules.items():
            _scan_phrases(issues, text, [str(p) for p in phrases], str(rule_name),
                          "flagged by the '%s' rule" % rule_name)

    # Claim pass: a claim stands only if its sentence or the next one cites a source.
    if check_claims:
        sentences = _split_sentences(text)
        for idx, (seg, start, _end) in enumerate(sentences):
            nxt = sentences[idx + 1][0] if idx + 1 < len(sentences) else ""
            if _SOURCE_CUE.search(seg) or _SOURCE_CUE.search(nxt):
                continue
            for m in _CLAIM.finditer(seg):
                _add(issues, text, start + m.start(), m.group(), "unsourced_claim",
                     "cite a source in this sentence or the next, or cut the figure")

    issues.sort(key=lambda it: (it["line"], it["column"], it["rule"]))
    counts: dict[str, int] = {}
    for it in issues:
        counts[it["rule"]] = counts.get(it["rule"], 0) + 1
    return {
        "locale": locale,
        "issue_count": len(issues),
        "counts": counts,
        "issues": issues,
        "pass": len(issues) == 0,
    }
