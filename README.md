# Discord Username Generator

Generates random Discord usernames and checks their availability against the Discord API.
It discovers working proxies in the background and rotates through them, so it keeps
making progress even though free proxies are unreliable.

![Discord Username Generator](assets/image.png)

## Features

- Random username generation with a configurable length
- Check a user-supplied list of usernames (batch mode)
- Use a user-supplied proxy list, or discover free proxies from multiple sources
- Proxies validated against the real Discord endpoint
- Background proxy refresher with cooldown-based rotation, so the pool never empties
- Local-connection fallback when no proxy is usable
- Discord webhook notifications when a valid username is found
- Optional automatic username change when a 3-letter name is found
- Small configuration file with sensible built-in defaults
- Runs in the foreground or detached in the background

## Requirements

- Python 3.8+
- [`requests`](https://pypi.org/project/requests/) library

Install dependencies:

```bash
pip install requests
```

## Quick start

```bash
python generator.py
```

To run it detached in the background and follow the logs:

```bash
./run_background.sh
tail -f app.log
```

The helper refuses to start a second instance while one is already running, and stores
the process id in `app.pid`.

## Configuration

All settings live in `config.json`. The file is **optional** — if it is missing, the
script uses built-in defaults. Create it next to `generator.py` with the content below
(this matches the shipped configuration):

```json
{
  "threads_number": 106,
  "username_length": 4,
  "usernames_file": "",
  "proxy_list_file": "",
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
  "result_file": "result.txt"
}
```

> `config.json` is git-ignored so your token and webhook URL stay private.

**Configuration Options:**

| Option | Description |
| --- | --- |
| `threads_number` | Number of worker threads |
| `username_length` | Length of generated usernames (clamped to 2-32) |
| `usernames_file` | Optional path to a text file of usernames to check instead of generating random ones (one per line) |
| `proxy_list_file` | Optional path to a text file of proxies to use, e.g. `1.2.3.4:8080` or `http://1.2.3.4:8080` (one per line) |
| `proxy_api_urls` | Free proxy sources, tried in order. Plain-text lists (`ip:port`) and JSON APIs are both supported. Set to `[]` to disable them and use only `proxy_list_file` |
| `discord_auth_token` | Optional user token; when set, a found 3-letter username is applied to your account |
| `discord_webhook_url` | Optional Discord webhook for notifications |
| `result_file` | Output file for valid usernames |

## Checking a username list

Set `usernames_file` to a text file with one username per line:

```text
alpha
beta
gamma
```

The script checks each entry once and then exits. Entries are trimmed, lower-cased
and de-duplicated automatically. If a username cannot be checked because every
attempt was rate-limited or errored, it is retried (up to 3 times) instead of being
dropped. Leave `usernames_file` empty to generate random usernames and run forever.

## Using your own proxy list

Set `proxy_list_file` to a text file with one proxy per line:

```text
1.2.3.4:8080
http://5.6.7.8:3128
user:pass@9.10.11.12:3128
```

The entries are validated against the real Discord endpoint and the working ones are
added to the pool, so dead entries are filtered out. Your proxies are used together
with the free sources; set `"proxy_api_urls": []` to rely only on your own list.

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

## Output

Each check prints one line with the username and its result:

```text
baraka -> taken
mi7way -> available
```

- `available` — the username is free; it is printed and appended to `result.txt`
- `taken` — the username is already in use
- `failed` — the result is unknown (every attempt was rate-limited or errored)

Nothing else is printed, so the output is just the names you tested and whether
they are valid.

## Notes

- Free proxies are unreliable: only a small fraction can reach Discord, and each
  usable IP allows roughly 15-20 requests before a long cooldown. The background
  refresher keeps looking for new ones, so the tool improves over time rather
  than stalling with an empty proxy list.
- Because throughput is limited by the number of usable IPs, a very high
  `threads_number` does not make the tool faster — it mostly produces `429`s.
  Start low (16-32) and increase only if your proxy pool is large.
- Interrupt with Ctrl+C to stop.

## Troubleshooting

| Symptom | Cause / fix |
| --- | --- |
| Everything is `failed` | No proxy can currently reach Discord. Add your own proxies via `proxy_list_file` or run from an IP that is not rate-limited. |
| Batch mode stops early | It stopped after no username could be checked for 2 minutes. Check your proxies and re-run. |
| Nothing is ever found | Free proxies are the bottleneck. Add your own proxy sources to `proxy_api_urls` or run from an IP that is not rate-limited. |

## Disclaimer

This tool is intended for checking the availability of usernames you may legitimately
claim. Automated account changes, bulk username squatting, or any activity that violates
Discord's [Terms of Service](https://discord.com/terms) is your responsibility.
