import json
import queue
import random
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, List, Optional
from urllib.parse import quote, urlsplit

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DEFAULT_ENDPOINT = "https://discord.com/api/v9/unique-username/username-attempt-unauthed"

DEFAULT_PROXY_SOURCES = [
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://proxylist.geonode.com/api/proxy-list?limit=500&page=1&sort_by=lastChecked&sort_type=desc&protocols=http%2Chttps",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://api.openproxylist.xyz/http.txt",
    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=10000",
    "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=protocolipport&format=text",
]

# Sentinel used for the local machine's own connection when no proxy is usable.
DIRECT_PROXY = "__direct__"

# ---------------------------------------------------------------------------
# Internal tuning. Deliberately kept out of config.json so the tool has a small,
# opinionated configuration surface and "just works" out of the box.
#
# Free proxies are unreliable: only a small fraction can actually reach Discord,
# and each usable IP allows ~15-20 requests before a long cooldown. The tool
# therefore validates a large candidate pool in the background and rotates on
# cooldowns rather than deleting proxies.
# ---------------------------------------------------------------------------
PROXY_FETCH_TIMEOUT = 15
PROXY_VALIDATION_TIMEOUT = 3
PROXY_VALIDATION_WORKERS = 350
PROXY_VALIDATION_CHUNK = 2000
PROXY_VALIDATION_LIMIT = 12000
PROXY_MIN_UP_TIME = 80
PROXY_MAX_LATENCY_MS = 3000
PROXY_REFRESH_INTERVAL = 20
MAX_POOL_SIZE = 800
VALIDATION_USERNAME = "zzqtest"

REQUEST_TIMEOUT = 10
MAX_PROXY_RESPONSE_TIME = 8
EMPTY_RETRY_SECONDS = 3
MAX_ATTEMPTS = 3
MAX_USERNAME_ATTEMPTS = 3
BATCH_IDLE_TIMEOUT = 120
DEFAULT_BACKOFF_SECONDS = 5
MAX_COOLDOWN_SECONDS = 1800


