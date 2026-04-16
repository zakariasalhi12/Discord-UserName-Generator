# Discord Username Generator


This script generates random Discord usernames and checks their availability using the Discord API. It uses a list of proxies to avoid rate limiting.

![Discord Username Generator](assets/image.png)

## Requirements

- Python 3.x
- `requests` library (install with `pip install requests`)

## Setup

1. Install Python dependencies:
   ```bash
   pip install requests
   ```
2. The script automatically fetches proxies from the [ProxyScrape API](https://api.proxyscrape.com/), so no manual proxy setup is required.

## Configuration

All settings are stored in `config.json`. Edit this file to customize the script behavior:

```json
{
  "endpoint": "https://discord.com/api/v9/unique-username/username-attempt-unauthed",
  "proxy_api_url": "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=protocolipport&format=text&timeout=619",
  "username_length": 4,
  "rate_limit_seconds": 0,
  "rate_limit_backoff": 5,
  "max_proxy_response_time": 9,
  "proxy_fail_limit": 2,
  "threads_number": 3,
  "show_proxy_logs": false,
  "result_file": "result.txt",
  "discord_webhook_url": ""
}
```

**Configuration Options:**
- `endpoint` - Discord API endpoint URL
- `proxy_api_url` - ProxyScrape API URL for fetching proxies
- `username_length` - Length of generated usernames
- `rate_limit_seconds` - Delay between normal requests (0 = no delay)
- `rate_limit_backoff` - Delay after 429 rate limit response
- `max_proxy_response_time` - Maximum proxy response time in seconds
- `proxy_fail_limit` - Number of failures before removing a proxy
- `threads_number` - Number of worker threads
- `show_proxy_logs` - Set to `true` for detailed proxy logs, `false` for clean output
- `result_file` - Output file for valid usernames

## Running the Script

Run the script with:

```bash
python generator.py
```

The script will start 3 threads, each checking random usernames using random proxies. Valid usernames will be printed and saved to `result.txt`.

## Output

- **Always visible**: Valid usernames are printed and saved to `result.txt` (e.g., `✅ VALID USERNAME FOUND: abc`)
- **With `show_proxy_logs = True`**: Detailed proxy information including response times, errors, rate limits, and slow proxy removals
- **With `show_proxy_logs = False`** (default): Only valid usernames are displayed for a clean output

## Notes

- The script handles proxy failures automatically by removing bad proxies after a few failures.
- Interrupt with Ctrl+C to stop.