# Copyright (c) 2026 The Wayfinder Trust - Jonathan Luethke
# All Rights Reserved. Proprietary and Confidential.
"""On-page SEO rules for local and service businesses, as plain functions.

Seven checks a marketer runs before and while trying to rank a page:

  money_page_check      is the target keyword actually on the page (the number
                        one cause of not ranking), element by element
  competitor_page_gap   your page against up to 3 competitor pages: structure,
                        keyword use, over-optimization, trust facts, topic gaps
  missing_pages         topics your competitors have a page for and you do not
  crawl_depth           how many clicks each page sits from the homepage, plus
                        orphans and pages buried in the blog
  internal_link_plan    which posts a new post should link to and from
  paid_vs_organic       split a keyword list between Google Ads and SEO by cost
  image_check           per-image file name, alt text, format, and lazy loading

Every function fetches its own pages through sitefetch (one User-Agent, one
bot-wall rule), so a page that is a bot wall, a 404, or a 5xx is reported
through sitefetch.get_page's error dict and never scored. Parsing is split from
fetching: the _parse_* helpers take HTML strings, so the whole decision surface
runs offline in the tests.

Dependencies: stdlib, httpx (through sitefetch), beautifulsoup4.
"""
from __future__ import annotations

import re
import time
from collections import Counter
from urllib.parse import urljoin, urlparse

import sitefetch

from bs4 import BeautifulSoup

# ---- shared parsing helpers ----------------------------------------------

_WORD_RE = re.compile(r"[a-z0-9]+")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
# Words too generic to prove a page is about a topic, so they are ignored when
# scoring topical relevance and when matching an alt text to a file name.
_STOP = {"the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "with",
         "is", "are", "be", "by", "at", "as", "it", "its", "this", "that",
         "your", "our", "you", "we", "how", "what", "why", "best", "near", "me",
         "from", "page", "home", "com", "www", "http", "https"}


def _soup(html: str) -> BeautifulSoup:
    """Parse an HTML string the same way sitefetch does, so a parse helper and a
    fetched page see the markup identically."""
    return BeautifulSoup(html or "", "html.parser")


def _tokens(text: str) -> list:
    """Lowercase alphanumeric word tokens of a string."""
    return _WORD_RE.findall((text or "").lower())


def _stem(token: str) -> str:
    """Drop a simple trailing plural 's' so 'plumbers' matches 'plumber'."""
    return token[:-1] if len(token) > 3 and token.endswith("s") else token


def _stems(text: str) -> list:
    return [_stem(t) for t in _tokens(text)]


def _keyword_present(text: str, keyword: str, slop: int = 4) -> bool:
    """True when the keyword appears in the text: as a phrase, as a simple
    plural, or with its words in any order inside a short window. Matching is
    case-insensitive and plural-insensitive through stemming."""
    kt = _stems(keyword)
    if not kt:
        return False
    tt = _stems(text)
    if not tt:
        return False
    need = set(kt)
    window = len(kt) + max(0, slop)
    for i in range(len(tt)):
        if need <= set(tt[i:i + window]):
            return True
    return False


def _keyword_count(text: str, keyword: str) -> int:
    """Count non-overlapping phrase occurrences of the keyword in the text,
    plural-insensitive. This is the 'how many times is the keyword on the page'
    number, kept separate from the looser presence test above."""
    kt = _stems(keyword)
    if not kt:
        return 0
    tt = _stems(text)
    n = len(kt)
    count = i = 0
    while i <= len(tt) - n:
        if tt[i:i + n] == kt:
            count += 1
            i += n
        else:
            i += 1
    return count


def _title(soup) -> str:
    return soup.title.get_text(strip=True) if soup.title else ""


def _h1(soup) -> str:
    h = soup.find("h1")
    return h.get_text(" ", strip=True) if h else ""


def _h2_list(soup) -> list:
    return [h.get_text(" ", strip=True) for h in soup.find_all("h2") if h.get_text(strip=True)]


def _meta_description(soup) -> str:
    t = soup.find("meta", attrs={"name": "description"})
    return (t.get("content") or "").strip() if t and t.get("content") else ""


def _slug_text(url: str) -> str:
    """The URL path as words: segments joined, dashes and underscores to spaces."""
    path = urlparse(url).path or ""
    return re.sub(r"[-_/]+", " ", path).strip().lower()


def _first_words(text: str, n: int) -> str:
    return " ".join((text or "").split()[:n])