def load_config(config_file: str = "config.json") -> Dict:
    """Load configuration from JSON file"""
    try:
        with open(config_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError:
        print(f"Invalid JSON in {config_file}; using defaults.")
        return {}


config = load_config()
endpoint = config.get("endpoint", DEFAULT_ENDPOINT)
username_length = config.get("username_length", 4)
threads_number = config.get("threads_number", 16)
result_file = config.get("result_file", "result.txt")
discord_webhook_url = config.get("discord_webhook_url", "").strip()
discord_auth_token = config.get("discord_auth_token", "").strip()

# Optional user-supplied lists. Leave them empty to use the built-in behaviour
# (random generation / free proxy sources).
usernames_file = config.get("usernames_file", "").strip()
proxy_list_file = config.get("proxy_list_file", "").strip()

# `proxy_api_urls` may be an explicit empty list to disable the free sources and
# rely only on a user-supplied proxy list.
sources = config.get("proxy_api_urls", config.get("proxy_sources"))
if isinstance(sources, str):
    sources = re.split(r"[\s,]+", sources)
if sources is None:
    sources = DEFAULT_PROXY_SOURCES
proxy_api_urls = [u.strip() for u in sources if u and u.strip()]

characters = [
    'a', 'b', 'c', 'd', 'e', 'f', 'g', 'h', 'i', 'j', 'k', 'l', 'm',
    'n', 'o', 'p', 'q', 'r', 's', 't', 'u', 'v', 'w', 'x', 'y', 'z',
    '0', '1', '2', '3', '4', '5', '6', '7', '8', '9', '.', '_'
]
# Discord rejects usernames with leading/trailing dots or consecutive dots, so
# never start a generated username with a separator.
SAFE_FIRST_CHARS = [c for c in characters if c not in "._"]

# requests only routes http:// and https:// proxies through the mapping we build
# in format_proxy(); SOCKS entries would need the optional requests[socks] extra.
SUPPORTED_PROXY_SCHEMES = {"http", "https"}
PROXY_ENTRY_SEPARATORS = re.compile(r"[\s,;]+")


# ---------------------------------------------------------------------------
# Proxy parsing
# ---------------------------------------------------------------------------

def _normalize_proxy(entry: str) -> Optional[str]:
    """Turn one proxy entry into a canonical http(s)://host:port URL."""
    candidate = entry.strip().strip("\"'").strip().rstrip(",;")
    if not candidate or candidate.startswith("#"):
        return None

    # Free proxy lists are inconsistent: some entries include the scheme, most do not.
    if "://" not in candidate:
        candidate = f"http://{candidate}"

    try:
        parts = urlsplit(candidate)
        scheme = parts.scheme.lower()
        host = parts.hostname
        port = parts.port
    except ValueError:
        return None

    if scheme not in SUPPORTED_PROXY_SCHEMES or not host or port is None:
        return None
    if port < 1 or port > 65535:
        return None

    # Skip placeholder entries such as 0.0.0.0:80.
    if host in {"0.0.0.0", "127.0.0.1", "localhost"}:
        return None

    if ":" in host:  # IPv6
        host = f"[{host}]"

    credentials = ""
    if parts.username:
        credentials = quote(parts.username, safe="")
        if parts.password:
            credentials += f":{quote(parts.password, safe='')}"
        credentials += "@"

    return f"{scheme}://{credentials}{host}:{port}"


def _candidate_from_json_object(obj: Dict) -> Optional[Dict]:
    """Turn one JSON proxy object into a candidate dict, or None if unusable.

    Handles the shapes returned by Geonode (`{"ip": ..., "port": ..., "upTime":
    ..., "responseTime": ...}`) and generic `{"proxy": "ip:port"}` objects.
    """
    if not isinstance(obj, dict):
        return None

    ip = obj.get("ip") or obj.get("host")
    port = obj.get("port")
    if ip and port is not None:
        entry = f"{ip}:{port}"
    else:
        proxy_field = obj.get("proxy") or obj.get("address")
        if not isinstance(proxy_field, str) or not proxy_field.strip():
            return None
        entry = proxy_field.strip()

    candidate = {"entry": entry}

    up_time = obj.get("upTime")
    if isinstance(up_time, (int, float)):
        candidate["up_time"] = float(up_time)

    # Geonode exposes both; responseTime is the most recent measurement.
    latency = obj.get("responseTime")
    if not isinstance(latency, (int, float)):
        latency = obj.get("latency")
    if isinstance(latency, (int, float)):
        candidate["latency_ms"] = float(latency)

    return candidate


def _flatten_proxy_payload(payload) -> List[Dict]:
    """Extract proxy candidate dicts from the different JSON shapes proxy APIs return."""
    entries: List[Dict] = []

    if isinstance(payload, str):
        entries.extend({"entry": part} for part in PROXY_ENTRY_SEPARATORS.split(payload) if part)
    elif isinstance(payload, (list, tuple)):
        for item in payload:
            entries.extend(_flatten_proxy_payload(item))
    elif isinstance(payload, dict):
        # Common shapes: {"proxy": "ip:port"}, {"ip": "...", "port": 8080},
        # {"proxies": [...]}, {"data": [...]}, {"results": [...]}
        if ("ip" in payload and "port" in payload) or (
            isinstance(payload.get("proxy"), str) and payload["proxy"].strip()
        ):
            candidate = _candidate_from_json_object(payload)
            if candidate:
                entries.append(candidate)
                return entries
        else:
            for key in ("proxies", "data", "results", "items", "list", "servers"):
                if key in payload:
                    entries.extend(_flatten_proxy_payload(payload[key]))
                    return entries
            for value in payload.values():
                entries.extend(_flatten_proxy_payload(value))

    return entries


def _proxy_quality_score(candidate: Dict) -> float:
    """Rank proxy candidates; higher is better.

    Metadata-rich JSON sources (Geonode) rank above plain-text lists, and within
    a source the healthiest entries (high up-time, low latency) come first.
    """
    score = 0.0
    up_time = candidate.get("up_time")
    latency = candidate.get("latency_ms")
    if isinstance(up_time, (int, float)):
        score += min(float(up_time), 100.0)
    if isinstance(latency, (int, float)):
        # Latency is in ms; reward anything under roughly 3s.
        score += max(0.0, 30.0 - float(latency) / 100.0)
    return score


def parse_proxies(raw_text: str) -> List[Dict]:
    """Parse a proxy API response into deduplicated, quality-ranked candidates.

    Returns a list of dicts with a ``url`` key. Sources that expose quality
    metadata (Geonode-style JSON) also carry ``up_time`` and ``latency_ms`` so
    the healthiest entries are validated first. Supports plain text lists
    (`ip:port`, `scheme://ip:port`), comma/whitespace separated lists, and
    common JSON response formats.
    """
    if not raw_text or not raw_text.strip():
        return []

    stripped = raw_text.strip()
    candidates: List[Dict] = []

    if stripped[0] in "[{":
        try:
            candidates = _flatten_proxy_payload(json.loads(stripped))
        except json.JSONDecodeError:
            candidates = []

    if not candidates:
        candidates = [
            {"entry": part}
            for part in PROXY_ENTRY_SEPARATORS.split(stripped)
            if part
        ]

    proxies: List[Dict] = []
    seen = set()
    for candidate in candidates:
        proxy_url = _normalize_proxy(candidate.get("entry", ""))
        if not proxy_url or proxy_url in seen:
            continue
        seen.add(proxy_url)
        proxies.append({
            "url": proxy_url,
            "up_time": candidate.get("up_time"),
            "latency_ms": candidate.get("latency_ms"),
        })

    # Quality-aware entries first; plain-text lists keep their original order.
    proxies.sort(key=_proxy_quality_score, reverse=True)
    return proxies


def _quality_gate(candidates: List[Dict]) -> List[Dict]:
    """Drop candidates whose reported quality is below the configured thresholds."""
    gated: List[Dict] = []
    for candidate in candidates:
        up_time = candidate.get("up_time")
        latency = candidate.get("latency_ms")
        if up_time is not None and up_time < PROXY_MIN_UP_TIME:
            continue
        if latency is not None and latency > PROXY_MAX_LATENCY_MS:
            continue
        gated.append(candidate)
    return gated


# ---------------------------------------------------------------------------
# Proxy pool
# ---------------------------------------------------------------------------

session = requests.Session()
session.trust_env = False
session.verify = False
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
})

