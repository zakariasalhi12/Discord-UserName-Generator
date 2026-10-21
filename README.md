# Discord Username Generator

Generates random Discord usernames and checks their availability using the Discord API.
It discovers working proxies in the background and rotates through them, so it keeps
making progress even though free proxies are unreliable.

![Discord Username Generator](assets/image.png)

## Requirements

- Python 3.x
- `requests` library (install with `pip install requests`)

## Setup

1. Install Python dependencies:
   ```bash
   pip install requests
   ```
2. No manual proxy setup is required — the script pulls proxies from several free
   sources automatically.

## Configuration

`config.json` is intentionally small. Everything else is tuned internally:

```json
{
  "threads_number": 16,
  "username_length": 4,
  "proxy_api_urls": [
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc&protocols=http%2Chttps",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://api.openproxylist.xyz/http.txt",
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000",
    "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=protocolipport&format=text"
  ],
  "discord_auth_token": "",
  "discord_webhook_url": "",
  "result_file": "result.txt",
  "show_proxy_logs": false
}
```

**Configuration Options:**
- `threads_number` - Number of worker threads
- `username_length` - Length of generated usernames
- `proxy_api_urls` - Free proxy sources, tried in order. Plain-text lists (`ip:port`) and JSON APIs are both supported
- `discord_auth_token` - Optional user token; when set, a found 3-letter username is applied to your account
- `discord_webhook_url` - Optional Discord webhook for notifications
- `result_file` - Output file for valid usernames
- `show_proxy_logs` - Set to `true` for detailed proxy logs

## How it works

1. A background refresher fetches every proxy source in parallel, dedupes and
   quality-ranks the candidates (Geonode exposes up-time/latency metadata).
2. Candidates are validated against the **real Discord endpoint**. A proxy is only
   kept if Discord returns its JSON body — many free proxies answer `200` with
   their own status page instead of forwarding, which is why status codes alone
   are not trusted.
3. Workers rotate through the validated pool. When a proxy is rate-limited (429)
   it is parked for the `retry_after` window instead of being deleted, so the
   pool never drains. The local connection is used as a fallback when no proxy
   is usable.

## Running the Script

```bash
python generator.py
```

Valid usernames are printed and saved to `result.txt`.

## Output

- **Always visible**: valid usernames (`[BINGOOO] - VALID USERNAME FOUND: ...`)
- **Periodic status**: `checked`, `valid`, `failed`, `rate_limited` and the proxy pool size
- **With `show_proxy_logs = true`**: detailed proxy errors and cooldowns

## Notes

- Free proxies are unreliable: only a small fraction can reach Discord, and each
  usable IP allows roughly 15-20 requests before a long cooldown. The background
  refresher keeps looking for new ones, so the tool improves over time rather
  than stalling with an empty proxy list.
- Interrupt with Ctrl+C to stop.
