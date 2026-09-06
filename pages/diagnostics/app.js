const bridge = window.AstrBotPluginPage;
const categoryLabels = {
  status: "状态",
  account: "账号",
  friend: "好友",
  group: "群组",
  request: "申请",
  message: "消息",
  media: "媒体",
  file: "文件",
};
const riskLabels = {
  read: "读取",
  write: "写入",
  privileged: "高权限",
  destructive: "破坏性",
};
const permissionLabels = {
  member: "成员",
  astrbot_admin: "AstrBot 管理员",
  group_admin: "群管理员",
  group_owner: "群主",
};
const disabledReasonLabels = {
  pack_not_enabled: "分类未启用",
  disabled_by_config: "配置已禁用",
};
const auditResultLabels = {
  ok: "成功",
  started: "开始执行",
  confirmation_required: "等待确认",
  permission_denied: "权限不足",
  invalid_parameters: "参数无效",
  target_not_found: "目标不存在",
  capability_unavailable: "能力不可用",
  protocol_rejected: "QQ 协议拒绝",
  network_error: "网络错误",
  timeout: "超时",
  response_invalid: "响应无效",
  internal_error: "内部错误",
};

let capabilities = [];

function text(value, fallback = "—") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

function formatTime(value) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(Number(value) * 1000));
}

function makeBadge(label, tone = "") {
  const element = document.createElement("span");
  element.className = `badge ${tone}`.trim();
  element.textContent = label;
  return element;
}

function appendCell(row, value, useCode = false) {
  const cell = document.createElement("td");
  const content = useCode ? document.createElement("code") : document.createElement("span");
  content.textContent = text(value);
  cell.append(content);
  row.append(cell);
  return cell;
}

function renderSummary(data) {
  const summary = data.summary;
  const cards = [
    ["NapCat 平台", `${summary.reachable_platforms}/${summary.platforms}`, "可访问 / 已发现"],
    ["模型工具", `${summary.tools_enabled}/${summary.tools_total}`, "已启用 / 总数"],
    ["插件操作", `${summary.operations_enabled}/${summary.operations_total}`, "已启用 / 总数"],
    ["兼容实例", summary.compatible_platforms, data.contract.supported_versions],
    ["待确认", summary.pending_confirmations, "当前有效操作"],
  ];
  const container = document.getElementById("summary-cards");
  container.replaceChildren();
  for (const [label, value, hint] of cards) {
    const card = document.createElement("article");
    card.className = "summary-card";
    const labelElement = document.createElement("span");
    labelElement.textContent = label;
    const valueElement = document.createElement("strong");
    valueElement.textContent = value;
    const hintElement = document.createElement("small");
    hintElement.textContent = hint;
    card.append(labelElement, valueElement, hintElement);
    container.append(card);
  }
  document.getElementById("updated-at").textContent = `更新时间 ${formatTime(data.generated_at)}`;
  document.getElementById("contract-range").textContent = `契约 ${data.contract.version} · 支持 ${data.contract.supported_versions}`;
}

function renderPlatforms(platforms) {
  const body = document.getElementById("platform-rows");
  body.replaceChildren();
  if (!platforms.length) {
    const row = document.createElement("tr");
    const cell = appendCell(row, "未发现 aiocqhttp 平台实例");
    cell.colSpan = 6;
    body.append(row);
    return;
  }
  for (const platform of platforms) {
    const row = document.createElement("tr");
    const platformCell = appendCell(row, platform.platform_id, true);
    if (!platform.selected) platformCell.append(" ", makeBadge("未选用", "warning"));

    const connectionCell = document.createElement("td");
    if (!platform.selected) connectionCell.append(makeBadge("未探测", "warning"));
    else if (platform.online === true) connectionCell.append(makeBadge("在线", "success"));
    else if (platform.reachable) connectionCell.append(makeBadge("可访问", "warning"));
    else connectionCell.append(makeBadge("不可访问", "danger"));
    row.append(connectionCell);

    appendCell(row, [platform.implementation, platform.version].filter(Boolean).join(" "));
    appendCell(row, [platform.nickname, platform.account_id].filter(Boolean).join(" / "));
    const compatibilityCell = document.createElement("td");
    if (platform.compatible === true) compatibilityCell.append(makeBadge("兼容", "success"));
    else if (platform.compatible === false) compatibilityCell.append(makeBadge("不兼容", "danger"));
    else compatibilityCell.append(makeBadge("未知", "warning"));
    row.append(compatibilityCell);
    appendCell(row, platform.errors.join("；"));
    body.append(row);
  }
}

