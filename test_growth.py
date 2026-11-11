# Copyright (c) 2026 The Wayfinder Trust - Jonathan Luethke
# All Rights Reserved. Proprietary and Confidential.
"""Offline checks for growth.py. No network. Run: python test_growth.py"""
import growth

PAGE_2024 = """<!doctype html><html><head><title>Acme: build apps by chat</title>
<meta name="description" content="Acme builds apps from a prompt.">
<script async src="https://www.googletagmanager.com/gtag/js?id=G-ABCDEF1234"></script>
<script>gtag('config', 'G-ABCDEF1234');</script>
</head><body>
<p>We wrote a blog post about how the Meta Pixel and hotjar work. Trusted by 12,000 users.</p>
<a href="/pricing">Pricing</a> <a href="/blog/first-post">Blog</a>
<a href="https://twitter.com/acme">X</a> <a href="https://twitter.com/intent/tweet?text=hi">Share</a>
</body></html>"""

PAGE_2025 = """<!doctype html><html><head><title>Acme: the app builder for teams</title>
<script async src="https://www.googletagmanager.com/gtag/js?id=G-ABCDEF1234"></script>
<script>(function(w,d,s,l,i){})(window,document,'script','dataLayer','GTM-ABC1234');</script>
<script>!function(f,b,e,v){}(window,document,'script','https://connect.facebook.net/en_US/fbevents.js');
fbq('init', '1234567890123'); fbq('track', 'PageView');</script>
<script src="https://r.wdfl.co/rw.js" data-rewardful="abc123"></script>
<script type="application/ld+json">{"@context":"https://schema.org","@type":"FAQPage"}</script>
</head><body>
<p>Join 2M+ builders. $100M ARR in eight months.</p>
<a href="/pricing">Pricing</a> <a href="/templates">Templates</a> <a href="/affiliates">Affiliates</a>
<a href="https://docs.acme.com/start">Docs</a> <a href="https://www.acme.com/enterprise?ref=nav">Enterprise</a>
<a href="https://x.com/acme">X</a> <a href="https://www.linkedin.com/company/acme-inc/">LinkedIn</a>
<a href="https://discord.gg/acme">Discord</a> <a href="https://www.youtube.com/@acme">YouTube</a>
</body></html>"""

ROBOTS = """User-agent: *
Disallow: /admin

User-agent: GPTBot
User-agent: CCBot
Disallow: /

User-agent: ClaudeBot
Allow: /

Sitemap: https://acme.com/sitemap.xml
"""


def check(name, cond):
    if not cond:
        raise AssertionError(name)
    print("ok  " + name)


