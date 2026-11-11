# Copyright (c) 2026 The Wayfinder Trust - Jonathan Luethke
# All Rights Reserved. Proprietary and Confidential.
"""Site hygiene: the housekeeping a site owner can fix before chasing rankings.

Six readings, all without credentials:

  duplicate_audit   pages that collide (same text, same title, same H1, same meta,
                    copy-suffixed slugs), orphans, broken internal links, redirects
  sitemap_hygiene   robots.txt, the XML sitemap, lastmod honesty, and what the
                    robots file tells each AI crawler
  schema_build      JSON-LD for a local business, ready to paste in a script tag
  assistants_index  an llms.txt body built from the site's own pages
  cover_image       a share-preview card whose text sits inside the crop safe zone
  strip_metadata    remove authoring metadata and C2PA/JUMBF from Office files,
                    PNGs and JPEGs

The network and the parsing are kept apart: every reading has a pure function that
works on text already fetched, so the tests run with no network. Page fetching
goes through sitefetch, so a change to how a bot wall is detected lands here too.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import struct
import time
import zlib
from collections import Counter, OrderedDict
from urllib.parse import urljoin, urlsplit, urlunsplit

import sitefetch

UA = sitefetch.UA

# The AI crawlers whose robots.txt treatment a site owner should know about.
AI_CRAWLERS = ["GPTBot", "ChatGPT-User", "OAI-SearchBot", "ClaudeBot", "Claude-User",
               "Claude-SearchBot", "PerplexityBot", "Google-Extended", "CCBot"]


# ---- small shared helpers -------------------------------------------------

def _norm_url(u: str) -> str:
    """A URL reduced to a comparable form: lowercase scheme and host, no fragment,
    no trailing slash on the path, query kept."""
    s = urlsplit(u.strip())
    path = s.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")
    return urlunsplit((s.scheme.lower(), s.netloc.lower(), path, s.query, ""))


def _slug(u: str) -> str:
    """The last non-empty path segment of a URL, lowercased."""
    segs = [s for s in urlsplit(u).path.split("/") if s]
    return segs[-1].lower() if segs else ""


def _top_segment(u: str) -> str:
    """The first path segment of a URL, '' for the site root."""
    segs = [s for s in urlsplit(u).path.split("/") if s]
    return segs[0].lower() if segs else ""


def _oneline(text: str) -> str:
    """One line: whitespace collapsed and square brackets dropped, so a Markdown
    link never breaks on a stray newline or bracket."""
    return re.sub(r"\s+", " ", (text or "").replace("[", "").replace("]", "")).strip()


# ---- 1. duplicate_audit ---------------------------------------------------

_SUFFIX_RE = re.compile(r"^(?P<base>.+?)-(?P<suffix>copy(?:-?\d+)?|[2-9])$", re.I)


def shingles(text: str, n: int = 5) -> set:
    """The set of word n-grams in `text`. A text shorter than n words yields one
    shingle (the whole text), so two short pages can still match."""
    words = (text or "").split()
    if len(words) < n:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def jaccard(a: set, b: set) -> float:
    """Jaccard overlap of two sets, 0.0 when either is empty."""
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


def page_record(url: str, html: str, root: str) -> dict:
    """One page reduced to the fields duplicate_audit compares. Parses HTML with
    no network, so the audit's grouping can be tested offline."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html or "", "html.parser")
    title = soup.title.get_text(strip=True) if soup.title else ""
    h1s = [h.get_text(" ", strip=True) for h in soup.find_all("h1")]
    desc = ""
    for tag in soup.find_all("meta"):
        name = (tag.get("name") or "").lower()
        prop = (tag.get("property") or "").lower()
        if name == "description" or prop == "og:description":
            desc = (tag.get("content") or "").strip()
            if name == "description":
                break
    text = sitefetch.visible_text(soup)
    links = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absu = urljoin(url, href)
        if not absu.lower().startswith("http"):
            continue
        if not sitefetch.same_site(absu, root):
            continue
        n = _norm_url(absu)
        if n not in seen:
            seen.add(n)
            links.append(absu.split("#", 1)[0])
    return {
        "url": url, "title": title, "h1": h1s[0] if h1s else "",
        "meta_description": desc, "text": text, "words": len(text.split()),
        "internal_links": links, "slug": _slug(url),
    }


def _group_shared(records, field):
    """Values of `field` shared by more than one record: [{value, urls}]."""
    buckets = OrderedDict()
    for r in records:
        v = (r.get(field) or "").strip()
        if v:
            buckets.setdefault(v, []).append(r["url"])
    return [{"value": v, "urls": urls} for v, urls in buckets.items() if len(urls) > 1]


