const { app, BrowserWindow, ipcMain, dialog } = require("electron");
const path = require("path");
const fs = require("fs");
const { spawn, execSync } = require("child_process");

let mainWindow;
let proxyProcess = null;
let userDataPath;

function getDataPath() {
  const p = path.join(app.getPath("userData"), "OpenShit");
  if (!fs.existsSync(p)) fs.mkdirSync(p, { recursive: true });
  return p;
}

function getConfigPath() {
  return path.join(getDataPath(), "config.json");
}

function getTokensPath() {
  return path.join(getDataPath(), "tokens.json");
}

function getBackendPath() {
  if (app.isPackaged) {
    return path.join(process.resourcesPath, "backend");
  }
  return path.join(__dirname, "backend");
}

function loadConfig() {
  const p = getConfigPath();
  const rootCfg = path.join(__dirname, "config.json");

  if (!fs.existsSync(p) && fs.existsSync(rootCfg)) {
    fs.copyFileSync(rootCfg, p);
  }
  if (fs.existsSync(p)) {
    const cfg = JSON.parse(fs.readFileSync(p, "utf-8"));
    cfg.openference_base = cfg.openference_base || "https://openference.com";
    cfg.openference_api_base = cfg.openference_api_base || "https://api.openference.com";
    return cfg;
  }
  return {
    email_base: "",
    email_password: "",
    account_password: "",
    account_count: 5,
    start_index: 1,
    proxy_port: 8787,
    proxy_host: "127.0.0.1",
    registration_user_agent:
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    openference_base: "https://openference.com",
    openference_api_base: "https://api.openference.com",
  };
}

function loadTokens() {
  const p = getTokensPath();
  const rootTokens = path.join(__dirname, "tokens.json");

  if (!fs.existsSync(p) && fs.existsSync(rootTokens)) {
    fs.copyFileSync(rootTokens, p);
  }
  if (fs.existsSync(p)) return JSON.parse(fs.readFileSync(p, "utf-8"));
  return [];
}

function saveConfig(cfg) {
  fs.writeFileSync(getConfigPath(), JSON.stringify(cfg, null, 2));
}

function loadTokens() {
  const p = getTokensPath();
  if (fs.existsSync(p)) return JSON.parse(fs.readFileSync(p, "utf-8"));
  return [];
}

function findPython() {
  const candidates = [
    "python",
    "python3",
    path.join(process.env.LOCALAPPDATA || "", "Programs", "Python", "Python312", "python.exe"),
    path.join(process.env.LOCALAPPDATA || "", "Programs", "Python", "Python311", "python.exe"),
    "C:\\Python312\\python.exe",
    "C:\\Python311\\python.exe",
  ];
  for (const c of candidates) {
    try {
      execSync(`"${c}" --version`, { stdio: "pipe" });
      return c;
    } catch (_) {}
  }
  return null;
}

function startProxy() {
  if (proxyProcess) return { ok: true, msg: "Already running" };

  const python = findPython();
  if (!python) return { ok: false, msg: "Python not found. Install Python 3.11+." };

  const backend = getBackendPath();
  const proxyScript = path.join(backend, "proxy.py");
  if (!fs.existsSync(proxyScript)) {
    return { ok: false, msg: "proxy.py not found in backend folder." };
  }

  const configPath = getConfigPath();
  const tokensPath = getTokensPath();

  const env = {
    ...process.env,
    OSH_CONFIG_PATH: configPath,
    OSH_TOKENS_PATH: tokensPath,
  };

  proxyProcess = spawn(python, [proxyScript], { env, cwd: backend, stdio: "pipe" });

  proxyProcess.stdout.on("data", (d) => {
    if (mainWindow) mainWindow.webContents.send("proxy-log", d.toString());
  });
  proxyProcess.stderr.on("data", (d) => {
    if (mainWindow) mainWindow.webContents.send("proxy-log", d.toString());
  });
  proxyProcess.on("close", (code) => {
    proxyProcess = null;
    if (mainWindow) mainWindow.webContents.send("proxy-stopped", code);
  });

  return { ok: true, msg: "Proxy starting..." };
}

function stopProxy() {
  if (!proxyProcess) return { ok: false, msg: "Not running" };
  proxyProcess.kill();
  proxyProcess = null;
  return { ok: true, msg: "Stopped" };
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 960,
    height: 680,
    minWidth: 800,
    minHeight: 600,
    frame: false,
    backgroundColor: "#ffffff",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  mainWindow.loadFile("renderer/index.html");
}

