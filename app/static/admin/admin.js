const state = {
  view: localStorage.getItem("legal_wecom_view") || "overview",
  apiKey: localStorage.getItem("legal_wecom_api_key") || "",
  data: {},
  editingCaseId: null,
};

const titles = {
  overview: ["总览", "系统状态、调度器和部署健康情况"],
  cases: ["案件", "创建、查询和同步案件"],
  messages: ["消息", "模拟企业微信群消息进入识别链路"],
  "archive-groups": ["归档群", "企业微信会话发现与法务群白名单"],
  reminders: ["提醒", "查看提醒、手动触发到期提醒发送"],
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
      await api(`/api/v1/legal/wecom-archive/groups/${encodeURIComponent(button.dataset.saveArchiveGroup)}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      });
      showAlert("归档群配置已保存");
      renderArchiveGroups();
    });
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
    if (state.view === "archive-groups") await renderArchiveGroups();
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
  window.addEventListener("popstate", () => setView(viewFromLocation(), { syncLocation: false }));
  setView(viewFromLocation(), { replaceLocation: true });
}

document.addEventListener("DOMContentLoaded", init);
