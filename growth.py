# Copyright (c) 2026 The Wayfinder Trust - Jonathan Luethke
# All Rights Reserved. Proprietary and Confidential.
"""Growth teardown: read a company's public growth signals and put dates on them.

Two readings, both without credentials:

  signals_now   the growth stack a site runs today (ad pixels, attribution and
                affiliate tools, analytics, social profiles, site sections,
                AI-search readiness)
  teardown      the same reading taken over archived copies of the homepage,
                turned into a timeline with a date bracket on every move

Sources are public: the site's own HTML, robots.txt, llms.txt, its tag-manager
container, and the Internet Archive (the CDX index and archived pages). Nothing
is estimated. A signal is reported with the snapshot it was first seen in and
the last snapshot it was absent from, so the reader sees how wide the bracket
is. What these sources cannot show (funding rounds, revenue, ad spend) is
listed under not_covered instead of being guessed.
"""
from __future__ import annotations

import datetime
import html as _html
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse

_CDX = "https://web.archive.org/cdx/search/cdx"

# ---- signatures -----------------------------------------------------------
# (lane, name, patterns). Patterns are matched against the page's code surface
# (script blocks, resource hints, noscript, iframes), never against body copy,
# so a blog post that mentions a vendor does not count as running it. The
# quoted "__xyz" forms are the built-in tag names inside a Google Tag Manager
# container.
SIGNATURES = [
    ("ads_tracking", "Google Ads", [r"\bAW-\d{6,}", r"googleadservices\.com", r"google_conversion_id", r'"__awct"', r'"__sp"']),
    ("ads_tracking", "Meta Pixel", [r"connect\.facebook\.net/[^\"'\s]*fbevents\.js", r"\bfbq\s*\(", r"facebook\.com/tr\?"]),
    ("ads_tracking", "TikTok Pixel", [r"analytics\.tiktok\.com", r"\bttq\.(?:load|track|page)\b"]),
    ("ads_tracking", "LinkedIn Insight", [r"snap\.licdn\.com", r"_linkedin_partner_id", r'"__bzi"']),
    ("ads_tracking", "Reddit Pixel", [r"redditstatic\.com/ads", r"\brdt\s*\(\s*['\"]init"]),
    ("ads_tracking", "Microsoft Ads UET", [r"bat\.bing\.com", r'"__baut"']),
    ("ads_tracking", "X Ads Pixel", [r"static\.ads-twitter\.com", r"\btwq\s*\(", r'"__twitter_website_tag"']),
    ("ads_tracking", "Pinterest Tag", [r"s\.pinimg\.com/ct", r"\bpintrk\s*\(", r'"__pntr"']),
    ("ads_tracking", "Snap Pixel", [r"sc-static\.net/scevent", r"\bsnaptr\s*\("]),
    ("ads_tracking", "Quora Pixel", [r"q\.quora\.com", r"\bqp\s*\(\s*['\"]init"]),
    ("ads_tracking", "Floodlight", [r"fls\.doubleclick\.net", r'"__fl[cs]"']),
    ("ads_tracking", "Google Tag Manager", [r"\bGTM-[A-Z0-9]{4,}\b", r"googletagmanager\.com/gtm\.js"]),
    ("ads_tracking", "Hyros", [r"hyros\.com", r"\bhyros\b"]),
    ("ads_tracking", "Triple Whale", [r"triplewhale", r"triplepixel"]),
    ("ads_tracking", "Northbeam", [r"northbeam"]),
    ("affiliates_referral", "Rewardful", [r"r\.wdfl\.co", r"rewardful"]),
    ("affiliates_referral", "FirstPromoter", [r"firstpromoter"]),
    ("affiliates_referral", "PartnerStack", [r"partnerstack", r"grsm\.io"]),
    ("affiliates_referral", "Impact", [r"impactradius", r"\.sjv\.io", r"impact\.com/"]),
    ("affiliates_referral", "Tolt", [r"tolt\.io"]),
    ("affiliates_referral", "Refersion", [r"refersion"]),
    ("affiliates_referral", "Tapfiliate", [r"tapfiliate"]),
    ("affiliates_referral", "PromoteKit", [r"promotekit"]),
    ("affiliates_referral", "Dub Partners", [r"dubcdn\.com", r"dub\.co/"]),
    ("affiliates_referral", "GrowSurf", [r"growsurf"]),
    ("affiliates_referral", "Viral Loops", [r"viral-loops", r"viralloops"]),
    ("affiliates_referral", "Cello", [r"cello\.so"]),
    ("analytics_product", "Google Analytics 4", [r"gtag/js\?id=G-[A-Z0-9]{6,}", r"['\"]G-[A-Z0-9]{8,}['\"]", r'"__googtag"', r'"__gaawe"']),
    ("analytics_product", "Universal Analytics", [r"\bUA-\d{4,}-\d+\b"]),
    ("analytics_product", "Segment", [r"cdn\.segment\.com", r"analytics\.load\s*\("]),
    ("analytics_product", "PostHog", [r"posthog"]),
    ("analytics_product", "Amplitude", [r"amplitude\.com", r"cdn\.amplitude"]),
    ("analytics_product", "Mixpanel", [r"mixpanel"]),
    ("analytics_product", "Heap", [r"heapanalytics", r"\bheap\.load\s*\("]),
    ("analytics_product", "Plausible", [r"plausible\.io"]),
    ("analytics_product", "Fathom", [r"usefathom"]),
    ("analytics_product", "Hotjar", [r"hotjar", r'"__hjtc"']),
    ("analytics_product", "Microsoft Clarity", [r"clarity\.ms"]),
    ("analytics_product", "FullStory", [r"fullstory"]),
    ("analytics_product", "Vercel Analytics", [r"/_vercel/insights", r"va\.vercel-scripts"]),
    ("analytics_product", "Cloudflare Web Analytics", [r"static\.cloudflareinsights"]),
    ("lifecycle_crm", "HubSpot", [r"js\.hs-scripts\.com", r"hs-analytics", r"hsforms"]),
    ("lifecycle_crm", "Intercom", [r"widget\.intercom\.io", r"intercomSettings"]),
    ("lifecycle_crm", "Klaviyo", [r"klaviyo"]),
    ("lifecycle_crm", "Customer.io", [r"customer\.io", r"customerioanalytics"]),
    ("lifecycle_crm", "Drift", [r"js\.driftt\.com"]),
    ("lifecycle_crm", "Crisp", [r"client\.crisp\.chat"]),
    ("lifecycle_crm", "Clearbit", [r"clearbitscripts", r"clearbit\.com"]),
    ("lifecycle_crm", "RB2B", [r"\brb2b\b"]),
    ("lifecycle_crm", "Apollo", [r"assets\.apollo\.io"]),
    ("lifecycle_crm", "Mailchimp", [r"list-manage\.com", r"chimpstatic"]),
    ("lifecycle_crm", "Kit", [r"convertkit"]),
    ("lifecycle_crm", "Beehiiv", [r"beehiiv"]),
    ("lifecycle_crm", "Loops", [r"loops\.so"]),
    ("experimentation", "Optimizely", [r"optimizely"]),
    ("experimentation", "VWO", [r"visualwebsiteoptimizer", r"vwo\.com"]),
    ("experimentation", "GrowthBook", [r"growthbook"]),
    ("experimentation", "Statsig", [r"statsig"]),
    ("experimentation", "LaunchDarkly", [r"launchdarkly"]),
]
_COMPILED = [(lane, name, [re.compile(p, re.I) for p in pats]) for lane, name, pats in SIGNATURES]
TAG_LANES = ("ads_tracking", "affiliates_referral", "analytics_product", "lifecycle_crm", "experimentation")

