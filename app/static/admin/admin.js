const state = {
  view: localStorage.getItem("legal_wecom_view") || "overview",
  apiKey: localStorage.getItem("legal_wecom_api_key") || "",
  data: {},
  editingCaseId: null,
  editingCandidateId: null,
  selectedReviewId: null,
  reviewStatusFilter: "pending",
  reviewPreviewUrl: null,
  editingReminderId: null,
  kdocsTarget: "enforcement",
  kdocsPage: 1,
  kdocsQuery: "判决书",
  kdocsDocumentToken: null,
  kdocsDocumentTokenStack: [],
  wecomPlatformGroups: [],
  selectedCaseId: null,
};

const titles = {
  overview: ["工作台", "集中处理待办、失败任务和业务异常"],
  cases: ["案件", "确认自动识别的案件并管理正式案件"],
  "case-workspace": ["案件工作台", "集中查看案件事实、资料、付款、提醒和外部同步"],
  attribution: ["待归属", "批量确认资料和事件所属案件"],
  messages: ["来源消息", "查看进入自动化链路的企业微信消息"],
  "archive-groups": ["企业微信群", "管理会话发现、案件识别和发送目标映射"],
  "ocr-reviews": ["人工复核", "核对识别结果并控制业务同步"],
  "recognition-settings": ["识别与 AI", "配置腾讯 OCR 和法律文书结构化模型"],
  reminders: ["提醒任务", "查看、编辑和执行企业微信提醒"],
  "payment-trackings": ["缴费信息跟踪", "按缴费通知汇总支付状态、催促进度和凭证"],
  "merchant-questions": ["商家待回复", "跟踪外部消息回复时效"],
  "send-platform": ["发送通道", "配置 wecomapi token、guid 和公网回调地址"],
  "system-alerts": ["系统异常", "处理归档、识别、写入、发送和运行异常"],
  events: ["识别记录", "查看系统抽取出的结构化法务事件"],
  media: ["附件记录", "查看图片、PDF、文件和 OCR 状态"],
  sync: ["写入记录", "查看金山文档写入日志和失败重试结果"],
  "kdocs-browser": ["文档内容", "查看金山表格和归档文件的真实内容"],
};

const sections = {
  workbench: {
    label: "工作台",
    defaultView: "overview",
    views: [{ view: "overview", label: "任务总览" }],
  },
  cases: {
    label: "案件与群",
    defaultView: "cases",
    views: [
      { view: "cases", label: "案件" },
      { view: "case-workspace", label: "案件工作台" },
      { view: "archive-groups", label: "企业微信群" },
    ],
  },
  materials: {
    label: "资料处理",
    defaultView: "ocr-reviews",
    views: [
      { view: "attribution", label: "待归属" },
      { view: "ocr-reviews", label: "人工复核" },
      { view: "media", label: "附件记录" },
      { view: "messages", label: "来源消息" },
      { view: "events", label: "识别记录" },
    ],
  },
  reminders: {
    label: "提醒任务",
    defaultView: "reminders",
    views: [
      { view: "payment-trackings", label: "缴费跟踪" },
      { view: "reminders", label: "提醒任务" },
      { view: "merchant-questions", label: "商家待回复" },
    ],
  },
  kdocs: {
    label: "金山结果",
    defaultView: "kdocs-browser",
    views: [
      { view: "kdocs-browser", label: "文档内容" },
      { view: "sync", label: "写入记录" },
    ],
  },
  settings: {
    label: "系统配置",
    defaultView: "recognition-settings",
    views: [
      { view: "recognition-settings", label: "识别与 AI" },
      { view: "send-platform", label: "发送通道" },
      { view: "system-alerts", label: "系统异常" },
    ],
  },
};

const viewAliases = {};

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

function normalizedView(view) {
  const canonicalView = viewAliases[view] || view;
  return Object.prototype.hasOwnProperty.call(titles, canonicalView) ? canonicalView : "overview";
}

function viewFromLocation() {
  return normalizedView(window.location.hash.replace(/^#/, "") || state.view);
}

function sectionForView(view) {
  return Object.entries(sections).find(([, section]) => section.views.some((item) => item.view === view))?.[0] || "workbench";
}

function renderSectionTabs(view) {
  const section = sections[sectionForView(view)];
  const tabs = $("#section-tabs");
  tabs.innerHTML = section.views
    .map(
      (item) =>
        `<button class="section-tab ${item.view === view ? "active" : ""}" type="button" data-section-view="${item.view}">${escapeHtml(item.label)}</button>`,
    )
    .join("");
  tabs.classList.toggle("single", section.views.length === 1);
  tabs.querySelectorAll("[data-section-view]").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.sectionView));
  });
}

function setView(view, { syncLocation = true, replaceLocation = false } = {}) {
  const nextView = normalizedView(view);
  state.view = nextView;
  localStorage.setItem("legal_wecom_view", nextView);
  if (syncLocation && window.location.hash !== `#${nextView}`) {
    const method = replaceLocation ? "replaceState" : "pushState";
    history[method](null, "", `${window.location.pathname}${window.location.search}#${nextView}`);
  }
  const [title, subtitle] = titles[nextView];
  $("#view-title").textContent = title;
  $("#view-subtitle").textContent = subtitle;
  const activeSection = sectionForView(nextView);
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.section === activeSection);
  });
  renderSectionTabs(nextView);
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