proxies: List[str] = []
proxy_count = 0
proxy_cooldowns: Dict[str, float] = {}  # proxy -> time.time() when it becomes usable again
proxy_lock = threading.RLock()
thread_local = threading.local()

stats_lock = threading.Lock()
stats = {"checked": 0, "valid": 0, "failed": 0, "rate_limited": 0}

# Queue of usernames to check when `usernames_file` is configured; None means
# the workers generate random usernames instead.
username_queue: Optional["queue.Queue[str]"] = None
# Retry counter for user-supplied usernames that could not be checked yet.
username_attempts: Dict[str, int] = {}
username_attempts_lock = threading.Lock()


def format_proxy(proxy_url: str) -> Dict[str, str]:
    if proxy_url == DIRECT_PROXY:
        return {}
    return {"http": proxy_url, "https": proxy_url}


def add_proxies(new_urls: List[str]) -> None:
    """Merge freshly validated proxies into the pool, capping its size."""
    global proxies, proxy_count

def add_proxies(new_urls: List[str]) -> None:
    """Merge freshly validated proxies into the pool, capping its size."""
    global proxies, proxy_count

    with proxy_lock:
        for url in new_urls:
            if url not in proxies:
                proxies.append(url)

        if len(proxies) > MAX_POOL_SIZE:
            # Evict the oldest non-cooling proxies to keep the pool bounded.
            excess = len(proxies) - MAX_POOL_SIZE
            now = time.time()
            kept: List[str] = []
            for p in proxies:
                if excess > 0 and proxy_cooldowns.get(p, 0.0) <= now:
                    excess -= 1
                    proxy_cooldowns.pop(p, None)
                else:
                    kept.append(p)
            proxies = kept

        proxy_count = len(proxies)


def remove_proxy(proxy_url: str, reason: str = "failure") -> None:
    global proxy_count

    # The local connection is a fallback, not a pool entry: never drop its
    # cooldown, otherwise it gets hammered again immediately.
    if proxy_url == DIRECT_PROXY:
        return

    with proxy_lock:
        if proxy_url in proxies:
            proxies.remove(proxy_url)
            proxy_count = len(proxies)
            proxy_cooldowns.pop(proxy_url, None)


