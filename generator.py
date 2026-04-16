import random
import requests
import time
import threading
import urllib3
from typing import Dict, List, Optional

endpoint = "https://discord.com/api/v9/unique-username/username-attempt-unauthed"
proxy_api_url = "https://api.proxyscrape.com/v4/free-proxy-list/get?request=display_proxies&proxy_format=protocolipport&format=text&timeout=619"
username_length = 3
rate_limit_seconds = 0
rate_limit_backoff = 5  # Delay when getting 429
max_proxy_response_time = 9  # Max response time in seconds
proxy_fail_limit = 2
threads_number = 3
show_proxy_logs = False  # Set to True to see proxy logs, False to only see usernames

characters = [
    'a','b','c','d','e','f','g','h','i','j','k','l','m',
    'n','o','p','q','r','s','t','u','v','w','x','y','z',
    'A','B','C','D','E','F','G','H','I','J','K','L','M',
    'N','O','P','Q','R','S','T','U','V','W','X','Y','Z',
    '0','1','2','3','4','5','6','7','8','9','_'
]

characters_len = len(characters)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def load_proxies(api_url: str) -> List[str]:
    proxy_urls: List[str] = []

    try:
        print("Fetching proxies from API...")
        response = requests.get(api_url, timeout=10)
        response.raise_for_status()
        
        for raw_line in response.text.split('\n'):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            proxy_url = line
            if "://" not in proxy_url:
                proxy_url = f"http://{proxy_url}"

            proxy_urls.append(proxy_url)
        
        print(f"Loaded {len(proxy_urls)} proxies from API")
    except requests.exceptions.RequestException as e:
        print(f"Failed to fetch proxies from API: {e}")

    return proxy_urls


def format_proxy(proxy_url: str) -> Dict[str, str]:
    return {"http": proxy_url, "https": proxy_url}


proxies = load_proxies(proxy_api_url)
proxy_count = len(proxies)
proxy_lock = threading.Lock()
proxy_failures: Dict[str, int] = {}
proxy_response_times: Dict[str, float] = {}  # Track response times per proxy
proxy_index = 0
thread_local = threading.local()

session = requests.Session()
session.trust_env = False
session.verify = False
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
})


def get_random_proxy() -> Optional[str]:
    with proxy_lock:
        if proxy_count == 0:
            return None
        return random.choice(proxies)


def get_next_proxy() -> Optional[str]:
    global proxy_index
    with proxy_lock:
        if proxy_count == 0:
            return None
        proxy = proxies[proxy_index % proxy_count]
        proxy_index += 1
        return proxy


def remove_proxy(proxy_url: str, reason: str = "failure") -> None:
    global proxies, proxy_count

    with proxy_lock:
        if proxy_url in proxies:
            proxies.remove(proxy_url)
            proxy_count = len(proxies)
            if show_proxy_logs:
                if reason == "timeout":
                    print(f"❌ Removed slow proxy (>{max_proxy_response_time}s): {proxy_url} (remaining {proxy_count})")
                else:
                    print(f"❌ Removed failing proxy: {proxy_url} (remaining {proxy_count})")
        # Clean up tracking data
        if proxy_url in proxy_response_times:
            del proxy_response_times[proxy_url]


def is_ignorable_proxy_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        token in message
        for token in [
            "certificate verify failed",
            "bad request",
            "connection to discord.com timed out",
            "tunnel connection failed",
            "proxyerror",
            "sockshttpsconnectionpool",
            "connecttimeouterror",
            "conncet timeout",
            "unable to connect to proxy",
            "ssleoferror",
        ]
    )


def appendToFile(username: str) -> None:
    with open("result.txt", "a", encoding="utf-8") as f:
        f.write(username + "\n")
    print(f"Appended {username} to result.txt")


def pickRandomUsername() -> str:
    username = ""

    for _ in range(username_length):
        username += random.choice(characters)

    return username


