# Copyright (c) 2026 The Wayfinder Trust - Jonathan Luethke
# All Rights Reserved. Proprietary and Confidential.
"""Offline checks for site_hygiene.py. No network. Run: python test_site_hygiene.py"""
import datetime
import json
import os
import struct
import tempfile
import zipfile
import zlib

import site_hygiene as sh

ROOT = "https://acme.com"

_BODY = ("We fix burst pipes, water heaters, and clogged drains across the whole metro "
         "area day and night, with upfront flat-rate pricing and fully licensed plumbers "
         "you can trust, backed by a written workmanship guarantee on every single job "
         "and same day service that keeps your home dry and running without any surprises")

PAGE_A = """<!doctype html><html><head><title>Acme Plumbing: emergency repair</title>
<meta name="description" content="Fast emergency plumbing in Austin."></head><body>
<h1>Emergency plumbing in Austin</h1>
<p>%s.</p>
<a href="/services">Services</a> <a href="/contact">Contact</a></body></html>""" % _BODY

PAGE_B = """<!doctype html><html><head><title>Acme Plumbing: emergency repair</title>
<meta name="description" content="Fast emergency plumbing in Austin."></head><body>
<h1>Emergency plumbing in Austin</h1>
<p>%s today.</p>
<a href="/services">Services</a> <a href="/contact">Contact</a></body></html>""" % _BODY

PAGE_C = """<!doctype html><html><head><title>About Acme</title>
<meta name="description" content="Who we are."></head><body>
<h1>About us</h1><p>A small family plumbing company founded in 2004 serving the region.</p>
<a href="/contact">Contact</a></body></html>"""

PAGE_D = """<!doctype html><html><head><title>Water heater repair duplicate</title>
<meta name="description" content="A copy page."></head><body>
<h1>Water heater repair</h1><p>Spun-up duplicate of the water heater service page.</p>
</body></html>"""


def check(name, cond):
    if not cond:
        raise AssertionError(name)
    print("ok  " + name)


def test_duplicates():
    a = sh.page_record(ROOT + "/a", PAGE_A, ROOT)
    b = sh.page_record(ROOT + "/b", PAGE_B, ROOT)
    c = sh.page_record(ROOT + "/about", PAGE_C, ROOT)
    dpage = sh.page_record(ROOT + "/services/water-heater-copy", PAGE_D, ROOT)

    check("shingles overlap scores high for near-identical text",
          sh.jaccard(sh.shingles(a["text"]), sh.shingles(b["text"])) >= 0.8)
    check("shingles overlap is low for different text",
          sh.jaccard(sh.shingles(a["text"]), sh.shingles(c["text"])) < 0.3)

    sitemap = [ROOT + "/a", ROOT + "/b", ROOT + "/about",
               ROOT + "/services/water-heater-copy", ROOT + "/"]
    an = sh.analyze_records([a, b, c, dpage], sitemap_urls=sitemap)
    pair = {frozenset(e["urls"]) for e in an["near_duplicates"]}
    check("near-duplicate pair is grouped with a score",
          frozenset([ROOT + "/a", ROOT + "/b"]) in pair
          and an["near_duplicates"][0]["score"] >= 0.8)
    check("shared titles grouped", any(len(g["urls"]) == 2 for g in an["shared_titles"]))
    check("shared H1s grouped", any(set(g["urls"]) == {ROOT + "/a", ROOT + "/b"}
                                    for g in an["shared_h1s"]))
    check("shared meta descriptions grouped",
          any(set(g["urls"]) == {ROOT + "/a", ROOT + "/b"} for g in an["shared_meta_descriptions"]))
    check("copy-suffixed slug flagged",
          any(c["suffix"] == "copy" for c in an["slug_collisions"]))
    check("orphan page detected",
          ROOT + "/about" in an["orphan_pages"] or "/about" in str(an["orphan_pages"]))