def mark_proxy_cooldown(proxy_url: str, seconds: float) -> None:
    """Park a rate-limited proxy instead of deleting it; it may recover later."""
    seconds = max(1.0, min(float(seconds), MAX_COOLDOWN_SECONDS))
    with proxy_lock:
        proxy_cooldowns[proxy_url] = time.time() + seconds
    increment_stat("rate_limited")


def available_proxies() -> List[str]:
    now = time.time()
    with proxy_lock:
        return [p for p in proxies if proxy_cooldowns.get(p, 0.0) <= now]


def get_working_proxy() -> Optional[str]:
    """Pick a usable proxy, falling back to the local connection if needed."""
    now = time.time()
    with proxy_lock:
        available = [p for p in proxies if proxy_cooldowns.get(p, 0.0) <= now]
        direct_ready = proxy_cooldowns.get(DIRECT_PROXY, 0.0) <= now

    if available:
        return random.choice(available)
    if direct_ready:
        return DIRECT_PROXY
    return None


def increment_stat(name: str, amount: int = 1) -> None:
    with stats_lock:
        stats[name] = stats.get(name, 0) + amount


def snapshot_stats() -> Dict[str, int]:
    with stats_lock:
        return dict(stats)


def print_result(username: str, status: str) -> None:
    """Print the outcome of a single username check.

    Only checks with a known result are printed: the name and whether it is
    valid. Failed checks are silent.
    """
    label = {"found": "valid", "taken": "taken"}.get(status, status)
    print(f"{username} -> {label}")


# ---------------------------------------------------------------------------
# Fetching + validating proxies
# ---------------------------------------------------------------------------

def _validate_single_proxy(proxy_url: str) -> Optional[str]:
    """A proxy is only kept if it can actually complete a username check.

    Validation uses the real endpoint and requires Discord's JSON body: many
    free proxies answer with HTTP 200 and their own status page instead of
    forwarding, so status codes alone are not enough.
    """
    validator_session = getattr(thread_local, "validation_session", None)
    if validator_session is None:
        validator_session = requests.Session()
        validator_session.trust_env = False
        validator_session.verify = False
        validator_session.headers.update(session.headers)
        thread_local.validation_session = validator_session

    try:
        response = validator_session.post(
            endpoint,
            json={"username": VALIDATION_USERNAME},
            proxies=format_proxy(proxy_url),
            timeout=PROXY_VALIDATION_TIMEOUT,
        )
    except requests.exceptions.RequestException:
        return None

    if response.status_code != 200:
        return None
    try:
        return proxy_url if "taken" in response.json() else None
    except ValueError:
        return None


def _validate_batch(urls: List[str]) -> List[str]:
    if not urls:
        return []
    working: List[str] = []
    with ThreadPoolExecutor(max_workers=PROXY_VALIDATION_WORKERS) as executor:
        for result in executor.map(_validate_single_proxy, urls):
            if result is not None:
                working.append(result)
    return working


def _fetch_candidates(api_url: str) -> List[Dict]:
    try:
        response = requests.get(api_url, timeout=PROXY_FETCH_TIMEOUT)
        response.raise_for_status()
    except requests.exceptions.RequestException:
        return []

    return parse_proxies(response.text)


def _gather_candidates() -> List[Dict]:
    """Fetch every source in parallel, quality-gate, dedupe and rank."""
    candidates: List[Dict] = []
    with ThreadPoolExecutor(max_workers=max(1, len(proxy_api_urls))) as executor:
        for batch in executor.map(_fetch_candidates, proxy_api_urls):
            candidates.extend(batch)

    candidates = _quality_gate(candidates)

    seen = set()
    unique: List[Dict] = []
    for candidate in candidates:
        url = candidate["url"]
        if url not in seen:
            seen.add(url)
            unique.append(candidate)

    return unique


