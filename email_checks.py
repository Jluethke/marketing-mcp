# Copyright (c) 2026 The Wayfinder Trust - Jonathan Luethke
# All Rights Reserved. Proprietary and Confidential.
"""Email deliverability checks and reply triage for outbound marketing.

This module never sends mail. It checks what a receiver would do with it and
plans when to send it. Six readings, all with the parsing split from the
network so every parser is testable offline:

  email_auth_check   SPF, DMARC and DKIM for a domain, read over DNS-over-HTTPS,
                     with a fixes list. Unsigned mail is routinely dropped as
                     spam by corporate filters, so this is the first thing to run.
  verify_email       one address: syntax, MX, role/free/disposable flags, and an
                     optional SMTP RCPT probe (catch-all aware) that never sends.
  dmarc_report       parse a DMARC aggregate report (XML, or a .gz/.zip path)
                     into per-source-IP rows and a pass rate.
  classify_replies   label inbound replies: bounces (dead / policy / full),
                     out-of-office, address change, unsubscribe, auto-reply, human.
  send_window        next send time per recipient at a local hour on allowed
                     weekdays, grouped into batches by UTC send time.

The DNS and SMTP calls use httpx and the standard library only; no new
dependency is introduced.
"""
from __future__ import annotations

import base64
import datetime
import gzip
import io
import re
import zipfile

# ---- DNS over HTTPS -------------------------------------------------------
# Two public JSON resolvers. Cloudflare first, Google as the fallback, so a
# single resolver being unreachable does not fail the check.
_DOH = ("https://cloudflare-dns.com/dns-query", "https://dns.google/resolve")


def _doh_query(name: str, rtype: str) -> list[dict]:
    """One DNS-over-HTTPS JSON query. Returns the Answer records (each a dict
    with 'type' and 'data'), or [] when neither resolver answers."""
    import httpx
    for url in _DOH:
        try:
            r = httpx.get(url, params={"name": name, "type": rtype},
                          headers={"accept": "application/dns-json"}, timeout=10.0)
            if r.status_code != 200:
                continue
            data = r.json()
        except Exception:  # noqa: BLE001
            continue
        if isinstance(data, dict):
            return data.get("Answer", []) or []
    return []


def _clean_txt(data: str) -> str:
    """A DoH TXT record arrives quoted, and a long one is split into several
    quoted chunks: strip the quotes and join the chunks."""
    parts = re.findall(r'"((?:[^"\\]|\\.)*)"', data)
    if parts:
        return "".join(p.replace('\\"', '"').replace("\\\\", "\\") for p in parts)
    return data.strip().strip('"')


def dns_txt(domain: str) -> list[str]:
    """TXT records for a name, de-quoted. Network call."""
    return [_clean_txt(a.get("data", "")) for a in _doh_query(domain, "TXT")
            if a.get("type") == 16]


def dns_mx(domain: str) -> list[dict]:
    """MX records for a domain as [{'preference', 'exchange'}], sorted by
    preference (lowest first). Network call."""
    out = []
    for a in _doh_query(domain, "MX"):
        if a.get("type") != 15:
            continue
        d = (a.get("data") or "").strip()
        m = re.match(r"(\d+)\s+(.+)", d)
        if m:
            out.append({"preference": int(m.group(1)),
                        "exchange": m.group(2).rstrip(".").lower()})
    out.sort(key=lambda x: x["preference"])
    return out


def _dns_a(domain: str) -> list[str]:
    return [a.get("data", "") for a in _doh_query(domain, "A") if a.get("type") == 1]


# ---- SPF / DMARC / DKIM parsing (pure) ------------------------------------

# SPF mechanisms that each cost a DNS lookup. SPF caps the total at 10; past
# that, receivers return permerror and the record is ignored.
_SPF_LOOKUP_MECHANISMS = ("include", "a", "mx", "ptr", "exists", "redirect")


def parse_spf(txt_records: list[str]) -> dict:
    """Read the SPF record out of a domain's TXT records.

    Reports whether exactly one SPF record exists (two is a permerror), the
    mechanisms, the all-qualifier (-all hard fail, ~all soft fail, ?all/+all
    weak), and an estimate of the DNS lookups the record triggers against the
    limit of 10.
    """
    spfs = [t for t in txt_records if t.lower().startswith("v=spf1")]
    present = bool(spfs)
    record = spfs[0] if spfs else None
    mechanisms: list[str] = []
    all_qualifier = None
    lookups = 0
    if record:
        for tok in record.split()[1:]:
            mechanisms.append(tok)
            low = tok.lower()
            m = re.match(r"^([+\-~?]?)all$", low)
            if m:
                all_qualifier = m.group(1) or "+"
                continue
            name = re.sub(r"^[+\-~?]", "", low).split(":")[0].split("=")[0]
            if name in _SPF_LOOKUP_MECHANISMS:
                lookups += 1
    return {
        "present": present,
        "single_record": len(spfs) == 1,
        "record_count": len(spfs),
        "record": record,
        "mechanisms": mechanisms,
        "all_qualifier": all_qualifier,
        "lookup_count": lookups,
        "over_lookup_limit": lookups > 10,
    }