def analyze_records(records: list, sitemap_urls=None, near_threshold: float = 0.8) -> dict:
    """The offline half of duplicate_audit: everything computable from the page
    records alone (no link checking). `sitemap_urls`, when given, drives orphan
    detection."""
    by_hash = OrderedDict()
    for r in records:
        h = hashlib.sha256(r["text"].encode("utf-8")).hexdigest()
        r["_hash"] = h
        by_hash.setdefault(h, []).append(r["url"])
    exact = [{"hash": h[:16], "urls": urls} for h, urls in by_hash.items() if len(urls) > 1]

    grams = [shingles(r["text"]) for r in records]
    near = []
    for i in range(len(records)):
        for j in range(i + 1, len(records)):
            if records[i]["_hash"] == records[j]["_hash"]:
                continue  # already an exact duplicate
            score = jaccard(grams[i], grams[j])
            if score >= near_threshold:
                near.append({"urls": [records[i]["url"], records[j]["url"]],
                             "score": round(score, 3)})
    near.sort(key=lambda e: -e["score"])

    collisions = []
    for r in records:
        m = _SUFFIX_RE.match(r["slug"])
        if m:
            collisions.append({"url": r["url"], "slug": r["slug"],
                               "base": m.group("base"), "suffix": m.group("suffix").lower()})

    orphans = []
    if sitemap_urls:
        linked = set()
        for r in records:
            for ln in r["internal_links"]:
                linked.add(_norm_url(ln))
        read = {_norm_url(r["url"]) for r in records}
        for u in sitemap_urls:
            n = _norm_url(u)
            # The homepage is the entry point, never an orphan.
            if urlsplit(n).path in ("", "/"):
                continue
            if n not in linked and n in read:
                orphans.append(u)

    for r in records:
        r.pop("_hash", None)
    return {
        "exact_duplicates": exact,
        "near_duplicates": near[:200],
        "shared_titles": _group_shared(records, "title"),
        "shared_h1s": _group_shared(records, "h1"),
        "shared_meta_descriptions": _group_shared(records, "meta_description"),
        "slug_collisions": collisions,
        "orphan_pages": orphans,
    }


def _check_internal_links(links, cap: int, deadline: float, ua: str = UA) -> tuple:
    """Fetch links without following redirects. Returns (broken, redirects, checked).
    broken: status >= 400 or a network failure. redirects: a 3xx (a redirect the
    internal link should be rewritten to skip)."""
    import httpx
    broken, redirects, checked = [], [], 0
    with httpx.Client(follow_redirects=False, timeout=15.0, headers={"User-Agent": ua}) as c:
        for u in links:
            if checked >= cap or time.monotonic() > deadline:
                break
            checked += 1
            try:
                r = c.head(u)
                if r.status_code in (403, 405, 501) or r.status_code >= 500:
                    r = c.get(u)  # some servers refuse HEAD; confirm with GET
            except Exception as e:  # noqa: BLE001
                broken.append({"url": u, "error": type(e).__name__ + ": " + str(e)[:100]})
                continue
            code = r.status_code
            if 300 <= code < 400:
                redirects.append({"url": u, "status_code": code,
                                  "location": r.headers.get("location")})
            elif code >= 400:
                broken.append({"url": u, "status_code": code})
    return broken, redirects, checked


def duplicate_audit(start_url: str, max_pages: int = 100, time_budget_s: int = 90) -> dict:
    """Read a site (sitemap first, else a same-site crawl) and report the pages
    that collide, the orphans, the broken internal links and the redirects its own
    links point at."""
    root = sitefetch.site_root(start_url)
    max_pages = max(1, min(int(max_pages), 500))
    deadline = time.monotonic() + max(10, min(int(time_budget_s), 600))
    rules, declared = sitefetch.parse_robots(root, ua=UA)
    sm_urls, _info = sitefetch.sitemap_urls(root, declared, limit=max(max_pages, 50), ua=UA)
    if sm_urls:
        mode, queue = "sitemap", list(sm_urls)
    else:
        mode, queue = "crawl", [sitefetch.normalize_url(start_url)]

    records, skipped, seen = [], [], set()
    while queue and len(records) < max_pages:
        if time.monotonic() > deadline:
            skipped.append({"url": queue[0], "reason": "time budget reached before this page was read"})
            break
        u = queue.pop(0)
        n = _norm_url(u)
        if n in seen:
            continue
        seen.add(n)
        if not sitefetch.same_site(u, root):
            continue
        r, soup, err = sitefetch.get_page(u, ua=UA)
        if err:
            skipped.append({"url": u, "status_code": err.get("status_code"),
                            "reason": err.get("error", "unreadable")[:160]})
            continue
        rec = page_record(str(r.url), r.text, root)
        records.append(rec)
        if mode == "crawl":
            for ln in rec["internal_links"]:
                if _norm_url(ln) not in seen:
                    queue.append(ln)

    analysis = analyze_records(records, sm_urls if sm_urls else None)

    all_links, seen_l = [], set()
    for rec in records:
        for ln in rec["internal_links"]:
            n = _norm_url(ln)
            if n not in seen_l:
                seen_l.add(n)
                all_links.append(ln)
    broken, redirects, checked = _check_internal_links(all_links, cap=150, deadline=deadline)

    return {
        "site": root, "seed_mode": mode, "pages_read": len(records),
        "exact_duplicates": analysis["exact_duplicates"],
        "near_duplicates": analysis["near_duplicates"],
        "shared_titles": analysis["shared_titles"],
        "shared_h1s": analysis["shared_h1s"],
        "shared_meta_descriptions": analysis["shared_meta_descriptions"],
        "slug_collisions": analysis["slug_collisions"],
        "orphan_pages": analysis["orphan_pages"],
        "broken_internal_links": broken,
        "redirects_owed": redirects,
        "internal_links_checked": checked,
        "skipped": skipped,
    }


# ---- 2. sitemap_hygiene ---------------------------------------------------

def _robots_groups(text: str) -> list:
    """robots.txt as [(agents_lowercased, [(kind, path)])]."""
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
        elif key in ("allow", "disallow") and agents:
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


