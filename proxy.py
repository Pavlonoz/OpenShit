import json
import os
import re
import sys
import time
import threading
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
from flask import Flask, request, Response, jsonify, stream_with_context
import logging
log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)

from proxy_rotator import (
    make_request as proxied_request,
    load_and_filter,
    test_proxy_batch,
    has_proxies,
    proxy_count,
    refresh_proxies,
)

RESIDENTIAL_FILE = Path(__file__).parent / "residential_proxies.txt"

CONFIG_PATH = Path(__file__).parent / "config.json"
TOKENS_PATH = Path(__file__).parent / "tokens.json"

app = Flask(__name__)

TOKENS = []
TOKEN_INDEX = 0
TOKEN_LOCK = threading.Lock()
TOKEN_EVENT = threading.Event()

USAGE = {}
REAL_USAGE = {}
SYNC_LOCK = threading.Lock()

OPENFERENCE_API = "https://api.openference.com"
OPENFERENCE_WEB = "https://openference.com"

AUTO_GEN_LOCK = threading.Lock()
_auto_gen_running = False
_last_auto_gen = 0
_auto_gen_min_interval = 60

_auto_gen_enabled = True
_auto_gen_threshold = 0.5
_auto_gen_count = 2
_auto_gen_min_tokens = 3

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
.auto-gen-badge{background:#1f6feb;color:#fff;padding:4px 12px;border-radius:12px;font-size:12px;font-weight:600;margin-left:8px;display:none}
</style>
</head>
<body>
<div class="header">
  <h1>Openshit Proxy</h1>
  <div>
    <span class="auto-gen-badge" id="autoGenBadge">AUTO-GEN ACTIVE</span>
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
      <h2>Token Usage <span style="font-size:12px;color:#8b949e;font-weight:normal;margin-left:8px" id="proxyStatus"></span></h2>
      <div id="tokenTable"></div>
    </div>
  </div>

  <div id="tab-generate" style="display:none">
    <div class="panel">
      <h2>Generate API Tokens</h2>
      <p style="color:#8b949e;font-size:14px;margin-bottom:16px">Create new Openference accounts. Auto-generation creates tokens when usage hits 50%.</p>
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
        <p>Then run <code>claude</code> as usual.</p>
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
  if (data.auto_gen) {
    document.getElementById('autoGenBadge').style.display = 'inline-block';
    document.getElementById('autoGenBadge').textContent = 'AUTO-GEN: ' + data.auto_gen;
  } else {
    document.getElementById('autoGenBadge').style.display = 'none';
  }
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

  document.getElementById('proxyStatus').textContent =
    'Proxies: ' + (data.proxies_available || 0) + ' | ' +
    'Auto-gen: ' + (data.auto_gen_enabled ? 'ON (' + (data.auto_gen_threshold*100) + '%)' : 'OFF');

  let html = '<table><tr><th>#</th><th>Email</th><th>Usage %</th><th>Req (proxy)</th><th>Real Req</th><th>Real Tok</th><th>Cost</th><th></th></tr>';
  keys.forEach((k, i) => {
    const u = usage[k];
    const real = u.real || {};
    const maxPct = Math.max(
      u.max_rpm > 0 ? u.minute_count / u.max_rpm * 100 : 0,
      u.window_limit > 0 ? u.window_count / u.window_limit * 100 : 0,
      u.week_limit > 0 ? u.week_count / u.week_limit * 100 : 0
    );
    const sc = statusClass(maxPct);
    html += `<tr>
      <td style="color:#484f58">${i+1}</td>
      <td style="color:#58a6ff">${u.email}</td>
      <td>${maxPct.toFixed(0)}%<div class="progress-bar"><div class="progress-fill ${progressClass(maxPct)}" style="width:${Math.min(maxPct,100)}%"></div></div></td>
      <td>${u.total_count}</td>
      <td style="color:#7ee787">${real.requests_total ?? '...'}</td>
      <td style="color:#d2a8ff">${real.tokens_total ?? '...'}</td>
      <td style="color:#ffa657">$${(real.cost_total ?? 0).toFixed(4)}</td>
      <td><span class="status-dot ${sc}"></span></td>
    </tr>`;
  });
  if (keys.length === 0) {
    html += '<tr><td colspan="8" style="text-align:center;color:#8b949e;padding:40px">No tokens loaded. Generate some first!</td></tr>';
  }
  html += '</table>';
  document.getElementById('tokenTable').innerHTML = html;
}

