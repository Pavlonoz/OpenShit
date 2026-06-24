import re
import time
import requests
import random
import string
import threading
from pathlib import Path
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

MAILTM_APIS = ["https://api.mail.tm", "https://api.mail.gw"]

GUERRILLA_API = "https://api.guerrillamail.com/ajax.php"
TEMPMAIL_APIS = [
    "https://api.internal.temp-mail.io/api/v3/email",
]
MINUTEMAIL_DOMAINS = [
    "https://www.1secmail.com/api/v1/",
]

GMAIL_SMTP = False
try:
    import imaplib
    import email as email_lib
    GMAIL_SMTP = True
except ImportError:
    pass


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


def create_mailtm(config, index):
    username = config.get("email_base", "user").split("@")[0] + str(index)
    password = config["account_password"]

    r = _mailtm_request("get", "/domains")
    if r is None:
        print(f"  [mail.tm] Failed to fetch domains")
        return None, None, None

    domains = r.json().get("hydra:member", [])
    if not domains:
        print(f"  [mail.tm] No domains available")
        return None, None, None

    domain = random.choice(domains)["domain"]
    email_addr = f"{username}@{domain}"

    r = _mailtm_request("post", "/accounts", json_data={"address": email_addr, "password": password})
    if r is None:
        print(f"  [mail.tm] Failed to create account")
        return None, None, None

    data = r.json()
    return data.get("address", email_addr), password, "mailtm"


def poll_mailtm(email_addr, password):
    r = _mailtm_request("post", "/token", json_data={"address": email_addr, "password": password})
    if r is None:
        return None
    token = r.json()["token"]
    headers = {"Authorization": f"Bearer {token}"}

    for _ in range(3):
        r = _mailtm_request("get", "/messages", headers=headers)
        if r is None:
            time.sleep(2)
            continue
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
        time.sleep(3)
    return None


def create_guerrillamail(config, index):
    try:
        r = requests.get(GUERRILLA_API, params={"f": "get_email_address"}, timeout=15)
        data = r.json()
        email_addr = data.get("email_addr", "")
        sid_token = data.get("sid_token", "")
        if email_addr and sid_token:
            print(f"  [guerrillamail] Created: {email_addr}")
            return email_addr, sid_token, "guerrillamail"
    except Exception as e:
        print(f"  [guerrillamail] Error: {e}")
    return None, None, None


def poll_guerrillamail(sid_token):
    try:
        r = requests.get(GUERRILLA_API, params={
            "f": "fetch_email",
            "sid_token": sid_token,
        }, timeout=15)
        data = r.json()
        messages = data.get("list", [])
        for msg in messages:
            mail_id = msg.get("mail_id", "")
            r2 = requests.get(GUERRILLA_API, params={
                "f": "fetch_email",
                "sid_token": sid_token,
                "email_id": mail_id,
            }, timeout=15)
            body = r2.json().get("mail_body", "") or ""
            pattern = r'https://openference\.com/auth/verify-email\?token=[^\s"\'<>&]+'
            match = re.search(pattern, body)
            if match:
                return match.group(0)
    except Exception:
        pass
    return None


def create_1secmail(config, index):
    username = config.get("email_base", "user").split("@")[0] + str(index)
    domains_url = "https://www.1secmail.com/api/v1/?action=getDomainList"
    try:
        r = requests.get(domains_url, timeout=10)
        domains = r.json()
        domain = random.choice(domains) if domains else "1secmail.com"
    except Exception:
        domain = "1secmail.com"

    email_addr = f"{username}@{domain}"
    login = username
    dom = domain
    print(f"  [1secmail] Created: {email_addr}")
    return email_addr, f"{login}|{dom}", "1secmail"


