# OpenShit

Abuse the fuck out of a small ai company to get free unlimited tokens.

## How it works

1. Creates multiple Openference accounts via Gmail plus-addressing (you+1@gmail.com, you+2@...)
2. Verifies emails automatically via IMAP
3. Generates API tokens for each account
4. Runs a local proxy that spreads requests across all tokens
5. When a token nears its 50/5h window or 100 RPM limit, the proxy silently switches to the next one

**Free plan limits:** 50 requests per 5h window, 100 RPM, 1250/week — per account(literaly the hole vuln).

## Requirements

- **Python 3.11+** with `flask`, `requests`, `pysocks`
- **Node.js** (for building the Electron app)
- **Gmail with 2FA** and an app password (for IMAP auto-verification)

## Quick start

```bash
# Install Python deps
pip install flask requests pysocks rich

# CLI mode
python openshit.py

# Or run the Electron desktop app
npm install
npm start
```

## Build Windows .exe

```bash
npm install
npm run build
# Output: dist/OpenShit 1.0.0.exe
```

## Configuration

All settings are saved to `%APPDATA%/OpenShit/`. The app stores:
- `config.json` — Gmail credentials, account count, proxy port
- `tokens.json` — generated API tokens with session keys
- `free-proxy-list.json` - REPLACE THOSE EVERY 7 DAYS.


**Example config** (copy to `config.json`):
```json
{
  "email_base": "you@gmail.com",
  "email_password": "your-gmail-app-password",
  "account_password": "shared-password",
  "account_count": 5,
  "start_index": 1,
  "proxy_port": 8787
}
```

## Gmail app password

1. Enable 2-Factor Authentication on your Google account
2. Go to https://myaccount.google.com/apppasswords
3. Generate a 16-character password for "Mail"
4. Paste it in Settings

## Proxy rotation

The proxy intercepts AI client requests, picks the token with the most remaining capacity, and forwards to Openference. If a token returns 401/403 it's marked bad and skipped. If the upstream returns 503 the proxy retries.

**Token selection priority:**
1. Tokens with <90% RPM usage
2. Tokens with space in the 5h window
3. Least-used token when all are near limits

## Client setup

### OpenCode
The app auto-writes config to `~/.config/opencode/opencode.json` and `~/.local/share/opencode/auth.json`.

### Claude Code
The app writes `.claude.json` and creates a `Claude_OpenShit.bat` launcher on your Desktop.

### Manual
```
# Set env vars
set ANTHROPIC_BASE_URL=http://127.0.0.1:8787/v1
set ANTHROPIC_API_KEY=anything
```

## Files

```
Openshit/
├── main.js              # Electron main process
├── preload.js           # Secure bridge
├── renderer/            # UI (HTML/CSS/JS)
├── backend/             # Python proxy + token manager
│   ├── proxy.py         # Rotating proxy server
│   ├── token_manager.py # Account creation + verification
│   └── proxy_rotator.py # Proxy list loader
├── openshit.py          # CLI launcher (rich TUI)
├── free-proxy-list.json # SOCKS proxy list for registration
└── config.example.json  # Example configuration
```

## Security

- `config.json` and `tokens.json` are gitignored
- No API keys or credentials are hardcoded in source
- The Electron app uses context isolation
- Proxy only listens on 127.0.0.1


Yea Yea this was summarized with ai and bullshit but shit works 99% of the time unless the server is overloaded.