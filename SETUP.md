# Setup walkthrough

This server is four independent platforms. You only set up the ones you use, in
any order. Two tools work with zero setup, so you can confirm the server runs
before touching any credentials.

At every step you can check progress with the doctor:

```
python doctor.py          # what is configured
python doctor.py --live   # also ping the configured platforms
```

## Effort map (read this first)

| Platform | Time | Waits on approval? | What it gives you |
|---|---|---|---|
| Keyword (no auth) | 0 min | no | autocomplete, clustering |
| Trends | 2 min | no | Google Trends interest + related |
| Google Ads | 30-60 min | yes (dev token) | keyword volumes, reporting, management |
| Meta Ads | 15 min | no | Meta campaign reporting + management |
| GA4 | 10 min | no | site analytics |

Google Ads is the only one with a real wait (the developer-token review). Start
that application first, then do the others while it is pending.

---

## Step 0 - Install and confirm the server runs

```
cd marketing-mcp
pip install -r requirements.txt
python doctor.py
```

You should see `keyword_no_auth` and `trends` as READY and the three credentialed
platforms as not set up. That confirms the server imports and runs.

---

## Step 1 - Google Ads (the long one)

You need four OAuth values plus two account ids. Do them in this order.

**1a. Apply for a developer token (start this first, it can take a day).**
In the Google Ads account that will own API access, go to Tools -> Setup -> API
Center, and apply for a developer token. Basic access is enough. The account must
have a payment method on file (you do not have to run ads).

**1b. Create an OAuth client (while the token is pending).**
In Google Cloud Console, pick or create a project, enable the Google Ads API
(APIs & Services -> Library), then create an OAuth client of type Desktop app
(APIs & Services -> Credentials). Copy the client id and client secret.

**1c. Get the refresh token (the one browser step).**
Run the helper with the two values from 1b:

```
python oauth_setup.py <CLIENT_ID> <CLIENT_SECRET>
```

A browser opens. Approve with the Google account that has access to the Ads
account. The script prints `GOOGLE_ADS_REFRESH_TOKEN=...`. Copy it.

**1d. Find the account ids.**
- `GOOGLE_ADS_LOGIN_CUSTOMER_ID`: your manager (MCC) account id if you use one,
  digits only, no dashes.
- `GOOGLE_ADS_CUSTOMER_ID`: the account you want to query, digits only.
If you have no manager account, set both to the same id.

**1e. Fill the env and verify.**
Put `GOOGLE_ADS_DEVELOPER_TOKEN`, `GOOGLE_ADS_CLIENT_ID`,
`GOOGLE_ADS_CLIENT_SECRET`, `GOOGLE_ADS_REFRESH_TOKEN`,
`GOOGLE_ADS_LOGIN_CUSTOMER_ID`, `GOOGLE_ADS_CUSTOMER_ID` into your `.env` (or the
`.mcp.json` env block, Step 4). Then:

```
python doctor.py --live
```

`google_ads` should read READY with `live: ok (N accounts)`.

Note: until the account has some ad spend, keyword volumes come back as ranges
(for example 1K-10K), not exact numbers. That is Google's limit, not the server's.

---

## Step 2 - Meta Ads

Set `META_ACCESS_TOKEN` to a Marketing API access token. Get it from
developers.facebook.com: create an app, add the Marketing API product, and
generate a token with the `ads_read` scope (add `ads_management` if you want the
pause/activate tool). For a token that does not expire, use a System User token
from Business Settings. Then:

```
python doctor.py --live
```

`meta_ads` should read READY.

---

## Step 3 - GA4

Set `GOOGLE_APPLICATION_CREDENTIALS` to a service-account JSON path.
1. In Google Cloud Console, create a service account and download its JSON key.
2. Enable the Google Analytics Data API on the project.
3. In GA4 (Admin -> Property Access Management), add the service account email as
   a Viewer on the property.
4. Point `GOOGLE_APPLICATION_CREDENTIALS` at the JSON file.

Find your property id in GA4 Admin -> Property Settings (a number like
`123456789`). You pass it to the GA4 tools as `property_id`.

```
python doctor.py
```

`ga4` should read READY (the GA4 live check needs a property id, so confirm it by
calling `ga4_run_report` with your property id once wired in).

### Step 3b - Search Console (same key)

The same service account unlocks Google Search Console (organic search). Enable
the Search Console API on the project, then in Search Console (Settings -> Users
and permissions) add the service-account email as a user on the property. Enable
the API at console.cloud.google.com (APIs & Services). The `gsc_*` tools take the
property string as `site_url` (e.g. `https://example.com/` or `sc-domain:example.com`).

### No-setup tools

`seo_audit` and `pagespeed` need no credentials and work immediately. `pagespeed`
shares a small keyless quota; set `PAGESPEED_API_KEY` (a free Google Cloud API
key) for reliable use.

---

## Step 4 - Wire into Claude

Add the block to your `.mcp.json` (project) or the desktop MCP config. Keep only
the env keys for the platforms you set up; the others can be omitted.

```json
{
  "mcpServers": {
    "marketing-mcp": {
      "command": "python",
      "args": ["path/to/marketing-mcp/server.py"],
      "env": {
        "GOOGLE_ADS_DEVELOPER_TOKEN": "...",
        "GOOGLE_ADS_CLIENT_ID": "...",
        "GOOGLE_ADS_CLIENT_SECRET": "...",
        "GOOGLE_ADS_REFRESH_TOKEN": "...",
        "GOOGLE_ADS_LOGIN_CUSTOMER_ID": "...",
        "GOOGLE_ADS_CUSTOMER_ID": "...",
        "META_ACCESS_TOKEN": "...",
        "GOOGLE_APPLICATION_CREDENTIALS": "C:/path/to/ga4-service-account.json"
      }
    }
  }
}
```

Restart the Claude session so it picks up the server, then ask it to run
`setup_check` with `live=true`. That is the same readout as `python doctor.py
--live`, from inside the chat.

Simpler option: instead of the `env` block above, copy `.env.example` to `.env`
next to `server.py` and fill it in. The server auto-loads that `.env` on startup,
so the `.mcp.json` can be just the `command` and `args` with no secrets in it.
`.env` is gitignored.

---

## Verify, end to end

1. `python doctor.py --live` shows the platforms you set up as READY.
2. In chat, a zero-setup call: "use autocomplete_suggestions for 'ai governance'".
3. A credentialed call per platform you configured, for example
   "keyword_ideas for 'ai governance' in the US", "campaign_performance last 30
   days", "ga4_traffic_sources for property 123456789".

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `google-ads not installed` | `pip install -r requirements.txt` |
| Google Ads `DEVELOPER_TOKEN_NOT_APPROVED` | dev token still under review, or wrong access level |
| Google Ads `USER_PERMISSION_DENIED` | the OAuth account lacks access to `GOOGLE_ADS_CUSTOMER_ID`, or the login-customer-id is wrong |
| `No refresh token returned` from oauth_setup | revoke the app's prior access in your Google account, re-run |
| Meta `error ... session has expired` | the token expired; mint a System User token |
| GA4 `PERMISSION_DENIED` | the service account is not a Viewer on the property, or the wrong property id |
| Keyword volumes are ranges, not numbers | expected without ad spend on the account |

When in doubt, run `python doctor.py --live` and read the `next` and `live` lines.
