"use strict";
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

async function api(path, data) {
  const opts = { method: "POST" };
  if (data) {
    const body = new URLSearchParams();
    Object.entries(data).forEach(([k, v]) => body.append(k, v));
    opts.body = body;
  }
  const res = await fetch(path, opts);
  let json = {};
  try { json = await res.json(); } catch (e) {}
  if (!res.ok && json.detail) json.error = json.detail;
  return { ok: res.ok && json.ok !== false, json };
}
const getJSON = (p) => fetch(p).then((r) => r.json());

const TITLES = {
  overview: "Tổng quan", telegram: "Telegram", userbot: "Userbot", platform: "Platform",
  archive: "Kho lưu trữ", bots: "Bots (tối đa 10)", users: "Users", vip: "VIP & Stars",
  gift: "Giftcode", ads: "Ads", share: "Share", backup: "Backup", rollup: "Rollup", logs: "Logs",
};

// --------------------------------------------------------- navigation
const LOADERS = {};
function showView(name) {
  document.querySelectorAll(".navitem").forEach((n) => n.classList.toggle("active", n.dataset.view === name));
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  $("view-" + name).classList.add("active");
  $("view-title").textContent = TITLES[name] || name;
  if (LOADERS[name]) LOADERS[name]();
}
document.querySelectorAll(".navitem").forEach((n) =>
  n.addEventListener("click", () => showView(n.dataset.view)));

// ----------------------------------------------------------- overview
LOADERS.overview = async () => {
  const d = await getJSON("/api/stats");
  $("today-pill").textContent = "VN: " + d.today_label;
  const s = d.stats;
  const cards = [
    ["Ngày", s.days], ["Đã publish", s.published_days], ["Bài (items)", s.items],
    ["Users", s.users], ["VIP", s.vip_users], ["Bots", s.bots],
    ["Giftcode", s.gift_codes], ["Ads active", s.active_ads], ["Share refs", s.share_refs],
  ];
  $("stat-grid").innerHTML = cards.map(([l, n]) =>
    `<div class="stat"><div class="n">${n}</div><div class="l">${l}</div></div>`).join("");
};

// ----------------------------------------------------------- config / telegram
async function refreshConfig() {
  const cfg = await getJSON("/api/config");
  $("api_id").value = cfg.telegram.api_id || "";
  $("api_hash_hint").textContent = cfg.telegram.has_api_hash ? "Đã lưu: " + cfg.telegram.api_hash_masked : "Chưa có api_hash";
  const ls = $("login_state");
  if (cfg.telegram.logged_in_user) { ls.textContent = "Đã đăng nhập: " + cfg.telegram.logged_in_user; ls.className = "badge online"; }
  else { ls.textContent = "Chưa đăng nhập Telegram"; ls.className = "badge warning"; }
  // platform form
  const p = cfg.platform;
  $("pf_enabled").checked = p.enabled; $("pf_publish").checked = p.publish_channels;
  $("pf_archive").checked = p.archive_index; $("pf_delivery").checked = p.bot_delivery;
  $("pf_vip").checked = p.require_vip_for_archive;
  $("pf_admin_forum").value = p.admin_forum_id || ""; $("pf_admin_notify").value = p.admin_notify_group || "";
  $("pf_delay").value = p.delivery_delay_sec; $("pf_member").value = p.membership_channel_id || "";
  $("pf_recheck").value = p.force_join_check_sec;
}
LOADERS.telegram = refreshConfig;
LOADERS.platform = refreshConfig;

$("save_tg").onclick = async () => {
  const { ok, json } = await api("/api/config/telegram", { api_id: $("api_id").value, api_hash: $("api_hash").value });
  if (!ok) return alert(json.error || "Lỗi"); $("api_hash").value = ""; refreshConfig();
};
$("send_code").onclick = async () => {
  const { ok, json } = await api("/api/telegram/send_code", { phone: $("phone").value });
  if (!ok) return alert(json.error || "Lỗi"); $("code_box").classList.remove("hidden");
};
$("sign_in").onclick = async () => {
  const { ok, json } = await api("/api/telegram/sign_in", { code: $("code").value });
  if (!ok) return alert(json.error || "Lỗi");
  if (json.need_password) return $("pwd_box").classList.remove("hidden");
  doneLogin(json);
};
$("check_pwd").onclick = async () => {
  const { ok, json } = await api("/api/telegram/password", { password: $("tfa").value });
  if (!ok) return alert(json.error || "Lỗi"); doneLogin(json);
};
function doneLogin(json) {
  $("code_box").classList.add("hidden"); $("pwd_box").classList.add("hidden");
  refreshConfig(); refreshStatus(); alert("Đăng nhập Telegram thành công: " + (json.username || ""));
}

