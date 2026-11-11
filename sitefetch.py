# Copyright (c) 2026 The Wayfinder Trust - Jonathan Luethke
# All Rights Reserved. Proprietary and Confidential.
"""Shared page fetching for every module that reads public web pages.

One place for: the User-Agent, fetching a page, deciding whether a response is a
page that may be audited (a bot wall, a 404 or a 5xx is reported, never scored),
the site root of a URL, robots.txt rules, and sitemap discovery. server.py and the
logic modules (growth, seo_rules, prospecting, site_hygiene) all call these, so a
fix to how a wall is detected lands everywhere at once.
"""
from __future__ import annotations

from urllib.parse import urlparse

UA = "Mozilla/5.0 (compatible; marketing-mcp/1.0; +https://wayfindersystemsgroup.com)"

# Status codes that mean "we were turned away at the door", not "this page is
# bad". A WAF answering 403 or 429 serves a challenge page whose markup has no
# title, no h1, no description and about nine words on it, so auditing that
# response scores the wall and reports it as the customer's site.
WALL_CODES = {401, 403, 406, 409, 418, 429, 503}


def site_root(url: str) -> str:
    """scheme://host for a URL or a bare domain (https assumed)."""
    p = urlparse(url if "://" in url else "https://" + url)
    return "%s://%s" % (p.scheme or "https", p.netloc)


def normalize_url(url: str) -> str:
    """Add https:// to a bare domain; leave a full URL alone."""
    url = (url or "").strip()
    return url if "://" in url else "https://" + url


def fetch(url: str, timeout: float = 20.0, ua: str = UA):
    """GET a URL following redirects. Returns the httpx response; raises on a
    network failure so the caller can report it in its own words."""
    import httpx
    return httpx.get(normalize_url(url), timeout=timeout, follow_redirects=True,
                     headers={"User-Agent": ua})


def fetch_soup(url: str, timeout: float = 20.0, ua: str = UA):
    """Fetch and parse. Returns (response, soup). Raises ImportError when
    beautifulsoup4 is missing, or the network error."""
    from bs4 import BeautifulSoup
    r = fetch(url, timeout=timeout, ua=ua)
    return r, BeautifulSoup(r.text, "html.parser")


def unreadable(r) -> dict | None:
    """None when the response is a page that may be audited, else why it may not.

    Anything outside 2xx is refused rather than audited. A 404 or a 500 is a real
    finding about that URL and is reported as one, but it is not a page whose title
    and word count mean anything.
    """
    code = getattr(r, "status_code", None)
    if code is None:
        return {"error": "no HTTP response", "readable": False}
    if 200 <= code < 300:
        return None
    final = str(getattr(r, "url", "") or "")
    server_hdr = ""
    try:
        server_hdr = (r.headers.get("server") or "").lower()
    except Exception:  # noqa: BLE001
        pass
    if code in WALL_CODES:
        who = server_hdr or "the site's firewall"
        return {
            "status_code": code, "url": final, "readable": False, "blocked": True,
            "error": (f"blocked before the page could be read (HTTP {code} from "
                      f"{who}). This is a bot wall, not a defect in the site, and "
                      "the site may well load normally in a browser. No audit was "
                      "run and no score is reported, because scoring the block "
                      "page would describe the wall rather than the site."),
        }
    if code == 404:
        return {"status_code": code, "url": final, "readable": False, "blocked": False,
                "error": "that URL returns 404. The page does not exist, so there "
                         "is nothing on it to audit."}
    if code >= 500:
        return {"status_code": code, "url": final, "readable": False, "blocked": False,
                "error": f"the server returned HTTP {code}. The site is erroring, "
                         "so there is no page to audit."}
    return {"status_code": code, "url": final, "readable": False, "blocked": False,
            "error": f"HTTP {code}, which is not a readable page."}


def get_page(url: str, timeout: float = 20.0, ua: str = UA):
    """Fetch and parse one page for an auditing tool.

    Returns (response, soup, None) for a readable page, or (response_or_None, None,
    error_dict) when the page cannot be audited, so callers never score a wall.
    """
    try:
        r, soup = fetch_soup(url, timeout=timeout, ua=ua)
    except ImportError:
        return None, None, {"error": "beautifulsoup4 not installed. Run: pip install beautifulsoup4"}
    except Exception as e:  # noqa: BLE001
        return None, None, {"error": "fetch failed: " + str(e)[:200], "url": url, "readable": False}
    bad = unreadable(r)
    if bad:
        return r, None, bad
    return r, soup, None


