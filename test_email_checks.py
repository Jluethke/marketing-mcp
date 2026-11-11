# Copyright (c) 2026 The Wayfinder Trust - Jonathan Luethke
# All Rights Reserved. Proprietary and Confidential.
"""Offline checks for email_checks.py. No network. Run: python test_email_checks.py"""
import datetime

import email_checks as ec

DMARC_XML = """<?xml version="1.0" encoding="UTF-8" ?>
<feedback>
  <report_metadata>
    <org_name>google.com</org_name>
    <email>noreply-dmarc-support@google.com</email>
    <report_id>fixture-1</report_id>
    <date_range><begin>1785000000</begin><end>1785086400</end></date_range>
  </report_metadata>
  <policy_published>
    <domain>example.com</domain><adkim>r</adkim><aspf>r</aspf>
    <p>reject</p><sp>reject</sp><pct>100</pct>
  </policy_published>
  <record>
    <row>
      <source_ip>40.107.1.1</source_ip><count>12</count>
      <policy_evaluated><disposition>none</disposition><dkim>pass</dkim><spf>pass</spf></policy_evaluated>
    </row>
    <identifiers><header_from>example.com</header_from></identifiers>
    <auth_results>
      <dkim><domain>example.com</domain><result>pass</result></dkim>
      <spf><domain>example.com</domain><result>pass</result></spf>
    </auth_results>
  </record>
  <record>
    <row>
      <source_ip>203.0.113.9</source_ip><count>3</count>
      <policy_evaluated><disposition>quarantine</disposition><dkim>fail</dkim><spf>fail</spf></policy_evaluated>
    </row>
    <identifiers><header_from>example.com</header_from></identifiers>
    <auth_results>
      <dkim><domain>example.com</domain><result>fail</result></dkim>
      <spf><domain>example.com</domain><result>softfail</result></spf>
    </auth_results>
  </record>
</feedback>
"""


def check(name, cond):
    if not cond:
        raise AssertionError(name)
    print("ok  " + name)


def test_spf():
    spf = ec.parse_spf(["v=spf1 include:_spf.google.com include:mailgun.org a:mail.x.com ~all"])
    check("SPF present and single", spf["present"] and spf["single_record"])
    check("SPF all-qualifier read", spf["all_qualifier"] == "~")
    check("SPF counts include/a lookups", spf["lookup_count"] == 3 and not spf["over_lookup_limit"])
    check("SPF mechanisms listed", spf["mechanisms"][0] == "include:_spf.google.com")

    over = ec.parse_spf(["v=spf1 " + " ".join("include:x%d.com" % i for i in range(11)) + " -all"])
    check("SPF over the 10-lookup limit is flagged",
          over["lookup_count"] == 11 and over["over_lookup_limit"] and over["all_qualifier"] == "-")

    two = ec.parse_spf(["v=spf1 include:a.com -all", "v=spf1 include:b.com -all"])
    check("two SPF records are not single", two["present"] and not two["single_record"]
          and two["record_count"] == 2)
    check("no SPF record", ec.parse_spf(["some other txt"])["present"] is False)


def test_dmarc_record():
    d = ec.parse_dmarc("v=DMARC1; p=reject; sp=quarantine; pct=50; "
                       "rua=mailto:agg@x.com; adkim=s; aspf=r")
    check("DMARC policy read", d["p"] == "reject" and d["sp"] == "quarantine")
    check("DMARC pct and rua read", d["pct"] == 50 and d["rua"] == ["mailto:agg@x.com"])
    check("DMARC alignment modes read", d["adkim"] == "s" and d["aspf"] == "r")
    d2 = ec.parse_dmarc("v=DMARC1; p=none; rua=mailto:a@b.com")
    check("DMARC pct defaults to 100 when unset", d2["pct"] == 100)
    check("no DMARC record", ec.parse_dmarc("not a dmarc record")["present"] is False)


def test_dkim():
    good = ec.parse_dkim("v=DKIM1; k=rsa; p=" + "A" * 392)
    check("DKIM 2048-bit key estimated", good["present"] and good["key_length_est"] == 2048
          and not good["weak"])
    weak = ec.parse_dkim("v=DKIM1; k=rsa; p=" + "A" * 180)
    check("DKIM weak key flagged", weak["key_length_est"] == 768 and weak["weak"])
    revoked = ec.parse_dkim("v=DKIM1; k=rsa; p=")
    check("DKIM revoked key (empty p)", revoked["present"] and revoked["revoked"])


def test_dmarc_aggregate():
    rep = ec.parse_dmarc_aggregate(DMARC_XML)
    check("aggregate org and policy", rep["org"] == "google.com" and rep["policy"]["p"] == "reject")
    check("aggregate rows parsed", len(rep["rows"]) == 2 and rep["rows"][0]["source_ip"] == "40.107.1.1")
    check("aggregate row alignment", rep["rows"][0]["aligned"] and not rep["rows"][1]["aligned"])
    check("aggregate raw auth results", rep["rows"][1]["spf_auth"] == "softfail")
    check("aggregate totals", rep["totals"]["messages"] == 15 and rep["totals"]["passing"] == 12)
    check("aggregate dispositions", rep["totals"]["dispositions"].get("quarantine") == 3)
    check("aggregate pass rate", rep["pass_rate"] == 0.8)
    check("aggregate date range to UTC", rep["date_range"]["begin_utc"].startswith("20"))