app.whenReady().then(() => {
  userDataPath = getDataPath();
  createWindow();
});

app.on("window-all-closed", () => {
  stopProxy();
  app.quit();
});

ipcMain.handle("get-config", () => loadConfig());
ipcMain.handle("save-config", (_, cfg) => {
  saveConfig(cfg);
  return { ok: true };
});
ipcMain.handle("get-tokens", () => loadTokens());
ipcMain.handle("get-proxy-status", () => {
  return { running: proxyProcess !== null };
});
ipcMain.handle("start-proxy", () => startProxy());
ipcMain.handle("stop-proxy", () => stopProxy());
ipcMain.handle("find-python", () => {
  const p = findPython();
  return p ? { found: true, path: p } : { found: false };
});
ipcMain.handle("generate-tokens", async () => {
  const python = findPython();
  if (!python) return { ok: false, msg: "Python not found." };

  const backend = getBackendPath();
  const script = path.join(backend, "token_manager.py");
  const cfg = loadConfig();
  const total = cfg.account_count || 5;

  const env = {
    ...process.env,
    OSH_CONFIG_PATH: getConfigPath(),
    OSH_TOKENS_PATH: getTokensPath(),
  };

  return new Promise((resolve) => {
    const child = spawn(python, [script, "--no-input"], { env, cwd: backend });
    let out = "";
    child.stdout.on("data", (d) => {
      const text = d.toString();
      out += text;
      const match = text.match(/Processing account #(\d+):/);
      if (match) {
        const current = parseInt(match[1]) - (cfg.start_index || 1) + 1;
        if (mainWindow) {
          mainWindow.webContents.send("generate-progress", {
            current: Math.max(1, current),
            total: total,
          });
        }
      }
    });
    child.stderr.on("data", (d) => { out += d.toString(); });
    child.on("close", () => {
      resolve({ ok: true, output: out.slice(-2000) });
    });
    child.on("error", (e) => {
      resolve({ ok: false, msg: e.message });
    });
  });
});
ipcMain.handle("window-minimize", () => mainWindow?.minimize());
ipcMain.handle("window-close", () => app.quit());
ipcMain.handle("setup-opencode", () => {
  const port = loadConfig().proxy_port || 8787;
  const home = process.env.USERPROFILE || "";

  const cfgPath = path.join(home, ".config", "opencode", "opencode.json");
  const cfgDir = path.dirname(cfgPath);
  if (!fs.existsSync(cfgDir)) fs.mkdirSync(cfgDir, { recursive: true });

  const providerConfig = {
    provider: {
      openference: {
        npm: "@ai-sdk/openai-compatible",
        name: "Openference",
        options: {
          baseURL: `http://127.0.0.1:${port}/v1`,
          apiKey: "proxy-handled",
        },
        models: {
          "GLM-5.2": { name: "GLM 5.2" },
        },
      },
    },
  };
  fs.writeFileSync(cfgPath, JSON.stringify(providerConfig, null, 2));

  const authPath = path.join(home, ".local", "share", "opencode", "auth.json");
  const authDir = path.dirname(authPath);
  if (!fs.existsSync(authDir)) fs.mkdirSync(authDir, { recursive: true });

  let authData = {};
  try { authData = JSON.parse(fs.readFileSync(authPath, "utf-8")); } catch (_) {}
  authData.openference = {
    type: "api",
    key: "proxy-handled",
  };
  fs.writeFileSync(authPath, JSON.stringify(authData, null, 2));

  return { ok: true, cfgPath, authPath };
});
ipcMain.handle("setup-claude", () => {
  const port = loadConfig().proxy_port || 8787;
  const home = process.env.USERPROFILE || "";
  const claudeJson = path.join(home, ".claude.json");
  const config = {
    anthropic: {
      baseUrl: `http://127.0.0.1:${port}/v1`,
      apiKey: "proxy-handled",
    },
  };
  fs.writeFileSync(claudeJson, JSON.stringify(config, null, 2));
  const batPath = path.join(home, "Desktop", "Claude_OpenShit.bat");
  const batContent = `@echo off\r\nset ANTHROPIC_BASE_URL=http://127.0.0.1:${port}/v1\r\nset ANTHROPIC_API_KEY=proxy-handled\r\nclaude %*\r\n`;
  fs.writeFileSync(batPath, batContent);
  return { ok: true, claudeJson, batPath };
});