def poll_1secmail(credentials):
    parts = credentials.split("|")
    if len(parts) != 2:
        return None
    login, domain = parts
    try:
        r = requests.get(
            f"https://www.1secmail.com/api/v1/?action=getMessages&login={login}&domain={domain}",
            timeout=10
        )
        messages = r.json()
        for msg in messages:
            msg_id = msg.get("id", "")
            r2 = requests.get(
                f"https://www.1secmail.com/api/v1/?action=readMessage&login={login}&domain={domain}&id={msg_id}",
                timeout=10
            )
            body = r2.json().get("body", "") or r2.json().get("htmlBody", "") or r2.text or ""
            pattern = r'https://openference\.com/auth/verify-email\?token=[^\s"\'<>&]+'
            match = re.search(pattern, body)
            if match:
                return match.group(0)
    except Exception:
        pass
    return None


def create_tempmail_io(config, index):
    try:
        r = requests.post(
            "https://api.internal.temp-mail.io/api/v3/email/new",
            json={"min_name_length": 8, "max_name_length": 12},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        data = r.json()
        email_addr = data.get("email", "")
        if email_addr:
            print(f"  [temp-mail.io] Created: {email_addr}")
            return email_addr, email_addr, "tempmailio"
    except Exception as e:
        print(f"  [temp-mail.io] Error: {e}")
    return None, None, None


def poll_tempmail_io(email_addr):
    try:
        email_hash = email_addr.split("@")[0]
        r = requests.get(
            f"https://api.internal.temp-mail.io/api/v3/email/{email_addr}/messages",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        messages = r.json()
        for msg in messages:
            body = msg.get("body_text", "") or msg.get("body_html", "") or ""
            pattern = r'https://openference\.com/auth/verify-email\?token=[^\s"\'<>&]+'
            match = re.search(pattern, body)
            if match:
                return match.group(0)
    except Exception:
        pass
    return None


def create_gmail_plus(config, index):
    base_email = config.get("gmail_address", "")
    if not base_email or "@gmail.com" not in base_email:
        return None, None, None

    gmail_password = config.get("gmail_app_password", "")
    if not gmail_password:
        return None, None, None

    local, domain = base_email.split("@")
    plus_email = f"{local}+openshit{index}@{domain}"
    print(f"  [gmail+] Created: {plus_email}")
    return plus_email, base_email, "gmailplus"


def poll_gmail_plus(base_email, gmail_password, plus_email):
    if not GMAIL_SMTP:
        return None

    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com")
        mail.login(base_email, gmail_password)
        mail.select("inbox")

        status, messages = mail.search(None, f'(TO "{plus_email}")')
        if status != "OK":
            mail.logout()
            return None

        msg_ids = messages[0].split()
        if not msg_ids:
            mail.logout()
            return None

        latest = msg_ids[-1]
        status, data = mail.fetch(latest, "(RFC822)")
        if status != "OK":
            mail.logout()
            return None

        raw_email = data[0][1]
        msg = email_lib.message_from_bytes(raw_email)

        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                if content_type == "text/plain" or content_type == "text/html":
                    try:
                        body += part.get_payload(decode=True).decode(errors="ignore")
                    except Exception:
                        pass
        else:
            try:
                body = msg.get_payload(decode=True).decode(errors="ignore")
            except Exception:
                pass

        mail.logout()

        pattern = r'https://openference\.com/auth/verify-email\?token=[^\s"\'<>&]+'
        match = re.search(pattern, body)
        if match:
            return match.group(0)
    except Exception:
        pass
    return None


def create_mohmal(config, index):
    try:
        r = requests.get("https://www.mohmal.com/en/inbox", timeout=15)
        token_match = re.search(r'name="_token"\s+value="([^"]+)"', r.text)
        token = token_match.group(1) if token_match else ""
        cookies = r.cookies.get_dict()

        name = config.get("email_base", "user").split("@")[0] + str(index)
        r2 = requests.post(
            "https://www.mohmal.com/en/inbox",
            data={"_token": token, "name": name, "domain": "", "action": "random"},
            cookies=cookies,
            headers={"Referer": "https://www.mohmal.com/en", "User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        match = re.search(r'<span[^>]*id="email"[^>]*>([^<]+)</span>', r2.text)
        if match:
            email_addr = match.group(1).strip()
            print(f"  [mohmal] Created: {email_addr}")
            return email_addr, cookies, "mohmal"
    except Exception as e:
        print(f"  [mohmal] Error: {e}")
    return None, None, None


def poll_mohmal(email_addr, cookies):
    try:
        r = requests.get(
            "https://www.mohmal.com/en/inbox",
            cookies=cookies,
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.mohmal.com/en"},
            timeout=15,
        )
        pattern = r'https://openference\.com/auth/verify-email\?token=[^\s"\'<>&]+'
        match = re.search(pattern, r.text)
        if match:
            return match.group(0)
    except Exception:
        pass
    return None


def create_tempmail_lol(config, index):
    try:
        r = requests.post(
            "https://api.tempmail.lol/v2/inbox/create",
            json={},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        data = r.json()
        email_addr = data.get("address", "")
        token = data.get("token", "")
        if email_addr and token:
            print(f"  [tempmail.lol] Created: {email_addr}")
            return email_addr, token, "tempmail_lol"
    except Exception as e:
        print(f"  [tempmail.lol] Error: {e}")
    return None, None, None


def poll_tempmail_lol(email_addr, token):
    try:
        r = requests.get(
            f"https://api.tempmail.lol/v2/inbox?token={token}",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=15,
        )
        data = r.json()
        emails = data.get("emails", [])
        for msg in emails:
            body = msg.get("body", "") or msg.get("html", "") or ""
            pattern = r'https://openference\.com/auth/verify-email\?token=[^\s"\'<>&]+'
            match = re.search(pattern, body)
            if match:
                return match.group(0)
    except Exception:
        pass
    return None


def create_maildrop(config, index):
    name = config.get("email_base", "user").split("@")[0] + str(index) + str(random.randint(100, 999))
    email_addr = f"{name}@maildrop.cc"
    print(f"  [maildrop] Created: {email_addr}")
    return email_addr, name, "maildrop"


def poll_maildrop(email_addr, name):
    try:
        r = requests.get(f"https://maildrop.cc/inbox/{name}", timeout=15)
        pattern = r'https://openference\.com/auth/verify-email\?token=[^\s"\'<>&]+'
        match = re.search(pattern, r.text)
        if match:
            return match.group(0)
    except Exception:
        pass
    return None


def create_yopmail(config, index):
    name = config.get("email_base", "user").split("@")[0] + str(index)
    domains = ["yopmail.com", "yopmail.fr", "yopmail.net", "cool.fr.nf", "jetable.fr.nf",
               "nospam.ze.tc", "nomail.xl.cx", "mega.zik.dj", "speed.1s.fr"]
    domain = random.choice(domains)
    email_addr = f"{name}@{domain}"
    print(f"  [yopmail] Created: {email_addr}")
    return email_addr, name, "yopmail"


def poll_yopmail(email_addr, name):
    try:
        r = requests.get(f"https://www.yopmail.com/en/inbox?login={name}&p=1&d=&ctrl=&scrl=&spam=true&yf=002&v=3.5&r_c=&id=", timeout=15)
        pattern = r'https://openference\.com/auth/verify-email\?token=[^\s"\'<>&]+'
        match = re.search(pattern, r.text)
        if match:
            return match.group(0)
    except Exception:
        pass
    return None


_file_emails = []
_file_index = 0
_file_lock = threading.Lock()


def _load_file_emails():
    global _file_emails
    try:
        email_file = Path(__file__).parent / "emails.txt"
        if email_file.exists():
            with open(email_file) as f:
                _file_emails = [line.strip() for line in f if line.strip() and ":" in line and not line.strip().startswith("#")]
            print(f"  [file] Loaded {len(_file_emails)} emails from emails.txt")
    except Exception:
        pass


def create_from_file(config, index):
    global _file_index
    _load_file_emails()
    if not _file_emails:
        return None, None, None

    if _file_index >= len(_file_emails):
        _file_index = 0

    line = _file_emails[_file_index]
    _file_index += 1

    parts = line.split(":", 1)
    if len(parts) == 2:
        email_addr, password = parts[0].strip(), parts[1].strip()
        print(f"  [file] Using: {email_addr}")
        return email_addr, password, "file"
    return None, None, None


def poll_from_file(email_addr, password):
    return None


def create_mailcx(config, index):
    try:
        s = requests.Session()
        s.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/148.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Referer": "https://mail.cx/",
        })
        r = s.get("https://mail.cx/", timeout=15)
        csrf_match = re.search(r'name="_token"\s+value="([^"]+)"', r.text)
        csrf = csrf_match.group(1) if csrf_match else ""

        username = config.get("email_base", "user").split("@")[0] + str(index)
        r2 = s.post(
            "https://mail.cx/v1/addr",
            json={"name": username},
            headers={
                "X-Client-Id": str(random.randint(10000000, 99999999)),
                "X-CSRF-Token": csrf,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=15,
        )
        data = r2.json()
        email_addr = data.get("address", "")
        if not email_addr:
            json_data = r2.json() if r2.text else {}
            email_addr = json_data.get("address", json_data.get("email", ""))
        if email_addr:
            print(f"  [mail.cx] Created: {email_addr}")
            cookies = s.cookies.get_dict()
            return email_addr, cookies, "mailcx"
        print(f"  [mail.cx] Response: {r2.text[:200]}")
    except Exception as e:
        print(f"  [mail.cx] Error: {e}")
    return None, None, None


def poll_mailcx(email_addr, cookies):
    try:
        s = requests.Session()
        for k, v in (cookies or {}).items():
            s.cookies.set(k, v)
        s.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/148.0.0.0 Safari/537.36",
            "Accept": "*/*",
            "Referer": "https://mail.cx/",
        })
        r = s.get(
            f"https://mail.cx/v1/inbox/{email_addr}",
            headers={"X-Client-Id": str(random.randint(10000000, 99999999))},
            timeout=15,
        )
        data = r.json()
        emails = data.get("emails", [])
        for msg in emails:
            preview = msg.get("preview_text", "") or msg.get("subject", "") or ""
            html = msg.get("html", "") or ""
            body = preview + " " + html
            pattern = r'https://openference\.com/auth/verify-email\?token=[^\s"\'<>&]+'
            match = re.search(pattern, body)
            if match:
                return match.group(0)
    except Exception:
        pass
    return None

def create_emailmux(config, index):
    token = config.get("emailmux_token", "")
    cf_clearance = config.get("emailmux_cf_clearance", "")
    if not token or not cf_clearance:
        print(f"  [emailmux] Missing emailmux_token or cf_clearance in config.json")
        return None, None, None

    cookies = {"emailmux_token": token, "cf_clearance": cf_clearance}
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/148.0.0.0 Safari/537.36",
        "Content-Type": "application/json",
        "Accept": "*/*",
        "Origin": "https://emailmux.com",
        "Referer": "https://emailmux.com/",
    }

    domains = config.get("emailmux_domains", ["gmail", "icloud", "googlemail"])
    domain = domains[index % len(domains)]

    try:
        r = requests.post(
            "https://emailmux.com/generate-email",
            json={"domains": [domain]},
            cookies=cookies,
            headers=headers,
            timeout=15,
        )
        data = r.json()
        if data.get("status") == "success":
            email_addr = data.get("email", "")
            if email_addr:
                # Activate the email
                requests.get(
                    f"https://emailmux.com/use-email?email={requests.utils.quote(email_addr, safe='')}",
                    cookies=cookies,
                    headers=headers,
                    timeout=10,
                )
                print(f"  [emailmux] Created + activated: {email_addr} (domain: {domain})")
                return email_addr, cookies, "emailmux"
        print(f"  [emailmux] Response: {r.text[:200]}")
    except Exception as e:
        print(f"  [emailmux] Error: {e}")
    return None, None, None


def poll_emailmux(email_addr, cookies):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/148.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Referer": "https://emailmux.com/",
    }
    try:
        r = requests.get(
            f"https://emailmux.com/emails?email={requests.utils.quote(email_addr, safe='')}",
            cookies=cookies,
            headers=headers,
            timeout=15,
        )
        data = r.json()
        emails = data if isinstance(data, list) else data.get("emails", [])
        for msg in emails:
            uuid = msg.get("uuid", "")
            if not uuid:
                continue
            # Fetch full email content
            try:
                r2 = requests.get(
                    f"https://emailmux.com/https:/email/{uuid}",
                    cookies=cookies,
                    headers=headers,
                    timeout=15,
                )
                # Extract email body from JSON in script tag
                script_match = re.search(
                    r'<script\s+id="email-html-data"\s+type="application/json">\s*(.+?)\s*</script>',
                    r2.text, re.DOTALL
                )
                if script_match:
                    import json
                    raw = json.loads(script_match.group(1))
                    body = raw if isinstance(raw, str) else str(raw)
                    pattern = r'https://openference\.com/auth/verify-email\?token=[^\s"\'<>&]+'
                    match = re.search(pattern, body)
                    if match:
                        return match.group(0)
            except Exception:
                continue
    except Exception:
        pass
    return None