$("save_pf").onclick = async () => {
  const { ok, json } = await api("/api/platform", {
    enabled: $("pf_enabled").checked, publish_channels: $("pf_publish").checked,
    archive_index_layer: $("pf_archive").checked, bot_delivery: $("pf_delivery").checked,
    require_vip_for_archive: $("pf_vip").checked, admin_forum_id: $("pf_admin_forum").value,
    admin_notify_group: $("pf_admin_notify").value, delivery_delay_sec: $("pf_delay").value,
    membership_channel_id: $("pf_member").value, force_join_check_sec: $("pf_recheck").value,
  });
  if (!ok) return alert(json.error || "Lỗi"); alert("Đã lưu Platform."); refreshConfig();
};

// ----------------------------------------------------------- userbot
function applyStatus(s) {
  const t = s.status || "stopped";
  const b = $("ub_status"); if (b) { b.textContent = t; b.className = "badge " + (t === "online" ? "online" : t === "error" ? "error" : ""); }
  const pill = $("ub-pill"); pill.textContent = "● userbot: " + t;
  pill.className = "pill " + (t === "online" ? "online" : t === "error" ? "error" : "stopped");
  const u = $("ub_user"); if (u) u.textContent = s.username ? "@" + s.username : (s.error ? "Lỗi: " + s.error : "");
}
const refreshStatus = async () => applyStatus(await getJSON("/api/userbot/status"));
$("btn_start").onclick = async () => { const { ok, json } = await api("/api/userbot/start"); if (!ok) return alert(json.error); applyStatus(json); };
$("btn_stop").onclick = async () => { const { json } = await api("/api/userbot/stop"); applyStatus(json); };
$("btn_logout_tg").onclick = async () => { if (!confirm("Đăng xuất Telegram?")) return; const { json } = await api("/api/userbot/logout"); applyStatus(json); refreshConfig(); };
$("sim_forward").onclick = async () => {
  const chat = "-100" + (1000000000 + Math.floor(Math.random() * 8999999));
  const { ok, json } = await api("/api/archive/ingest", { src_chat_id: chat, src_msg_id: Math.floor(Math.random() * 9999) + 1, caption: "auto-forward giả lập" });
  alert(ok ? `Đã ghi index ngày ${json.label} (item ${json.item_id})` : (json.error || "Lỗi"));
};

// ----------------------------------------------------------- archive
LOADERS.archive = async () => {
  const days = await getJSON("/api/archive/days");
  if (!days.length) { $("days_table").innerHTML = '<p class="muted">Chưa có ngày nào.</p>'; return; }
  $("days_table").innerHTML = `<table><tr><th>Label</th><th>Bài</th><th>Trạng thái</th><th></th></tr>` +
    days.map((d) => `<tr><td><b>${esc(d.label)}</b></td><td>${d.item_count}</td>
      <td><span class="tag ${d.status}">${d.status}</span></td>
      <td>
        <button class="btn sm" onclick="viewDay(${d.id},'${esc(d.label)}')">Xem</button>
        <button class="btn sm primary" onclick="pubDay(${d.id})">Publish</button>
        <button class="btn sm" onclick="closeDay(${d.id})">Close</button>
      </td></tr>`).join("") + `</table>`;
};
window.viewDay = async (id, label) => {
  const d = await getJSON("/api/archive/day/" + id);
  $("day_detail_card").classList.remove("hidden");
  $("day_detail_title").textContent = "Chi tiết ngày " + label;
  $("day_items").innerHTML = d.items.length ? `<table><tr><th>seq</th><th>src_chat</th><th>msg</th><th>caption</th></tr>` +
    d.items.map((i) => `<tr><td>${i.seq}</td><td>${esc(i.src_chat_id)}</td><td>${i.src_msg_id}</td><td>${esc(i.caption)}</td></tr>`).join("") + `</table>`
    : '<p class="muted">Chưa có item.</p>';
};
window.pubDay = async (id) => { await api("/api/archive/publish", { day_id: id }); LOADERS.archive(); };
window.closeDay = async (id) => { await api("/api/archive/close", { day_id: id }); LOADERS.archive(); };
$("btn_ingest").onclick = async () => {
  const { ok, json } = await api("/api/archive/ingest", {
    src_chat_id: $("ig_chat").value, src_msg_id: $("ig_msg").value || 0,
    day_label: $("ig_day").value, caption: $("ig_cap").value });
  if (!ok) return alert(json.error || "Lỗi"); alert("Đã ingest ngày " + json.label); LOADERS.archive();
};

