# SPDX-License-Identifier: MIT
"""Google Ads OAuth helper. Runs the consent flow once and prints the refresh
token, which is the single hardest value to obtain in setup. Everything else for
Google Ads is copy-paste; this is the step that needs a browser.

  python oauth_setup.py <CLIENT_ID> <CLIENT_SECRET>

Prereqs: a Desktop OAuth client created in Google Cloud (APIs & Services ->
Credentials), and the Google Ads API enabled on that project. The flow opens a
browser, you approve with the Google account that has access to the Ads account,
and it prints GOOGLE_ADS_REFRESH_TOKEN to paste into your .env / .mcp.json.
"""
import sys

SCOPES = ["https://www.googleapis.com/auth/adwords"]


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: python oauth_setup.py <CLIENT_ID> <CLIENT_SECRET>")
        return 2
    client_id, client_secret = sys.argv[1], sys.argv[2]
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Missing dependency. Run: pip install google-auth-oauthlib")
        return 1
    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        },
        scopes=SCOPES,
    )
    creds = flow.run_local_server(port=0, prompt="consent")
    if not creds.refresh_token:
        print("No refresh token returned. Revoke prior access and re-run with a "
              "fresh consent (the flow already requests prompt=consent).")
        return 1
    print("\n" + "=" * 60)
    print("Paste this into your .env or the .mcp.json env block:")
    print("GOOGLE_ADS_REFRESH_TOKEN=" + creds.refresh_token)
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