function safeExternalUrl(value) {
  try {
    const url = new URL(String(value || ""));
    return url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

function formatFileSize(value) {
  const size = Number(value);
  if (!Number.isFinite(size) || size < 0) return "-";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function badge(value) {
  const text = String(value || "-");
  const cls = ["ok", "success", "sent", "paid", "normal", "downloaded", "processed", "resolved"].includes(text)
    ? "ok"
    : ["pending", "retrying", "degraded", "acknowledged", "warning"].includes(text)
      ? "warn"
      : "";
  const finalCls = ["rejected", "failed", "cancelled", "critical", "open"].includes(text) ? "danger" : cls;
  return `<span class="badge ${finalCls}">${escapeHtml(text)}</span>`;
}

function healthStatusClass(status) {
  if (status === "ok") return "status-ok";
  if (status === "error") return "status-error";
  return "status-warning";
}

function table(columns, rows, className = "") {
  if (!rows || rows.length === 0) {
    return document.querySelector("#empty-state-template").innerHTML;
  }
  return `
    <div class="table-wrap">
      <table class="${escapeHtml(className)}">
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

function workbenchTaskCard({ label, count, note, view, tone = "" }) {
  return `
    <button class="workbench-task-card ${tone}" type="button" data-workbench-view="${view}">
      <span class="workbench-task-label">${escapeHtml(label)}</span>
      <strong>${count}</strong>
      <span class="workbench-task-note">${escapeHtml(note)}</span>
      <span class="workbench-task-action">进入处理</span>
    </button>
  `;
}

function workbenchConnection(label, status, note) {
  const normalizedStatus = ["ok", "success"].includes(status) ? "ok" : ["warning", "degraded", "disabled"].includes(status) ? "warning" : "error";
  const statusLabel = normalizedStatus === "ok" ? "正常" : normalizedStatus === "warning" ? "需关注" : "异常";
  return `
    <div class="workbench-connection">
      <span class="connection-dot ${normalizedStatus}"></span>
      <div><strong>${escapeHtml(label)}</strong><span>${escapeHtml(note || statusLabel)}</span></div>
      <span class="connection-status ${normalizedStatus}">${statusLabel}</span>
    </div>
  `;
}

async function renderOverview() {
  const [candidatesData, reviewsData, syncData, remindersData, questionsData, alertsData, detail] = await Promise.all([
    api("/api/v1/legal/cases/candidates?status=pending&page_size=100"),
    api("/api/v1/legal/ocr-reviews?review_status=pending&page_size=100"),
    api("/api/v1/legal/document-sync-logs?status=failed&page_size=100"),
    api("/api/v1/legal/reminders?status=failed&limit=100"),
    api("/api/v1/legal/merchant-questions?status=open&limit=200"),
    api("/api/v1/legal/system-alerts?status=open&page_size=200"),
    api("/api/v1/health/detail"),
  ]);
  const reviews = reviewsData.items || [];
  const configItems = (detail.config && detail.config.items) || [];
  const configByName = (name) => configItems.find((item) => item.name === name) || {};
  const archive = configByName("WECOM_ARCHIVE_MODE");
  const ocr = configByName("OCR_PROVIDER");
  const ai = configByName("LEGAL_EXTRACTION_MODE");
  const kdocs = configByName("KDOCS_MODE");
  const sender = detail.sender || { status: "disabled", message: "发送通道未启用" };
  const queueRows = reviews.slice(0, 8);

  $("#content").innerHTML = `
    <section class="workbench" data-business-workbench>
      <div class="workbench-heading">
        <div><h2>当前待办</h2><p>数量最多显示当前接口返回的前 100 条，商家回复和系统异常最多 200 条。</p></div>
        <span class="workbench-updated">刚刚刷新</span>
      </div>
      <div class="workbench-summary">
        ${workbenchTaskCard({ label: "待确认案件", count: candidatesData.total ?? (candidatesData.items || []).length, note: "补齐识别结果后确认建立正式案件", view: "cases", tone: (candidatesData.items || []).length ? "warning" : "clear" })}
        ${workbenchTaskCard({ label: "待人工复核", count: reviewsData.total ?? reviews.length, note: "识别结果需确认后才能进入业务台账", view: "ocr-reviews", tone: reviews.length ? "warning" : "clear" })}
        ${workbenchTaskCard({ label: "金山写入失败", count: syncData.total ?? (syncData.items || []).length, note: "检查失败原因并决定是否重试", view: "sync", tone: (syncData.items || []).length ? "danger" : "clear" })}
        ${workbenchTaskCard({ label: "提醒发送失败", count: remindersData.total ?? (remindersData.items || []).length, note: "处理未送达的企业微信提醒", view: "reminders", tone: (remindersData.items || []).length ? "danger" : "clear" })}
        ${workbenchTaskCard({ label: "商家待回复", count: questionsData.total ?? (questionsData.items || []).length, note: "跟进尚未收到答复的客户问题", view: "merchant-questions", tone: (questionsData.items || []).length ? "warning" : "clear" })}
        ${workbenchTaskCard({ label: "系统异常", count: alertsData.total ?? (alertsData.items || []).length, note: "查看当前未恢复的运行异常", view: "system-alerts", tone: (alertsData.items || []).length ? "danger" : "clear" })}
      </div>

      <div class="workbench-layout">
        <section class="workbench-queue">
          <header><div><h2>最近待复核资料</h2><p>优先确认识别结果，再执行后续提醒和金山写入。</p></div><button class="ghost small" type="button" data-workbench-view="ocr-reviews">查看全部</button></header>
          ${
            queueRows.length
              ? `<div class="workbench-queue-list">${queueRows
                  .map((item) => {
                    const result = item.ocr_result || {};
                    const name = item.original_filename || `资料 ${item.media_file_id}`;
                    const detailText = [result.case_no, result.document_type || result.event_type, item.group_id].filter(Boolean).join(" · ");
                    return `<button type="button" class="workbench-queue-row" data-review-entry="${item.media_file_id}"><span class="queue-file">${escapeHtml(name)}</span><span class="queue-detail">${escapeHtml(detailText || "待确认资料类型")}</span><span class="queue-time">${escapeHtml(item.updated_at || "")}</span><span class="queue-action">复核</span></button>`;
                  })
                  .join("")}</div>`
              : '<div class="workbench-empty"><strong>当前没有待复核资料</strong><span>新的企业微信材料进入后会显示在这里。</span></div>'
          }
        </section>

        <aside class="workbench-connections">
          <header><h2>系统连接</h2><button class="ghost small" type="button" data-workbench-view="recognition-settings">管理配置</button></header>
          ${workbenchConnection("企业微信会话存档", archive.status || "warning", archive.message || "等待状态检查")}
          ${workbenchConnection("OCR 识别", ocr.status || "warning", ocr.message || "等待状态检查")}
          ${workbenchConnection("AI 结构化", ai.status || "warning", ai.message || "等待状态检查")}
          ${workbenchConnection("金山文档", kdocs.status || "warning", kdocs.message || "等待状态检查")}
          ${workbenchConnection("消息发送通道", sender.status, sender.message || "等待状态检查")}
        </aside>
      </div>
    </section>
  `;
  document.querySelectorAll("[data-workbench-view]").forEach((button) => {
    button.addEventListener("click", () => setView(button.dataset.workbenchView));
  });
  document.querySelectorAll("[data-review-entry]").forEach((button) => {
    button.addEventListener("click", () => {
      state.reviewStatusFilter = "pending";
      state.selectedReviewId = Number(button.dataset.reviewEntry);
      setView("ocr-reviews");
    });
  });
}

function wecomApiStageLabel(stage) {
  const labels = {
    not_configured: "未完成配置",
    request_failed: "连接失败",
    invalid_response: "返回异常",
    remote_error: "平台返回错误",
    login_expired: "登录态过期",
    logged_out: "未登录",
    logged_in: "已在线",
  };
  return labels[stage] || "未检测";
}

function wecomApiStatusClass(status) {
  if (!status) return "";
  if (status.online) return "online";
  if (status.stage === "not_configured") return "warning";
  return "error";
}

function renderWeComApiStatus(status) {
  if (!status) {
    return `
      <div class="platform-status-box">
        <span class="platform-status-dot warning"></span>
        <div>
          <strong>尚未检测登录态</strong>
          <p>点击检测后会调用第三方平台 <span class="mono">/login/checkLogin</span>，登录和重新登录都在第三方平台完成。</p>
        </div>
      </div>
    `;
  }
  const message = status.vendor_message || (status.missing || []).join("、") || (status.online ? "第三方平台返回账号在线。" : "请在第三方平台确认账号登录态。");
  return `
    <div class="platform-status-box ${status.online ? "success" : "warn"}">
      <span class="platform-status-dot ${wecomApiStatusClass(status)}"></span>
      <div>
        <strong>${escapeHtml(wecomApiStageLabel(status.stage))}</strong>
        <p>${escapeHtml(message)}</p>
        ${status.account_name ? `<p>当前账号：${escapeHtml(status.account_name)}</p>` : ""}
      </div>
    </div>
  `;
}

async function renderWeComApiPlatform(initialStatus = null) {
  const settings = await api("/api/v1/legal/wecomapi-settings");
  const endpoint = `${settings.base_url || ""}${settings.api_path || ""}`;
  const configured = settings.has_token && settings.has_guid;
  const sendModeClass = settings.send_mode === "wecomapi" ? "live" : "mock";
  $("#content").innerHTML = `
    <section class="platform-console">
      <header class="platform-hero">
        <div class="platform-hero-main">
          <div class="platform-hero-mark">API</div>
          <div>
            <h2>第三方 wecomapi 发送平台</h2>
            <div class="platform-hero-meta">
              <span class="platform-pill ${configured ? "ready" : "warn"}">${configured ? "Token 和 guid 已配置" : "Token 或 guid 待配置"}</span>
              <span class="platform-pill ${sendModeClass}">发送模式：${escapeHtml(settings.send_mode)}</span>
            </div>
          </div>
        </div>
        <div class="platform-hero-actions">
          <a class="button-like ghost" href="${escapeHtml(settings.platform_url)}" target="_blank" rel="noreferrer">打开平台</a>
          <button id="check-wecomapi-login-btn" type="button">检测登录态</button>
        </div>
      </header>
      <div class="platform-body">
        <div id="wecomapi-status-result">${renderWeComApiStatus(initialStatus)}</div>
        <div class="platform-info-grid">
          <div class="platform-info-item primary">
            <span>平台接口</span>
            <strong class="mono">${escapeHtml(endpoint || "-")}</strong>
          </div>
          <div class="platform-info-item">
            <span>Token Header</span>
            <strong>${escapeHtml(settings.token_header || "-")}</strong>
          </div>
          <div class="platform-info-item">
            <span>guid</span>
            <strong class="mono">${escapeHtml(settings.guid || "未配置")}</strong>
          </div>
          <div class="platform-info-item">
            <span>回调校验</span>
            <strong>${settings.callback_auth_enabled ? "已启用 Token 校验" : "不校验 Token"}</strong>
          </div>
        </div>
        <div class="callback-line">
          <div>
            <span>消息回调地址</span>
            <strong class="mono">${escapeHtml(settings.callback_url)}</strong>
          </div>
          <button type="button" class="ghost" data-copy-platform-callback>复制回调</button>
        </div>
        <section class="platform-settings-card">
          <div class="platform-section-head">
            <div>
              <h3>连接配置</h3>
              <p>token 不会明文回显，留空时保留服务器现有值。</p>
            </div>
            <span class="platform-security-note">敏感字段已保护</span>
          </div>
          <form id="wecomapi-settings-form" class="form-grid platform-form">
            <div class="field">
              <label>发送模式</label>
              <select name="send_mode">
                ${["mock", "wecomapi"].map((value) => `<option value="${value}" ${settings.send_mode === value ? "selected" : ""}>${value}</option>`).join("")}
              </select>
            </div>
            <div class="field">
              <label>Token Header</label>
              <input name="token_header" maxlength="64" value="${escapeHtml(settings.token_header || "WECOM-TOKEN")}" />
            </div>
            <div class="field wide">
              <label>平台 Base URL</label>
              <input name="base_url" maxlength="255" value="${escapeHtml(settings.base_url || "")}" placeholder="https://manager.wecomapi.com" />
            </div>
            <div class="field">
              <label>接口 Path</label>
              <input name="api_path" maxlength="128" value="${escapeHtml(settings.api_path || "/wecom/finder/api")}" />
            </div>
            <div class="field">
              <label>guid</label>
              <input name="guid" class="mono" maxlength="128" value="${escapeHtml(settings.guid || "")}" placeholder="第三方平台设备 guid" />
            </div>
            <div class="field wide">
              <label>token${settings.has_token ? "（已配置，留空不修改）" : ""}</label>
              <input name="token" type="password" maxlength="512" autocomplete="off" placeholder="${settings.has_token ? settings.token_mask : "粘贴第三方平台 token"}" />
            </div>
            <div class="field form-actions platform-form-actions">
              <button type="submit">保存配置</button>
              <button type="reset" class="ghost">恢复当前值</button>
            </div>
          </form>
        </section>
      </div>
    </section>
  `;
  document.querySelectorAll("[data-copy-platform-callback]").forEach((button) => {
    button.addEventListener("click", async () => {
      await navigator.clipboard.writeText(settings.callback_url);
      showAlert("回调地址已复制");
    });
  });
  $("#wecomapi-settings-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    const payload = {
      send_mode: formData.get("send_mode"),
      base_url: formData.get("base_url"),
      api_path: formData.get("api_path"),
      token_header: formData.get("token_header"),
      guid: formData.get("guid"),
    };
    const token = String(formData.get("token") || "").trim();
    if (token) payload.token = token;
    try {
      await api("/api/v1/legal/wecomapi-settings", {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      showAlert("第三方发送平台配置已保存");
      await renderWeComApiPlatform();
    } catch (error) {
      showAlert(error.message, "error");
    }
  });
  $("#check-wecomapi-login-btn").addEventListener("click", async () => {
    try {
      const status = await api("/api/v1/legal/wecomapi-settings/check-login", { method: "POST" });
      $("#wecomapi-status-result").innerHTML = renderWeComApiStatus(status);
    } catch (error) {
      showAlert(error.message, "error");
    }
  });
}

function renderRecognitionStatus(label, status) {
  if (!status) {
    return `
      <div class="platform-status-box">
        <span class="platform-status-dot warning"></span>
        <div><strong>${escapeHtml(label)}尚未检测</strong><p>保存配置后点击检测服务。</p></div>
      </div>
    `;
  }
  const statusClass = status.available ? "success" : "warn";
  const dotClass = status.available ? "online" : "error";
  return `
    <div class="platform-status-box ${statusClass}">
      <span class="platform-status-dot ${dotClass}"></span>
      <div>
        <strong>${escapeHtml(label)}${status.available ? "可用" : "不可用"}</strong>
        <p>${escapeHtml(status.message || "未返回状态")}</p>
      </div>
    </div>
  `;
}

async function renderRecognitionSettings(initialStatus = null) {
  const settings = await api("/api/v1/legal/recognition-settings");
  const ocrReady = settings.ocr_provider === "tencent" && settings.has_tencent_secret_id && settings.has_tencent_secret_key;
  const llmReady = settings.extraction_mode === "llm" && settings.has_llm_api_key && settings.llm_base_url && settings.llm_model;
  $("#content").innerHTML = `
    <section class="platform-console">
      <header class="platform-hero">
        <div class="platform-hero-main">
          <div class="platform-hero-mark">AI</div>
          <div>
            <h2>文书识别与结构化</h2>
            <div class="platform-hero-meta">
              <span class="platform-pill ${ocrReady ? "ready" : "warn"}">OCR：${escapeHtml(settings.ocr_provider)}</span>
              <span class="platform-pill ${llmReady ? "live" : "warn"}">结构化：${escapeHtml(settings.extraction_mode)}</span>
            </div>
          </div>
        </div>
        <div class="platform-hero-actions">
          <button id="check-recognition-btn" type="button">检测服务</button>
        </div>
      </header>
      <div class="platform-body">
        <div class="grid cols-2 recognition-status-grid">
          ${renderRecognitionStatus("OCR 服务", initialStatus && initialStatus.ocr)}
          ${renderRecognitionStatus("AI 模型", initialStatus && initialStatus.llm)}
        </div>
        <form id="recognition-settings-form" class="recognition-settings-form">
          <section class="platform-settings-card">
            <div class="platform-section-head">
              <div><h3>腾讯 OCR</h3><p>负责把图片和 PDF 转成原始文字；云密钥由独立 OCR 服务隔离管理。</p></div>
              <span class="platform-security-note">${ocrReady ? "服务凭证已配置" : "服务凭证待配置"}</span>
            </div>
            <div class="form-grid platform-form">
              <div class="field">
                <label>OCR 提供商</label>
                <select name="ocr_provider">
                  ${["tencent", "aliyun", "local_text", "mock"].map((value) => `<option value="${value}" ${settings.ocr_provider === value ? "selected" : ""}>${value}</option>`).join("")}
                </select>
              </div>
              <div class="field wide">
                <label>OCR Sidecar 地址</label>
                <input name="ocr_sidecar_url" maxlength="255" value="${escapeHtml(settings.ocr_sidecar_url || "")}" placeholder="http://127.0.0.1:9002" />
              </div>
              <div class="field wide service-managed-note">
                OCR SecretId、SecretKey、区域和 PDF 页数保留在独立服务的受保护配置中，网页只读取可用状态。
              </div>
            </div>
          </section>
          <section class="platform-settings-card recognition-ai-card">
            <div class="platform-section-head">
              <div><h3>AI 结构化</h3><p>从 OCR 文字中提取案号、当事人、金额、日期和材料类型。</p></div>
              <span class="platform-security-note">低置信度进入人工复核</span>
            </div>
            <div class="form-grid platform-form">
              <div class="field">
                <label>抽取模式</label>
                <select name="extraction_mode">
                  <option value="llm" ${settings.extraction_mode === "llm" ? "selected" : ""}>AI + 规则校验</option>
                  <option value="regex" ${settings.extraction_mode === "regex" ? "selected" : ""}>仅规则</option>
                </select>
              </div>
              <div class="field">
                <label>模型名称</label>
                <input name="llm_model" maxlength="128" value="${escapeHtml(settings.llm_model || "")}" placeholder="deepseek-chat" />
              </div>
              <div class="field wide">
                <label>模型 API 地址</label>
                <input name="llm_base_url" maxlength="255" value="${escapeHtml(settings.llm_base_url || "")}" placeholder="https://api.deepseek.com/v1" />
              </div>
              <div class="field wide">
                <label>API Key${settings.has_llm_api_key ? "（已配置，留空不修改）" : ""}</label>
                <input name="llm_api_key" type="password" maxlength="512" autocomplete="off" placeholder="${settings.has_llm_api_key ? settings.secret_mask : "模型 API Key"}" />
              </div>
              <div class="field">
                <label>置信度阈值</label>
                <input name="llm_min_confidence" type="number" min="0" max="1" step="0.05" value="${escapeHtml(settings.llm_min_confidence)}" />
              </div>
              <div class="field">
                <label>超时时间（秒）</label>
                <input name="llm_timeout_seconds" type="number" min="1" max="120" value="${escapeHtml(settings.llm_timeout_seconds)}" />
              </div>
              <div class="field">
                <label>最大文本长度</label>
                <input name="llm_max_text_length" type="number" min="1000" max="100000" value="${escapeHtml(settings.llm_max_text_length)}" />
              </div>
              <label class="field check-field">
                <span>模型失败时回退规则</span>
                <input name="llm_fallback_to_regex" type="checkbox" ${settings.llm_fallback_to_regex ? "checked" : ""} />
              </label>
              <div class="field form-actions platform-form-actions wide">
                <button type="submit">保存配置</button>
                <button type="reset" class="ghost">恢复当前值</button>
              </div>
            </div>
          </section>
          <section class="platform-settings-card">
            <div class="platform-section-head">
              <div><h3>法律资料留存</h3><p>默认永久保留；启用后仅清理符合期限和复核状态的本地文件，业务记录与审计继续保留。</p></div>
              <span class="platform-security-note">${settings.data_retention_enabled ? "自动清理已启用" : "自动清理未启用"}</span>
            </div>
            <div class="form-grid platform-form">
              <label class="field check-field">
                <span>启用自动清理</span>
                <input name="data_retention_enabled" type="checkbox" ${settings.data_retention_enabled ? "checked" : ""} />
              </label>
              <div class="field">
                <label>保留天数</label>
                <input name="data_retention_days" type="number" min="30" max="36500" value="${escapeHtml(settings.data_retention_days)}" />
              </div>
              <div class="field wide">
                <label>允许清理的复核状态</label>
                <select name="data_retention_review_statuses" multiple size="4">
                  ${[["rejected","已驳回"],["approved","已批准"],["corrected","已更正"],["not_required","无需复核"]].map(([value,label]) => `<option value="${value}" ${(settings.data_retention_review_statuses || []).includes(value) ? "selected" : ""}>${label}</option>`).join("")}
                </select>
              </div>
              <div class="field form-actions platform-form-actions wide">
                <button type="submit">保存配置</button>
                <button type="reset" class="ghost">恢复当前值</button>
              </div>
            </div>
          </section>
        </form>
      </div>
    </section>
  `;

  $("#recognition-settings-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const formData = new FormData(form);
    const payload = {
      ocr_provider: formData.get("ocr_provider"),
      ocr_sidecar_url: formData.get("ocr_sidecar_url"),
      extraction_mode: formData.get("extraction_mode"),
      llm_base_url: formData.get("llm_base_url"),
      llm_model: formData.get("llm_model"),
      llm_timeout_seconds: Number(formData.get("llm_timeout_seconds")),
      llm_max_text_length: Number(formData.get("llm_max_text_length")),
      llm_min_confidence: Number(formData.get("llm_min_confidence")),
      llm_fallback_to_regex: formData.get("llm_fallback_to_regex") === "on",
      data_retention_enabled: formData.get("data_retention_enabled") === "on",
      data_retention_days: Number(formData.get("data_retention_days")),
      data_retention_review_statuses: formData.getAll("data_retention_review_statuses"),
    };
    for (const secretField of ["llm_api_key"]) {
      const value = String(formData.get(secretField) || "").trim();
      if (value) payload[secretField] = value;
    }
    try {
      await api("/api/v1/legal/recognition-settings", { method: "PUT", body: JSON.stringify(payload) });
      showAlert("识别与 AI 配置已保存");
      await renderRecognitionSettings();
    } catch (error) {
      showAlert(error.message, "error");
    }
  });

  $("#check-recognition-btn").addEventListener("click", async () => {
    const button = $("#check-recognition-btn");
    button.disabled = true;
    button.textContent = "检测中...";
    try {
      const status = await api("/api/v1/legal/recognition-settings/check", { method: "POST" });
      showAlert(status.ocr.available && status.llm.available ? "OCR 与 AI 服务均可用" : "检测完成，请查看服务状态");
      await renderRecognitionSettings(status);
    } catch (error) {
      showAlert(error.message, "error");
      button.disabled = false;
      button.textContent = "检测服务";
    }
  });
}

function archiveGroupDatalist(groups) {
  return `
    <datalist id="case-group-options">
      ${groups
        .map((group) => {
          const name = group.display_name || "未命名群";
          return `<option value="${escapeHtml(group.room_id)}" label="${escapeHtml(`${name} · ${group.status}`)}"></option>`;
        })
        .join("")}
    </datalist>
  `;
}

function caseGroupLabel(groupId, groups) {
  const group = groups.find((item) => item.room_id === groupId);
  if (!group) return `<span class="mono">${escapeHtml(groupId)}</span>`;
  return `<div class="case-group-cell"><strong>${escapeHtml(group.display_name || "未命名群")}</strong><span class="mono muted">${escapeHtml(group.room_id)}</span></div>`;
}

function caseForm() {
  return `
    <form id="case-form" class="form-grid">
      <div class="field"><label>案号</label><input name="case_no" required placeholder="(2026)黔0281民初3118号" /></div>
      <div class="field"><label>债务人</label><input name="debtor_name" required /></div>
      <div class="field"><label>归档群</label><input name="group_id" list="case-group-options" required placeholder="选择群名称或输入 roomid" /></div>
      <div class="field"><label>到期日</label><input name="due_date" type="date" required /></div>
      <div class="field"><label>总金额</label><input name="total_amount" type="number" step="0.01" value="0.00" /></div>
      <div class="field"><label>租户 ID</label><input name="tenant_id" /></div>
      <div class="field"><label>债务人企微 ID</label><input name="debtor_wecom_userid" /></div>
      <div class="field"><label>律师企微 ID</label><input name="lawyer_wecom_userid" /></div>
      <div class="field"><label>&nbsp;</label><button type="submit">创建案件</button></div>
    </form>
  `;
}

function caseEditForm(item) {
  return `
    <form id="case-edit-form" class="form-grid" data-case-id="${item.id}">
      <div class="field"><label>案号</label><input value="${escapeHtml(item.case_no)}" disabled /></div>
      <div class="field"><label>债务人</label><input name="debtor_name" required maxlength="128" value="${escapeHtml(item.debtor_name)}" /></div>
      <div class="field"><label>归档群</label><input name="group_id" list="case-group-options" required maxlength="128" value="${escapeHtml(item.group_id)}" /></div>
      <div class="field"><label>到期日</label><input name="due_date" type="date" required value="${escapeHtml(item.due_date)}" /></div>
      <div class="field"><label>总金额</label><input name="total_amount" type="number" min="${escapeHtml(item.paid_amount || 0)}" step="0.01" required value="${escapeHtml(item.total_amount)}" /></div>
      <div class="field"><label>所属客户 ID</label><input name="tenant_id" maxlength="128" value="${escapeHtml(item.tenant_id || "")}" /></div>
      <div class="field"><label>债务人企微 ID</label><input name="debtor_wecom_userid" maxlength="128" value="${escapeHtml(item.debtor_wecom_userid || "")}" /></div>
      <div class="field"><label>法务企微 ID</label><input name="lawyer_wecom_userid" maxlength="128" value="${escapeHtml(item.lawyer_wecom_userid || "")}" /></div>
      <div class="field form-actions"><button type="submit">保存绑定</button><button id="cancel-case-edit" class="ghost" type="button">取消</button></div>
    </form>
  `;
}

function caseCandidateItem(item, groups) {
  const editing = state.editingCandidateId === item.id;
  const confidence = item.confidence === null || item.confidence === undefined ? "-" : `${Math.round(Number(item.confidence) * 100)}%`;
  const sourceLabel = item.source_type.startsWith("media") ? "附件 OCR" : "企业微信消息";
  if (!editing) {
    return `
      <article class="case-candidate-item">
        <div class="case-candidate-main">
          <div class="case-candidate-title"><strong>${escapeHtml(item.case_no)}</strong>${badge("pending")}</div>
          <div class="case-candidate-meta">
            <span>债务人：${escapeHtml(item.debtor_name || "待补充")}</span>
            <span>识别金额：${escapeHtml(item.total_amount ?? "-")}</span>
            <span>来源：${escapeHtml(sourceLabel)}</span>
            <span>置信度：${escapeHtml(confidence)}</span>
            <span>发现 ${escapeHtml(item.occurrence_count)} 次</span>
          </div>
          <div class="case-candidate-group">${caseGroupLabel(item.group_id, groups)}</div>
        </div>
        <div class="case-candidate-actions">
          ${item.source_media_file_id ? `<button type="button" class="ghost small" data-open-candidate-media="${item.source_media_file_id}">查看材料</button>` : ""}
          <button type="button" class="small" data-edit-candidate="${item.id}">确认建案</button>
          <button type="button" class="ghost small danger-text" data-dismiss-candidate="${item.id}">忽略</button>
        </div>
      </article>
    `;
  }
  return `
    <article class="case-candidate-item editing">
      <form class="case-candidate-form form-grid" data-confirm-candidate="${item.id}">
        <div class="field"><label>识别案号</label><input value="${escapeHtml(item.case_no)}" disabled /></div>
        <div class="field"><label>债务人</label><input name="debtor_name" required maxlength="128" value="${escapeHtml(item.debtor_name || "")}" /></div>
        <div class="field"><label>归档群</label><input name="group_id" list="case-group-options" required maxlength="128" value="${escapeHtml(item.group_id)}" /></div>
        <div class="field"><label>到期日</label><input name="due_date" type="date" required value="${escapeHtml(item.due_date || "")}" /></div>
        <div class="field"><label>总金额</label><input name="total_amount" type="number" min="0" step="0.01" required value="${escapeHtml(item.total_amount ?? "0.00")}" /></div>
        <div class="field"><label>所属客户 ID</label><input name="tenant_id" maxlength="128" value="${escapeHtml(item.tenant_id || "")}" /></div>
        <div class="field"><label>债务人企微 ID</label><input name="debtor_wecom_userid" maxlength="128" /></div>
        <div class="field"><label>法务企微 ID</label><input name="lawyer_wecom_userid" maxlength="128" /></div>
        <div class="field form-actions candidate-form-actions"><button type="submit">确认并建案</button><button type="button" class="ghost" data-cancel-candidate>取消</button></div>
      </form>
    </article>
  `;
}

async function renderCases() {
  const [data, candidatesData, archiveGroupsData] = await Promise.all([
    api("/api/v1/legal/cases?limit=50"),
    api("/api/v1/legal/cases/candidates?status=pending&page_size=100"),
    api("/api/v1/legal/wecom-archive/groups?page_size=200"),
  ]);
  const cases = data.items || [];
  const candidates = candidatesData.items || [];
  const archiveGroups = archiveGroupsData.items || [];
  const editingCase = cases.find((item) => item.id === state.editingCaseId);
  if (state.editingCaseId && !editingCase) state.editingCaseId = null;
  $("#content").innerHTML = `
    <div class="grid">
      ${archiveGroupDatalist(archiveGroups)}
      <section class="case-candidates">
        <header class="case-section-header">
          <div><h2>待确认案件</h2><p>系统从企业微信消息和附件中自动识别，补齐必要信息后建立正式案件。</p></div>
          <div class="case-section-actions"><span class="case-candidate-count">${candidates.length}</span><button id="scan-case-candidates-btn" type="button" class="ghost small">扫描现有资料</button></div>
        </header>
        <div class="case-candidate-list">
          ${candidates.length ? candidates.map((item) => caseCandidateItem(item, archiveGroups)).join("") : '<div class="workbench-empty"><strong>当前没有待确认案件</strong><span>识别到新的案号后会自动出现在这里。</span></div>'}
        </div>
      </section>
      ${panel("创建案件", caseForm())}
      ${editingCase ? panel(`编辑案件 · ${escapeHtml(editingCase.case_no)}`, caseEditForm(editingCase)) : ""}
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
            { label: "归档群", render: (row) => caseGroupLabel(row.group_id, archiveGroups) },
            { label: "债务人企微 ID", key: "debtor_wecom_userid" },
            { label: "法务企微 ID", key: "lawyer_wecom_userid" },
            { label: "操作", render: (row) => `<button class="small" data-open-case="${row.id}">工作台</button> <button class="small ghost" data-edit-case="${row.id}">编辑</button>` },
          ],
          cases,
        ),
        '<button id="scan-status-btn" class="ghost">扫描状态</button>',
      )}
    </div>
  `;
  document.querySelectorAll("[data-edit-candidate]").forEach((button) => {
    button.addEventListener("click", () => {
      state.editingCandidateId = Number(button.dataset.editCandidate);
      renderCases();
    });
  });
  $("#scan-case-candidates-btn").addEventListener("click", async () => {
    const result = await api("/api/v1/legal/cases/candidates/scan", { method: "POST", body: "{}" });
    showAlert(`扫描完成：检查附件 ${result.scanned_media} 条、消息 ${result.scanned_messages} 条，新增候选 ${result.created_candidates} 个`);
    renderCases();
  });
  document.querySelectorAll("[data-cancel-candidate]").forEach((button) => {
    button.addEventListener("click", () => {
      state.editingCandidateId = null;
      renderCases();
    });
  });
  document.querySelectorAll("[data-confirm-candidate]").forEach((form) => {
    form.addEventListener("submit", submitCaseCandidate);
  });
  document.querySelectorAll("[data-dismiss-candidate]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (!window.confirm("确定忽略这个候选案件吗？后续相同案号不会再次进入待确认列表。")) return;
      await api(`/api/v1/legal/cases/candidates/${button.dataset.dismissCandidate}/dismiss`, { method: "POST", body: "{}" });
      showAlert("候选案件已忽略");
      renderCases();
    });
  });
  document.querySelectorAll("[data-open-candidate-media]").forEach((button) => {
    button.addEventListener("click", () => {
      state.reviewStatusFilter = "pending";
      state.selectedReviewId = Number(button.dataset.openCandidateMedia);
      setView("ocr-reviews");
    });
  });
  $("#case-form").addEventListener("submit", submitCase);
  document.querySelectorAll("[data-edit-case]").forEach((button) => {
    button.addEventListener("click", () => {
      state.editingCaseId = Number(button.dataset.editCase);
      renderCases();
    });
  });
  document.querySelectorAll("[data-open-case]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedCaseId = Number(button.dataset.openCase);
      setView("case-workspace");
    });
  });
  if (editingCase) {
    $("#cancel-case-edit").addEventListener("click", () => {
      state.editingCaseId = null;
      renderCases();
    });
    $("#case-edit-form").addEventListener("submit", submitCaseUpdate);
  }
  $("#scan-status-btn").addEventListener("click", async () => {
    await api("/api/v1/legal/cases/scan-status", { method: "POST", body: "{}" });
    showAlert("案件状态扫描完成");
    renderCases();
  });
}

async function submitCaseCandidate(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = Object.fromEntries(new FormData(form).entries());
  for (const key of ["tenant_id", "debtor_wecom_userid", "lawyer_wecom_userid"]) {
    if (payload[key] === "") payload[key] = null;
  }
  const result = await api(`/api/v1/legal/cases/candidates/${form.dataset.confirmCandidate}/confirm`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  state.editingCandidateId = null;
  const linked = Number(result.linked_media_files || 0) + Number(result.linked_events || 0);
  showAlert(`案件 ${result.case.case_no} 已建立，关联历史材料 ${linked} 条`);
  renderCases();
}

async function submitCaseUpdate(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const payload = Object.fromEntries(new FormData(form).entries());
  for (const key of ["tenant_id", "debtor_wecom_userid", "lawyer_wecom_userid"]) {
    if (payload[key] === "") payload[key] = null;
  }
  const result = await api(`/api/v1/legal/cases/${form.dataset.caseId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
  state.editingCaseId = null;
  const linked = Number(result.linked_media_files || 0) + Number(result.linked_events || 0);
  const suffix = result.backfill_skipped_reason
    ? `；${result.backfill_skipped_reason}`
    : `；关联历史材料 ${linked} 条，更新待发送提醒 ${result.updated_pending_reminders || 0} 条`;
  showAlert(`案件绑定已保存${suffix}`);
  renderCases();
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
  $("#content").innerHTML = `
    ${panel(
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
    )}
    ${panel(
      "企业微信归档 + OCR 开发回放",
      `
      <div style="margin-bottom:12px"><button id="archive-demo-btn" class="ghost">一键生成演示数据</button></div>
      <form id="archive-ocr-form" class="form-grid">
        <div class="field"><label>群 ID</label><input name="roomid" required value="group_001" /></div>
        <div class="field"><label>发送人 ID</label><input name="from" required value="user_001" /></div>
        <div class="field"><label>消息 ID</label><input name="msgid" required value="msg_dev_001" /></div>
        <div class="field"><label>文件名</label><input name="filename" required value="判决书.pdf" /></div>
        <div class="field"><label>序号 seq</label><input name="seq" type="number" value="1001" /></div>
        <div class="field wide"><label>OCR 文本</label><textarea name="ocr_text" placeholder="民事判决书&#10;案号：(2026)黔0281民初3118号&#10;原告：李四&#10;被告：张三"></textarea></div>
        <div class="field"><button type="submit">回放并处理 OCR</button></div>
      </form>
      <pre id="archive-ocr-result" class="mono muted"></pre>
      `,
    )}
  `;
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
  $("#archive-ocr-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const form = Object.fromEntries(new FormData(event.currentTarget).entries());
    const msgid = form.msgid;
    const payload = {
      messages: [
        {
          seq: Number(form.seq || 0),
          msgid,
          roomid: form.roomid,
          from: form.from,
          msgtype: "file",
          file: { filename: form.filename, md5sum: "dev", filesize: 100 },
          msgtime: Date.now(),
        },
      ],
      ocr_text_by_msgid: { [msgid]: form.ocr_text || "" },
    };
    const result = await api("/api/v1/legal/wecom-archive/replay-with-ocr", { method: "POST", body: JSON.stringify(payload) });
    $("#archive-ocr-result").textContent = JSON.stringify(result, null, 2);
    showAlert("归档回放和 OCR 处理完成");
  });
  $("#archive-demo-btn").addEventListener("click", async () => {
    const result = await api("/api/v1/legal/wecom-archive/replay-demo", { method: "POST", body: "{}" });
    $("#archive-ocr-result").textContent = JSON.stringify(result, null, 2);
    showAlert("演示数据已生成");
  });
}