def create_evapmail(config, index):
    import uuid
    payload = {"expirationMinutes": 60}

    for attempt in range(4):
        proxy = None
        if attempt >= 2:
            from proxy_rotator import get_proxy
            proxy = get_proxy()
            if not proxy:
                continue

        try:
            kw = {"proxies": proxy, "verify": False} if proxy else {}
            r = requests.post("https://api.evapmail.com/v1/accounts/create",
                json=payload, headers={
                    "Content-Type": "application/json",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/148.0.0.0 Safari/537.36",
                    "Origin": "https://evapmail.com",
                    "Referer": "https://evapmail.com/",
                    "em-client-id": str(uuid.uuid4()),
                    "em-client-type": "web",
                    "em-client-version": "1.0.0",
                }, timeout=15, **kw)
            data = r.json()
            email_addr = data.get("email", "")
            token = data.get("token", "")
            if email_addr and token:
                tag = "proxy" if proxy else "direct"
                print(f"  [evapmail] Created via {tag}: {email_addr}")
                return email_addr, token, "evapmail"
            if data.get("message") == "ACCOUNT_CREATION_LIMIT_REACHED":
                tag = f"proxy (attempt {attempt+1})" if proxy else f"direct (attempt {attempt+1})"
                print(f"  [evapmail] Rate limited {tag}, retrying...")
                continue
            print(f"  [evapmail] Response: {r.text[:200]}")
            return None, None, None
        except Exception as e:
            print(f"  [evapmail] Error: {e}")
            continue

    return None, None, None


