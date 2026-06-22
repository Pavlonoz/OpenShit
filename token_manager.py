import json
import re
import time
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

from proxy_rotator import make_request as proxy_request, load_and_filter, test_proxy_batch, has_proxies, proxy_count

CONFIG_PATH = Path(__file__).parent / "config.json"
TOKENS_PATH = Path(__file__).parent / "tokens.json"
NO_INPUT = "--no-input" in sys.argv or "--no-interactive" in sys.argv
SKIP_REGISTER = "--no-register" in sys.argv or "--skip-register" in sys.argv

MAILTM_APIS = ["https://api.mail.tm", "https://api.mail.gw"]


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def save_tokens(tokens):
    with open(TOKENS_PATH, "w") as f:
        json.dump(tokens, f, indent=2)
    print(f"Saved {len(tokens)} tokens to {TOKENS_PATH}")


def load_tokens():
    if TOKENS_PATH.exists():
        with open(TOKENS_PATH) as f:
            return json.load(f)
    return []


def make_headers(session_token=None, api_key=None):
    headers = {
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
        "Origin": "https://openference.com",
        "User-Agent": load_config().get("registration_user_agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"),
    }
    if session_token:
        headers["Authorization"] = f"Bearer {session_token}"
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _mailtm_request(method, path, json_data=None, headers=None, timeout=15):
    for base in MAILTM_APIS:
        url = f"{base}{path}"
        try:
            if method == "post":
                r = requests.post(url, json=json_data, headers=headers or {}, timeout=timeout)
            else:
                r = requests.get(url, headers=headers or {}, timeout=timeout)
            if r.status_code in (200, 201):
                return r
        except Exception:
            continue
    return None


def create_mailtm_account(config, index):
    username = config.get("email_base", "user").split("@")[0] + str(index)
    password = config["account_password"]

    r = _mailtm_request("get", "/domains")
    if r is None:
        print(f"  Failed to fetch mail.tm domains")
        return None, None
    domains = r.json().get("hydra:member", [])
    if not domains:
        print(f"  No mail.tm domains available")
        return None, None
    domain = domains[0]["domain"]
    email_addr = f"{username}@{domain}"

    r = _mailtm_request("post", "/accounts", json_data={"address": email_addr, "password": password})
    if r is None:
        print(f"  Failed to create mail.tm account")
        return None, None
    data = r.json()
    return data.get("address", email_addr), password


def poll_mailtm_for_verification(config, email_addr, password):
    r = _mailtm_request("post", "/token", json_data={"address": email_addr, "password": password})
    if r is None:
        return None
    token = r.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    r = _mailtm_request("get", "/messages", headers=headers)
    if r is None:
        return None
    messages = r.json().get("hydra:member", [])
    for msg in messages:
        msg_id = msg["id"]
        r = _mailtm_request("get", f"/messages/{msg_id}", headers=headers)
        if r is None:
            continue
        body = r.json().get("text", "") or r.json().get("html", "") or ""
        pattern = r'https://openference\.com/auth/verify-email\?token=[^\s"\'<>&]+'
        match = re.search(pattern, body)
        if match:
            return match.group(0)
    return None


def register_account(config, email, password):
    cfg = config
    url = f"{cfg.get('openference_base', 'https://openference.com')}/auth/register"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    payload = {
        "email": email,
        "password": password,
        "acceptedTos": True,
        "acceptedPrivacy": True,
        "acceptedAt": now,
    }
    headers = {
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
        "Origin": "https://openference.com",
        "User-Agent": config.get("registration_user_agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"),
    }

    for attempt in range(10):
        print(f"  Registering {email} (attempt {attempt+1}) ...")
        try:
            r = proxy_request("post", url, json=payload, headers=headers, timeout=20)
        except Exception as e:
            print(f"  Error: {e}")
            time.sleep(1)
            continue

        print(f"  Register response: {r.status_code}")
        if r.status_code in (200, 201):
            data = r.json()
            session = data.get("session") or data.get("token") or data.get("session_token")
            return True, session
        if r.status_code == 429:
            print(f"  Rate limited (429). Switching proxy and retrying...")
            time.sleep(0.5)
            continue
        if r.status_code == 409:
            print(f"  Email already registered")
            return False, None
        print(f"  Register body: {r.text[:300]}")
        return False, None

    print(f"  All 10 proxy attempts failed.")
    return False, None


