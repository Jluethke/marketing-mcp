# Copyright (c) 2026 The Wayfinder Trust - Jonathan Luethke
# All Rights Reserved. Proprietary and Confidential.
"""Prospecting: find local businesses, grade one truthful finding per site, and
turn a list into call rows.

Four readings, all without credentials:

  find_businesses   every independent business with (optionally) a website in a
                    named place, from OpenStreetMap through the Overpass API
  prospect_finding  one site reduced to its single strongest honest finding,
                    graded, with the evidence it rests on, or "no finding"
  call_sheet        a prospect list turned into one neutral opener per business,
                    split into callable, no-phone, unreadable and clean sections
  agency_score      a marketing or web agency's site scored as a reseller partner

The honesty rules carried from the campaign this was built for:

  - One finding per prospect, graded. The strongest one, not a pile.
  - A clean site yields grade C and the words "no finding". No defect is invented
    to have something to say.
  - A finding never rests on nothing. Every finding carries the exact element or
    measure it was read from.
  - A site that turns the reader away (a bot wall) or is down is listed as
    unreadable, never guessed at, because scoring a block page describes the wall
    rather than the business.

Sources are public and keyless. Place names resolve through Nominatim; businesses
come from Overpass (OpenStreetMap). Commercial business directories refuse
automated reads, which is why the source is OpenStreetMap rather than a
directory. Both OSM services are used within their usage policy: the shared
identifying User-Agent from sitefetch, one request at a time, with sensible
timeouts and a short pause between calls.
"""
from __future__ import annotations

import csv
import io
import time
from urllib.parse import urlparse

import sitefetch

NOMINATIM = "https://nominatim.openstreetmap.org/search"
OVERPASS_MIRRORS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
)
UA = sitefetch.UA

ATTRIBUTION = ("Business data from OpenStreetMap contributors, available under "
               "the Open Database License (ODbL).")
DIRECTORY_NOTE = ("Commercial business directories refuse automated reads, so "
                  "OpenStreetMap is the source here.")

# The five category tags a business is read from, in the order a row's category
# is taken from.
CATEGORY_KEYS = ("shop", "craft", "office", "amenity", "healthcare")

# Tag values that are not a business anyone sells marketing to.
_DROP_AMENITY = {
    "place_of_worship", "school", "kindergarten", "college", "university",
    "library", "townhall", "courthouse", "police", "fire_station", "prison",
    "post_office", "post_box", "parking", "parking_space", "parking_entrance",
    "atm", "bench", "waste_basket", "recycling", "toilets", "shelter",
    "drinking_water", "fountain", "bicycle_parking", "charging_station",
    "grave_yard", "community_centre", "social_facility", "hospital",
    "bus_station", "ferry_terminal", "public_bookcase", "clock",
}
_DROP_OFFICE = {"government", "diplomatic", "political_party", "quango",
                "administrative", "employment_agency", "ngo", "charity"}
_DROP_ANY_KEY = ("historic", "railway", "aeroway", "military", "power",
                 "man_made", "natural", "barrier", "highway")
# Land and open space are mapped like businesses in OSM and are not one.
_DROP_LEISURE = {"nature_reserve", "park", "playground", "pitch", "garden",
                 "common", "dog_park", "picnic_table", "slipway", "track",
                 "swimming_area", "beach_resort", "marina", "recreation_ground"}
_DROP_LANDUSE = {"residential", "forest", "farmland", "meadow", "cemetery",
                 "grass", "recreation_ground", "military", "conservation"}
_DROP_TOURISM = {"attraction", "artwork", "viewpoint", "picnic_site",
                 "information", "camp_pitch"}

# Social profiles and marketplaces are not a site we can audit or fix.
_NOT_A_SITE = ("facebook.com", "instagram.com", "twitter.com", "x.com",
               "linkedin.com", "yelp.com", "tripadvisor.", "doordash.com",
               "grubhub.com", "ubereats.com", "toasttab.com", "square.site",
               "linktr.ee", "google.com", "wixsite.com/blank")

# A page over this many bytes of HTML ships a lot of code before any image loads.
HTML_HEAVY_BYTES = 500 * 1024
# A homepage slower than this to respond loses mobile visitors.
SLOW_RESPONSE_MS = 2500


