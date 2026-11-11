# Copyright (c) 2026 The Wayfinder Trust - Jonathan Luethke
# All Rights Reserved. Proprietary and Confidential.
"""Ask Claude a list of buyer questions, each in its own fresh session, with web search on.

This is the measurement half of AI visibility: a buyer asks an assistant who to
hire, and the assistant answers from what it finds. Asking inside the chat the
user is already in would be contaminated by that chat's context, so each question
goes to the Claude API as a new conversation with no history and no memory, with
the server-side web search tool enabled, and the answer comes back with the links
it cited. visibility_record then counts whether the business was named.

Needs an Anthropic API key (ANTHROPIC_API_KEY, saved from chat with set_anthropic_key)
and the anthropic Python package.
"""
from __future__ import annotations

import os

DEFAULT_MODEL = "claude-opus-5-5"
WEB_SEARCH_TOOL = {"type": "web_search_20260209", "name": "web_search", "max_uses": 5}
SYSTEM = ("Answer the user's question the way you would for anyone asking it, using web search for current "
          "information. Name specific businesses where the question calls for them.")


def _client():
    import anthropic
    return anthropic, anthropic.Anthropic()


def _parse(response) -> dict:
    """Text answer and cited URLs from one Messages response."""
    texts, urls = [], []
    for block in getattr(response, "content", None) or []:
        btype = getattr(block, "type", "")
        if btype == "text":
            texts.append(getattr(block, "text", "") or "")
            for cit in getattr(block, "citations", None) or []:
                url = getattr(cit, "url", None)
                if url and url not in urls:
                    urls.append(url)
        elif btype == "web_search_tool_result":
            content = getattr(block, "content", None)
            if isinstance(content, list):  # success is a list; an error is a single object
                for res in content:
                    url = getattr(res, "url", None)
                    if url and url not in urls:
                        urls.append(url)
    return {"answer": "".join(texts).strip(), "cited_urls": urls}


def ask_one(question: str, model: str | None = None, client=None, anthropic_mod=None) -> dict:
    """Ask one question in a fresh conversation. Continues a paused server-tool turn up to 3 times."""
    if client is None:
        anthropic_mod, client = _client()
    model = model or os.environ.get("MARKETING_MCP_ASK_MODEL") or DEFAULT_MODEL
    messages = [{"role": "user", "content": question}]
    response = None
    for _ in range(4):
        response = client.beta.messages.create(
            model=model, max_tokens=16000, system=SYSTEM, messages=messages,
            tools=[WEB_SEARCH_TOOL],
            betas=["server-side-fallback-2026-07-01"],
            extra_body={"fallbacks": "default"},
        )
        if getattr(response, "stop_reason", None) != "pause_turn":
            break
        messages.append({"role": "assistant", "content": response.content})
    out = {"question": question, **_parse(response), "model": getattr(response, "model", model),
           "stop_reason": getattr(response, "stop_reason", None)}
    if out["stop_reason"] == "refusal":
        details = getattr(response, "stop_details", None)
        out["refusal_category"] = getattr(details, "category", None) if details else None
    return out


def ask_all(questions, model: str | None = None) -> dict:
    """Ask every question, one fresh session each. Returns {answers, asked, failed, model}."""
    questions = [q.get("question") if isinstance(q, dict) else q for q in (questions or [])]
    questions = [q for q in questions if q]
    if not questions:
        return {"error": "no questions given"}
    if not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
        return {"needs_setup": "no Anthropic API key is set. Save one from chat with set_anthropic_key."}
    try:
        anthropic_mod, client = _client()
    except ImportError:
        return {"needs_setup": "the anthropic package is not installed. Run: pip install anthropic"}
    except Exception as e:  # noqa: BLE001  (the client raises when no credential is found)
        return {"needs_setup": "no Anthropic API key found (%s). Save one with set_anthropic_key." % str(e)[:120]}
    answers, failed = [], 0
    for q in questions:
        try:
            answers.append(ask_one(q, model=model, client=client, anthropic_mod=anthropic_mod))
        except anthropic_mod.AuthenticationError:
            return {"needs_setup": "the Anthropic API key was rejected. Save a valid one with set_anthropic_key."}
        except anthropic_mod.RateLimitError as e:
            failed += 1
            answers.append({"question": q, "error": "rate limited: " + str(e)[:160]})
        except anthropic_mod.APIStatusError as e:
            failed += 1
            answers.append({"question": q, "error": "API error %s: %s" % (e.status_code, str(e)[:160])})
        except anthropic_mod.APIConnectionError as e:
            failed += 1
            answers.append({"question": q, "error": "connection error: " + str(e)[:160]})
    return {"answers": answers, "asked": len(questions), "failed": failed,
            "model": model or os.environ.get("MARKETING_MCP_ASK_MODEL") or DEFAULT_MODEL,
            "method": "one fresh API session per question, web search on, no history or memory"}
