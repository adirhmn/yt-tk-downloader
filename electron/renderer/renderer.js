const els = {
  pythonCmd: document.getElementById("pythonCmd"),
  channelUrl: document.getElementById("channelUrl"),
  ytCookies: document.getElementById("ytCookies"),
  ytBtnPickCookies: document.getElementById("ytBtnPickCookies"),
  btnLoad: document.getElementById("btnLoad"),
  query: document.getElementById("query"),
  excludeShorts: document.getElementById("excludeShorts"),
  minDuration: document.getElementById("minDuration"),
  maxDuration: document.getElementById("maxDuration"),
  dateFrom: document.getElementById("dateFrom"),
  dateTo: document.getElementById("dateTo"),
  btnPrev: document.getElementById("btnPrev"),
  btnNext: document.getElementById("btnNext"),
  pageJump: document.getElementById("pageJump"),
  btnGo: document.getElementById("btnGo"),
  pageInfo: document.getElementById("pageInfo"),
  btnSelectAll: document.getElementById("btnSelectAll"),
  btnSelectNone: document.getElementById("btnSelectNone"),
  list: document.getElementById("list"),
  outputDir: document.getElementById("outputDir"),
  btnBrowse: document.getElementById("btnBrowse"),
  customLabel: document.getElementById("customLabel"),
  maxParallel: document.getElementById("maxParallel"),
  audioOnly: document.getElementById("audioOnly"),
  subtitles: document.getElementById("subtitles"),
  btnDownloadSelected: document.getElementById("btnDownloadSelected"),
  btnPause: document.getElementById("btnPause"),
  btnContinue: document.getElementById("btnContinue"),
  btnCancel: document.getElementById("btnCancel"),
  status: document.getElementById("status"),
  overallProgress: document.getElementById("overallProgress"),
  itemProgress: document.getElementById("itemProgress"),
  overallText: document.getElementById("overallText"),
  currentText: document.getElementById("currentText"),
  log: document.getElementById("log"),
  downloads: document.getElementById("downloads"),
  btnClearFinished: document.getElementById("btnClearFinished"),
};

let state = {
  page: 1,
  hasMore: false,
  items: [],
  selected: new Set(),
  progressByUrl: new Map(), // url -> number|null
  titleByUrl: new Map(),
  bytesByUrl: new Map(), // url -> { downloaded, total, speed, eta }
  downloadStateByUrl: new Map(), // url -> queued|running|paused|done|error
  sessionActive: false,
  total: 0,
  completed: 0,
};

function appendLog(line) {
  const t = new Date().toLocaleTimeString();
  els.log.value += `[${t}] ${line}\n`;
  els.log.scrollTop = els.log.scrollHeight;
}

