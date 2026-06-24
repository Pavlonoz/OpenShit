import json
import random
import socket
import threading
import time
from pathlib import Path

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

PROXY_FILE = Path(__file__).parent / "free-proxy-list.json"
LIVE_PROXY_CACHE = Path(__file__).parent / "live_proxies.json"
RESIDENTIAL_FILE = Path(__file__).parent / "residential_proxies.txt"

_good_proxies = []
_bad_proxies = {}
BAD_COOLDOWN = 1800
_lock = threading.Lock()
_index = 0
_initialized = False
_CACHE_TTL = 600
_last_fetch = 0

PROXY_SOURCES = [
    {
        "name": "proxyscrape_http",
        "url": "https://api.proxyscrape.com/v3/free-proxy-list/get?request=display_proxies&protocol=http&proxy_format=protocolipport&format=json&timeout=3000&anonymity=elite,anonymous&ssl=all",
    },
    {
        "name": "proxyscrape_socks5",
        "url": "https://api.proxyscrape.com/v3/free-proxy-list/get?request=display_proxies&protocol=socks5&proxy_format=protocolipport&format=json&timeout=4000&anonymity=elite,anonymous&ssl=all",
    },
    {
        "name": "geonode_elite",
        "url": "https://proxylist.geonode.com/api/proxy-list?limit=100&page=1&sort_by=lastChecked&sort_type=desc&protocols=http,https,socks5&anonymityLevel=elite&filterUpTime=80",
    },
    {
        "name": "openproxy_http",
        "url": "https://api.openproxylist.xyz/http.txt",
        "is_text": True,
    },
    {
        "name": "openproxy_socks5",
        "url": "https://api.openproxylist.xyz/socks5.txt",
        "is_text": True,
    },
    {
        "name": "pubproxy",
        "url": "https://api.pubproxy.com/v1/proxies?limit=20&type=http,https&anonymity=elite",
    },
]

try:
    import socks as _socks_mod
    _original_create_connection = _socks_mod.create_connection
    def _local_dns_create_connection(address, timeout=None, source_address=None, **kwargs):
        host, port = address
        try:
            ip = socket.gethostbyname(host)
        except Exception:
            ip = host
        return _original_create_connection((ip, port), timeout, source_address, **kwargs)
    _socks_mod.create_connection = _local_dns_create_connection
except ImportError:
    pass


def _load_residential_proxies():
    results = []
    if RESIDENTIAL_FILE.exists():
        try:
            with open(RESIDENTIAL_FILE) as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split(":")
                    if len(parts) == 4:
                        ip, port, user, pw = parts
                        proxy_str = f"socks5://{user}:{pw}@{ip}:{port}"
                        results.append(proxy_str)
            print(f"[proxy] Loaded {len(results)} residential proxies")
        except Exception as e:
            print(f"[proxy] Error loading residential: {e}")
    return results


def _make_proxies_dict(proxy_str):
    if proxy_str.startswith("socks4://"):
        return {"http": proxy_str, "https": proxy_str.replace("socks4://", "socks5://")}
    if proxy_str.startswith("socks5://"):
        return {"http": proxy_str, "https": proxy_str}
    if proxy_str.startswith("http://"):
        return {"http": proxy_str, "https": proxy_str.replace("http://", "https://")}
    return {"http": proxy_str, "https": proxy_str}


def _proxies_from_item(item):
    if item is None:
        return None
    scheme = str(item.get("protocol", "http")).lower()
    ip = item.get("ip", "")
    port = str(item.get("port", ""))
    if ip and port:
        p = f"{scheme}://{ip}:{port}"
        return p
    proxy_str = item.get("proxy", "")
    if proxy_str:
        if "://" not in proxy_str:
            proxy_str = f"{scheme}://{proxy_str}"
        return proxy_str
    return None


def _fetch_source(source):
    results = []
    try:
        if source.get("is_text"):
            r = requests.get(source["url"], timeout=8)
            for line in r.text.strip().split("\n"):
                line = line.strip()
                if line and ":" in line and not line.startswith("#"):
                    if "://" not in line:
                        line = f"http://{line}"
                    results.append(line)
        else:
            r = requests.get(source["url"], headers={"User-Agent": "Mozilla/5.0"}, timeout=8)
            data = r.json()
            items = data if isinstance(data, list) else data.get("data", data.get("proxies", data.get("results", data.get("list", []))))
            if isinstance(items, list):
                for item in items:
                    p = _proxies_from_item(item)
                    if p:
                        results.append(p)
            elif isinstance(items, dict):
                for ip_port in items:
                    if "://" not in ip_port:
                        ip_port = f"http://{ip_port}"
                    results.append(ip_port)
        return results
    except Exception:
        return []


def _load_live_cache():
    if LIVE_PROXY_CACHE.exists():
        try:
            with open(LIVE_PROXY_CACHE) as f:
                cache = json.load(f)
            if time.time() - cache.get("fetched_at", 0) < _CACHE_TTL:
                return cache.get("proxies", [])
        except Exception:
            pass
    return None


def _save_live_cache(proxies):
    try:
        with open(LIVE_PROXY_CACHE, "w") as f:
            json.dump({"fetched_at": time.time(), "proxies": proxies}, f)
    except Exception:
        pass


def _fetch_live_proxies(force=False):
    global _last_fetch
    now = time.time()
    if not force and (now - _last_fetch < _CACHE_TTL):
        return []

    cached = _load_live_cache()
    if cached and not force:
        _last_fetch = now
        print(f"[proxy] Loaded {len(cached)} proxies from live cache")
        return cached

    print("[proxy] Fetching fresh proxies from multiple sources...")
    all_p = []
    for source in PROXY_SOURCES:
        try:
            fetched = _fetch_source(source)
            if fetched:
                all_p.extend(fetched)
                print(f"  {source['name']}: {len(fetched)}")
        except Exception:
            continue
    seen = set()
    unique = []
    for p in all_p:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    _save_live_cache(unique)
    _last_fetch = now
    print(f"[proxy] Fetched {len(unique)} unique proxies from live sources")
    return unique


