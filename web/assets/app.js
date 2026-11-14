const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => Array.from(document.querySelectorAll(selector));

let currentVideo = null;
let currentInput = "";
let pollTimer = null;
let taskTimer = null;
let toastTimer = null;
let lastTasks = [];

function escapeHtml(value) {
  return String(value == null ? "" : value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[char]);
}

function formatNumber(value) {
  const number = Number(value || 0);
  if (number >= 100000000) return (number / 100000000).toFixed(1) + "亿";
  if (number >= 10000) return (number / 10000).toFixed(1) + "万";
  return number.toLocaleString("zh-CN");
}

function formatDuration(seconds) {
  const value = Math.max(0, Number(seconds || 0));
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const secs = Math.floor(value % 60);
  return hours ? [hours, minutes, secs].map((n) => String(n).padStart(2, "0")).join(":")
    : [minutes, secs].map((n) => String(n).padStart(2, "0")).join(":");
}

function formatSize(bytes) {
  let value = Number(bytes || 0);
  for (const unit of ["B", "KB", "MB", "GB"]) {
    if (value < 1024 || unit === "GB") {
      return (unit === "B" ? Math.round(value) : value.toFixed(1)) + " " + unit;
    }
    value /= 1024;
  }
  return value.toFixed(1) + " GB";
}

function showToast(message) {
  const element = $("#toast");
  element.textContent = message;
  element.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => element.classList.remove("show"), 2600);
}

async function api(path, options) {
  const response = await fetch(path, Object.assign({
    headers: { "Content-Type": "application/json" },
    cache: "no-store"
  }, options || {}));
  let data;
  try { data = await response.json(); }
  catch (_) { throw new Error("服务器响应格式异常"); }
  if (!response.ok || data.ok === false) {
    throw new Error(data.error || "请求失败（HTTP " + response.status + "）");
  }
  return data;
}

function switchView(name) {
  $$(".view").forEach((view) => view.classList.toggle("active", view.id === "view-" + name));
  $$(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === name));
  if (name === "tasks") refreshTasks();
  if (name === "history") refreshHistory();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

$$("[data-view]").forEach((button) => button.addEventListener("click", () => switchView(button.dataset.view)));

function renderVideo(data) {
  currentVideo = data.video;
  const video = data.video;
  $("#resultSection").classList.remove("hidden");
  $("#coverImage").src = video.cover || "";
  $("#coverImage").alt = video.title || "视频封面";
  $("#videoDuration").textContent = formatDuration(video.duration);
  $("#videoTitle").textContent = video.title || "未命名视频";
  $("#videoOwner").textContent = "UP主 " + (video.owner || "未知");
  $("#videoViews").textContent = "播放 " + formatNumber((video.stat || {}).view);
  $("#videoLikes").textContent = "点赞 " + formatNumber((video.stat || {}).like);
  $("#videoDescription").textContent = video.description || "暂无简介";
  $("#videoIdLabel").textContent = video.bvid || ("av" + video.aid);

  const partSelect = $("#partSelect");
  const previousCid = Number(partSelect.value || 0);
  partSelect.innerHTML = "";
  (video.pages || []).forEach((page) => {
    const option = document.createElement("option");
    option.value = page.cid;
    option.textContent = "P" + page.page + " · " + page.part + "（" + formatDuration(page.duration) + "）";
    partSelect.appendChild(option);
  });
  if (Array.from(partSelect.options).some((option) => Number(option.value) === previousCid)) {
    partSelect.value = String(previousCid);
  } else if (video.pages && video.pages.length) {
    partSelect.value = String(video.pages[0].cid);
  }

  const qualitySelect = $("#qualitySelect");
  qualitySelect.innerHTML = "";
  const qualities = data.qualities || [];
  qualities.forEach((quality) => {
    const option = document.createElement("option");
    option.value = quality.id;
    option.textContent = quality.label;
    qualitySelect.appendChild(option);
  });
  const preferred = Number(data.current_quality || 0);
  if (preferred && Array.from(qualitySelect.options).some((option) => Number(option.value) === preferred)) {
    qualitySelect.value = String(preferred);
  }
  qualitySelect.disabled = qualities.length === 0;
  $("#downloadButton").disabled = qualities.length === 0;
  const qualityError = $("#qualityError");
  if (data.quality_error) {
    qualityError.textContent = data.quality_error + (data.login && !data.login.logged_in ? "。可尝试扫码授权后重新解析。" : "");
    qualityError.classList.remove("hidden");
  } else if (!qualities.length) {
    qualityError.textContent = "接口没有返回可用画质，请确认视频可播放后重试。";
    qualityError.classList.remove("hidden");
  } else {
    qualityError.textContent = "";
    qualityError.classList.add("hidden");
  }
  $("#parseError").classList.add("hidden");
}