_ID_PATTERNS = {
    "Google Ads": re.compile(r"\bAW-\d{6,}"),
    "Google Tag Manager": re.compile(r"\bGTM-[A-Z0-9]{4,}\b"),
    "Google Analytics 4": re.compile(r"\bG-[A-Z0-9]{8,}\b"),
    "Universal Analytics": re.compile(r"\bUA-\d{4,}-\d+\b"),
    "Meta Pixel": re.compile(r"fbq\s*\(\s*['\"]init['\"]\s*,\s*['\"](\d{6,})"),
}

_SOCIAL = [
    ("X", re.compile(r"https?://(?:www\.)?(?:twitter|x)\.com/([A-Za-z0-9_]{1,15})(?=[/\"'?\s\\<]|$)", re.I),
     {"intent", "share", "home", "hashtag", "search", "i", "privacy", "tos", "login", "compose"}),
    ("LinkedIn", re.compile(r"https?://(?:[a-z]+\.)?linkedin\.com/((?:company|school|showcase)/[^/\"'?\s\\<]+)", re.I), set()),
    ("YouTube", re.compile(r"https?://(?:www\.)?youtube\.com/(@[\w.-]+|c/[\w.-]+|channel/[\w-]+|user/[\w.-]+)", re.I), set()),
    ("TikTok", re.compile(r"https?://(?:www\.)?tiktok\.com/(@[\w.-]+)", re.I), set()),
    ("Instagram", re.compile(r"https?://(?:www\.)?instagram\.com/([\w.]+)", re.I), {"p", "reel", "explore", "accounts"}),
    ("Facebook", re.compile(r"https?://(?:www\.)?facebook\.com/([\w.-]+)", re.I),
     {"sharer", "sharer.php", "tr", "plugins", "dialog", "share", "login", "privacy"}),
    ("Discord", re.compile(r"https?://(?:www\.)?discord\.(?:gg|com/invite)/([\w-]+)", re.I), set()),
    ("GitHub", re.compile(r"https?://(?:www\.)?github\.com/([\w.-]+)", re.I), {"login", "features", "sponsors", "apps"}),
    ("Reddit", re.compile(r"https?://(?:www\.)?reddit\.com/(r/\w+)", re.I), set()),
    ("Threads", re.compile(r"https?://(?:www\.)?threads\.(?:net|com)/(@[\w.]+)", re.I), set()),
    ("Bluesky", re.compile(r"https?://bsky\.app/profile/([\w.-]+)", re.I), set()),
    ("Telegram", re.compile(r"https?://t\.me/([\w]+)", re.I), {"share"}),
    ("Product Hunt", re.compile(r"https?://(?:www\.)?producthunt\.com/((?:products|posts)/[\w-]+)", re.I), set()),
]