# ==== FIND BUSINESSES ======================================================

def _category_of(tags: dict):
    for k in CATEGORY_KEYS:
        if tags.get(k):
            return "%s=%s" % (k, tags[k])
    return None


def _is_business(tags: dict) -> bool:
    if any(tags.get(k) for k in _DROP_ANY_KEY):
        return False
    if tags.get("amenity") in _DROP_AMENITY:
        return False
    if tags.get("office") in _DROP_OFFICE:
        return False
    if tags.get("operator:type") in ("government", "public"):
        return False
    if tags.get("leisure") in _DROP_LEISURE:
        return False
    if tags.get("landuse") in _DROP_LANDUSE:
        return False
    if tags.get("tourism") in _DROP_TOURISM:
        return False
    return _category_of(tags) is not None


def _is_chain(tags: dict) -> bool:
    """A brand tag is OSM's own marker that this is a franchise or chain."""
    return bool(tags.get("brand") or tags.get("brand:wikidata")
                or tags.get("operator:wikidata"))


def _clean_site(url):
    if not url:
        return None
    url = str(url).strip().split()[0].split(";")[0]
    if not url:
        return None
    if not url.startswith(("http://", "https://")):
        url = "https://" + url.lstrip("/")
    host = urlparse(url).netloc
    if not host or "." not in host:
        return None
    low = url.lower()
    for bad in _NOT_A_SITE:
        if bad in low:
            return None
    return url


def _address_of(tags: dict) -> str:
    line = " ".join(p for p in (tags.get("addr:housenumber"), tags.get("addr:street"))
                    if p)
    rest = ", ".join(p for p in (tags.get("addr:city"), tags.get("addr:state"),
                                 tags.get("addr:postcode")) if p)
    parts = [p for p in (line, rest) if p]
    return ", ".join(parts)


def _matches_category(tags: dict, name: str, category) -> bool:
    """A category filter matches when the wanted word is in a category tag value
    or in the business name, so 'bakery' finds shop=bakery and 'Mia's Bakery'."""
    if not category:
        return True
    want = str(category).strip().lower()
    if not want:
        return True
    if want in (name or "").lower():
        return True
    for k in CATEGORY_KEYS:
        v = tags.get(k)
        if v and want in str(v).lower():
            return True
    return False


def _build_rows(elements, category=None, include_chains=False,
                require_website=True, limit=200) -> dict:
    """Turn raw Overpass elements into prospect rows plus counts. Pure: no
    network, so the parsing and chain dropping are tested offline."""
    rows, seen = [], set()
    found = with_website = with_phone = 0
    for el in elements or []:
        tags = el.get("tags", {}) or {}
        name = (tags.get("name") or "").strip()
        if not name:
            continue
        if not _is_business(tags):
            continue
        if not include_chains and _is_chain(tags):
            continue
        if not _matches_category(tags, name, category):
            continue
        site = _clean_site(tags.get("website") or tags.get("contact:website"))
        phone = (tags.get("phone") or tags.get("contact:phone") or "").strip() or None
        key = (name.lower(), (site or "").lower())
        if key in seen:
            continue
        seen.add(key)
        found += 1
        if site:
            with_website += 1
        if phone:
            with_phone += 1
        if require_website and not site:
            continue
        rows.append({
            "name": name,
            "category": _category_of(tags),
            "website": site,
            "phone": phone,
            "address": _address_of(tags),
            "osm": "%s/%s" % (el.get("type"), el.get("id")),
        })
    if limit and limit > 0:
        rows = rows[:limit]
    return {"rows": rows, "found": found, "with_website": with_website,
            "with_phone": with_phone}


