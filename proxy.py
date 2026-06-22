import json
import sys
import time
import threading
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import requests
from flask import Flask, request, Response, jsonify, stream_with_context

CONFIG_PATH = Path(__file__).parent / "config.json"
TOKENS_PATH = Path(__file__).parent / "tokens.json"

app = Flask(__name__)

TOKENS = []
TOKEN_INDEX = 0
TOKEN_LOCK = threading.Lock()

USAGE = {}
REAL_USAGE = {}
SYNC_LOCK = threading.Lock()

OPENFERENCE_API = "https://api.openference.com"
OPENFERENCE_WEB = "https://openference.com"

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Openshit — Token Rotator</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Segoe UI',system-ui,sans-serif;background:#0d1117;color:#c9d1d9;min-height:100vh}
.header{background:#161b22;border-bottom:1px solid #30363d;padding:16px 24px;display:flex;align-items:center;justify-content:space-between;position:sticky;top:0;z-index:10}
.header h1{font-size:18px;font-weight:600;color:#58a6ff}
.header .badge{background:#238636;color:#fff;padding:4px 12px;border-radius:12px;font-size:12px;font-weight:600}
.container{max-width:1200px;margin:0 auto;padding:24px}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:24px}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:20px}
.card .label{font-size:12px;color:#8b949e;text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px}
.card .value{font-size:28px;font-weight:700;color:#58a6ff}
.card .sub{font-size:12px;color:#8b949e;margin-top:4px}
.panel{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:20px;margin-bottom:24px}
.panel h2{font-size:16px;color:#58a6ff;margin-bottom:16px;padding-bottom:8px;border-bottom:1px solid #30363d}
table{width:100%;border-collapse:collapse}
th{text-align:left;padding:10px 12px;font-size:12px;color:#8b949e;text-transform:uppercase;letter-spacing:.5px;border-bottom:1px solid #30363d}
td{padding:10px 12px;font-size:14px;border-bottom:1px solid #21262d}
tr:hover{background:#1c2128}
.progress-bar{height:6px;background:#21262d;border-radius:3px;overflow:hidden;margin-top:4px}
.progress-fill{height:100%;border-radius:3px;transition:width .3s}
.progress-fill.green{background:#238636}
.progress-fill.yellow{background:#d29922}
.progress-fill.red{background:#da3633}
.status-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
.status-dot.green{background:#238636}
.status-dot.yellow{background:#d29922}
.status-dot.red{background:#da3633}
.btn{padding:8px 16px;border-radius:6px;border:none;font-size:13px;font-weight:600;cursor:pointer;transition:.2s}
.btn-primary{background:#238636;color:#fff}
.btn-primary:hover{background:#2ea043}
.btn-secondary{background:#21262d;color:#c9d1d9;border:1px solid #30363d}
.btn-secondary:hover{background:#30363d}
.btn-danger{background:#da3633;color:#fff}
.btn-danger:hover{background:#f85149}
.input{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:8px 12px;color:#c9d1d9;font-size:14px;width:100%}
.input:focus{outline:none;border-color:#58a6ff}
.form-row{display:flex;gap:12px;align-items:flex-end;margin-bottom:12px}
.form-row label{font-size:12px;color:#8b949e;margin-bottom:4px;display:block}
.form-group{flex:1}
.instructions{background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:16px;margin-top:12px}
.instructions code{background:#1c2128;padding:2px 8px;border-radius:4px;font-size:13px;color:#7ee787}
.instructions pre{background:#1c2128;padding:12px;border-radius:6px;overflow-x:auto;font-size:13px;margin:8px 0}
.tabs{display:flex;gap:8px;margin-bottom:16px}
.tab{padding:8px 16px;border-radius:6px;font-size:13px;cursor:pointer;background:#21262d;color:#8b949e;border:1px solid transparent;transition:.2s}
.tab.active{background:#1f6feb;color:#fff;border-color:#1f6feb}
.toast{position:fixed;top:16px;right:16px;padding:12px 20px;border-radius:8px;font-size:14px;z-index:100;animation:fadeIn .3s;display:none}
.toast.success{background:#238636;color:#fff}
.toast.error{background:#da3633;color:#fff}
@keyframes fadeIn{from{opacity:0;transform:translateY(-10px)}to{opacity:1;transform:translateY(0)}}
footer{text-align:center;color:#484f58;font-size:12px;padding:24px}
a{color:#58a6ff;text-decoration:none}
a:hover{text-decoration:underline}
</style>
</head>
<body>
<div class="header">
  <h1>Openshit Proxy</h1>
  <div>
    <span class="badge" id="tokenCount">0 tokens</span>
  </div>
</div>
<div class="container">
  <div class="cards" id="statsCards">
    <div class="card"><div class="label">Tokens Active</div><div class="value" id="statTokens">-</div><div class="sub">accounts loaded</div></div>
    <div class="card"><div class="label">Requests Today</div><div class="value" id="statToday">-</div><div class="sub">across all tokens</div></div>
    <div class="card"><div class="label">Combined Rate</div><div class="value" id="statRate">-</div><div class="sub">total RPM capacity</div></div>
    <div class="card"><div class="label">Weekly Capacity</div><div class="value" id="statWeekly">-</div><div class="sub">combined requests</div></div>
  </div>

  <div class="tabs">
    <button class="tab active" onclick="switchTab('status')">Status</button>
    <button class="tab" onclick="switchTab('generate')">Generate Tokens</button>
    <button class="tab" onclick="switchTab('setup')">Setup Instructions</button>
  </div>

  <div id="tab-status">
    <div class="panel">
      <h2>Token Usage</h2>
      <div id="tokenTable"></div>
    </div>
  </div>

  <div id="tab-generate" style="display:none">
    <div class="panel">
      <h2>Generate API Tokens</h2>
      <p style="color:#8b949e;font-size:14px;margin-bottom:16px">Create new Openference accounts and generate API tokens. Make sure your config.json has the correct Gmail credentials.</p>
      <div class="form-row">
        <div class="form-group"><label>Number of accounts</label><input class="input" type="number" id="genCount" value="3" min="1" max="20"></div>
        <div class="form-group"><label>Starting index</label><input class="input" type="number" id="genStart" value="1" min="1"></div>
        <div class="form-group" style="flex:0"><label>&nbsp;</label><button class="btn btn-primary" onclick="generateTokens()" id="genBtn">Generate</button></div>
      </div>
      <div id="genStatus"></div>
    </div>
    <div class="panel">
      <h2>Current Configuration</h2>
      <div id="configView">Loading...</div>
    </div>
  </div>

  <div id="tab-setup" style="display:none">
    <div class="panel">
      <h2>Claude Code (VS Code / Terminal)</h2>
      <div class="instructions">
        <p>Set these environment variables before launching Claude Code:</p>
        <pre>set ANTHROPIC_BASE_URL=http://{host}:{port}/v1
set ANTHROPIC_API_KEY=anything</pre>
        <p>Then run <code>claude</code> as usual. Works with VS Code extension and CLI.</p>
      </div>
    </div>
    <div class="panel">
      <h2>OpenCode CLI</h2>
      <div class="instructions">
        <p>In your <code>~/.config/opencode/opencode.json</code>:</p>
        <pre>{
  "provider": {
    "openference": {
      "options": {
        "baseURL": "http://{host}:{port}/v1",
        "apiKey": "anything"
      }
    }
  }
}</pre>
        <p>Then run <code>/connect openference</code> inside OpenCode.</p>
      </div>
    </div>
    <div class="panel">
      <h2>Any OpenAI-compatible client</h2>
      <div class="instructions">
        <p>Point any OpenAI-compatible client to:</p>
        <pre>Base URL: http://{host}:{port}/v1
API Key:  anything</pre>
      </div>
    </div>
  </div>
</div>
<footer>Openshit &mdash; Openference Token Rotator &mdash; <a href="/api/proxy/status" target="_blank">JSON API</a></footer>

<div class="toast" id="toast"></div>

<script>
const HOST = window.location.hostname;
const PORT = window.location.port;

function showToast(msg, type) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast ' + (type || 'success');
  t.style.display = 'block';
  setTimeout(() => t.style.display = 'none', 3000);
}

function switchTab(name) {
  document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('[id^="tab-"]').forEach(el => el.style.display = 'none');
  document.getElementById('tab-' + name).style.display = '';
  event.target.classList.add('active');
}

function progressClass(pct) {
  if (pct > 80) return 'red';
  if (pct > 50) return 'yellow';
  return 'green';
}

function statusClass(pct) {
  if (pct > 80) return 'red';
  if (pct > 50) return 'yellow';
  return 'green';
}

function renderStatus(data) {
  document.getElementById('tokenCount').textContent = data.tokens_loaded + ' tokens';
  const usage = data.usage;
  const keys = Object.keys(usage);

  let totalToday = 0, totalRate = 0, totalWeekly = 0;
  keys.forEach(k => {
    const u = usage[k];
    totalToday += u.total_count;
    totalRate += u.max_rpm;
    totalWeekly += u.week_limit;
  });
  document.getElementById('statTokens').textContent = keys.length;
  document.getElementById('statToday').textContent = totalToday;
  document.getElementById('statRate').textContent = totalRate + '/min';
  document.getElementById('statWeekly').textContent = totalWeekly;

  let html = '<table><tr><th>#</th><th>Email</th><th>Proxy</th><th>Real Req</th><th>Real Tok</th><th>Cost</th><th></th></tr>';
  keys.forEach((k, i) => {
    const u = usage[k];
    const real = u.real || {};
    const mp = u.minute_count / u.max_rpm * 100;
    const sc = statusClass(mp);
    html += `<tr>
      <td style="color:#484f58">${i+1}</td>
      <td style="color:#58a6ff">${u.email}</td>
      <td>${u.total_count}<div class="progress-bar"><div class="progress-fill ${progressClass(mp)}" style="width:${Math.min(mp,100)}%"></div></div></td>
      <td style="color:#7ee787">${real.requests_total ?? '...'}</td>
      <td style="color:#d2a8ff">${real.tokens_total ?? '...'}</td>
      <td style="color:#ffa657">$${(real.cost_total ?? 0)}</td>
      <td><span class="status-dot ${sc}"></span></td>
    </tr>`;
  });
  if (keys.length === 0) {
    html += '<tr><td colspan="7" style="text-align:center;color:#8b949e;padding:40px">No tokens loaded. Generate some first!</td></tr>';
  }
  html += '</table>';
  document.getElementById('tokenTable').innerHTML = html;
}

function loadStatus() {
  fetch('/api/proxy/status?v=' + Date.now())
    .then(r => r.json())
    .then(data => renderStatus(data))
    .catch(e => {
      document.getElementById('tokenTable').innerHTML = '<p style="color:#da3633;text-align:center;padding:20px">Could not load status. Is the proxy running?</p>';
      console.error(e);
    });
}

function loadConfig() {
  fetch('/api/proxy/config')
    .then(r => r.json())
    .then(cfg => {
      let html = '<table>';
      for (const [k, v] of Object.entries(cfg)) {
        html += `<tr><td style="color:#58a6ff;width:200px">${k}</td><td>${v}</td></tr>`;
      }
      html += '</table>';
      document.getElementById('configView').innerHTML = html;
    })
    .catch(() => document.getElementById('configView').textContent = 'Could not load config');
}

function generateTokens() {
  const btn = document.getElementById('genBtn');
  btn.disabled = true;
  btn.textContent = 'Generating...';
  const count = document.getElementById('genCount').value;
  const start = document.getElementById('genStart').value;

  fetch('/api/proxy/generate', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({count: parseInt(count), start: parseInt(start)})
  })
  .then(r => r.json())
  .then(data => {
    if (data.error) {
      showToast('Error: ' + data.error, 'error');
      document.getElementById('genStatus').innerHTML = '<p style="color:#da3633;margin-top:12px">Failed: ' + data.error + '</p>';
    } else {
      showToast('Generated ' + data.tokens + ' tokens!');
      document.getElementById('genStatus').innerHTML = '<p style="color:#238636;margin-top:12px">Done! ' + data.tokens + ' tokens loaded.</p>';
      loadStatus();
    }
    btn.disabled = false;
    btn.textContent = 'Generate';
  })
  .catch(e => {
    showToast('Network error', 'error');
    btn.disabled = false;
    btn.textContent = 'Generate';
  });
}

loadStatus();
loadConfig();
setInterval(loadStatus, 3000);

document.querySelectorAll('.instructions pre').forEach(el => {
  el.textContent = el.textContent.replace(/{host}/g, HOST).replace(/{port}/g, PORT);
});
</script>
</body>
</html>"""


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_tokens():
    if TOKENS_PATH.exists():
        with open(TOKENS_PATH) as f:
            return json.load(f)
    return []


def init_usage(tokens):
    global USAGE
    USAGE = {}
    now = time.time()
    for t in tokens:
        key = t["api_key"]
        USAGE[key] = {
            "api_key": key,
            "email": t.get("email", "unknown"),
            "minute_start": now,
            "minute_count": 0,
            "window_start": now,
            "window_count": 0,
            "week_start": now,
            "week_count": 0,
            "total_count": 0,
            "max_rpm": t.get("max_rpm", 100),
            "window_limit": t.get("requests_per_window", 50),
            "window_hours": t.get("window_hours", 5),
            "week_limit": t.get("requests_per_week", 1250),
            "last_used": 0,
            "errors": 0,
        }


def peek_best_token():
    global TOKEN_INDEX
    now = time.time()

    with TOKEN_LOCK:
        available = []
        for key, stats in USAGE.items():
            if now - stats["minute_start"] > 60:
                stats["minute_start"] = now
                stats["minute_count"] = 0
            if now - stats["window_start"] > stats["window_hours"] * 3600:
                stats["window_start"] = now
                stats["window_count"] = 0
            if now - stats["week_start"] > 7 * 24 * 3600:
                stats["week_start"] = now
                stats["week_count"] = 0

            can_use = True
            rpm_limit = max(stats["max_rpm"], 10)
            win_limit = max(stats["window_limit"], 10)
            wk_limit = max(stats["week_limit"], 100)

            if stats["minute_count"] >= rpm_limit * 0.9:
                can_use = False
            if stats["window_count"] >= win_limit * 0.9:
                can_use = False
            if stats["week_count"] >= wk_limit * 0.9:
                can_use = False

            available.append((key, can_use, stats))

        usable = [(k, s) for k, can, s in available if can]
        if usable:
            usable.sort(key=lambda x: x[1]["minute_count"])
            return usable[0][0]

        exhausted = [(k, s) for k, can, s in available if not can]
        if exhausted:
            exhausted.sort(key=lambda x: min(x[1]["minute_count"], x[1]["window_count"], x[1]["week_count"]))
            return exhausted[0][0]

        if TOKENS:
            return TOKENS[TOKEN_INDEX % len(TOKENS)]["api_key"]

        return None


def count_request(api_key):
    now = time.time()
    with TOKEN_LOCK:
        if api_key in USAGE:
            USAGE[api_key]["minute_count"] += 1
            USAGE[api_key]["window_count"] += 1
            USAGE[api_key]["week_count"] += 1
            USAGE[api_key]["total_count"] += 1
            USAGE[api_key]["last_used"] = now


def get_best_token():
    key = peek_best_token()
    if key:
        count_request(key)
    return key


def mark_token_error(api_key):
    with TOKEN_LOCK:
        if api_key in USAGE:
            USAGE[api_key]["errors"] += 1


def proxy_headers():
    excluded = {"host", "connection", "transfer-encoding", "content-length"}
    headers = {}
    for k, v in request.headers:
        if k.lower() not in excluded:
            headers[k] = v
    headers["Accept-Encoding"] = "identity"
    return headers


@app.route("/v1/models", methods=["GET"])
def proxy_models():
    api_key = get_best_token()
    if not api_key:
        return jsonify({"error": "No tokens available"}), 503

    resp = requests.get(
        f"{OPENFERENCE_API}/v1/models",
        headers={"Authorization": f"Bearer {api_key}"},
        timeout=30,
    )
    return Response(resp.content, status=resp.status_code,
                    content_type=resp.headers.get("Content-Type", "application/json"))


def do_chat_request(body, api_key):
    is_stream = body.get("stream", False)
    headers = proxy_headers()
    headers["Authorization"] = f"Bearer {api_key}"
    headers["Content-Type"] = "application/json"

    upstream = requests.post(
        f"{OPENFERENCE_API}/v1/chat/completions",
        json=body,
        headers=headers,
        stream=is_stream,
        timeout=300,
    )
    return upstream, is_stream


@app.route("/v1/chat/completions", methods=["POST"])
def proxy_chat():
    body = request.get_json(force=True, silent=True) or {}
    is_stream = body.get("stream", False)

    max_retries = max(len(TOKENS) * 2, 3)
    server_errors = 0
    last_api_key = None
    for attempt in range(max_retries):
        api_key = peek_best_token()
        if not api_key:
            return jsonify({"error": "No tokens available"}), 503

        try:
            upstream, _ = do_chat_request(body, api_key)
        except requests.RequestException as e:
            mark_token_error(api_key)
            time.sleep(1)
            continue

        if upstream.status_code in (401, 403, 429):
            if upstream.status_code == 429:
                with TOKEN_LOCK:
                    if api_key in USAGE:
                        USAGE[api_key]["window_count"] = USAGE[api_key]["window_limit"]
                        USAGE[api_key]["minute_count"] = USAGE[api_key]["max_rpm"]
            mark_token_error(api_key)
            time.sleep(0.5)
            continue

        if upstream.status_code in (502, 503, 504):
            server_errors += 1
            if server_errors < 5:
                time.sleep(1.5 * (attempt + 1))
                continue

        count_request(api_key)
        break
    else:
        return jsonify({"error": "All tokens failed or exhausted."}), 502

    if not is_stream:
        return Response(upstream.content, status=upstream.status_code,
                        content_type=upstream.headers.get("Content-Type", "application/json"))

    def generate():
        try:
            for chunk in upstream.iter_content(chunk_size=None):
                if chunk:
                    yield chunk
        except Exception:
            pass

    return Response(
        stream_with_context(generate()),
        status=upstream.status_code,
        content_type=upstream.headers.get("Content-Type", "text/event-stream"),
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/v1/<path:subpath>", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
def proxy_v1(subpath):
    if request.method == "OPTIONS":
        return Response(status=200)

    api_key = get_best_token()
    if not api_key:
        return jsonify({"error": "No tokens available"}), 503

    url = f"{OPENFERENCE_API}/v1/{subpath}"
    headers = proxy_headers()
    headers["Authorization"] = f"Bearer {api_key}"

    try:
        if request.method == "GET":
            r = requests.get(url, headers=headers, timeout=60, params=request.args)
        elif request.method == "POST":
            r = requests.post(url, headers=headers, timeout=60, json=request.get_json(silent=True) or {})
        else:
            r = requests.request(request.method, url, headers=headers, timeout=60,
                                data=request.get_data(), params=request.args)
    except requests.RequestException as e:
        mark_token_error(api_key)
        return jsonify({"error": str(e)}), 502

    return Response(r.content, status=r.status_code,
                    content_type=r.headers.get("Content-Type", "application/json"))


def sync_usage_from_api():
    global REAL_USAGE
    with SYNC_LOCK:
        for t in TOKENS:
            session = t.get("session_token", "")
            if not session or not session.startswith("session_"):
                continue
            api_key = t["api_key"]
            try:
                r = requests.get(
                    f"{OPENFERENCE_WEB}/api/user/usage?days=1",
                    headers={"Authorization": f"Bearer {session}"},
                    timeout=10,
                )
                if r.status_code != 200:
                    continue
                data = r.json()
                total = data.get("total", {})
                day = (data.get("daily") or [{}])[-1]
                per_token_list = data.get("perToken", [])

                pt_requests = 0
                pt_tokens = 0
                for pt in per_token_list:
                    if str(pt.get("token_id")) == str(t.get("token_id", "")):
                        pt_requests = pt.get("requests", 0)
                        pt_tokens = pt.get("tokens", 0)
                        break

                REAL_USAGE[api_key] = {
                    "email": t.get("email", "?"),
                    "requests_total": total.get("requests", 0),
                    "tokens_total": total.get("tokens", 0),
                    "cost_total": total.get("cost", 0),
                    "requests_today": day.get("requests", 0),
                    "tokens_today": day.get("tokens", 0),
                    "cost_today": day.get("cost", 0),
                    "per_token_requests": pt_requests,
                    "per_token_tokens": pt_tokens,
                    "last_sync": datetime.now(timezone.utc).isoformat(),
                }
            except Exception:
                pass


def sync_usage_loop(interval=45):
    while True:
        time.sleep(interval)
        try:
            sync_usage_from_api()
        except Exception:
            pass
        try:
            global TOKENS
            fresh = load_tokens()
            if fresh and len(fresh) != len(TOKENS):
                TOKENS = fresh
                init_usage(TOKENS)
                print(f"[sync] Reloaded tokens: {len(TOKENS)} total")
        except Exception:
            pass


@app.route("/", methods=["GET"])
def index():
    resp = Response(DASHBOARD_HTML, content_type="text/html")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/api/proxy/generate", methods=["POST"])
def proxy_generate_token():
    data = request.get_json(silent=True) or {}
    count = int(data.get("count", 1))
    start = int(data.get("start", 1))
    if count < 1:
        count = 1

    try:
        config = load_config()
        config["account_count"] = count
        config["start_index"] = start
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=2)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    try:
        result = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "token_manager.py"), "--no-input"],
            cwd=str(Path(__file__).parent),
            capture_output=True, text=True, timeout=600,
        )
        global TOKENS, USAGE
        new_tokens = load_tokens()
        if new_tokens:
            TOKENS = new_tokens
            init_usage(TOKENS)
        return jsonify({"status": "done", "tokens": len(TOKENS), "output": result.stdout[-500:]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/proxy/config", methods=["GET"])
def proxy_config():
    try:
        config = load_config()
        safe = {}
        for k, v in config.items():
            if "password" in k.lower():
                safe[k] = "***" if v else ""
            else:
                safe[k] = v
        return jsonify(safe)
    except Exception as e:
        return jsonify({"error": str(e)})


@app.route("/api/proxy/status", methods=["GET"])
def proxy_status():
    return jsonify({
        "tokens_loaded": len(TOKENS),
        "usage": {k: {
            "email": v["email"],
            "minute_count": v["minute_count"],
            "window_count": v["window_count"],
            "week_count": v["week_count"],
            "total_count": v["total_count"],
            "max_rpm": v["max_rpm"],
            "window_limit": v["window_limit"],
            "week_limit": v["week_limit"],
            "errors": v["errors"],
            "real": REAL_USAGE.get(k),
        } for k, v in USAGE.items()},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/api/proxy/refresh", methods=["POST"])
def proxy_refresh():
    global TOKENS
    new_tokens = load_tokens()
    if new_tokens:
        TOKENS = new_tokens
        init_usage(TOKENS)
        return jsonify({"status": "refreshed", "count": len(TOKENS)})
    return jsonify({"error": "No tokens found"}), 400


def start_proxy(host="127.0.0.1", port=8787):
    global TOKENS
    config = load_config()
    host = config.get("proxy_host", host)
    port = config.get("proxy_port", port)

    TOKENS = load_tokens()
    if not TOKENS:
        print("WARNING: No tokens loaded! Run token_manager.py first.")
        print("The proxy will start but won't be able to forward requests.")
    else:
        init_usage(TOKENS)
        total_weekly = sum(
            t.get("requests_per_week", 0) or 0 for t in TOKENS
        )
        print(f"Loaded {len(TOKENS)} tokens ({total_weekly} combined weekly requests)")

    print(f"\nProxy starting on http://{host}:{port}")
    print(f"Status page: http://{host}:{port}/")
    print(f"API status:  http://{host}:{port}/api/proxy/status")
    print(f"\nFor CLAUDE CODE set:")
    print(f'  set ANTHROPIC_BASE_URL=http://{host}:{port}/v1')
    print(f'  set ANTHROPIC_API_KEY=anything')
    print(f"\nFor OPENCODE set in opencode.json:")
    print(f'  "baseURL": "http://{host}:{port}/v1"')
    print(f"\nPress Ctrl+C to stop.\n")

    sync_thread = threading.Thread(target=sync_usage_loop, args=(45,), daemon=True)
    sync_thread.start()
    print("[sync] Background usage sync started (every 45s)")

    app.run(host=host, port=port, debug=False, threaded=True)


if __name__ == "__main__":
    start_proxy()