async function parseVideo(event) {
  if (event) event.preventDefault();
  const raw = $("#videoInput").value.trim();
  if (!raw) {
    showToast("先粘贴 B站视频链接或 BV / AV 号");
    $("#videoInput").focus();
    return;
  }
  currentInput = raw;
  const button = $("#parseButton");
  const errorLine = $("#parseError");
  button.disabled = true;
  button.querySelector("span").textContent = "正在解析…";
  errorLine.classList.add("hidden");
  try {
    const payload = { input: raw };
    if ($("#partSelect").value) payload.cid = Number($("#partSelect").value);
    const result = await api("/api/parse", {
      method: "POST", body: JSON.stringify(payload)
    });
    renderVideo(result);
    $("#resultSection").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    errorLine.textContent = error.message;
    errorLine.classList.remove("hidden");
    $("#resultSection").classList.add("hidden");
  } finally {
    button.disabled = false;
    button.querySelector("span").textContent = "解析视频";
  }
}

$("#parseForm").addEventListener("submit", parseVideo);
$("#videoInput").addEventListener("input", () => {
  $("#clearInput").classList.toggle("visible", !!$("#videoInput").value);
});
$("#clearInput").addEventListener("click", () => {
  $("#videoInput").value = "";
  $("#clearInput").classList.remove("visible");
  $("#videoInput").focus();
});
$("#partSelect").addEventListener("change", () => {
  if (currentVideo) parseVideo();
});

$("#downloadButton").addEventListener("click", async () => {
  const qn = Number($("#qualitySelect").value || 0);
  const cid = Number($("#partSelect").value || 0);
  if (!currentVideo || !qn || !cid) return;
  const button = $("#downloadButton");
  button.disabled = true;
  button.querySelectorAll("span")[1].textContent = "正在创建任务…";
  try {
    const result = await api("/api/download", {
      method: "POST",
      body: JSON.stringify({
        input: currentInput,
        cid,
        qn,
        title: currentVideo.title
      })
    });
    showToast("已加入下载任务");
    $("#taskPreview").classList.remove("hidden");
    switchView("tasks");
    await refreshTasks();
  } catch (error) {
    showToast(error.message);
  } finally {
    button.disabled = false;
    button.querySelectorAll("span")[1].textContent = "下载视频";
  }
});

function taskStatusText(task) {
  if (task.status === "queued") return "排队中";
  if (task.status === "downloading") return task.phase || "下载中";
  if (task.status === "merging") return task.phase || "封装中";
  if (task.status === "completed") return "已完成";
  if (task.status === "failed") return "失败";
  return task.phase || "处理中";
}

function taskCard(task) {
  const state = escapeHtml(task.status);
  const progress = Math.max(0, Math.min(100, Number(task.progress || 0)));
  const detail = task.error
    ? '<div class="task-error">' + escapeHtml(task.error) + '</div>'
    : "";
  const action = task.status === "completed" && task.filename
    ? '<div class="task-actions"><a class="download-link" href="/api/files/' + encodeURIComponent(task.filename) + '">保存文件 ↓</a></div>'
    : "";
  return '<article class="task-card">' +
    '<div class="task-top"><div class="task-file-icon">↓</div><div class="task-info"><strong>' +
    escapeHtml(task.title) + '</strong><small>' + escapeHtml(task.detail || task.phase || "") +
    '</small></div><span class="task-state ' + state + '">' + escapeHtml(taskStatusText(task)) + '</span></div>' +
    '<div class="task-progress-row"><span>' + escapeHtml(task.phase || "等待中") +
    '</span><b>' + progress + '%</b></div><div class="progress-track"><div class="progress-fill" style="width:' +
    progress + '%"></div></div>' + detail + action + '</article>';
}

async function refreshTasks() {
  try {
    const result = await api("/api/tasks");
    lastTasks = result.tasks || [];
    $("#taskCount").textContent = String(lastTasks.filter((task) => !["completed", "failed"].includes(task.status)).length);
    const list = $("#taskList");
    if (!lastTasks.length) {
      list.innerHTML = '<div class="empty-state"><span>↓</span><strong>还没有下载任务</strong><p>解析视频并点击下载后，任务会显示在这里。</p></div>';
      $("#taskPreview").classList.add("hidden");
      return;
    }
    list.innerHTML = lastTasks.map(taskCard).join("");
    const preview = $("#recentTask");
    preview.innerHTML = taskCard(lastTasks[0]);
    $("#taskPreview").classList.remove("hidden");
  } catch (error) {
    console.warn("refresh tasks:", error);
  }
}

$("#refreshTasks").addEventListener("click", refreshTasks);