def _resolve_area(area: str) -> dict:
    """Resolve a place name to an OSM area through Nominatim. Returns the Overpass
    area id when the place is a relation or way, else a bounding box."""
    import httpx
    r = httpx.get(NOMINATIM,
                  params={"q": area, "format": "json", "limit": 1},
                  headers={"User-Agent": UA}, timeout=30.0)
    r.raise_for_status()
    hits = r.json()
    if not hits:
        raise RuntimeError("could not find a place called %r" % area)
    hit = hits[0]
    osm_type = (hit.get("osm_type") or "").lower()
    osm_id = int(hit.get("osm_id") or 0)
    out = {"display_name": hit.get("display_name", area)}
    if osm_type == "relation":
        out["area_id"] = 3600000000 + osm_id
    elif osm_type == "way":
        out["area_id"] = 2400000000 + osm_id
    else:
        bb = hit.get("boundingbox")  # [south, north, west, east]
        if not bb:
            raise RuntimeError("no area or bounding box returned for %r" % area)
        out["bbox"] = (float(bb[0]), float(bb[2]), float(bb[1]), float(bb[3]))
    return out


def _overpass_query(area: dict, timeout: int = 60) -> str:
    """Build the Overpass query for the five category keys over an area or box."""
    if "area_id" in area:
        scope = "area(%d)->.a;" % area["area_id"]
        suffix = "(area.a)"
    else:
        s, w, n, e = area["bbox"]
        scope = ""
        suffix = "(%.5f,%.5f,%.5f,%.5f)" % (s, w, n, e)
    body = "".join('nwr["%s"]["name"]%s;' % (k, suffix) for k in CATEGORY_KEYS)
    return "[out:json][timeout:%d];%s(%s);out center tags;" % (timeout, scope, body)


def _overpass(query: str, timeout: int = 60) -> list:
    """Run one Overpass query against the first mirror that answers, one request
    at a time per the public endpoint's usage policy."""
    import httpx
    last = None
    for mirror in OVERPASS_MIRRORS:
        try:
            r = httpx.post(mirror, content=query.encode("utf-8"),
                           headers={"User-Agent": UA}, timeout=timeout + 30)
            if r.status_code == 200:
                return r.json().get("elements", [])
            last = "%s -> HTTP %d" % (mirror, r.status_code)
        except Exception as e:  # noqa: BLE001
            last = "%s -> %s" % (mirror, str(e)[:80])
        time.sleep(2.0)
    raise RuntimeError("Overpass did not answer (%s)" % last)


def find_businesses(area: str, category: str | None = None, limit: int = 200,
                    require_website: bool = True, include_chains: bool = False) -> dict:
    """Find independent local businesses in a named area from OpenStreetMap.

    `area` is a place name such as "Bergen County, New Jersey" or "Austin, TX".
    It is resolved to an OSM area through Nominatim, then the area is queried on
    Overpass for the shop, craft, office, amenity and healthcare tags. National
    chains and franchises are dropped by their OSM brand tags unless
    include_chains is True; non-commercial places (government, schools, parks,
    land) are never returned. `category` filters by a category tag value or a
    name substring ("bakery", "dentist", "law"). require_website keeps only
    businesses that list a website (the ones with a site to audit).

    Sources are keyless and used within policy: Nominatim and Overpass are each
    called one request at a time with the shared identifying User-Agent and a
    pause between them. Commercial directories refuse automated reads, which is
    why OpenStreetMap is the source.

    Returns: area, category, found, with_website, with_phone, count, businesses,
    attribution, note.
    """
    try:
        resolved = _resolve_area(area)
    except Exception as e:  # noqa: BLE001
        return {"error": "could not resolve the area: " + str(e)[:200],
                "area": area, "note": DIRECTORY_NOTE}
    time.sleep(1.0)  # Nominatim asks for no more than one call a second
    try:
        elements = _overpass(_overpass_query(resolved))
    except Exception as e:  # noqa: BLE001
        return {"error": "Overpass query failed: " + str(e)[:200],
                "area": resolved.get("display_name", area), "note": DIRECTORY_NOTE}
    built = _build_rows(elements, category=category, include_chains=include_chains,
                        require_website=require_website, limit=limit)
    return {
        "area": resolved.get("display_name", area),
        "category": category,
        "found": built["found"],
        "with_website": built["with_website"],
        "with_phone": built["with_phone"],
        "count": len(built["rows"]),
        "businesses": built["rows"],
        "attribution": ATTRIBUTION,
        "note": DIRECTORY_NOTE,
    }


# ==== PROSPECT FINDING =====================================================
# One site, one finding. Checks are evaluated in a fixed priority that puts
# ranking factors first. The first check that fails is the finding: grade A when
# it is a ranking-factor defect a searcher would feel, grade B when it is a real
# but lesser defect. When nothing fails the grade is C and there is no finding.

