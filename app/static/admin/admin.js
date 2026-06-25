const state = {
  view: "overview",
  apiKey: localStorage.getItem("legal_wecom_api_key") || "",
  data: {},
};

const titles = {
  overview: ["总览", "系统状态、调度器和部署健康情况"],
  cases: ["案件", "创建、查询和同步案件"],
  messages: ["消息", "模拟企业微信群消息进入识别链路"],
  reminders: ["提醒", "查看提醒、手动触发到期提醒发送"],
  events: ["事件", "查看系统抽取出的结构化法务事件"],
  media: ["媒体", "图片、PDF、文件和 OCR 状态"],
  sync: ["同步日志", "腾讯文档同步日志和重试结果"],
};

const $ = (selector) => document.querySelector(selector);

function showAlert(message, type = "info") {
  const alert = $("#alert");
  if (!message) {
    alert.className = "alert hidden";
    alert.textContent = "";
    return;
  }
  alert.className = `alert ${type === "error" ? "error" : ""}`;
  alert.textContent = message;
}

async function api(path, options = {}) {
  const headers = {
    "Content-Type": "application/json",
    ...(options.headers || {}),
  };
  if (state.apiKey) {
    headers["X-API-Key"] = state.apiKey;
  }
  const response = await fetch(path, { ...options, headers });
  const text = await response.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = { message: text };
  }
  if (!response.ok || (body && body.code && body.code !== 0)) {
    throw new Error((body && body.message) || `请求失败：${response.status}`);
  }
  return body && Object.prototype.hasOwnProperty.call(body, "data") ? body.data : body;
}

function setView(view) {
  state.view = view;
  const [title, subtitle] = titles[view];
  $("#view-title").textContent = title;
  $("#view-subtitle").textContent = subtitle;
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.view === view);
  });
  showAlert("");
  loadView();
}

