# Copyright (c) 2026 The Wayfinder Trust - Jonathan Luethke
# All Rights Reserved. Proprietary and Confidential.
"""Offline checks for prospecting.py. No network. Run: python test_prospecting.py"""
from bs4 import BeautifulSoup

import prospecting


# ---- Overpass elements for the parsing and chain-dropping checks ----------
ELEMENTS = [
    {"type": "node", "id": 1, "tags": {
        "name": "Hoboken Bakery", "shop": "bakery",
        "website": "hobokenbakery.com", "phone": "201-555-1000",
        "addr:housenumber": "100", "addr:street": "Washington St",
        "addr:city": "Hoboken", "addr:state": "NJ"}},
    {"type": "node", "id": 2, "tags": {  # a chain: dropped by its brand tag
        "name": "Starbucks", "shop": "coffee", "brand": "Starbucks",
        "brand:wikidata": "Q37158", "website": "https://www.starbucks.com"}},
    {"type": "node", "id": 3, "tags": {  # not a business
        "name": "City Hall", "amenity": "townhall", "website": "hoboken.gov"}},
    {"type": "node", "id": 4, "tags": {  # a business with no website
        "name": "Joe Dentist", "healthcare": "dentist", "phone": "201-555-2000"}},
    {"type": "way", "id": 5, "tags": {
        "name": "Hoboken Cafe", "amenity": "cafe", "website": "hobokencafe.com"}},
    {"type": "node", "id": 6, "tags": {  # a social link is not a site to audit
        "name": "Sal Barber", "shop": "hairdresser",
        "website": "https://facebook.com/salbarber", "phone": "201-555-3000"}},
]


# ---- HTML pages for the finding grading checks ----------------------------
CLEAN = """<!doctype html><html lang="en"><head>
<title>Hoboken Bakery - Fresh Bread Daily</title>
<meta name="description" content="A family bakery in Hoboken baking fresh bread and pastry every morning.">
<meta name="viewport" content="width=device-width, initial-scale=1">
<script type="application/ld+json">{"@type":"LocalBusiness","name":"Hoboken Bakery"}</script>
</head><body>
<h1>Fresh bread, baked daily</h1>
<p>%s</p>
<address>100 Washington St, Hoboken NJ</address>
<a href="tel:2015551000">Call us</a>
<form><input name="email"><button>Send</button></form>
</body></html>""" % (("The Hoboken Bakery has baked fresh sourdough rye and "
                      "whole wheat loaves for the neighborhood for thirty years. ") * 12)

NO_TITLE = "<html><head></head><body><p>hello there</p></body></html>"

NO_HTTPS_AND_NO_TITLE = NO_TITLE  # graded with https=False to test priority

LESSER_ONLY = """<!doctype html><html lang="en"><head>
<title>Hoboken Bakery - Fresh Bread Daily</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script type="application/ld+json">{"@type":"LocalBusiness"}</script>
</head><body>
<h1>Fresh bread, baked daily</h1>
<p>%s</p>
<a href="tel:2015551000">Call us</a>
</body></html>""" % (("We bake fresh bread every single morning here in town. ") * 30)


def check(name, cond):
    if not cond:
        raise AssertionError(name)
    print("ok  " + name)


class FakeResp:
    """Just enough of an httpx response for sitefetch.unreadable and _assess."""
    def __init__(self, status, url):
        self.status_code = status
        self.url = url
        self.headers = {"server": "cloudflare"}


def signals(html, https=True, response_ms=120, keyword=None, final_url="https://x/"):
    soup = BeautifulSoup(html, "html.parser")
    return prospecting._extract_signals(soup, html, final_url, https, response_ms, keyword)


