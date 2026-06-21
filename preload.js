const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("api", {
  getConfig: () => ipcRenderer.invoke("get-config"),
  saveConfig: (cfg) => ipcRenderer.invoke("save-config", cfg),
  getTokens: () => ipcRenderer.invoke("get-tokens"),
  getProxyStatus: () => ipcRenderer.invoke("get-proxy-status"),
  startProxy: () => ipcRenderer.invoke("start-proxy"),
  stopProxy: () => ipcRenderer.invoke("stop-proxy"),
  findPython: () => ipcRenderer.invoke("find-python"),
  generateTokens: () => ipcRenderer.invoke("generate-tokens"),
  windowMinimize: () => ipcRenderer.invoke("window-minimize"),
  windowClose: () => ipcRenderer.invoke("window-close"),
  onProxyLog: (cb) => ipcRenderer.on("proxy-log", (_, d) => cb(d)),
  onProxyStopped: (cb) => ipcRenderer.on("proxy-stopped", (_, code) => cb(code)),
  onGenerateProgress: (cb) => ipcRenderer.on("generate-progress", (_, d) => cb(d)),
  setupOpenCode: () => ipcRenderer.invoke("setup-opencode"),
  setupClaude: () => ipcRenderer.invoke("setup-claude"),
});