function panel(title, body, extra = "") {
  return `
    <div class="panel">
      <div class="panel-header">
        <h2 class="panel-title">${title}</h2>
        ${extra}
      </div>
      <div class="panel-body">${body}</div>
    </div>
  `;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function fmt(value) {
  if (value === null || value === undefined || value === "") return '<span class="muted">-</span>';
  return escapeHtml(value);
}

function badge(value) {
  const text = String(value || "-");
  const cls = ["ok", "success", "sent", "paid", "normal", "downloaded", "processed"].includes(text)
    ? "ok"
    : ["pending", "retrying", "degraded"].includes(text)
      ? "warn"
      : "";
  return `<span class="badge ${cls}">${escapeHtml(text)}</span>`;
}

function table(columns, rows) {
  if (!rows || rows.length === 0) {
    return document.querySelector("#empty-state-template").innerHTML;
  }
  return `
    <div class="table-wrap">
      <table>
        <thead><tr>${columns.map((column) => `<th>${column.label}</th>`).join("")}</tr></thead>
        <tbody>
          ${rows
            .map(
              (row) => `
                <tr>
                  ${columns
                    .map((column) => {
                      const value = column.render ? column.render(row) : fmt(row[column.key]);
                      return `<td>${value}</td>`;
                    })
                    .join("")}
                </tr>
              `,
            )
            .join("")}
        </tbody>
      </table>
    </div>
  `;
}

async function renderOverview() {
  const [health, detail] = await Promise.all([api("/api/v1/health"), api("/api/v1/health/detail")]);
  const config = detail.config || {};
  const jobs = (detail.scheduler && detail.scheduler.jobs) || [];
  $("#content").innerHTML = `
    <div class="grid cols-3">
      <div class="panel stat"><div class="stat-label">系统状态</div><div class="stat-value status-ok">${escapeHtml(health.status)}</div></div>
      <div class="panel stat"><div class="stat-label">运行环境</div><div class="stat-value">${escapeHtml(health.env)}</div></div>
      <div class="panel stat"><div class="stat-label">调度器</div><div class="stat-value ${detail.scheduler.running ? "status-ok" : "status-warning"}">${detail.scheduler.running ? "running" : "stopped"}</div></div>
    </div>
    <div class="grid cols-2" style="margin-top:14px">
      ${panel(
        "配置自检",
        table(
          [
            { label: "项目", key: "name" },
            { label: "状态", render: (row) => badge(row.status) },
            { label: "说明", key: "message" },
          ],
          config.items || [],
        ),
      )}
      ${panel(
        "调度任务",
        table(
          [
            { label: "任务", key: "id" },
            { label: "下次运行", key: "next_run_time" },
          ],
          jobs,
        ),
      )}
    </div>
  `;
}

function caseForm() {
  return `
    <form id="case-form" class="form-grid">
      <div class="field"><label>案号</label><input name="case_no" required placeholder="(2026)黔0281民初3118号" /></div>
      <div class="field"><label>债务人</label><input name="debtor_name" required /></div>
      <div class="field"><label>群 ID</label><input name="group_id" required placeholder="group_001" /></div>
      <div class="field"><label>到期日</label><input name="due_date" type="date" required /></div>
      <div class="field"><label>总金额</label><input name="total_amount" type="number" step="0.01" value="0.00" /></div>
      <div class="field"><label>租户 ID</label><input name="tenant_id" /></div>
      <div class="field"><label>债务人企微 ID</label><input name="debtor_wecom_userid" /></div>
      <div class="field"><label>律师企微 ID</label><input name="lawyer_wecom_userid" /></div>
      <div class="field"><label>&nbsp;</label><button type="submit">创建案件</button></div>
    </form>
  `;
}

async function renderCases() {
  const data = await api("/api/v1/legal/cases?limit=50");
  $("#content").innerHTML = `
    <div class="grid">
      ${panel("创建案件", caseForm())}
      ${panel(
        "案件列表",
        table(
          [
            { label: "ID", key: "id" },
            { label: "案号", key: "case_no" },
            { label: "债务人", key: "debtor_name" },
            { label: "状态", render: (row) => badge(row.status) },
            { label: "到期日", key: "due_date" },
            { label: "已还/总额", render: (row) => `${fmt(row.paid_amount)} / ${fmt(row.total_amount)}` },
            { label: "群", key: "group_id" },
          ],
          data.items || [],
        ),
        '<button id="scan-status-btn" class="ghost">扫描状态</button>',
      )}
    </div>
  `;
  $("#case-form").addEventListener("submit", submitCase);
  $("#scan-status-btn").addEventListener("click", async () => {
    await api("/api/v1/legal/cases/scan-status", { method: "POST", body: "{}" });
    showAlert("案件状态扫描完成");
    renderCases();
  });
}

async function submitCase(event) {
  event.preventDefault();
  const form = new FormData(event.currentTarget);
  const payload = Object.fromEntries(form.entries());
  Object.keys(payload).forEach((key) => {
    if (payload[key] === "") payload[key] = null;
  });
  await api("/api/v1/legal/cases", { method: "POST", body: JSON.stringify(payload) });
  showAlert("案件创建成功");
  renderCases();
}

async function renderMessages() {
  $("#content").innerHTML = panel(
    "模拟群消息",
    `
      <form id="message-form" class="form-grid">
        <div class="field"><label>群 ID</label><input name="group_id" required value="group_001" /></div>
        <div class="field"><label>发送人 ID</label><input name="sender_id" required value="user_001" /></div>
        <div class="field"><label>消息类型</label><select name="msg_type"><option>text</option><option>image</option><option>file</option><option>pdf</option></select></div>
        <div class="field wide"><label>消息内容</label><textarea name="content" placeholder="案件(2026)黔0281民初3118号需要缴费400元，7天内完成"></textarea></div>
        <div class="field wide"><label>文件 URL</label><input name="file_url" /></div>
        <div class="field"><button type="submit">提交识别</button></div>
      </form>
      <pre id="message-result" class="mono muted"></pre>
    `,
  );
  $("#message-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(event.currentTarget).entries());
    Object.keys(payload).forEach((key) => {
      if (payload[key] === "") payload[key] = null;
    });
    const result = await api("/api/v1/legal/messages/mock", { method: "POST", body: JSON.stringify(payload) });
    $("#message-result").textContent = JSON.stringify(result, null, 2);
    showAlert("消息处理完成");
  });
}