function renderConfiguration(config) {
  const spoofLabels = { off: "关闭", weak: "弱档", strong: "强档" };
  const items = [
    ["绑定平台", config.platform_id || "全部 aiocqhttp"],
    ["工具暴露模式", config.exposure_mode],
    ["启用分类", config.enabled_packs.length ? config.enabled_packs.join(", ") : "全部"],
    ["显式禁用操作", config.disabled_operations],
    ["组件语义化", config.semanticize_components ? "开启" : "关闭"],
    ["NapCat 语音增强", config.enhance_voice_messages ? "开启" : "关闭"],
    ["组件防伪", spoofLabels[config.component_spoof_mode] || config.component_spoof_mode],
    ["防伪类型", config.protected_types.join(", ")],
    ["戳一戳响应", config.respond_to_poke ? "开启" : "关闭"],
    ["红包响应", config.respond_to_red_packet ? "开启" : "关闭"],
    ["撤回感知", config.mark_recalled_messages ? "开启" : "关闭"],
    ["消息防抖", config.debounce_enabled ? "开启" : "关闭"],
    ["首条等待窗口", `${config.debounce_initial_window_seconds ?? 0} 秒`],
    ["后续等待窗口", `${config.debounce_followup_window_seconds ?? 0} 秒`],
    ["累计等待上限", `${config.debounce_max_wait_seconds ?? 0} 秒`],
    ["申请通知", config.request_notifications ? `开启（${config.notification_admins} 位管理员）` : "关闭"],
    ["需要确认的操作", config.confirmation_operations],
  ];
  const container = document.getElementById("config-grid");
  container.replaceChildren();
  for (const [label, value] of items) {
    const item = document.createElement("div");
    item.className = "config-item";
    const term = document.createElement("dt");
    term.textContent = label;
    const description = document.createElement("dd");
    description.textContent = text(value);
    item.append(term, description);
    container.append(item);
  }
}

function renderCapabilities() {
  const query = document.getElementById("capability-search").value.trim().toLowerCase();
  const category = document.getElementById("category-filter").value;
  const status = document.getElementById("status-filter").value;
  const filtered = capabilities.filter((item) => {
    const matchesQuery = !query || [
      item.operation_id,
      item.display_name,
      item.action,
      item.category,
    ].some((value) => String(value).toLowerCase().includes(query));
    const matchesCategory = !category || item.category === category;
    const matchesStatus = !status || (status === "enabled" ? item.enabled : !item.enabled);
    return matchesQuery && matchesCategory && matchesStatus;
  });
  const body = document.getElementById("capability-rows");
  body.replaceChildren();
  for (const item of filtered) {
    const row = document.createElement("tr");
    appendCell(row, categoryLabels[item.category] || item.category);
    appendCell(row, item.operation_id, true);
    appendCell(row, item.display_name);
    appendCell(row, item.action || "插件安全封装", true);
    const riskCell = document.createElement("td");
    const riskTone = item.risk === "read" ? "success" : item.risk === "destructive" ? "danger" : "warning";
    riskCell.append(makeBadge(riskLabels[item.risk] || item.risk, riskTone));
    row.append(riskCell);
    appendCell(row, permissionLabels[item.permission] || item.permission);
    const stateCell = document.createElement("td");
    stateCell.append(
      makeBadge(
        item.enabled ? "已启用" : disabledReasonLabels[item.disabled_reason] || "已禁用",
        item.enabled ? "success" : "danger",
      ),
    );
    row.append(stateCell);
    body.append(row);
  }
  if (!filtered.length) {
    const row = document.createElement("tr");
    const cell = appendCell(row, "没有符合筛选条件的操作");
    cell.colSpan = 7;
    body.append(row);
  }
  document.getElementById("capability-count").textContent = `显示 ${filtered.length} / ${capabilities.length} 项操作`;
}

