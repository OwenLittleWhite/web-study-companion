const API_BASE = "http://127.0.0.1:8765";

const state = {
  sessionId: null,
  session: null,
  capturing: false,
  starting: false,
  authorizedTab: null,
  segments: [],
  messages: [],
  archives: [],
  page: null,
  asrConfig: null,
  mediaPlayback: { known: false, playing: true },
  activeView: "transcript",
  unseenTranscriptSegments: 0,
  renameTarget: null,
  deleteTarget: null
};

const el = Object.fromEntries([
  "serverBadge", "pageTitle", "pageUrl", "provider", "language", "startButton",
  "stopButton", "status", "liveDot", "modelSettingsButton", "captureConfigSummary",
  "captureConfigTitle", "captureConfigMeta", "captureConfigPanel", "closeCaptureConfigButton",
  "providerPrice", "localProviderButton", "qwenProviderButton", "asrModelSummary",
  "asrSettingsButton", "providerDetail", "asrSettingsModal", "closeAsrSettingsButton",
  "asrSettingsForm", "asrApiKey", "toggleAsrApiKeyButton", "asrApiKeyHint",
  "asrRegion", "asrModel", "asrTerms", "asrUsePageContext", "asrSettingsStatus",
  "testAsrConfigButton",
  "downloadButton", "downloadMenu", "historyButton", "newSessionButton", "workspace", "transcriptViewButton",
  "chatViewButton", "transcriptTabMeta", "chatTabMeta", "unseenTranscriptBadge",
  "transcriptPane", "chatPane", "transcriptCount", "roundCount", "partialTranscript",
  "transcript", "messages", "chatForm", "question",
  "askButton", "includeTranscript", "contextSize", "historyModal", "closeHistoryButton",
  "historySearch", "archiveList", "renameForm", "renameInput", "cancelRenameButton",
  "deleteDialog", "deleteTargetTitle", "deleteStatus", "cancelDeleteIconButton",
  "cancelDeleteButton", "confirmDeleteButton", "settingsModal",
  "closeSettingsButton", "settingsForm", "llmProvider", "llmBaseUrl", "llmApiKey",
  "toggleApiKeyButton", "llmModel", "apiKeyHint", "settingsStatus", "testConfigButton"
].map((id) => [id, document.getElementById(id)]));

let transcriptScrollFrame = null;

function scrollTranscriptToLatest() {
  if (transcriptScrollFrame !== null) cancelAnimationFrame(transcriptScrollFrame);
  transcriptScrollFrame = requestAnimationFrame(() => {
    transcriptScrollFrame = null;
    const scroller = el.transcript.parentElement;
    scroller.scrollTop = scroller.scrollHeight;
  });
}

function setStatus(text, error = false) {
  el.status.textContent = text;
  el.status.classList.toggle("error", error);
  el.liveDot.classList.toggle("error", error);
  el.liveDot.classList.toggle("idle", !state.capturing && !error);
}

function setMediaPlaybackState(mediaState) {
  state.mediaPlayback = mediaState || { known: false, playing: true };
  if (!state.capturing) return;
  if (state.mediaPlayback.known && !state.mediaPlayback.playing) {
    setStatus("网页媒体已暂停或缓冲 · 转写与时间戳已暂停");
  } else {
    setStatus(`实时转写中 · 已自动保存 ${state.segments.length} 段`);
  }
}