def ai_crawler_rules(robots_text: str, crawlers=None) -> dict:
    """What robots.txt says to each AI crawler. A crawler the file does not name
    inherits the * group."""
    crawlers = crawlers or AI_CRAWLERS
    groups = _robots_groups(robots_text)
    star = [r for agents, rules in groups if "*" in agents for r in rules]
    star_verdict = _verdict(star)
    out = {}
    for bot in crawlers:
        low = bot.lower()
        named = any(low in agents for agents, _ in groups)
        if named:
            rules = [r for agents, rules in groups if low in agents for r in rules]
            out[bot] = {"named": True, "access": _verdict(rules)}
        else:
            out[bot] = {"named": False, "access": star_verdict}
    return out


def analyze_lastmod(rows: list) -> dict:
    """Read the lastmod column of a sitemap's rows. Reports the share that carry a
    lastmod, whether every one is the same date (a stamped build date rather than
    real content dates), and any that sit in the future."""
    total = len(rows)
    vals = [r["lastmod"] for r in rows if r.get("lastmod")]
    days = sorted({v[:10] for v in vals})
    today = datetime.date.today().isoformat()
    future = sorted({v for v in vals if v[:10] > today})
    return {
        "total": total, "with_lastmod": len(vals),
        "present_share": round(len(vals) / total, 3) if total else 0.0,
        "all_identical": len(days) == 1 and len(vals) > 1,
        "identical_value": days[0] if (len(days) == 1 and len(vals) > 1) else None,
        "in_future": future,
    }


def analyze_hosts(locs: list) -> dict:
    """Mixed scheme or host across the sitemap's URLs (a split that scatters link
    equity and confuses canonicalization)."""
    schemes, hosts = set(), set()
    for u in locs:
        s = urlsplit(u)
        if s.scheme:
            schemes.add(s.scheme.lower())
        if s.netloc:
            hosts.add(s.netloc.lower())
    web = {s for s in schemes if s in ("http", "https")}
    has_www = any(h.startswith("www.") for h in hosts)
    has_apex = any(not h.startswith("www.") for h in hosts)
    return {
        "mixed_http_https": len(web) > 1,
        "schemes": sorted(web),
        "mixed_www_apex": has_www and has_apex,
        "hosts": sorted(hosts),
    }


def _collect_sitemap_rows(root: str, declared, limit: int = 2000, ua: str = UA) -> dict:
    """Fetch the sitemap(s) and return {rows, sitemaps_read, is_index, valid_xml}.
    Follows one level of sitemap-index nesting."""
    queue = list(declared) or [root + "/sitemap.xml"]
    seen, rows, read = set(), [], []
    is_index, valid_any, checked_any = False, False, False
    while queue and len(rows) < limit:
        sm = queue.pop(0)
        if sm in seen:
            continue
        seen.add(sm)
        try:
            r = sitefetch.fetch(sm, ua=ua)
            if r.status_code >= 400:
                continue
        except Exception:  # noqa: BLE001
            continue
        checked_any = True
        entries = sitefetch.parse_sitemap_entries(r.text)
        if entries is None:
            continue
        valid_any = True
        read.append(sm)
        kind, these = entries
        if kind == "sitemapindex":
            is_index = True
            queue.extend(row["loc"] for row in these if row["loc"] not in seen)
        else:
            rows.extend(these)
    return {"rows": rows[:limit], "sitemaps_read": read, "is_index": is_index,
            "valid_xml": valid_any if checked_any else None}


def _url_status_sample(locs, sample: int, deadline: float, ua: str = UA) -> dict:
    """Fetch a sample of sitemap URLs and flag the ones that are non-200, carry a
    noindex robots meta, or name a canonical that points somewhere else."""
    non_200, noindex, canonical_elsewhere, checked = [], [], [], 0
    for u in locs[:sample]:
        if time.monotonic() > deadline:
            break
        checked += 1
        r, soup, err = sitefetch.get_page(u, ua=ua)
        if err:
            non_200.append({"url": u, "status_code": err.get("status_code")})
            continue
        robots_meta = soup.find("meta", attrs={"name": re.compile(r"^robots$", re.I)})
        if robots_meta and "noindex" in (robots_meta.get("content") or "").lower():
            noindex.append(u)
        canon = soup.find("link", rel="canonical")
        href = (canon.get("href") if canon else None) or ""
        if href and _norm_url(urljoin(u, href)) != _norm_url(u):
            canonical_elsewhere.append({"url": u, "canonical": urljoin(u, href)})
    return {"checked": checked, "non_200": non_200, "noindex": noindex,
            "canonical_elsewhere": canonical_elsewhere}