def proxy_refresher(stop_event: threading.Event) -> None:
    """Continuously find and validate working proxies in the background."""
    while not stop_event.is_set():
        started_at = time.time()
        try:
            candidates = _gather_candidates()
            with proxy_lock:
                known = set(proxies)
            fresh = [c for c in candidates if c["url"] not in known]
            if len(fresh) > PROXY_VALIDATION_LIMIT:
                fresh = fresh[:PROXY_VALIDATION_LIMIT]

            for i in range(0, len(fresh), PROXY_VALIDATION_CHUNK):
                if stop_event.is_set():
                    return
                valid = _validate_batch([c["url"] for c in fresh[i:i + PROXY_VALIDATION_CHUNK]])
                if valid:
                    add_proxies(valid)
        except Exception:
            # Never let a refresh error kill the refresher thread.
            pass

        elapsed = time.time() - started_at
        stop_event.wait(max(1, PROXY_REFRESH_INTERVAL - elapsed))


# ---------------------------------------------------------------------------
# Discord checks
# ---------------------------------------------------------------------------

def _retry_after_seconds(response) -> float:
    try:
        value = response.json().get("retry_after", 0)
        return float(value) if value else 0.0
    except Exception:
        return 0.0


def checkUsername(username: str, stop_event: Optional[threading.Event] = None) -> str:
    """Check one username.

    Returns "found" (available), "taken" (not available) or "failed" (the result
    is unknown because every attempt errored or was rate-limited).
    """
    payload = {"username": username}
    status = "failed"

    for _ in range(MAX_ATTEMPTS):
        if stop_event is not None and stop_event.is_set():
            break

        proxy_url = get_working_proxy()
        if proxy_url is None:
            break

        try:
            started_at = time.time()
            response = session.post(
                endpoint,
                json=payload,
                proxies=format_proxy(proxy_url),
                timeout=REQUEST_TIMEOUT,
            )
            response_time = time.time() - started_at
        except requests.exceptions.Timeout:
            remove_proxy(proxy_url, reason="timeout")
            increment_stat("failed")
            continue
        except requests.exceptions.RequestException:
            remove_proxy(proxy_url)
            increment_stat("failed")
            continue

        if response_time > MAX_PROXY_RESPONSE_TIME:
            remove_proxy(proxy_url, reason="timeout")
            increment_stat("failed")
            continue

        if response.status_code == 200:
            try:
                taken = response.json().get("taken", False)
            except ValueError:
                increment_stat("failed")
                continue
            increment_stat("checked")
            if not taken:
                increment_stat("valid")
                status = "found"
            else:
                status = "taken"
            break

        if response.status_code == 429:
            retry_after = _retry_after_seconds(response) or DEFAULT_BACKOFF_SECONDS
            mark_proxy_cooldown(proxy_url, retry_after)
            continue

        remove_proxy(proxy_url)
        increment_stat("failed")

    if status != "failed":
        print_result(username, status)
    return status


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

def appendToFile(username: str) -> None:
    with open(result_file, "a", encoding="utf-8") as f:
        f.write(username + "\n")


def send_discord_webhook(username: str) -> None:
    if not discord_webhook_url:
        return

    payload = {"content": f"[+] username found: {username}"}
    try:
        session.post(discord_webhook_url, json=payload, timeout=10)
    except requests.exceptions.RequestException:
        pass


def change_discord_username(username: str) -> None:
    """Attempt to change the authenticated Discord account username to `username`.

    Requires `discord_auth_token` to be set in `config.json` as a valid user token.
    """
    if not discord_auth_token:
        return

    url = "https://discord.com/api/v9/users/@me"
    headers = session.headers.copy()
    headers["Authorization"] = discord_auth_token

    payload = {"username": username}
    try:
        resp = session.patch(url, json=payload, headers=headers, timeout=10)
    except requests.exceptions.RequestException:
        return

    if resp.status_code in (200, 204):
        print(f"Discord username changed to: {username}")
    elif resp.status_code == 401:
        print("Unauthorized: invalid discord_auth_token provided.")
    else:
        try:
            error_text = resp.json()
        except Exception:
            error_text = resp.text
        print(f"Failed to change username ({resp.status_code}): {error_text}")


def pickRandomUsername() -> str:
    """Generate a Discord-valid random username of the configured length."""
    length = max(2, min(int(username_length), 32))
    while True:
        chars = [random.choice(SAFE_FIRST_CHARS)]
        chars.extend(random.choice(characters) for _ in range(length - 1))
        username = "".join(chars)
        if ".." not in username and not username.endswith("."):
            return username