def _meta_content(soup, name: str) -> str:
    t = soup.find("meta", attrs={"name": name})
    return (t.get("content") or "").strip() if t and t.get("content") else ""


def _extract_signals(soup, html: str, final_url: str, https: bool,
                     response_ms, keyword: str | None = None) -> dict:
    """Reduce a parsed page to the signals the grader reads. Pure, so grading is
    tested on built-in HTML."""
    title = soup.title.get_text(strip=True) if soup.title else ""
    desc = _meta_content(soup, "description")
    h1 = soup.find_all("h1")
    viewport = bool(_meta_content(soup, "viewport"))
    text = soup.get_text(" ", strip=True)
    words = len(text.split())
    schema = soup.find_all("script", attrs={"type": "application/ld+json"})
    imgs = soup.find_all("img")
    no_dims = sum(1 for i in imgs if not (i.get("width") and i.get("height")))

    rb = 0
    head = soup.head
    if head:
        for sc in head.find_all("script"):
            if sc.get("src") and not (sc.has_attr("async") or sc.has_attr("defer")
                                      or (sc.get("type") or "").lower() == "module"):
                rb += 1
        for ln in head.find_all("link"):
            rel = [x.lower() for x in (ln.get("rel") or [])]
            if "stylesheet" in rel:
                rb += 1

    kw = (keyword or "").strip().lower()
    keyword_present = bool(kw) and (kw in text.lower() or kw in title.lower())

    tel = soup.find("a", href=lambda h: bool(h) and h.strip().lower().startswith("tel:"))
    form = soup.find("form")
    addr = soup.find("address")
    has_contact = bool(tel or form or addr)

    return {
        "final_url": final_url, "https": https, "response_ms": response_ms,
        "title": title, "title_length": len(title),
        "meta_description": desc, "h1_count": len(h1), "viewport": viewport,
        "words": words, "schema_blocks": len(schema),
        "images": len(imgs), "images_no_dims": no_dims, "render_blocking": rb,
        "html_bytes": len(html or ""),
        "keyword": keyword, "keyword_present": keyword_present,
        "has_contact": has_contact,
    }


