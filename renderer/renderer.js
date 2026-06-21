let config = {};
let tokens = [];
let proxyRunning = false;
let liveInterval = null;

document.addEventListener("DOMContentLoaded", init);

async function init() {
  await loadConfig();
  await loadTokens();
  await checkPython();
  await checkProxyStatus();

  setupNav();
  setupButtons();
  renderDashboard();
  renderSettings();
}

async function loadConfig() {
  config = await window.api.getConfig();
}

async function loadTokens() {
  tokens = await window.api.getTokens();
}

async function checkPython() {
  const p = await window.api.findPython();
  document.getElementById("python-status").textContent = p.found
    ? `Python found: ${p.path}`
    : "Python NOT found. Install Python 3.11+.";
}

async function checkProxyStatus() {
  const s = await window.api.getProxyStatus();
  proxyRunning = s.running;
  updateProxyIndicator();
  if (proxyRunning) startLivePoll();
}

function updateProxyIndicator() {
  const dot = document.querySelector("#proxy-indicator .status-dot");
  const label = document.getElementById("proxy-label");
  const btn = document.getElementById("btn-proxy-toggle");
  const badge = document.getElementById("live-badge");

  if (proxyRunning) {
    dot.className = "status-dot on";
    label.textContent = "Proxy Online";
    btn.textContent = "Stop Proxy";
    if (badge) badge.style.display = "";
    startLivePoll();
  } else {
    dot.className = "status-dot off";
    label.textContent = "Proxy Offline";
    btn.textContent = "Start Proxy";
    if (badge) badge.style.display = "none";
    stopLivePoll();
  }
}

function startLivePoll() {
  stopLivePoll();
  if (!proxyRunning) return;
  liveInterval = setInterval(pollLiveStats, 5000);
  pollLiveStats();
}

function stopLivePoll() {
  if (liveInterval) { clearInterval(liveInterval); liveInterval = null; }
}

async function pollLiveStats() {
  try {
    const port = config.proxy_port || 8787;
    const r = await fetch(`http://127.0.0.1:${port}/api/proxy/status`);
    const d = await r.json();
    updateLiveStats(d);
  } catch (_) {}
}

function updateLiveStats(data) {
  const usage = data.usage || {};
  const keys = Object.keys(usage);

  let totalWindow = 0;
  let totalWindowLimit = 0;
  let totalRequests = 0;

  keys.forEach((k) => {
    const u = usage[k];
    totalWindow += u.window_count || 0;
    totalWindowLimit += u.window_limit || 50;
    totalRequests += u.total_count || 0;
  });

  document.getElementById("stat-window").textContent = `${totalWindow} / ${totalWindowLimit}`;
  document.getElementById("stat-requests").textContent = totalRequests;

  const pct = totalWindowLimit > 0 ? Math.min((totalWindow / totalWindowLimit) * 100, 100) : 0;
  const bar = document.getElementById("stat-window-bar");
  bar.style.width = pct + "%";
  if (pct > 80) bar.style.background = "#c00";
  else if (pct > 50) bar.style.background = "#d29922";
  else bar.style.background = "#111";

  document.getElementById("stat-weekly").textContent =
    keys.reduce((s, k) => s + (usage[k].week_limit || 1250), 0);

  const tbody = document.getElementById("token-tbody");
  const empty = document.getElementById("empty-tokens");
  if (tokens.length === 0) {
    tbody.innerHTML = "";
    empty.style.display = "block";
  } else {
    empty.style.display = "none";
    tbody.innerHTML = tokens.map((t, i) => {
      const u = usage[t.api_key];
      const wc = u ? u.window_count : 0;
      const wl = u ? u.window_limit : 50;
      const wp = wl > 0 ? Math.min((wc / wl) * 100, 100) : 0;
      return `<tr>
        <td>${i + 1}</td>
        <td>${t.email || "?"}</td>
        <td>${wc}/${wl}<div class="stat-bar-wrap"><div class="stat-bar" style="width:${wp}%;background:${wp > 80 ? '#c00' : wp > 50 ? '#d29922' : '#111'}"></div></div></td>
        <td style="font-family:monospace;font-size:10px">${(t.api_key || "").slice(0, 14)}...</td>
        <td>${t.plan || "Free"}</td>
      </tr>`;
    }).join("");
  }

  document.getElementById("stat-accounts").textContent = tokens.length;
}