def login(config, email, password):
    url = f"{config.get('openference_base', 'https://openference.com')}/auth/login"
    payload = {"email": email, "password": password}
    print(f"  Logging in as {email} ...")
    r = requests.post(url, json=payload, headers=make_headers(), timeout=30)
    print(f"  Login response: {r.status_code}")
    if r.status_code in (200, 201):
        data = r.json()
        session = (
            data.get("session")
            or data.get("token")
            or data.get("session_token")
            or data.get("access_token")
            or data.get("api_key")
        )
        if session:
            return session
        if "user" in data and "id" in data.get("user", {}):
            for key in data:
                if isinstance(data[key], str) and data[key].startswith("session_"):
                    return data[key]
    if r.status_code == 403 and "email_unverified" in r.text:
        print(f"  Email not yet verified for {email}")
    print(f"  Login body: {r.text[:300]}")
    return None


def verify_email(config, verification_url):
    print(f"  Verifying email: {verification_url[:80]}...")
    r = requests.get(verification_url, headers=make_headers(), timeout=30, allow_redirects=True)
    print(f"  Verify response: {r.status_code}")
    return r.status_code in (200, 301, 302, 303, 307, 308)


def fetch_plan_limits(config, session_token):
    url = f"{config.get('openference_base', 'https://openference.com')}/api/user/me"
    r = requests.get(url, headers=make_headers(session_token=session_token), timeout=30)
    if r.status_code == 200:
        data = r.json()
        plan = data.get("plan", {})
        limits = data.get("limits", {})
        return {
            "plan": plan.get("name", "Unknown"),
            "requests_per_week": limits.get("requestsPerWeek") or plan.get("requestsPerWeek", 1250),
            "requests_per_window": limits.get("windowLimit", {}).get("requests") or plan.get("requestsPerWindow", 50),
            "window_hours": limits.get("windowLimit", {}).get("hours") or plan.get("windowHours", 5),
            "max_rpm": limits.get("maxRpm") or plan.get("maxRpm", 100),
        }
    return None


def create_api_token(config, session_token, name="auto-token"):
    url = f"{config.get('openference_base', 'https://openference.com')}/api/user/tokens"
    payload = {
        "name": name,
        "token_limit": None,
        "hourly_limit": None,
        "model_restrictions": None,
        "ip_allowlist": None,
        "expires_at": None,
    }
    print(f"  Creating API token '{name}' ...")
    r = requests.post(url, json=payload, headers=make_headers(session_token=session_token), timeout=30)
    print(f"  Token creation response: {r.status_code}")
    if r.status_code in (200, 201):
        data = r.json()
        token_info = data.get("token", {})
        api_key = token_info.get("api_key", "")
        token_id = token_info.get("id", "")
        return api_key, token_id
    print(f"  Token body: {r.text[:300]}")
    return None, None


