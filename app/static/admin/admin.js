const state = {
  view: localStorage.getItem("legal_wecom_view") || "overview",
  apiKey: localStorage.getItem("legal_wecom_api_key") || "",
  data: {},
  editingCaseId: null,
  selectedReviewId: null,
  reviewStatusFilter: "pending",
  reviewPreviewUrl: null,
  editingReminderId: null,
};

const titles = {
  overview: ["总览", "系统状态、调度器和部署健康情况"],
  cases: ["案件", "创建、查询和同步案件"],
  messages: ["消息", "模拟企业微信群消息进入识别链路"],
  "archive-groups": ["归档群", "企业微信会话发现与法务群白名单"],
  "ocr-reviews": ["人工复核", "核对识别结果并控制业务同步"],
  reminders: ["提醒", "查看提醒、手动触发到期提醒发送"],
  "merchant-questions": ["商家提问", "跟踪外部消息回复时效"],
  "system-alerts": ["系统告警", "归档、识别、同步、机器人、备份和磁盘健康"],
  events: ["事件", "查看系统抽取出的结构化法务事件"],
  media: ["媒体", "图片、PDF、文件和 OCR 状态"],
  sync: ["同步日志", "金山文档同步日志和重试结果"],
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

function normalizedView(view) {
  return Object.prototype.hasOwnProperty.call(titles, view) ? view : "overview";
}

function viewFromLocation() {
  return normalizedView(window.location.hash.replace(/^#/, "") || state.view);
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
  document.querySelectorAll(".nav-item").forEach((item) => {
    item.classList.toggle("active", item.dataset.view === nextView);
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
  const sender = detail.sender || { status: "disabled", message: "发送端状态未知" };
  const senderLabels = { ok: "设备在线", disabled: "未启用", degraded: "需配置", error: "不可用" };
  const senderLabel = senderLabels[sender.status] || sender.status;
  $("#content").innerHTML = `
    <div class="grid cols-4">
      <div class="panel stat"><div class="stat-label">系统状态</div><div class="stat-value ${healthStatusClass(detail.status)}">${escapeHtml(detail.status || health.status)}</div></div>
      <div class="panel stat"><div class="stat-label">运行环境</div><div class="stat-value">${escapeHtml(health.env)}</div></div>
      <div class="panel stat"><div class="stat-label">调度器</div><div class="stat-value ${detail.scheduler.running ? "status-ok" : "status-warning"}">${detail.scheduler.running ? "running" : "stopped"}</div></div>
      <div class="panel stat"><div class="stat-label">Android 发送端</div><div class="stat-value ${healthStatusClass(sender.status)}">${escapeHtml(senderLabel)}</div><div class="stat-note">${escapeHtml(sender.message)}</div></div>
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

async function renderCases() {
  const [data, archiveGroupsData] = await Promise.all([
    api("/api/v1/legal/cases?limit=50"),
    api("/api/v1/legal/wecom-archive/groups?page_size=200"),
  ]);
  const cases = data.items || [];
  const archiveGroups = archiveGroupsData.items || [];
  const editingCase = cases.find((item) => item.id === state.editingCaseId);
  if (state.editingCaseId && !editingCase) state.editingCaseId = null;
  $("#content").innerHTML = `
    <div class="grid">
      ${archiveGroupDatalist(archiveGroups)}
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
            { label: "操作", render: (row) => `<button class="small ghost" data-edit-case="${row.id}">编辑</button>` },
          ],
          cases,
        ),
        '<button id="scan-status-btn" class="ghost">扫描状态</button>',
      )}
    </div>
  `;
  $("#case-form").addEventListener("submit", submitCase);
  document.querySelectorAll("[data-edit-case]").forEach((button) => {
    button.addEventListener("click", () => {
      state.editingCaseId = Number(button.dataset.editCase);
      renderCases();
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
  $("#content").innerHTML = `
    <div class="grid cols-3">
      <div class="panel stat"><div class="stat-label">待确认</div><div class="stat-value status-warning">${counts.discovered}</div></div>
      <div class="panel stat"><div class="stat-label">已启用</div><div class="stat-value status-ok">${counts.enabled}</div></div>
      <div class="panel stat"><div class="stat-label">已停用</div><div class="stat-value">${counts.disabled}</div></div>
    </div>
    <div class="grid archive-group-grid">
      ${panel(
        "登记法务群",
        `
        <form id="archive-group-form" class="form-grid">
          <div class="field"><label>群 roomid</label><input name="room_id" required maxlength="128" placeholder="wrxxxxxxxx" /></div>
          <div class="field"><label>发送目标 ID</label><input name="wecomapi_room_id" maxlength="128" placeholder="例如 zhihe-legal" /></div>
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
        '<button id="discover-groups-btn" class="ghost">立即拉取</button>',
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
        "群聊白名单",
        table(
          [
            { label: "roomid", render: (row) => `<span class="mono">${escapeHtml(row.room_id)}</span>` },
            {
              label: "发送目标 ID",
              render: (row) => `<input class="compact-input mono" data-field="wecomapi_room_id" value="${escapeHtml(row.wecomapi_room_id || "")}" maxlength="128" placeholder="未映射" />`,
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
              render: (row) => `<button class="small" data-save-archive-group="${escapeHtml(row.room_id)}">保存修改</button>`,
            },
          ],
          groups,
        ),
      )}
    </div>
  `;

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
}

function reviewFieldValue(result, key) {
  const value = result && result[key];
  if (value === null || value === undefined) return "";
  if (key === "court_time" && typeof value === "string") return value.slice(0, 16);
  return String(value);
}

function reviewDetail(review) {
  const result = review.final_result || review.ocr_result || {};
  const editable = review.review_status === "pending";
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
      ${badge(review.review_status)}
    </div>
    <div class="review-detail-grid">
      <section class="review-preview"><div id="review-preview" class="preview-placeholder">加载预览中...</div></section>
      <section class="review-fields">
        <form id="review-form" data-media-id="${review.media_file_id}">
          <div class="form-grid review-form-grid">
            <div class="field"><label>案号</label><input name="case_no" value="${escapeHtml(reviewFieldValue(result, "case_no"))}" ${editable ? "" : "disabled"} /></div>
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

async function renderOCRReviews() {
  const query = state.reviewStatusFilter ? `?review_status=${encodeURIComponent(state.reviewStatusFilter)}&page_size=100` : "?page_size=100";
  const data = await api(`/api/v1/legal/ocr-reviews${query}`);
  const items = data.items || [];
  if (!items.some((item) => item.media_file_id === state.selectedReviewId)) {
    state.selectedReviewId = items[0] ? items[0].media_file_id : null;
  }
  const selected = items.find((item) => item.media_file_id === state.selectedReviewId);
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
  if (selected) await loadReviewPreview(selected);
}

async function renderReminders() {
  const [data, rulesData] = await Promise.all([
    api("/api/v1/legal/reminders?limit=100"),
    api("/api/v1/legal/reminder-rules"),
  ]);
  const reminders = data.items || [];
  const rules = rulesData.items || [];
  const editing = reminders.find((item) => item.id === state.editingReminderId);
  $("#content").innerHTML = `
    <div class="grid">
      ${panel(
        "创建自定义提醒",
        `<form id="custom-reminder-form" class="form-grid"><div class="field"><label>群 ID</label><input name="group_id" required /></div><div class="field"><label>提醒时间</label><input name="remind_at" type="datetime-local" required /></div><div class="field"><label>目标人员 ID</label><input name="target_userid" /></div><div class="field wide"><label>提醒内容</label><textarea name="content" required></textarea></div><div class="field"><button type="submit">创建提醒</button></div></form>`,
      )}
      ${
        editing
          ? panel(
              `编辑自定义提醒 · ${editing.id}`,
              `<form id="edit-reminder-form" class="form-grid"><div class="field"><label>提醒时间</label><input name="remind_at" type="datetime-local" value="${escapeHtml(editing.remind_at.slice(0, 16))}" required /></div><div class="field"><label>目标人员 ID</label><input name="target_userid" value="${escapeHtml(editing.target_userid || "")}" /></div><div class="field wide"><label>提醒内容</label><textarea name="content" required>${escapeHtml(editing.content)}</textarea></div><div class="field form-actions"><button type="submit">保存</button><button type="button" class="ghost" id="cancel-reminder-edit">取消</button></div></form>`,
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
            { label: "群", key: "group_id" },
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
  $("#custom-reminder-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(event.currentTarget).entries());
    if (!payload.target_userid) payload.target_userid = null;
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
    $("#cancel-reminder-edit").addEventListener("click", () => { state.editingReminderId = null; renderReminders(); });
    $("#edit-reminder-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      const payload = Object.fromEntries(new FormData(event.currentTarget).entries());
      if (!payload.target_userid) payload.target_userid = null;
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

async function loadView() {
  $("#content").innerHTML = '<div class="empty-state">加载中...</div>';
  try {
    if (state.view === "overview") await renderOverview();
    if (state.view === "cases") await renderCases();
    if (state.view === "messages") await renderMessages();
    if (state.view === "archive-groups") await renderArchiveGroups();
    if (state.view === "ocr-reviews") await renderOCRReviews();
    if (state.view === "reminders") await renderReminders();
    if (state.view === "merchant-questions") await renderMerchantQuestions();
    if (state.view === "system-alerts") await renderSystemAlerts();
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
  window.addEventListener("popstate", () => setView(viewFromLocation(), { syncLocation: false }));
  setView(viewFromLocation(), { replaceLocation: true });
}

document.addEventListener("DOMContentLoaded", init);