def parse_dmarc(records) -> dict:
    """Read a DMARC record (a TXT at _dmarc.<domain>). Accepts one string or a
    list. Reports the policy (p), subdomain policy (sp), pct, the report
    addresses (rua/ruf), and the alignment modes (adkim/aspf; 'r' relaxed is
    the default when unset)."""
    if isinstance(records, str):
        records = [records]
    dmarcs = [t for t in records if t.lower().startswith("v=dmarc1")]
    present = bool(dmarcs)
    record = dmarcs[0] if dmarcs else None
    tags: dict[str, str] = {}
    if record:
        for part in record.split(";"):
            part = part.strip()
            if "=" in part:
                k, v = part.split("=", 1)
                tags[k.strip().lower()] = v.strip()
    pct_raw = tags.get("pct")
    try:
        pct = int(pct_raw) if pct_raw is not None else (100 if present else None)
    except ValueError:
        pct = None
    return {
        "present": present,
        "record": record,
        "p": tags.get("p"),
        "sp": tags.get("sp"),
        "pct": pct,
        "rua": [a.strip() for a in tags.get("rua", "").split(",") if a.strip()],
        "ruf": [a.strip() for a in tags.get("ruf", "").split(",") if a.strip()],
        "adkim": tags.get("adkim", "r") if present else None,
        "aspf": tags.get("aspf", "r") if present else None,
    }


def _estimate_key_bits(p_b64: str):
    """Estimate an RSA key length from the base64 public key in a DKIM record,
    snapping to the nearest common size. None when the key cannot be decoded."""
    try:
        der = base64.b64decode(p_b64 + "=" * (-len(p_b64) % 4))
    except Exception:  # noqa: BLE001
        return None
    bits = (len(der) - 38) * 8  # SubjectPublicKeyInfo overhead is about 38 bytes
    for common in (512, 768, 1024, 2048, 3072, 4096):
        if abs(bits - common) <= 160:
            return common
    return max(0, bits)


def parse_dkim(record: str) -> dict:
    """Read a DKIM public-key record. Reports the key type (k=, default rsa),
    an estimated key length, and whether the key has been revoked (empty p=).
    A key under 1024 bits is weak and may be rejected."""
    present = bool(record and "p=" in record)
    tags: dict[str, str] = {}
    for part in (record or "").split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            tags[k.strip().lower()] = v.strip()
    p_val = tags.get("p", "")
    key_type = tags.get("k", "rsa") if present else None
    bits = _estimate_key_bits(p_val) if (present and p_val and key_type == "rsa") else None
    return {
        "present": present,
        "key_type": key_type,
        "key_length_est": bits,
        "revoked": present and not p_val,
        "weak": bool(bits and bits < 1024),
    }


# Selectors tried when the caller names none. The first group is common across
# self-hosted and Google/Microsoft senders; the rest are provider defaults.
_COMMON_DKIM_SELECTORS = ("default", "google", "selector1", "selector2", "k1", "k2",
                          "s1", "s2", "mail", "dkim", "smtp", "mandrill",
                          "everlytickey1", "zoho", "protonmail")


def email_auth_check(domain: str, dkim_selectors: list[str] | None = None) -> dict:
    """Check SPF, DMARC, DKIM and MX for a sending domain, with a fixes list.

    Reads TXT and MX records over DNS-over-HTTPS. DKIM is probed at the given
    selectors, else a list of common ones. Unsigned, unaligned mail is routinely
    rejected or filed as spam by corporate mail filters, so a domain that sends
    outreach needs SPF, a DMARC policy, and at least one DKIM selector in place.
    """
    domain = (domain or "").strip().lower().rstrip(".")
    if not domain or "." not in domain:
        return {"error": "give a domain such as example.com"}

    spf = parse_spf(dns_txt(domain))
    dmarc = parse_dmarc(dns_txt("_dmarc." + domain))
    mx = dns_mx(domain)

    selectors = list(dkim_selectors) if dkim_selectors else list(_COMMON_DKIM_SELECTORS)
    dkim_found = []
    for sel in selectors:
        recs = dns_txt("%s._domainkey.%s" % (sel, domain))
        rec = next((t for t in recs if "v=dkim1" in t.lower() or "p=" in t), None)
        if rec:
            d = parse_dkim(rec)
            d["selector"] = sel
            dkim_found.append(d)
    # A key with an empty p= is revoked (example.com publishes a wildcard null
    # key to say nothing signs there), so it does not count as a usable signer.
    dkim_usable = [d for d in dkim_found if not d["revoked"]]

    fixes = []
    if not spf["present"]:
        fixes.append("No SPF record. Publish a TXT record 'v=spf1 include:<your esp> -all' "
                     "so receivers can confirm who may send for this domain.")
    else:
        if not spf["single_record"]:
            fixes.append("%d SPF records found; there must be exactly one, or receivers "
                         "return permerror and ignore SPF entirely." % spf["record_count"])
        if spf["all_qualifier"] in ("+", "?"):
            fixes.append("SPF ends in '%sall', which does not fail forged senders. Use "
                         "'-all' (or '~all' while testing)." % spf["all_qualifier"])
        if spf["over_lookup_limit"]:
            fixes.append("SPF triggers about %d DNS lookups; the limit is 10, past which "
                         "SPF fails. Flatten includes." % spf["lookup_count"])
    if not dmarc["present"]:
        fixes.append("No DMARC record. Publish a TXT record at _dmarc.%s starting "
                     "'v=DMARC1; p=none; rua=mailto:...' to begin monitoring, then raise "
                     "p to quarantine and reject." % domain)
    elif dmarc["p"] in (None, "none"):
        fixes.append("DMARC policy is p=none, which only monitors. Once SPF and DKIM pass "
                     "for real mail, move to p=quarantine then p=reject.")
    elif not dmarc["rua"]:
        fixes.append("DMARC has no rua= address, so no aggregate reports are sent. Add "
                     "rua=mailto:... to see how receivers treat your mail.")
    if not dkim_usable:
        fixes.append("No usable DKIM key found at the selectors tried (any records present "
                     "are revoked null keys). Unsigned mail is routinely rejected as spam by "
                     "corporate filters; enable DKIM signing at your sending platform and "
                     "publish its selector.")
    elif any(d["weak"] for d in dkim_usable):
        fixes.append("A DKIM key is weak (under 1024 bits); rotate to a 2048-bit key.")
    if not mx:
        fixes.append("No MX record, so this domain cannot receive mail (and replies and "
                     "bounces will not arrive).")

    return {
        "domain": domain,
        "spf": spf,
        "dmarc": dmarc,
        "dkim": {"selectors_tried": selectors, "found": dkim_found,
                 "usable": dkim_usable, "any_found": bool(dkim_found),
                 "any_usable": bool(dkim_usable)},
        "mx": {"present": bool(mx), "hosts": mx},
        "fixes": fixes,
        "summary": {"spf": spf["present"], "dmarc": dmarc["present"],
                    "dkim": bool(dkim_usable), "mx": bool(mx),
                    "unsigned_mail_warning": not dkim_usable},
    }