function loadStatus() {
  fetch('/api/proxy/status?v=' + Date.now())
    .then(r => r.json())
    .then(data => renderStatus(data))
    .catch(e => {
      document.getElementById('tokenTable').innerHTML = '<p style="color:#da3633;text-align:center;padding:20px">Could not load status.</p>';
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
    body: JSON.stringify({count: parseInt(count), start: parseInt(start), threaded: true})
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


def save_tokens(tokens):
    with open(TOKENS_PATH, "w") as f:
        json.dump(tokens, f, indent=2)


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


def acquire_token():
    with TOKEN_LOCK:
        now = time.time()
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

            rpm_limit = max(stats["max_rpm"], 10)
            win_limit = max(stats["window_limit"], 10)
            wk_limit = max(stats["week_limit"], 100)

            can_use = True
            if stats["minute_count"] >= rpm_limit * 0.9:
                can_use = False
            if stats["window_count"] >= win_limit * 0.9:
                can_use = False
            if stats["week_count"] >= wk_limit * 0.9:
                can_use = False

            available.append((key, can_use, stats))

        usable = [(k, s) for k, can, s in available if can]
        closest_to_limit = None

        if usable:
            usable.sort(key=lambda x: (
                x[1]["minute_count"] / max(x[1]["max_rpm"], 1),
                x[1]["window_count"] / max(x[1]["window_limit"], 1),
                x[1]["week_count"] / max(x[1]["week_limit"], 1),
            ))
            closest_to_limit = usable[-1]
            selected_key = usable[0][0]
        else:
            exhausted = [(k, s) for k, can, s in available if not can]
            if exhausted:
                exhausted.sort(key=lambda x: min(
                    x[1]["minute_count"] / max(x[1]["max_rpm"], 1),
                    x[1]["window_count"] / max(x[1]["window_limit"], 1),
                    x[1]["week_count"] / max(x[1]["week_limit"], 1),
                ))
                closest_to_limit = exhausted[0]
                selected_key = exhausted[0][0]
            elif TOKENS:
                selected_key = TOKENS[0]["api_key"]
                closest_to_limit = None
            else:
                return None, None

        if selected_key in USAGE:
            USAGE[selected_key]["minute_count"] += 1
            USAGE[selected_key]["window_count"] += 1
            USAGE[selected_key]["week_count"] += 1
            USAGE[selected_key]["total_count"] += 1
            USAGE[selected_key]["last_used"] = now

        return selected_key, closest_to_limit


def get_token_usage_pct(api_key):
    with TOKEN_LOCK:
        if api_key not in USAGE:
            return 0.0
        s = USAGE[api_key]
        pcts = []
        if s["max_rpm"] > 0:
            pcts.append(s["minute_count"] / s["max_rpm"])
        if s["window_limit"] > 0:
            pcts.append(s["window_count"] / s["window_limit"])
        if s["week_limit"] > 0:
            pcts.append(s["week_count"] / s["week_limit"])
        return max(pcts) if pcts else 0.0


def get_min_token_usage_pct():
    with TOKEN_LOCK:
        if not USAGE:
            return 1.0
        min_pct = 1.0
        for key, stats in USAGE.items():
            pcts = []
            if stats["max_rpm"] > 0:
                pcts.append(stats["minute_count"] / stats["max_rpm"])
            if stats["window_limit"] > 0:
                pcts.append(stats["window_count"] / stats["window_limit"])
            if stats["week_limit"] > 0:
                pcts.append(stats["week_count"] / stats["week_limit"])
            pct = max(pcts) if pcts else 0.0
            if pct < min_pct:
                min_pct = pct
        return min_pct


def mark_token_error(api_key):
    with TOKEN_LOCK:
        if api_key in USAGE:
            USAGE[api_key]["errors"] += 1


def mark_token_exhausted(api_key):
    with TOKEN_LOCK:
        if api_key in USAGE:
            USAGE[api_key]["window_count"] = USAGE[api_key]["window_limit"]
            USAGE[api_key]["minute_count"] = USAGE[api_key]["max_rpm"]
            USAGE[api_key]["week_count"] = USAGE[api_key]["week_limit"]


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
    api_key, _ = acquire_token()
    if not api_key:
        return jsonify({"error": "No tokens available"}), 503

    try:
        resp = proxied_request("GET",
            f"{OPENFERENCE_API}/v1/models",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30,
        )
    except Exception as e:
        mark_token_error(api_key)
        return jsonify({"error": str(e)}), 502

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

    max_retries = max(len(TOKENS) * 3, 5)
    server_errors = 0
    last_status = None

    for attempt in range(max_retries):
        api_key, _ = acquire_token()
        if not api_key:
            return jsonify({"error": "No tokens available"}), 503

        try:
            upstream, _ = do_chat_request(body, api_key)
        except Exception as e:
            mark_token_error(api_key)
            time.sleep(0.5)
            continue

        if upstream.status_code in (401, 403):
            mark_token_error(api_key)
            time.sleep(0.3)
            continue

        if upstream.status_code == 429:
            mark_token_exhausted(api_key)
            mark_token_error(api_key)
            time.sleep(0.5)
            continue

        if upstream.status_code in (502, 503, 504):
            server_errors += 1
            if server_errors < 5:
                time.sleep(1.5 * (attempt + 1))
                continue

        last_status = upstream.status_code
        break
    else:
        return jsonify({"error": "All tokens failed or exhausted.", "status": last_status}), 502

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

    api_key, _ = acquire_token()
    if not api_key:
        return jsonify({"error": "No tokens available"}), 503

    url = f"{OPENFERENCE_API}/v1/{subpath}"
    headers = proxy_headers()
    headers["Authorization"] = f"Bearer {api_key}"

    try:
        if request.method == "GET":
            r = proxied_request("GET", url, headers=headers, timeout=60, params=request.args)
        elif request.method == "POST":
            r = proxied_request("POST", url, headers=headers, timeout=60, json=request.get_json(silent=True) or {})
        else:
            r = proxied_request(request.method, url, headers=headers, timeout=60,
                                data=request.get_data(), params=request.args)
    except Exception as e:
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
                r = proxied_request("GET",
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


def auto_generate_tokens(reason=""):
    global _auto_gen_running, _last_auto_gen, TOKENS

    with AUTO_GEN_LOCK:
        if _auto_gen_running:
            return
        now = time.time()
        if now - _last_auto_gen < _auto_gen_min_interval:
            return
        _auto_gen_running = True
        _last_auto_gen = now

    try:
        config = load_config()
        existing = load_tokens()
        existing_indices = {t["index"] for t in existing}
        next_index = max(existing_indices) + 1 if existing_indices else config.get("start_index", 1)
        count = config.get("auto_gen_count", _auto_gen_count)

        print(f"\n[AUTO-GEN] Triggered ({reason}). Creating {count} accounts starting at #{next_index}...")

        from token_manager import process_one_account as process_account

        results = []
        with ThreadPoolExecutor(max_workers=min(count, 4)) as executor:
            futures = {
                executor.submit(process_account, config, next_index + i): next_index + i
                for i in range(count)
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    entry = future.result(timeout=120)
                    if entry:
                        results.append(entry)
                        print(f"  [AUTO-GEN] Account #{idx} created: {entry.get('email')}")
                except Exception as e:
                    print(f"  [AUTO-GEN] Account #{idx} failed: {e}")

        if results:
            all_tokens = existing + results
            save_tokens(all_tokens)
            TOKENS = all_tokens
            init_usage(TOKENS)
            print(f"[AUTO-GEN] Successfully added {len(results)} new tokens. Total: {len(TOKENS)}")
        else:
            print(f"[AUTO-GEN] No new tokens created.")

    except Exception as e:
        print(f"[AUTO-GEN] Error: {e}")
    finally:
        with AUTO_GEN_LOCK:
            _auto_gen_running = False


def _check_auto_gen_needed():
    global _auto_gen_enabled, _auto_gen_threshold, _auto_gen_min_tokens, _auto_gen_count, _auto_gen_min_interval
    config = load_config()
    _auto_gen_enabled = config.get("auto_generate", True)
    _auto_gen_threshold = config.get("auto_gen_threshold", 0.5)
    _auto_gen_min_tokens = config.get("auto_gen_min_tokens", 3)
    _auto_gen_count = config.get("auto_gen_count", 2)
    _auto_gen_min_interval = config.get("auto_gen_cooldown", 1800)

    if not _auto_gen_enabled:
        return

    max_tokens = config.get("auto_gen_max_tokens", 50)

    with TOKEN_LOCK:
        now = time.time()
        if now - _last_auto_gen < _auto_gen_min_interval:
            return

        if len(TOKENS) >= max_tokens:
            return

        if len(TOKENS) == 0:
            print(f"[AUTO-GEN] No tokens loaded, triggering initial generation...")
            auto_generate_tokens("initial boot")
            return

        if not USAGE:
            return

        any_above_threshold = False
        usable_count = 0
        for key, stats in USAGE.items():
            pcts = []
            if stats["max_rpm"] > 0:
                pcts.append(stats["minute_count"] / stats["max_rpm"])
            if stats["window_limit"] > 0:
                pcts.append(stats["window_count"] / stats["window_limit"])
            if stats["week_limit"] > 0:
                pcts.append(stats["week_count"] / stats["week_limit"])
            max_pct = max(pcts) if pcts else 0
            if max_pct >= _auto_gen_threshold:
                any_above_threshold = True
            if max_pct < 0.85:
                usable_count += 1

        total = len(USAGE)

        if usable_count <= 1 and total > 0:
            print(f"[AUTO-GEN] Only {usable_count}/{total} tokens usable, triggering generation...")
            auto_generate_tokens("low token availability")
        elif any_above_threshold:
            print(f"[AUTO-GEN] Tokens at >= {_auto_gen_threshold*100:.0f}% usage, triggering generation...")
            auto_generate_tokens("usage threshold reached")


def sync_usage_loop(interval=30):
    global _auto_gen_threshold, _auto_gen_enabled, TOKENS
    first_run = True
    while True:
        if not first_run:
            time.sleep(interval)
        first_run = False
        try:
            sync_usage_from_api()
        except Exception:
            pass
        try:
            fresh = load_tokens()
            if fresh and len(fresh) != len(TOKENS):
                TOKENS = fresh
                init_usage(TOKENS)
                print(f"[sync] Reloaded tokens: {len(TOKENS)} total")
        except Exception:
            pass
        try:
            _check_auto_gen_needed()
        except Exception as e:
            print(f"[AUTO-GEN] Check error: {e}")


@app.route("/", methods=["GET"])
def index():
    resp = Response(DASHBOARD_HTML, content_type="text/html")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/api/proxy/generate", methods=["POST"])
def proxy_generate_token():
    global TOKENS
    data = request.get_json(silent=True) or {}
    count = int(data.get("count", 1))
    start = int(data.get("start", 1))
    threaded = data.get("threaded", False)

    if count < 1:
        count = 1
    if count > 10:
        count = 10

    config = load_config()
    existing = load_tokens()
    existing_indices = {t["index"] for t in existing}
    if start == 0 or data.get("start") is None:
        start = max(existing_indices) + 1 if existing_indices else config.get("start_index", 1)

    print(f"\n[GEN] Starting generation of {count} accounts from index {start} (threaded={threaded})")

    if threaded:
        from token_manager import process_one_account as process_account

        new_tokens = []
        errors = []
        with ThreadPoolExecutor(max_workers=min(count, 4)) as executor:
            futures = {
                executor.submit(process_account, config, start + i): start + i
                for i in range(count)
            }
            for future in as_completed(futures):
                idx = futures[future]
                try:
                    entry = future.result(timeout=120)
                    if entry:
                        new_tokens.append(entry)
                        print(f"  [GEN] Account #{idx} done: {entry.get('email')}")
                    else:
                        errors.append(idx)
                except Exception as e:
                    print(f"  [GEN] Account #{idx} failed: {e}")
                    errors.append(idx)

        new_tokens.sort(key=lambda t: t["index"])
        all_tokens = existing + new_tokens
        save_tokens(all_tokens)
        TOKENS = all_tokens
        init_usage(TOKENS)

        return jsonify({
            "status": "done",
            "tokens": len(new_tokens),
            "total": len(all_tokens),
            "errors": len(errors),
        })
    else:
        try:
            result = subprocess.run(
                [sys.executable, str(Path(__file__).parent / "token_manager.py"),
                 "--no-input", "--count", str(count), "--start", str(start)],
                cwd=str(Path(__file__).parent),
                capture_output=True, text=True, timeout=600,
            )
            new_tokens = load_tokens()
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
    config = load_config()
    return jsonify({
        "tokens_loaded": len(TOKENS),
        "proxies_available": proxy_count(),
        "auto_gen_enabled": config.get("auto_generate", True),
        "auto_gen_threshold": config.get("auto_gen_threshold", 0.5),
        "auto_gen": "running" if _auto_gen_running else "idle",
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
    global TOKENS, _auto_gen_enabled, _auto_gen_threshold, _auto_gen_count, _auto_gen_min_tokens
    config = load_config()
    host = config.get("proxy_host", host)
    port = config.get("proxy_port", port)

    _auto_gen_enabled = config.get("auto_generate", True)
    _auto_gen_threshold = config.get("auto_gen_threshold", 0.5)
    _auto_gen_count = config.get("auto_gen_count", 2)
    _auto_gen_min_tokens = config.get("auto_gen_min_tokens", 3)

    print()
    print(" ______                                  ______   __        __    __")
    print("/      \\                                /      \\ /  |      /  |  /  |")
    print("/$$$$$$  |  ______    ______   _______  /$$$$$$  |$$ |____  $$/  _$$ |_")
    print("$$ |  $$ | /      \\  /      \\ /       \\ $$ \\__$$/ $$      \\ /  |/ $$   |")
    print("$$ |  $$ |/$$$$$$  |/$$$$$$  |$$$$$$$  |$$      \\ $$$$$$$  |$$ |$$$$$$/")
    print("$$ |  $$ |$$ |  $$ |$$    $$ |$$ |  $$ | $$$$$$  |$$ |  $$ |$$ |  $$ | __")
    print("$$ \\__$$ |$$ |__$$ |$$$$$$$$/ $$ |  $$ |/  \\__$$ |$$ |  $$ |$$ |  $$ |/  |")
    print("$$    $$/ $$    $$/ $$       |$$ |  $$ |$$    $$/ $$ |  $$ |$$ |  $$  $$/")
    print(" $$$$$$/  $$$$$$$/   $$$$$$$/ $$/   $$/  $$$$$$/  $$/   $$/ $$/    $$$$/")
    print("          $$ |")
    print("          $$ |")
    print("          $$/")
    print("                    made by Pavlonoz <3")
    print("=" * 74)
    print()

    if not RESIDENTIAL_FILE.exists():
        print("  [ERROR] No residential_proxies.txt found!")
        print("  [ERROR] Residential proxies are REQUIRED for account creation.")
        print("  [ERROR] Get 10 free residential proxies at: https://webshare.io")
        print("  [ERROR] File format: ip:port:user:pass (one per line)")
        print()
        return

    res_count = 0
    try:
        res_count = sum(1 for l in open(RESIDENTIAL_FILE) if l.strip() and not l.strip().startswith("#") and l.count(":") >= 3)
    except Exception:
        pass
    if res_count == 0:
        print("  [ERROR] residential_proxies.txt is empty or has invalid format!")
        print("  [ERROR] Format: ip:port:user:pass (one per line)")
        print()
        return

    print("  Initializing proxy pool...")
    load_and_filter()

    TOKENS = load_tokens()
    if TOKENS:
        init_usage(TOKENS)
        total_rpm = sum(t.get("max_rpm", 0) or 0 for t in TOKENS)
        total_weekly = sum(t.get("requests_per_week", 0) or 0 for t in TOKENS)
        print(f"  Tokens:     {len(TOKENS)} loaded ({total_weekly}/week, {total_rpm}/min)")
    else:
        print(f"  Tokens:     0 (will auto-generate on startup)")

    print(f"  Proxies:    {proxy_count()} total ({res_count} residential)")
    print(f"  Auto-gen:   {'ON' if _auto_gen_enabled else 'OFF'} (at {_auto_gen_threshold*100:.0f}%, {_auto_gen_count} at a time)")
    print(f"  Dashboard:  http://{host}:{port}/")
    print()
    print(f"  Account creation takes 2-5 minutes per account.")
    print(f"  For Claude Code: set ANTHROPIC_BASE_URL=http://{host}:{port}/v1")
    print(f"  Press Ctrl+C to stop.")
    print()

    sync_thread = threading.Thread(target=sync_usage_loop, args=(30,), daemon=True)
    sync_thread.start()

    proxy_refresh_thread = threading.Thread(target=_proxy_refresh_loop, args=(300,), daemon=True)
    proxy_refresh_thread.start()

    app.run(host=host, port=port, debug=False, threaded=True)


def _proxy_refresh_loop(interval=300):
    while True:
        time.sleep(interval)
        try:
            new_count = refresh_proxies()
            test_proxy_batch(10)
            print(f"[proxy-pool] Refreshed: {proxy_count()} proxies available")
        except Exception:
            pass


if __name__ == "__main__":
    start_proxy()