def parse_robots_text(text: str):
    """Return (rules, sitemaps) from a robots.txt body. rules has disallow/allow
    path lists for the * user-agent; sitemaps lists declared Sitemap: URLs."""
    sitemaps, disallow, allow = [], [], []
    agent_star = False
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        low = line.lower()
        if low.startswith("sitemap:"):
            sitemaps.append(line.split(":", 1)[1].strip())
        elif low.startswith("user-agent:"):
            agent_star = line.split(":", 1)[1].strip() == "*"
        elif agent_star and low.startswith("disallow:"):
            disallow.append(line.split(":", 1)[1].strip())
        elif agent_star and low.startswith("allow:"):
            allow.append(line.split(":", 1)[1].strip())
    return {"disallow": disallow, "allow": allow}, sitemaps


def parse_robots(root: str, ua: str = UA):
    """Fetch robots.txt for a site root and parse it. Returns (rules, sitemaps);
    an unreachable robots.txt yields empty rules."""
    try:
        r = fetch(root + "/robots.txt", timeout=15.0, ua=ua)
        if r.status_code < 400:
            return parse_robots_text(r.text)
    except Exception:  # noqa: BLE001
        pass
    return {"disallow": [], "allow": []}, []


def parse_sitemap(xml_text):
    """Return (child_sitemaps, page_urls) from a sitemap body. A <sitemapindex>
    yields child sitemaps; a <urlset> yields page URLs."""
    entries = parse_sitemap_entries(xml_text)
    if entries is None:
        return [], []
    kind, rows = entries
    locs = [row["loc"] for row in rows]
    return (locs, []) if kind == "sitemapindex" else ([], locs)


def parse_sitemap_entries(xml_text):
    """Return (kind, rows) where kind is 'sitemapindex' or 'urlset' and each row is
    {'loc', 'lastmod'}; None when the body is not XML."""
    import xml.etree.ElementTree as ET
    try:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except Exception:  # noqa: BLE001
        return None
    kind = root.tag.rsplit("}", 1)[-1]
    rows = []
    for child in root:
        loc = lastmod = None
        for el in child.iter():
            tag = el.tag.rsplit("}", 1)[-1]
            if tag == "loc" and el.text:
                loc = el.text.strip()
            elif tag == "lastmod" and el.text:
                lastmod = el.text.strip()
        if loc:
            rows.append({"loc": loc, "lastmod": lastmod})
    return kind, rows


def sitemap_urls(root: str, declared_sitemaps, limit: int = 200, ua: str = UA):
    """Discover up to `limit` page URLs for a site from its sitemap(s), following
    sitemap-index nesting. Returns (urls, info)."""
    queue = list(declared_sitemaps) or [root + "/sitemap.xml"]
    seen_sm, pages = set(), []
    info = {"sitemaps_read": [], "is_index": False}
    while queue and len(pages) < limit:
        sm = queue.pop(0)
        if sm in seen_sm:
            continue
        seen_sm.add(sm)
        try:
            r = fetch(sm, ua=ua)
            if r.status_code >= 400:
                continue
        except Exception:  # noqa: BLE001
            continue
        children, urls = parse_sitemap(r.text)
        info["sitemaps_read"].append(sm)
        if children:
            info["is_index"] = True
            queue.extend(c for c in children if c not in seen_sm)
        for u in urls:
            if len(pages) >= limit:
                break
            pages.append(u)
    return pages, info


def visible_text(soup) -> str:
    """The text a reader sees: scripts, styles, noscript and template content
    removed, whitespace collapsed. Does not modify the soup passed in."""
    import copy
    s = copy.copy(soup)
    for t in s(["script", "style", "noscript", "template", "svg"]):
        t.decompose()
    return " ".join(s.get_text(" ").split())


def same_site(url: str, root: str) -> bool:
    """True when url is on the same host as root (www. ignored)."""
    a = urlparse(normalize_url(url)).netloc.lower().removeprefix("www.")
    b = urlparse(normalize_url(root)).netloc.lower().removeprefix("www.")
    return a == b