# ---- single-address verification ------------------------------------------

_ADDR_RE = re.compile(r"^[A-Za-z0-9!#$%&'*+/=?^_`{|}~.\-]+@([A-Za-z0-9.\-]+\.[A-Za-z]{2,})$")
_ROLE_LOCALPARTS = {"info", "sales", "support", "admin", "contact", "help", "hello",
                    "office", "team", "marketing", "billing", "accounts", "hr",
                    "jobs", "careers", "press", "media", "noreply", "no-reply",
                    "postmaster", "webmaster", "abuse", "security", "privacy",
                    "enquiries", "inquiries", "service", "orders", "newsletter"}
_FREE_DOMAINS = {"gmail.com", "googlemail.com", "yahoo.com", "ymail.com", "hotmail.com",
                 "outlook.com", "live.com", "msn.com", "aol.com", "icloud.com",
                 "me.com", "mac.com", "proton.me", "protonmail.com", "gmx.com",
                 "mail.com", "zoho.com", "yandex.com", "pm.me"}
_DISPOSABLE_DOMAINS = {"mailinator.com", "guerrillamail.com", "10minutemail.com",
                       "tempmail.com", "temp-mail.org", "throwawaymail.com",
                       "yopmail.com", "trashmail.com", "getnada.com", "sharklasers.com",
                       "dispostable.com", "maildrop.cc", "mailnesia.com", "fakeinbox.com",
                       "emailondeck.com", "mohmal.com", "spamgourmet.com"}


def _parse_address(address: str) -> dict:
    """Syntax plus the role / free-mail / disposable flags. No network."""
    addr = (address or "").strip()
    m = _ADDR_RE.match(addr)
    if not m:
        return {"address": addr, "valid_syntax": False, "domain": None,
                "local_part": None, "role_address": False, "free_mail": False,
                "disposable": False}
    local, domain = addr.rsplit("@", 1)
    domain = domain.lower()
    return {
        "address": addr,
        "valid_syntax": True,
        "domain": domain,
        "local_part": local,
        "role_address": local.lower() in _ROLE_LOCALPARTS,
        "free_mail": domain in _FREE_DOMAINS,
        "disposable": domain in _DISPOSABLE_DOMAINS,
    }


def _smtp_probe(address: str, mx_host: str, timeout: float = 10.0) -> dict:
    """RCPT-TO probe against one MX. Never sends DATA, so no mail goes out.
    Probes a random local-part first to detect a catch-all. Returns the verdict
    and the server's code and text."""
    import random
    import smtplib
    import socket
    import string
    domain = address.rsplit("@", 1)[1]
    bogus = "".join(random.choices(string.ascii_lowercase, k=16)) + "@" + domain
    smtp = None
    try:
        smtp = smtplib.SMTP(timeout=timeout)
        smtp.connect(mx_host, 25)
        smtp.ehlo_or_helo_if_needed()
        smtp.mail("")  # null sender, the standard probe envelope
        cb, mb = smtp.rcpt(bogus)
        if cb in (250, 251):
            return {"result": "catch_all", "code": cb,
                    "message": _decode(mb),
                    "note": "the domain accepts any address, so the probe cannot "
                            "confirm this mailbox exists."}
        ca, ma = smtp.rcpt(address)
        if ca in (250, 251):
            return {"result": "accepted", "code": ca, "message": _decode(ma)}
        if ca in (550, 551, 553, 554, 501, 505):
            return {"result": "rejected", "code": ca, "message": _decode(ma)}
        return {"result": "unknown", "code": ca, "message": _decode(ma)}
    except (socket.timeout, ConnectionRefusedError, OSError) as e:
        return {"result": "unknown", "code": None,
                "message": "%s: %s" % (type(e).__name__, str(e)[:120]),
                "note": "outbound port 25 is likely blocked on this network, so the "
                        "probe could not run."}
    except smtplib.SMTPException as e:
        return {"result": "unknown", "code": None, "message": str(e)[:160]}
    finally:
        if smtp is not None:
            try:
                smtp.quit()
            except Exception:  # noqa: BLE001
                pass