def _find_candidates(s: dict, keyword: str | None) -> list:
    """All findings that apply, ranking factors first, strongest first within
    each group. The first entry is the finding returned."""
    c = []

    def add(key, ranking, cond, phrase, evidence):
        if cond:
            c.append({"key": key, "ranking_factor": ranking,
                      "finding": phrase, "evidence": evidence})

    # Ranking-factor defects a searcher would feel (grade A).
    add("no_https", True, not s["https"], "no HTTPS on the site",
        "the final URL %s is served over http, not https" % s["final_url"])
    add("no_title", True, not s["title"], "no page title",
        "the page has no <title> element")
    add("no_viewport", True, not s["viewport"], "no mobile viewport",
        "no <meta name=\"viewport\"> tag, so the page renders desktop width on a phone")
    add("thin", True, 0 < s["words"] < 150, "very little text on the page",
        "%d words of text on the page" % s["words"])
    add("slow", True,
        isinstance(s["response_ms"], (int, float)) and s["response_ms"] >= SLOW_RESPONSE_MS,
        "a slow homepage",
        "the page took %d ms to respond" % int(s["response_ms"] or 0))
    add("heavy_page", True, s["html_bytes"] > HTML_HEAVY_BYTES, "a heavy page",
        "%d KB of HTML before any image loads" % (s["html_bytes"] // 1024))
    add("render_blocking", True, s["render_blocking"] >= 8,
        "render-blocking resources in the head",
        "%d render-blocking scripts and stylesheets in the page head" % s["render_blocking"])
    add("cls_images", True, s["images_no_dims"] >= 5, "images with no set size",
        "%d of %d images have no width and height, so the layout shifts as it loads"
        % (s["images_no_dims"], s["images"]))

    # Real but lesser defects (grade B).
    if keyword:
        add("keyword_missing", False, not s["keyword_present"],
            "no mention of \"%s\"" % keyword,
            "the term \"%s\" does not appear on the page" % keyword)
    add("no_meta_desc", False, not s["meta_description"], "no meta description",
        "no <meta name=\"description\"> on the page")
    add("title_long", False, s["title_length"] > 70, "an overlong page title",
        "the <title> is %d characters, past the roughly 60 that show in search results"
        % s["title_length"])
    add("no_h1", False, s["h1_count"] == 0, "no main heading",
        "no <h1> element on the page")
    add("no_schema", False, s["schema_blocks"] == 0, "no structured data",
        "no JSON-LD structured data on the page")
    add("no_contact", False, not s["has_contact"], "no visible way to get in touch",
        "no phone (tel:) link, contact form, or address on the page")
    return c


def _select_finding(s: dict, keyword: str | None = None) -> dict:
    """Pick the single strongest finding, or report a clean page as grade C."""
    cands = _find_candidates(s, keyword)
    if not cands:
        return {"finding": "no finding", "grade": "C", "evidence": None,
                "ranking_factor": False, "key": None, "clean": True,
                "all_findings": []}
    top = cands[0]
    return {"finding": top["finding"],
            "grade": "A" if top["ranking_factor"] else "B",
            "evidence": top["evidence"], "ranking_factor": top["ranking_factor"],
            "key": top["key"], "clean": False, "all_findings": cands}


def _assess(r, soup, error, url: str, keyword: str | None = None) -> dict:
    """Build the finding dict from a fetched page, or pass through the reason a
    page could not be read. Pure given the fetch result, so a wall response is
    tested without the network."""
    if error:
        out = dict(error)
        out.setdefault("readable", False)
        out["url"] = out.get("url") or url
        out["finding"] = None
        out["grade"] = None
        return out
    final_url = str(getattr(r, "url", "") or url)
    https = urlparse(final_url).scheme == "https"
    response_ms = None
    try:
        response_ms = r.elapsed.total_seconds() * 1000.0
    except Exception:  # noqa: BLE001
        pass
    html = getattr(r, "text", "") or ""
    s = _extract_signals(soup, html, final_url, https, response_ms, keyword)
    sel = _select_finding(s, keyword)
    return {
        "url": url, "final_url": final_url, "readable": True,
        "status_code": getattr(r, "status_code", None),
        "https": https,
        "finding": sel["finding"], "grade": sel["grade"],
        "evidence": sel["evidence"], "ranking_factor": sel["ranking_factor"],
        "clean": sel["clean"], "all_findings": sel["all_findings"],
        "measured": {k: s[k] for k in ("title_length", "words", "render_blocking",
                                       "images", "images_no_dims", "html_bytes",
                                       "response_ms", "schema_blocks")},
    }


def prospect_finding(url: str, keyword: str | None = None) -> dict:
    """Read one business site and return its single strongest honest finding.

    The page is fetched once with the shared fetch layer, which turns a bot wall,
    a 404 or a 5xx into readable False with the reason rather than a finding. On a
    readable page the keyless checks run: title, meta description and H1 presence
    and quality; HTTPS; mobile viewport; the keyword on the page when one is
    given; the speed measures that need no key (response time, HTML weight,
    render-blocking head resources, images missing dimensions); structured data;
    and contact visibility (a tel link, a form, an address). The strongest finding
    is chosen by a fixed priority that puts ranking factors first, graded A (a
    ranking-factor defect), B (a lesser defect) or C (clean, no finding), and
    returned with the exact element or measure it rests on.

    Returns, on a readable page: url, final_url, readable, status_code, https,
    finding, grade, evidence, ranking_factor, clean, all_findings, measured. On
    an unreadable one: readable False with error and status_code.
    """
    r, soup, error = sitefetch.get_page(url)
    return _assess(r, soup, error, url, keyword)


# ==== CALL SHEET ===========================================================

def _opener(site: str, finding, grade, offer: str) -> str:
    """A neutral two-sentence opener built only from the finding and the offer. A
    clean site (grade C) gets an opener that claims no defect."""
    offer = (offer or "").strip()
    if grade == "C" or not finding or finding == "no finding":
        first = "I looked at %s and it is in good shape." % site
    else:
        first = "I looked at %s and noticed %s." % (site, finding)
    return (first + " " + offer).strip()


def _already_assessed(p: dict):
    """The finding a prospect already carries, if any: a readable-False result or
    a graded finding. Returns the dict to use, or None to audit it."""
    if p.get("readable") is False or p.get("blocked") or p.get("error"):
        return p
    if p.get("grade") in ("A", "B", "C"):
        return p
    return None


def _csv_string(rows: list) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["business", "phone", "website", "grade", "finding", "evidence", "opener"])
    for r in rows:
        w.writerow([r.get("business", ""), r.get("phone") or "", r.get("website") or "",
                    r.get("grade") or "", r.get("finding") or "",
                    r.get("evidence") or "", r.get("opener") or ""])
    return buf.getvalue()


def call_sheet(prospects: list, your_offer: str, your_name: str = "",
               format: str = "rows", max_audits: int = 25,
               time_budget_s: int = 120) -> dict:
    """Turn a prospect list into one call row per business.

    `prospects` is a list of dicts, typically the rows from find_businesses,
    optionally already carrying a prospect_finding result. A prospect that has a
    website and no finding yet is audited with prospect_finding, one at a time, up
    to max_audits sites and within a time budget. Each row carries the business,
    phone, website, grade, finding, evidence and a neutral two-sentence opener
    built only from the finding and `your_offer` (a clean site's opener claims no
    defect). Rows are split into callable (a finding and a phone), no_phone (a
    finding, no phone), unreadable (a wall or a dead site, never guessed) and
    clean (grade C). voice_agent repeats the callable rows for a voice dialer, and
    format="csv" adds a CSV string of every row.

    Returns: callable, no_phone, unreadable, clean, voice_agent, counts, and csv
    when format is "csv" (plus not_audited when the audit cap was reached).
    """
    deadline = time.monotonic() + max(10, int(time_budget_s))
    audits = 0
    callable_rows, no_phone, unreadable, clean, voice = [], [], [], [], []
    all_rows, not_audited = [], []

    for p in prospects or []:
        site = p.get("website") or p.get("url") or ""
        phone = p.get("phone")
        business = p.get("name") or p.get("business") or site
        fr = _already_assessed(p)
        if fr is None and site and audits < max_audits and time.monotonic() < deadline:
            fr = prospect_finding(site)
            audits += 1
        if fr is None:
            not_audited.append({"business": business, "phone": phone, "website": site})
            continue

        if fr.get("readable") is False:
            row = {"business": business, "phone": phone, "website": site,
                   "grade": None, "finding": None,
                   "evidence": fr.get("error"), "opener": "",
                   "caller": your_name}
            unreadable.append(row)
            all_rows.append(row)
            continue

        grade = fr.get("grade")
        finding = fr.get("finding")
        row = {"business": business, "phone": phone, "website": site,
               "grade": grade, "finding": finding, "evidence": fr.get("evidence"),
               "opener": _opener(site, finding, grade, your_offer),
               "caller": your_name}
        all_rows.append(row)
        if grade == "C":
            clean.append(row)
        elif phone:
            callable_rows.append(row)
            voice.append(row)
        else:
            no_phone.append(row)

    result = {
        "callable": callable_rows, "no_phone": no_phone,
        "unreadable": unreadable, "clean": clean,
        "voice_agent": voice,
        "counts": {"prospects": len(prospects or []), "audited": audits,
                   "callable": len(callable_rows), "no_phone": len(no_phone),
                   "unreadable": len(unreadable), "clean": len(clean)},
    }
    if not_audited:
        result["not_audited"] = not_audited
        result["counts"]["not_audited"] = len(not_audited)
    if format == "csv":
        result["csv"] = _csv_string(all_rows)
    return result


# ==== AGENCY SCORE =========================================================
# A marketing or web agency does not fail a site audit; it keeps its own site
# clean, so a defect is no signal. The buyer signal for an agency is evidence of
# the workload a reporting rollup removes: the ad platforms it runs, the number
# of clients, a promise of reporting, a small team to absorb it, a platform
# certification, and an incumbent reporting tool. Every one is stated on the
# agency's own site, because it is how they sell.

_SIGNAL_WEIGHTS = {
    "platforms": 30, "client_scale": 25, "reporting": 20, "small_team": 15,
    "incumbent": 10, "certified": 15,
}
_PLATFORM_PATTERNS = {
    "google_ads": r"\b(google ads|adwords|google advertising|ppc|paid search|sem)\b",
    "meta_ads": r"\b(meta ads|facebook ads|instagram ads|meta advertising|paid social)\b",
    "analytics": r"\b(google analytics|ga4|analytics)\b",
    "search_console": r"\b(search console|webmaster tools|technical seo|seo)\b",
}
_REPORTING_PATTERNS = (r"monthly report", r"reporting", r"dashboard", r"transparent",
                       r"real[- ]time report", r"performance report", r"analytics report")
_INCUMBENT_TOOLS = ("agencyanalytics", "swydo", "dashthis", "reportgarden", "databox",
                    "whatagraph", "looker studio", "data studio", "klipfolio", "supermetrics")
_CLIENT_PAGE_HINTS = ("client", "case-stud", "case_stud", "portfolio", "work", "results")
_TEAM_PAGE_HINTS = ("team", "about", "who-we-are", "our-people", "staff")
_BADGE_PATTERNS = ("premier-partner", "premier_partner", "marketing-partner", "-partner",
                   "_partner", "partner-", "certified", "certification", "badge", "clutch",
                   "award", "accredited", "bbb")
_BADGE_PLATFORM = {
    "google": ("google-premier", "google-partner", "google_partner"),
    "meta": ("facebook-marketing-partner", "meta-partner", "facebook-partner"),
    "other": ("klaviyo", "shopify", "hubspot", "bing", "microsoft-advertising"),
}
_TIERS = (
    (70, "A", "carries the workload and can pay; a strong reseller prospect"),
    (45, "B", "plausible, one question to answer before spending time on it"),
    (0, "C", "not enough evidence of the workload"),
)


def _strip_html(html: str) -> str:
    import re
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html or "")
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text)


