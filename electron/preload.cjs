const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("api", {
  selectOutputDir: () => ipcRenderer.invoke("select-output-dir"),
  selectCookiesFile: () => ipcRenderer.invoke("select-cookies-file"),
  listVideos: (params) => ipcRenderer.invoke("list-videos", params),

  startDownload: (params) => ipcRenderer.invoke("start-download", params),
  enqueueDownload: (params) => ipcRenderer.invoke("enqueue-download", params),
  pauseDownload: () => ipcRenderer.invoke("pause-download"),
  continueDownload: () => ipcRenderer.invoke("continue-download"),
  cancelDownload: () => ipcRenderer.invoke("cancel-download"),

  onDownloadEvent: (callback) => {
    ipcRenderer.on("download-event", (_event, payload) => callback(payload));
  },
});