def _schema_types(soup) -> list:
    """Sorted unique schema.org @type values in the page's JSON-LD blocks."""
    import json
    types = set()

    def visit(node):
        if isinstance(node, list):
            for n in node:
                visit(n)
            return
        if not isinstance(node, dict):
            return
        if isinstance(node.get("@graph"), list):
            for n in node["@graph"]:
                visit(n)
        t = node.get("@type")
        for ty in (t if isinstance(t, list) else [t]) if t else []:
            if isinstance(ty, str):
                types.add(ty)

    for b in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = b.string or b.get_text() or ""
        try:
            visit(json.loads(raw))
        except Exception:  # noqa: BLE001
            pass
    return sorted(types)


# Trust facts a competitor can state that you cannot copy without earning. Each
# is matched against the page's visible text. The checks are deliberately simple
# patterns, not claims of truth: they say "this page asserts X", which is what a
# gap analysis compares.
_TRUST_PATTERNS = {
    "years_in_business": re.compile(
        r"\b(?:since|est\.?|established|serving[^.]{0,30}since)\s+(?:19|20)\d{2}\b"
        r"|\b\d{1,3}\+?\s+years?\b", re.I),
    "licensed": re.compile(r"\blicen[sc]ed\b", re.I),
    "insured": re.compile(r"\binsured\b", re.I),
    "certified": re.compile(r"\bcertifi(?:ed|cation)\b", re.I),
    "award": re.compile(r"\baward(?:-?winning|ed|s)?\b", re.I),
    "reviews_count": re.compile(r"\b\d[\d,]*\+?\s+(?:5-?star\s+)?(?:reviews|ratings)\b", re.I),
    "phone": re.compile(r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    "hours": re.compile(
        r"\b(?:24/7|open\s+24)\b"
        r"|\b\d{1,2}(?::\d{2})?\s*(?:am|pm)\b"
        r"|\b(?:mon|tue|wed|thu|fri|sat|sun)(?:day|s|\.)?\b", re.I),
    "price_ranges": re.compile(
        r"[$\u20ac\u00a3]\s?\d|\bstarting\s+at\b|\bprice\s+range|\bper\s+(?:hour|visit|job)\b", re.I),
    "service_areas": re.compile(
        r"\bservice\s+areas?\b|\bareas?\s+we\s+serve\b|\bwe\s+serve\b|\bserving\s+[A-Z]", re.I),
}


def _trust_facts(text: str) -> list:
    """Sorted names of the trust facts the visible text asserts."""
    return sorted(name for name, rx in _TRUST_PATTERNS.items() if rx.search(text or ""))


def _is_blog_url(url: str) -> bool:
    """True when a URL lives under a blog, news, or dated-archive path."""
    segs = [s.lower() for s in urlparse(url).path.split("/") if s]
    return any(s in ("blog", "news", "article", "articles", "post", "posts") for s in segs) \
        or any(re.fullmatch(r"(19|20)\d{2}", s) for s in segs)


def _canon(url: str) -> str:
    """scheme://host/path with the fragment and query dropped and a trailing
    slash removed, so the same page is counted once however it is linked."""
    p = urlparse(sitefetch.normalize_url(url))
    path = p.path or "/"
    if len(path) > 1:
        path = path.rstrip("/")
    return "%s://%s%s" % (p.scheme or "https", p.netloc.lower(), path)


def _same_site_links(soup, base_url: str, root: str, containers=None) -> list:
    """Absolute, canonicalized, same-site page links from a page. When
    `containers` is given (for example ('nav', 'header', 'footer')), only links
    inside those elements are read."""
    scopes = []
    if containers:
        for name in containers:
            scopes.extend(soup.find_all(name))
    else:
        scopes = [soup]
    out, seen = [], set()
    for scope in scopes:
        for a in scope.find_all("a", href=True):
            href = a["href"].strip()
            if href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            absolute = urljoin(base_url, href)
            if not absolute.lower().startswith(("http://", "https://")):
                continue
            if not sitefetch.same_site(absolute, root):
                continue
            c = _canon(absolute)
            if c not in seen:
                seen.add(c)
                out.append(c)
    return out


# ---- 1. money page check --------------------------------------------------

def _parse_money_page(html: str, url: str, keyword: str) -> dict:
    """The money_page_check decision logic over an HTML string (no fetching)."""
    soup = _soup(html)
    visible = sitefetch.visible_text(soup)
    title, h1 = _title(soup), _h1(soup)
    meta = _meta_description(soup)
    slug = _slug_text(url)
    first100 = _first_words(visible, 100)

    elements = {
        "visible_text": _keyword_present(visible, keyword),
        "title": _keyword_present(title, keyword),
        "h1": _keyword_present(h1, keyword),
        "url_slug": _keyword_present(slug, keyword),
        "first_100_words": _keyword_present(first100, keyword),
        "meta_description": _keyword_present(meta, keyword),
    }
    occurrences = _keyword_count(visible, keyword)

    fixes = []
    if not elements["visible_text"]:
        fixes.append("The keyword '%s' never appears in the visible body text. This is the "
                     "number one cause of not ranking. Use it naturally in the page copy "
                     "before anything else." % keyword)
    if not elements["title"]:
        fixes.append("Put '%s' in the title tag." % keyword)
    if not elements["h1"]:
        fixes.append("Put '%s' in the H1." % keyword)
    if not elements["first_100_words"]:
        fixes.append("Work '%s' into the opening (first 100 words), ideally the first sentence." % keyword)
    if not elements["url_slug"]:
        fixes.append("Reflect '%s' in the URL slug." % keyword)
    if not elements["meta_description"]:
        fixes.append("Add '%s' to the meta description for click-through." % keyword)
    if occurrences == 0 and elements["visible_text"]:
        fixes.append("The keyword matches only loosely (word order or plural). Add the exact "
                     "phrase '%s' at least once in the body." % keyword)

    return {
        "url": url,
        "keyword": keyword,
        "word_count": len(visible.split()),
        "occurrences_in_visible_text": occurrences,
        "elements": elements,
        "all_elements_pass": all(elements.values()),
        "fixes": fixes,
    }


def money_page_check(url: str, keyword: str) -> dict:
    """Check whether a money page actually uses its target keyword, element by element.

    Returns a dict: url, keyword, word_count, occurrences_in_visible_text,
    elements (visible_text / title / h1 / url_slug / first_100_words /
    meta_description, each True or False), all_elements_pass, and fixes (ordered,
    the missing-from-body fix first because it is the number one cause of not
    ranking). A bot wall, 404, or 5xx is returned as the sitefetch error dict and
    never scored.
    """
    r, soup, err = sitefetch.get_page(url)
    if err:
        return err
    return _parse_money_page(r.text, str(r.url), keyword)


# ---- 2. competitor page gap -----------------------------------------------

def _read_page_for_gap(html: str, url: str, keyword: str) -> dict:
    """Pull the comparable fields from one page's HTML for competitor_page_gap."""
    soup = _soup(html)
    visible = sitefetch.visible_text(soup)
    title, h1 = _title(soup), _h1(soup)
    meta = _meta_description(soup)
    slug = _slug_text(url)
    placements = [name for name, present in (
        ("title", _keyword_present(title, keyword)),
        ("h1", _keyword_present(h1, keyword)),
        ("meta_description", _keyword_present(meta, keyword)),
        ("url_slug", _keyword_present(slug, keyword)),
        ("visible_text", _keyword_present(visible, keyword)),
    ) if present]
    return {
        "url": url,
        "readable": True,
        "title": title,
        "meta_description": meta,
        "h1": h1,
        "h2": _h2_list(soup),
        "word_count": len(visible.split()),
        "keyword_count": _keyword_count(visible, keyword),
        "keyword_placements": placements,
        "schema_types": _schema_types(soup),
        "trust_facts": _trust_facts(visible),
    }


def _median(values: list):
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2:
        return s[mid]
    return round((s[mid - 1] + s[mid]) / 2, 1)


def competitor_page_gap(url: str, competitor_urls: list, keyword: str) -> dict:
    """Compare your page to up to 3 competitor pages for a keyword.

    Returns a dict: keyword; your_page and competitors (each with title, meta
    description, h1, h2 list, word_count, keyword_count, keyword_placements,
    schema_types, trust_facts); unreadable_competitors (listed, not counted);
    table (your page then readable competitors); over_optimization (True when
    your keyword_count exceeds the readable competitors' maximum) with
    your_keyword_count and max_competitor_keyword_count; competitor_word_count_median
    and word_count_gap_vs_median (median minus yours, positive means you are
    short); and missing_from_you (h2_topics and trust_facts present on every
    readable competitor but absent on yours). If your own page cannot be read,
    the sitefetch error dict is returned.
    """
    r, soup, err = sitefetch.get_page(url)
    if err:
        return err
    mine = _read_page_for_gap(r.text, str(r.url), keyword)

    comps, unreadable = [], []
    for cu in list(competitor_urls or [])[:3]:
        cr, cs, ce = sitefetch.get_page(cu)
        if ce:
            unreadable.append({"url": cu, "status_code": ce.get("status_code"),
                               "error": ce["error"], "blocked": ce.get("blocked", False)})
            continue
        comps.append(_read_page_for_gap(cr.text, str(cr.url), keyword))

    comp_counts = [c["keyword_count"] for c in comps]
    comp_words = [c["word_count"] for c in comps]
    max_comp = max(comp_counts) if comp_counts else 0
    median_words = _median(comp_words)

    if comps:
        h2_sets = [set(h.lower() for h in c["h2"]) for c in comps]
        trust_sets = [set(c["trust_facts"]) for c in comps]
        common_h2 = set.intersection(*h2_sets) if h2_sets else set()
        common_trust = set.intersection(*trust_sets) if trust_sets else set()
        mine_h2 = set(h.lower() for h in mine["h2"])
        missing = {
            "h2_topics": sorted(common_h2 - mine_h2),
            "trust_facts": sorted(common_trust - set(mine["trust_facts"])),
        }
    else:
        missing = {"h2_topics": [], "trust_facts": []}

    return {
        "keyword": keyword,
        "your_page": mine,
        "competitors": comps,
        "unreadable_competitors": unreadable,
        "table": [mine] + comps,
        "over_optimization": bool(comps) and mine["keyword_count"] > max_comp,
        "your_keyword_count": mine["keyword_count"],
        "max_competitor_keyword_count": max_comp,
        "competitor_word_count_median": median_words,
        "word_count_gap_vs_median": (round(median_words - mine["word_count"], 1)
                                     if median_words is not None else None),
        "missing_from_you": missing,
    }


# ---- 3. missing pages -----------------------------------------------------

def _topic_key(url: str):
    """Turn a URL into a (topic, is_money_candidate) pair.

    The topic is the last path segment that is not numbers-only, with its file
    extension stripped, dashes and underscores turned to spaces, lowercased.
    Stop words and city-like suffixes are left in place (not guessed away).
    is_money_candidate is False for blog and dated-archive paths, which are kept
    out of the money-page comparison. Returns (None, _) for the homepage or a
    path with no usable segment.
    """
    segs = [s for s in urlparse(url).path.split("/") if s]
    if not segs:
        return None, False
    clean = [re.sub(r"\.(html?|php|aspx?|jsp)$", "", s.split(";")[0], flags=re.I) for s in segs]
    lower = [c.lower() for c in clean]
    money = not ("blog" in lower or "news" in lower
                 or any(re.fullmatch(r"(19|20)\d{2}", c) for c in clean))
    key = None
    for c in reversed(clean):
        if re.fullmatch(r"\d+", c):
            continue
        key = c
        break
    if not key:
        return None, money
    topic = re.sub(r"\s+", " ", re.sub(r"[-_]+", " ", key)).strip().lower()
    return (topic or None), money


def _site_page_urls(site: str, max_pages: int) -> dict:
    """Page URLs for one site: the sitemap first, else the homepage's same-site
    nav, header, and footer links. Returns {urls, source}."""
    root = sitefetch.site_root(site)
    _rules, declared = sitefetch.parse_robots(root)
    urls, _info = sitefetch.sitemap_urls(root, declared, limit=max_pages)
    if urls:
        return {"urls": list(urls)[:max_pages], "source": "sitemap"}
    r, soup, err = sitefetch.get_page(root)
    if err or soup is None:
        return {"urls": [], "source": "none"}
    links = _same_site_links(soup, str(r.url), root, containers=("nav", "header", "footer"))
    return {"urls": links[:max_pages], "source": "homepage nav/header/footer links"}


def _topic_map(urls: list) -> dict:
    """Map each money-page topic to the first URL that produced it, in first-seen
    order (blog and dated paths excluded)."""
    out = {}
    for u in urls:
        topic, money = _topic_key(u)
        if topic and money and topic not in out:
            out[topic] = u
    return out


def missing_pages(site: str, competitor_sites: list, max_pages: int = 200) -> dict:
    """Topics competitors have a money page for and you do not.

    Gathers page URLs for each site from its sitemap, or if there is none from
    the homepage's same-site nav, header, and footer links. Each URL becomes a
    topic key (the last non-numeric path segment, extension stripped, dashes to
    spaces, lowercased); blog and dated paths are left out of the comparison.

    Returns a dict: site; your_topics (sorted) and your_topic_count; per_site
    (each site's url_count, topic_count, and source); and missing_topics, the
    topics present on at least one competitor and absent on yours, each with the
    competitors that have it and their URLs, ranked by how many competitors have
    it (then alphabetically).
    """
    max_pages = max(1, int(max_pages))
    mine = _site_page_urls(site, max_pages)
    my_topics = _topic_map(mine["urls"])

    per_site = {sitefetch.site_root(site): {"url_count": len(mine["urls"]),
                                            "topic_count": len(my_topics), "source": mine["source"]}}
    comp_maps = []
    for cs in list(competitor_sites or []):
        info = _site_page_urls(cs, max_pages)
        tmap = _topic_map(info["urls"])
        root = sitefetch.site_root(cs)
        per_site[root] = {"url_count": len(info["urls"]), "topic_count": len(tmap), "source": info["source"]}
        comp_maps.append((root, tmap))

    agg = {}
    for root, tmap in comp_maps:
        for topic, u in tmap.items():
            if topic in my_topics:
                continue
            agg.setdefault(topic, []).append({"site": root, "url": u})
    missing = [{"topic": t, "competitor_count": len(v), "competitors": v} for t, v in agg.items()]
    missing.sort(key=lambda m: (-m["competitor_count"], m["topic"]))

    return {
        "site": sitefetch.site_root(site),
        "your_topics": sorted(my_topics),
        "your_topic_count": len(my_topics),
        "per_site": per_site,
        "missing_topics": missing,
    }


# ---- 4. crawl depth -------------------------------------------------------

def _disallowed(url: str, disallow: list) -> bool:
    path = urlparse(url).path or "/"
    return any(d and path.startswith(d) for d in disallow)


def crawl_depth(start_url: str, max_pages: int = 150, time_budget_s: int = 90) -> dict:
    """Breadth-first crawl from the homepage, recording how deep each page sits.

    Click depth is the fewest links from the homepage (depth 0) to a page. The
    crawl is sequential and polite, stays on the same host, honors the robots.txt
    disallow rules for the * user-agent, and stops at max_pages or when the time
    budget runs out.

    Returns a dict: site, start_url, pages_crawled, fetch_errors, max_depth;
    depths (every page with its depth); deeper_than_2 (pages more than 2 clicks
    from home); orphan_sitemap_urls (sitemap URLs never reached by a link);
    blog_only_pages (pages whose every inbound link comes from a blog path); and
    skipped (what the crawl did not finish and why).
    """
    max_pages = max(1, int(max_pages))
    deadline = time.monotonic() + max(5, int(time_budget_s))
    root = sitefetch.site_root(start_url)
    host = urlparse(root).netloc
    rules, declared = sitefetch.parse_robots(root)
    disallow = rules["disallow"]

    start = _canon(start_url)
    depth = {start: 0}
    inbound = {}
    visited, errors, skipped = set(), 0, []
    queue = [start]

    while queue:
        if len(visited) >= max_pages:
            skipped.append("reached the max_pages limit of %d, so deeper pages were not crawled" % max_pages)
            break
        if time.monotonic() > deadline:
            skipped.append("the %ds time budget ran out with %d page(s) still queued" % (time_budget_s, len(queue)))
            break
        u = queue.pop(0)
        if u in visited:
            continue
        if urlparse(u).netloc not in ("", host) or _disallowed(u, disallow):
            continue
        visited.add(u)
        r, soup, err = sitefetch.get_page(u)
        if err:
            errors += 1
            continue
        for link in _same_site_links(soup, str(r.url), root):
            inbound.setdefault(link, set()).add(u)
            if link not in depth:
                depth[link] = depth[u] + 1
            if link not in visited and link not in queue and len(queue) < max_pages * 4:
                queue.append(link)

    reached = sorted(visited)
    depths = [{"url": u, "depth": depth[u]} for u in reached]
    deeper = [{"url": u, "depth": depth[u]} for u in reached if depth[u] > 2]

    sitemap_urls, _info = sitefetch.sitemap_urls(root, declared, limit=max_pages * 2)
    reached_canon = {_canon(u) for u in reached}
    orphans = sorted({_canon(u) for u in sitemap_urls} - reached_canon)

    blog_only = sorted(
        u for u in reached
        if u != start and inbound.get(u) and all(_is_blog_url(src) for src in inbound[u]) and not _is_blog_url(u))

    return {
        "site": root,
        "start_url": start_url,
        "pages_crawled": len(reached),
        "fetch_errors": errors,
        "max_depth": max((d["depth"] for d in depths), default=0),
        "depths": depths,
        "deeper_than_2": deeper,
        "orphan_sitemap_urls": orphans,
        "blog_only_pages": blog_only,
        "skipped": skipped,
    }


# ---- 5. internal link plan ------------------------------------------------

def _topic_words(topic: str) -> list:
    """Significant, de-duplicated words of a topic, in first-seen order."""
    out, seen = [], set()
    for t in _tokens(topic):
        s = _stem(t)
        if s in _STOP or len(s) < 3 or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _score_text(text: str, topic_words: list) -> int:
    """How many distinct topic words appear in the text (stemmed)."""
    present = set(_stems(text))
    return sum(1 for w in topic_words if w in present)


def _anchor_sentence(text: str, topic_words: list) -> str:
    """The first sentence in the text that mentions a topic word, trimmed. This
    is the candidate anchor: the place a link to the topic would read naturally."""
    for sentence in _SENTENCE_SPLIT.split(text or ""):
        s = sentence.strip()
        if not s:
            continue
        present = set(_stems(s))
        if any(w in present for w in topic_words):
            return s[:300]
    return ""


def internal_link_plan(site: str, new_post_url: str, topic: str | None = None,
                       max_pages: int = 150) -> dict:
    """Plan the internal links for a new post: what it links to and from.

    The topic defaults to the new post's H1, or its title. Every other page on
    the site (sitemap first, else homepage links) is scored by how many topic
    words appear in its visible text and title.

    Returns a dict: site, new_post_url, topic, topic_words; link_from (3 to 5
    posts the new post should link to, highest scoring); money_page_to_link_to
    (the one non-blog page whose title and H1 best match the topic); older_posts_to_link_to_new
    (3 posts that should link to the new post, each with an anchor_sentence, the
    sentence in that page that mentions the topic); already_linking_to_new_post
    (reported separately and excluded from the suggestions); and pages_scored. A
    bot wall, 404, or 5xx on the new post itself returns the sitefetch error dict.
    """
    max_pages = max(1, int(max_pages))
    r, soup, err = sitefetch.get_page(new_post_url)
    if err:
        return err
    resolved_new = _canon(str(r.url))
    if not topic:
        topic = _h1(soup) or _title(soup)
    words = _topic_words(topic)

    root = sitefetch.site_root(site)
    _rules, declared = sitefetch.parse_robots(root)
    urls, _info = sitefetch.sitemap_urls(root, declared, limit=max_pages)
    if not urls:
        home_r, home_soup, home_err = sitefetch.get_page(root)
        urls = _same_site_links(home_soup, str(home_r.url), root) if not home_err and home_soup else []

    scored, already = [], []
    seen = {resolved_new}
    for u in urls:
        c = _canon(u)
        if c in seen:
            continue
        seen.add(c)
        pr, ps, pe = sitefetch.get_page(c)
        if pe or ps is None:
            continue
        visible = sitefetch.visible_text(ps)
        score = _score_text(visible, words) + _score_text(_title(ps), words)
        links_to_new = resolved_new in set(_same_site_links(ps, str(pr.url), root))
        rec = {"url": _canon(str(pr.url)), "title": _title(ps), "score": score,
               "is_blog": _is_blog_url(str(pr.url)), "visible": visible,
               "h1": _h1(ps), "links_to_new": links_to_new}
        if links_to_new:
            already.append(rec["url"])
        else:
            scored.append(rec)

    def _by_score(rec):
        return (-rec["score"], rec["url"])

    blog_posts = sorted((p for p in scored if p["is_blog"] and p["score"] > 0), key=_by_score)
    link_from = [{"url": p["url"], "title": p["title"], "score": p["score"]} for p in blog_posts[:5]]

    money_candidates = sorted(
        (p for p in scored if not p["is_blog"]),
        key=lambda p: (-(_score_text(p["title"] + " " + p["h1"], words)), -p["score"], p["url"]))
    money = None
    for p in money_candidates:
        if _score_text(p["title"] + " " + p["h1"], words) > 0 or p["score"] > 0:
            money = {"url": p["url"], "title": p["title"],
                     "score": _score_text(p["title"] + " " + p["h1"], words)}
            break

    older = [{"url": p["url"], "title": p["title"], "anchor_sentence": _anchor_sentence(p["visible"], words)}
             for p in blog_posts[:3]]

    return {
        "site": root,
        "new_post_url": resolved_new,
        "topic": topic,
        "topic_words": words,
        "link_from": link_from,
        "money_page_to_link_to": money,
        "older_posts_to_link_to_new": older,
        "already_linking_to_new_post": sorted(already),
        "pages_scored": len(scored) + len(already),
    }


# ---- 6. paid vs organic ---------------------------------------------------

_CPC_KEYS = ("cpc", "avg_cpc", "average_cpc")
_CPC_HIGH_KEYS = ("top_of_page_bid_high", "high_top_of_page_bid", "high_bid")
_CPC_LOW_KEYS = ("top_of_page_bid_low", "low_top_of_page_bid", "low_bid")
_DIFF_KEYS = ("difficulty", "keyword_difficulty", "kd")
# The four boxes, in a fixed order so counts and output never reshuffle.
_BOXES = ("SEO first", "Ads now, SEO long-term", "Ads for speed, content later", "Ads only")


def _row_cpc(row: dict):
    """The row's CPC and the key it came from, trying an explicit CPC first, then
    the top-of-page high bid, then the low bid, in the units keyword_research
    returns. Returns (None, None) when the row carries no cost at all."""
    for group in (_CPC_KEYS, _CPC_HIGH_KEYS, _CPC_LOW_KEYS):
        for k in group:
            if row.get(k) is not None:
                try:
                    return float(row[k]), k
                except (TypeError, ValueError):
                    continue
    return None, None


def _row_difficulty(row: dict):
    for k in _DIFF_KEYS:
        if row.get(k) is not None:
            try:
                return float(row[k])
            except (TypeError, ValueError):
                return None
    return None


def paid_vs_organic(rows: list, cpc_threshold: float | None = None,
                    difficulty_threshold: float = 30) -> dict:
    """Split keyword rows between Google Ads and SEO by cost and difficulty.

    Each row is read for a CPC (cpc / avg_cpc, else the top-of-page high bid,
    else the low bid) and, when present, a difficulty (0 to 100). The CPC split
    is the median CPC of the rows unless cpc_threshold is given; the difficulty
    split is 30 unless difficulty_threshold is given. CPC at or above the split
    is high; difficulty at or below the split is low. The four boxes: high CPC +
    low difficulty = 'SEO first'; high CPC + high difficulty = 'Ads now, SEO
    long-term'; low CPC + low difficulty = 'Ads for speed, content later'; low
    CPC + high difficulty = 'Ads only'.

    Difficulty is never invented. A row with no difficulty goes to
    unclassified_needs_difficulty with its CPC side stated.

    Returns a dict: cpc_threshold, difficulty_threshold, row_count,
    classified_count; counts (per box); boxes (per box, the rows in input order,
    each annotated with cpc, cpc_side, difficulty, difficulty_side, box); and
    unclassified_needs_difficulty.
    """
    rows = list(rows or [])
    cpcs = [c for c, _k in (_row_cpc(r) for r in rows) if c is not None]
    if cpc_threshold is None:
        cpc_threshold = _median(cpcs) if cpcs else 0.0

    boxes = {b: [] for b in _BOXES}
    unclassified = []
    classified = 0

    for row in rows:
        cpc, _k = _row_cpc(row)
        diff = _row_difficulty(row)
        cpc_side = "unknown" if cpc is None else ("high" if cpc >= cpc_threshold else "low")
        annotated = dict(row)
        annotated["cpc"] = cpc
        annotated["cpc_side"] = cpc_side
        annotated["difficulty"] = diff

        if diff is None or cpc_side == "unknown":
            annotated["missing"] = "difficulty" if diff is None else "cpc"
            unclassified.append(annotated)
            continue

        diff_side = "low" if diff <= difficulty_threshold else "high"
        annotated["difficulty_side"] = diff_side
        if cpc_side == "high":
            box = "SEO first" if diff_side == "low" else "Ads now, SEO long-term"
        else:
            box = "Ads for speed, content later" if diff_side == "low" else "Ads only"
        annotated["box"] = box
        boxes[box].append(annotated)
        classified += 1

    return {
        "cpc_threshold": round(cpc_threshold, 2) if cpc_threshold is not None else None,
        "difficulty_threshold": difficulty_threshold,
        "row_count": len(rows),
        "classified_count": classified,
        "counts": {b: len(boxes[b]) for b in _BOXES},
        "boxes": boxes,
        "unclassified_needs_difficulty": unclassified,
    }


# ---- 7. image check -------------------------------------------------------

_BAD_NAME_PATTERNS = (
    re.compile(r"^img[-_]?\d+$", re.I),
    re.compile(r"^dsc[-_]?\d*$", re.I),
    re.compile(r"^(?:screen[\s_-]?shot|screenshot)", re.I),
    re.compile(r"^photo[-_]?\d+$", re.I),
    re.compile(r"^image[-_]?\d+$", re.I),
    re.compile(r"^\d+$"),
    re.compile(r"^[0-9a-f]{16,}$", re.I),
)
_IMG_FORMATS = ("webp", "avif", "jpg", "jpeg", "png", "gif", "svg")


def _descriptive_name(stem: str) -> bool:
    """True when a file name (no extension) reads as a description rather than a
    camera dump, a screenshot, a bare number, or a hash."""
    s = stem.strip().lower()
    if not s:
        return False
    return not any(p.match(s) for p in _BAD_NAME_PATTERNS)


def _parse_image_check(html: str, url: str) -> dict:
    """The image_check decision logic over an HTML string (no fetching)."""
    soup = _soup(html)
    visible = sitefetch.visible_text(soup)
    word_count = len(visible.split())
    imgs = soup.find_all("img")

    results = []
    for img in imgs:
        src = (img.get("src") or img.get("data-src") or "").strip()
        name = urlparse(src).path.split("/")[-1].split("?")[0] if src else ""
        stem, _dot, ext = name.rpartition(".")
        stem = stem or name
        fmt = ext.lower() if ext.lower() in _IMG_FORMATS else (ext.lower() or None)
        alt_raw = img.get("alt")
        alt_present = alt_raw is not None
        alt_text = (alt_raw or "").strip()
        alt_nonempty = bool(alt_text)
        name_words = {w for w in _tokens(stem) if w not in _STOP and len(w) > 2}
        alt_words = {w for w in _tokens(alt_text) if w not in _STOP and len(w) > 2}
        results.append({
            "src": src,
            "file_name": name,
            "descriptive_name": _descriptive_name(stem),
            "alt_present": alt_present,
            "alt_nonempty": alt_nonempty,
            "alt_shares_word_with_filename": bool(name_words & alt_words),
            "format": fmt,
            "lazy": (img.get("loading") or "").strip().lower() == "lazy",
            "has_dimensions": bool((img.get("width") or "").strip()) and bool((img.get("height") or "").strip()),
        })

    per_250 = round(len(imgs) / (word_count / 250.0), 2) if word_count else None

    fixes = []
    no_alt = [r["file_name"] or r["src"] for r in results if not r["alt_nonempty"]]
    if no_alt:
        fixes.append("%d image(s) have empty or missing alt text: %s" % (len(no_alt), ", ".join(no_alt[:10])))
    non_desc = [r["file_name"] or r["src"] for r in results if not r["descriptive_name"]]
    if non_desc:
        fixes.append("%d image(s) have a non-descriptive file name (rename before upload, for example "
                     "'service-city-result.jpg'): %s" % (len(non_desc), ", ".join(non_desc[:10])))
    legacy = [r["file_name"] or r["src"] for r in results if r["format"] in ("jpg", "jpeg", "png", "gif")]
    if legacy:
        fixes.append("%d image(s) are not WebP or AVIF; convert and compress them: %s"
                     % (len(legacy), ", ".join(legacy[:10])))
    not_lazy = [r["file_name"] or r["src"] for r in results if not r["lazy"]]
    if not_lazy:
        fixes.append("%d image(s) are not lazy-loaded; add loading=\"lazy\" below the fold." % len(not_lazy))
    no_dims = [r["file_name"] or r["src"] for r in results if not r["has_dimensions"]]
    if no_dims:
        fixes.append("%d image(s) have no width/height attributes (add them to prevent layout shift)." % len(no_dims))
    if word_count and per_250 is not None and per_250 < 1 and word_count >= 500:
        fixes.append("Only %s image(s) per 250 words; aim for about one image every 200 to 300 words." % per_250)

    return {
        "url": url,
        "image_count": len(imgs),
        "word_count": word_count,
        "images_per_250_words": per_250,
        "images": results,
        "fixes": fixes,
    }


def image_check(url: str) -> dict:
    """Audit a page's images for file name, alt text, format, and lazy loading.

    Returns a dict: url, image_count, word_count, images_per_250_words; images
    (per image: src, file_name, descriptive_name, alt_present, alt_nonempty,
    alt_shares_word_with_filename, format, lazy, has_dimensions); and fixes. A
    bot wall, 404, or 5xx is returned as the sitefetch error dict.
    """
    r, soup, err = sitefetch.get_page(url)
    if err:
        return err
    return _parse_image_check(r.text, str(r.url))