def poll_evapmail(email_addr, token):
    try:
        r = requests.get(
            "https://api.evapmail.com/v1/messages/inbox",
            headers={
                "Authorization": f"Bearer {token}",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/148.0.0.0 Safari/537.36",
                "Origin": "https://evapmail.com",
                "Referer": "https://evapmail.com/",
            },
            timeout=15,
        )
        messages = r.json()
        if not isinstance(messages, list):
            messages = messages.get("messages", messages.get("data", []))
        for msg in messages:
            msg_id = msg.get("id", "")
            intro = msg.get("intro", "") or ""
            pattern = r'https://openference\.com/auth/verify-email\?token=[^\s"\'<>&]+'
            match = re.search(pattern, intro)
            if match:
                return match.group(0)
            # Fetch full message if intro doesn't have the link
            if msg_id:
                try:
                    r2 = requests.get(
                        f"https://api.evapmail.com/v1/messages/inbox/{msg_id}",
                        headers={
                            "Authorization": f"Bearer {token}",
                            "User-Agent": "Mozilla/5.0",
                            "Origin": "https://evapmail.com",
                        },
                        timeout=15,
                    )
                    full = r2.json()
                    html = full.get("html", "")
                    if isinstance(html, list):
                        html = " ".join(html)
                    text = full.get("text", "")
                    if isinstance(text, list):
                        text = " ".join(text)
                    body = html or text or str(full)
                    match = re.search(pattern, body)
                    if match:
                        return match.group(0)
                except Exception:
                    pass
    except Exception:
        pass
    return None