def _decode(msg) -> str:
    if isinstance(msg, bytes):
        return msg.decode("utf-8", "replace").strip()
    return str(msg).strip()


def verify_email(address: str, smtp_probe: bool = False) -> dict:
    """Verify one email address without sending to it.

    Checks syntax, that the domain has MX records (or an A record as a fallback),
    and flags role (info@, sales@ ...), free-mail and disposable-domain
    addresses. With smtp_probe=True it opens one SMTP connection to the top MX,
    runs the RCPT-TO probe (catch-all aware) and reports accepted / rejected /
    catch_all / unknown with the server's code and text; it never sends DATA.

    Note: many networks block outbound port 25, in which case the probe result
    is 'unknown'. Pattern-guessed addresses bounced at about a quarter in
    practice, so verify before sending rather than guessing.
    """
    info = _parse_address(address)
    out = dict(info)
    if not info["valid_syntax"]:
        out["deliverable"] = False
        out["reason"] = "address does not parse as a valid email"
        return out
    mx = dns_mx(info["domain"])
    a_fallback = [] if mx else _dns_a(info["domain"])
    out["mx"] = mx
    out["mx_present"] = bool(mx)
    out["a_fallback"] = bool(a_fallback)
    if not mx and not a_fallback:
        out["deliverable"] = False
        out["reason"] = "the domain has no MX and no A record, so it cannot receive mail"
        return out
    out["deliverable"] = None  # not determined without a probe
    if smtp_probe:
        host = mx[0]["exchange"] if mx else info["domain"]
        probe = _smtp_probe(address, host)
        out["smtp_probe"] = probe
        if probe["result"] == "accepted":
            out["deliverable"] = True
        elif probe["result"] == "rejected":
            out["deliverable"] = False
    else:
        out["smtp_probe"] = {"result": "not_run",
                             "note": "pass smtp_probe=True to probe the mailbox; the "
                                     "probe needs outbound port 25."}
    return out


# ---- DMARC aggregate report parsing ---------------------------------------

def _ts_to_iso(ts: str):
    try:
        return datetime.datetime.fromtimestamp(int(ts), datetime.timezone.utc).isoformat()
    except (ValueError, TypeError, OSError):
        return None


def _xml_text(node, path, default=""):
    el = node.find(path)
    return (el.text or "").strip() if el is not None and el.text else default


def parse_dmarc_aggregate(xml_bytes) -> dict:
    """Parse one DMARC aggregate report (XML bytes or str) into org, date range,
    policy, per-source-IP rows (count, disposition, dkim/spf alignment and raw
    authentication results), totals and the share that passed DMARC. A row
    passes when SPF or DKIM aligned. Raises on malformed XML."""
    import xml.etree.ElementTree as ET
    if isinstance(xml_bytes, str):
        xml_bytes = xml_bytes.encode("utf-8")
    root = ET.fromstring(xml_bytes)
    meta = {
        "org": _xml_text(root, "report_metadata/org_name", "unknown"),
        "report_id": _xml_text(root, "report_metadata/report_id"),
    }
    begin = _xml_text(root, "report_metadata/date_range/begin")
    end = _xml_text(root, "report_metadata/date_range/end")
    policy = {
        "domain": _xml_text(root, "policy_published/domain"),
        "p": _xml_text(root, "policy_published/p"),
        "sp": _xml_text(root, "policy_published/sp"),
        "pct": _xml_text(root, "policy_published/pct"),
        "adkim": _xml_text(root, "policy_published/adkim"),
        "aspf": _xml_text(root, "policy_published/aspf"),
    }
    rows = []
    total = passing = 0
    dispositions: dict[str, int] = {}
    for rec in root.findall("record"):
        try:
            count = int(_xml_text(rec, "row/count", "0") or 0)
        except ValueError:
            count = 0
        dkim_al = _xml_text(rec, "row/policy_evaluated/dkim", "unknown")
        spf_al = _xml_text(rec, "row/policy_evaluated/spf", "unknown")
        disp = _xml_text(rec, "row/policy_evaluated/disposition", "none") or "none"
        aligned = dkim_al == "pass" or spf_al == "pass"
        total += count
        if aligned:
            passing += count
        dispositions[disp] = dispositions.get(disp, 0) + count
        rows.append({
            "source_ip": _xml_text(rec, "row/source_ip"),
            "count": count,
            "disposition": disp,
            "dkim_aligned": dkim_al,
            "spf_aligned": spf_al,
            "dkim_auth": _xml_text(rec, "auth_results/dkim/result"),
            "spf_auth": _xml_text(rec, "auth_results/spf/result"),
            "header_from": _xml_text(rec, "identifiers/header_from"),
            "aligned": aligned,
        })
    return {
        "org": meta["org"],
        "report_id": meta["report_id"],
        "date_range": {"begin": begin, "end": end,
                       "begin_utc": _ts_to_iso(begin), "end_utc": _ts_to_iso(end)},
        "policy": policy,
        "rows": rows,
        "totals": {"messages": total, "passing": passing, "failing": total - passing,
                   "dispositions": dispositions},
        "pass_rate": round(passing / total, 4) if total else None,
    }


