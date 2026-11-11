# Copyright (c) 2026 The Wayfinder Trust - Jonathan Luethke
# All Rights Reserved. Proprietary and Confidential.
"""Offline checks for seo_rules.py. No network. Run: python test_seo_rules.py

Single-page functions are tested through their _parse_* helpers on HTML strings.
Multi-page functions (missing_pages, crawl_depth, internal_link_plan) run in full
against a fake fetch layer: sitefetch.get_page, sitemap_urls, and parse_robots are
replaced with ones that serve canned pages from a dict, so the whole decision
surface runs without touching the network.
"""
import seo_rules
import sitefetch
from bs4 import BeautifulSoup


def check(name, cond):
    if not cond:
        raise AssertionError(name)
    print("ok  " + name)


# ---- a fake fetch layer ---------------------------------------------------

class _Resp:
    def __init__(self, url, text, status=200):
        self.url = url
        self.text = text
        self.status_code = status
        self.headers = {}


def install_fetch(pages, sitemap=None, disallow=None):
    """Point sitefetch at an in-memory site. `pages` maps a canonical URL to HTML.
    Returns a restore() to put the real functions back."""
    canon_pages = {seo_rules._canon(u): html for u, html in pages.items()}
    saved = (sitefetch.get_page, sitefetch.sitemap_urls, sitefetch.parse_robots)

    def fake_get_page(url, *a, **k):
        c = seo_rules._canon(url)
        if c in canon_pages:
            html = canon_pages[c]
            return _Resp(c, html), BeautifulSoup(html, "html.parser"), None
        return _Resp(c, "", 404), None, {"status_code": 404, "url": c, "readable": False,
                                         "blocked": False, "error": "404"}

    sitefetch.get_page = fake_get_page
    sitefetch.sitemap_urls = lambda root, declared, limit=200, ua=None: (list(sitemap or []), {})
    sitefetch.parse_robots = lambda root, ua=None: ({"disallow": list(disallow or []), "allow": []}, [])

    def restore():
        sitefetch.get_page, sitefetch.sitemap_urls, sitefetch.parse_robots = saved
    return restore


# ---- fixtures -------------------------------------------------------------

MONEY_GOOD = """<!doctype html><html lang="en"><head>
<title>Springfield Web Design | Example Studio</title>
<meta name="description" content="Professional Springfield web design that converts.">
</head><body>
<h1>Springfield Web Design</h1>
<p>Our Springfield web design service builds fast sites. We have offered web design in
Springfield for years and clients love the results of this web design work.</p>
</body></html>"""

MONEY_BAD = """<!doctype html><html><head>
<title>Welcome to Our Studio</title>
<meta name="description" content="We build nice things.">
</head><body>
<h1>Home</h1>
<p>We make great websites for all kinds of businesses across the region. Call today
and let us help your company grow online with a modern, fast, friendly site.</p>
</body></html>"""

COMP_A = """<html><head><title>Springfield Web Design Experts</title>
<meta name="description" content="Licensed, insured Springfield web design since 2008.">
<script type="application/ld+json">{"@type":"LocalBusiness","name":"A"}</script>
</head><body>
<h1>Springfield Web Design</h1>
<h2>Our Process</h2><h2>Pricing</h2><h2>Service Areas</h2>
<p>Licensed and insured, serving Springfield since 2008. Web design starting at $1,500.
We serve Springfield and the areas we serve nearby. Call 570-555-1212.</p>
</body></html>"""

COMP_B = """<html><head><title>Best Springfield Web Design</title>
<meta name="description" content="Award winning web design.">
</head><body>
<h1>Springfield Web Design Studio</h1>
<h2>Our Process</h2><h2>Portfolio</h2><h2>Pricing</h2>
<p>Award winning and certified web design. Pricing from $2,000. Insured and licensed.
Hours: Mon to Fri 9am to 5pm. Over 120 reviews.</p>
</body></html>"""

IMG_PAGE = """<html><body>
<p>%s</p>
<img src="/images/springfield-web-design-team.webp" alt="our Springfield web design team" width="800" height="600" loading="lazy">
<img src="/photos/IMG_4821.JPG" alt="">
<img src="https://cdn.example.com/a1b2c3d4e5f6a7b8.png">
</body></html>""" % ("word " * 400)