EMAIL_PROVIDERS = [
    {
        "name": "evapmail",
        "create": create_evapmail,
        "poll": poll_evapmail,
        "enabled": True,
    },
    {
        "name": "emailmux",
        "create": create_emailmux,
        "poll": poll_emailmux,
        "enabled": False,
    },
    {
        "name": "file",
        "create": create_from_file,
        "poll": poll_from_file,
        "enabled": True,
    },
    {
        "name": "mailcx",
        "create": create_mailcx,
        "poll": poll_mailcx,
        "enabled": True,
    },
    {
        "name": "mailcx",
        "create": create_mailcx,
        "poll": poll_mailcx,
        "enabled": False,
    },
    {
        "name": "mailtm",
        "create": create_mailtm,
        "poll": poll_mailtm,
        "enabled": False,
    },
    {
        "name": "guerrillamail",
        "create": create_guerrillamail,
        "poll": poll_guerrillamail,
        "enabled": False,
    },
    {
        "name": "1secmail",
        "create": create_1secmail,
        "poll": poll_1secmail,
        "enabled": False,
    },
    {
        "name": "tempmailio",
        "create": create_tempmail_io,
        "poll": poll_tempmail_io,
        "enabled": False,
    },
    {
        "name": "gmailplus",
        "create": create_gmail_plus,
        "poll": lambda *args: poll_gmail_plus(args[0], load_gmail_password(), args[2]) if len(args) >= 3 else None,
        "enabled": False,
    },
    {
        "name": "mohmal",
        "create": create_mohmal,
        "poll": poll_mohmal,
        "enabled": False,
    },
    {
        "name": "tempmail_lol",
        "create": create_tempmail_lol,
        "poll": poll_tempmail_lol,
        "enabled": False,
    },
    {
        "name": "maildrop",
        "create": create_maildrop,
        "poll": poll_maildrop,
        "enabled": False,
    },
    {
        "name": "yopmail",
        "create": create_yopmail,
        "poll": poll_yopmail,
        "enabled": False,
    },
]


def load_gmail_password():
    try:
        from pathlib import Path
        import json
        config_path = Path(__file__).parent / "config.json"
        with open(config_path) as f:
            config = json.load(f)
        return config.get("gmail_app_password", "")
    except Exception:
        return ""


def get_enabled_providers():
    return [p for p in EMAIL_PROVIDERS if p["enabled"]]


def create_email(config, index, preferred_provider=None, exclude=None):
    if exclude is None:
        exclude = set()

    if preferred_provider and preferred_provider not in exclude:
        for p in EMAIL_PROVIDERS:
            if p["name"] == preferred_provider and p["enabled"]:
                result = p["create"](config, index)
                if result[0]:
                    return result
                break

    providers = [p for p in EMAIL_PROVIDERS if p["enabled"] and p["name"] not in exclude]
    if not providers:
        return None, None, None

    for p in providers:
        try:
            result = p["create"](config, index)
            if result[0]:
                return result
        except Exception as e:
            print(f"  [{p['name']}] Provider error: {e}")
            continue

    return None, None, None


def poll_email(email_addr, credentials, provider_type):
    for p in EMAIL_PROVIDERS:
        if p["name"] == provider_type:
            try:
                return p["poll"](email_addr, credentials)
            except Exception:
                return None
    return None