def checkUsername(username: str) -> bool:
    payload = {"username": username}
    max_retries = 3

    for attempt in range(max_retries):
        if attempt == 0:
            proxy_url = getattr(thread_local, 'proxy', None)
        else:
            proxy_url = get_random_proxy()

        if proxy_url is None:
            print("No proxies available for checking username.")
            return False

        proxy = format_proxy(proxy_url) if proxy_url else None

        try:
            start_time = time.time()
            response = session.post(endpoint, json=payload, proxies=proxy, timeout=15)
            response_time = time.time() - start_time
            
            # Track and check response time
            with proxy_lock:
                proxy_response_times[proxy_url] = response_time
            
            # Remove proxy if response time exceeds threshold
            if response_time > max_proxy_response_time:
                if show_proxy_logs:
                    print(f"⏱️  Slow proxy detected ({response_time:.2f}s > {max_proxy_response_time}s): {proxy_url}")
                remove_proxy(proxy_url, reason="timeout")
                continue  # retry with another proxy
                
        except requests.exceptions.Timeout:
            if show_proxy_logs:
                print(f"⏱️  Timeout via proxy {proxy_url} - removing slow proxy")
            remove_proxy(proxy_url, reason="timeout")
            continue  # retry with another proxy
        except requests.exceptions.SSLError as ssl_exc:
            if show_proxy_logs and not is_ignorable_proxy_error(ssl_exc):
                print(f"SSL error via proxy {proxy_url}: {ssl_exc}")
            continue  # retry with another proxy
        except requests.exceptions.RequestException as exc:
            if show_proxy_logs and not is_ignorable_proxy_error(exc):
                print(f"Request error via proxy {proxy_url}: {exc}")
            continue  # retry with another proxy

        if response.status_code == 200:
            try:
                taken = response.json().get("taken", False)
                valid = not taken
            except ValueError:
                if show_proxy_logs:
                    print("Invalid JSON response")
                continue  # retry
            if valid:
                print(f"✅ VALID USERNAME FOUND: {username}")
            elif show_proxy_logs:
                print(f"✓ {username} -> taken={taken} ({response_time:.2f}s) via {proxy_url}")
            time.sleep(rate_limit_seconds)  # Add delay after successful request
            return valid

        if response.status_code == 429:
            if show_proxy_logs:
                print(f"⚠️  Rate limited (429) via {proxy_url}; switching proxy.")
            with proxy_lock:
                proxy_failures[proxy_url] = proxy_failures.get(proxy_url, 0) + 1
                if proxy_failures[proxy_url] >= proxy_fail_limit:
                    remove_proxy(proxy_url)
            # switch proxy for this thread
            thread_local.proxy = get_random_proxy()
            if thread_local.proxy is None:
                if show_proxy_logs:
                    print(f"No proxies available after rate limit on {proxy_url}")
                return False
            if show_proxy_logs:
                print(f"Switched to proxy: {thread_local.proxy}")
            time.sleep(rate_limit_backoff)  # Wait longer after rate limit
            return False  # don't retry username, just switch proxy

        if show_proxy_logs:
            print(f"Error: {response.status_code} - {response.text} via {proxy_url}")
        time.sleep(rate_limit_seconds)  # Add delay after other errors
        continue  # retry with another proxy

    # if all attempts failed, return False
    return False


def worker():
    thread_name = threading.current_thread().name
    thread_local.proxy = get_random_proxy()
    if thread_local.proxy is None:
        print(f"{thread_name}: No proxies available, stopping.")
        return
    if show_proxy_logs:
        print(f"{thread_name} started with proxy: {thread_local.proxy}")
    while True:
        # Check if proxy is still available before making request
        if thread_local.proxy is None:
            thread_local.proxy = get_random_proxy()
            if thread_local.proxy is None:
                print(f"{thread_name}: No proxies available, stopping.")
                break
        
        username = pickRandomUsername()
        if checkUsername(username):
            print(f"Valid username found: {username}")
            appendToFile(username)


if __name__ == "__main__":
    threads = []
    for i in range(threads_number):
        t = threading.Thread(target=worker, name=f"Worker-{i+1}")
        t.daemon = True
        threads.append(t)
        t.start()

    for t in threads:
        t.join()