async function renderReminders() {
  const data = await api("/api/v1/legal/reminders?limit=50");
  $("#content").innerHTML = panel(
    "提醒列表",
    table(
      [
        { label: "ID", key: "id" },
        { label: "类型", key: "reminder_type" },
        { label: "状态", render: (row) => badge(row.status) },
        { label: "提醒时间", key: "remind_at" },
        { label: "群", key: "group_id" },
        { label: "内容", key: "content" },
      ],
      data.items || [],
    ),
    '<button id="run-due-btn">发送到期提醒</button>',
  );
  $("#run-due-btn").addEventListener("click", async () => {
    const result = await api("/api/v1/legal/reminders/run-due", { method: "POST", body: "{}" });
    showAlert(`扫描完成：sent=${result.sent}, failed=${result.failed}, retrying=${result.retrying}`);
    renderReminders();
  });
}

async function renderEvents() {
  const data = await api("/api/v1/legal/events?limit=50");
  $("#content").innerHTML = panel(
    "事件列表",
    table(
      [
        { label: "ID", key: "id" },
        { label: "类型", render: (row) => badge(row.event_type) },
        { label: "案件 ID", key: "case_id" },
        { label: "金额", key: "amount" },
        { label: "时间", key: "event_time" },
        { label: "文本", render: (row) => `<div class="json-cell">${fmt(row.extracted_text)}</div>` },
      ],
      data.items || [],
    ),
  );
}

async function renderMedia() {
  const data = await api("/api/v1/legal/media-files?page_size=50");
  $("#content").innerHTML = panel(
    "媒体文件",
    table(
      [
        { label: "ID", key: "id" },
        { label: "类型", key: "media_type" },
        { label: "下载", render: (row) => badge(row.download_status) },
        { label: "OCR", render: (row) => badge(row.ocr_status) },
        { label: "文件名", key: "original_filename" },
        { label: "群", key: "group_id" },
        { label: "错误", key: "last_error" },
      ],
      data.items || [],
    ),
  );
}

async function renderSync() {
  const data = await api("/api/v1/legal/document-sync-logs?page_size=50");
  $("#content").innerHTML = panel(
    "同步日志",
    table(
      [
        { label: "ID", key: "id" },
        { label: "类型", key: "sync_type" },
        { label: "状态", render: (row) => badge(row.status) },
        { label: "目标", key: "sync_target" },
        { label: "Sheet", key: "external_sheet_name" },
        { label: "错误", key: "error_message" },
      ],
      data.items || [],
    ),
  );
}

async function loadView() {
  $("#content").innerHTML = '<div class="empty-state">加载中...</div>';
  try {
    if (state.view === "overview") await renderOverview();
    if (state.view === "cases") await renderCases();
    if (state.view === "messages") await renderMessages();
    if (state.view === "reminders") await renderReminders();
    if (state.view === "events") await renderEvents();
    if (state.view === "media") await renderMedia();
    if (state.view === "sync") await renderSync();
  } catch (error) {
    $("#content").innerHTML = "";
    showAlert(error.message, "error");
  }
}

function init() {
  $("#api-key-input").value = state.apiKey;
  $("#save-key-btn").addEventListener("click", () => {
    state.apiKey = $("#api-key-input").value.trim();
    localStorage.setItem("legal_wecom_api_key", state.apiKey);
    showAlert("API Key 已保存");
    loadView();
  });
  $("#refresh-btn").addEventListener("click", loadView);
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.addEventListener("click", () => setView(item.dataset.view));
  });
  setView("overview");
}

document.addEventListener("DOMContentLoaded", init);