def test_classify_replies():
    msgs = [
        {"from": "mailer-daemon@mail.acme.com", "subject": "Undeliverable: hello",
         "body": "550 5.1.1 <jane@acme.com> user unknown; recipient not found"},
        {"from": "postmaster@acme.com", "subject": "Delivery Status Notification (Failure)",
         "body": "550 5.7.1 Message rejected as spam due to sender reputation"},
        {"from": "mailer-daemon@acme.com", "subject": "Delivery Status Notification (Failure)",
         "body": "452 4.2.2 Mailbox is full, recipient over quota"},
        {"from": "bob@acme.com", "subject": "Automatic reply: out of office",
         "body": "I am out of office returning July 15. For urgent matters contact Jane jane@acme.com"},
        {"from": "john@oldco.com", "subject": "Re: your note",
         "body": "I have left the company. Please contact Sarah Smith at sarah@newco.com going forward."},
        {"from": "lead@prospect.com", "subject": "Re: quick question",
         "body": "Please unsubscribe me from your list, not interested."},
        {"from": "support@vendor.com", "subject": "Thank you for contacting support",
         "body": "This is an automated response. Your ticket number is 12345."},
        {"from": "cfo@target.com", "subject": "Re: proposal",
         "body": "Thanks for the note. This looks interesting, can we talk Thursday?"},
    ]
    res = ec.classify_replies(msgs)
    labels = [m["label"] for m in res["messages"]]
    check("dead-address bounce", labels[0] == "bounce_dead_address"
          and res["messages"][0]["fields"]["smtp_code"] == "5.1.1")
    check("policy-block bounce", labels[1] == "bounce_policy_block")
    check("mailbox-full bounce", labels[2] == "bounce_mailbox_full_or_temp"
          and res["messages"][2]["fields"]["smtp_code"] == "4.2.2")
    check("out of office with return date", labels[3] == "out_of_office"
          and res["messages"][3]["fields"]["return_date"] == "July 15")
    check("address change with new contact", labels[4] == "address_change"
          and res["messages"][4]["fields"]["new_address"] == "sarah@newco.com"
          and res["messages"][4]["fields"]["replacement_contact"] == "Sarah Smith")
    check("unsubscribe request", labels[5] == "unsubscribe_request")
    check("auto-reply other", labels[6] == "auto_reply_other")
    check("human reply", labels[7] == "human_reply")
    check("counts total to message count", sum(res["counts"].values()) == 8 and res["count"] == 8)


def _hour(iso):
    return datetime.datetime.fromisoformat(iso).astimezone(datetime.timezone.utc).hour


def test_send_window():
    recips = [
        {"email": "a@ny.com", "timezone": "America/New_York"},
        {"email": "b@la.com", "timezone": "America/Los_Angeles"},
    ]
    winter = ec.send_window(recips, local_hour=10, start_date="2025-01-06")
    by_email = {r["email"]: r for b in winter["batches"] for r in b["recipients"]}
    check("winter send is the next Tuesday", by_email["a@ny.com"]["local_time"].startswith("2025-01-07T10:00"))
    check("winter NY 10:00 EST is 15:00 UTC", _hour(by_email["a@ny.com"]["utc_time"]) == 15)
    check("winter LA 10:00 PST is 18:00 UTC", _hour(by_email["b@la.com"]["utc_time"]) == 18)
    check("two zones make two batches", winter["batch_count"] == 2)

    summer = ec.send_window(recips, local_hour=10, start_date="2025-07-07")
    s_email = {r["email"]: r for b in summer["batches"] for r in b["recipients"]}
    check("summer send is the next Tuesday", s_email["a@ny.com"]["local_time"].startswith("2025-07-08T10:00"))
    check("DST: summer NY 10:00 EDT is 14:00 UTC", _hour(s_email["a@ny.com"]["utc_time"]) == 14)
    check("DST: summer LA 10:00 PDT is 17:00 UTC", _hour(s_email["b@la.com"]["utc_time"]) == 17)

    mapped = ec.send_window([
        {"email": "s@ca.com", "state": "CA"},
        {"email": "d@de.com", "country": "Germany"},
        {"email": "x@nowhere.com", "country": "Atlantis"},
    ], start_date="2025-01-06")
    zones = {r["email"]: r["timezone"] for b in mapped["batches"] for r in b["recipients"]}
    check("US state maps to a zone", zones["s@ca.com"] == "America/Los_Angeles")
    check("country maps to a zone", zones["d@de.com"] == "Europe/Berlin")
    check("unknown place is unassigned",
          mapped["unassigned"] == ["x@nowhere.com"] and mapped["unassigned_count"] == 1)

    many = ec.send_window([{"email": "u%d@ny.com" % i, "timezone": "America/New_York"}
                           for i in range(3)], start_date="2025-01-06", batch_size=2)
    check("batch_size caps a batch", many["batch_count"] == 2
          and [b["size"] for b in many["batches"]] == [2, 1])


def test_address_parse():
    check("role address flagged", ec._parse_address("info@acme.com")["role_address"])
    check("free-mail flagged", ec._parse_address("jane@gmail.com")["free_mail"])
    check("disposable flagged", ec._parse_address("x@mailinator.com")["disposable"])
    check("bad syntax rejected", ec._parse_address("not-an-email")["valid_syntax"] is False)


def main():
    test_spf()
    test_dmarc_record()
    test_dkim()
    test_dmarc_aggregate()
    test_classify_replies()
    test_send_window()
    test_address_parse()
    print("all checks passed")


if __name__ == "__main__":
    main()
