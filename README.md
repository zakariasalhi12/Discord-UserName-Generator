# Discord Username Generator

This script generates random Discord usernames and checks their availability using the Discord API. It uses a list of proxies to avoid rate limiting.

## Requirements

- Python 3.x
- `requests` library (install with `pip install requests`)

## Setup

1. Download a list of proxies from [ProxyScrape](https://proxyscrape.com/free-proxy-list).
2. Save the proxy list as `proxies.txt` in the same directory as `generator.py`. Each proxy should be on a new line, e.g.:
   ```
   http://proxy1:port
   socks4://proxy2:port
   ```
3. Ensure `proxies.txt` is present.

## Running the Script

Run the script with:

```bash
python generator.py
```

The script will start 3 threads, each checking random usernames using random proxies. Valid usernames will be printed and saved to `result.txt`.

## Output

- Console output shows thread activity and check results.
- Valid usernames are appended to `result.txt`.

## Notes

- The script handles proxy failures automatically by removing bad proxies after a few failures.
- Interrupt with Ctrl+C to stop.