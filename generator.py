import random
import requests
import time
import threading
import urllib3
from typing import Dict, List, Optional

endpoint = "https://discord.com/api/v9/unique-username/username-attempt-unauthed"
username_length = 3
rate_limit_seconds = 1.0
proxy_file = "proxies.txt"
proxy_fail_limit = 2
threads_number = 3

characters = [
    'a','b','c','d','e','f','g','h','i','j','k','l','m',
    'n','o','p','q','r','s','t','u','v','w','x','y','z',
    'A','B','C','D','E','F','G','H','I','J','K','L','M',
    'N','O','P','Q','R','S','T','U','V','W','X','Y','Z',
    '0','1','2','3','4','5','6','7','8','9','_'
]

characters_len = len(characters)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def load_proxies(file_path: str) -> List[str]:
    proxy_urls: List[str] = []

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue

                proxy_url = line
                if "://" not in proxy_url:
                    proxy_url = f"http://{proxy_url}"

                proxy_urls.append(proxy_url)
    except FileNotFoundError:
        print(f"Proxy file not found: {file_path}")

    return proxy_urls


def format_proxy(proxy_url: str) -> Dict[str, str]:
    return {"http": proxy_url, "https": proxy_url}


proxies = load_proxies(proxy_file)
proxy_count = len(proxies)
proxy_lock = threading.Lock()
proxy_failures: Dict[str, int] = {}
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


def remove_proxy(proxy_url: str) -> None:
    global proxies, proxy_count

    with proxy_lock:
        if proxy_url in proxies:
            proxies.remove(proxy_url)
            proxy_count = len(proxies)
            print(f"Removed failing proxy: {proxy_url} (remaining {proxy_count})")


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
            return False

        proxy = format_proxy(proxy_url) if proxy_url else None

        try:
            response = session.post(endpoint, json=payload, proxies=proxy, timeout=15)
        except requests.exceptions.SSLError as ssl_exc:
            if not is_ignorable_proxy_error(ssl_exc):
                print(f"SSL error via proxy {proxy_url}: {ssl_exc}")
            continue  # retry with another proxy
        except requests.exceptions.RequestException as exc:
            if not is_ignorable_proxy_error(exc):
                print(f"Request error via proxy {proxy_url}: {exc}")
            continue  # retry with another proxy

        if response.status_code == 200:
            try:
                taken = response.json().get("taken", False)
                valid = not taken
            except ValueError:
                print("Invalid JSON response")
                continue  # retry
            print(f"{username} -> taken={taken} via {proxy_url}")
            return valid

        if response.status_code == 429:
            print(f"Rate limited (429) via {proxy_url}; switching proxy.")
            with proxy_lock:
                proxy_failures[proxy_url] = proxy_failures.get(proxy_url, 0) + 1
                if proxy_failures[proxy_url] >= proxy_fail_limit:
                    remove_proxy(proxy_url)
            # switch proxy for this thread
            thread_local.proxy = get_next_proxy()
            return False  # don't retry username, just switch proxy

        print(f"Error: {response.status_code} - {response.text} via {proxy_url}")
        continue  # retry with another proxy

    # if all attempts failed, return False
    return False


def worker():
    thread_name = threading.current_thread().name
    thread_local.proxy = get_next_proxy()
    print(f"{thread_name} started with proxy: {thread_local.proxy}")
    while True:
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