def dmarc_report(xml_text_or_path: str) -> dict:
    """Parse a DMARC aggregate report given as XML text, or as a path to an .xml,
    .gz or .zip file. Returns parse_dmarc_aggregate's dict (a .zip with several
    XML members is merged into one 'reports' list)."""
    s = xml_text_or_path or ""
    stripped = s.lstrip()
    if stripped.startswith("<"):
        return parse_dmarc_aggregate(s)
    low = s.lower()
    try:
        with open(s, "rb") as f:
            blob = f.read()
    except OSError as e:
        return {"error": "could not read %s: %s" % (s, e)}
    xmls: list[bytes] = []
    try:
        if low.endswith(".gz") or blob[:2] == b"\x1f\x8b":
            xmls.append(gzip.decompress(blob))
        elif low.endswith(".zip") or blob[:2] == b"PK":
            with zipfile.ZipFile(io.BytesIO(blob)) as z:
                for n in z.namelist():
                    if n.lower().endswith(".xml"):
                        xmls.append(z.read(n))
        else:
            xmls.append(blob)
    except Exception as e:  # noqa: BLE001
        return {"error": "could not unpack %s: %s" % (s, e)}
    if not xmls:
        return {"error": "no XML report found in %s" % s}
    reports = []
    for x in xmls:
        try:
            reports.append(parse_dmarc_aggregate(x))
        except Exception as e:  # noqa: BLE001
            reports.append({"error": "unparseable XML: %s" % e})
    return reports[0] if len(reports) == 1 else {"reports": reports, "count": len(reports)}


# ---- reply classification -------------------------------------------------

_NDR_SUBJECT = re.compile(
    r"undeliverable|delivery (status notification|has failed|failure)|returned mail|"
    r"mail delivery (failed|subsystem)|failure notice|returned to sender|"
    r"delivery incomplete|non[- ]?delivery", re.I)
_NDR_FROM = re.compile(r"mailer-daemon|postmaster|maildelivery|microsoftexchange|"
                       r"mail delivery (system|subsystem)", re.I)

_DEAD = re.compile(
    r"\b5\.1\.[0-9]\b|user unknown|no such user|does not exist|unknown user|"
    r"recipient (address )?rejected|mailbox (unavailable|not found)|"
    r"no such (mailbox|recipient|address)|recipient not found|address (not found|unknown)|"
    r"recipnotfound|user not found|account (?:is )?(disabled|deactivated)|"
    r"no longer accepts mail", re.I)
_FULL = re.compile(
    r"\b4\.2\.2\b|\b5\.2\.2\b|over ?quota|quota (exceeded|full)|mailbox (is )?full|"
    r"insufficient (system )?storage|exceeded storage", re.I)
_TEMP = re.compile(
    r"\b4\.\d\.\d+\b|temporar(il)?y (failure|unavailable|rejected|deferred)|try again later|"
    r"greylist|grey-?listed|deferred|resources temporarily|please retry", re.I)
_POLICY = re.compile(
    r"\b5\.7\.\d+\b|black ?list|block ?list|\bblocked\b|\bspam\b|reputation|"
    r"policy (reasons|restrictions|violation)|rejected (for|due to) policy|"
    r"message (was )?rejected|content rejected|not authori[sz]ed|refused|"
    r"prohibited|bulk mail|spamhaus|rbl\b", re.I)

_OOO_SUBJECT = re.compile(
    r"^\s*(automatic reply|auto[- ]?reply|out of office|ooo\b|away from (the )?office|"
    r"on vacation|annual leave|réponse automatique|respuesta automática|"
    r"automatische antwort|risposta automatica)", re.I)
_OOO_BODY = re.compile(
    r"out of (the )?office|on (vacation|holiday|leave|annual leave|parental leave|"
    r"maternity leave|paternity leave|sabbatical)|away from (my )?(desk|the office)|"
    r"currently (away|out)|will be back|back in the office|limited access to (my )?(e-?mail)|"
    r"returning (on|to the office)|away until", re.I)

_DEPARTED = re.compile(
    r"no longer (employed|with|at|here|works)|no longer works?|has (left|departed)|"
    r"is no longer (part of|with|employed)|left (the )?(company|organi[sz]ation|firm)|"
    r"has retired|has moved on", re.I)
_NEW_ADDR = re.compile(
    r"new (e-?mail)( address)?|e-?mail (address )?has changed|has a new e-?mail|"
    r"i(?:'| ha)ve moved to|now reachable at|can (now )?be reached at|"
    r"please update your (records|address book)|please use my new", re.I)