def sitemap_hygiene(url: str, sample: int = 50, time_budget_s: int = 90) -> dict:
    """Check robots.txt and the XML sitemap of a site: reachability, validity,
    lastmod honesty, URLs that should not be in a sitemap, host consistency, and
    what robots.txt tells each AI crawler."""
    root = sitefetch.site_root(url)
    deadline = time.monotonic() + max(10, min(int(time_budget_s), 600))
    robots_reachable, robots_text = False, ""
    try:
        r = sitefetch.fetch(root + "/robots.txt", ua=UA)
        if r.status_code < 400 and r.text.strip():
            robots_reachable, robots_text = True, r.text
    except Exception:  # noqa: BLE001
        pass
    _rules, declared = sitefetch.parse_robots_text(robots_text)

    sm = _collect_sitemap_rows(root, declared, limit=2000, ua=UA)
    rows = sm["rows"]
    locs = [row["loc"] for row in rows]
    status = _url_status_sample(locs, min(int(sample), len(locs)), deadline) if locs else \
        {"checked": 0, "non_200": [], "noindex": [], "canonical_elsewhere": []}

    issues = []
    if not robots_reachable:
        issues.append("robots.txt is not reachable")
    if not declared:
        issues.append("no Sitemap: directive in robots.txt")
    if sm["valid_xml"] is False:
        issues.append("the sitemap did not parse as XML")
    if not rows:
        issues.append("no URLs discovered in the sitemap")
    lastmod = analyze_lastmod(rows)
    if lastmod["all_identical"]:
        issues.append("every lastmod is the same date (%s): a stamped build date, "
                      "not real content dates" % lastmod["identical_value"])
    if lastmod["in_future"]:
        issues.append("%d URL(s) carry a lastmod in the future" % len(lastmod["in_future"]))
    hosts = analyze_hosts(locs)
    if hosts["mixed_http_https"]:
        issues.append("the sitemap mixes http and https URLs")
    if hosts["mixed_www_apex"]:
        issues.append("the sitemap mixes www and apex hosts")
    if status["non_200"]:
        issues.append("%d sampled URL(s) do not return 200" % len(status["non_200"]))
    if status["noindex"]:
        issues.append("%d sampled URL(s) carry a noindex meta but sit in the sitemap"
                      % len(status["noindex"]))
    if status["canonical_elsewhere"]:
        issues.append("%d sampled URL(s) canonicalize to another URL but sit in the sitemap"
                      % len(status["canonical_elsewhere"]))

    return {
        "site": root,
        "robots_txt_reachable": robots_reachable,
        "sitemap_declared": bool(declared),
        "declared_sitemaps": declared,
        "sitemap_valid_xml": sm["valid_xml"],
        "is_sitemap_index": sm["is_index"],
        "sitemaps_read": sm["sitemaps_read"],
        "url_count": len(rows),
        "lastmod": lastmod,
        "hosts": hosts,
        "sampled": status["checked"],
        "non_200": status["non_200"],
        "noindex_in_sitemap": status["noindex"],
        "canonicalized_elsewhere": status["canonical_elsewhere"],
        "ai_crawlers": ai_crawler_rules(robots_text),
        "issues": issues,
    }


# ---- 3. schema_build ------------------------------------------------------

# The most specific schema.org LocalBusiness subtype for a plain-language business
# type. Anything not listed falls back to LocalBusiness.
_LOCALBUSINESS_SUBTYPES = {
    "plumber": "Plumber", "plumbing": "Plumber",
    "electrician": "Electrician", "electrical": "Electrician",
    "dentist": "Dentist", "dental": "Dentist",
    "attorney": "Attorney", "lawyer": "Attorney", "law firm": "Attorney",
    "notary": "Notary",
    "restaurant": "Restaurant", "cafe": "CafeOrCoffeeShop",
    "coffee shop": "CafeOrCoffeeShop", "bakery": "Bakery", "bar": "BarOrPub",
    "brewery": "Brewery", "winery": "Winery", "fast food": "FastFoodRestaurant",
    "ice cream": "IceCreamShop",
    "roofing contractor": "RoofingContractor", "roofer": "RoofingContractor",
    "roofing": "RoofingContractor",
    "hvac": "HVACBusiness", "heating and cooling": "HVACBusiness",
    "general contractor": "GeneralContractor", "contractor": "GeneralContractor",
    "painter": "HousePainter", "house painter": "HousePainter",
    "locksmith": "Locksmith", "moving company": "MovingCompany", "movers": "MovingCompany",
    "auto repair": "AutoRepair", "mechanic": "AutoRepair", "auto body": "AutoBodyShop",
    "car wash": "AutoWash", "gas station": "GasStation", "car dealer": "AutoDealer",
    "accountant": "AccountingService", "accounting": "AccountingService",
    "bookkeeper": "AccountingService", "insurance agency": "InsuranceAgency",
    "bank": "BankOrCreditUnion",
    "real estate agent": "RealEstateAgent", "realtor": "RealEstateAgent",
    "medical clinic": "MedicalClinic", "clinic": "MedicalClinic",
    "doctor": "Physician", "physician": "Physician", "pharmacy": "Pharmacy",
    "veterinarian": "VeterinaryCare", "vet": "VeterinaryCare",
    "optometrist": "Optician", "physical therapy": "PhysicalTherapy",
    "hair salon": "HairSalon", "salon": "HairSalon", "barber": "HairSalon",
    "nail salon": "NailSalon", "beauty salon": "BeautySalon", "day spa": "DaySpa",
    "spa": "DaySpa", "tattoo": "TattooParlor",
    "gym": "ExerciseGym", "fitness": "ExerciseGym", "health club": "HealthClub",
    "yoga studio": "HealthClub",
    "hotel": "Hotel", "motel": "Motel", "bed and breakfast": "BedAndBreakfast",
    "resort": "Resort", "campground": "Campground", "hostel": "Hostel",
    "dry cleaner": "DryCleaningOrLaundry", "laundry": "DryCleaningOrLaundry",
    "child care": "ChildCare", "daycare": "ChildCare",
    "travel agency": "TravelAgency", "self storage": "SelfStorage",
    "storage": "SelfStorage", "employment agency": "EmploymentAgency",
    "landscaper": "HomeAndConstructionBusiness", "landscaping": "HomeAndConstructionBusiness",
    "store": "Store", "retail": "Store", "grocery store": "GroceryStore",
    "florist": "Florist", "jewelry store": "JewelryStore", "pet store": "PetStore",
    "hardware store": "HardwareStore", "bookstore": "BookStore",
    "financial service": "FinancialService", "professional service": "ProfessionalService",
    "emergency service": "EmergencyService",
}