def main():
    # ---- keyword matching primitives --------------------------------------
    check("exact phrase present", seo_rules._keyword_present("the Springfield web design shop", "springfield web design"))
    check("plural matches singular keyword", seo_rules._keyword_present("great plumbers here", "plumber"))
    check("words in any order within window",
          seo_rules._keyword_present("design for the web in Springfield today", "springfield web design"))
    check("far-apart words do not match",
          not seo_rules._keyword_present("web is first. " + ("x " * 30) + "design last in Springfield", "springfield web design"))
    check("phrase count is non-overlapping", seo_rules._keyword_count("web design and web design", "web design") == 2)
    check("absent keyword counts zero", seo_rules._keyword_count("nothing relevant here", "web design") == 0)

    # ---- 1. money_page_check ----------------------------------------------
    good = seo_rules._parse_money_page(MONEY_GOOD, "https://x.com/springfield-web-design", "Springfield web design")
    check("good money page passes every element", good["all_elements_pass"])
    check("good money page counts occurrences", good["occurrences_in_visible_text"] >= 3)
    check("good money page needs no fixes", good["fixes"] == [])
    bad = seo_rules._parse_money_page(MONEY_BAD, "https://x.com/", "Springfield web design")
    check("bad money page fails visible text", bad["elements"]["visible_text"] is False)
    check("bad money page lists the body fix first",
          bad["fixes"][0].startswith("The keyword 'Springfield web design' never appears in the visible body text"))
    check("bad money page occurrences zero", bad["occurrences_in_visible_text"] == 0)

    # ---- 2. competitor_page_gap (parse-level) -----------------------------
    mine = seo_rules._read_page_for_gap(MONEY_BAD, "https://x.com/", "Springfield web design")
    ca = seo_rules._read_page_for_gap(COMP_A, "https://a.com/", "Springfield web design")
    cb = seo_rules._read_page_for_gap(COMP_B, "https://b.com/", "Springfield web design")
    check("competitor trust facts detected", "licensed" in ca["trust_facts"] and "insured" in ca["trust_facts"])
    check("competitor phone detected", "phone" in ca["trust_facts"])
    check("competitor schema types read", ca["schema_types"] == ["LocalBusiness"])
    check("competitor keyword placements include h1", "h1" in ca["keyword_placements"])
    # shared H2s on both competitors, absent on yours
    h2_a = set(h.lower() for h in ca["h2"])
    h2_b = set(h.lower() for h in cb["h2"])
    common = (h2_a & h2_b) - set(h.lower() for h in mine["h2"])
    check("both competitors share the pricing H2 you lack", "pricing" in common)
    check("your page has no h2s", mine["h2"] == [])

    over = seo_rules._read_page_for_gap(
        '<html><body><h1>k</h1><p>%s</p></body></html>' % ("web design " * 9),
        "https://x.com/", "web design")
    check("over-optimized page has a high keyword count", over["keyword_count"] == 9)

    # full competitor_page_gap over the fake layer
    restore = install_fetch({
        "https://me.com/web-design": MONEY_BAD,
        "https://a.com/": COMP_A,
        "https://b.com/": COMP_B,
    })
    try:
        gap = seo_rules.competitor_page_gap("https://me.com/web-design",
                                            ["https://a.com/", "https://b.com/", "https://dead.com/"],
                                            "Springfield web design")
    finally:
        restore()
    check("gap counts two readable competitors", len(gap["competitors"]) == 2)
    check("gap lists the unreadable competitor", len(gap["unreadable_competitors"]) == 1)
    check("gap finds missing pricing H2", "pricing" in gap["missing_from_you"]["h2_topics"])
    check("gap finds missing trust facts", "licensed" in gap["missing_from_you"]["trust_facts"])
    check("gap word-count median is positive gap", gap["word_count_gap_vs_median"] is not None)
    check("gap over-optimization is false here", gap["over_optimization"] is False)

    # ---- 3. missing_pages -------------------------------------------------
    check("topic key strips extension and dashes", seo_rules._topic_key("https://x.com/water-heater-repair.html") == ("water heater repair", True))
    check("blog path is not a money candidate", seo_rules._topic_key("https://x.com/blog/why-pipes-freeze")[1] is False)
    check("numbers-only segment is dropped", seo_rules._topic_key("https://x.com/services/12345")[0] == "services")
    check("homepage has no topic", seo_rules._topic_key("https://x.com/")[0] is None)

    restore = install_fetch(
        {"https://me.com/": "<html><body><nav><a href='/drain-cleaning'>d</a></nav></body></html>"},
        sitemap=None)
    # mine via sitemap empty -> homepage nav; competitors via sitemap
    saved = sitefetch.sitemap_urls

    def sm(root, declared, limit=200, ua=None):
        if "comp.com" in root:
            return (["https://comp.com/drain-cleaning", "https://comp.com/water-heater-repair",
                     "https://comp.com/sewer-line", "https://comp.com/blog/tips"], {})
        return ([], {})
    sitefetch.sitemap_urls = sm
    try:
        miss = seo_rules.missing_pages("https://me.com/", ["https://comp.com/"], max_pages=50)
    finally:
        sitefetch.sitemap_urls = saved
        restore()
    topics = [m["topic"] for m in miss["missing_topics"]]
    check("missing_pages finds the competitor-only topics",
          "water heater repair" in topics and "sewer line" in topics)
    check("missing_pages excludes a shared topic", "drain cleaning" not in topics)
    check("missing_pages excludes the blog path", "tips" not in topics)
    check("missing_pages ranks by competitor count",
          miss["missing_topics"] == sorted(miss["missing_topics"],
                                            key=lambda m: (-m["competitor_count"], m["topic"])))

    # ---- 4. crawl_depth ---------------------------------------------------
    site_pages = {
        "https://s.com/": "<html><body><nav><a href='/'>h</a><a href='/services'>s</a>"
                          "<a href='/blog/post-1'>b</a></nav></body></html>",
        "https://s.com/services": "<html><body><a href='/services/deep'>d</a></body></html>",
        "https://s.com/services/deep": "<html><body><a href='/services/deep/deeper'>x</a></body></html>",
        "https://s.com/services/deep/deeper": "<html><body>end</body></html>",
        "https://s.com/blog/post-1": "<html><body><a href='/buried'>buried</a></body></html>",
        "https://s.com/buried": "<html><body>only from blog</body></html>",
    }
    restore = install_fetch(site_pages, sitemap=[
        "https://s.com/", "https://s.com/services", "https://s.com/orphan-page"])
    try:
        cd = seo_rules.crawl_depth("https://s.com/", max_pages=50, time_budget_s=30)
    finally:
        restore()
    depth_by = {d["url"]: d["depth"] for d in cd["depths"]}
    check("homepage is depth 0", depth_by[seo_rules._canon("https://s.com/")] == 0)
    check("services is depth 1", depth_by[seo_rules._canon("https://s.com/services")] == 1)
    check("deeper page exceeds depth 2",
          any(d["depth"] > 2 for d in cd["deeper_than_2"]))
    check("sitemap orphan is reported",
          seo_rules._canon("https://s.com/orphan-page") in cd["orphan_sitemap_urls"])
    check("page reachable only through blog is flagged",
          seo_rules._canon("https://s.com/buried") in cd["blog_only_pages"])

    # robots disallow is honored
    restore = install_fetch(site_pages, disallow=["/services"])
    try:
        cd2 = seo_rules.crawl_depth("https://s.com/", max_pages=50, time_budget_s=30)
    finally:
        restore()
    check("disallowed path is not crawled",
          seo_rules._canon("https://s.com/services") not in {d["url"] for d in cd2["depths"]})

    # ---- 5. internal_link_plan --------------------------------------------
    check("topic words drop stop words and short words",
          seo_rules._topic_words("How to fix a Water Heater") == ["fix", "water", "heater"])
    check("score counts distinct topic words",
          seo_rules._score_text("the water heater and the heater", ["water", "heater"]) == 2)
    check("anchor sentence is the first mentioning the topic",
          seo_rules._anchor_sentence("Nothing here. A water heater leaks. The end.", ["water"])
          == "A water heater leaks.")

    link_pages = {
        "https://s.com/blog/new-water-heater-guide":
            "<html><head><title>New Water Heater Guide</title></head><body><h1>Water Heater Guide</h1></body></html>",
        "https://s.com/blog/old-leak-post":
            "<html><head><title>Fixing a Water Heater Leak</title></head><body>"
            "<p>A water heater leak is common. Our water heater tips help.</p></body></html>",
        "https://s.com/blog/unrelated":
            "<html><head><title>Garden Tips</title></head><body><p>Flowers and soil.</p></body></html>",
        "https://s.com/water-heater-repair":
            "<html><head><title>Water Heater Repair Service</title></head><body>"
            "<h1>Water Heater Repair</h1><p>We repair water heaters fast.</p></body></html>",
        "https://s.com/blog/already-links":
            "<html><head><title>Water Heater News</title></head><body>"
            "<p>See our water heater guide.</p>"
            "<a href='/blog/new-water-heater-guide'>guide</a></body></html>",
    }
    restore = install_fetch(link_pages, sitemap=list(link_pages.keys()))
    try:
        plan = seo_rules.internal_link_plan("https://s.com/", "https://s.com/blog/new-water-heater-guide")
    finally:
        restore()
    check("plan derives topic from the new post H1", plan["topic"] == "Water Heater Guide")
    from_urls = [p["url"] for p in plan["link_from"]]
    check("plan links from the relevant old post",
          seo_rules._canon("https://s.com/blog/old-leak-post") in from_urls)
    check("plan excludes the unrelated post", seo_rules._canon("https://s.com/blog/unrelated") not in from_urls)
    check("plan picks the money page to link to",
          plan["money_page_to_link_to"]["url"] == seo_rules._canon("https://s.com/water-heater-repair"))
    check("plan reports the post already linking separately",
          seo_rules._canon("https://s.com/blog/already-links") in plan["already_linking_to_new_post"]
          and seo_rules._canon("https://s.com/blog/already-links") not in from_urls)
    check("plan older posts carry an anchor sentence",
          all("anchor_sentence" in p for p in plan["older_posts_to_link_to_new"]))

    # ---- 6. paid_vs_organic ----------------------------------------------
    rows = [
        {"keyword": "a", "cpc": 10.0, "difficulty": 20},   # high cpc, low diff -> SEO first
        {"keyword": "b", "cpc": 9.0, "difficulty": 80},    # high cpc, high diff -> Ads now
        {"keyword": "c", "cpc": 1.0, "difficulty": 10},    # low cpc, low diff -> Ads for speed
        {"keyword": "d", "cpc": 2.0, "difficulty": 70},    # low cpc, high diff -> Ads only
        {"keyword": "e", "cpc": 8.0},                      # no difficulty -> unclassified
    ]
    pvo = seo_rules.paid_vs_organic(rows)
    check("cpc split defaults to the median", pvo["cpc_threshold"] == 8.0)
    check("SEO first box is correct", [r["keyword"] for r in pvo["boxes"]["SEO first"]] == ["a"])
    check("Ads now box is correct", [r["keyword"] for r in pvo["boxes"]["Ads now, SEO long-term"]] == ["b"])
    check("Ads for speed box is correct", [r["keyword"] for r in pvo["boxes"]["Ads for speed, content later"]] == ["c"])
    check("Ads only box is correct", [r["keyword"] for r in pvo["boxes"]["Ads only"]] == ["d"])
    check("row without difficulty is unclassified with its cpc side",
          pvo["unclassified_needs_difficulty"][0]["keyword"] == "e"
          and pvo["unclassified_needs_difficulty"][0]["cpc_side"] == "high")
    check("counts total the classified rows", sum(pvo["counts"].values()) == 4)

    pvo2 = seo_rules.paid_vs_organic(
        [{"keyword": "x", "high_bid": 5.0, "difficulty": 15}], cpc_threshold=3.0)
    check("accepts high_bid as the cpc key and an explicit threshold",
          pvo2["boxes"]["SEO first"][0]["keyword"] == "x")

    # ---- 7. image_check ---------------------------------------------------
    ic = seo_rules._parse_image_check(IMG_PAGE, "https://x.com/post")
    check("image_check counts images", ic["image_count"] == 3)
    first = ic["images"][0]
    check("descriptive webp image is clean",
          first["descriptive_name"] and first["alt_nonempty"] and first["lazy"]
          and first["has_dimensions"] and first["format"] == "webp")
    check("descriptive alt shares a word with the file name", first["alt_shares_word_with_filename"])
    check("IMG_4821 is a non-descriptive name", ic["images"][1]["descriptive_name"] is False)
    check("empty alt is present but not non-empty",
          ic["images"][1]["alt_present"] and ic["images"][1]["alt_nonempty"] is False)
    check("hash file name is non-descriptive", ic["images"][2]["descriptive_name"] is False)
    check("missing alt attribute is not present", ic["images"][2]["alt_present"] is False)
    check("images per 250 words is reported", ic["images_per_250_words"] is not None)
    check("image fixes name the empty-alt image", any("alt text" in f for f in ic["fixes"]))

    print("all checks passed")


if __name__ == "__main__":
    main()