function fmtDuration(sec) {
  if (sec == null) return "-";
  const s = Number(sec);
  if (!Number.isFinite(s)) return "-";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const ss = Math.floor(s % 60);
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(ss).padStart(2, "0")}`;
  return `${m}:${String(ss).padStart(2, "0")}`;
}

function fmtBytes(v) {
  const n = Number(v);
  if (!Number.isFinite(n) || n < 0) return "-";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let x = n;
  let i = 0;
  while (x >= 1024 && i < units.length - 1) {
    x /= 1024;
    i += 1;
  }
  const digits = i === 0 ? 0 : i === 1 ? 1 : 2;
  return `${x.toFixed(digits)} ${units[i]}`;
}

function fmtSpeed(v) {
  const n = Number(v);
  if (!Number.isFinite(n) || n <= 0) return "-";
  return `${fmtBytes(n)}/s`;
}

function fmtEta(v) {
  const n = Number(v);
  if (!Number.isFinite(n) || n < 0) return "-";
  const sec = Math.floor(n);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function normalizeDurationInput(value) {
  const v = String(value || "").trim();
  if (!v) return null;
  return v;
}

function renderList() {
  els.list.innerHTML = "";
  els.pageInfo.textContent = `Page ${state.page}`;
  els.btnPrev.disabled = state.page <= 1;
  els.btnNext.disabled = !state.hasMore;

  for (const item of state.items) {
    const url = item.url;
    const checked = state.selected.has(url);
    const pct = state.progressByUrl.has(url) ? state.progressByUrl.get(url) : null;
    const dlState = state.downloadStateByUrl.get(url) || "idle";

    const card = document.createElement("div");
    card.className = "card";

    const img = document.createElement("img");
    img.className = "thumb";
    img.src = item.thumbnail || "";
    img.alt = "thumbnail";

    const meta = document.createElement("div");
    meta.className = "meta";

    const title = document.createElement("div");
    title.className = "title";
    title.textContent = item.title || "(no title)";

    const sub = document.createElement("div");
    sub.className = "sub";
    const stateText =
      dlState && dlState !== "idle" ? ` • ${dlState}` : "";
    sub.textContent = `${fmtDuration(item.duration)} • ${item.upload_date || "-"}${stateText}`;

    const actions = document.createElement("div");
    actions.className = "card-actions";

    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.checked = checked;
    cb.addEventListener("change", () => {
      if (cb.checked) state.selected.add(url);
      else state.selected.delete(url);
    });

    const a = document.createElement("a");
    a.href = url;
    a.textContent = "Open";
    a.target = "_blank";
    a.rel = "noreferrer";
    a.style.color = "#93c5fd";
    a.style.fontSize = "12px";

    const btn = document.createElement("button");
    btn.textContent = "Download";
    btn.addEventListener("click", async () => {
      await addToDownload([url]);
    });

    actions.appendChild(cb);
    actions.appendChild(a);
    actions.appendChild(btn);

    meta.appendChild(title);
    meta.appendChild(sub);
    meta.appendChild(actions);

    card.appendChild(img);
    card.appendChild(meta);

    els.list.appendChild(card);
  }
}

function renderDownloads() {
  els.downloads.innerHTML = "";
  const urls = Array.from(state.downloadStateByUrl.keys());
  // Put running first, then queued/paused, then done/error.
  const rank = (s) => {
    if (s === "running") return 0;
    if (s === "queued") return 1;
    if (s === "paused") return 2;
    if (s === "error") return 3;
    if (s === "done") return 4;
    return 5;
  };
  urls.sort((a, b) => {
    const ra = rank(state.downloadStateByUrl.get(a));
    const rb = rank(state.downloadStateByUrl.get(b));
    if (ra !== rb) return ra - rb;
    return a.localeCompare(b);
  });

  for (const url of urls) {
    const st = state.downloadStateByUrl.get(url) || "idle";
    const pct = state.progressByUrl.has(url) ? state.progressByUrl.get(url) : null;
    const title = state.titleByUrl.get(url) || url;
    const bytes = state.bytesByUrl.get(url) || {};

    const row = document.createElement("div");
    row.className = "dlrow";

    const meta = document.createElement("div");
    meta.className = "dlmeta";

    const name = document.createElement("div");
    name.className = "dlname";
    name.textContent = title;

    const sub = document.createElement("div");
    sub.className = "dlsub";
    sub.textContent = url;

    const prog = document.createElement("progress");
    prog.max = 100;
    if (typeof pct === "number" && Number.isFinite(pct)) {
      prog.value = Math.max(0, Math.min(100, Math.floor(pct)));
    } else {
      prog.removeAttribute("value"); // indeterminate
    }

    meta.appendChild(name);
    meta.appendChild(sub);
    meta.appendChild(prog);

    const right = document.createElement("div");
    right.className = "dlstate";
    const pctText =
      typeof pct === "number" && Number.isFinite(pct) ? `${Math.floor(pct)}%` : "…";
    const dlText = (() => {
      if (!bytes) return "-";
      const downloaded = bytes.downloaded || 0;
      const total = bytes.total || 0;
      const speed = bytes.speed;
      const eta = bytes.eta;
      if (total > 0 && typeof pct === "number" && Number.isFinite(pct)) {
        return `${pct.toFixed(1)}% of ${fmtBytes(total)} at ${fmtSpeed(speed)} ETA ${fmtEta(eta)}`;
      }
      if (downloaded > 0 || total > 0) {
        const totalText = total > 0 ? fmtBytes(total) : "?";
        return `${fmtBytes(downloaded)} / ${totalText} at ${fmtSpeed(speed)} ETA ${fmtEta(eta)}`;
      }
      return "-";
    })();
    right.textContent = `${st} • ${pctText}\n${dlText}`;

    row.appendChild(meta);
    row.appendChild(right);
    els.downloads.appendChild(row);
  }
}

async function loadPage(page) {
  const url = els.channelUrl.value.trim();
  if (!url) return appendLog("URL channel wajib diisi.");

  const params = {
    pythonCmd: els.pythonCmd.value.trim() || "py",
    url,
    page,
    pageSize: 20,
    query: els.query.value.trim() || null,
    excludeShorts: els.excludeShorts.checked,
    minDuration: normalizeDurationInput(els.minDuration.value),
    maxDuration: normalizeDurationInput(els.maxDuration.value),
    dateFrom: els.dateFrom.value.trim() || null,
    dateTo: els.dateTo.value.trim() || null,
    cookies: (els.ytCookies.value || "").trim() || null,
  };

  appendLog(`Loading page ${page}...`);
  const res = await window.api.listVideos(params);
  if (!res.ok) {
    appendLog(res.error || "List error");
    if (res.stderr) appendLog(res.stderr);
    return;
  }

  state.page = page;
  state.items = res.payload.items || [];
  state.hasMore = !!res.payload.has_more;
  // Keep selection if the same URLs appear
  renderList();
}

async function startDownload(urls) {
  const params = {
    pythonCmd: els.pythonCmd.value.trim() || "py",
    urls,
    output: els.outputDir.value.trim() || "downloads",
    audioOnly: els.audioOnly.checked,
    subtitles: els.subtitles.checked,
    maxParallel: Number(els.maxParallel.value || 1),
    custom: (els.customLabel.value || "").trim() || null,
    cookies: (els.ytCookies.value || "").trim() || null,
  };
  const res = await window.api.startDownload(params);
  if (!res.ok) {
    appendLog(res.error || "Start download error");
  }
}

async function addToDownload(urls) {
  // If session not started yet, start it. Otherwise enqueue.
  const baseParams = {
    pythonCmd: els.pythonCmd.value.trim() || "py",
    output: els.outputDir.value.trim() || "downloads",
    audioOnly: els.audioOnly.checked,
    subtitles: els.subtitles.checked,
    maxParallel: Number(els.maxParallel.value || 1),
    custom: (els.customLabel.value || "").trim() || null,
    cookies: (els.ytCookies.value || "").trim() || null,
  };
  if (!state.sessionActive) {
    return await startDownload(urls);
  }
  const res = await window.api.enqueueDownload({ ...baseParams, urls });
  if (!res.ok) appendLog(res.error || "Enqueue error");
}

els.ytBtnPickCookies.addEventListener("click", async () => {
  const file = await window.api.selectCookiesFile();
  if (file) els.ytCookies.value = file;
});

els.btnLoad.addEventListener("click", () => loadPage(1));
els.btnPrev.addEventListener("click", () => loadPage(state.page - 1));
els.btnNext.addEventListener("click", () => loadPage(state.page + 1));
els.btnGo.addEventListener("click", () => {
  const n = Number(els.pageJump.value);
  if (!Number.isFinite(n) || n < 1) return appendLog("Page number harus >= 1");
  loadPage(Math.floor(n));
});
els.pageJump.addEventListener("keydown", (e) => {
  if (e.key === "Enter") els.btnGo.click();
});

els.btnSelectAll.addEventListener("click", () => {
  for (const item of state.items) state.selected.add(item.url);
  renderList();
});
els.btnSelectNone.addEventListener("click", () => {
  for (const item of state.items) state.selected.delete(item.url);
  renderList();
});

els.btnBrowse.addEventListener("click", async () => {
  const dir = await window.api.selectOutputDir();
  if (dir) els.outputDir.value = dir;
});

els.btnDownloadSelected.addEventListener("click", async () => {
  const urls = Array.from(state.selected.values());
  await addToDownload(urls);
});

els.btnPause.addEventListener("click", async () => {
  const res = await window.api.pauseDownload();
  if (!res.ok) appendLog(res.error || "Pause error");
});
els.btnContinue.addEventListener("click", async () => {
  const res = await window.api.continueDownload();
  if (!res.ok) appendLog(res.error || "Continue error");
});
els.btnCancel.addEventListener("click", async () => {
  const res = await window.api.cancelDownload();
  if (!res.ok) appendLog(res.error || "Cancel error");
});

els.btnClearFinished.addEventListener("click", () => {
  for (const [url, st] of state.downloadStateByUrl.entries()) {
    if (st === "done") {
      state.downloadStateByUrl.delete(url);
      state.progressByUrl.delete(url);
      // keep title for convenience
    }
  }
  renderList();
  renderDownloads();
});

window.api.onDownloadEvent((evt) => {
  if (!evt || !evt.type) return;

  if (evt.type === "session_start") {
    state.total = evt.total || 0;
    state.completed = 0;
    state.sessionActive = true;
    els.overallText.textContent = `0/${state.total} (0 running, ${state.total} queued)`;
    els.overallProgress.value = 0;
    els.itemProgress.value = 0;
    els.currentText.textContent = "-";
    appendLog(`Session start (total ${state.total})`);
    return;
  }

  if (evt.type === "item_start") {
    if (evt.url) {
      state.downloadStateByUrl.set(evt.url, "running");
      if (!state.progressByUrl.has(evt.url)) state.progressByUrl.set(evt.url, null);
    }
    renderList();
    renderDownloads();
    return;
  }

  if (evt.type === "session_update") {
    els.status.textContent = evt.status || "unknown";
    const completed = typeof evt.completed === "number" ? evt.completed : state.completed;
    const total = typeof evt.total === "number" ? evt.total : state.total;
    const running = typeof evt.running === "number" ? evt.running : 0;
    const queued = typeof evt.queued === "number" ? evt.queued : 0;
    state.completed = completed;
    state.total = total;
    state.sessionActive = evt.status !== "idle" && evt.status !== "canceled";
    els.overallText.textContent = `${completed}/${total} (${running} running, ${queued} queued)`;
    if (typeof evt.overallPercent === "number") {
      els.overallProgress.value = Math.max(0, Math.min(100, Math.floor(evt.overallPercent)));
    }
    return;
  }

  if (evt.type === "progress") {
    const percent = evt.percent;
    if (typeof percent === "number" && Number.isFinite(percent)) {
      els.itemProgress.value = Math.max(0, Math.min(100, Math.floor(percent)));
      if (evt.url) state.progressByUrl.set(evt.url, percent);
    } else {
      // No percent available (common for some fragment streams); show indeterminate UI.
      els.itemProgress.removeAttribute("value");
      if (evt.url) state.progressByUrl.set(evt.url, null);
    }
    if (evt.url) {
      state.bytesByUrl.set(evt.url, {
        downloaded: evt.downloaded_bytes,
        total: evt.total_bytes,
        speed: evt.speed,
        eta: evt.eta,
      });
    }
    if (typeof evt.overallPercent === "number") {
      els.overallProgress.value = Math.max(0, Math.min(100, Math.floor(evt.overallPercent)));
    }
    if (evt.title) {
      els.currentText.textContent = evt.title;
      if (evt.url) state.titleByUrl.set(evt.url, evt.title);
    } else if (evt.url) {
      els.currentText.textContent = evt.url;
    }
    if (evt.url) state.downloadStateByUrl.set(evt.url, "running");
    renderList();
    renderDownloads();
    return;
  }

  if (evt.type === "finished") {
    appendLog(`Finished: ${evt.title || evt.id || ""}`);
    return;
  }

  if (evt.type === "item_done") {
    if (evt.url) state.progressByUrl.set(evt.url, 100);
    if (evt.url) state.downloadStateByUrl.set(evt.url, "done");
    if (evt.url) {
      const prev = state.bytesByUrl.get(evt.url) || {};
      state.bytesByUrl.set(evt.url, { ...prev, downloaded: prev.total || prev.downloaded, total: prev.total || null });
    }
    els.itemProgress.value = 0;
    appendLog(`Done (${state.completed}/${state.total})`);
    renderList();
    renderDownloads();
    return;
  }

  if (evt.type === "error") {
    appendLog(evt.message || "Error");
    if (evt.url) state.downloadStateByUrl.set(evt.url, "error");
    renderList();
    renderDownloads();
    return;
  }

  if (evt.type === "log") {
    if (evt.message) appendLog(evt.message);
    return;
  }

  if (evt.type === "session_end") {
    appendLog("Session end");
    els.status.textContent = "idle";
    state.sessionActive = false;
    renderDownloads();
    return;
  }
});