# Site sections grouped by the growth play they serve.
SECTION_PLAYS = {
    "programmatic_search": {"templates", "compare", "vs", "alternatives", "alternative", "tools", "free-tools",
                            "integrations", "use-cases", "solutions", "guides", "learn", "glossary", "examples",
                            "prompts", "library", "directory", "academy"},
    "content": {"blog", "news", "newsletter", "podcast", "changelog", "resources", "stories", "press", "videos",
                "webinars", "research", "reports"},
    "partners": {"affiliates", "affiliate", "partners", "partner", "referral", "referrals", "refer", "ambassadors",
                 "creators", "experts", "agencies", "resellers"},
    "sales": {"pricing", "enterprise", "customers", "case-studies", "demo", "contact-sales", "startups", "students",
              "education", "teams", "business"},
    "community": {"community", "showcase", "gallery", "events", "hackathon", "hackathons", "launched", "launch",
                  "forum", "discord", "meetups", "champions", "hall-of-fame", "discover", "projects", "reviews"},
    "personas": {"founders", "marketers", "designers", "product-managers", "sales", "ops", "agencies-teams",
                 "freelancers", "engineers", "for-work", "for-teams", "for-startups", "for-agencies"},
    "developers": {"docs", "developers", "api", "sdk", "open-source", "mcp"},
    "hiring": {"careers", "jobs"},
}
_SECTION_TO_PLAY = {s: play for play, names in SECTION_PLAYS.items() for s in names}
# Language-code path prefixes mark a localized site: an international play.
_LOCALES = {"de", "es", "fr", "it", "ja", "ko", "pt", "pt-br", "zh", "zh-cn", "zh-tw", "hi", "id", "th", "nl",
            "pl", "tr", "ru", "sv", "da", "no", "fi", "ar", "he", "vi", "cs", "el", "ro", "hu", "en", "en-us",
            "en-gb", "es-mx", "fr-ca"}
# Legal and housekeeping pages say nothing about growth and are left out.
_LEGAL = {"privacy", "terms", "legal", "cookie-policy", "cookies", "dmca", "abuse", "security-issues",
          "data-processing-agreement", "dpa", "accessibility", "platform-rules", "sitemap", "imprint",
          "community-code-of-conduct", "code-of-conduct", "tos", "privacy-policy", "terms-of-service", "home"}


def play_of(seg: str):
    """The growth play a first path segment serves, or None."""
    if seg in _LOCALES:
        return "international"
    return _SECTION_TO_PLAY.get(seg)


_SEG_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")


def _housekeeping(seg: str) -> bool:
    """True for a path segment that is no site section: legal pages, profile
    pages, and malformed or percent-encoded paths the archive picked up."""
    return (seg in _LEGAL or seg.endswith(("-terms", "-policy")) or not _SEG_RE.fullmatch(seg))
_SKIP_SEGMENTS = {"_next", "static", "assets", "cdn-cgi", "wp-content", "wp-json", "wp-includes", "images", "img",
                  "fonts", "css", "js", "favicon.ico", "login", "signin", "sign-in", "signup", "sign-up", "auth",
                  "web"}

AI_CRAWLERS = ["GPTBot", "ChatGPT-User", "OAI-SearchBot", "ClaudeBot", "Claude-User", "Claude-SearchBot",
               "anthropic-ai", "PerplexityBot", "Perplexity-User", "Google-Extended", "Applebot-Extended",
               "CCBot", "Bytespider", "Amazonbot", "meta-externalagent"]
_ANSWER_SCHEMA = {"FAQPage", "HowTo", "QAPage", "Article", "BlogPosting", "Organization", "SoftwareApplication",
                  "Product", "WebSite", "BreadcrumbList"}

NOT_COVERED = [
    "funding rounds and valuation (read them from news and filings, one source link per row)",
    "revenue and user counts beyond what the site itself states (see stated_numbers)",
    "ad spend and ad creative (meta_ad_library returns live Meta creative once Meta is connected)",
    "search traffic volume (trend_index returns relative interest for the brand name)",
]


# ---- page reading ---------------------------------------------------------

def host_of(url_or_domain: str) -> str:
    """Bare lowercase host without a leading www, from a URL or a domain."""
    s = (url_or_domain or "").strip()
    p = urlparse(s if "://" in s else "https://" + s)
    host = (p.netloc or p.path.split("/")[0]).lower()
    host = host.split("@")[-1].split(":")[0]
    return host[4:] if host.startswith("www.") else host


_SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.I | re.S)
_NOSCRIPT_RE = re.compile(r"<noscript\b[^>]*>.*?</noscript\s*>", re.I | re.S)
_STYLE_RE = re.compile(r"<style\b[^>]*>.*?</style\s*>", re.I | re.S)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)
_LINK_RE = re.compile(r"<link\b[^>]*>", re.I)
_IFRAME_RE = re.compile(r"<iframe\b[^>]*>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_META_RE = re.compile(r"<meta\b[^>]*>", re.I)
_ATTR_RE = re.compile(r"([\w:-]+)\s*=\s*(?:\"([^\"]*)\"|'([^']*)')")
_HREF_RE = re.compile(r"href\s*=\s*[\"']([^\"'#]+)", re.I)
_TITLE_RE = re.compile(r"<title\b[^>]*>(.*?)</title\s*>", re.I | re.S)
_LD_TYPE_RE = re.compile(r"\"@type\"\s*:\s*\"([A-Za-z]+)\"")
_NUM_RE = re.compile(
    r"((?:[$€£])?\d[\d,]*(?:\.\d+)?\s?(?:[KkMmBb]\b|million|billion|thousand)?\+?)\s+"
    r"((?:[A-Za-z-]+\s){0,2}?(?:users|customers|teams|companies|developers|builders|projects|apps|websites|"
    r"sites|creators|downloads|businesses|members|stars|organizations|countries|integrations|templates|ARR))\b")


def code_surface(page: str) -> str:
    """The parts of a page where a running tool leaves a mark: script blocks,
    resource hints, noscript fallbacks and iframes. Body copy is excluded."""
    parts = _SCRIPT_RE.findall(page) + _NOSCRIPT_RE.findall(page) + _LINK_RE.findall(page) + _IFRAME_RE.findall(page)
    return "\n".join(parts)


def detect_tags(text: str) -> dict:
    """Signatures found in `text`. Returns {name: {"lane": lane, "ids": [...]}}."""
    found = {}
    for lane, name, pats in _COMPILED:
        if any(p.search(text) for p in pats):
            ids = []
            idp = _ID_PATTERNS.get(name)
            if idp is not None:
                for m in idp.finditer(text):
                    val = m.group(1) if idp.groups else m.group(0)
                    if val not in ids:
                        ids.append(val)
            found[name] = {"lane": lane, "ids": ids[:5]}
    return found


def extract_social(page: str) -> dict:
    """Social profiles linked from the page: {platform: [handles]}."""
    out = {}
    for platform, rx, skip in _SOCIAL:
        handles, seen = [], set()
        for m in rx.finditer(page):
            h = m.group(1).rstrip("/.,\\")
            if not h or h.lower() in skip or h.lower() in seen:
                continue
            seen.add(h.lower())
            handles.append(h)
        if handles:
            out[platform] = handles[:4]
    return out


def extract_sections(page: str, host: str) -> dict:
    """First path segments linked from the page on the site's own host, plus
    its linked subdomains. Returns {"paths": [...], "subdomains": [...]}."""
    paths, subs = [], []
    for href in _HREF_RE.findall(page):
        href = href.strip()
        if href.startswith("//"):
            href = "https:" + href
        if href.startswith("/"):
            path = href
        elif href.lower().startswith("http"):
            p = urlparse(href)
            h = p.netloc.lower().split(":")[0]
            h = h[4:] if h.startswith("www.") else h
            if h == host:
                path = p.path or "/"
            elif h.endswith("." + host):
                sub = h[: -len(host) - 1]
                if sub not in subs:
                    subs.append(sub)
                continue
            else:
                continue
        else:
            continue
        seg = path.split("?")[0].strip("/").split("/")[0].lower()
        if not seg or "." in seg or seg in _SKIP_SEGMENTS or len(seg) > 40 or _housekeeping(seg):
            continue
        if seg not in paths:
            paths.append(seg)
    return {"paths": paths[:80], "subdomains": subs[:20]}


def visible_text(page: str) -> str:
    t = _SCRIPT_RE.sub(" ", page)
    t = _STYLE_RE.sub(" ", t)
    t = _COMMENT_RE.sub(" ", t)
    t = _TAG_RE.sub(" ", t)
    return re.sub(r"\s+", " ", _html.unescape(t)).strip()


_INLINE_RE = re.compile(r"</?(?:span|b|strong|em|i|a|u|small|sup|sub|mark|font|abbr)\b[^>]*>", re.I)


def claim_text(page: str) -> str:
    """Visible text with a bar between block elements, so a figure in one element
    is never joined to a noun in the next."""
    t = _SCRIPT_RE.sub(" ", page)
    t = _STYLE_RE.sub(" ", t)
    t = _COMMENT_RE.sub(" ", t)
    t = _INLINE_RE.sub(" ", t)
    t = _TAG_RE.sub(" | ", t)
    return re.sub(r"\s+", " ", _html.unescape(t)).strip()


def stated_numbers(text: str) -> list:
    """Traction figures the site states about itself, verbatim. A zero (an
    animated counter caught before it runs) and a figure whose currency sign
    disagrees with its unit are dropped."""
    out = []
    for m in _NUM_RE.finditer(text):
        num, unit = m.group(1).strip(), m.group(2).strip()
        digits = sum(c.isdigit() for c in num)
        if digits < 4 and not re.search(r"[KkMmBb+]|million|billion|thousand", num):
            continue
        try:
            if float(re.sub(r"[^\d.]", "", num) or "0") == 0:
                continue
        except ValueError:
            continue
        money = num[0] in "$€£"
        if money != unit.endswith("ARR"):
            continue
        s = num + " " + unit
        if s not in out:
            out.append(s)
    return out[:10]


def page_title(page: str) -> str:
    m = _TITLE_RE.search(page)
    return re.sub(r"\s+", " ", _html.unescape(m.group(1))).strip()[:200] if m else ""


def meta_description(page: str) -> str:
    for tag in _META_RE.findall(page):
        attrs = {k.lower(): (a or b) for k, a, b in _ATTR_RE.findall(tag)}
        if attrs.get("name", "").lower() == "description" or attrs.get("property", "").lower() == "og:description":
            return _html.unescape(attrs.get("content", "")).strip()[:300]
    return ""


def read_page(page: str, host: str) -> dict:
    """One page reduced to its growth signals."""
    text = visible_text(page)
    return {
        "title": page_title(page),
        "meta_description": meta_description(page),
        "tags": detect_tags(code_surface(page)),
        "social": extract_social(page),
        "sections": extract_sections(page, host),
        "stated_numbers": stated_numbers(claim_text(page)),
        "schema_types": sorted(set(_LD_TYPE_RE.findall(page))),
        "html_bytes": len(page),
        "words": len(text.split()),
    }


# ---- robots and AI-search readiness ---------------------------------------

def parse_robots_groups(text: str) -> list:
    """robots.txt as [(agents, rules)], agents lowercased, rules as (kind, path)."""
    groups, agents, rules = [], [], []
    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, val = line.split(":", 1)
        key, val = key.strip().lower(), val.strip()
        if key == "user-agent":
            if rules:
                groups.append((agents, rules))
                agents, rules = [], []
            agents.append(val.lower())
        elif key in ("allow", "disallow"):
            if agents:
                rules.append((key, val))
    if agents:
        groups.append((agents, rules))
    return groups


def _verdict(rules) -> str:
    blocked_all = any(k == "disallow" and v == "/" for k, v in rules)
    allowed_all = any(k == "allow" and v == "/" for k, v in rules)
    if blocked_all and not allowed_all:
        return "blocked"
    if any(k == "disallow" and v for k, v in rules):
        return "partly restricted"
    return "allowed"


def ai_crawler_access(robots_text: str) -> dict:
    """What robots.txt says to each AI crawler. A crawler the file does not name
    falls under the * group."""
    groups = parse_robots_groups(robots_text)
    star = [r for agents, rules in groups if "*" in agents for r in rules]
    star_verdict = _verdict(star)
    out = {}
    for bot in AI_CRAWLERS:
        named = [r for agents, rules in groups if bot.lower() in agents for r in rules]
        is_named = any(bot.lower() in agents for agents, _ in groups)
        if is_named:
            out[bot] = {"named": True, "access": _verdict(named)}
        else:
            out[bot] = {"named": False, "access": star_verdict}
    return out


def _looks_like_text(body: str, content_type: str) -> bool:
    head = (body or "").lstrip()[:200].lower()
    return bool(head) and "html" not in (content_type or "").lower() and not head.startswith(("<!doctype", "<html"))


def _first_segment_counts(urls, host: str, top: int = 15) -> list:
    c = Counter()
    for u in urls:
        p = urlparse(u)
        seg = p.path.strip("/").split("/")[0].lower() or "(home)"
        c[seg] += 1
    return [{"section": s, "urls": n} for s, n in c.most_common(top)]


def latest_snapshot(host: str, ua: str = "marketing-mcp"):
    """Newest archived homepage of a host. Returns (timestamp, html), or
    (None, reason) when the archive holds none."""
    import httpx
    try:
        with httpx.Client(follow_redirects=True, headers={"User-Agent": ua}) as c:
            # The newest capture that the archive itself received as a 200. The
            # newest capture of any status may be a stored copy of the bot wall.
            rows = _cdx(c, [("url", host), ("fl", "timestamp"), ("filter", "statuscode:200"), ("limit", "-1")])
            if not rows:
                return None, "the archive holds no readable capture of the homepage"
            ts = rows[-1][0]
            r = c.get("https://web.archive.org/web/%sid_/http://%s/" % (ts, host), timeout=40.0)
        if r.status_code != 200:
            return None, "the archive answered HTTP %d" % r.status_code
        return ts, r.text
    except Exception as e:  # noqa: BLE001
        return None, type(e).__name__ + ": " + str(e)[:120]


def signals_now(root: str, page: str, sitemap_urls=None, ua: str = "marketing-mcp", client=None,
                archived_ts: str | None = None) -> dict:
    """The growth stack a site runs. `root` is scheme://host, `page` is the
    homepage HTML already fetched by the caller, `sitemap_urls` the URLs the
    caller discovered from the sitemap (may be empty). When the live site turns
    readers away, the caller passes the archived page and its timestamp as
    `archived_ts`; robots.txt and llms.txt are then read from the archive too."""
    import httpx
    own = client is None
    client = client or httpx.Client(timeout=20.0, follow_redirects=True, headers={"User-Agent": ua})

    def get_text(path: str):
        if archived_ts:
            return client.get("https://web.archive.org/web/%sid_/http://%s%s" % (archived_ts, host_of(root), path),
                              timeout=40.0)
        return client.get(root + path)

    try:
        host = host_of(root)
        pg = read_page(page, host)
        tags = {name: dict(info, seen_in="page html") for name, info in pg["tags"].items()}
        containers = []
        for gid in pg["tags"].get("Google Tag Manager", {}).get("ids", [])[:3]:
            try:
                r = client.get("https://www.googletagmanager.com/gtm.js", params={"id": gid})
                if r.status_code != 200:
                    containers.append({"id": gid, "read": False, "status_code": r.status_code})
                    continue
                inside = detect_tags(r.text)
                inside.pop("Google Tag Manager", None)
                containers.append({"id": gid, "read": True, "tags_inside": sorted(inside)})
                for name, info in inside.items():
                    if name not in tags:
                        tags[name] = dict(info, seen_in="tag manager container " + gid)
            except Exception as e:  # noqa: BLE001
                containers.append({"id": gid, "read": False, "error": str(e)})

        lanes = {lane: [] for lane in TAG_LANES}
        for name in sorted(tags):
            info = tags[name]
            lanes[info["lane"]].append({"name": name, "ids": info["ids"], "seen_in": info["seen_in"]})

        # robots: "read" (file parsed), "absent" (live 404: every crawler allowed),
        # or "unknown" (could not be read, so no verdict is given).
        robots_text, robots_state, llms, llms_full = "", "unknown", {"present": False}, False
        try:
            r = get_text("/robots.txt")
            if r.status_code == 200 and _looks_like_text(r.text, r.headers.get("content-type", "")):
                robots_text, robots_state = r.text, "read"
            elif r.status_code == 404 and not archived_ts:
                robots_state = "absent"
        except Exception:  # noqa: BLE001
            pass
        try:
            r = get_text("/llms.txt")
            if r.status_code == 200 and _looks_like_text(r.text, r.headers.get("content-type", "")):
                first = next((ln.strip() for ln in r.text.splitlines() if ln.strip()), "")
                llms = {"present": True, "bytes": len(r.text), "first_line": first[:120]}
        except Exception:  # noqa: BLE001
            pass
        try:
            r = get_text("/llms-full.txt")
            llms_full = r.status_code == 200 and _looks_like_text(r.text, r.headers.get("content-type", ""))
        except Exception:  # noqa: BLE001
            pass

        paths = pg["sections"]["paths"]
        by_play = {}
        for seg in paths:
            play = play_of(seg)
            if play:
                by_play.setdefault(play, []).append(seg)

        caveats = ["A tool that loads only after login, or from a script bundle that names no vendor domain, "
                   "leaves no mark in the homepage HTML and is not listed."]
        if archived_ts:
            caveats.append("The live site turned the reader away, so this reads the archived copy of %s. "
                           "The sitemap was not read, and llms.txt is reported from the archive."
                           % _day(archived_ts))
        if pg["words"] < 80:
            caveats.append("The homepage HTML carries under 80 words, so the page is rendered in the browser "
                           "and its links and stated numbers are under-read here.")
        sm = list(sitemap_urls or [])
        return {
            "site": root, "source": ("archived copy of " + _day(archived_ts)) if archived_ts else "live site",
            "title": pg["title"], "meta_description": pg["meta_description"],
            "ads_tracking": lanes["ads_tracking"], "affiliates_referral": lanes["affiliates_referral"],
            "analytics_product": lanes["analytics_product"], "lifecycle_crm": lanes["lifecycle_crm"],
            "experimentation": lanes["experimentation"],
            "tag_manager": containers,
            "social": pg["social"],
            "sections": {"linked_from_home": paths, "subdomains": pg["sections"]["subdomains"], "by_play": by_play},
            "aeo": {"llms_txt": llms, "llms_full_txt": llms_full, "robots_txt": robots_state,
                    "ai_crawlers": ai_crawler_access(robots_text) if robots_state != "unknown" else None,
                    "answer_schema": [t for t in pg["schema_types"] if t in _ANSWER_SCHEMA]},
            "stated_numbers": pg["stated_numbers"],
            "sitemap": {"url_count": len(sm), "sections": _first_segment_counts(sm, host)},
            "not_covered": NOT_COVERED, "caveats": caveats,
        }
    finally:
        if own:
            client.close()


# ---- archive reading ------------------------------------------------------

def _day(ts: str) -> str:
    return "%s-%s-%s" % (ts[0:4], ts[4:6], ts[6:8])


def _quarter(ts: str) -> str:
    return "%s-Q%d" % (ts[0:4], (int(ts[4:6]) - 1) // 3 + 1)


def _cdx(client, params, timeout: float = 45.0) -> list:
    """One CDX query. Returns data rows (header row removed). Raises on failure."""
    r = client.get(_CDX, params=list(params) + [("output", "json")], timeout=timeout)
    r.raise_for_status()
    body = r.text.strip()
    if not body:
        return []
    rows = r.json()
    return rows[1:] if rows else []


def pick_evenly(rows: list, n: int) -> list:
    """At most n rows, evenly spaced, always keeping the first and the last."""
    if n <= 0:
        return []
    if len(rows) <= n:
        return list(rows)
    if n == 1:
        return [rows[-1]]
    idx = sorted({round(i * (len(rows) - 1) / (n - 1)) for i in range(n)})
    return [rows[i] for i in idx]


def _fetch_snapshot(client, host: str, ts: str, deadline: float) -> dict:
    """One archived homepage, read as originally served (the id_ form carries no
    archive toolbar and no rewritten links)."""
    left = deadline - time.monotonic()
    if left < 3:
        return {"timestamp": ts, "error": "time budget reached before this snapshot was fetched"}
    try:
        r = client.get("https://web.archive.org/web/%sid_/http://%s/" % (ts, host), timeout=min(40.0, left))
        if r.status_code != 200:
            return {"timestamp": ts, "error": "archive returned HTTP %d" % r.status_code}
        return {"timestamp": ts, "page": r.text}
    except Exception as e:  # noqa: BLE001
        return {"timestamp": ts, "error": type(e).__name__ + ": " + str(e)[:120]}


def _signals_of(pg: dict) -> dict:
    """Flatten one page reading to {(lane, signal)} for comparison across dates."""
    sig = {}
    for name, info in pg["tags"].items():
        sig[(info["lane"], name)] = True
    for platform, handles in pg["social"].items():
        if platform == "Discord":  # invite codes rotate; the channel is the signal
            sig[("social", "Discord")] = True
            continue
        for h in handles:
            sig[("social", "%s (%s)" % (platform, h.lower()))] = True
    for seg in pg["sections"]["paths"]:
        play = play_of(seg)
        sig[("sections:" + (play or "other"), "/" + seg)] = True
    for sub in pg["sections"]["subdomains"]:
        sig[("sections:subdomain", sub + ".")] = True
    for s in pg["stated_numbers"]:
        sig[("traction_claims", s)] = True
    return sig


def build_timeline(readings: list) -> dict:
    """Turn dated page readings into lanes and a timeline.

    `readings` is a list of {"date": "YYYY-MM-DD", "page": read_page(...)} in date
    order. Each signal gets first_seen (the first snapshot that carries it),
    absent_before (the last earlier snapshot that lacks it, or None when it is
    already there in the first snapshot), last_seen, and in_latest."""
    dates = [r["date"] for r in readings]
    per = [_signals_of(r["page"]) for r in readings]
    keys = []
    for s in per:
        for k in s:
            if k not in keys:
                keys.append(k)
    lanes, timeline, at_start = {}, [], []
    for lane, signal in keys:
        present = [i for i, s in enumerate(per) if (lane, signal) in s]
        first, last = present[0], present[-1]
        entry = {"signal": signal, "first_seen": dates[first],
                 "absent_before": dates[first - 1] if first > 0 else None,
                 "last_seen": dates[last], "in_latest": last == len(per) - 1}
        lanes.setdefault(lane, []).append(entry)
        # Sections outside a named play stay in `lanes` and are kept off the
        # timeline; a nav reshuffle is reported as a removal only for tags.
        if lane == "sections:other":
            continue
        if first == 0:
            at_start.append({"lane": lane, "signal": signal})
        else:
            timeline.append({"date": dates[first], "lane": lane, "event": signal + " first seen",
                             "between": [dates[first - 1], dates[first]]})
        if last < len(per) - 1 and lane in TAG_LANES:
            timeline.append({"date": dates[last + 1], "lane": lane, "event": signal + " no longer seen",
                             "between": [dates[last], dates[last + 1]]})
    prev = None
    for r in readings:
        title = r["page"]["title"]
        if title and title != prev:
            if prev is not None:
                timeline.append({"date": r["date"], "lane": "positioning", "event": "homepage title changed",
                                 "title": title})
            prev = title
    timeline.sort(key=lambda e: (e["date"], e["lane"], e["event"]))
    return {"lanes": lanes, "timeline": timeline, "present_at_window_start": at_start}


def site_growth(client, host: str, page_limit: int, time_cap: float) -> dict:
    """How the site grew, from the first archive capture of each HTML URL on the
    domain: new URLs per quarter, and the date each section and subdomain was
    first captured. The list is read as it streams, so a connection the archive
    closes early still yields the rows that arrived, marked partial."""
    params = [("url", host), ("matchType", "domain"), ("fl", "timestamp,original"),
              ("filter", "statuscode:200"), ("filter", "mimetype:text/html"),
              ("collapse", "urlkey"), ("limit", str(page_limit))]
    rows, partial = [], None
    t_end = time.monotonic() + time_cap
    for attempt in (1, 2):
        try:
            with client.stream("GET", _CDX, params=params, timeout=max(5.0, t_end - time.monotonic())) as r:
                if r.status_code in (429, 503, 504) and attempt == 1 and t_end - time.monotonic() > 25:
                    time.sleep(4)  # the index sheds load under this query; one more try
                    continue
                if r.status_code != 200:
                    return {"error": "the archive index answered HTTP %d for the URL list" % r.status_code}
                for line in r.iter_lines():
                    parts = line.split(" ", 1)
                    if len(parts) == 2 and parts[0].isdigit():
                        rows.append(parts)
                    if time.monotonic() > t_end:
                        partial = "the time budget ran out while the URL list was still arriving"
                        break
        except Exception as e:  # noqa: BLE001
            if not rows:
                return {"error": "the archive index did not return the URL list: " + str(e)[:120]}
            partial = "the archive closed the connection before the URL list ended"
        break
    if partial is None and len(rows) >= page_limit:
        partial = "the limit of %d URLs was reached" % page_limit
    by_q, sec_first, sec_n, host_first, host_n = Counter(), {}, Counter(), {}, Counter()
    kept = 0
    for ts, original in rows:
        if "?" in original:
            continue
        p = urlparse(original if "://" in original else "http://" + original)
        h = p.netloc.lower().split(":")[0]
        h = h[4:] if h.startswith("www.") else h
        seg = p.path.strip("/").split("/")[0].lower()
        if seg in _SKIP_SEGMENTS or "." in seg:
            continue
        kept += 1
        by_q[_quarter(ts)] += 1
        host_n[h] += 1
        if h not in host_first or ts < host_first[h]:
            host_first[h] = ts
        if h == host and seg and not _housekeeping(seg):
            sec_n[seg] += 1
            if seg not in sec_first or ts < sec_first[seg]:
                sec_first[seg] = ts
    sections = [{"section": "/" + s, "first_archived": _day(sec_first[s]), "urls": n,
                 "play": play_of(s)} for s, n in sec_n.most_common(30)]
    hosts = [{"host": h, "first_archived": _day(host_first[h]), "urls": n} for h, n in host_n.most_common(12)]
    out = {"urls_read": kept, "complete": partial is None,
           "new_urls_by_quarter": dict(sorted(by_q.items())), "sections": sections, "hosts": hosts}
    if partial:
        out["partial_reason"] = partial
        out["partial_note"] = ("The index lists URLs in alphabetical order, so a partial read covers the "
                               "alphabetically first part of the site. Counts per quarter are a floor.")
    return out


def teardown(domain: str, years: int = 3, max_snapshots: int = 10, time_budget_s: int = 120,
             ua: str = "marketing-mcp", page_limit: int = 3000) -> dict:
    """Growth timeline for a domain from archived copies of its homepage."""
    import httpx
    host = host_of(domain)
    if not host or "." not in host:
        return {"error": "give a domain such as example.com"}
    years = max(1, min(int(years), 15))
    max_snapshots = max(2, min(int(max_snapshots), 24))
    deadline = time.monotonic() + max(30, min(int(time_budget_s), 300))
    today = datetime.date.today()
    start = "%04d%02d" % (today.year - years, today.month)
    skipped = []

    with httpx.Client(follow_redirects=True, headers={"User-Agent": ua}) as client:
        try:
            months = _cdx(client, [("url", host), ("fl", "timestamp"), ("filter", "statuscode:200"),
                                   ("collapse", "timestamp:6"), ("from", start)])
        except Exception as e:  # noqa: BLE001
            return {"domain": host, "error": "the Internet Archive index did not answer: " + str(e)[:160]}
        if not months:
            return {"domain": host, "error": "the Internet Archive holds no homepage capture of %s since %s-%s"
                                             % (host, start[:4], start[4:])}
        first_ever = None
        try:
            fe = _cdx(client, [("url", host), ("fl", "timestamp"), ("filter", "statuscode:200"), ("limit", "1")])
            first_ever = _day(fe[0][0]) if fe else None
        except Exception:  # noqa: BLE001
            skipped.append("date of the first archive capture")

        chosen = [row[0] for row in pick_evenly(months, max_snapshots)]
        with ThreadPoolExecutor(max_workers=4) as pool:
            fetched = list(pool.map(lambda ts: _fetch_snapshot(client, host, ts, deadline), chosen))
        readings, failed = [], []
        for f in fetched:
            if "page" in f:
                readings.append({"date": _day(f["timestamp"]), "page": read_page(f["page"], host)})
            else:
                failed.append({"date": _day(f["timestamp"]), "error": f["error"]})
        if not readings:
            return {"domain": host, "error": "no archived homepage could be read", "snapshots_failed": failed}

        built = build_timeline(readings)

        # Exact first-capture date of each named section's own page: one cheap
        # index lookup per section, sharper than a bracket between two snapshots.
        named = [(lane, e) for lane, entries in built["lanes"].items()
                 if lane.startswith("sections:") and lane not in ("sections:other", "sections:subdomain")
                 for e in entries][:24]

        def _first_capture(item):
            left = deadline - time.monotonic()
            if left < 6:
                return None
            try:
                rows = _cdx(client, [("url", host + item[1]["signal"]), ("fl", "timestamp"),
                                     ("filter", "statuscode:200"), ("limit", "1")], timeout=min(20.0, left))
                return _day(rows[0][0]) if rows else None
            except Exception:  # noqa: BLE001
                return None

        with ThreadPoolExecutor(max_workers=4) as pool:
            firsts = list(pool.map(_first_capture, named))
        by_event = {}
        for (lane, e), d in zip(named, firsts):
            e["page_first_archived"] = d
            by_event[(lane, e["signal"] + " first seen")] = d
        for ev in built["timeline"]:
            d = by_event.get((ev["lane"], ev["event"]))
            if d:
                ev["page_first_archived"] = d
        if named and not any(firsts):
            skipped.append("first archive capture of each section page")

        llms_first = None
        if deadline - time.monotonic() > 8:
            try:
                rows = _cdx(client, [("url", host + "/llms.txt"), ("fl", "timestamp"),
                                     ("filter", "statuscode:200"), ("limit", "1")],
                            timeout=min(30.0, deadline - time.monotonic()))
                llms_first = _day(rows[0][0]) if rows else None
            except Exception:  # noqa: BLE001
                skipped.append("first archive capture of llms.txt")
        else:
            skipped.append("first archive capture of llms.txt")
        if llms_first:
            built["timeline"].append({"date": llms_first, "lane": "aeo",
                                      "event": "llms.txt first captured by the archive"})
            built["timeline"].sort(key=lambda e: (e["date"], e["lane"], e["event"]))

        growth = None
        left = deadline - time.monotonic()
        if left > 15:
            growth = site_growth(client, host, page_limit, time_cap=min(75.0, left - 5))
        else:
            skipped.append("site growth by quarter")

    snaps = [{"date": r["date"], "title": r["page"]["title"], "words": r["page"]["words"],
              "tags": sorted(r["page"]["tags"]), "social": sorted(r["page"]["social"]),
              "stated_numbers": r["page"]["stated_numbers"]} for r in readings]
    caveats = [
        "Each date is a bracket: a signal first seen in one snapshot arrived some time after the snapshot "
        "before it. Raise max_snapshots to narrow the brackets.",
        "Archived HTML shows tags placed in the page. Tags fired from inside a tag manager are visible only "
        "for the live site, through growth_signals.",
        "A tag 'no longer seen' left the homepage markup. It may still run from a tag manager, a script "
        "bundle or the server, so read it as a change of placement unless growth_signals also lacks it.",
    ]
    thin = [s["date"] for s in snaps if s["words"] < 80]
    if thin:
        caveats.append("These snapshots carry under 80 words of HTML (the page renders in the browser), so "
                       "links and stated numbers are under-read on: " + ", ".join(thin))
    return {
        "domain": host,
        "window": {"from": readings[0]["date"], "to": readings[-1]["date"], "first_archived": first_ever,
                   "months_with_captures": len(months)},
        "snapshots_read": len(readings), "snapshots_failed": failed,
        "timeline": built["timeline"],
        "lanes": built["lanes"],
        "present_at_window_start": built["present_at_window_start"],
        "aeo": {"llms_txt_first_archived": llms_first},
        "site_growth": growth,
        "snapshots": snaps,
        "skipped": skipped, "not_covered": NOT_COVERED, "caveats": caveats,
    }