function renderRecords(data) {
  const pendingList = document.getElementById("pending-list");
  pendingList.replaceChildren();
  if (!data.pending_confirmations.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "当前没有待确认操作";
    pendingList.append(empty);
  }
  for (const item of data.pending_confirmations) {
    const record = document.createElement("article");
    record.className = "record";
    const top = document.createElement("div");
    top.className = "record-topline";
    const operation = document.createElement("code");
    operation.textContent = item.operation_id;
    top.append(operation, makeBadge(`${item.remaining_seconds} 秒`, "warning"));
    const detail = document.createElement("p");
    detail.textContent = `${item.summary} · 调用者 ${item.caller_id} · ${formatTime(item.created_at)}`;
    record.append(top, detail);
    pendingList.append(record);
  }

  const auditList = document.getElementById("audit-list");
  auditList.replaceChildren();
  if (!data.audits.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "暂无审计记录";
    auditList.append(empty);
  }
  for (const item of data.audits) {
    const record = document.createElement("article");
    record.className = "record";
    const top = document.createElement("div");
    top.className = "record-topline";
    const operation = document.createElement("code");
    operation.textContent = item.operation_id;
    let tone = "danger";
    if (item.result_code === "ok") tone = "success";
    else if (item.result_code === "started") tone = "";
    else if (item.result_code === "confirmation_required") tone = "warning";
    top.append(
      operation,
      makeBadge(auditResultLabels[item.result_code] || item.result_code, tone),
    );
    const detail = document.createElement("p");
    const target = item.target_id ? `${item.target_kind} ${item.target_id}` : item.target_kind;
    detail.textContent = `${formatTime(item.created_at)} · 调用者 ${item.caller_id} · ${target} · ${item.duration_ms} ms`;
    record.append(top, detail);
    auditList.append(record);
  }
}

function renderCategoryFilter(items) {
  const select = document.getElementById("category-filter");
  const currentValue = select.value;
  select.replaceChildren(new Option("全部分类", ""));
  for (const category of [...new Set(items.map((item) => item.category))].sort()) {
    select.append(new Option(categoryLabels[category] || category, category));
  }
  select.value = currentValue;
}

async function loadDiagnostics() {
  const button = document.getElementById("refresh-button");
  const notice = document.getElementById("notice");
  button.disabled = true;
  button.textContent = "加载中";
  notice.hidden = true;
  try {
    const data = await bridge.apiGet("diagnostics");
    capabilities = data.capabilities;
    renderSummary(data);
    renderPlatforms(data.platforms);
    renderConfiguration(data.configuration);
    renderCategoryFilter(capabilities);
    renderCapabilities();
    renderRecords(data);
    if (data.warnings.length) {
      notice.className = "notice";
      notice.textContent = data.warnings.join("；");
      notice.hidden = false;
    }
  } catch (error) {
    notice.className = "notice error";
    notice.textContent = `加载诊断数据失败：${error instanceof Error ? error.message : String(error)}`;
    notice.hidden = false;
  } finally {
    button.disabled = false;
    button.textContent = "刷新";
  }
}

document.getElementById("refresh-button").addEventListener("click", loadDiagnostics);
document.getElementById("capability-search").addEventListener("input", renderCapabilities);
document.getElementById("category-filter").addEventListener("change", renderCapabilities);
document.getElementById("status-filter").addEventListener("change", renderCapabilities);

await bridge.ready();
await loadDiagnostics();