function archiveGroupStatusOptions(selected) {
  const options = [
    ["discovered", "待确认"],
    ["enabled", "已启用"],
    ["disabled", "已停用"],
  ];
  return options
    .map(([value, label]) => `<option value="${value}" ${selected === value ? "selected" : ""}>${label}</option>`)
    .join("");
}

function archiveGroupTypeOptions(selected) {
  return [
    ["merchant", "商家群"],
    ["debtor", "债务人群"],
    ["internal", "内部群"],
    ["other", "其他"],
  ]
    .map(([value, label]) => `<option value="${value}" ${selected === value ? "selected" : ""}>${label}</option>`)
    .join("");
}

function groupFeatureInputs(features = {}) {
  const options = [
    ["ocr", "OCR"],
    ["document_sync", "文书同步"],
    ["payment_tracking", "缴费跟踪"],
    ["case_reminders", "案件提醒"],
    ["question_timeout", "提问超时"],
  ];
  return `<div class="feature-checks">${options.map(([key, label]) => `<label><input type="checkbox" data-feature="${key}" ${features[key] !== false ? "checked" : ""} />${label}</label>`).join("")}</div>`;
}

async function renderArchiveGroups() {
  const data = await api("/api/v1/legal/wecom-archive/groups?page_size=200");
  const groups = data.items || [];
  const counts = groups.reduce(
    (result, group) => {
      result[group.status] = (result[group.status] || 0) + 1;
      return result;
    },
    { discovered: 0, enabled: 0, disabled: 0 },
  );
  const callbackUrl = `${window.location.origin}/api/v1/wecomapi/callback`;
  const platformGroups = state.wecomPlatformGroups || [];
  const platformGroupOptions = platformGroups
    .map((room) => `<option value="${escapeHtml(room.room_id)}">${escapeHtml(room.room_name || "未命名群")} · ${escapeHtml(room.member_count ?? "-")} 人</option>`)
    .join("");
  $("#content").innerHTML = `
    <div class="grid cols-3">
      <div class="panel stat"><div class="stat-label">待确认</div><div class="stat-value status-warning">${counts.discovered}</div></div>
      <div class="panel stat"><div class="stat-label">已启用</div><div class="stat-value status-ok">${counts.enabled}</div></div>
      <div class="panel stat"><div class="stat-label">已停用</div><div class="stat-value">${counts.disabled}</div></div>
    </div>
    <div class="integration-note">
      <div>
        <div class="integration-note-title">第三方 wecomapi 发送平台</div>
        <div class="integration-note-body">平台接口使用 <span class="mono">https://manager.wecomapi.com/wecom/finder/api</span>。发送目标请填写平台返回的群 <span class="mono">toId/roomId</span>，不要填写会话存档的 <span class="mono">wr...</span> roomid。</div>
      </div>
      <div class="callback-url-block">
        <span>消息回调地址</span>
        <input class="mono" readonly value="${escapeHtml(callbackUrl)}" />
        <button id="copy-wecomapi-callback-btn" type="button" class="small ghost">复制</button>
      </div>
    </div>
    <div class="grid archive-group-grid">
      ${panel(
        "登记法务群",
        `
        <form id="archive-group-form" class="form-grid">
          <div class="field"><label>会话存档 roomid</label><input name="room_id" required maxlength="128" placeholder="wrxxxxxxxx" /></div>
          <div class="field"><label>平台群 ID（toId/roomId）</label><input name="wecomapi_room_id" list="wecomapi-room-options" maxlength="128" placeholder="同步后可选择平台群" /></div>
          <div class="field"><label>显示名称</label><input name="display_name" maxlength="255" /></div>
          <div class="field"><label>所属客户 ID</label><input name="tenant_id" maxlength="128" /></div>
          <div class="field"><label>状态</label><select name="status">${archiveGroupStatusOptions("enabled")}</select></div>
          <div class="field"><label>群类型</label><select name="group_type">${archiveGroupTypeOptions("other")}</select></div>
          <div class="field"><label>内部人员 ID</label><input name="internal_userids" placeholder="多个 ID 用逗号分隔" /></div>
          <div class="field"><label>告警人员 ID</label><input name="alert_userids" placeholder="多个 ID 用逗号分隔" /></div>
          <div class="field"><label>提问超时（分钟）</label><input name="question_timeout_minutes" type="number" min="1" max="1440" value="5" /></div>
          <div class="field field-command"><button type="submit">登记</button></div>
        </form>
        `,
        '<div class="panel-actions"><button id="sync-platform-groups-btn" type="button" class="ghost">同步平台群资料</button><button id="discover-groups-btn" type="button" class="ghost">拉取会话存档</button></div>',
      )}
      ${panel(
        "wecomapi 平台群",
        platformGroups.length
          ? table(
              [
                { label: "群名称", render: (room) => escapeHtml(room.room_name || "未命名群") },
                { label: "成员数", render: (room) => escapeHtml(room.member_count ?? "-") },
                { label: "群主 ID", render: (room) => `<span class="mono">${escapeHtml(room.owner_userid || "-")}</span>` },
                { label: "平台群 ID", render: (room) => `<span class="mono">${escapeHtml(room.room_id)}</span>` },
              ],
              platformGroups,
            )
          : '<div class="platform-groups-empty">点击“同步平台群资料”获取当前账号的群列表，再将平台群 ID 填入下方发送映射。</div>',
        `<span class="panel-meta">${platformGroups.length ? `本次获取 ${platformGroups.length} 个群` : "尚未同步"}</span>`,
      )}
      ${panel(
        "生成群名识别消息",
        `
        <form id="identify-group-form" class="form-grid">
          <div class="field"><label>目标群名称</label><input name="display_name" required maxlength="64" placeholder="致和法务执行群" /></div>
          <div class="field wide-command"><label>特殊消息</label><input id="identify-message-output" class="mono" readonly value="#群名识别群" /></div>
          <div class="field field-command"><button type="submit">复制消息</button></div>
        </form>
        `,
      )}
      ${panel(
        "群聊发送映射",
        table(
          [
            { label: "会话存档 roomid", render: (row) => `<span class="mono room-id-cell" title="${escapeHtml(row.room_id)}">${escapeHtml(row.room_id)}</span>` },
            {
              label: "平台群 ID",
              render: (row) => `<input class="compact-input mono" data-field="wecomapi_room_id" list="wecomapi-room-options" value="${escapeHtml(row.wecomapi_room_id || "")}" maxlength="128" placeholder="同步后选择平台群" />`,
            },
            {
              label: "显示名称",
              render: (row) => `<input class="compact-input" data-field="display_name" value="${escapeHtml(row.display_name || "")}" maxlength="255" />`,
            },
            {
              label: "所属客户 ID",
              render: (row) => `<input class="compact-input" data-field="tenant_id" value="${escapeHtml(row.tenant_id || "")}" maxlength="128" />`,
            },
            {
              label: "状态",
              render: (row) => `<select class="compact-input" data-field="status">${archiveGroupStatusOptions(row.status)}</select>`,
            },
            {
              label: "群类型",
              render: (row) => `<select class="compact-input" data-field="group_type">${archiveGroupTypeOptions(row.group_type)}</select>`,
            },
            {
              label: "内部/告警人员",
              render: (row) => `<input class="compact-input" data-field="internal_userids" value="${escapeHtml((row.internal_userids || []).join(","))}" placeholder="内部人员" /><input class="compact-input compact-stack" data-field="alert_userids" value="${escapeHtml((row.alert_userids || []).join(","))}" placeholder="告警人员" />`,
            },
            {
              label: "超时",
              render: (row) => `<input class="compact-input compact-number" type="number" min="1" max="1440" data-field="question_timeout_minutes" value="${escapeHtml(row.question_timeout_minutes || 5)}" />`,
            },
            { label: "群功能", render: (row) => groupFeatureInputs(row.features) },
            { label: "发现消息", key: "seen_message_count" },
            { label: "最后发现", key: "last_seen_at" },
            {
              label: "操作",
              render: (row) => `<div class="mapping-row-actions"><button class="small" data-save-archive-group="${escapeHtml(row.room_id)}">保存</button><button class="small ghost" data-test-send-group="${escapeHtml(row.room_id)}" ${row.wecomapi_room_id ? "" : "disabled"}>测试发送</button></div>`,
            },
          ],
          groups,
          "archive-mapping-table",
        ),
      )}
    </div>
    <datalist id="wecomapi-room-options">${platformGroupOptions}</datalist>
  `;

  $("#copy-wecomapi-callback-btn").addEventListener("click", async () => {
    await navigator.clipboard.writeText(callbackUrl);
    showAlert("回调地址已复制");
  });

  $("#archive-group-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(event.currentTarget).entries());
    for (const key of ["wecomapi_room_id", "display_name", "tenant_id"]) {
      if (!payload[key]) payload[key] = null;
    }
    payload.internal_userids = payload.internal_userids ? payload.internal_userids.split(/[,，]/).map((value) => value.trim()).filter(Boolean) : [];
    payload.alert_userids = payload.alert_userids ? payload.alert_userids.split(/[,，]/).map((value) => value.trim()).filter(Boolean) : [];
    payload.question_timeout_minutes = Number(payload.question_timeout_minutes || 5);
    await api("/api/v1/legal/wecom-archive/groups", { method: "POST", body: JSON.stringify(payload) });
    showAlert("法务群已登记");
    renderArchiveGroups();
  });

  const identifyForm = $("#identify-group-form");
  const identifyNameInput = identifyForm.elements.display_name;
  const identifyOutput = $("#identify-message-output");
  identifyNameInput.addEventListener("input", () => {
    const name = identifyNameInput.value.trim().replaceAll(/\s+/g, " ");
    identifyOutput.value = name ? `#群名识别群 ${name}` : "#群名识别群";
  });
  identifyForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const message = identifyOutput.value;
    if (message === "#群名识别群") return;
    await navigator.clipboard.writeText(message);
    showAlert("识别消息已复制，可发送到目标企业微信群");
  });

  $("#discover-groups-btn").addEventListener("click", async () => {
    const result = await api("/api/v1/legal/wecom-archive/pull", { method: "POST", body: "{}" });
    showAlert(`拉取完成：发现 ${result.discovered} 个新群，识别 ${result.identified} 个群，跳过 ${result.skipped} 条非业务消息`);
    renderArchiveGroups();
  });

  $("#sync-platform-groups-btn").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      const result = await api("/api/v1/legal/wecomapi-settings/sync-groups", { method: "POST", body: "{}" });
      state.wecomPlatformGroups = result.rooms || [];
      showAlert(`平台群同步完成：获取 ${result.fetched} 个，已映射 ${result.mapped} 个，更新群名 ${result.updated} 个`);
      await renderArchiveGroups();
    } finally {
      button.disabled = false;
    }
  });

  document.querySelectorAll("[data-save-archive-group]").forEach((button) => {
    button.addEventListener("click", async () => {
      const row = button.closest("tr");
      const payload = {};
      row.querySelectorAll("[data-field]").forEach((field) => {
        payload[field.dataset.field] = field.value.trim() || null;
      });
      payload.internal_userids = payload.internal_userids ? payload.internal_userids.split(/[,，]/).map((value) => value.trim()).filter(Boolean) : [];
      payload.alert_userids = payload.alert_userids ? payload.alert_userids.split(/[,，]/).map((value) => value.trim()).filter(Boolean) : [];
      payload.question_timeout_minutes = Number(payload.question_timeout_minutes || 5);
      payload.features = {};
      row.querySelectorAll("[data-feature]").forEach((field) => {
        payload.features[field.dataset.feature] = field.checked;
      });
      await api(`/api/v1/legal/wecom-archive/groups/${encodeURIComponent(button.dataset.saveArchiveGroup)}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      showAlert("归档群配置已保存");
      renderArchiveGroups();
    });
  });

  document.querySelectorAll("[data-test-send-group]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (!window.confirm("确认向该企业微信群发送一条通道测试消息？")) return;
      button.disabled = true;
      try {
        const result = await api("/api/v1/legal/wecomapi-settings/test-send", {
          method: "POST",
          body: JSON.stringify({ room_id: button.dataset.testSendGroup }),
        });
        showAlert(`测试消息发送成功，通道：${result.mode}`);
      } finally {
        button.disabled = false;
      }
    });
  });
}

function reviewFieldValue(result, key) {
  const value = result && result[key];
  if (value === null || value === undefined) return "";
  if (key === "court_time" && typeof value === "string") return value.slice(0, 16);
  return String(value);
}

function reviewContextTimeline(review) {
  const analyzedMessages = review.context_messages || [];
  const availableMessages = review.available_context_messages || [];
  const messages = analyzedMessages.length ? analyzedMessages : availableMessages;
  if (!messages.length) return '<div class="context-empty">当前没有可用的相邻群聊文字或附件 OCR 摘要</div>';
  return `<div class="context-timeline">${messages
    .map(
      (message) => `
        <article class="context-message ${message.position === "after" ? "after" : "before"}">
          <header><span class="mono">${escapeHtml(message.sender_id || "未知发送人")}</span><time>${escapeHtml(message.received_at || "")}</time></header>
          <p>${escapeHtml(message.content || "")}</p>
        </article>`,
    )
    .join("")}</div>`;
}

function reviewDetail(review) {
  const result = review.final_result || review.ocr_result || {};
  const editable = review.review_status === "pending";
  const metadata = result.metadata || {};
  const fieldSources = metadata.field_sources || {};
  const analyzedContextCount = (review.context_messages || []).length;
  const availableContextCount = (review.available_context_messages || []).length;
  const contextIsSnapshot = analyzedContextCount > 0;
  const eventTypes = [
    ["judgment", "判决/调解/裁定"],
    ["court_notice", "开庭传票"],
    ["payment_notice", "缴费通知"],
    ["payment_screenshot", "付款完成"],
    ["keyword", "业务关键词"],
    ["unknown", "未知"],
  ];
  const documentTypes = ["", "判决书", "调解书", "裁定书", "开庭传票"];
  return `
    <div class="review-detail-header">
      <div><strong>${escapeHtml(review.original_filename || `媒体 ${review.media_file_id}`)}</strong><div class="muted mono">${escapeHtml(review.msg_id || "无消息 ID")}</div></div>
      <div class="review-header-actions">
        ${editable ? '<button type="button" class="ghost small" data-review-reanalyze>结合最新群聊重新分析</button>' : ""}
        ${badge(review.review_status)}
      </div>
    </div>
    <div class="review-detail-grid">
      <section class="review-preview"><div id="review-preview" class="preview-placeholder">加载预览中...</div></section>
      <section class="review-fields">
        <form id="review-form" data-media-id="${review.media_file_id}">
          <div class="form-grid review-form-grid">
            <div class="field"><label>案号 ${fieldSources.case_no ? `<span class="field-source">${escapeHtml(fieldSources.case_no)}</span>` : ""}</label><input name="case_no" value="${escapeHtml(reviewFieldValue(result, "case_no"))}" ${editable ? "" : "disabled"} /></div>
            <div class="field"><label>材料类型</label><select name="event_type" ${editable ? "" : "disabled"}>${eventTypes.map(([value, label]) => `<option value="${value}" ${result.event_type === value ? "selected" : ""}>${label}</option>`).join("")}</select></div>
            <div class="field"><label>文书类型</label><select name="document_type" ${editable ? "" : "disabled"}>${documentTypes.map((value) => `<option value="${value}" ${result.document_type === value ? "selected" : ""}>${value || "无"}</option>`).join("")}</select></div>
            <div class="field"><label>原告</label><input name="plaintiff" value="${escapeHtml(reviewFieldValue(result, "plaintiff"))}" ${editable ? "" : "disabled"} /></div>
            <div class="field"><label>被告</label><input name="defendant" value="${escapeHtml(reviewFieldValue(result, "defendant"))}" ${editable ? "" : "disabled"} /></div>
            <div class="field"><label>金额</label><input name="amount" type="number" min="0" step="0.01" value="${escapeHtml(reviewFieldValue(result, "amount"))}" ${editable ? "" : "disabled"} /></div>
            <div class="field"><label>开庭时间</label><input name="court_time" type="datetime-local" value="${escapeHtml(reviewFieldValue(result, "court_time"))}" ${editable ? "" : "disabled"} /></div>
            <div class="field wide"><label>复核备注</label><textarea name="note" ${editable ? "" : "disabled"}>${escapeHtml(review.review_note || "")}</textarea></div>
          </div>
          ${
            editable
              ? '<div class="review-actions"><button type="button" data-review-decision="approved">批准原结果</button><button type="button" class="ghost" data-review-decision="corrected">保存修正并执行</button><button type="button" class="danger-button" data-review-decision="rejected">驳回</button></div>'
              : `<div class="review-audit muted">复核人：${escapeHtml(review.reviewed_by || "-")} · 复核时间：${escapeHtml(review.reviewed_at || "-")} · 业务执行：${escapeHtml(review.business_applied_at || "未执行")}</div>`
          }
        </form>
        <div class="review-context-block">
          <div class="context-heading"><div><div class="field-label">${contextIsSnapshot ? "AI 分析使用的群聊上下文" : "当前可用于重新分析的群聊上下文"}</div><span>${contextIsSnapshot ? analyzedContextCount : availableContextCount} 条相邻消息</span></div>${contextIsSnapshot ? '<span class="context-used">已参与识别</span>' : availableContextCount ? '<span class="context-available">尚未参与当次识别</span>' : ""}</div>
          ${reviewContextTimeline(review)}
        </div>
        <div class="ocr-text-block"><div class="field-label">OCR 原文</div><pre>${escapeHtml(review.extracted_text || "无识别文本")}</pre></div>
      </section>
    </div>
  `;
}

async function loadReviewPreview(review) {
  const container = $("#review-preview");
  if (!container || !review.preview_url) {
    if (container) container.textContent = "无可预览文件";
    return;
  }
  if (state.reviewPreviewUrl) URL.revokeObjectURL(state.reviewPreviewUrl);
  const headers = state.apiKey ? { "X-API-Key": state.apiKey } : {};
  const response = await fetch(review.preview_url, { headers });
  if (!response.ok) {
    container.textContent = "预览加载失败";
    return;
  }
  state.reviewPreviewUrl = URL.createObjectURL(await response.blob());
  if ((review.mime_type || "").startsWith("image/")) {
    container.innerHTML = `<img src="${state.reviewPreviewUrl}" alt="待复核原图" />`;
  } else {
    container.innerHTML = `<iframe src="${state.reviewPreviewUrl}" title="待复核 PDF"></iframe>`;
  }
}

async function submitReviewDecision(review, decision) {
  const form = $("#review-form");
  const values = Object.fromEntries(new FormData(form).entries());
  const payload = { decision, note: values.note.trim() || null };
  if (decision === "rejected" && !payload.note) {
    showAlert("驳回时必须填写复核备注", "error");
    return;
  }
  if (decision === "corrected") {
    for (const key of ["case_no", "event_type", "document_type", "plaintiff", "defendant", "amount", "court_time"]) {
      if (values[key] !== "") payload[key] = values[key];
    }
  }
  const result = await api(`/api/v1/legal/ocr-reviews/${review.media_file_id}/decision`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
  showAlert(`复核完成：生成提醒 ${result.created_reminders} 条，取消提醒 ${result.cancelled_reminders} 条`);
  await renderOCRReviews();
}

async function reanalyzeReview(review, button) {
  button.disabled = true;
  button.textContent = "分析中...";
  try {
    await api(`/api/v1/legal/media-files/${review.media_file_id}/ocr`, { method: "POST" });
    showAlert("已结合最新群聊上下文重新分析");
    await renderOCRReviews();
  } catch (error) {
    button.disabled = false;
    button.textContent = "结合最新群聊重新分析";
    throw error;
  }
}

async function renderOCRReviews() {
  const query = state.reviewStatusFilter ? `?review_status=${encodeURIComponent(state.reviewStatusFilter)}&page_size=100` : "?page_size=100";
  const data = await api(`/api/v1/legal/ocr-reviews${query}`);
  const items = data.items || [];
  if (!items.some((item) => item.media_file_id === state.selectedReviewId)) {
    state.selectedReviewId = items[0] ? items[0].media_file_id : null;
  }
  const selectedSummary = items.find((item) => item.media_file_id === state.selectedReviewId);
  const selected = selectedSummary
    ? await api(`/api/v1/legal/ocr-reviews/${selectedSummary.media_file_id}`)
    : null;
  $("#content").innerHTML = `
    <div class="review-toolbar">
      <label for="review-status-filter">状态</label>
      <select id="review-status-filter">
        <option value="pending" ${state.reviewStatusFilter === "pending" ? "selected" : ""}>待复核</option>
        <option value="approved" ${state.reviewStatusFilter === "approved" ? "selected" : ""}>已批准</option>
        <option value="corrected" ${state.reviewStatusFilter === "corrected" ? "selected" : ""}>已修正</option>
        <option value="rejected" ${state.reviewStatusFilter === "rejected" ? "selected" : ""}>已驳回</option>
        <option value="" ${state.reviewStatusFilter === "" ? "selected" : ""}>全部</option>
      </select>
      <span class="muted">${items.length} 条</span>
    </div>
    <div class="review-workspace">
      <aside class="review-list-pane">
        ${
          items.length
            ? items
                .map(
                  (item) => `<button class="review-list-item ${item.media_file_id === state.selectedReviewId ? "active" : ""}" data-review-id="${item.media_file_id}"><span>${escapeHtml(item.original_filename || `媒体 ${item.media_file_id}`)}</span><small>${escapeHtml(item.ocr_result.event_type || "unknown")} · ${escapeHtml(item.updated_at)}</small></button>`,
                )
                .join("")
            : '<div class="empty-state">当前状态暂无材料</div>'
        }
      </aside>
      <main class="review-detail-pane">${selected ? reviewDetail(selected) : '<div class="empty-state">请选择待复核材料</div>'}</main>
    </div>
  `;
  $("#review-status-filter").addEventListener("change", (event) => {
    state.reviewStatusFilter = event.target.value;
    state.selectedReviewId = null;
    renderOCRReviews();
  });
  document.querySelectorAll("[data-review-id]").forEach((button) => {
    button.addEventListener("click", () => {
      state.selectedReviewId = Number(button.dataset.reviewId);
      renderOCRReviews();
    });
  });
  document.querySelectorAll("[data-review-decision]").forEach((button) => {
    button.addEventListener("click", () => submitReviewDecision(selected, button.dataset.reviewDecision));
  });
  const reanalyzeButton = document.querySelector("[data-review-reanalyze]");
  if (reanalyzeButton && selected) {
    reanalyzeButton.addEventListener("click", () => reanalyzeReview(selected, reanalyzeButton));
  }
  if (selected) await loadReviewPreview(selected);
}

async function renderReminders() {
  const [data, rulesData, groupsData] = await Promise.all([
    api("/api/v1/legal/reminders?limit=100"),
    api("/api/v1/legal/reminder-rules"),
    api("/api/v1/legal/wecom-archive/groups?status=enabled&page_size=200"),
  ]);
  const reminders = data.items || [];
  const rules = rulesData.items || [];
  const confirmedGroups = groupsData.items || [];
  const reminderGroupOptions = confirmedGroups
    .map((group) => `<option value="${escapeHtml(group.room_id)}">${escapeHtml(`${group.room_id}${group.display_name ? ` · ${group.display_name}` : ""}`)}</option>`)
    .join("");
  const editing = reminders.find((item) => item.id === state.editingReminderId);
  $("#content").innerHTML = `
    <div class="grid">
      ${panel(
        "创建自定义提醒",
        `<form id="custom-reminder-form" class="form-grid"><div class="field"><label>确认群</label><select id="custom-reminder-group" name="group_id" required><option value="">请选择群</option>${reminderGroupOptions}</select></div><div class="field"><label>@人员（可选）</label><select id="custom-reminder-target" name="target_userid" disabled><option value="">请先选择群</option></select></div><div class="field"><label>提醒时间</label><input name="remind_at" type="datetime-local" required /></div><div class="field wide"><label>提醒内容</label><textarea name="content" required></textarea></div><div class="field"><button type="submit" ${confirmedGroups.length ? "" : "disabled"}>创建提醒</button></div></form>`,
      )}
      ${
        editing
          ? panel(
              `编辑自定义提醒 · ${editing.id}`,
              `<form id="edit-reminder-form" class="form-grid"><div class="field"><label>确认群</label><input value="${escapeHtml(caseGroupLabel(editing.group_id, confirmedGroups).replace(/<[^>]*>/g, ""))}" disabled /></div><div class="field"><label>@人员（可选）</label><select id="edit-reminder-target" name="target_userid"><option value="">正在加载群成员...</option></select></div><div class="field"><label>提醒时间</label><input name="remind_at" type="datetime-local" value="${escapeHtml(editing.remind_at.slice(0, 16))}" required /></div><div class="field wide"><label>提醒内容</label><textarea name="content" required>${escapeHtml(editing.content)}</textarea></div><div class="field form-actions"><button type="submit">保存</button><button type="button" class="ghost" id="cancel-reminder-edit">取消</button></div></form>`,
            )
          : ""
      }
      ${panel(
        "新增提醒规则",
        `<form id="reminder-rule-form" class="form-grid"><div class="field"><label>规则名称</label><input name="name" required /></div><div class="field"><label>规则类型</label><select name="rule_type"><option value="repayment">还款</option><option value="default_upgrade">违约</option><option value="payment_tracking">缴费</option></select></div><div class="field"><label>偏移天数</label><input name="offset_days" type="number" min="0" max="365" value="0" required /></div><div class="field"><label>发送时间</label><input name="send_time" type="time" value="09:00" required /></div><div class="field"><label>目标角色</label><select name="target_role"><option value="debtor">债务人</option><option value="lawyer">法务</option><option value="both">双方</option></select></div><div class="field"><label>客户 ID（留空为全局）</label><input name="tenant_id" /></div><div class="field wide"><label>话术模板</label><textarea name="template" required>案件 {case_no} 请及时跟进。</textarea></div><div class="field"><button type="submit">新增规则</button></div></form>`,
      )}
      ${panel(
        "提醒规则",
        `${table(
          [
            { label: "名称", render: (row) => `<input class="compact-input" data-rule-field="name" value="${escapeHtml(row.name)}" />` },
            { label: "类型", key: "rule_type" },
            { label: "偏移天数", render: (row) => `<input class="compact-input compact-number" type="number" min="0" data-rule-field="offset_days" value="${row.offset_days}" />` },
            { label: "发送时间", render: (row) => `<input class="compact-input" type="time" data-rule-field="send_time" value="${escapeHtml(row.send_time)}" />` },
            { label: "目标", render: (row) => `<select class="compact-input" data-rule-field="target_role"><option value="debtor" ${row.target_role === "debtor" ? "selected" : ""}>债务人</option><option value="lawyer" ${row.target_role === "lawyer" ? "selected" : ""}>法务</option><option value="both" ${row.target_role === "both" ? "selected" : ""}>双方</option></select>` },
            { label: "话术模板", render: (row) => `<textarea class="compact-template" data-rule-field="template">${escapeHtml(row.template)}</textarea>` },
            { label: "启用", render: (row) => `<input type="checkbox" data-rule-field="enabled" ${row.enabled ? "checked" : ""} />` },
            { label: "操作", render: (row) => `<button class="small" data-save-rule="${row.id}">保存</button>` },
          ],
          rules,
        )}`,
      )}
      ${panel(
        "提醒列表",
        table(
          [
            { label: "ID", key: "id" },
            { label: "类型", key: "reminder_type" },
            { label: "状态", render: (row) => badge(row.status) },
            { label: "提醒时间", key: "remind_at" },
            { label: "群", render: (row) => caseGroupLabel(row.group_id, confirmedGroups) },
            { label: "@人员", render: (row) => row.target_userid ? `<span class="mono">${escapeHtml(row.target_userid)}</span>` : "-" },
            { label: "内容", key: "content" },
            { label: "取消原因", key: "cancel_reason" },
            { label: "操作", render: (row) => row.status === "pending" ? `<div class="row-actions">${row.reminder_type === "custom" ? `<button class="small ghost" data-edit-reminder="${row.id}">编辑</button>` : ""}<button class="small ghost" data-cancel-reminder="${row.id}">取消</button></div>` : "" },
          ],
          reminders,
        ),
        '<button id="run-due-btn">处理到期提醒</button>',
      )}
    </div>
  `;
  const loadMemberOptions = async (groupId, select, selectedUserId = "") => {
    if (!groupId) {
      select.innerHTML = '<option value="">请先选择群</option>';
      select.disabled = true;
      return;
    }
    select.disabled = true;
    select.innerHTML = '<option value="">正在加载群成员...</option>';
    try {
      const result = await api(`/api/v1/legal/wecomapi-settings/group-members?room_id=${encodeURIComponent(groupId)}`);
      const members = result.members || [];
      const selectedExists = members.some((member) => member.user_id === selectedUserId);
      select.innerHTML = `
        <option value="">不 @ 任何人</option>
        ${!selectedExists && selectedUserId ? `<option value="${escapeHtml(selectedUserId)}">${escapeHtml(`${selectedUserId}（当前值）`)}</option>` : ""}
        ${members.map((member) => `<option value="${escapeHtml(member.user_id)}">${escapeHtml(`${member.display_name} · ${member.user_id}`)}</option>`).join("")}
      `;
      select.value = selectedUserId || "";
      select.disabled = false;
      if (result.warning) showAlert(result.warning);
    } catch (error) {
      select.innerHTML = '<option value="">群成员加载失败</option>';
      select.disabled = true;
      showAlert(error.message, "error");
    }
  };
  $("#custom-reminder-group").addEventListener("change", (event) => {
    loadMemberOptions(event.target.value, $("#custom-reminder-target"));
  });
  $("#custom-reminder-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(event.currentTarget).entries());
    payload.target_userid = payload.target_userid || null;
    await api("/api/v1/legal/reminders/custom", { method: "POST", body: JSON.stringify(payload) });
    showAlert("自定义提醒已创建");
    renderReminders();
  });
  $("#reminder-rule-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(event.currentTarget).entries());
    payload.offset_days = Number(payload.offset_days);
    payload.tenant_id = payload.tenant_id || null;
    await api("/api/v1/legal/reminder-rules", { method: "POST", body: JSON.stringify(payload) });
    showAlert("提醒规则已新增");
    renderReminders();
  });
  if (editing) {
    await loadMemberOptions(editing.group_id, $("#edit-reminder-target"), editing.target_userid || "");
    $("#cancel-reminder-edit").addEventListener("click", () => { state.editingReminderId = null; renderReminders(); });
    $("#edit-reminder-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const payload = Object.fromEntries(new FormData(event.currentTarget).entries());
      payload.target_userid = payload.target_userid || null;
      await api(`/api/v1/legal/reminders/${editing.id}`, { method: "PATCH", body: JSON.stringify(payload) });
      state.editingReminderId = null;
      showAlert("自定义提醒已更新");
      renderReminders();
    });
  }
  document.querySelectorAll("[data-edit-reminder]").forEach((button) => button.addEventListener("click", () => { state.editingReminderId = Number(button.dataset.editReminder); renderReminders(); }));
  document.querySelectorAll("[data-cancel-reminder]").forEach((button) => button.addEventListener("click", async () => {
    await api(`/api/v1/legal/reminders/${button.dataset.cancelReminder}/cancel`, { method: "POST", body: JSON.stringify({ reason: "管理端人工取消" }) });
    showAlert("提醒已取消");
    renderReminders();
  }));
  document.querySelectorAll("[data-save-rule]").forEach((button) => button.addEventListener("click", async () => {
    const row = button.closest("tr");
    const payload = {};
    row.querySelectorAll("[data-rule-field]").forEach((field) => {
      payload[field.dataset.ruleField] = field.type === "checkbox" ? field.checked : field.value;
    });
    payload.offset_days = Number(payload.offset_days);
    const result = await api(`/api/v1/legal/reminder-rules/${button.dataset.saveRule}`, { method: "PATCH", body: JSON.stringify(payload) });
    showAlert(`规则已保存，重建待发送提醒 ${result.rebuilt_pending} 条`);
    renderReminders();
  }));
  $("#run-due-btn").addEventListener("click", async () => {
    const result = await api("/api/v1/legal/reminders/run-due", { method: "POST", body: "{}" });
    showAlert(`扫描完成：真实发送 ${result.sent}，Mock 模拟 ${result.simulated}，失败 ${result.failed}，重试 ${result.retrying}`);
    renderReminders();
  });
}

async function openProtectedMedia(url) {
  const target = window.open("", "_blank");
  try {
    const headers = state.apiKey ? { "X-API-Key": state.apiKey } : {};
    const response = await fetch(url, { headers });
    if (!response.ok) throw new Error("缴费截图加载失败");
    const objectUrl = URL.createObjectURL(await response.blob());
    if (target) target.location = objectUrl;
    else window.open(objectUrl, "_blank");
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 60000);
  } catch (error) {
    if (target) target.close();
    throw error;
  }
}

async function renderPaymentTrackings() {
  const data = await api("/api/v1/legal/payment-trackings?limit=200");
  const items = data.items || [];
  const statusText = { pending: "待支付", partial: "部分支付", paid: "已支付", overdue: "已逾期" };
  $("#content").innerHTML = `
    <section class="payment-tracking-view">
      <header class="case-section-header">
        <div><h2>缴费信息跟踪</h2><p>数据来自已确认的缴费通知、催促任务和付款凭证，剩余时间按截止日实时计算。</p></div>
        <span class="case-candidate-count">${data.total || 0}</span>
      </header>
      ${panel("缴费信息表", table([
        { label: "日期", key: "notice_date" },
        { label: "原告", key: "plaintiff" },
        { label: "被告", key: "defendant" },
        { label: "案号", render: (row) => `<button class="text-link" data-payment-case="${row.case_id}">${escapeHtml(row.case_no)}</button>` },
        { label: "缴费信息", render: (row) => row.payment_info ? `${escapeHtml(row.payment_info)}${Number.isFinite(Number(row.payment_info)) ? " 元" : ""}` : fmt(null) },
        { label: "支付情况", render: (row) => badge(statusText[row.payment_status] || row.payment_status) },
        { label: "跟踪情况", key: "tracking_status" },
        { label: "剩余缴费时间", key: "remaining_payment_time" },
        { label: "缴费截图上传", render: (row) => row.screenshot_url ? `<button class="small ghost" data-payment-screenshot="${escapeHtml(row.screenshot_url)}">查看截图</button>` : '<span class="muted">待上传</span>' },
      ], items, "payment-tracking-table"))}
    </section>`;
  document.querySelectorAll("[data-payment-case]").forEach((button) => button.addEventListener("click", () => {
    state.selectedCaseId = Number(button.dataset.paymentCase);
    setView("case-workspace");
  }));
  document.querySelectorAll("[data-payment-screenshot]").forEach((button) => button.addEventListener("click", () => {
    openProtectedMedia(button.dataset.paymentScreenshot).catch((error) => showAlert(error.message, "error"));
  }));
}

async function renderMerchantQuestions() {
  const data = await api("/api/v1/legal/merchant-questions?limit=200");
  const items = data.items || [];
  $("#content").innerHTML = panel(
    "提问记录",
    table(
      [
        { label: "状态", render: (row) => badge(row.status) },
        { label: "群", key: "group_id" },
        { label: "提问人", key: "sender_id" },
        { label: "内容", key: "content" },
        { label: "提问时间", key: "asked_at" },
        { label: "截止时间", key: "deadline_at" },
        { label: "告警人员", key: "assigned_userid" },
        { label: "操作", render: (row) => ["open", "timed_out"].includes(row.status) ? `<button class="small ghost" data-close-question="${row.id}">人工关闭</button>` : "" },
      ],
      items,
    ),
  );
  document.querySelectorAll("[data-close-question]").forEach((button) => button.addEventListener("click", async () => {
    await api(`/api/v1/legal/merchant-questions/${button.dataset.closeQuestion}/close`, { method: "POST", body: JSON.stringify({ reason: "管理端人工关闭" }) });
    showAlert("提问已关闭");
    renderMerchantQuestions();
  }));
}

async function renderSystemAlerts() {
  const data = await api("/api/v1/legal/system-alerts?page_size=200");
  const items = data.items || [];
  const openCount = items.filter((item) => item.status === "open").length;
  const acknowledgedCount = items.filter((item) => item.status === "acknowledged").length;
  const resolvedCount = items.filter((item) => item.status === "resolved").length;
  $("#content").innerHTML = `
    <div class="grid cols-3">
      <div class="panel stat"><div class="stat-label">待处理</div><div class="stat-value ${openCount ? "status-warning" : "status-ok"}">${openCount}</div></div>
      <div class="panel stat"><div class="stat-label">已确认</div><div class="stat-value">${acknowledgedCount}</div></div>
      <div class="panel stat"><div class="stat-label">已恢复</div><div class="stat-value status-ok">${resolvedCount}</div></div>
    </div>
    <div style="margin-top:14px">
      ${panel(
        "告警记录",
        table(
          [
            { label: "级别", render: (row) => badge(row.severity) },
            { label: "状态", render: (row) => badge(row.status) },
            { label: "告警", render: (row) => `<strong>${escapeHtml(row.title)}</strong><div class="muted">${escapeHtml(row.message)}</div>` },
            { label: "来源", key: "source" },
            { label: "次数", key: "occurrence_count" },
            { label: "最近发现", key: "last_detected_at" },
            { label: "确认人", key: "acknowledged_by" },
            { label: "恢复时间", key: "resolved_at" },
            { label: "操作", render: (row) => row.status === "open" ? `<button class="small ghost" data-ack-alert="${row.id}">确认</button>` : "" },
          ],
          items,
        ),
        '<button id="scan-alerts-btn" class="ghost">立即扫描</button>',
      )}
    </div>
  `;
  $("#scan-alerts-btn").addEventListener("click", async () => {
    const result = await api("/api/v1/legal/system-alerts/scan", { method: "POST", body: "{}" });
    showAlert(`扫描完成：当前异常 ${result.active}，新告警 ${result.opened}，已恢复 ${result.resolved}`);
    renderSystemAlerts();
  });
  document.querySelectorAll("[data-ack-alert]").forEach((button) => button.addEventListener("click", async () => {
    await api(`/api/v1/legal/system-alerts/${button.dataset.ackAlert}/ack`, { method: "POST", body: "{}" });
    showAlert("系统告警已确认");
    renderSystemAlerts();
  }));
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

const kdocsVisibleColumns = {
  enforcement: ["原告主体", "被告", "文书执行类型", "上传文件", "应还款时间", "民初案号", "总金额", "已还欠款", "案件状态", "备注"],
  court: ["开庭时间", "时间", "公司（原告）", "民初案号", "被告", "开庭方式", "跟进人", "金额", "传票", "核对"],
  payment: ["案号", "被告", "缴费类型", "金额", "文件链接", "识别摘要", "需人工复核", "消息ID"],
};

function kdocsValue(value) {
  if (value === null || value === undefined || value === "") return '<span class="muted">-</span>';
  const url = safeExternalUrl(value);
  if (url) return `<a class="kdocs-link" href="${escapeHtml(url)}" target="_blank" rel="noreferrer">打开</a>`;
  return `<span class="kdocs-cell-text">${escapeHtml(value)}</span>`;
}

function kdocsTargetTabs(overview) {
  const targets = [
    ...(overview.targets || []).map((target) => ({ ...target, key: target.key })),
    { key: "documents", name: "判决书文件", configured: Boolean(overview.drive_id), total_rows: null },
  ];
  return targets
    .map(
      (target) => `
        <button type="button" class="kdocs-tab ${state.kdocsTarget === target.key ? "active" : ""}" data-kdocs-target="${escapeHtml(target.key)}">
          <span>${escapeHtml(target.name)}</span>
          ${target.total_rows === null ? "" : `<strong>${escapeHtml(target.total_rows || 0)}</strong>`}
          <i class="${target.configured ? "ready" : ""}"></i>
        </button>
      `,
    )
    .join("");
}

function kdocsTableContent(data) {
  const columns = kdocsVisibleColumns[data.target] || data.headers || [];
  const rows = data.items || [];
  const totalPages = Math.max(1, Math.ceil((data.total || 0) / data.page_size));
  return `
    <div class="kdocs-content-head">
      <div>
        <h3>${escapeHtml(data.sheet_name || data.target_name)}</h3>
        <span>共 ${escapeHtml(data.total)} 条，第 ${escapeHtml(data.page)} / ${escapeHtml(totalPages)} 页</span>
      </div>
      ${safeExternalUrl(data.file_url) ? `<a class="button-like ghost" href="${escapeHtml(data.file_url)}" target="_blank" rel="noreferrer">在金山中打开</a>` : ""}
    </div>
    <div class="table-wrap kdocs-table-wrap">
      <table class="kdocs-table">
        <thead><tr><th class="kdocs-row-number">行</th>${columns.map((column) => `<th>${escapeHtml(column)}</th>`).join("")}</tr></thead>
        <tbody>
          ${rows.length ? rows.map((row) => `<tr><td class="kdocs-row-number">${escapeHtml(row.row_index + 1)}</td>${columns.map((column) => `<td>${kdocsValue((row.values || {})[column])}</td>`).join("")}</tr>`).join("") : `<tr><td colspan="${columns.length + 1}"><div class="empty-state">当前页暂无数据</div></td></tr>`}
        </tbody>
      </table>
    </div>
    <div class="kdocs-pagination">
      <button type="button" class="ghost" data-kdocs-page="prev" ${data.page <= 1 ? "disabled" : ""}>&larr; 上一页</button>
      <button type="button" class="ghost" data-kdocs-page="next" ${data.page >= totalPages ? "disabled" : ""}>下一页 &rarr;</button>
    </div>
  `;
}

function kdocsDocumentContent(data) {
  return `
    <div class="kdocs-content-head">
      <div><h3>判决书文件</h3><span>${escapeHtml(data.items.length)} 个搜索结果</span></div>
      <form id="kdocs-document-search" class="kdocs-search-form">
        <input name="query" maxlength="100" value="${escapeHtml(state.kdocsQuery)}" placeholder="搜索文件名" />
        <button type="submit">搜索</button>
      </form>
    </div>
    <div class="kdocs-file-list">
      ${data.items.length ? data.items.map((item) => {
        const url = safeExternalUrl(item.url);
        return `
          <article class="kdocs-file-row">
            <div class="kdocs-file-type">${escapeHtml((item.name.split(".").pop() || "文件").slice(0, 4).toUpperCase())}</div>
            <div class="kdocs-file-main">
              <strong>${escapeHtml(item.name)}</strong>
              <span>${escapeHtml(item.path || "金山云盘")} · ${escapeHtml(formatFileSize(item.size))}</span>
            </div>
            <div class="kdocs-file-meta">
              <span>${escapeHtml(item.modified_by || "-")}</span>
              <span>${escapeHtml(item.modified_at || "-")}</span>
            </div>
            ${url ? `<a class="button-like ghost" href="${escapeHtml(url)}" target="_blank" rel="noreferrer">打开</a>` : ""}
          </article>
        `;
      }).join("") : '<div class="empty-state">没有找到匹配文件</div>'}
    </div>
    <div class="kdocs-pagination">
      <button type="button" class="ghost" data-kdocs-doc-page="prev" ${state.kdocsDocumentTokenStack.length === 0 ? "disabled" : ""}>&larr; 上一页</button>
      <button type="button" class="ghost" data-kdocs-doc-page="next" ${data.next_page_token ? "" : "disabled"}>下一页 &rarr;</button>
    </div>
  `;
}

async function renderKDocsBrowser({ refreshOverview = false } = {}) {
  if (refreshOverview || !state.data.kdocsOverview) {
    state.data.kdocsOverview = await api("/api/v1/legal/kdocs-browser");
  }
  const overview = state.data.kdocsOverview;
  let contentData;
  if (state.kdocsTarget === "documents") {
    const params = new URLSearchParams({ query: state.kdocsQuery, page_size: "30" });
    if (state.kdocsDocumentToken) params.set("page_token", state.kdocsDocumentToken);
    contentData = await api(`/api/v1/legal/kdocs-browser/documents?${params}`);
  } else {
    contentData = await api(`/api/v1/legal/kdocs-browser/tables/${state.kdocsTarget}?page=${state.kdocsPage}&page_size=30`);
  }
  $("#content").innerHTML = `
    <section class="kdocs-browser">
      <header class="kdocs-header">
        <div>
          <div class="kdocs-title-line">
            <h2>致和法务文档库</h2>
            <span class="kdocs-live-badge ${overview.configured ? "ready" : ""}">${overview.configured ? "实时数据" : "配置异常"}</span>
          </div>
          <p>Drive ${escapeHtml(overview.drive_id || "未配置")} · ${escapeHtml(overview.transport)}</p>
        </div>
        <button id="refresh-kdocs-btn" type="button" class="ghost">刷新</button>
      </header>
      <nav class="kdocs-tabs" aria-label="金山文档视图">${kdocsTargetTabs(overview)}</nav>
      <div class="kdocs-content">${state.kdocsTarget === "documents" ? kdocsDocumentContent(contentData) : kdocsTableContent(contentData)}</div>
    </section>
  `;

  document.querySelectorAll("[data-kdocs-target]").forEach((button) => {
    button.addEventListener("click", async () => {
      state.kdocsTarget = button.dataset.kdocsTarget;
      state.kdocsPage = 1;
      state.kdocsDocumentToken = null;
      state.kdocsDocumentTokenStack = [];
      await renderKDocsBrowser();
    });
  });
  $("#refresh-kdocs-btn").addEventListener("click", () => renderKDocsBrowser({ refreshOverview: true }));
  document.querySelectorAll("[data-kdocs-page]").forEach((button) => {
    button.addEventListener("click", async () => {
      state.kdocsPage += button.dataset.kdocsPage === "next" ? 1 : -1;
      await renderKDocsBrowser();
    });
  });
  const searchForm = $("#kdocs-document-search");
  if (searchForm) {
    searchForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      state.kdocsQuery = String(new FormData(event.currentTarget).get("query") || "").trim() || "判决书";
      state.kdocsDocumentToken = null;
      state.kdocsDocumentTokenStack = [];
      await renderKDocsBrowser();
    });
  }
  document.querySelectorAll("[data-kdocs-doc-page]").forEach((button) => {
    button.addEventListener("click", async () => {
      if (button.dataset.kdocsDocPage === "next" && contentData.next_page_token) {
        state.kdocsDocumentTokenStack.push(state.kdocsDocumentToken);
        state.kdocsDocumentToken = contentData.next_page_token;
      } else if (button.dataset.kdocsDocPage === "prev" && state.kdocsDocumentTokenStack.length) {
        state.kdocsDocumentToken = state.kdocsDocumentTokenStack.pop();
      }
      await renderKDocsBrowser();
    });
  });
}

function workspaceTable(title, rows, columns) {
  return panel(title, table(columns, rows || []), `<span class="panel-meta">${(rows || []).length} 条</span>`);
}

async function renderCaseWorkspace() {
  if (!state.selectedCaseId) {
    const casesData = await api("/api/v1/legal/cases?limit=200");
    const cases = casesData.items || [];
    if (cases.length) state.selectedCaseId = cases[0].id;
    else {
      $("#content").innerHTML = '<div class="empty-state">暂无正式案件</div>';
      return;
    }
  }
  const data = await api(`/api/v1/legal/cases/${state.selectedCaseId}/workspace`);
  const item = data.case;
  $("#content").innerHTML = `
    <section class="case-workspace-view">
      <header class="case-workspace-header">
        <div><button class="ghost small" id="back-to-cases" type="button">返回案件</button><h2>${escapeHtml(item.case_no)}</h2><p>${escapeHtml([item.plaintiff_name, item.debtor_name, item.court_name].filter(Boolean).join(" · ") || "案件信息待补充")}</p></div>
        <div class="case-workspace-amount"><span>已付 / 总额</span><strong>${escapeHtml(item.paid_amount)} / ${escapeHtml(item.total_amount)}</strong>${badge(item.status)}</div>
      </header>
      <div class="workspace-stat-grid">
        ${Object.entries(data.counts).map(([key, value]) => `<div><span>${escapeHtml({groups:"群",messages:"消息",media:"资料",events:"事件",payments:"付款",reminders:"提醒",sync_logs:"金山"}[key] || key)}</span><strong>${value}</strong></div>`).join("")}
      </div>
      <div class="workspace-columns">
        <div class="workspace-main">
          ${workspaceTable("付款流水", data.payments, [
            { label: "类型", key: "record_type" }, { label: "金额", key: "amount" }, { label: "日期", key: "payment_date" },
            { label: "付款人", key: "payer_name" }, { label: "状态", render: (row) => badge(row.status) },
            { label: "操作", render: (row) => row.status === "pending" ? `<button class="small" data-approve-payment="${row.id}">批准</button>` : row.status === "approved" && row.record_type !== "reversal" ? `<button class="small ghost" data-reverse-payment="${row.id}">冲正</button>` : "-" },
          ])}
          ${panel("新增付款", `<form id="workspace-payment-form" class="form-grid"><div class="field"><label>金额</label><input name="amount" type="number" min="0.01" step="0.01" required /></div><div class="field"><label>付款日期</label><input name="payment_date" type="date" /></div><div class="field"><label>付款人</label><input name="payer_name" /></div><div class="field"><label>复核状态</label><select name="status"><option value="pending">待复核</option><option value="approved">已批准</option></select></div><div class="field wide"><label>备注</label><input name="note" /></div><div class="field"><button type="submit">登记流水</button></div></form>`)}
          ${workspaceTable("资料", data.media, [{label:"文件",key:"original_filename"},{label:"类型",key:"media_type"},{label:"OCR",render:(row)=>badge(row.ocr_status)},{label:"复核",render:(row)=>badge(row.review_status)}])}
          ${workspaceTable("业务事件", data.events, [{label:"类型",key:"event_type"},{label:"金额",key:"amount"},{label:"归属",render:(row)=>badge(row.attribution_status)},{label:"业务状态",render:(row)=>badge(row.business_status)},{label:"时间",key:"event_time"}])}
          ${workspaceTable("群聊上下文", data.messages, [{label:"群",key:"group_id"},{label:"发送人",key:"sender_id"},{label:"类型",key:"msg_type"},{label:"内容",render:(row)=>escapeHtml(String(row.content||"").slice(0,180))},{label:"时间",key:"received_at"}])}
        </div>
        <aside class="workspace-side">
          ${workspaceTable("关联群", data.groups, [{label:"群 ID",key:"group_id"},{label:"主群",render:(row)=>row.is_primary?"是":"否"}])}
          ${workspaceTable("提醒", data.reminders, [{label:"时间",key:"remind_at"},{label:"内容",render:(row)=>escapeHtml(String(row.content||"").slice(0,80))},{label:"状态",render:(row)=>badge(row.status)}])}
          ${workspaceTable("金山结果", data.sync_logs, [{label:"类型",key:"sync_type"},{label:"结果",render:(row)=>badge(row.outcome)},{label:"行",key:"external_row_index"}])}
          ${workspaceTable("审计时间线", data.audit_timeline, [{label:"类型",key:"type"},{label:"内容",key:"label"},{label:"时间",key:"at"}])}
        </aside>
      </div>
    </section>`;
  $("#back-to-cases").addEventListener("click", () => setView("cases"));
  $("#workspace-payment-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(event.currentTarget).entries());
    if (!payload.payment_date) payload.payment_date = null;
    await api(`/api/v1/legal/cases/${item.id}/payments`, {method:"POST", body:JSON.stringify(payload)});
    await renderCaseWorkspace();
  });
  document.querySelectorAll("[data-approve-payment]").forEach((button) => button.addEventListener("click", async () => {
    await api(`/api/v1/legal/cases/${item.id}/payments/${button.dataset.approvePayment}`, {method:"PATCH", body:JSON.stringify({action:"approve"})});
    await renderCaseWorkspace();
  }));
  document.querySelectorAll("[data-reverse-payment]").forEach((button) => button.addEventListener("click", async () => {
    const note = window.prompt("填写冲正原因");
    if (!note) return;
    await api(`/api/v1/legal/cases/${item.id}/payments/${button.dataset.reversePayment}`, {method:"PATCH", body:JSON.stringify({action:"reverse", note})});
    await renderCaseWorkspace();
  }));
}

async function renderAttributionQueue() {
  const [queueData, casesData] = await Promise.all([
    api("/api/v1/legal/attribution-queue?status=pending&limit=200"),
    api("/api/v1/legal/cases?limit=200"),
  ]);
  const items = queueData.items || [];
  const cases = casesData.items || [];
  $("#content").innerHTML = `
    <section class="attribution-view">
      <header class="case-section-header"><div><h2>案件归属复核</h2><p>按群、上下文和 AI 候选批量确认；确认前不会产生付款、提醒或金山写入。</p></div><span class="case-candidate-count">${queueData.total || 0}</span></header>
      ${panel("批量操作", `<form id="attribution-form" class="form-grid"><div class="field wide"><label>目标案件</label><select name="case_id"><option value="">选择案件</option>${cases.map((row)=>`<option value="${row.id}">${escapeHtml(row.case_no)} · ${escapeHtml(row.debtor_name)}</option>`).join("")}</select></div><div class="field wide"><label>驳回原因</label><input name="reason" placeholder="仅驳回时填写" /></div><div class="field form-actions"><button type="submit" data-attribution-action="confirm">确认归属</button><button type="submit" class="danger" data-attribution-action="reject">明确驳回</button></div></form>`)}
      ${panel("隔离队列", table([
        {label:"选择",render:(row)=>`<input type="checkbox" data-attribution-id="${row.id}" />`},
        {label:"群 ID",key:"group_id"},{label:"对象",render:(row)=>`${escapeHtml(row.subject_type)} #${row.subject_id}`},
        {label:"候选案件",render:(row)=>fmt(row.suggested_case_id)},{label:"置信度",render:(row)=>fmt(row.confidence)},
        {label:"原因",key:"reason"},{label:"进入时间",key:"created_at"},
      ], items))}
    </section>`;
  $("#attribution-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const submitter = event.submitter;
    const itemIds = [...document.querySelectorAll("[data-attribution-id]:checked")].map((input)=>Number(input.dataset.attributionId));
    if (!itemIds.length) return showAlert("请至少选择一条待归属记录", "error");
    const form = new FormData(event.currentTarget);
    const decision = submitter.dataset.attributionAction;
    const payload = {item_ids:itemIds, decision, case_id: decision === "confirm" ? Number(form.get("case_id")) || null : null, reason:String(form.get("reason")||"") || null};
    await api("/api/v1/legal/attribution-queue/batch-confirm", {method:"POST", body:JSON.stringify(payload)});
    showAlert("批量归属已处理");
    await renderAttributionQueue();
  });
}

async function loadView() {
  $("#content").innerHTML = '<div class="empty-state">加载中...</div>';
  try {
    if (state.view === "overview") await renderOverview();
    if (state.view === "cases") await renderCases();
    if (state.view === "case-workspace") await renderCaseWorkspace();
    if (state.view === "attribution") await renderAttributionQueue();
    if (state.view === "messages") await renderMessages();
    if (state.view === "archive-groups") await renderArchiveGroups();
    if (state.view === "ocr-reviews") await renderOCRReviews();
    if (state.view === "recognition-settings") await renderRecognitionSettings();
    if (state.view === "payment-trackings") await renderPaymentTrackings();
    if (state.view === "reminders") await renderReminders();
    if (state.view === "merchant-questions") await renderMerchantQuestions();
    if (state.view === "send-platform") await renderWeComApiPlatform();
    if (state.view === "system-alerts") await renderSystemAlerts();
    if (state.view === "events") await renderEvents();
    if (state.view === "media") await renderMedia();
    if (state.view === "sync") await renderSync();
    if (state.view === "kdocs-browser") await renderKDocsBrowser();
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
  window.addEventListener("popstate", () => setView(viewFromLocation(), { syncLocation: false }));
  setView(viewFromLocation(), { replaceLocation: true });
}

document.addEventListener("DOMContentLoaded", init);