def load_and_filter():
    global _good_proxies, _bad_proxies, _initialized, _last_fetch

    with _lock:
        if _initialized:
            return len(_good_proxies)
        _initialized = True

    all_raw = []

    residential = _load_residential_proxies()
    all_raw.extend(residential)

    if residential:
        _good_proxies = residential[:]
        print(f"[proxy] Pool: {len(_good_proxies)} residential proxies (skipping public sources)")
        return len(_good_proxies)

    if PROXY_FILE.exists():
        try:
            print("[proxy] Loading static proxy list...")
            with open(PROXY_FILE) as f:
                data = json.load(f)
            proxies = data.get("proxies", [])
            print(f"[proxy] {len(proxies)} proxies in static file")
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
                all_raw.append(proxy_str)
            print(f"[proxy] {len(all_raw) - len(residential)} passed static filters")
        except Exception as e:
            print(f"[proxy] Error loading static list: {e}")

    live = _fetch_live_proxies()
    all_raw.extend(live)

    residential_set = set(residential)
    non_res = [p for p in all_raw if p not in residential_set]
    random.shuffle(non_res)
    _good_proxies = residential + non_res[:200]
    print(f"[proxy] Pool: {len(_good_proxies)} proxies ready ({len(residential)} residential priority)")
    return len(_good_proxies)


def test_proxy_batch(count=5):
    global _good_proxies
    load_and_filter()
    with _lock:
        sample = _good_proxies[:count]
        _good_proxies = _good_proxies[count:]

    print(f"[proxy] Testing {len(sample)} proxies...")
    working = []
    for proxy_str in sample:
        proxies = _make_proxies_dict(proxy_str)
        try:
            r = requests.get("https://httpbin.org/ip", proxies=proxies, timeout=5, verify=False)
            if r.status_code == 200 and "origin" in r.json():
                working.append(proxy_str)
                continue
        except Exception:
            pass
        try:
            r = requests.get("https://openference.com", proxies=proxies, timeout=6, verify=False)
            if r.status_code in (200, 301, 302, 403):
                working.append(proxy_str)
                continue
        except Exception:
            pass
        _bad_proxies[proxy_str] = time.time()

    with _lock:
        _good_proxies = working + _good_proxies

    print(f"[proxy] {len(working)}/{len(sample)} working, pool: {len(_good_proxies)}")
    return len(working)


def get_proxy():
    global _index
    load_and_filter()

    with _lock:
        _recover_expired()
        if not _good_proxies:
            return None
        proxy_str = _good_proxies[_index % len(_good_proxies)]
        _index += 1
        return _make_proxies_dict(proxy_str)


def get_proxy_str():
    global _index
    load_and_filter()

    with _lock:
        _recover_expired()
        if not _good_proxies:
            return None
        proxy_str = _good_proxies[_index % len(_good_proxies)]
        _index += 1
        return proxy_str


def _recover_expired():
    now = time.time()
    recovered = [p for p, t in _bad_proxies.items() if now - t > BAD_COOLDOWN]
    for p in recovered:
        del _bad_proxies[p]
        if p not in _good_proxies:
            _good_proxies.append(p)
    if recovered:
        print(f"[proxy] Recovered {len(recovered)} proxies (cooldown expired)")


def mark_bad(proxy_dict):
    global _good_proxies
    with _lock:
        for val in proxy_dict.values():
            if val in _good_proxies:
                _good_proxies.remove(val)
                _bad_proxies[val] = time.time()


def mark_bad_str(proxy_str):
    global _good_proxies
    with _lock:
        if proxy_str in _good_proxies:
            _good_proxies.remove(proxy_str)
            _bad_proxies[proxy_str] = time.time()


def proxy_count():
    with _lock:
        now = time.time()
        recoverable = sum(1 for t in _bad_proxies.values() if now - t > BAD_COOLDOWN)
        return len(_good_proxies) + recoverable


def has_proxies():
    return proxy_count() > 0


def make_request(method, url, **kwargs):
    if not has_proxies():
        return requests.request(method, url, **kwargs)

    kwargs.setdefault("verify", False)
    kwargs.setdefault("timeout", 20)

    max_attempts = 3
    last_exc = None
    for attempt in range(max_attempts):
        proxies = get_proxy()
        if not proxies:
            return requests.request(method, url, **kwargs)

        try:
            r = requests.request(method, url, proxies=proxies, **kwargs)
            if r.status_code == 429:
                mark_bad(proxies)
                continue
            if r.status_code in (407, 502, 503):
                mark_bad(proxies)
                continue
            return r
        except (requests.ConnectTimeout, requests.ConnectionError, requests.ReadTimeout) as e:
            mark_bad(proxies)
            last_exc = e
            continue
        except Exception as e:
            mark_bad(proxies)
            last_exc = e
            continue

    try:
        return requests.request(method, url, **kwargs)
    except Exception:
        if last_exc:
            raise last_exc
        raise


def refresh_proxies():
    global _initialized, _good_proxies, _bad_proxies
    with _lock:
        _initialized = False
        _good_proxies = []
        _bad_proxies = {}
    _fetch_live_proxies(force=True)
    return load_and_filter()


if __name__ == "__main__":
    load_and_filter()
    if has_proxies():
        for _ in range(3):
            p = get_proxy_str()
            print(f"  {p}")
    else:
        print("No proxies available.")
