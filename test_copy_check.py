# Copyright (c) 2026 The Wayfinder Trust - Jonathan Luethke
# All Rights Reserved. Proprietary and Confidential.
"""Offline checks for copy_check.py. No network. Run: python test_copy_check.py"""
import copy_check as cc


def check(name, cond):
    if not cond:
        raise AssertionError(name)
    print("ok  " + name)


def rules(text, **kw):
    return cc.copy_check(text, **kw)["counts"]


def test_claims():
    sourced = cc.copy_check("We cut costs by 40% according to the 2025 audit.")
    check("a sourced number is not flagged", sourced["counts"].get("unsourced_claim", 0) == 0)

    url = cc.copy_check("Traffic rose 300%. See https://example.com/report for the data.")
    check("a number sourced by a URL in the next sentence is not flagged",
          url["counts"].get("unsourced_claim", 0) == 0)

    bare = cc.copy_check("We grew revenue 300% last year.")
    check("a bare number is flagged as an unsourced claim",
          bare["counts"].get("unsourced_claim", 0) >= 1)

    sup = cc.copy_check("We are the best tool on the market.")
    check("a bare superlative is flagged", sup["counts"].get("unsourced_claim", 0) >= 1)


def test_ai_tells():
    em = cc.copy_check("It works — really well.")
    check("em-dash flagged as an AI tell", em["counts"].get("ai_tell_dash", 0) == 1)
    check("number range with en-dash is not flagged",
          cc.copy_check("Open 9–17 daily.", check_claims=False)["counts"].get("ai_tell_dash", 0) == 0)
    check("stock opener flagged", rules("Let us delve into this topic.").get("ai_tell_phrase", 0) >= 1)
    check("closing tic flagged",
          rules("Let me know if you have any questions.").get("ai_tell_closer", 0) == 1)


def test_hype_hedge_punct():
    check("hype adjectives flagged", rules("Our seamless, powerful platform.").get("hype_adjective", 0) == 2)
    check("hedge flagged", rules("We believe this is useful.").get("hedge", 0) == 1)
    check("exclamation flagged", rules("Buy now!").get("exclamation", 0) == 1)


def test_readability():
    long_one = "This " + "very " * 40 + "long sentence keeps going."
    check("over-35-word sentence flagged", rules(long_one).get("long_sentence", 0) >= 1)
    check("passive voice estimated",
          rules("The report was written by the team.").get("passive_voice", 0) >= 1)


def test_spelling():
    check("British spellings flagged under en-US",
          rules("We optimise the colour.").get("british_spelling", 0) == 2)
    check("British spellings ignored under en-GB",
          rules("We optimise the colour.", locale="en-GB").get("british_spelling", 0) == 0)


def test_caller_rules():
    check("banned word flagged", rules("Our widget is fine.", banned_words=["widget"]).get("banned_word", 0) == 1)
    check("extra rule flagged",
          rules("Please use our solution.", extra_rules={"jargon": ["solution"]}).get("jargon", 0) == 1)


def test_pass_and_shape():
    clean = cc.copy_check("We shipped the feature on time.")
    check("clean copy passes", clean["pass"] and clean["issue_count"] == 0)
    one = cc.copy_check("Buy now!")
    check("issue carries line, column, rule, suggestion",
          one["issues"][0]["line"] == 1 and one["issues"][0]["column"] >= 1
          and one["issues"][0]["rule"] == "exclamation" and one["issues"][0]["suggestion"])
    check("failing copy does not pass", one["pass"] is False)


def main():
    test_claims()
    test_ai_tells()
    test_hype_hedge_punct()
    test_readability()
    test_spelling()
    test_caller_rules()
    test_pass_and_shape()
    print("all checks passed")


if __name__ == "__main__":
    main()