def localbusiness_subtype(business_type: str) -> str:
    """The schema.org type for a business type, falling back to LocalBusiness."""
    key = re.sub(r"\s+", " ", (business_type or "").strip().lower())
    if key in _LOCALBUSINESS_SUBTYPES:
        return _LOCALBUSINESS_SUBTYPES[key]
    for name, typ in _LOCALBUSINESS_SUBTYPES.items():
        if name in key:
            return typ
    return "LocalBusiness"


_DAYS = {
    "monday": "Monday", "tuesday": "Tuesday", "wednesday": "Wednesday",
    "thursday": "Thursday", "friday": "Friday", "saturday": "Saturday",
    "sunday": "Sunday", "mon": "Monday", "tue": "Tuesday", "wed": "Wednesday",
    "thu": "Thursday", "fri": "Friday", "sat": "Saturday", "sun": "Sunday",
}


def _hours_spec(hours) -> list:
    """Turn a {day: 'HH:MM-HH:MM'} map into OpeningHoursSpecification nodes."""
    out = []
    if not isinstance(hours, dict):
        return out
    for day, span in hours.items():
        d = _DAYS.get(str(day).strip().lower())
        if not d or not isinstance(span, str) or "-" not in span:
            continue
        opens, closes = (p.strip() for p in span.split("-", 1))
        out.append({"@type": "OpeningHoursSpecification", "dayOfWeek": d,
                    "opens": opens, "closes": closes})
    return out


def schema_build(business_type: str, name: str, url: str, phone: str | None = None,
                 address: str | None = None, city: str | None = None,
                 region: str | None = None, postal_code: str | None = None,
                 country: str = "US", services=None, faqs=None, same_as=None,
                 hours=None, logo: str | None = None, founder: str | None = None) -> dict:
    """Build a JSON-LD @graph for a local business: the most specific LocalBusiness
    subtype, an Organization and a WebSite, a Service per service, an FAQPage when
    faqs are given, and a Person for the founder. Returns the string ready to paste
    in a <script type="application/ld+json"> tag and the list of types used."""
    subtype = localbusiness_subtype(business_type)
    base = (url or "").rstrip("/")
    biz_id, org_id, site_id = base + "/#business", base + "/#organization", base + "/#website"
    graph = []

    biz = {"@type": subtype, "@id": biz_id, "name": name, "url": base or url}
    if phone:
        biz["telephone"] = phone
    if logo:
        biz["image"] = logo
    addr = {}
    if address:
        addr["streetAddress"] = address
    if city:
        addr["addressLocality"] = city
    if region:
        addr["addressRegion"] = region
    if postal_code:
        addr["postalCode"] = postal_code
    if country:
        addr["addressCountry"] = country
    if addr:
        addr["@type"] = "PostalAddress"
        biz["address"] = addr
    if same_as:
        biz["sameAs"] = list(same_as)
    spec = _hours_spec(hours)
    if spec:
        biz["openingHoursSpecification"] = spec
    graph.append(biz)

    org = {"@type": "Organization", "@id": org_id, "name": name, "url": base or url}
    if logo:
        org["logo"] = logo
    if same_as:
        org["sameAs"] = list(same_as)
    graph.append(org)
    graph.append({"@type": "WebSite", "@id": site_id, "name": name,
                  "url": base or url, "publisher": {"@id": org_id}})

    for i, svc in enumerate(services or [], 1):
        sname = svc if isinstance(svc, str) else (svc or {}).get("name", "")
        if not sname:
            continue
        node = {"@type": "Service", "@id": "%s/#service-%d" % (base, i),
                "name": sname, "provider": {"@id": biz_id}}
        if isinstance(svc, dict) and svc.get("description"):
            node["description"] = svc["description"]
        graph.append(node)

    if faqs:
        entities = []
        for qa in faqs:
            q = qa.get("question") if isinstance(qa, dict) else None
            a = qa.get("answer") if isinstance(qa, dict) else None
            if q and a:
                entities.append({"@type": "Question", "name": q,
                                 "acceptedAnswer": {"@type": "Answer", "text": a}})
        if entities:
            graph.append({"@type": "FAQPage", "@id": base + "/#faq", "mainEntity": entities})

    if founder:
        person_id = base + "/#founder"
        graph.append({"@type": "Person", "@id": person_id, "name": founder,
                      "worksFor": {"@id": org_id}})
        biz["founder"] = {"@id": person_id}

    doc = {"@context": "https://schema.org", "@graph": graph}
    jsonld = json.dumps(doc, indent=2, ensure_ascii=False)
    valid = True
    try:
        json.loads(jsonld)
    except Exception:  # noqa: BLE001
        valid = False
    types = []
    for node in graph:
        t = node["@type"]
        if t not in types:
            types.append(t)
    return {"jsonld": jsonld, "types": types, "node_count": len(graph), "valid_json": valid}


# ---- 4. assistants_index (llms.txt) ---------------------------------------

def _segment_heading(seg: str) -> str:
    if not seg:
        return "Main"
    return seg.replace("-", " ").replace("_", " ").strip().title()