async function refreshHistory() {
  try {
    const result = await api("/api/history");
    const entries = result.history || [];
    const list = $("#historyList");
    if (!entries.length) {
      list.innerHTML = '<div class="empty-state"><span>◷</span><strong>暂无下载记录</strong><p>完成的视频会自动出现在这里。</p></div>';
      return;
    }
    list.innerHTML = entries.map((item) => {
      const date = new Date(Number(item.created_at || 0) * 1000);
      const dateText = isNaN(date.getTime()) ? "" : date.toLocaleString("zh-CN");
      return '<article class="history-card"><div class="task-file-icon">✓</div><div class="history-info"><strong>' +
        escapeHtml(item.title) + '</strong><small>' + escapeHtml(dateText) +
        '</small></div><span class="history-size">' + formatSize(item.size) + '</span><a class="download-link" href="/api/files/' +
        encodeURIComponent(item.filename) + '">下载</a></article>';
    }).join("");
  } catch (error) {
    console.warn("refresh history:", error);
  }
}

async function refreshHealth() {
  try {
    const data = await api("/api/health");
    $("#connectionState").innerHTML = '<i></i> 本机服务';
    if (!data.ffmpeg) {
      $("#connectionState").title = "未检测到 FFmpeg，DASH 合并不可用";
      $("#connectionState").style.color = "#bd5a70";
    }
    updateLoginLabel(data.login || {});
  } catch (_) {
    $("#connectionState").textContent = "服务未连接";
    $("#connectionState").style.color = "#bd5a70";
  }
}

function updateLoginLabel(login) {
  if (login.logged_in) {
    $("#loginLabel").textContent = login.username ? login.username : "已登录";
    $("#loginOpen").classList.add("logged-in");
    $("#loginOpen").title = "点击查看登录状态或退出";
  } else {
    $("#loginLabel").textContent = "扫码登录";
    $("#loginOpen").classList.remove("logged-in");
    $("#loginOpen").title = "使用 B站 APP 扫码登录";
  }
}

function closeLoginModal() {
  $("#loginModal").classList.add("hidden");
  stopQrPolling();
}

function stopQrPolling() {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
}

async function startQr() {
  stopQrPolling();
  $("#qrFrame").innerHTML = '<div class="qr-placeholder"><span class="spinner"></span><small>正在生成二维码…</small></div>';
  $("#qrState").textContent = "请稍候，正在连接 B站";
  try {
    const data = await api("/api/login/qrcode");
    $("#qrFrame").innerHTML = '<img src="' + data.image + '" alt="B站扫码登录二维码">';
    $("#qrState").textContent = "请使用 B站手机 APP 扫描";
    pollTimer = setInterval(() => pollQr(data.key), 2000);
  } catch (error) {
    $("#qrState").textContent = error.message;
    showToast(error.message);
  }
}

async function pollQr(key) {
  try {
    const result = await api("/api/login/poll?key=" + encodeURIComponent(key));
    $("#qrState").textContent = result.message || "等待扫码确认";
    if (result.state === "success") {
      stopQrPolling();
      updateLoginLabel({ logged_in: true, username: result.username });
      showToast("B站账号登录成功");
      setTimeout(closeLoginModal, 700);
      if (currentInput) parseVideo();
    } else if (result.state === "expired") {
      stopQrPolling();
      $("#qrState").textContent = "二维码已过期，请点击刷新二维码";
    }
  } catch (error) {
    $("#qrState").textContent = error.message;
    stopQrPolling();
  }
}

$("#loginOpen").addEventListener("click", async () => {
  $("#loginModal").classList.remove("hidden");
  const logged = $("#loginOpen").classList.contains("logged-in");
  if (logged) {
    $("#qrFrame").innerHTML = '<div class="qr-placeholder"><span style="font-size:26px;color:#35aa80">✓</span><small>当前设备已授权登录</small></div>';
    $("#qrState").textContent = "已登录 " + $("#loginLabel").textContent;
    $("#qrRefresh").textContent = "退出登录";
  } else {
    $("#qrRefresh").textContent = "刷新二维码";
    await startQr();
  }
});
$("#loginClose").addEventListener("click", closeLoginModal);
$("#qrRefresh").addEventListener("click", async () => {
  if ($("#qrRefresh").textContent === "退出登录") {
    try {
      await api("/api/login/logout", { method: "POST", body: "{}" });
      updateLoginLabel({ logged_in: false });
      $("#qrRefresh").textContent = "刷新二维码";
      await startQr();
      showToast("已退出登录");
    } catch (error) { showToast(error.message); }
  } else {
    await startQr();
  }
});
$("#loginModal").addEventListener("click", (event) => {
  if (event.target === $("#loginModal")) closeLoginModal();
});

refreshHealth();
refreshTasks();
refreshHistory();
taskTimer = setInterval(() => {
  refreshTasks();
  if ($("#view-history").classList.contains("active")) refreshHistory();
}, 2600);
window.addEventListener("beforeunload", () => {
  stopQrPolling();
  if (taskTimer) clearInterval(taskTimer);
});