_UNSUB = re.compile(
    r"\bunsubscribe\b|remove me|take me off|opt(-| )?out|stop (e-?mailing|sending|contacting)|"
    r"do not (e-?mail|contact)|no longer (wish|want) to receive|please remove (me|us)|"
    r"not interested.{0,20}(remove|stop)", re.I)

_AUTO_OTHER = re.compile(
    r"this is an autom(ated|atic) (reply|response|message)|do not reply to this|"
    r"no[- ]?reply|your (message|e-?mail|request|ticket) (has been )?(received|logged)|"
    r"thank you for (contacting|your e-?mail|reaching out)|ticket (number|#|id)|"
    r"case (number|#)|we('| wi)ll (get|be) back to you|received your (message|inquiry)", re.I)

_MONTHS = ("january|february|march|april|may|june|july|august|september|october|"
           "november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec")
_RETURN_PATTERNS = [
    re.compile(r"(?:return(?:ing)?|back|until|till|through|thru)\b[^.\n]{0,40}?"
               r"\b((?:%s)[a-z]*\.?\s+\d{1,2})" % _MONTHS, re.I),
    re.compile(r"(?:return(?:ing)?|back|until|till)\b[^.\n]{0,40}?"
               r"\b(\d{1,2}\s+(?:%s)[a-z]*)" % _MONTHS, re.I),
    re.compile(r"(?:return(?:ing)?|back|until)\b[^.\n]{0,30}?(\d{1,2}/\d{1,2}(?:/\d{2,4})?)", re.I),
    re.compile(r"(?:return(?:ing)?|back|until)\b[^.\n]{0,30}?(\d{4}-\d{2}-\d{2})", re.I),
]
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def _find_return_date(text: str):
    head = text[:800]
    for pat in _RETURN_PATTERNS:
        m = pat.search(head)
        if m:
            return m.group(1).strip()
    return None


def _snippet(text: str, match: re.Match, width: int = 50) -> str:
    start = max(0, match.start() - 20)
    return re.sub(r"\s+", " ", text[start:match.start() + width]).strip()


def _extract_new_contact(text: str, sender: str):
    """A new/alternate email address and any named person, from a departure or
    address-change reply."""
    sender = (sender or "").lower()
    new = None
    for e in _EMAIL_RE.findall(text):
        el = e.lower().rstrip(".")
        if el != sender:
            new = el
            break
    name = None
    m = re.search(r"(?:contact|reach out to|reach|speak (?:to|with)|e-?mail|see|ask for)\s+"
                  r"([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)", text)
    if m:
        name = m.group(1)
    return new, name


def _classify_bounce(text: str) -> tuple:
    """Return (label, evidence match, smtp_code) for a non-delivery report."""
    code_m = re.search(r"\b[45]\.\d\.\d+\b", text)
    code = code_m.group(0) if code_m else None
    m = _FULL.search(text)
    if m:
        return "bounce_mailbox_full_or_temp", m, code
    m = _DEAD.search(text)
    if m:
        return "bounce_dead_address", m, code
    m = _POLICY.search(text)
    if m:
        return "bounce_policy_block", m, code
    m = _TEMP.search(text)
    if m:
        return "bounce_mailbox_full_or_temp", m, code
    if code:
        cls, sub = code[0], code[2]
        if cls == "4":
            return "bounce_mailbox_full_or_temp", code_m, code
        if sub == "1":
            return "bounce_dead_address", code_m, code
        return "bounce_policy_block", code_m, code
    return "bounce_dead_address", None, code


def _classify_one(msg: dict) -> dict:
    subject = str(msg.get("subject") or "")
    body = str(msg.get("body") or "")
    sender = str(msg.get("from") or "")
    headers = str(msg.get("headers") or "")
    text = subject + "\n" + body + "\n" + headers
    fields: dict = {}

    is_ndr = bool(_NDR_FROM.search(sender) or _NDR_FROM.search(headers)
                  or _NDR_SUBJECT.search(subject))
    if is_ndr:
        label, m, code = _classify_bounce(text)
        if code:
            fields["smtp_code"] = code
        rm = re.search(r"(?:to|recipient|<)\s*([A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,})", body)
        if rm:
            fields["failed_recipient"] = rm.group(1).lower()
        evidence = _snippet(text, m) if m else "non-delivery report (cause unspecified)"
        return {"label": label, "evidence": evidence, "fields": fields}

    m = _UNSUB.search(text)
    if m:
        return {"label": "unsubscribe_request", "evidence": _snippet(text, m), "fields": fields}

    m = _DEPARTED.search(text) or _NEW_ADDR.search(text)
    if m:
        new, name = _extract_new_contact(body or text, sender)
        if new:
            fields["new_address"] = new
        if name:
            fields["replacement_contact"] = name
        return {"label": "address_change", "evidence": _snippet(text, m), "fields": fields}

    m = _OOO_SUBJECT.search(subject) or _OOO_BODY.search(text)
    if m:
        ret = _find_return_date(text)
        if ret:
            fields["return_date"] = ret
        alt, _ = _extract_new_contact(body, sender)
        if alt:
            fields["alternate_contact"] = alt
        return {"label": "out_of_office", "evidence": _snippet(text, m), "fields": fields}

    m = _AUTO_OTHER.search(text)
    if m:
        return {"label": "auto_reply_other", "evidence": _snippet(text, m), "fields": fields}

    return {"label": "human_reply", "evidence": "", "fields": fields}


