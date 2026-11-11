# Copyright (c) 2026 The Wayfinder Trust - Jonathan Luethke
# All Rights Reserved. Proprietary and Confidential.
"""Offline checks for ai_visibility.py. No network. Run: python test_ai_visibility.py"""
import os
import tempfile

import ai_visibility as av


def check(name, cond):
    if not cond:
        raise AssertionError(name)
    print("ok  " + name)


def test_questions():
    q = av.visibility_questions("Acme Plumbing", "emergency plumbing", city="Austin",
                                competitors=["Rival Plumbing", "Budget Pipes"], count=15)
    check("question count honored", q["count"] == 15 and len(q["questions"]) == 15)
    check("deterministic across calls",
          av.build_questions("Acme Plumbing", "emergency plumbing", "Austin",
                             ["Rival Plumbing", "Budget Pipes"])
          == av.build_questions("Acme Plumbing", "emergency plumbing", "Austin",
                                ["Rival Plumbing", "Budget Pipes"]))
    joined = " ".join(q["questions"]).lower()
    check("best/top phrasing present", "best" in joined or "top" in joined)
    check("cost phrasing present", "cost" in joined or "price" in joined)
    check("how to choose present", "choose" in joined)
    check("city near-phrasing present", "near me" in joined and "austin" in joined)
    check("competitor comparison present", "rival plumbing" in joined)
    check("instructions require a session that never saw this chat, with search on",
          any("never seen this chat" in s.lower() for s in q["instructions"])
          and any("search" in s.lower() for s in q["instructions"]))
    check("instructions never hand a step to a person",
          not any(w in " ".join(q["instructions"]).lower() for w in ("paste", "copy each", "by hand")))
    vendor = av.build_questions("Acme Software", "contract analytics", None, ["Rival Co"])
    vjoined = " ".join(vendor).lower()
    check("without a city the set is vendor-phrased, never 'near me'",
          "near me" not in vjoined and "vendor" in vjoined)
    rec = av.analyze_answer("Is Acme Software or Rival Co better?", "Acme Software is fine.", "Acme Software")
    check("a question naming the business is marked branded", rec["branded"] is True)
    rec = av.analyze_answer("Which vendors provide contract analytics?", "Rival Co.", "Acme Software")
    check("a discovery question is not branded", rec["branded"] is False)


def test_analyze_answer():
    answer = (
        "Here are some good options:\n"
        "1. Acme Plumbing - fast and licensed, see https://acmeplumbing.com\n"
        "2. Rival Plumbing - decent reviews\n"
        "3. Budget Pipes - cheapest option\n")
    res = av.analyze_answer("best plumber in Austin?", answer, "Acme Plumbing",
                            competitors=["Rival Plumbing", "Budget Pipes"])
    check("business named", res["named"])
    check("business at position 1", res["position"] == 1)
    check("both competitors detected",
          set(res["competitors_present"]) == {"Rival Plumbing", "Budget Pipes"})
    check("link to business detected", res["link_to_business"])

    missing = av.analyze_answer("best plumber?", "You should call Rival Plumbing or Budget Pipes.",
                                "Acme Plumbing", competitors=["Rival Plumbing", "Budget Pipes"])
    check("business not named when absent", not missing["named"] and missing["position"] is None)
    check("competitors still detected when business absent",
          set(missing["competitors_present"]) == {"Rival Plumbing", "Budget Pipes"})

    alias = av.analyze_answer("acme?", "I recommend Acme for your pipes.", "Acme Plumbing",
                              aliases=["Acme"])
    check("alias match counts as named", alias["named"])


def test_record_and_report_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        os.environ["MARKETING_MCP_DATA_DIR"] = d
        try:
            answers1 = [
                {"question": "best plumber in Austin?",
                 "answer": "1. Rival Plumbing\n2. Acme Plumbing is also good."},
                {"question": "cheap plumber?", "answer": "Try Budget Pipes."},
            ]
            r1 = av.visibility_record("Acme Plumbing", answers1, assistant="claude",
                                      run_date="2026-01-01",
                                      competitors=["Rival Plumbing", "Budget Pipes"])
            check("share of answer is named over asked", r1["share_of_answer"] == 0.5)
            check("avg position when named", r1["avg_position_when_named"] == 2.0)
            check("never-named question listed", "cheap plumber?" in r1["never_named_questions"])
            check("store file created", os.path.exists(os.path.join(d, av.STORE_NAME)))

            answers2 = [
                {"question": "best plumber in Austin?",
                 "answer": "1. Acme Plumbing is the top pick. 2. Rival Plumbing."},
                {"question": "cheap plumber?", "answer": "Acme Plumbing has fair prices."},
            ]
            av.visibility_record("Acme Plumbing", answers2, assistant="claude",
                                 run_date="2026-04-01",
                                 competitors=["Rival Plumbing", "Budget Pipes"])

            rep = av.visibility_report("Acme Plumbing", assistant="claude")
            check("two runs recorded", rep["runs"] == 2)
            check("share rose to full in the second run", rep["share_of_answer_latest"] == 1.0)
            check("change since first run is positive", rep["share_change_since_first"] == 0.5)
            check("over_time is in date order",
                  [r["run_date"] for r in rep["over_time"]] == ["2026-01-01", "2026-04-01"])
            check("no question is never-named across both runs", rep["never_named_questions"] == [])
        finally:
            del os.environ["MARKETING_MCP_DATA_DIR"]


def main():
    test_questions()
    test_analyze_answer()
    test_record_and_report_roundtrip()
    print("all checks passed")


if __name__ == "__main__":
    main()