def test_sitemap_hygiene():
    today = datetime.date.today()
    same = today.isoformat() + "T00:00:00+00:00"
    rows_same = [{"loc": ROOT + "/1", "lastmod": same},
                 {"loc": ROOT + "/2", "lastmod": same},
                 {"loc": ROOT + "/3", "lastmod": same}]
    lm = sh.analyze_lastmod(rows_same)
    check("identical lastmod detected", lm["all_identical"] and lm["present_share"] == 1.0)

    future = (today + datetime.timedelta(days=30)).isoformat()
    rows_mixed = [{"loc": ROOT + "/1", "lastmod": "2025-01-01"},
                  {"loc": ROOT + "/2", "lastmod": future},
                  {"loc": ROOT + "/3", "lastmod": None}]
    lm2 = sh.analyze_lastmod(rows_mixed)
    check("non-identical lastmod not flagged", not lm2["all_identical"])
    check("future lastmod detected", future in lm2["in_future"])
    check("lastmod present share", lm2["with_lastmod"] == 2)

    hosts = sh.analyze_hosts([ROOT + "/a", "http://acme.com/b", "https://www.acme.com/c"])
    check("mixed http/https detected", hosts["mixed_http_https"])
    check("mixed www/apex detected", hosts["mixed_www_apex"])


def test_ai_crawlers():
    robots = ("User-agent: *\nDisallow: /admin\n\n"
              "User-agent: GPTBot\nDisallow: /\n\n"
              "User-agent: ClaudeBot\nAllow: /\n")
    rules = sh.ai_crawler_rules(robots)
    check("GPTBot blocked by name", rules["GPTBot"] == {"named": True, "access": "blocked"})
    check("ClaudeBot allowed by name", rules["ClaudeBot"] == {"named": True, "access": "allowed"})
    check("unnamed crawler inherits star group",
          rules["PerplexityBot"] == {"named": False, "access": "partly restricted"})
    check("every listed crawler is reported", set(rules) == set(sh.AI_CRAWLERS))


def test_schema_build():
    out = sh.schema_build(
        "plumber", "Acme Plumbing", "https://acme.com", phone="+1-512-555-0100",
        address="1 Main St", city="Austin", region="TX", postal_code="78701",
        services=["Water heater repair", {"name": "Drain cleaning", "description": "Fast"}],
        faqs=[{"question": "Are you licensed?", "answer": "Yes."}],
        same_as=["https://facebook.com/acme"], founder="Jane Roe",
        hours={"monday": "08:00-17:00"})
    check("most specific LocalBusiness subtype used", "Plumber" in out["types"])
    check("Organization, WebSite, Service, FAQPage, Person present",
          {"Organization", "WebSite", "Service", "FAQPage", "Person"}.issubset(set(out["types"])))
    check("JSON-LD round-trips through json", out["valid_json"])
    doc = json.loads(out["jsonld"])
    check("jsonld is a schema.org @graph", doc["@context"] == "https://schema.org"
          and isinstance(doc["@graph"], list))
    check("unknown type falls back to LocalBusiness",
          sh.localbusiness_subtype("llama groomer") == "LocalBusiness")


def test_llms_txt():
    pages = [
        {"url": "https://acme.com/", "title": "Acme Plumbing", "description": "Home", "segment": ""},
        {"url": "https://acme.com/services/drains", "title": "Drain cleaning",
         "description": "We clear drains", "segment": "services"},
        {"url": "https://acme.com/blog/pipes", "title": "Pipe tips",
         "description": "How pipes [fail]", "segment": "blog"},
    ]
    built = sh.build_llms_txt("Acme Plumbing", "The Austin plumber", pages, skipped=2)
    text = built["text"]
    check("H1 site name present", text.startswith("# Acme Plumbing"))
    check("summary quoted", "> The Austin plumber" in text)
    check("section heading from top segment", "## Services" in text)
    check("line format with title, url and description",
          "- [Drain cleaning](https://acme.com/services/drains): We clear drains" in text)
    check("brackets stripped from description so the link does not break",
          "How pipes fail" in text and "[fail]" not in text.split("pipes", 1)[1][:20])
    check("skipped pages noted", "2 page(s) were skipped" in text)
    check("counts returned", built["page_count"] == 3 and built["section_count"] == 3)