function formatTime(milliseconds) {
  const total = Math.max(0, Math.floor(milliseconds / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = total % 60;
  return hours
    ? `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`
    : `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function archiveTime(value) {
  if (!value) return "";
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) }
  });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try { detail = (await response.json()).detail || detail; } catch (_error) {}
    throw new Error(detail);
  }
  return response.json();
}

async function checkServer() {
  try {
    const health = await api("/health");
    el.serverBadge.textContent = `服务正常 · ${health.version}`;
    el.serverBadge.classList.remove("offline");
    const readiness = health.providers?.[el.provider.value];
    if (readiness) {
      if (el.provider.value === "qwen-cloud") {
        el.providerDetail.textContent = readiness.reason;
      }
      if (!readiness.ready) setStatus(readiness.reason, true);
    }
  } catch (_error) {
    el.serverBadge.textContent = "服务未连接";
    el.serverBadge.classList.add("offline");
    setStatus("请先启动本机 Companion 服务。", true);
  }
}

async function loadCurrentTab() {
  const response = await chrome.runtime.sendMessage({ type: "tab.current" });
  if (!response?.ok || !response.tab) return;
  state.page = response.tab;
  if (!state.sessionId) {
    el.pageTitle.textContent = response.tab.title || "未命名网页";
    el.pageUrl.textContent = response.tab.url || "";
  }
}

function segmentText(segment) {
  return segment.text ?? segment.final_text ?? segment.raw_text ?? "[该片段文字缺失]";
}

function transcriptSeparator(previous, next) {
  if (!previous) return "";
  if (/^[,.;:!?，。；：！？、'”’)]/.test(next)) return "";
  if (/[A-Za-z0-9)]$/.test(previous) && /^[A-Za-z0-9(']/.test(next)) return " ";
  return "";
}

function appendSegmentToTranscript(segment, autoScroll = true) {
  if (el.transcript.classList.contains("empty-state")) {
    el.transcript.classList.remove("empty-state");
    el.transcript.textContent = "";
  }
  const text = segmentText(segment).trim();
  let paragraph = el.transcript.lastElementChild;
  const paragraphStart = paragraph ? Number(paragraph.dataset.startMs || 0) : 0;
  const paragraphChars = paragraph ? Number(paragraph.dataset.chars || 0) : 0;
  const previousText = paragraph?.dataset.lastText || "";
  const shouldBreak = !paragraph
    || paragraphChars >= 320
    || (segment.start_ms - paragraphStart >= 30_000 && /[.!?。！？]$/.test(previousText));
  if (shouldBreak) {
    paragraph = document.createElement("p");
    paragraph.dataset.startMs = String(segment.start_ms);
    paragraph.dataset.chars = "0";
    const time = document.createElement("span");
    time.className = "timestamp";
    time.textContent = formatTime(segment.start_ms);
    paragraph.append(time);
    el.transcript.append(paragraph);
  }
  paragraph.append(document.createTextNode(transcriptSeparator(paragraph.dataset.lastText || "", text) + text));
  paragraph.dataset.chars = String(Number(paragraph.dataset.chars || 0) + text.length);
  paragraph.dataset.lastText = text;
  if (autoScroll) scrollTranscriptToLatest();
}

function renderTranscript() {
  el.transcript.textContent = "";
  el.transcript.classList.toggle("empty-state", state.segments.length === 0);
  if (!state.segments.length) {
    el.transcript.textContent = "当前 Session 尚无逐字稿。";
  } else {
    state.segments.forEach((segment) => appendSegmentToTranscript(segment, false));
    scrollTranscriptToLatest();
  }
  const characterCount = state.segments.reduce((sum, segment) => sum + segmentText(segment).length, 0);
  el.transcriptCount.textContent = `${characterCount.toLocaleString("zh-CN")} 字`;
  el.transcriptTabMeta.textContent = `${characterCount.toLocaleString("zh-CN")} 字`;
  el.contextSize.textContent = `${characterCount.toLocaleString("zh-CN")} 字`;
}

function transcriptScopeLabel(message) {
  if (message.transcript_scope === "full") return "携带完整逐字稿";
  if (message.transcript_scope === "recent_half") return "上下文超限 · 仅携带最近 50% 逐字稿";
  if (message.transcript_scope === "legacy") return "历史问答";
  return "未携带逐字稿";
}

function renderMessage(message, pending = false) {
  if (el.messages.classList.contains("empty-state")) {
    el.messages.classList.remove("empty-state");
    el.messages.textContent = "";
  }
  const node = document.createElement("div");
  node.className = `message ${message.role}`;
  const content = document.createElement("div");
  if (message.role === "assistant") {
    content.className = "markdown-body";
    window.renderMarkdownSafe(content, message.content);
  } else {
    content.textContent = message.content;
  }
  node.append(content);
  if (message.role === "user") {
    const meta = document.createElement("div");
    meta.className = `message-meta${message.transcript_scope === "recent_half" ? " warning" : ""}`;
    meta.textContent = pending ? "正在发送…" : transcriptScopeLabel(message);
    node.append(meta);
  }
  el.messages.append(node);
  el.messages.scrollTop = el.messages.scrollHeight;
  return node;
}

function renderMessages() {
  el.messages.textContent = "";
  el.messages.classList.toggle("empty-state", state.messages.length === 0);
  if (!state.messages.length) {
    el.messages.textContent = "当前 Session 尚无问答。";
  } else {
    state.messages.forEach((message) => renderMessage(message));
  }
  const rounds = state.messages.filter((message) => message.role === "user").length;
  el.roundCount.textContent = `${rounds} 轮`;
  el.chatTabMeta.textContent = `${rounds} 轮`;
}

function updateViewTabs() {
  const transcriptActive = state.activeView === "transcript";
  el.transcriptPane.classList.toggle("hidden", !transcriptActive);
  el.chatPane.classList.toggle("hidden", transcriptActive);
  el.workspace.classList.toggle("transcript-view", transcriptActive);
  el.workspace.classList.toggle("chat-view", !transcriptActive);
  el.transcriptViewButton.classList.toggle("active", transcriptActive);
  el.chatViewButton.classList.toggle("active", !transcriptActive);
  el.transcriptViewButton.setAttribute("aria-selected", String(transcriptActive));
  el.chatViewButton.setAttribute("aria-selected", String(!transcriptActive));
  if (transcriptActive) {
    state.unseenTranscriptSegments = 0;
    scrollTranscriptToLatest();
  }
  el.unseenTranscriptBadge.textContent = state.unseenTranscriptSegments
    ? `新增 ${state.unseenTranscriptSegments} 段`
    : "";
  el.unseenTranscriptBadge.classList.toggle("hidden", state.unseenTranscriptSegments === 0);
}

function setActiveView(view, { focusQuestion = false } = {}) {
  state.activeView = view === "chat" ? "chat" : "transcript";
  updateViewTabs();
  if (focusQuestion) requestAnimationFrame(() => el.question.focus());
}

function enableSessionActions(enabled) {
  el.question.disabled = !enabled;
  el.askButton.disabled = !enabled;
  el.includeTranscript.disabled = !enabled;
  document.querySelectorAll("[data-format]").forEach((button) => { button.disabled = !enabled; });
}

function updateCaptureControls() {
  const busy = state.capturing || state.starting;
  el.startButton.disabled = busy;
  el.startButton.textContent = state.starting
    ? "正在启动…"
    : (state.capturing ? "正在采集" : (state.sessionId ? "继续采集" : "开始采集"));
  el.startButton.classList.toggle("hidden", state.capturing);
  el.stopButton.classList.toggle("hidden", !state.capturing);
  el.stopButton.disabled = !state.capturing;
  el.provider.disabled = busy;
  el.language.disabled = busy;
  el.localProviderButton.disabled = busy;
  el.qwenProviderButton.disabled = busy;
  el.asrModelSummary.disabled = busy || el.provider.value === "local-funasr";
  el.asrSettingsButton.disabled = busy;
  el.newSessionButton.disabled = busy || !state.sessionId;
  el.liveDot.classList.toggle("idle", !state.capturing);
}

function updateProviderUI() {
  const cloud = el.provider.value === "qwen-cloud";
  el.localProviderButton.classList.toggle("active", !cloud);
  el.localProviderButton.setAttribute("aria-pressed", String(!cloud));
  el.qwenProviderButton.classList.toggle("active", cloud);
  el.qwenProviderButton.setAttribute("aria-pressed", String(cloud));
  el.asrSettingsButton.classList.toggle("hidden", !cloud);
  if (cloud) {
    const model = state.asrConfig?.model || "qwen-audio-3.1-asr-flash-streaming";
    el.asrModelSummary.value = model;
    el.providerPrice.textContent = model.includes("3.0") ? "约 ¥1.19 / 小时" : "3.1 按 Token 计费";
    el.providerDetail.textContent = state.asrConfig?.has_api_key
      ? "阿里云配置已保存 · 专业词和页面上下文将在新 Session 生效。"
      : "尚未配置 DashScope API Key；请先点击“配置”。";
  } else {
    el.asrModelSummary.value = "local-funasr";
    el.providerPrice.textContent = "本地免费";
    el.providerDetail.textContent = "本地模型已加载后，音频不会离开本机。";
  }
  const languageLabels = { auto: "自动语言", zh: "中文", en: "English" };
  const providerLabel = cloud ? "阿里云识别" : "本地识别";
  const modelLabel = cloud
    ? (el.asrModelSummary.selectedOptions[0]?.textContent || "Qwen 实时识别")
    : "FunASR";
  el.captureConfigTitle.textContent = `${providerLabel} · ${languageLabels[el.language.value] || "自动语言"}`;
  el.captureConfigMeta.textContent = `${modelLabel} · 点击调整`;
  updateCaptureControls();
}

async function selectProvider(provider) {
  if (state.capturing) {
    setStatus("请先结束当前 Session，再切换转写方式。", true);
    return;
  }
  el.provider.value = provider;
  await chrome.storage.local.set({ provider });
  updateProviderUI();
  await checkServer();
}

async function loadSession(sessionId, capturing = false) {
  const session = await api(`/api/sessions/${sessionId}`);
  state.sessionId = session.id;
  state.session = session;
  state.capturing = capturing;
  state.segments = session.segments || [];
  state.messages = session.messages || [];
  el.pageTitle.textContent = session.title || "未命名网页";
  el.pageUrl.textContent = session.url || "";
  renderTranscript();
  renderMessages();
  state.unseenTranscriptSegments = 0;
  setActiveView("transcript");
  enableSessionActions(true);
  updateCaptureControls();
  setStatus(
    capturing
      ? "已恢复正在进行的 Session。"
      : "已加载历史 Session；可继续采集追加内容，或新建 Session。"
  );
}

function clearSessionView() {
  state.sessionId = null;
  state.session = null;
  state.segments = [];
  state.messages = [];
  state.capturing = false;
  state.starting = false;
  renderTranscript();
  renderMessages();
  state.unseenTranscriptSegments = 0;
  setActiveView("transcript");
  enableSessionActions(false);
  updateCaptureControls();
  if (state.page) {
    el.pageTitle.textContent = state.page.title || "未命名网页";
    el.pageUrl.textContent = state.page.url || "";
  }
  setStatus("点击工具栏授权当前标签页，然后在这里手动开始采集。");
}

function setCaptureConfigOpen(open) {
  el.captureConfigPanel.classList.toggle("hidden", !open);
  el.captureConfigSummary.setAttribute("aria-expanded", String(open));
}

async function prepareNewSession() {
  if (state.capturing || state.starting) {
    setStatus("请先结束当前采集，再新建 Session。", true);
    return;
  }
  await chrome.storage.local.remove("lastSessionId");
  clearSessionView();
  closeModal(el.historyModal);
  setStatus("已准备全新 Session；配置参数后点击“开始采集”。");
}

function openModal(modal) {
  modal.classList.remove("hidden");
}

function closeModal(modal) {
  modal.classList.add("hidden");
}

function archiveMatches(session, query) {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return true;
  return `${session.title} ${session.url}`.toLowerCase().includes(normalized);
}

function renderArchive() {
  const query = el.historySearch.value;
  const sessions = state.archives.filter((session) => archiveMatches(session, query));
  el.archiveList.textContent = "";
  el.archiveList.classList.toggle("empty-state", sessions.length === 0);
  if (!sessions.length) {
    el.archiveList.textContent = query ? "没有匹配的 Session。" : "还没有历史 Session。";
    return;
  }
  sessions.forEach((session) => {
    const row = document.createElement("article");
    row.className = `archive-item${session.id === state.sessionId ? " active" : ""}`;
    const main = document.createElement("button");
    main.type = "button";
    main.className = "archive-main";
    const title = document.createElement("div");
    title.className = "archive-title";
    title.textContent = session.title || "未命名网页";
    const meta = document.createElement("div");
    meta.className = "archive-meta";
    const rounds = Math.floor((session.message_count || 0) / 2);
    meta.textContent = `${archiveTime(session.created_at)} · ${session.segment_count} 段 · ${rounds} 轮问答`;
    main.append(title, meta);
    main.addEventListener("click", async () => {
      if (state.capturing && session.id !== state.sessionId) {
        setStatus("请先结束当前正在采集的 Session。", true);
        return;
      }
      await loadSession(session.id, session.id === state.sessionId && state.capturing);
      await chrome.storage.local.set({ lastSessionId: session.id });
      closeModal(el.historyModal);
    });

    const actions = document.createElement("div");
    actions.className = "archive-actions";
    const rename = document.createElement("button");
    rename.type = "button";
    rename.textContent = "重命名";
    rename.disabled = state.capturing && session.id === state.sessionId;
    rename.addEventListener("click", () => beginRename(session));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "delete";
    remove.textContent = "删除";
    remove.disabled = state.capturing && session.id === state.sessionId;
    remove.addEventListener("click", () => beginDelete(session));
    actions.append(rename, remove);
    row.append(main, actions);
    el.archiveList.append(row);
  });
}

async function refreshArchive() {
  try {
    const result = await api("/api/sessions?limit=100");
    state.archives = result.sessions || [];
    renderArchive();
  } catch (error) {
    el.archiveList.classList.add("empty-state");
    el.archiveList.textContent = `读取历史失败：${error.message}`;
  }
}

function beginRename(session) {
  state.renameTarget = session;
  cancelDelete();
  el.renameForm.classList.remove("hidden");
  el.renameInput.value = session.title || "";
  el.renameInput.focus();
  el.renameInput.select();
}

function cancelRename() {
  state.renameTarget = null;
  el.renameForm.classList.add("hidden");
}

async function renameSession(event) {
  event.preventDefault();
  if (!state.renameTarget) return;
  const result = await api(`/api/sessions/${state.renameTarget.id}`, {
    method: "PATCH",
    body: JSON.stringify({ title: el.renameInput.value.trim() })
  });
  if (result.id === state.sessionId) {
    state.session = result;
    el.pageTitle.textContent = result.title;
  }
  cancelRename();
  await refreshArchive();
  setStatus("Session 已重命名。", false);
}

function beginDelete(session) {
  state.deleteTarget = session;
  state.renameTarget = null;
  el.renameForm.classList.add("hidden");
  el.deleteTargetTitle.textContent = session.title || "未命名网页";
  el.deleteStatus.textContent = "";
  el.deleteStatus.className = "form-status";
  if (!el.deleteDialog.open) el.deleteDialog.showModal();
}

function cancelDelete() {
  state.deleteTarget = null;
  el.deleteTargetTitle.textContent = "";
  el.deleteStatus.textContent = "";
  if (el.deleteDialog.open) el.deleteDialog.close();
}

async function deleteSession() {
  if (!state.deleteTarget) return;
  const targetId = state.deleteTarget.id;
  el.confirmDeleteButton.disabled = true;
  el.deleteStatus.textContent = "正在删除…";
  el.deleteStatus.className = "form-status";
  try {
    await api(`/api/sessions/${targetId}`, { method: "DELETE" });
    cancelDelete();
    if (targetId === state.sessionId) {
      clearSessionView();
      await chrome.storage.local.remove("lastSessionId");
    }
    await refreshArchive();
    setStatus("Session 已删除。", false);
  } catch (error) {
    const oldServer = error.message === "Not Found" || error.message.startsWith("404 ");
    el.deleteStatus.textContent = oldServer
      ? "当前本机服务版本过旧，不支持删除。请先结束采集并重启服务。"
      : `删除失败：${error.message}`;
    el.deleteStatus.className = "form-status error";
  } finally {
    el.confirmDeleteButton.disabled = false;
  }
}

async function openHistory() {
  cancelRename();
  cancelDelete();
  el.historySearch.value = "";
  openModal(el.historyModal);
  await refreshArchive();
}

function setAsrSettingsStatus(text, type = "") {
  el.asrSettingsStatus.textContent = text;
  el.asrSettingsStatus.className = `form-status${type ? ` ${type}` : ""}`;
}

async function loadASRConfig() {
  const config = await api("/api/asr/config");
  state.asrConfig = config;
  el.asrRegion.value = config.region;
  el.asrModel.value = config.model;
  el.asrTerms.value = config.terms || "";
  el.asrUsePageContext.checked = Boolean(config.use_page_context);
  el.asrApiKey.value = "";
  el.asrApiKey.placeholder = config.has_api_key ? "已保存；不修改请保持为空" : "请输入 API Key";
  el.asrApiKeyHint.textContent = config.has_api_key
    ? "已有密钥保存在本机服务中；界面不会读取或回显。"
    : "尚未保存 DashScope API Key。";
  setAsrSettingsStatus("");
  updateProviderUI();
  return config;
}

async function openAsrSettings(preselectedModel = null) {
  openModal(el.asrSettingsModal);
  try {
    await loadASRConfig();
    if (preselectedModel) el.asrModel.value = preselectedModel;
  } catch (error) {
    setAsrSettingsStatus(`读取配置失败：${error.message}`, "error");
  }
}

function asrConfigPayload() {
  return {
    region: el.asrRegion.value,
    model: el.asrModel.value,
    api_key: el.asrApiKey.value.trim() || null,
    terms: el.asrTerms.value.trim(),
    use_page_context: el.asrUsePageContext.checked
  };
}

async function testASRConfig() {
  el.testAsrConfigButton.disabled = true;
  setAsrSettingsStatus("正在建立阿里云 WebSocket 验证连接…");
  try {
    await api("/api/asr/config/test", {
      method: "POST",
      body: JSON.stringify(asrConfigPayload())
    });
    setAsrSettingsStatus("连接验证成功；配置尚未保存。", "success");
  } catch (error) {
    setAsrSettingsStatus(`连接失败：${error.message}`, "error");
  } finally {
    el.testAsrConfigButton.disabled = false;
  }
}

async function saveASRConfig(event) {
  event.preventDefault();
  const submit = el.asrSettingsForm.querySelector('button[type="submit"]');
  submit.disabled = true;
  setAsrSettingsStatus("正在验证并保存…");
  try {
    const config = await api("/api/asr/config", {
      method: "PUT",
      body: JSON.stringify(asrConfigPayload())
    });
    state.asrConfig = config;
    el.asrApiKey.value = "";
    el.asrApiKey.placeholder = "已保存；不修改请保持为空";
    el.asrApiKeyHint.textContent = "已有密钥保存在本机服务中；界面不会读取或回显。";
    updateProviderUI();
    setAsrSettingsStatus("连接验证成功，配置已保存在本机；下个 Session 生效。", "success");
    await checkServer();
  } catch (error) {
    setAsrSettingsStatus(`保存失败，原配置未改变：${error.message}`, "error");
  } finally {
    submit.disabled = false;
  }
}

function setSettingsStatus(text, type = "") {
  el.settingsStatus.textContent = text;
  el.settingsStatus.className = `form-status${type ? ` ${type}` : ""}`;
}

async function loadLLMConfig() {
  const config = await api("/api/llm/config");
  el.llmProvider.value = config.provider;
  el.llmBaseUrl.value = config.base_url;
  el.llmModel.value = config.model;
  el.llmApiKey.value = "";
  el.llmApiKey.placeholder = config.has_api_key ? "已保存；不修改请保持为空" : "请输入 API Key";
  el.apiKeyHint.textContent = config.has_api_key
    ? "已有密钥保存在本机服务中；界面不会读取或回显。"
    : "尚未保存 API Key。";
  setSettingsStatus("");
}

async function openSettings() {
  openModal(el.settingsModal);
  try {
    await loadLLMConfig();
  } catch (error) {
    setSettingsStatus(`读取配置失败：${error.message}`, "error");
  }
}

function llmConfigPayload() {
  return {
    provider: el.llmProvider.value,
    base_url: el.llmBaseUrl.value.trim(),
    model: el.llmModel.value.trim(),
    api_key: el.llmApiKey.value.trim() || null
  };
}

async function testLLMConfig() {
  el.testConfigButton.disabled = true;
  setSettingsStatus("正在调用模型验证连接…");
  try {
    await api("/api/llm/config/test", {
      method: "POST",
      body: JSON.stringify(llmConfigPayload())
    });
    setSettingsStatus("连接验证成功；配置尚未保存。", "success");
  } catch (error) {
    setSettingsStatus(`连接失败：${error.message}`, "error");
  } finally {
    el.testConfigButton.disabled = false;
  }
}

async function saveLLMConfig(event) {
  event.preventDefault();
  const submit = el.settingsForm.querySelector('button[type="submit"]');
  submit.disabled = true;
  setSettingsStatus("正在验证并保存…");
  try {
    const config = await api("/api/llm/config", {
      method: "PUT",
      body: JSON.stringify(llmConfigPayload())
    });
    el.llmApiKey.value = "";
    el.llmApiKey.placeholder = "已保存；不修改请保持为空";
    el.apiKeyHint.textContent = config.has_api_key
      ? "已有密钥保存在本机服务中；界面不会读取或回显。"
      : "尚未保存 API Key。";
    setSettingsStatus("连接验证成功，配置已保存在本机。", "success");
  } catch (error) {
    setSettingsStatus(`保存失败，原配置未改变：${error.message}`, "error");
  } finally {
    submit.disabled = false;
  }
}

async function restoreSession() {
  try {
    const savedSettings = await chrome.storage.local.get(["provider", "language"]);
    if (savedSettings.provider) el.provider.value = savedSettings.provider;
    if (savedSettings.language) el.language.value = savedSettings.language;
    updateProviderUI();
    const status = await chrome.runtime.sendMessage({ type: "capture.status" });
    state.authorizedTab = status?.authorizedTab || null;
    const sessionId = status?.activeCapture?.sessionId || status?.lastSessionId;
    if (sessionId) {
      try {
        await loadSession(sessionId, Boolean(status.activeCapture));
      } catch (error) {
        if (String(error.message).includes("Session 不存在")) {
          await chrome.storage.local.remove("lastSessionId");
        } else {
          throw error;
        }
      }
    }
    if (status?.captureStarting && !status.activeCapture) {
      state.starting = true;
      updateCaptureControls();
      setStatus("正在创建 Session 并申请当前标签页音频流…");
    } else if (status?.lastCaptureError && !status.activeCapture) {
      setStatus(status.lastCaptureError, true);
      await chrome.storage.local.remove("lastCaptureError");
    } else if (status?.authorizedTab && !status.activeCapture) {
      setStatus("当前标签页已授权，请配置转写参数后点击“开始采集”。");
    }
  } catch (_error) {
    // Health status explains an offline server; stale Session ids are cleared above.
  }
}

async function startSession() {
  if (state.capturing || state.starting) return;
  setCaptureConfigOpen(false);
  state.starting = true;
  updateCaptureControls();
  setStatus("正在创建 Session 并启动标签页音频采集…");
  try {
    const response = await chrome.runtime.sendMessage({
      type: "capture.start",
      provider: el.provider.value,
      language: el.language.value,
      sessionId: state.sessionId || null
    });
    if (!response?.ok) throw new Error(response?.error || "无法开始标签页音频采集。");
  } catch (error) {
    state.starting = false;
    updateCaptureControls();
    setStatus(error.message, true);
  }
}

async function stopSession() {
  el.stopButton.disabled = true;
  setStatus("正在结束采集…已确认的逐字稿此前已实时保存。");
  const response = await chrome.runtime.sendMessage({ type: "capture.stop" });
  if (!response?.ok) {
    el.stopButton.disabled = false;
    setStatus(response?.error || "无法结束当前 Session。", true);
    return;
  }
  state.capturing = false;
  state.starting = false;
  updateCaptureControls();
  setStatus("Session 已保存，可继续提问、下载或管理历史。", false);
  if (state.sessionId) await loadSession(state.sessionId, false);
  await refreshArchive();
}

async function askQuestion(event) {
  event.preventDefault();
  const question = el.question.value.trim();
  if (!question || !state.sessionId) return;
  setActiveView("chat");
  const includeTranscript = el.includeTranscript.checked;
  const pending = renderMessage({
    role: "user",
    content: question,
    include_transcript: includeTranscript,
    transcript_scope: includeTranscript ? "full" : "none"
  }, true);
  el.question.value = "";
  el.askButton.disabled = true;
  el.includeTranscript.disabled = true;
  try {
    const response = await api(`/api/sessions/${state.sessionId}/chat`, {
      method: "POST",
      body: JSON.stringify({ question, include_transcript: includeTranscript })
    });
    pending.remove();
    state.messages.push(response.user_message, response.assistant_message);
    renderMessage(response.user_message);
    renderMessage(response.assistant_message);
    const rounds = state.messages.filter((message) => message.role === "user").length;
    el.roundCount.textContent = `${rounds} 轮`;
    el.chatTabMeta.textContent = `${rounds} 轮`;
  } catch (error) {
    pending.classList.add("failed");
    const meta = pending.querySelector(".message-meta");
    if (meta) meta.textContent = `发送失败 · 未保存：${error.message}`;
  } finally {
    el.askButton.disabled = false;
    el.includeTranscript.disabled = false;
    el.question.focus();
  }
}

async function download(format) {
  if (!state.sessionId) return;
  const response = await fetch(`${API_BASE}/api/sessions/${state.sessionId}/export?format=${format}`);
  if (!response.ok) {
    setStatus(`导出失败：${response.statusText}`, true);
    return;
  }
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") || "";
  const encoded = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  const simple = disposition.match(/filename="?([^";]+)"?/i);
  const filename = encoded ? decodeURIComponent(encoded[1]) : (simple?.[1] || `study-session.${format}`);
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  el.downloadMenu.classList.add("hidden");
  el.downloadButton.setAttribute("aria-expanded", "false");
}

chrome.runtime.onMessage.addListener((message) => {
  if (message.target !== "sidepanel") return;
  if (message.type === "transcript.partial") {
    el.partialTranscript.textContent = message.text;
    el.partialTranscript.classList.toggle("hidden", !message.text);
    scrollTranscriptToLatest();
  } else if (message.type === "transcript.final") {
    el.partialTranscript.classList.add("hidden");
    state.segments.push(message.segment);
    appendSegmentToTranscript(message.segment);
    const characterCount = state.segments.reduce((sum, segment) => sum + segmentText(segment).length, 0);
    el.transcriptCount.textContent = `${characterCount.toLocaleString("zh-CN")} 字`;
    el.transcriptTabMeta.textContent = `${characterCount.toLocaleString("zh-CN")} 字`;
    el.contextSize.textContent = `${characterCount.toLocaleString("zh-CN")} 字`;
    if (state.activeView === "chat") {
      state.unseenTranscriptSegments += 1;
      updateViewTabs();
    }
    setStatus(`实时转写中 · 已自动保存 ${state.segments.length} 段`);
  } else if (message.type === "provider.ready") {
    if (state.mediaPlayback.known && !state.mediaPlayback.playing) {
      setMediaPlaybackState(state.mediaPlayback);
    } else {
      setStatus(`转写引擎已连接：${message.provider}`);
    }
  } else if (message.type === "provider.loading") {
    setStatus("正在加载本地 ASR 模型…");
  } else if (message.type === "provider.warming") {
    setStatus("模型已加载，正在预热 GPU…");
  } else if (message.type === "capture.preparing") {
    state.starting = true;
    updateCaptureControls();
    setStatus("正在创建 Session 并申请标签页音频流…");
  } else if (message.type === "capture.started") {
    state.starting = false;
    state.capturing = true;
    state.mediaPlayback = message.mediaState || { known: false, playing: true };
    updateCaptureControls();
    if (state.mediaPlayback.known && !state.mediaPlayback.playing) {
      setMediaPlaybackState(state.mediaPlayback);
    } else {
      setStatus("已获得标签页音频，正在连接转写引擎…");
    }
    if (message.sessionId) {
      loadSession(message.sessionId, true)
        .then(() => {
          setMediaPlaybackState(state.mediaPlayback);
          return refreshArchive();
        })
        .catch((error) => setStatus(`载入 Session 失败：${error.message}`, true));
    }
  } else if (message.type === "capture.already-active") {
    state.starting = false;
    state.capturing = true;
    updateCaptureControls();
    setStatus("当前已有一个正在进行的 Session。");
    if (message.sessionId && message.sessionId !== state.sessionId) {
      loadSession(message.sessionId, true).catch((error) => setStatus(error.message, true));
    }
  } else if (message.type === "capture.error") {
    state.starting = false;
    updateCaptureControls();
    setStatus(message.error || "音频采集失败。", true);
  } else if (message.type === "capture.stopped") {
    state.starting = false;
    state.capturing = false;
    state.mediaPlayback = { known: false, playing: true };
    updateCaptureControls();
    refreshArchive();
  } else if (message.type === "media.playback") {
    setMediaPlaybackState(message.state);
  } else if (message.type === "capture.authorized") {
    state.authorizedTab = message.tab || null;
    if (message.tab && !state.capturing) {
      state.page = message.tab;
      el.pageTitle.textContent = message.tab.title || "未命名网页";
      el.pageUrl.textContent = message.tab.url || "";
      setStatus("当前标签页已授权，请配置转写参数后点击“开始采集”。");
    }
  } else if (message.type === "capture.authorization-expired") {
    state.authorizedTab = null;
    if (!state.capturing) {
      setStatus("页面地址已变化，请重新点击工具栏图标授权当前标签页。", true);
    }
  }
});

el.startButton.addEventListener("click", startSession);
el.stopButton.addEventListener("click", stopSession);
el.chatForm.addEventListener("submit", askQuestion);
el.captureConfigSummary.addEventListener("click", (event) => {
  event.stopPropagation();
  setCaptureConfigOpen(el.captureConfigPanel.classList.contains("hidden"));
});
el.closeCaptureConfigButton.addEventListener("click", () => setCaptureConfigOpen(false));
el.localProviderButton.addEventListener("click", () => selectProvider("local-funasr"));
el.qwenProviderButton.addEventListener("click", () => selectProvider("qwen-cloud"));
el.asrSettingsButton.addEventListener("click", () => openAsrSettings());
el.asrModelSummary.addEventListener("change", () => {
  if (el.provider.value === "qwen-cloud") openAsrSettings(el.asrModelSummary.value);
});
el.language.addEventListener("change", () => {
  chrome.storage.local.set({ language: el.language.value });
  updateProviderUI();
});

el.transcriptViewButton.addEventListener("click", () => setActiveView("transcript"));
el.chatViewButton.addEventListener("click", () => setActiveView("chat", { focusQuestion: true }));
el.question.addEventListener("focus", () => setActiveView("chat"));
el.question.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" || event.shiftKey || event.isComposing || event.keyCode === 229) return;
  event.preventDefault();
  if (!el.askButton.disabled && el.question.value.trim()) el.chatForm.requestSubmit();
});

el.downloadButton.addEventListener("click", (event) => {
  event.stopPropagation();
  const opening = el.downloadMenu.classList.contains("hidden");
  el.downloadMenu.classList.toggle("hidden", !opening);
  el.downloadButton.setAttribute("aria-expanded", String(opening));
});
document.querySelectorAll("[data-format]").forEach((button) => {
  button.addEventListener("click", () => download(button.dataset.format));
});

el.historyButton.addEventListener("click", openHistory);
el.newSessionButton.addEventListener("click", prepareNewSession);
el.closeHistoryButton.addEventListener("click", () => closeModal(el.historyModal));
el.historySearch.addEventListener("input", renderArchive);
el.renameForm.addEventListener("submit", (event) => {
  renameSession(event).catch((error) => setStatus(`重命名失败：${error.message}`, true));
});
el.cancelRenameButton.addEventListener("click", cancelRename);
el.cancelDeleteButton.addEventListener("click", cancelDelete);
el.cancelDeleteIconButton.addEventListener("click", cancelDelete);
el.confirmDeleteButton.addEventListener("click", deleteSession);
el.deleteDialog.addEventListener("cancel", (event) => {
  event.preventDefault();
  cancelDelete();
});
el.deleteDialog.addEventListener("click", (event) => {
  if (event.target === el.deleteDialog) cancelDelete();
});

el.modelSettingsButton.addEventListener("click", openSettings);
el.closeSettingsButton.addEventListener("click", () => closeModal(el.settingsModal));
el.testConfigButton.addEventListener("click", testLLMConfig);
el.settingsForm.addEventListener("submit", saveLLMConfig);
el.toggleApiKeyButton.addEventListener("click", () => {
  el.llmApiKey.type = el.llmApiKey.type === "password" ? "text" : "password";
});

el.closeAsrSettingsButton.addEventListener("click", () => closeModal(el.asrSettingsModal));
el.testAsrConfigButton.addEventListener("click", testASRConfig);
el.asrSettingsForm.addEventListener("submit", saveASRConfig);
el.toggleAsrApiKeyButton.addEventListener("click", () => {
  el.asrApiKey.type = el.asrApiKey.type === "password" ? "text" : "password";
});

document.addEventListener("click", (event) => {
  if (!event.target.closest(".capture-strip")) setCaptureConfigOpen(false);
  if (!event.target.closest(".popover-anchor")) {
    el.downloadMenu.classList.add("hidden");
    el.downloadButton.setAttribute("aria-expanded", "false");
  }
  if (event.target === el.historyModal) closeModal(el.historyModal);
  if (event.target === el.settingsModal) closeModal(el.settingsModal);
  if (event.target === el.asrSettingsModal) closeModal(el.asrSettingsModal);
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  setCaptureConfigOpen(false);
  el.downloadMenu.classList.add("hidden");
  cancelDelete();
  closeModal(el.historyModal);
  closeModal(el.settingsModal);
  closeModal(el.asrSettingsModal);
});

new MutationObserver(scrollTranscriptToLatest).observe(el.transcript.parentElement, {
  childList: true,
  subtree: true,
  characterData: true
});

setActiveView("transcript");
enableSessionActions(false);
updateProviderUI();
Promise.all([checkServer(), loadCurrentTab(), loadASRConfig(), restoreSession(), refreshArchive()]);