def process_one_account(config, index):
    email_addr, temp_password = create_mailtm_account(config, index)
    if not email_addr:
        return None

    password = config["account_password"]
    print(f"\n{'='*60}")
    print(f"Processing account #{index}: {email_addr}")
    print(f"{'='*60}")

    success, _ = register_account(config, email_addr, password)
    if not success:
        if SKIP_REGISTER:
            print(f"  Skipping registration (--no-register). Proceeding with verification...")
        else:
            print(f"  Registration failed for {email_addr}")
            return None

    verify_url = None
    for attempt in range(8):
        if attempt > 0:
            time.sleep(4)
        verify_url = poll_mailtm_for_verification(config, email_addr, temp_password)
        if verify_url:
            print(f"  Found verification link on attempt {attempt+1}!")
            break
        if attempt == 0:
            pass
        elif attempt < 3:
            print(f"  Waiting for email... ({attempt+1}/8)")

    if not verify_url:
        if NO_INPUT:
            print(f"  Could not auto-verify. Skipping verification.")
        else:
            print(f"\n  {'='*50}")
            print(f"  Could not auto-verify via temp mail.")
            print(f"  OPTION 1: Paste the verification link below")
            print(f"  OPTION 2: Press Enter to skip (account may not work)")
            print(f"  {'='*50}")
            manual = input(f"  Link: ").strip()
            if manual:
                if "openference.com/auth/verify-email" in manual:
                    verify_url = manual
                else:
                    print(f"  That doesn't look like a verification link. Skipping.")
            else:
                print(f"  Skipping verification. Login may fail.")

    if verify_url:
        if verify_email(config, verify_url):
            print(f"  Email verified successfully!")
        else:
            print(f"  Email verification request returned non-200, but may still be verified.")

    time.sleep(3)
    session_token = login(config, email_addr, password)
    if not session_token:
        print(f"  Login failed, retrying after delay...")
        time.sleep(3)
        session_token = login(config, email_addr, password)
    if not session_token:
        print(f"  Could not login as {email_addr}. Email may not be verified yet.")
        return None

    print(f"  Session token: {session_token[:40]}...")

    time.sleep(1)
    api_key, token_id = create_api_token(config, session_token, f"auto-token-{index}")
    if not api_key:
        print(f"  Failed to create API token for {email_addr}")
        return None

    token_entry = {
        "index": index,
        "email": email_addr,
        "session_token": session_token,
        "api_key": api_key,
        "token_id": token_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        plan_info = fetch_plan_limits(config, session_token)
        if plan_info:
            token_entry.update(plan_info)
    except Exception:
        pass

    print(f"  API key: {api_key}")
    print(f"  Account #{index} complete!")
    return token_entry


def main():
    config = load_config()
    count = config.get("account_count", 5)
    start = config.get("start_index", 1)
    delay_reg = config.get("delay_between_registrations", 3)

    existing = load_tokens()
    existing_indices = {t["index"] for t in existing}
    new_tokens = []

    print(f"\n{'='*60}")
    print(f"Openshit Token Manager")
    print(f"{'='*60}")

    n_proxies = load_and_filter()
    if n_proxies > 0:
        test_proxy_batch(10)
        if not has_proxies():
            print("[!] No working proxies. Will use direct connection (may be rate-limited).")
        else:
            print(f"[proxy] {proxy_count()} proxies available. Registration via rotating proxies.")
            delay_reg = max(0.5, delay_reg - 2)
    else:
        print("[!] No proxy file found. Direct connection only.")

    for i in range(start, start + count):
        if i in existing_indices:
            print(f"\nSkipping index #{i} (already in tokens.json)")
            continue

        entry = process_one_account(config, i)
        if entry:
            new_tokens.append(entry)

        if i < start + count - 1:
            print(f"\nWaiting {delay_reg:.1f}s before next registration...")
            time.sleep(delay_reg)

    all_tokens = existing + new_tokens
    if all_tokens:
        save_tokens(all_tokens)
        free_plan = all_tokens[0]
        total_weekly = sum(
            t.get("requests_per_week", 0) or 0 for t in all_tokens
        )
        print(f"\n{'='*60}")
        print(f"SUMMARY: {len(all_tokens)} total accounts")
        print(f"  Newly created: {len(new_tokens)}")
        print(f"  Total combined weekly requests: {total_weekly}")
        print(f"  Tokens saved to: {TOKENS_PATH}")
        print(f"{'='*60}")
    else:
        print("No tokens created or loaded.")


if __name__ == "__main__":
    main()