function setupNav() {
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.addEventListener("click", () => {
      document.querySelectorAll(".nav-item").forEach((i) => i.classList.remove("active"));
      item.classList.add("active");
      const tab = item.dataset.tab;
      document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
      document.getElementById("tab-" + tab).classList.add("active");
      if (tab === "dashboard") renderDashboard();
      if (tab === "settings") renderSettings();
    });
  });
}

function setupButtons() {
  document.getElementById("btn-min").addEventListener("click", () => window.api.windowMinimize());
  document.getElementById("btn-close").addEventListener("click", () => window.api.windowClose());

  document.getElementById("btn-proxy-toggle").addEventListener("click", async () => {
    if (proxyRunning) {
      await window.api.stopProxy();
      proxyRunning = false;
      updateProxyIndicator();
    } else {
      const r = await window.api.startProxy();
      if (!r.ok) { alert(r.msg); return; }
      proxyRunning = true;
      document.getElementById("log-output").textContent = "";
      updateProxyIndicator();
    }
  });

  document.getElementById("btn-save-settings").addEventListener("click", saveSettings);
  document.getElementById("btn-generate").addEventListener("click", generateTokens);
  document.getElementById("btn-clear-logs").addEventListener("click", () => {
    document.getElementById("log-output").textContent = "";
  });

  document.getElementById("btn-setup-opencode").addEventListener("click", async () => {
    const r = await window.api.setupOpenCode();
    const s = document.getElementById("opencode-status");
    if (r.ok) {
      s.textContent = `Done. Config: ${r.cfgPath}`;
      s.style.color = "#080";
    } else {
      s.textContent = "Failed";
      s.style.color = "#c00";
    }
  });

  document.getElementById("btn-setup-claude").addEventListener("click", async () => {
    const r = await window.api.setupClaude();
    const s = document.getElementById("claude-status");
    if (r.ok) {
      s.textContent = `Done. Launcher on Desktop.`;
      s.style.color = "#080";
    } else {
      s.textContent = "Failed";
      s.style.color = "#c00";
    }
  });

  window.api.onProxyLog((data) => {
    const log = document.getElementById("log-output");
    log.textContent += data;
    log.scrollTop = log.scrollHeight;
  });
  window.api.onProxyStopped(() => {
    proxyRunning = false;
    updateProxyIndicator();
  });
}

function renderDashboard() {
  pollLiveStats();
}

function renderSettings() {
  document.getElementById("cfg-email-base").value = config.email_base || "";
  document.getElementById("cfg-email-pass").value = config.email_password || "";
  document.getElementById("cfg-account-pass").value = config.account_password || "";
  document.getElementById("cfg-count").value = config.account_count || 5;
  document.getElementById("cfg-start").value = config.start_index || 1;
  document.getElementById("cfg-port").value = config.proxy_port || 8787;
}

async function saveSettings() {
  config.email_base = document.getElementById("cfg-email-base").value.trim();
  config.email_password = document.getElementById("cfg-email-pass").value.trim();
  config.account_password = document.getElementById("cfg-account-pass").value.trim();
  config.account_count = parseInt(document.getElementById("cfg-count").value) || 5;
  config.start_index = parseInt(document.getElementById("cfg-start").value) || 1;
  config.proxy_port = parseInt(document.getElementById("cfg-port").value) || 8787;
  config.proxy_host = "127.0.0.1";
  config.registration_user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36";
  await window.api.saveConfig(config);
  renderDashboard();
}

async function generateTokens() {
  const output = document.getElementById("gen-output");
  const wrap = document.getElementById("gen-progress-wrap");
  const bar = document.getElementById("gen-progress-bar");

  output.textContent = "Starting...\n";
  wrap.style.display = "block";
  bar.style.width = "0%";

  const onProgress = (data) => {
    const pct = Math.round((data.current / data.total) * 100);
    bar.style.width = Math.min(pct, 100) + "%";
    output.textContent += `Account ${data.current}/${data.total}...\n`;
    output.scrollTop = output.scrollHeight;
  };

  window.api.onGenerateProgress(onProgress);

  const r = await window.api.generateTokens();

  bar.style.width = "100%";
  output.textContent += r.output || r.msg || "Done.";

  await loadTokens();
  renderDashboard();
}