def build_llms_txt(site_name: str, summary: str | None, pages: list, skipped: int = 0) -> dict:
    """Assemble an llms.txt body: an H1 site name, a quoted summary, then one
    section per top path segment with a '- [title](url): description' line per page.
    `pages` is a list of {url, title, description, segment}. Returns text and counts."""
    lines = ["# " + _oneline(site_name), ""]
    if summary:
        lines += ["> " + _oneline(summary), ""]
    groups = OrderedDict()
    for p in pages:
        groups.setdefault(p.get("segment", ""), []).append(p)
    # Root/home section first, then the rest alphabetically.
    order = ([""] if "" in groups else []) + sorted(s for s in groups if s)
    for seg in order:
        lines.append("## " + _segment_heading(seg))
        lines.append("")
        for p in groups[seg]:
            title = _oneline(p.get("title") or p.get("url"))
            head = "- [%s](%s)" % (title, p.get("url"))
            desc = _oneline(p.get("description") or "")
            lines.append(head + (": " + desc if desc else ""))
        lines.append("")
    if skipped:
        lines.append("<!-- %d page(s) were skipped (unreadable or over the limit). -->" % skipped)
        lines.append("")
    text = "\n".join(lines).rstrip() + "\n"
    return {"text": text, "page_count": len(pages), "section_count": len(order),
            "skipped": skipped}


def assistants_index(url: str, max_pages: int = 200, site_name: str | None = None,
                     summary: str | None = None, time_budget_s: int = 120) -> dict:
    """Build an llms.txt body from a site's own pages: read the homepage for the
    name and summary when not given, then read each page (sitemap first, else a
    crawl) for its title and meta description, up to max_pages. Does not write files."""
    root = sitefetch.site_root(url)
    max_pages = max(1, min(int(max_pages), 500))
    deadline = time.monotonic() + max(10, min(int(time_budget_s), 600))

    home_r, home_soup, home_err = sitefetch.get_page(url, ua=UA)
    if not site_name:
        if home_err or home_soup is None:
            site_name = urlsplit(root).netloc.replace("www.", "")
        else:
            t = home_soup.title.get_text(strip=True) if home_soup.title else ""
            site_name = t or urlsplit(root).netloc.replace("www.", "")
    if summary is None and not home_err and home_soup is not None:
        tag = home_soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
        summary = (tag.get("content") or "").strip() if tag else ""

    rules, declared = sitefetch.parse_robots(root, ua=UA)
    sm_urls, _info = sitefetch.sitemap_urls(root, declared, limit=max_pages, ua=UA)
    if sm_urls:
        mode, queue = "sitemap", list(sm_urls)
    else:
        mode, queue = "crawl", [sitefetch.normalize_url(url)]

    pages, seen, skipped = [], set(), 0
    while queue and len(pages) < max_pages:
        if time.monotonic() > deadline:
            skipped += len(queue)
            break
        u = queue.pop(0)
        n = _norm_url(u)
        if n in seen:
            continue
        seen.add(n)
        if not sitefetch.same_site(u, root):
            continue
        r, soup, err = sitefetch.get_page(u, ua=UA)
        if err or soup is None:
            skipped += 1
            continue
        title = soup.title.get_text(strip=True) if soup.title else ""
        tag = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
        desc = (tag.get("content") or "").strip() if tag else ""
        pages.append({"url": str(r.url), "title": title, "description": desc,
                      "segment": _top_segment(str(r.url))})
        if mode == "crawl":
            for a in soup.find_all("a", href=True):
                nxt = urljoin(u, a["href"].split("#", 1)[0])
                if nxt.lower().startswith("http") and sitefetch.same_site(nxt, root) \
                        and _norm_url(nxt) not in seen:
                    queue.append(nxt)

    built = build_llms_txt(site_name, summary, pages, skipped)
    built["site"] = root
    built["seed_mode"] = mode
    return built


# ---- 5. cover_image -------------------------------------------------------

# The preview crop. LinkedIn, Facebook and X crop a shared image to about 1.91:1;
# text outside that centered rectangle can be clipped. The safe zone is that crop
# inset by a further margin, so nothing sits right on the cut line.
SAFE_RATIO = 1.91
SAFE_MARGIN_FRAC = 0.06


def safe_zone(width: int, height: int, ratio: float = SAFE_RATIO,
              margin: float = SAFE_MARGIN_FRAC) -> tuple:
    """The (left, top, right, bottom) box that survives a centered ratio:1 crop,
    inset by `margin` of the crop on every side."""
    if width / height > ratio:
        crop_w, crop_h = height * ratio, float(height)
    else:
        crop_w, crop_h = float(width), width / ratio
    cx, cy = width / 2.0, height / 2.0
    mx, my = crop_w * margin, crop_h * margin
    return (cx - crop_w / 2 + mx, cy - crop_h / 2 + my,
            cx + crop_w / 2 - mx, cy + crop_h / 2 - my)


