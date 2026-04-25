const { app, BrowserWindow, ipcMain, dialog, shell } = require("electron");
const path = require("path");
const { spawn } = require("child_process");

let mainWindow = null;

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1100,
    height: 800,
    webPreferences: {
      contextIsolation: true,
      nodeIntegration: false,
      preload: path.join(__dirname, "preload.cjs"),
    },
  });

  mainWindow.loadFile(path.join(__dirname, "renderer", "index.html"));

  // Open external links in default browser (avoid navigating the app window).
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    try {
      shell.openExternal(url);
    } catch {
      // ignore
    }
    return { action: "deny" };
  });
  mainWindow.webContents.on("will-navigate", (e, url) => {
    if (url && !url.startsWith("file:")) {
      e.preventDefault();
      try {
        shell.openExternal(url);
      } catch {
        // ignore
      }
    }
  });
}

app.whenReady().then(() => {
  createWindow();
  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") app.quit();
});

function getBackendScriptPath() {
  return path.join(app.getAppPath(), "yt_app.py");
}

function spawnPython(pythonCmd, scriptArgs, opts = {}) {
  const scriptPath = getBackendScriptPath();
  const baseArgs = ["-u", scriptPath, ...scriptArgs];
  const child = spawn(pythonCmd, baseArgs, {
    windowsHide: true,
    cwd: app.getAppPath(),
    ...opts,
  });
  return child;
}

function readLines(stream, onLine) {
  let buffer = "";
  stream.setEncoding("utf8");
  stream.on("data", (chunk) => {
    buffer += chunk;
    while (true) {
      const idx = buffer.indexOf("\n");
      if (idx === -1) break;
      const line = buffer.slice(0, idx).trim();
      buffer = buffer.slice(idx + 1);
      if (line) onLine(line);
    }
  });
}

ipcMain.handle("select-output-dir", async () => {
  const result = await dialog.showOpenDialog({
    properties: ["openDirectory", "createDirectory"],
  });
  if (result.canceled) return null;
  return result.filePaths[0] || null;
});

ipcMain.handle("select-cookies-file", async () => {
  const result = await dialog.showOpenDialog({
    properties: ["openFile"],
    filters: [{ name: "Cookies", extensions: ["txt"] }],
  });
  if (result.canceled) return null;
  return result.filePaths[0] || null;
});

ipcMain.handle("list-videos", async (event, params) => {
  const pythonCmd = params?.pythonCmd || "py";
  const args = ["list", params.url, "--page", String(params.page || 1), "--page-size", String(params.pageSize || 20)];

  if (params.query) args.push("--query", String(params.query));
  if (params.excludeShorts) args.push("--exclude-shorts");
  if (params.minDuration) args.push("--min-duration", String(params.minDuration));
  if (params.maxDuration) args.push("--max-duration", String(params.maxDuration));
  if (params.dateFrom) args.push("--date-from", String(params.dateFrom));
  if (params.dateTo) args.push("--date-to", String(params.dateTo));
  if (params.cookies) args.push("--cookies", String(params.cookies));

  return await new Promise((resolve) => {
    const child = spawnPython(pythonCmd, args);
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (d) => (stdout += d));
    child.stderr.on("data", (d) => (stderr += d));
    child.on("close", () => {
      try {
        const payload = JSON.parse(stdout.trim());
        resolve({ ok: true, payload, stderr });
      } catch (e) {
        resolve({ ok: false, error: "Gagal parse output JSON dari backend.", stdout, stderr });
      }
    });
  });
});

const downloadSession = {
  active: false,
  pythonCmd: "py",
  queue: [],
  maxParallel: 1,
  total: 0,
  completed: 0,
  output: "downloads",
  audioOnly: false,
  subtitles: false,
  custom: null,
  cookies: null,
  paused: false,
  canceled: false,
  running: new Map(), // url -> { child, percent, title }
};

function sendToRenderer(channel, payload) {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  mainWindow.webContents.send(channel, payload);
}

