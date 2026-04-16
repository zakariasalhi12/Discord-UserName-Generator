# import requests
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
    proxy_url = get_random_proxy()
    proxy = format_proxy(proxy_url) if proxy_url else None

    try:
        response = session.post(endpoint, json=payload, proxies=proxy, timeout=15)
    except requests.exceptions.SSLError as ssl_exc:
        if proxy_url:
            with proxy_lock:
                proxy_failures[proxy_url] = proxy_failures.get(proxy_url, 0) + 1
                if proxy_failures[proxy_url] >= proxy_fail_limit:
                    remove_proxy(proxy_url)
        if not is_ignorable_proxy_error(ssl_exc):
            print(f"SSL error via proxy {proxy_url}: {ssl_exc}")
        return False
    except requests.exceptions.RequestException as exc:
        if proxy_url:
            with proxy_lock:
                proxy_failures[proxy_url] = proxy_failures.get(proxy_url, 0) + 1
                if proxy_failures[proxy_url] >= proxy_fail_limit:
                    remove_proxy(proxy_url)
        if not is_ignorable_proxy_error(exc):
            print(f"Request error via proxy {proxy_url}: {exc}")
        return False

    if response.status_code == 200:
        try:
            taken = response.json().get("taken", False)
            valid = not taken
        except ValueError:
            print("Invalid JSON response")
            return False
        print(f"{username} -> taken={taken} via {proxy_url}")
        return valid

    if response.status_code == 429:
        print(f"Rate limited (429) via {proxy_url}; rotating proxy and sleeping.")
        if proxy_url:
            with proxy_lock:
                proxy_failures[proxy_url] = proxy_failures.get(proxy_url, 0) + 1
                if proxy_failures[proxy_url] >= proxy_fail_limit:
                    remove_proxy(proxy_url)
        time.sleep(rate_limit_seconds * 2)
        return False

    print(f"Error: {response.status_code} - {response.text} via {proxy_url}")
    if proxy_url:
        with proxy_lock:
            proxy_failures[proxy_url] = proxy_failures.get(proxy_url, 0) + 1
            if proxy_failures[proxy_url] >= proxy_fail_limit:
                remove_proxy(proxy_url)
    return False


def worker():
    thread_name = threading.current_thread().name
    print(f"{thread_name} started")
    while True:
        username = pickRandomUsername()
        print(f"{thread_name} checking {username}")

        if checkUsername(username):
            print(f"Valid username found: {username}")
            appendToFile(username)

        time.sleep(rate_limit_seconds)


if __name__ == "__main__":
    threads = []
    for i in range(3):
        t = threading.Thread(target=worker, name=f"Worker-{i+1}")
        t.daemon = True
        threads.append(t)
        t.start()

    for t in threads:
        t.join()