def test_cover_image():
    with tempfile.TemporaryDirectory() as d:
        out = os.path.join(d, "card.png")
        long_title = ("Emergency Plumbing Repair and Water Heater Installation "
                      "for the Entire Greater Austin Metropolitan Service Area")
        res = sh.cover_image(long_title, subtitle="Licensed, insured, available day and night",
                             out_path=out)
        check("cover PNG written", os.path.exists(out) and os.path.getsize(out) > 0)
        check("cover size is 1200x630", res["size"] == [1200, 630])
        check("long title sits inside the safe zone", res["safe_zone_ok"])
        from PIL import Image
        with Image.open(out) as im:
            check("saved image has the requested dimensions", im.size == (1200, 630))


def _chunk(typ, data):
    return struct.pack(">I", len(data)) + typ + data + \
        struct.pack(">I", zlib.crc32(typ + data) & 0xffffffff)


def test_strip_metadata_png():
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "img.png")
        ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
        idat = zlib.compress(b"\x00\x00\x00\x00")
        raw = (sh._PNG_SIG + _chunk(b"IHDR", ihdr) + _chunk(b"tEXt", b"Author\x00Jane")
               + _chunk(b"caBX", b"c2pa manifest bytes") + _chunk(b"IDAT", idat)
               + _chunk(b"IEND", b""))
        with open(src, "wb") as f:
            f.write(raw)
        res = sh.strip_metadata(src)
        check("png out_path is not the source", res["out_path"] != src and os.path.exists(res["out_path"]))
        check("tEXt and caBX removed", "tEXt" in res["removed"] and "caBX" in res["removed"])
        with open(res["out_path"], "rb") as f:
            cleaned = f.read()
        check("image chunks kept", b"IHDR" in cleaned and b"IDAT" in cleaned and b"IEND" in cleaned)
        check("metadata chunks gone", b"tEXt" not in cleaned and b"caBX" not in cleaned
              and b"c2pa" not in cleaned)


def test_strip_metadata_docx():
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "doc.docx")
        core = ('<?xml version="1.0"?><cp:coreProperties '
                'xmlns:cp="x" xmlns:dc="y" xmlns:dcterms="z">'
                '<dc:title>Keep This Title</dc:title>'
                '<dc:creator>Jane Secret</dc:creator>'
                '<cp:lastModifiedBy>Jane Secret</cp:lastModifiedBy>'
                '<cp:revision>7</cp:revision></cp:coreProperties>')
        app = ('<?xml version="1.0"?><Properties><Application>Microsoft Word</Application>'
               '<Company>Secret Corp</Company></Properties>')
        with zipfile.ZipFile(src, "w") as z:
            z.writestr("[Content_Types].xml", "<Types/>")
            z.writestr("word/document.xml", "<document>body</document>")
            z.writestr("docProps/core.xml", core)
            z.writestr("docProps/app.xml", app)
        res = sh.strip_metadata(src)
        check("docx out_path is not the source", res["out_path"] != src)
        with zipfile.ZipFile(res["out_path"]) as z:
            new_core = z.read("docProps/core.xml").decode("utf-8")
            new_app = z.read("docProps/app.xml").decode("utf-8")
            body = z.read("word/document.xml").decode("utf-8")
        check("creator removed", "Jane Secret" not in new_core)
        check("company removed", "Secret Corp" not in new_app)
        check("title kept", "Keep This Title" in new_core)
        check("other parts untouched", body == "<document>body</document>")
        check("what was removed is reported", "core.xml" in res["removed"])


def main():
    test_duplicates()
    test_sitemap_hygiene()
    test_ai_crawlers()
    test_schema_build()
    test_llms_txt()
    test_cover_image()
    test_strip_metadata_png()
    test_strip_metadata_docx()
    print("all checks passed")


if __name__ == "__main__":
    main()