function stopChild() {
  for (const { child } of downloadSession.running.values()) {
    try {
      child.kill();
    } catch {
      // ignore
    }
  }
}

function computeOverallPercent() {
  const total = downloadSession.total || 0;
  if (total <= 0) return 0;
  const completed = downloadSession.completed || 0;
  let inFlight = 0;
  for (const v of downloadSession.running.values()) {
    const p = typeof v.percent === "number" ? v.percent : 0;
    inFlight += Math.max(0, Math.min(100, p)) / 100;
  }
  const overall = (completed + inFlight) / total;
  return Math.max(0, Math.min(1, overall)) * 100;
}

function sendSessionUpdate() {
  sendToRenderer("download-event", {
    type: "session_update",
    status: downloadSession.canceled
      ? "canceled"
      : downloadSession.paused
        ? "paused"
        : downloadSession.active
          ? "downloading"
          : "idle",
    completed: downloadSession.completed,
    total: downloadSession.total,
    running: downloadSession.running.size,
    queued: downloadSession.queue.length,
    overallPercent: computeOverallPercent(),
  });
}

function ensureQueued(urls) {
  const set = new Set(downloadSession.queue);
  for (const url of urls) {
    if (!url) continue;
    if (set.has(url)) continue;
    if (downloadSession.running.has(url)) continue;
    set.add(url);
    downloadSession.queue.push(url);
    downloadSession.total += 1;
  }
}

function startMoreDownloads() {
  if (!downloadSession.active) return;
  if (downloadSession.paused || downloadSession.canceled) return;

  while (
    downloadSession.running.size < downloadSession.maxParallel &&
    downloadSession.queue.length > 0
  ) {
    const nextUrl = downloadSession.queue.shift();
    if (!nextUrl) continue;
    if (downloadSession.running.has(nextUrl)) continue;
    startOneDownload(nextUrl);
  }

  if (downloadSession.running.size === 0 && downloadSession.queue.length === 0) {
    downloadSession.active = false;
    sendToRenderer("download-event", { type: "session_end", code: 0 });
  } else {
    sendSessionUpdate();
  }
}

function startOneDownload(url) {
  const args = ["download", url, "--json-progress", "-o", downloadSession.output];
  if (downloadSession.audioOnly) args.push("--audio-only");
  if (downloadSession.subtitles) args.push("--subtitles");
  if (downloadSession.custom) args.push("--custom", String(downloadSession.custom));
  if (downloadSession.cookies) args.push("--cookies", String(downloadSession.cookies));

  const child = spawnPython(downloadSession.pythonCmd, args);
  downloadSession.running.set(url, { child, percent: 0, title: null });

  sendToRenderer("download-event", { type: "item_start", url });
  sendSessionUpdate();

  readLines(child.stdout, (line) => {
    let evt = null;
    try {
      evt = JSON.parse(line);
    } catch {
      evt = { type: "log", message: line };
    }
    evt.url = url;
    if (evt.type === "progress") {
      const p = typeof evt.percent === "number" ? evt.percent : null;
      const title = evt.title || null;
      const r = downloadSession.running.get(url);
      if (r) {
        if (typeof p === "number" && Number.isFinite(p)) r.percent = p;
        if (title) r.title = title;
      }
      evt.overallPercent = computeOverallPercent();
    }
    sendToRenderer("download-event", evt);
  });

  child.stderr.setEncoding("utf8");
  child.stderr.on("data", (d) => {
    const msg = String(d).trim();
    if (msg) sendToRenderer("download-event", { type: "log", message: msg, url });
  });

  child.on("close", (code) => {
    downloadSession.running.delete(url);

    if (downloadSession.canceled) {
      if (downloadSession.running.size === 0) {
        downloadSession.active = false;
        sendSessionUpdate();
      }
      return;
    }

    if (downloadSession.paused) {
      // When paused, we keep remaining items queued; any in-flight item should be resumable via .part
      // Re-queue the current URL if it isn't completed.
      if (!downloadSession.queue.includes(url)) downloadSession.queue.unshift(url);
      sendSessionUpdate();
      return;
    }

    if (code === 0) {
      downloadSession.completed += 1;
      sendToRenderer("download-event", { type: "item_done", url });
      sendSessionUpdate();
      startMoreDownloads();
      return;
    }

    // Non-zero code: pause and re-queue for retry/resume.
    downloadSession.queue.unshift(url);
    downloadSession.paused = true;
    sendToRenderer("download-event", {
      type: "error",
      message: `Download gagal untuk 1 item (exit code ${code}). Klik Continue untuk lanjut/resume.`,
      url,
    });
    sendSessionUpdate();
  });
}