def classify_replies(messages: list[dict]) -> dict:
    """Classify a list of inbound reply messages.

    Each message is a dict with 'subject', 'body', 'from', and optional
    'headers'. Each is labeled one of: bounce_dead_address, bounce_policy_block,
    bounce_mailbox_full_or_temp, out_of_office, address_change,
    unsubscribe_request, auto_reply_other, human_reply. Returns the per-message
    label, an evidence phrase, extracted fields (return date, new address and
    named replacement contact, SMTP code), and counts by label.
    """
    out = []
    counts: dict[str, int] = {}
    for i, msg in enumerate(messages or []):
        res = _classify_one(msg if isinstance(msg, dict) else {})
        res["index"] = i
        out.append(res)
        counts[res["label"]] = counts.get(res["label"], 0) + 1
    return {"count": len(out), "counts": counts, "messages": out}


# ---- send window planning -------------------------------------------------

_WEEKDAYS = {"mon": 0, "monday": 0, "tue": 1, "tues": 1, "tuesday": 1,
             "wed": 2, "weds": 2, "wednesday": 2, "thu": 3, "thur": 3, "thurs": 3,
             "thursday": 3, "fri": 4, "friday": 4, "sat": 5, "saturday": 5,
             "sun": 6, "sunday": 6}

# Representative IANA zone per US state (abbreviation and full name). A state
# that straddles zones is mapped to the zone of most of its population.
_US_STATE_ZONES = {
    "al": "America/Chicago", "ak": "America/Anchorage", "az": "America/Phoenix",
    "ar": "America/Chicago", "ca": "America/Los_Angeles", "co": "America/Denver",
    "ct": "America/New_York", "de": "America/New_York", "fl": "America/New_York",
    "ga": "America/New_York", "hi": "Pacific/Honolulu", "id": "America/Boise",
    "il": "America/Chicago", "in": "America/Indiana/Indianapolis", "ia": "America/Chicago",
    "ks": "America/Chicago", "ky": "America/New_York", "la": "America/Chicago",
    "me": "America/New_York", "md": "America/New_York", "ma": "America/New_York",
    "mi": "America/Detroit", "mn": "America/Chicago", "ms": "America/Chicago",
    "mo": "America/Chicago", "mt": "America/Denver", "ne": "America/Chicago",
    "nv": "America/Los_Angeles", "nh": "America/New_York", "nj": "America/New_York",
    "nm": "America/Denver", "ny": "America/New_York", "nc": "America/New_York",
    "nd": "America/Chicago", "oh": "America/New_York", "ok": "America/Chicago",
    "or": "America/Los_Angeles", "pa": "America/New_York", "ri": "America/New_York",
    "sc": "America/New_York", "sd": "America/Chicago", "tn": "America/Chicago",
    "tx": "America/Chicago", "ut": "America/Denver", "vt": "America/New_York",
    "va": "America/New_York", "wa": "America/Los_Angeles", "wv": "America/New_York",
    "wi": "America/Chicago", "wy": "America/Denver", "dc": "America/New_York",
}
_US_STATE_NAMES = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar",
    "california": "ca", "colorado": "co", "connecticut": "ct", "delaware": "de",
    "florida": "fl", "georgia": "ga", "hawaii": "hi", "idaho": "id",
    "illinois": "il", "indiana": "in", "iowa": "ia", "kansas": "ks",
    "kentucky": "ky", "louisiana": "la", "maine": "me", "maryland": "md",
    "massachusetts": "ma", "michigan": "mi", "minnesota": "mn", "mississippi": "ms",
    "missouri": "mo", "montana": "mt", "nebraska": "ne", "nevada": "nv",
    "new hampshire": "nh", "new jersey": "nj", "new mexico": "nm", "new york": "ny",
    "north carolina": "nc", "north dakota": "nd", "ohio": "oh", "oklahoma": "ok",
    "oregon": "or", "pennsylvania": "pa", "rhode island": "ri", "south carolina": "sc",
    "south dakota": "sd", "tennessee": "tn", "texas": "tx", "utah": "ut",
    "vermont": "vt", "virginia": "va", "washington": "wa", "west virginia": "wv",
    "wisconsin": "wi", "wyoming": "wy", "district of columbia": "dc",
}
# Representative zone per country (code and common name).
_COUNTRY_ZONES = {
    "us": "America/New_York", "usa": "America/New_York", "united states": "America/New_York",
    "ca": "America/Toronto", "canada": "America/Toronto",
    "gb": "Europe/London", "uk": "Europe/London", "united kingdom": "Europe/London",
    "ie": "Europe/Dublin", "ireland": "Europe/Dublin",
    "de": "Europe/Berlin", "germany": "Europe/Berlin",
    "fr": "Europe/Paris", "france": "Europe/Paris",
    "es": "Europe/Madrid", "spain": "Europe/Madrid",
    "it": "Europe/Rome", "italy": "Europe/Rome",
    "nl": "Europe/Amsterdam", "netherlands": "Europe/Amsterdam",
    "se": "Europe/Stockholm", "sweden": "Europe/Stockholm",
    "ch": "Europe/Zurich", "switzerland": "Europe/Zurich",
    "pl": "Europe/Warsaw", "poland": "Europe/Warsaw",
    "au": "Australia/Sydney", "australia": "Australia/Sydney",
    "nz": "Pacific/Auckland", "new zealand": "Pacific/Auckland",
    "in": "Asia/Kolkata", "india": "Asia/Kolkata",
    "jp": "Asia/Tokyo", "japan": "Asia/Tokyo",
    "cn": "Asia/Shanghai", "china": "Asia/Shanghai",
    "sg": "Asia/Singapore", "singapore": "Asia/Singapore",
    "ae": "Asia/Dubai", "uae": "Asia/Dubai", "united arab emirates": "Asia/Dubai",
    "br": "America/Sao_Paulo", "brazil": "America/Sao_Paulo",
    "mx": "America/Mexico_City", "mexico": "America/Mexico_City",
    "za": "Africa/Johannesburg", "south africa": "Africa/Johannesburg",
    "il": "Asia/Jerusalem", "israel": "Asia/Jerusalem",
}