def main():
    # --- find_businesses parsing and chain dropping -----------------------
    built = prospecting._build_rows(ELEMENTS, require_website=True)
    names = [r["name"] for r in built["rows"]]
    check("chain is dropped by its brand tag", "Starbucks" not in names)
    check("non-business is dropped", "City Hall" not in names)
    check("a social-only website is not kept", "Sal Barber" not in names)
    check("business with no website is excluded when a website is required",
          "Joe Dentist" not in names)
    check("auditable businesses are kept", set(names) == {"Hoboken Bakery", "Hoboken Cafe"})
    check("found counts every real independent business",
          built["found"] == 4)  # bakery, dentist, cafe, barber (chain + city hall out)
    check("with_website count", built["with_website"] == 2)  # bakery + cafe; barber's is social
    check("with_phone count", built["with_phone"] == 3)  # bakery, dentist, barber
    bakery = next(r for r in built["rows"] if r["name"] == "Hoboken Bakery")
    check("address is assembled", bakery["address"] == "100 Washington St, Hoboken, NJ")
    check("category is read from the tag", bakery["category"] == "shop=bakery")
    check("osm id is carried", bakery["osm"] == "node/1")

    chained = prospecting._build_rows(ELEMENTS, include_chains=True, require_website=True)
    check("include_chains keeps the chain", "Starbucks" in [r["name"] for r in chained["rows"]])

    cat = prospecting._build_rows(ELEMENTS, category="bakery", require_website=True)
    check("category filter keeps only matching businesses",
          [r["name"] for r in cat["rows"]] == ["Hoboken Bakery"])

    # --- finding priority and grading -------------------------------------
    clean = prospecting._select_finding(signals(CLEAN))
    check("a clean page yields grade C", clean["grade"] == "C")
    check("a clean page states no finding", clean["finding"] == "no finding")
    check("a clean page invents no evidence", clean["evidence"] is None)

    nt = prospecting._select_finding(signals(NO_TITLE))
    check("a missing title is grade A", nt["grade"] == "A")
    check("a missing title is a ranking factor", nt["ranking_factor"] is True)
    check("the missing-title finding is a short noun phrase", nt["finding"] == "no page title")
    check("the finding carries its evidence", "<title>" in nt["evidence"])

    both = prospecting._select_finding(signals(NO_HTTPS_AND_NO_TITLE, https=False))
    check("https outranks the missing title in the fixed priority",
          both["key"] == "no_https")

    lesser = prospecting._select_finding(signals(LESSER_ONLY))
    check("a page with only a lesser defect is grade B", lesser["grade"] == "B")
    check("the lesser finding is not a ranking factor", lesser["ranking_factor"] is False)
    check("the lesser finding rests on evidence", bool(lesser["evidence"]))

    kw = prospecting._select_finding(signals(CLEAN, keyword="gluten free"), keyword="gluten free")
    check("a keyword absent from the page is a lesser finding",
          kw["key"] == "keyword_missing" and kw["grade"] == "B")

    # --- a wall response must be readable False, never a finding -----------
    err = prospecting.sitefetch.unreadable(FakeResp(403, "https://walled.example/"))
    check("a 403 is read as unreadable", err and err.get("readable") is False and err.get("blocked"))
    walled = prospecting._assess(FakeResp(403, "https://walled.example/"), None, err,
                                 "https://walled.example")
    check("prospect_finding reports a wall as readable False", walled["readable"] is False)
    check("a walled site carries no finding", walled["finding"] is None)

    # --- opener text never claims a defect for grade C --------------------
    offer = "I help local bakeries show up on Google."
    c_opener = prospecting._opener("hobokenbakery.com", "no finding", "C", offer)
    check("a clean opener claims no defect",
          "noticed" not in c_opener and "good shape" in c_opener and offer in c_opener)
    a_opener = prospecting._opener("hobokenbakery.com", "no page title", "A", offer)
    check("a graded opener names the finding",
          "noticed no page title" in a_opener and a_opener.endswith(offer))

    # --- call_sheet sections, voice agent and CSV -------------------------
    prospects = [
        {"name": "A Bakery", "phone": "201-555-1000", "website": "a.example",
         "grade": "A", "finding": "no page title", "evidence": "no <title> element"},
        {"name": "B Cafe", "phone": "", "website": "b.example",
         "grade": "B", "finding": "no meta description", "evidence": "no meta desc"},
        {"name": "C Shop", "phone": "201-555-2000", "website": "c.example",
         "grade": "C", "finding": "no finding", "evidence": None},
        {"name": "D Diner", "phone": "201-555-4000", "website": "d.example",
         "readable": False, "error": "blocked before the page could be read"},
    ]
    sheet = prospecting.call_sheet(prospects, offer, your_name="Sam", format="csv")
    check("a finding with a phone is callable", [r["business"] for r in sheet["callable"]] == ["A Bakery"])
    check("a finding with no phone is no_phone", [r["business"] for r in sheet["no_phone"]] == ["B Cafe"])
    check("a clean site is in the clean section", [r["business"] for r in sheet["clean"]] == ["C Shop"])
    check("a blocked site is in the unreadable section",
          [r["business"] for r in sheet["unreadable"]] == ["D Diner"])
    check("voice_agent repeats the callable rows", len(sheet["voice_agent"]) == 1)
    check("the clean row's opener claims no defect",
          "good shape" in sheet["clean"][0]["opener"] and "noticed" not in sheet["clean"][0]["opener"])
    check("the callable row's opener names its finding",
          "noticed no page title" in sheet["callable"][0]["opener"])
    csv_text = sheet["csv"]
    check("csv has the header row",
          csv_text.splitlines()[0] == "business,phone,website,grade,finding,evidence,opener")
    check("csv carries every row", len(csv_text.strip().splitlines()) == 1 + len(prospects))
    check("csv does not leak a defect claim into the clean row",
          "C Shop" in csv_text and "good shape" in csv_text)

    print("all checks passed")


if __name__ == "__main__":
    main()