def _agency_links(html: str, base: str) -> list:
    import re
    from urllib.parse import urljoin
    out = []
    host = urlparse(base).netloc
    for m in re.finditer(r'href=["\']([^"\']+)["\']', html or "", re.I):
        href = m.group(1)
        if href.startswith(("mailto:", "tel:", "#", "javascript:")):
            continue
        full = urljoin(base, href)
        if urlparse(full).netloc == host:
            out.append(full.split("#")[0])
    return out


def _pick_links(links: list, hints, limit: int = 2) -> list:
    seen, out = set(), []
    for link in links:
        low = link.lower()
        if any(h in low for h in hints) and link not in seen:
            seen.add(link)
            out.append(link)
            if len(out) >= limit:
                break
    return out


def _is_badge(src: str) -> bool:
    return any(b in src for b in _BADGE_PATTERNS)


def _count_logos(html: str):
    """Return (client logo count, badge basenames). Partner badges sit in the
    same logo walls and are kept out of the client count."""
    import re
    clients, badges = set(), set()
    for m in re.finditer(r'<img[^>]+src=["\']([^"\']+)["\']', html or "", re.I):
        src = m.group(1).lower()
        if not any(k in src for k in ("logo", "client", "brand", "partner")):
            continue
        (badges if _is_badge(src) else clients).add(src)
    return len(clients), sorted(b.split("/")[-1][:60] for b in badges)