def _resolve_zone(rec: dict):
    """IANA zone for a recipient, from an explicit timezone, else a US state,
    else a country. None when nothing resolves."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    tz = (rec.get("timezone") or "").strip()
    if tz:
        try:
            ZoneInfo(tz)
            return tz
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            pass
    state = (rec.get("state") or "").strip().lower()
    if state:
        if state in _US_STATE_ZONES:
            return _US_STATE_ZONES[state]
        if state in _US_STATE_NAMES:
            return _US_STATE_ZONES[_US_STATE_NAMES[state]]
    country = (rec.get("country") or "").strip().lower()
    if country in _COUNTRY_ZONES:
        return _COUNTRY_ZONES[country]
    return None


def _next_send_local(start: datetime.date, allowed: set, local_hour: int):
    """The first date on or after `start` whose weekday is allowed, at local_hour."""
    d = start
    for _ in range(14):
        if d.weekday() in allowed:
            return datetime.datetime(d.year, d.month, d.day, local_hour, 0, 0)
        d += datetime.timedelta(days=1)
    return datetime.datetime(start.year, start.month, start.day, local_hour, 0, 0)


def send_window(recipients: list[dict], local_hour: int = 10,
                weekdays=("Tue", "Wed", "Thu"), start_date=None,
                batch_size: int = 50) -> dict:
    """Plan when to send to each recipient and group them into batches.

    Each recipient is a dict with 'email' and either a 'timezone' (IANA) or a
    'country' / 'state' (US states and common countries map to a representative
    IANA zone; anything that does not resolve goes to the unassigned list). For
    each recipient the next send time is the first allowed weekday on or after
    start_date at local_hour in the recipient's zone, reported in both UTC and
    local time. Recipients are grouped into batches by UTC send time, each batch
    capped at batch_size.
    """
    from zoneinfo import ZoneInfo
    allowed = set()
    for w in weekdays:
        key = str(w).strip().lower()
        if key in _WEEKDAYS:
            allowed.add(_WEEKDAYS[key])
    if not allowed:
        allowed = {1, 2, 3}
    if start_date is None:
        start = datetime.datetime.now(datetime.timezone.utc).date()
    elif isinstance(start_date, datetime.date):
        start = start_date
    else:
        start = datetime.date.fromisoformat(str(start_date))

    assigned = []
    unassigned = []
    for rec in recipients or []:
        email = (rec.get("email") or "").strip() if isinstance(rec, dict) else ""
        zone = _resolve_zone(rec) if isinstance(rec, dict) else None
        if not zone:
            unassigned.append(email or rec)
            continue
        local_naive = _next_send_local(start, allowed, local_hour)
        local_dt = local_naive.replace(tzinfo=ZoneInfo(zone))
        utc_dt = local_dt.astimezone(datetime.timezone.utc)
        assigned.append({
            "email": email,
            "timezone": zone,
            "local_time": local_dt.isoformat(),
            "utc_time": utc_dt.isoformat(),
            "_utc": utc_dt,
        })

    assigned.sort(key=lambda r: (r["_utc"], r["email"]))
    groups: dict[str, list] = {}
    for r in assigned:
        groups.setdefault(r["utc_time"], []).append(r)

    cap = max(1, int(batch_size))
    batches = []
    for utc_time in sorted(groups):
        members = groups[utc_time]
        for i in range(0, len(members), cap):
            chunk = members[i:i + cap]
            batches.append({
                "send_at_utc": utc_time,
                "size": len(chunk),
                "recipients": [{"email": r["email"], "timezone": r["timezone"],
                                "local_time": r["local_time"], "utc_time": r["utc_time"]}
                               for r in chunk],
            })

    return {
        "local_hour": local_hour,
        "weekdays": list(weekdays),
        "start_date": start.isoformat(),
        "batch_size": cap,
        "assigned_count": len(assigned),
        "unassigned_count": len(unassigned),
        "unassigned": unassigned,
        "batch_count": len(batches),
        "batches": batches,
    }
