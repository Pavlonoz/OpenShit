import json
import random
import time
import threading
from pathlib import Path

import requests

PROXY_FILE = Path(__file__).parent / "free-proxy-list.json"

_good_proxies = []
_bad_proxies = set()
_lock = threading.Lock()
_index = 0
_initialized = False


def _make_proxies_dict(proxy_str):
    if proxy_str.startswith("socks4://"):
        return {"http": proxy_str, "https": proxy_str.replace("socks4://", "socks5://")}
    if proxy_str.startswith("socks5://"):
        return {"http": proxy_str, "https": proxy_str}
    if proxy_str.startswith("http://"):
        return {"http": proxy_str, "https": proxy_str.replace("http://", "https://")}
    return {"http": proxy_str, "https": proxy_str}


def load_and_filter():
    global _good_proxies, _bad_proxies, _initialized

    with _lock:
        if _initialized:
            return len(_good_proxies)
        _initialized = True

    if not PROXY_FILE.exists():
        print("[proxy] No free-proxy-list.json found. Using direct connection.")
        return 0

    print("[proxy] Loading proxy list...")
    with open(PROXY_FILE) as f:
        data = json.load(f)

    proxies = data.get("proxies", [])
    print(f"[proxy] {len(proxies)} proxies in file")

    filtered = []
    for p in proxies:
        if not p.get("alive"):
            continue
        if p.get("uptime", 0) < 80:
            continue
        if p.get("timeout", 9999) > 4000:
            continue
        if p.get("anonymity") not in ("elite", "anonymous"):
            continue
        if p.get("ssl") is False:
            continue

        proto = p.get("protocol", "http")
        proxy_str = p.get("proxy", "")
        if not proxy_str or "://" not in proxy_str:
            proxy_str = f"{proto}://{p['ip']}:{p['port']}"

        filtered.append(proxy_str)

    print(f"[proxy] {len(filtered)} passed filters (alive, uptime>80%, timeout<4s, SSL, elite/anon)")

    random.shuffle(filtered)
    _good_proxies = filtered[:100]
    print(f"[proxy] Kept top 100 shuffled proxies for rotation")
    return len(_good_proxies)


def test_proxy_batch(count=10):
    global _good_proxies
    load_and_filter()
    tested = []
    with _lock:
        sample = _good_proxies[:count]
        _good_proxies = _good_proxies[count:]

    print(f"[proxy] Testing {len(sample)} proxies...")
    for proxy_str in sample:
        proxies = _make_proxies_dict(proxy_str)
        try:
            r = requests.get("https://openference.com", proxies=proxies, timeout=8)
            if r.status_code in (200, 301, 302, 403):
                tested.append(proxy_str)
        except Exception:
            _bad_proxies.add(proxy_str)

    with _lock:
        _good_proxies = tested + _good_proxies

    print(f"[proxy] {len(tested)}/{len(sample)} proxies working, pool size: {len(_good_proxies)}")
    return len(tested)


def get_proxy():
    global _index
    load_and_filter()

    with _lock:
        if not _good_proxies:
            return None
        proxy_str = _good_proxies[_index % len(_good_proxies)]
        _index += 1
        return _make_proxies_dict(proxy_str)


def mark_bad(proxy_dict):
    global _good_proxies
    with _lock:
        for val in proxy_dict.values():
            if val in _good_proxies:
                _good_proxies.remove(val)
                _bad_proxies.add(val)


def proxy_count():
    with _lock:
        return len(_good_proxies)


def has_proxies():
    return proxy_count() > 0


def make_request(method, url, **kwargs):
    if not has_proxies():
        return requests.request(method, url, **kwargs)

    proxies = get_proxy()
    if not proxies:
        return requests.request(method, url, **kwargs)

    kwargs["proxies"] = proxies
    try:
        r = requests.request(method, url, **kwargs)
        if r.status_code == 429:
            mark_bad(proxies)
        return r
    except requests.RequestException:
        mark_bad(proxies)
        kwargs.pop("proxies", None)
        return requests.request(method, url, **kwargs)


if __name__ == "__main__":
    load_and_filter()
    if has_proxies():
        test_proxy_batch(10)
        print(f"\nWorking proxies: {proxy_count()}")
        for _ in range(3):
            p = get_proxy()
            print(f"  {p}")
    else:
        print("No proxies available.")
