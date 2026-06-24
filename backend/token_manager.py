import json
import random
import re
import sys
import time
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from proxy_rotator import make_request as proxy_request, load_and_filter, test_proxy_batch, has_proxies, proxy_count
from email_providers import create_email, poll_email

CONFIG_PATH = Path(os.environ.get("OSH_CONFIG_PATH", str(Path(__file__).parent / "config.json")))
TOKENS_PATH = Path(os.environ.get("OSH_TOKENS_PATH", str(Path(__file__).parent / "tokens.json")))
NO_INPUT = True
SKIP_REGISTER = False


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


def make_headers(session_token=None, api_key=None, config=None):
    if config is None:
        config = load_config()
    headers = {
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Content-Type": "application/json",
        "Origin": "https://openference.com",
        "User-Agent": config.get("registration_user_agent",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"),
    }
    if session_token:
        headers["Authorization"] = f"Bearer {session_token}"
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def register_account(config, email, password):
    url = f"{config.get('openference_base', 'https://openference.com')}/auth/register"
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

    for attempt in range(3):
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
            return "ok", "registered", session
        if r.status_code == 429:
            return "rate_limited", "rate_limited", None
        if r.status_code == 400:
            return "rejected", r.text[:300], None
        if r.status_code == 409:
            return "rejected", "already_exists", None
        print(f"  Register body: {r.text[:300]}")
        time.sleep(1)

    return "failed", "all_attempts_failed", None


def login(config, email, password):
    url = f"{config.get('openference_base', 'https://openference.com')}/auth/login"
    payload = {"email": email, "password": password}
    print(f"  Logging in as {email} ...")
    try:
        r = proxy_request("post", url, json=payload, headers=make_headers(config=config), timeout=30)
    except Exception as e:
        print(f"  Login proxy error: {e}")
        try:
            r = requests.post(url, json=payload, headers=make_headers(config=config), timeout=30)
        except Exception:
            return None

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
    try:
        r = proxy_request("get", verification_url, headers=make_headers(config=config), timeout=30, allow_redirects=True)
    except Exception:
        try:
            r = requests.get(verification_url, headers=make_headers(config=config), timeout=30, allow_redirects=True)
        except Exception:
            return False
    print(f"  Verify response: {r.status_code}")
    return r.status_code in (200, 301, 302, 303, 307, 308)


def fetch_plan_limits(config, session_token):
    url = f"{config.get('openference_base', 'https://openference.com')}/api/user/me"
    try:
        r = proxy_request("get", url, headers=make_headers(session_token=session_token, config=config), timeout=30)
    except Exception:
        try:
            r = requests.get(url, headers=make_headers(session_token=session_token, config=config), timeout=30)
        except Exception:
            return None

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
    try:
        r = proxy_request("post", url, json=payload, headers=make_headers(session_token=session_token, config=config), timeout=30)
    except Exception:
        try:
            r = requests.post(url, json=payload, headers=make_headers(session_token=session_token, config=config), timeout=30)
        except Exception:
            return None, None

    print(f"  Token creation response: {r.status_code}")
    if r.status_code in (200, 201):
        data = r.json()
        token_info = data.get("token", {})
        api_key = token_info.get("api_key", "")
        token_id = token_info.get("id", "")
        return api_key, token_id
    print(f"  Token body: {r.text[:300]}")
    return None, None


def process_one_account(config, index, preferred_email_provider=None):
    max_provider_switches = 4
    max_email_retries = 8
    used_providers = set()
    provider_type = None
    credentials = None
    email_addr = None
    status = "failed"

    for prov_attempt in range(max_provider_switches):
        if not email_addr:
            email_addr, credentials, provider_type = create_email(
                config, index, preferred_email_provider, exclude=used_providers
            )
            if not email_addr:
                print(f"  No more email providers available.")
                return None
            used_providers.add(provider_type)

        password = config["account_password"]
        print(f"\n{'='*60}")
        print(f"Processing account #{index}: {email_addr} (provider: {provider_type})")
        print(f"{'='*60}")

        # Try registration, generating fresh email on 429
        for reg_attempt in range(max_email_retries):
            status, msg, session = register_account(config, email_addr, password)
            if status == "ok":
                break
            elif status == "rate_limited":
                # Generate fresh email from SAME provider, don't switch provider
                print(f"  Rate limited on {email_addr}. Generating new email...")
                new_email, new_creds, _ = create_email(
                    config, index, provider_type, exclude=None
                )
                if new_email and new_email != email_addr:
                    email_addr = new_email
                    credentials = new_creds
                    print(f"  Switched to: {email_addr}")
                else:
                    print(f"  No more fresh emails from {provider_type}. Trying next provider.")
                    email_addr = None
                    break
                continue
            elif status == "rejected":
                print(f"  Rejected. Switching provider...")
                email_addr = None
                break
            else:
                print(f"  Failed. Switching provider...")
                email_addr = None
                break
        else:
            print(f"  Exhausted {max_email_retries} email attempts for this provider.")
            email_addr = None
            continue

        if status == "ok":
            break

    if status != "ok":
        print(f"  All attempts failed for account #{index}.")
        return None

    verify_url = None
    poll_attempts = 20
    poll_delay = 4

    print(f"  Waiting for verification email (up to {poll_attempts * poll_delay}s)...")
    for attempt in range(poll_attempts):
        if attempt > 0:
            time.sleep(poll_delay)
        verify_url = poll_email(email_addr, credentials, provider_type)
        if verify_url:
            print(f"  Found verification link on attempt {attempt+1}!")
            break
        if attempt % 3 == 0 and attempt > 0:
            print(f"  Still waiting for email... ({attempt+1}/{poll_attempts})")

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
            time.sleep(1)
        else:
            print(f"  Email verification request returned non-200, but may still be verified.")
            time.sleep(1)

    time.sleep(1)
    session_token = login(config, email_addr, password)
    if not session_token:
        print(f"  Login failed, retrying after delay...")
        time.sleep(2)
        session_token = login(config, email_addr, password)
    if not session_token:
        print(f"  Could not login as {email_addr}. Email may not be verified yet.")
        return None

    print(f"  Session token: {session_token[:40]}...")

    time.sleep(0.5)
    api_key, token_id = create_api_token(config, session_token, f"auto-token-{index}")
    if not api_key:
        print(f"  Failed to create API token for {email_addr}")
        return None

    token_entry = {
        "index": index,
        "email": email_addr,
        "email_provider": provider_type,
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
    parser = argparse.ArgumentParser(description="Openshit Token Manager")
    parser.add_argument("--count", type=int, default=None, help="Number of accounts to create")
    parser.add_argument("--start", type=int, default=None, help="Starting index")
    parser.add_argument("--threads", type=int, default=1, help="Number of parallel threads for account creation")
    parser.add_argument("--no-input", action="store_true", help="Non-interactive mode")
    parser.add_argument("--no-register", action="store_true", help="Skip registration (assumes accounts exist)")
    parser.add_argument("--email-provider", type=str, default=None, help="Preferred email provider")

    args = parser.parse_args()
    global NO_INPUT, SKIP_REGISTER
    if args.no_input:
        NO_INPUT = True
    if args.no_register:
        SKIP_REGISTER = True

    config = load_config()
    count = args.count if args.count is not None else config.get("account_count", 5)
    start = args.start if args.start is not None else config.get("start_index", 1)
    num_threads = args.threads if args.threads > 1 else config.get("generation_threads", 1)
    delay_reg = config.get("delay_between_registrations", 3)

    existing = load_tokens()
    existing_indices = {t["index"] for t in existing}
    new_tokens = []

    print(f"\n{'='*60}")
    print(f"Openshit Token Manager v2")
    print(f"{'='*60}")

    n_proxies = load_and_filter()
    if n_proxies > 0:
        if has_proxies():
            print(f"[proxy] {proxy_count()} proxies available. Registration via rotating proxies.")
            delay_reg = max(0.3, delay_reg - 2)
        else:
            print("[!] No working proxies. Will use direct connection (may be rate-limited).")
    else:
        print("[!] No proxy file found. Direct connection only.")

    indices_to_process = [i for i in range(start, start + count) if i not in existing_indices]
    if not indices_to_process:
        print("\nAll requested accounts already exist in tokens.json")
        return

    print(f"\nCreating {len(indices_to_process)} accounts (indices {indices_to_process[0]}-{indices_to_process[-1]})")
    if num_threads > 1:
        print(f"Multi-threaded: {num_threads} workers")

    if num_threads > 1 and len(indices_to_process) > 1:
        workers = min(num_threads, len(indices_to_process))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(process_one_account, config, i, args.email_provider): i
                for i in indices_to_process
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    entry = future.result(timeout=180)
                    if entry:
                        new_tokens.append(entry)
                except Exception as e:
                    print(f"\nAccount #{idx} failed with exception: {e}")
    else:
        for i in indices_to_process:
            entry = process_one_account(config, i, args.email_provider)
            if entry:
                new_tokens.append(entry)
            if i != indices_to_process[-1]:
                wait = delay_reg
                print(f"\nWaiting {wait:.1f}s before next registration...")
                time.sleep(wait)

    all_tokens = existing + new_tokens
    if all_tokens:
        save_tokens(all_tokens)
        free_plan = all_tokens[0] if all_tokens else {}
        total_weekly = sum(
            t.get("requests_per_week", 0) or 0 for t in all_tokens
        )
        total_rpm = sum(t.get("max_rpm", 0) or 0 for t in all_tokens)
        print(f"\n{'='*60}")
        print(f"SUMMARY: {len(all_tokens)} total accounts")
        print(f"  Newly created: {len(new_tokens)}")
        print(f"  Total combined weekly requests: {total_weekly}")
        print(f"  Combined RPM: {total_rpm}")
        print(f"  Tokens saved to: {TOKENS_PATH}")
        print(f"{'='*60}")
    else:
        print("No tokens created or loaded.")


if __name__ == "__main__":
    main()
