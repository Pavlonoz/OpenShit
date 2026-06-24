# OpenShit

Abuse the fuck out of a small AI company to get free unlimited tokens.

## How it works

1. Creates Openference accounts using disposable email providers (evapmail, mail.cx, etc.)
2. Verifies emails automatically via inbox polling
3. Generates API tokens for each account
4. Runs a local proxy that spreads requests across all tokens
5. When tokens near their limits, auto-generates fresh accounts
6. All traffic routed through residential SOCKS5 proxies — your real IP stays hidden

**Free plan limits:** 50 requests per 5h window, 100 RPM, 1250/week — per account (the hole vuln).

## Requirements

- **Python 3.11+** with `flask`, `requests`, `rich`
- **Residential SOCKS5 proxies** — required for account creation
  - Get 10 free at: https://webshare.io
  - Save as `residential_proxies.txt` (format: `ip:port:user:pass`)

## Quick start

```bash
# Install Python deps
pip install flask requests pysocks rich

# Put your residential proxies in residential_proxies.txt
# Format: ip:port:user:pass (one per line)

# Run the CLI
python openshit.py
# Press 1 to start the proxy

# Or directly
python proxy.py
```

## Configuration

Copy `config.example.json` to `config.json` and edit:

```json
{
  "email_base": "someprefix",
  "account_password": "shared-password",
  "account_count": 5,
  "start_index": 1,
  "proxy_port": 8787,
  "proxy_host": "127.0.0.1",
  "delay_between_registrations": 3,
  "auto_generate": true,
  "auto_gen_threshold": 0.5,
  "auto_gen_count": 2,
  "auto_gen_cooldown": 1800,
  "auto_gen_max_tokens": 50,
  "generation_threads": 2
}
```

| Setting | Default | Description |
|---|---|---|
| `auto_generate` | true | Auto-create accounts when usage hits threshold |
| `auto_gen_threshold` | 0.5 | Trigger at 50% usage |
| `auto_gen_count` | 2 | Create 2 accounts per batch |
| `auto_gen_cooldown` | 1800 | Min 30 min between batches |
| `auto_gen_max_tokens` | 50 | Never exceed this many tokens |
| `generation_threads` | 2 | Parallel account creation workers |

## Client setup

### OpenCode
```json
{
  "provider": {
    "openference": {
      "options": {
        "baseURL": "http://127.0.0.1:8787/v1",
        "apiKey": "anything"
      }
    }
  }
}
```

### Claude Code / Any OpenAI client
```
set ANTHROPIC_BASE_URL=http://127.0.0.1:8787/v1
set ANTHROPIC_API_KEY=anything
```

## Proxy rotation

- Atomic token selection (select + count in one lock)
- Auto-recovery from rate limits (proxies recover after 30 min)
- Dashboard at http://127.0.0.1:8787 shows live usage stats
- Background sync with real API usage every 30s

## Email providers

Multiple providers tried in order, falling through on failure:
- **evapmail** — clean API, instant emails
- **mail.cx** — random domains
- **mail.tm / mail.gw** — rotating domains
- **guerrillamail** — disposable inbox
- **1secmail** — quick temp mail
- Plus: tempmail.io, mohmal, yopmail, maildrop, gmail+, file-based

## Files

```
Openshit/
├── openshit.py          # CLI launcher (Rich TUI)
├── proxy.py             # Rotating proxy server
├── token_manager.py     # Multi-threaded account creation
├── proxy_rotator.py     # Residential proxy pool manager
├── email_providers.py   # Multi-provider email system
├── backend/             # Electron app backend
├── main.js              # Electron main process
├── renderer/            # Electron UI
├── run.bat              # Windows launcher
├── config.example.json  # Example configuration
└── residential_proxies.txt  # Your proxies (ip:port:user:pass)
```

## Security

- `config.json`, `tokens.json`, `residential_proxies.txt` are gitignored
- No API keys or credentials hardcoded
- Proxy only listens on 127.0.0.1
- All Openference traffic routed through residential proxies

---

made by Pavlonoz <3