// ----------------------------------------------------------- bots
LOADERS.bots = async () => {
  const d = await getJSON("/api/bots");
  $("bots_table").innerHTML = d.bots.length ? `<table><tr><th>slug</th><th>order</th><th>token</th><th>status</th><th></th></tr>` +
    d.bots.map((b) => `<tr><td>${esc(b.slug)}</td><td>${b.queue_order}</td>
      <td>${b.has_token ? "✅" : "—"}</td>
      <td><span class="badge ${b.status === "online" ? "online" : b.status === "error" ? "error" : ""}">${b.status}</span></td>
      <td><button class="btn sm primary" onclick="botStart('${esc(b.slug)}')">START</button>
          <button class="btn sm" onclick="botStop('${esc(b.slug)}')">STOP</button></td></tr>`).join("") + `</table>`
    : '<p class="muted">Chưa có bot.</p>';
};
window.botStart = async (slug) => { const { ok, json } = await api("/api/bots/start", { slug }); if (!ok) return alert(json.error); LOADERS.bots(); };
window.botStop = async (slug) => { await api("/api/bots/stop", { slug }); LOADERS.bots(); };
$("save_bot_btn").onclick = async () => {
  const { ok, json } = await api("/api/bots", { slug: $("bot_slug").value, token: $("bot_token").value, source_forum_id: $("bot_forum").value, queue_order: $("bot_order").value || 0 });
  if (!ok) return alert(json.error || "Lỗi"); $("bot_token").value = ""; LOADERS.bots();
};
$("start_all").onclick = async () => { const { ok, json } = await api("/api/bots/start"); if (!ok) return alert(json.error); LOADERS.bots(); };
$("stop_all").onclick = async () => { await api("/api/bots/stop"); LOADERS.bots(); };
$("broadcast").onclick = async () => { const { ok, json } = await api("/api/bots/broadcast"); alert(ok ? `Broadcast: ${json.sent} bài / ${json.users} user` : (json.error || "Lỗi")); };

// ----------------------------------------------------------- users
LOADERS.users = async () => {
  const u = await getJSON("/api/users");
  $("users_table").innerHTML = u.length ? `<table><tr><th>tg_user_id</th><th>username</th><th>VIP</th><th>đến</th><th></th></tr>` +
    u.map((x) => `<tr><td>${esc(x.tg_user_id)}</td><td>${esc(x.username)}</td>
      <td>${x.is_vip ? "⭐" : "—"}</td><td>${esc(x.vip_until)}</td>
      <td><button class="btn sm" onclick="revokeVip('${esc(x.tg_user_id)}')">Revoke</button></td></tr>`).join("") + `</table>`
    : '<p class="muted">Chưa có user.</p>';
};
window.revokeVip = async (uid) => { await api("/api/users/vip/revoke", { tg_user_id: uid }); LOADERS.users(); };
$("grant_vip").onclick = async () => { const { ok, json } = await api("/api/users/vip/grant", { tg_user_id: $("vip_uid").value, days: $("vip_days").value || 30 }); if (!ok) return alert(json.error); alert("Đã cấp VIP."); LOADERS.users(); };

// ----------------------------------------------------------- vip plans
LOADERS.vip = async () => {
  const p = await getJSON("/api/vip/plans");
  $("plans_table").innerHTML = p.length ? `<table><tr><th>Tên</th><th>Ngày</th><th>Stars</th><th></th></tr>` +
    p.map((x) => `<tr><td>${esc(x.name)}</td><td>${x.days}</td><td>${x.stars}⭐</td>
      <td><button class="btn sm danger" onclick="delPlan(${x.id})">Xoá</button></td></tr>`).join("") + `</table>`
    : '<p class="muted">Chưa có gói.</p>';
};
window.delPlan = async (id) => { await api("/api/vip/plans/delete", { plan_id: id }); LOADERS.vip(); };
$("add_plan").onclick = async () => { const { ok, json } = await api("/api/vip/plans", { name: $("plan_name").value, days: $("plan_days").value, stars: $("plan_stars").value }); if (!ok) return alert(json.error); LOADERS.vip(); };

// ----------------------------------------------------------- gift
LOADERS.gift = async () => {
  const g = await getJSON("/api/gift");
  $("gift_table").innerHTML = g.length ? `<table><tr><th>Mã</th><th>VIP days</th><th>Dùng</th><th>Active</th></tr>` +
    g.map((x) => `<tr><td><b>${esc(x.code)}</b></td><td>${x.vip_days}</td><td>${x.used_count}/${x.max_uses}</td><td>${x.active ? "✅" : "—"}</td></tr>`).join("") + `</table>`
    : '<p class="muted">Chưa có mã.</p>';
};
$("add_gift").onclick = async () => { const { ok, json } = await api("/api/gift", { code: $("gc_code").value, vip_days: $("gc_days").value, max_uses: $("gc_max").value }); if (!ok) return alert(json.error); $("gc_code").value = ""; LOADERS.gift(); };
$("redeem_gift").onclick = async () => { const { ok, json } = await api("/api/gift/redeem", { code: $("rd_code").value, tg_user_id: $("rd_uid").value }); alert(ok ? `OK +${json.vip_days} ngày VIP` : (json.error || "Lỗi")); LOADERS.gift(); };

