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

Edit `generator.py` to customize the script behavior:

- `threads_number` - Number of worker threads (default: 3)
- `username_length` - Length of generated usernames (default: 3)
- `max_proxy_response_time` - Max response time in seconds before removing a proxy (default: 9)
- `show_proxy_logs` - Set to `True` to see detailed proxy logs, `False` to only see found usernames (default: False)

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