ipcMain.handle("start-download", async (event, params) => {
  if (downloadSession.active) {
    return { ok: false, error: "Masih ada download session yang berjalan. Gunakan enqueue untuk menambah item." };
  }
  const urls = Array.isArray(params.urls) ? params.urls.filter(Boolean) : [];
  if (urls.length === 0) return { ok: false, error: "Tidak ada URL yang dipilih." };

  downloadSession.active = true;
  downloadSession.pythonCmd = params.pythonCmd || "py";
  downloadSession.queue = urls.slice();
  downloadSession.maxParallel = Math.max(1, Number(params.maxParallel || 1));
  downloadSession.total = urls.length;
  downloadSession.completed = 0;
  downloadSession.output = params.output || "downloads";
  downloadSession.audioOnly = !!params.audioOnly;
  downloadSession.subtitles = !!params.subtitles;
  downloadSession.custom = (params.custom || "").trim() || null;
  downloadSession.cookies = (params.cookies || "").trim() || null;
  downloadSession.paused = false;
  downloadSession.canceled = false;
  downloadSession.running = new Map();

  sendToRenderer("download-event", { type: "session_start", total: downloadSession.total });
  sendSessionUpdate();
  startMoreDownloads();
  return { ok: true };
});

ipcMain.handle("enqueue-download", async (event, params) => {
  if (!downloadSession.active) {
    return { ok: false, error: "Tidak ada session aktif. Klik Download selected dulu." };
  }
  const urls = Array.isArray(params.urls) ? params.urls.filter(Boolean) : [];
  if (urls.length === 0) return { ok: false, error: "Tidak ada URL yang ditambahkan." };
  ensureQueued(urls);
  if (typeof params.maxParallel === "number" && params.maxParallel >= 1) {
    downloadSession.maxParallel = Math.max(1, Number(params.maxParallel));
  }
  if (typeof params.custom === "string") {
    downloadSession.custom = params.custom.trim() || null;
  }
  if (typeof params.cookies === "string") {
    downloadSession.cookies = params.cookies.trim() || null;
  }
  if (!downloadSession.paused && !downloadSession.canceled) startMoreDownloads();
  sendSessionUpdate();
  return { ok: true };
});

ipcMain.handle("pause-download", async () => {
  if (!downloadSession.active) return { ok: false, error: "Tidak ada session aktif." };
  if (downloadSession.paused) return { ok: true };
  downloadSession.paused = true;
  // Put in-flight back to queue so it can resume later.
  const inflight = Array.from(downloadSession.running.keys());
  for (const u of inflight.reverse()) {
    if (!downloadSession.queue.includes(u)) downloadSession.queue.unshift(u);
  }
  stopChild();
  sendSessionUpdate();
  return { ok: true };
});

ipcMain.handle("continue-download", async () => {
  if (!downloadSession.active) return { ok: false, error: "Tidak ada session aktif." };
  if (!downloadSession.paused) return { ok: true };
  downloadSession.paused = false;
  sendSessionUpdate();
  startMoreDownloads();
  return { ok: true };
});

ipcMain.handle("cancel-download", async () => {
  if (!downloadSession.active) return { ok: false, error: "Tidak ada session aktif." };
  downloadSession.canceled = true;
  downloadSession.queue = [];
  stopChild();
  sendSessionUpdate();
  return { ok: true };
});