// ----------------------------------------------------------- ads
LOADERS.ads = async () => {
  const d = await getJSON("/api/ads");
  $("ads_table").innerHTML = (d.ads.length ? `<table><tr><th>Advertiser</th><th>alias</th><th>Khoảng</th><th>Active</th><th></th></tr>` +
    d.ads.map((a) => `<tr><td>${esc(a.advertiser)}</td><td>${esc(a.alias)}</td><td>${esc(a.start_label)}→${esc(a.end_label)}</td>
      <td>${a.active ? "✅" : "🚫"}</td><td>${a.active ? `<button class="btn sm danger" onclick="revokeAd(${a.id})">Revoke</button>` : ""}</td></tr>`).join("") + `</table>`
    : '<p class="muted">Chưa có ads.</p>') + `<p class="muted">Alias đang hiển thị: ${d.active_aliases.map(esc).join(", ") || "—"}</p>`;
};
window.revokeAd = async (id) => { await api("/api/ads/revoke", { ad_id: id }); LOADERS.ads(); };
$("add_ad").onclick = async () => { const { ok, json } = await api("/api/ads", { advertiser: $("ad_adv").value, alias: $("ad_alias").value, content: $("ad_content").value, start_label: $("ad_start").value, end_label: $("ad_end").value }); if (!ok) return alert(json.error); LOADERS.ads(); };

// ----------------------------------------------------------- share
LOADERS.share = async () => {
  const s = await getJSON("/api/share");
  $("share_table").innerHTML = s.length ? `<table><tr><th>Token</th><th>Owner</th><th>Clicks</th><th>Joined</th></tr>` +
    s.map((x) => `<tr><td>${esc(x.token)}</td><td>${esc(x.owner_tg_user_id)}</td><td>${x.clicks}</td><td>${x.joined}</td></tr>`).join("") + `</table>`
    : '<p class="muted">Chưa có ref.</p>';
};
$("add_share").onclick = async () => { const { ok, json } = await api("/api/share", { owner: $("sh_owner").value }); if (!ok) return alert(json.error); $("sh_token").textContent = "Token: " + json.token; LOADERS.share(); };

// ----------------------------------------------------------- backup
LOADERS.backup = async () => {
  const b = await getJSON("/api/backup/list");
  $("backup_table").innerHTML = b.length ? `<table><tr><th>File</th><th>KB</th><th></th></tr>` +
    b.map((x) => `<tr><td>${esc(x.name)}</td><td>${(x.size / 1024).toFixed(1)}</td>
      <td><a class="btn sm" href="/api/backup/download/${encodeURIComponent(x.name)}">Tải</a></td></tr>`).join("") + `</table>`
    : '<p class="muted">Chưa có backup.</p>';
};
$("make_backup").onclick = async () => { const { ok, json } = await api("/api/backup/create"); if (!ok) return alert(json.error); alert("Đã tạo: " + json.name); LOADERS.backup(); };

// ----------------------------------------------------------- rollup
$("gen_rollup").onclick = async () => { const d = await getJSON("/api/rollup"); $("rollup_out").textContent = d.text; };
LOADERS.rollup = async () => { const d = await getJSON("/api/rollup"); $("rollup_out").textContent = d.text; };

// ----------------------------------------------------------- logs SSE
function addLog(rec) {
  const v = $("log_view"); if (!v) return;
  const line = document.createElement("div");
  line.className = "log-line level-" + (rec.level || "info");
  line.innerHTML = `<span class="ts">[${rec.ts}]</span> <span class="src">${esc(rec.source)}</span> ${esc(rec.message)}`;
  v.appendChild(line); v.scrollTop = v.scrollHeight;
}
function startSSE() {
  const es = new EventSource("/api/logs/stream");
  es.onmessage = (e) => { try { addLog(JSON.parse(e.data)); } catch (_) {} };
  es.onopen = () => { $("sse_dot").className = "pill online"; $("sse_dot").textContent = "● live"; };
  es.onerror = () => { $("sse_dot").className = "pill error"; $("sse_dot").textContent = "● reconnect"; };
}

// ----------------------------------------------------------- boot
refreshConfig(); refreshStatus(); startSSE(); LOADERS.overview();
setInterval(refreshStatus, 5000);
