"use strict";

const $ = (id) => document.getElementById(id);

async function api(path, data) {
  const opts = { method: "POST" };
  if (data) {
    const body = new URLSearchParams();
    Object.entries(data).forEach(([k, v]) => body.append(k, v));
    opts.body = body;
  }
  const res = await fetch(path, opts);
  let json = {};
  try { json = await res.json(); } catch (e) { /* ignore */ }
  if (!res.ok && json.detail) json.error = json.detail;
  return { ok: res.ok && json.ok !== false, json };
}

async function getJSON(path) {
  const res = await fetch(path);
  return res.json();
}

// ----------------------------------------------------------------- tabs
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".tabpane").forEach((p) => p.classList.remove("active"));
    tab.classList.add("active");
    $("tab-" + tab.dataset.tab).classList.add("active");
  });
});

// ----------------------------------------------------------------- config
async function refreshConfig() {
  const cfg = await getJSON("/api/config");
  $("api_id").value = cfg.telegram.api_id || "";
  $("api_hash_hint").textContent = cfg.telegram.has_api_hash
    ? "Đã lưu: " + cfg.telegram.api_hash_masked : "Chưa có api_hash";
  $("notify_hint").textContent = cfg.bot.has_notify_token
    ? "Đã lưu: " + cfg.bot.notify_token_masked : "Chưa có token";

  const ls = $("login_state");
  if (cfg.telegram.logged_in_user) {
    ls.textContent = "Đã đăng nhập: " + cfg.telegram.logged_in_user;
    ls.className = "badge online";
  } else {
    ls.textContent = "Chưa đăng nhập Telegram";
    ls.className = "badge warning";
  }
}

$("save_tg").addEventListener("click", async () => {
  const { ok, json } = await api("/api/config/telegram", {
    api_id: $("api_id").value, api_hash: $("api_hash").value,
  });
  if (!ok) return alert(json.error || "Lỗi lưu");
  $("api_hash").value = "";
  refreshConfig();
});

$("save_bot").addEventListener("click", async () => {
  const { ok, json } = await api("/api/config/bot", { notify_token: $("notify_token").value });
  if (!ok) return alert(json.error || "Lỗi lưu");
  $("notify_token").value = "";
  refreshConfig();
});

// -------------------------------------------------------- telegram login
$("send_code").addEventListener("click", async () => {
  const { ok, json } = await api("/api/telegram/send_code", { phone: $("phone").value });
  if (!ok) return alert(json.error || "Lỗi gửi mã");
  $("code_box").classList.remove("hidden");
});

$("sign_in").addEventListener("click", async () => {
  const { ok, json } = await api("/api/telegram/sign_in", { code: $("code").value });
  if (!ok) return alert(json.error || "Lỗi đăng nhập");
  if (json.need_password) {
    $("pwd_box").classList.remove("hidden");
    return;
  }
  finishLogin(json);
});

$("check_pwd").addEventListener("click", async () => {
  const { ok, json } = await api("/api/telegram/password", { password: $("tfa").value });
  if (!ok) return alert(json.error || "Lỗi 2FA");
  finishLogin(json);
});

function finishLogin(json) {
  $("code_box").classList.add("hidden");
  $("pwd_box").classList.add("hidden");
  refreshConfig();
  refreshStatus();
  alert("Đăng nhập Telegram thành công: " + (json.username || ""));
}

// ------------------------------------------------------------- userbot
function applyStatus(s) {
  const txt = s.status || "stopped";
  const badge = $("ub_status");
  const pill = $("ub-pill");
  badge.textContent = txt;
  badge.className = "badge " + (txt === "online" ? "online" : txt === "error" ? "error" : "");
  pill.textContent = "● userbot: " + txt;
  pill.className = "pill " + (txt === "online" ? "online" : txt === "error" ? "error" : "stopped");
  $("ub_user").textContent = s.username ? ("@" + s.username) : (s.error ? ("Lỗi: " + s.error) : "");
}

async function refreshStatus() {
  applyStatus(await getJSON("/api/userbot/status"));
}

$("btn_start").addEventListener("click", async () => {
  const { ok, json } = await api("/api/userbot/start");
  if (!ok) return alert(json.error || "Không start được");
  applyStatus(json);
});

$("btn_stop").addEventListener("click", async () => {
  const { json } = await api("/api/userbot/stop");
  applyStatus(json);
});

$("btn_logout_tg").addEventListener("click", async () => {
  if (!confirm("Đăng xuất Telegram và xoá session?")) return;
  const { json } = await api("/api/userbot/logout");
  applyStatus(json);
  refreshConfig();
});

// ----------------------------------------------------------------- logs (SSE)
function addLog(rec) {
  const view = $("log_view");
  const line = document.createElement("div");
  line.className = "log-line level-" + (rec.level || "info");
  line.innerHTML = `<span class="ts">[${rec.ts}]</span> ` +
    `<span class="src">${rec.source}</span> ${escapeHtml(rec.message)}`;
  view.appendChild(line);
  view.scrollTop = view.scrollHeight;
}

function escapeHtml(s) {
  return String(s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));
}

function startSSE() {
  const es = new EventSource("/api/logs/stream");
  es.onmessage = (e) => { try { addLog(JSON.parse(e.data)); } catch (_) {} };
  es.onerror = () => {
    $("sse_dot").className = "pill error";
    $("sse_dot").textContent = "● reconnecting";
  };
  es.onopen = () => {
    $("sse_dot").className = "pill online";
    $("sse_dot").textContent = "● live";
  };
}

// ----------------------------------------------------------------- boot
refreshConfig();
refreshStatus();
startSSE();
setInterval(refreshStatus, 5000);