def main():
    check("host_of strips scheme and www", growth.host_of("https://www.Acme.com/pricing") == "acme.com")
    check("host_of takes a bare domain", growth.host_of("acme.com") == "acme.com")

    a = growth.read_page(PAGE_2024, "acme.com")
    b = growth.read_page(PAGE_2025, "acme.com")

    check("2024 sees GA4 with its id", a["tags"]["Google Analytics 4"]["ids"] == ["G-ABCDEF1234"])
    check("body copy naming a vendor is not a tag", "Meta Pixel" not in a["tags"] and "Hotjar" not in a["tags"])
    check("2025 sees Meta Pixel with its id", b["tags"]["Meta Pixel"]["ids"] == ["1234567890123"])
    check("2025 sees the tag manager id", b["tags"]["Google Tag Manager"]["ids"] == ["GTM-ABC1234"])
    check("2025 sees Rewardful in the affiliate lane", b["tags"]["Rewardful"]["lane"] == "affiliates_referral")
    check("share intent link is not a profile", a["social"] == {"X": ["acme"]})
    check("2025 social profiles",
          set(b["social"]) == {"X", "LinkedIn", "Discord", "YouTube"} and b["social"]["LinkedIn"] == ["company/acme-inc"])
    check("2024 sections", a["sections"]["paths"] == ["pricing", "blog"])
    check("2025 sections and subdomain",
          b["sections"]["paths"] == ["pricing", "templates", "affiliates", "enterprise"]
          and b["sections"]["subdomains"] == ["docs"])
    check("stated numbers are verbatim", a["stated_numbers"] == ["12,000 users"])
    check("2025 stated numbers", "2M+ builders" in b["stated_numbers"] and "$100M ARR" in b["stated_numbers"])
    check("answer schema read", b["schema_types"] == ["FAQPage"])
    check("title read", a["title"] == "Acme: build apps by chat")
    check("meta description read", a["meta_description"] == "Acme builds apps from a prompt.")

    access = growth.ai_crawler_access(ROBOTS)
    check("GPTBot blocked by name", access["GPTBot"] == {"named": True, "access": "blocked"})
    check("CCBot shares the GPTBot group", access["CCBot"] == {"named": True, "access": "blocked"})
    check("ClaudeBot allowed by name", access["ClaudeBot"] == {"named": True, "access": "allowed"})
    check("unnamed crawler falls under star",
          access["PerplexityBot"] == {"named": False, "access": "partly restricted"})
    check("empty robots allows all", growth.ai_crawler_access("")["GPTBot"]["access"] == "allowed")

    check("pick_evenly keeps first and last",
          growth.pick_evenly(list(range(37)), 5) == [0, 9, 18, 27, 36])
    check("pick_evenly returns all when few", growth.pick_evenly([1, 2, 3], 10) == [1, 2, 3])

    built = growth.build_timeline([{"date": "2024-03-01", "page": a}, {"date": "2025-06-01", "page": b}])
    events = {(e["date"], e["lane"], e["event"]) for e in built["timeline"]}
    check("Meta Pixel first seen with its bracket",
          ("2025-06-01", "ads_tracking", "Meta Pixel first seen") in events)
    pixel = next(e for e in built["lanes"]["ads_tracking"] if e["signal"] == "Meta Pixel")
    check("bracket names the last snapshot without it", pixel["absent_before"] == "2024-03-01")
    ga = next(e for e in built["lanes"]["analytics_product"] if e["signal"] == "Google Analytics 4")
    check("signal present at window start has no bracket",
          ga["absent_before"] is None and {"lane": "analytics_product", "signal": "Google Analytics 4"}
          in built["present_at_window_start"])
    check("affiliate page lands in the partners play",
          ("2025-06-01", "sections:partners", "/affiliates first seen") in events)
    check("templates land in programmatic search",
          ("2025-06-01", "sections:programmatic_search", "/templates first seen") in events)
    blog = next(e for e in built["lanes"]["sections:content"] if e["signal"] == "/blog")
    check("a dropped section is marked in its lane, off the timeline",
          blog["in_latest"] is False and not any("/blog no longer seen" == e[2] for e in events))

    noisy = ('<a href="https://x.com/Acme">a</a><a href="https://x.com/acme">b</a>'
             '<script>{"u":"https://www.linkedin.com/company/acme-inc\\\\"}</script>'
             '<a href="/privacy">p</a><a href="/de/">de</a><a href="/@someuser">u</a><a href="/founders">f</a>'
             '<div><span>0</span> M+ projects</div><div>Saved €130K</div><div>users love it</div>'
             '<div>2500+</div><div>ARR tracked</div><p>Over <b>3M+</b> projects built</p>')
    n = growth.read_page(noisy, "acme.com")
    check("handles differing only in case count once", n["social"]["X"] == ["Acme"])
    check("escaped backslash is not part of a handle", n["social"]["LinkedIn"] == ["company/acme-inc"])
    check("legal pages and profile pages are left out", n["sections"]["paths"] == ["de", "founders"])
    check("a locale prefix is the international play", growth.play_of("de") == "international")
    check("persona page play", growth.play_of("founders") == "personas")
    check("zero counters and cross-element joins are dropped", n["stated_numbers"] == ["3M+ projects"])
    check("a tag removal is reported on the timeline",
          any(e["event"] == "Google Analytics 4 no longer seen" for e in growth.build_timeline(
              [{"date": "2024-01-01", "page": a}, {"date": "2024-06-01", "page": n}])["timeline"]))
    check("title change is reported", ("2025-06-01", "positioning", "homepage title changed") in events)
    check("timeline is in date order", [e["date"] for e in built["timeline"]] == sorted(e["date"] for e in built["timeline"]))
    print("all checks passed")


if __name__ == "__main__":
    main()