def _certified_platforms(badges) -> list:
    blob = " ".join(badges).lower()
    return [name for name, pats in _BADGE_PLATFORM.items()
            if any(p in blob for p in pats)]


def _count_people(text: str, html: str) -> int:
    import re
    roles = re.findall(
        r"\b(founder|owner|ceo|president|director|manager|strategist|specialist|"
        r"analyst|designer|developer|account executive|coordinator)\b",
        text or "", re.I)
    cards = len(re.findall(r'class=["\'][^"\']*(team|member|staff|bio)[^"\']*["\']',
                           html or "", re.I))
    return max(len(set(r.lower() for r in roles)), min(cards, 40))


def _score_agency(pages: dict, links: list) -> dict:
    """Score an agency from its fetched pages. Pure, given the HTML."""
    import re
    all_html = " ".join(pages.values())
    low = _strip_html(all_html).lower()
    signals, evidence, score = {}, {}, 0.0

    found = [name for name, pat in _PLATFORM_PATTERNS.items() if re.search(pat, low, re.I)]
    signals["platforms"] = len(found)
    evidence["platforms"] = found
    score += _SIGNAL_WEIGHTS["platforms"] * min(len(found), 4) / 4

    logos, badges = _count_logos(all_html)
    case_studies = len(_pick_links(links, ("case-stud", "case_stud"), limit=99))
    client_scale = max(logos, case_studies)
    signals["client_scale"] = client_scale
    evidence["client_scale"] = {"client_logos": logos, "case_study_links": case_studies,
                                "badges_excluded": len(badges)}
    if client_scale >= 5:
        score += _SIGNAL_WEIGHTS["client_scale"] * min(client_scale, 20) / 20

    rep = [p for p in _REPORTING_PATTERNS if re.search(p, low, re.I)]
    signals["reporting"] = len(rep)
    evidence["reporting"] = rep[:4]
    if rep:
        score += _SIGNAL_WEIGHTS["reporting"] * min(len(rep), 3) / 3

    people = _count_people(low, pages.get("team", ""))
    signals["headcount_proxy"] = people
    evidence["headcount_proxy"] = "role words or member cards on the team page"
    if 1 <= people <= 12:
        score += _SIGNAL_WEIGHTS["small_team"]
    elif people <= 25:
        score += _SIGNAL_WEIGHTS["small_team"] * 0.4

    certs = _certified_platforms(badges)
    signals["certified_platforms"] = certs
    evidence["certified_platforms"] = badges[:8]
    if certs:
        score += _SIGNAL_WEIGHTS["certified"] * min(len(certs), 2) / 2

    tools = [t for t in _INCUMBENT_TOOLS if t in low]
    signals["incumbent_tool"] = tools
    evidence["incumbent_tool"] = tools
    if tools:
        score += _SIGNAL_WEIGHTS["incumbent"]

    out = {"score": round(score, 1), "factors": signals, "evidence": evidence}
    for floor, tier, meaning in _TIERS:
        if out["score"] >= floor:
            out["tier"] = tier
            out["tier_meaning"] = meaning
            break

    proven = set(found)
    if "google" in certs:
        proven.update({"google_ads", "analytics"})
    if "meta" in certs:
        proven.add("meta_ads")
    missing = [k for k in ("google_ads", "meta_ads", "analytics") if k not in proven]
    out["disqualifiers"] = (["does not advertise running: " + ", ".join(missing)]
                            if missing else [])
    out["ask_on_the_call"] = ("How many clients do you report on every month, and "
                              "who builds the report?")
    return out


