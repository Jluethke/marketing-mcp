# SPDX-License-Identifier: MIT
"""Setup doctor. Prints per-platform readiness without an MCP client, so you can
check progress while setting up. Reads the same environment the server reads.

  python doctor.py          # configured / not configured per platform
  python doctor.py --live   # also ping the configured platforms (lists accounts)
"""
import sys

import server


def main() -> int:
    live = "--live" in sys.argv
    st = server._platform_status(live)
    print("Marketing MCP - setup doctor\n")
    order = ["keyword_no_auth", "trends", "google_ads", "meta_ads", "ga4"]
    for plat in order:
        v = st[plat]
        box = "x" if v.get("ready") else " "
        print("  [%s] %-16s %s" % (box, plat, "READY" if v.get("ready") else "not set up"))
        if not v.get("ready") and v.get("next_step"):
            print("         next: " + v["next_step"])
        if v.get("missing_env"):
            print("         missing env: " + ", ".join(v["missing_env"]))
        if v.get("live_check"):
            print("         live: " + str(v["live_check"]))
    ready = [p for p in order if st[p].get("ready")]
    pending = [p for p in order if not st[p].get("ready")]
    print("\nReady now: " + (", ".join(ready) or "none"))
    if pending:
        print("Still to set up: " + ", ".join(pending) + "   (see SETUP.md)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