def load_username_list(path: str) -> Optional["queue.Queue[str]"]:
    """Read usernames from a file into a thread-safe queue (one check each).

    Lines are trimmed, lower-cased and de-duplicated. Returns None when the file
    is unreadable or empty so the caller can fall back to random generation.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError as exc:
        print(f"Could not read usernames file {path}: {exc}")
        return None

    usernames: "queue.Queue[str]" = queue.Queue()
    seen = set()
    for raw in lines:
        username = raw.strip().lower()
        if username and username not in seen:
            seen.add(username)
            usernames.put(username)

    if usernames.empty():
        print(f"No usernames found in {path}")
        return None

    return usernames


def load_proxy_list_file(path: str) -> List[str]:
    """Read a local proxy list file and validate the entries."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read()
    except OSError as exc:
        print(f"Could not read proxy list file {path}: {exc}")
        return []

    candidates = parse_proxies(raw)
    if not candidates:
        print(f"No valid proxies found in {path}")
        return []

    if len(candidates) > PROXY_VALIDATION_LIMIT:
        candidates = candidates[:PROXY_VALIDATION_LIMIT]

    working = _validate_batch([candidate["url"] for candidate in candidates])
    if working:
        add_proxies(working)
    return working


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------

def worker(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        # Wait until a proxy is available before taking the next username, so a
        # username is never skipped just because the pool is temporarily empty.
        if get_working_proxy() is None:
            stop_event.wait(EMPTY_RETRY_SECONDS)
            continue

        if username_queue is not None:
            try:
                username = username_queue.get_nowait()
            except queue.Empty:
                return  # every username in the list has been checked
        else:
            username = pickRandomUsername()

        status = checkUsername(username, stop_event)
        if status == "found":
            appendToFile(username)
            send_discord_webhook(username)
            # If the found username is exactly 3 letters, attempt to change the
            # authenticated Discord account username to it.
            try:
                if len(username) == 3:
                    change_discord_username(username)
            except Exception:
                # Don't let username-change failures stop the worker
                pass
            username_attempts.pop(username, None)
        elif status == "failed" and username_queue is not None:
            # A user-supplied username that could not be checked is put back so
            # it is retried later (up to a bounded number of attempts).
            with username_attempts_lock:
                attempts = username_attempts.get(username, 0) + 1
                retry = attempts < MAX_USERNAME_ATTEMPTS
                if retry:
                    username_attempts[username] = attempts
                else:
                    username_attempts.pop(username, None)
            if retry:
                username_queue.put(username)


def start_workers(stop_event: threading.Event) -> List[threading.Thread]:
    threads = []
    for i in range(threads_number):
        t = threading.Thread(target=worker, args=(stop_event,), name=f"Worker-{i+1}")
        t.daemon = True
        threads.append(t)
        t.start()

    return threads


def run() -> None:
    global username_queue

    stop_event = threading.Event()

    if usernames_file:
        username_queue = load_username_list(usernames_file)

    # A user-supplied proxy list is validated up front and added to the pool. The
    # free-source refresher keeps running as a fallback unless proxy_api_urls is
    # explicitly empty.
    if proxy_list_file:
        load_proxy_list_file(proxy_list_file)

    if proxy_api_urls:
        refresher = threading.Thread(target=proxy_refresher, args=(stop_event,), name="ProxyRefresher", daemon=True)
        refresher.start()

    threads = start_workers(stop_event)

    if username_queue is not None:
        # Batch mode: exit once every username in the list has been checked.
        # If no username can be checked for a while (e.g. every proxy is
        # rate-limited), stop instead of waiting forever.
        last_checked = snapshot_stats()["checked"]
        last_progress = time.time()
        for t in threads:
            while t.is_alive():
                t.join(timeout=1)
                now = time.time()
                current_checked = snapshot_stats()["checked"]
                if current_checked != last_checked:
                    last_checked = current_checked
                    last_progress = now
                elif now - last_progress > BATCH_IDLE_TIMEOUT:
                    print(f"No username could be checked for {BATCH_IDLE_TIMEOUT}s; stopping.")
                    stop_event.set()
                    break
        for t in threads:
            t.join(timeout=2)
        return

    try:
        while not stop_event.is_set():
            stop_event.wait(1)
    except KeyboardInterrupt:
        stop_event.set()
        for t in threads:
            t.join()


if __name__ == "__main__":
    run()