def agency_score(url: str) -> dict:
    """Score a marketing or web agency's site as a reseller partner.

    The homepage is read with the shared fetch layer, so a bot wall or a dead
    site is reported as unreadable rather than scored. A clients or case-study
    page and a team page are read when linked. The site is then scored on the
    buying signals an agency states about itself: the ad platforms it runs, its
    client scale, a reporting promise, a small enough team to feel the workload, a
    platform certification, and an incumbent reporting tool. Each signal weight is
    a stated convention, kept in one place so one edit retunes the model.

    Returns: url, status_code, score, tier, tier_meaning, factors, evidence,
    disqualifiers, ask_on_the_call. On an unreadable site: readable False with the
    reason.
    """
    r, soup, error = sitefetch.get_page(url)
    if error:
        out = dict(error)
        out.setdefault("readable", False)
        out["url"] = out.get("url") or url
        return out
    base = str(getattr(r, "url", "") or url)
    html = getattr(r, "text", "") or ""
    links = _agency_links(html, base)
    pages = {"home": html}
    pages_read = {}
    for label, hints in (("clients", _CLIENT_PAGE_HINTS), ("team", _TEAM_PAGE_HINTS)):
        for u in _pick_links(links, hints, limit=1):
            try:
                sub = sitefetch.fetch(u, ua=UA)
                if sub.status_code < 400 and sub.text:
                    pages[label] = sub.text
                    pages_read[label] = u
            except Exception:  # noqa: BLE001
                pass
            break
    scored = _score_agency(pages, links)
    scored.update({"url": url, "status_code": getattr(r, "status_code", None),
                   "readable": True, "pages_read": pages_read})
    return scored