def _load_font(font_path, size):
    from PIL import ImageFont
    candidates = []
    if font_path:
        candidates.append(font_path)
    candidates += ["arialbd.ttf", "Arialbd.ttf", "arial.ttf",
                   "C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/arial.ttf",
                   "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"]
    for c in candidates:
        try:
            return ImageFont.truetype(c, size)
        except Exception:  # noqa: BLE001
            continue
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def _wrap(draw, text, font, max_width) -> list:
    """Greedy word wrap to lines no wider than max_width."""
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_width or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def _slugify(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s[:60] or "cover"


def cover_image(title: str, subtitle: str | None = None, out_path: str | None = None,
                width: int = 1200, height: int = 630, bg: str = "#0B1F3A",
                fg: str = "#FFFFFF", accent: str = "#C9A227",
                logo_path: str | None = None, font_path: str | None = None) -> dict:
    """Render a clean share-preview card: the title wrapped and sized to fit the
    safe zone, an optional subtitle, an accent rule, and an optional logo kept to
    its aspect ratio. Asserts every text box sits inside the crop safe zone. Saves
    a PNG and returns its path, size and the safe-zone check."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(img)
    left, top, right, bottom = safe_zone(width, height)
    zone_w, zone_h = right - left, bottom - top
    boxes = []  # (x0, y0, x1, y1) of every text box drawn

    # Logo top-left of the safe zone, aspect kept, never redrawn.
    logo_bottom = top
    if logo_path and os.path.exists(logo_path):
        try:
            logo = Image.open(logo_path).convert("RGBA")
            target_h = int(zone_h * 0.14)
            ratio = target_h / logo.height
            logo = logo.resize((max(1, int(logo.width * ratio)), target_h), Image.LANCZOS)
            img.paste(logo, (int(left), int(top)), logo)
            logo_bottom = top + target_h + zone_h * 0.04
        except Exception:  # noqa: BLE001
            logo_bottom = top

    # Title: shrink until the wrapped block fits the safe zone width and height.
    size = int(zone_h * 0.30)
    title = _oneline(title)
    while size > 10:
        font = _load_font(font_path, size)
        lines = _wrap(draw, title, font, zone_w)
        line_h = (draw.textbbox((0, 0), "Ag", font=font)[3]
                  - draw.textbbox((0, 0), "Ag", font=font)[1])
        gap = int(line_h * 0.2)
        block_h = len(lines) * line_h + (len(lines) - 1) * gap
        widest = max((draw.textlength(ln, font=font) for ln in lines), default=0)
        reserve = zone_h * 0.22 if subtitle else zone_h * 0.08
        if widest <= zone_w and block_h <= (bottom - logo_bottom) - reserve:
            break
        size -= 2
    font = _load_font(font_path, size)
    lines = _wrap(draw, title, font, zone_w)
    line_h = (draw.textbbox((0, 0), "Ag", font=font)[3]
              - draw.textbbox((0, 0), "Ag", font=font)[1])
    gap = int(line_h * 0.2)
    block_h = len(lines) * line_h + (len(lines) - 1) * gap
    y = top + ((bottom - top) - block_h) / 2 - (zone_h * 0.05 if subtitle else 0)
    if y < logo_bottom:
        y = logo_bottom
    for ln in lines:
        w = draw.textlength(ln, font=font)
        x = left + (zone_w - w) / 2
        draw.text((x, y), ln, font=font, fill=fg)
        boxes.append((x, y, x + w, y + line_h))
        y += line_h + gap

    # Accent rule under the title.
    rule_y = y + gap
    rule_w = zone_w * 0.18
    rule_x0 = left + (zone_w - rule_w) / 2
    if rule_y < bottom:
        draw.line([(rule_x0, rule_y), (rule_x0 + rule_w, rule_y)], fill=accent, width=4)

    # Subtitle under the rule.
    if subtitle:
        sub_size = max(12, int(size * 0.42))
        sub_font = _load_font(font_path, sub_size)
        sub = _oneline(subtitle)
        sub_lines = _wrap(draw, sub, sub_font, zone_w)
        sub_h = (draw.textbbox((0, 0), "Ag", font=sub_font)[3]
                 - draw.textbbox((0, 0), "Ag", font=sub_font)[1])
        sy = rule_y + sub_h
        for ln in sub_lines:
            w = draw.textlength(ln, font=sub_font)
            x = left + (zone_w - w) / 2
            if sy + sub_h > bottom:
                break
            draw.text((x, sy), ln, font=sub_font, fill=fg)
            boxes.append((x, sy, x + w, sy + sub_h))
            sy += int(sub_h * 1.3)

    inside = all(b[0] >= left - 0.5 and b[1] >= top - 0.5
                 and b[2] <= right + 0.5 and b[3] <= bottom + 0.5 for b in boxes)

    if out_path is None:
        covers = os.path.join(os.path.dirname(os.path.abspath(__file__)), "covers")
        os.makedirs(covers, exist_ok=True)
        out_path = os.path.join(covers, _slugify(title) + ".png")
    else:
        parent = os.path.dirname(os.path.abspath(out_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
    img.save(out_path, "PNG")
    return {"path": out_path, "size": [width, height], "title_font_size": size,
            "safe_zone": [round(v, 1) for v in (left, top, right, bottom)],
            "text_boxes": len(boxes), "safe_zone_ok": inside}


# ---- 6. strip_metadata ----------------------------------------------------

_OFFICE_EXT = {".docx", ".xlsx", ".pptx", ".dotx", ".xltx", ".potx"}
_CORE_BLANK = {"dc:creator": "", "cp:lastModifiedBy": "", "cp:revision": "1",
               "dcterms:created": "2000-01-01T00:00:00Z",
               "dcterms:modified": "2000-01-01T00:00:00Z"}
_APP_BLANK = {"Application": "", "Company": "", "Manager": "",
              "Template": "", "HyperlinkBase": ""}


def _default_out(path: str) -> str:
    stem, ext = os.path.splitext(path)
    return stem + ".clean" + ext


def _set_element(xml: str, tag: str, value: str):
    """Replace the inner text of <tag>...</tag> with `value`. Returns (xml, old)
    or (xml, None) when the tag is absent."""
    pat = re.compile(r"(<%s(?:\s[^>]*)?>)(.*?)(</%s>)" % (re.escape(tag), re.escape(tag)), re.S)
    m = pat.search(xml)
    if not m:
        return xml, None
    old = m.group(2)
    return xml[:m.start()] + m.group(1) + value + m.group(3) + xml[m.end():], old


def _scrub_office(path: str, out_path: str) -> dict:
    import shutil
    import zipfile
    removed = {}
    tmp = out_path + ".tmp"
    with zipfile.ZipFile(path, "r") as zin:
        names = zin.namelist()
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)
                if item.filename == "docProps/core.xml":
                    text = data.decode("utf-8", "replace")
                    for tag, val in _CORE_BLANK.items():
                        text, old = _set_element(text, tag, val)
                        if old is not None and old != val:
                            removed.setdefault("core.xml", {})[tag] = old
                    data = text.encode("utf-8")
                elif item.filename == "docProps/app.xml":
                    text = data.decode("utf-8", "replace")
                    for tag, val in _APP_BLANK.items():
                        text, old = _set_element(text, tag, val)
                        if old is not None and old != val:
                            removed.setdefault("app.xml", {})[tag] = old
                    # TitlesOfParts / template names left structurally intact.
                    data = text.encode("utf-8")
                zout.writestr(item, data)
    if os.path.abspath(out_path) == os.path.abspath(path):
        shutil.move(tmp, out_path)
    else:
        if os.path.exists(out_path):
            os.remove(out_path)
        shutil.move(tmp, out_path)
    return {"format": "office", "out_path": out_path, "removed": removed}


_PNG_SIG = b"\x89PNG\r\n\x1a\n"
_PNG_DROP = {b"tEXt", b"iTXt", b"zTXt", b"eXIf", b"caBX"}


def _scrub_png(path: str, out_path: str) -> dict:
    with open(path, "rb") as f:
        data = f.read()
    if data[:8] != _PNG_SIG:
        raise ValueError("not a PNG file")
    out = bytearray(_PNG_SIG)
    removed = []
    i = 8
    while i + 8 <= len(data):
        length = struct.unpack(">I", data[i:i + 4])[0]
        ctype = data[i + 4:i + 8]
        chunk_data = data[i + 8:i + 8 + length]
        drop = ctype in _PNG_DROP or b"c2pa" in chunk_data.lower() or b"jumb" in chunk_data.lower()
        if drop:
            removed.append(ctype.decode("latin-1"))
        else:
            out += data[i:i + 4] + ctype + chunk_data
            out += struct.pack(">I", zlib.crc32(ctype + chunk_data) & 0xffffffff)
        i += 12 + length
        if ctype == b"IEND":
            break
    with open(out_path, "wb") as f:
        f.write(out)
    return {"format": "png", "out_path": out_path, "removed": removed}


_JPEG_DROP = {0xE1: "APP1 (EXIF/XMP)", 0xEB: "APP11 (JUMBF/C2PA)", 0xED: "APP13 (IPTC)"}


def _scrub_jpeg(path: str, out_path: str) -> dict:
    with open(path, "rb") as f:
        data = f.read()
    if data[:2] != b"\xff\xd8":
        raise ValueError("not a JPEG file")
    out = bytearray(b"\xff\xd8")
    removed = []
    i = 2
    n = len(data)
    while i + 1 < n:
        if data[i] != 0xFF:
            out += data[i:]
            break
        marker = data[i + 1]
        if marker == 0xDA:  # start of scan: copy the rest verbatim
            out += data[i:]
            break
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7 or marker == 0x01:
            out += data[i:i + 2]
            i += 2
            continue
        if i + 4 > n:
            out += data[i:]
            break
        seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
        seg = data[i:i + 2 + seg_len]
        if marker in _JPEG_DROP:
            removed.append(_JPEG_DROP[marker])
        else:
            out += seg
        i += 2 + seg_len
    with open(out_path, "wb") as f:
        f.write(out)
    return {"format": "jpeg", "out_path": out_path, "removed": removed}


def strip_metadata(path: str, out_path: str | None = None) -> dict:
    """Remove authoring metadata and provenance from a file. For Office files
    (.docx/.xlsx/.pptx) rewrite docProps/core.xml and app.xml and leave every other
    part untouched; for PNG drop text and EXIF chunks and any C2PA/JUMBF chunk; for
    JPEG drop the APP1, APP11 and APP13 segments. Never overwrites in place unless
    out_path is set equal to path."""
    ext = os.path.splitext(path)[1].lower()
    if out_path is None:
        out_path = _default_out(path)
    try:
        if ext in _OFFICE_EXT:
            return _scrub_office(path, out_path)
        if ext == ".png":
            return _scrub_png(path, out_path)
        if ext in (".jpg", ".jpeg"):
            return _scrub_jpeg(path, out_path)
    except Exception as e:  # noqa: BLE001
        return {"error": "could not strip metadata: " + str(e)[:200], "path": path}
    return {"error": "unsupported file type: %s (handles .docx/.xlsx/.pptx, .png, .jpg)" % ext,
            "path": path}
