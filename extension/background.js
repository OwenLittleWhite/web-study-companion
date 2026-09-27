const OFFSCREEN_URL = "offscreen.html";
const API_BASE = "http://127.0.0.1:8765";

// A toolbar action grants activeTab access for the current page. It only opens/authorizes the
// side panel; the user starts capture later after choosing the ASR settings.
chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: false }).catch(console.error);
chrome.storage.local.get("captureStarting").then(({ captureStarting }) => {
  if (captureStarting && Date.now() - captureStarting.startedAt > 30_000) {
    chrome.storage.local.remove("captureStarting");
  }
}).catch(() => {});

function emitToUi(payload) {
  chrome.runtime.sendMessage({ target: "sidepanel", ...payload }).catch(() => {});
}

function validateCapturableTab(tab) {
  const restricted = ["chrome://", "edge://", "chrome-extension://", "devtools://"];
  if (!tab?.id || !tab.url || restricted.some((prefix) => tab.url.startsWith(prefix))) {
    throw new Error("当前页面不允许标签页音频采集，请切换到普通网页后重试。");
  }
}

function sameOrigin(firstUrl, secondUrl) {
  try {
    return new URL(firstUrl).origin === new URL(secondUrl).origin;
  } catch (_error) {
    return false;
  }
}

function authorizationMatchesTab(authorization, tab) {
  return Boolean(
    authorization?.tabId
    && authorization.tabId === tab?.id
    && sameOrigin(authorization.url, tab.url)
  );
}

async function ensureOffscreenDocument() {
  const documentUrl = chrome.runtime.getURL(OFFSCREEN_URL);
  const contexts = await chrome.runtime.getContexts({
    contextTypes: ["OFFSCREEN_DOCUMENT"],
    documentUrls: [documentUrl]
  });
  if (contexts.length) return;

  await chrome.offscreen.createDocument({
    url: OFFSCREEN_URL,
    reasons: ["USER_MEDIA"],
    justification: "Capture active-tab audio for user-initiated live transcription."
  });
}

async function installMediaPlaybackMonitor(tabId) {
  const fallback = { known: false, playing: true, playbackRate: 1, observedAt: Date.now() };
  try {
    const results = await chrome.scripting.executeScript({
      target: { tabId },
      func: () => {
        const monitorKey = "__studyCompanionMediaPlaybackMonitor";
        globalThis[monitorKey]?.dispose?.();

        const mediaCandidates = () => Array.from(document.querySelectorAll("video, audio")).filter((media) => {
          if (media.tagName === "AUDIO") return true;
          const rect = media.getBoundingClientRect();
          return rect.width >= 120 && rect.height >= 60 || media.currentTime > 0 || !media.paused;
        });
        const snapshot = () => {
          const candidates = mediaCandidates();
          const active = candidates.filter(
            (media) => !media.paused && !media.ended && !media.seeking && media.readyState >= 3
          );
          const primary = active[0] || candidates[0] || null;
          return {
            known: candidates.length > 0,
            playing: candidates.length === 0 || active.length > 0,
            playbackRate: primary?.playbackRate || 1,
            currentTimeMs: primary ? Math.max(0, Math.round(primary.currentTime * 1000)) : null,
            observedAt: Date.now()
          };
        };

        let lastStateKey = "";
        const publish = (force = false) => {
          const state = snapshot();
          const stateKey = `${state.known}:${state.playing}:${state.playbackRate}`;
          if (!force && stateKey === lastStateKey) return state;
          lastStateKey = stateKey;
          chrome.runtime.sendMessage({ type: "media.playback", state }).catch(() => {});
          return state;
        };
        const events = [
          "play", "playing", "pause", "ended", "waiting", "stalled", "seeking", "seeked", "emptied"
        ];
        events.forEach((name) => document.addEventListener(name, publish, true));
        const observer = new MutationObserver(() => publish());
        observer.observe(document.documentElement, { childList: true, subtree: true });
        globalThis[monitorKey] = {
          dispose() {
            observer.disconnect();
            events.forEach((name) => document.removeEventListener(name, publish, true));
          }
        };
        return publish(true);
      }
    });
    return results[0]?.result || fallback;
  } catch (_error) {
    // Pages without an injectable standard media element keep the original audio-clock behavior.
    return fallback;
  }
}

async function removeMediaPlaybackMonitor(tabId) {
  if (!tabId) return;
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      func: () => {
        const monitorKey = "__studyCompanionMediaPlaybackMonitor";
        globalThis[monitorKey]?.dispose?.();
        delete globalThis[monitorKey];
      }
    });
  } catch (_error) {
    // Navigation, tab closure, or an expired activeTab grant already removes the old document monitor.
  }
}

async function createSession(tab, provider, language) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  let response;
  try {
    response = await fetch(`${API_BASE}/api/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: tab.title || "Untitled page",
        url: tab.url || "",
        provider,
        language
      }),
      signal: controller.signal
    });
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("本机服务 5 秒内没有响应；请等待 FunASR 启动完成后再试。");
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
  if (!response.ok) {
    let detail = `本机服务创建 Session 失败（${response.status}）。`;
    try {
      detail = (await response.json()).detail || detail;
    } catch (_error) {}
    throw new Error(detail);
  }
  return response.json();
}

async function loadExistingSession(sessionId) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 5000);
  let response;
  try {
    response = await fetch(`${API_BASE}/api/sessions/${encodeURIComponent(sessionId)}`, {
      signal: controller.signal
    });
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("本机服务 5 秒内没有响应，无法继续历史 Session。");
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
  if (!response.ok) {
    let detail = `读取历史 Session 失败（${response.status}）。`;
    try {
      detail = (await response.json()).detail || detail;
    } catch (_error) {}
    throw new Error(detail);
  }
  return response.json();
}

async function startAuthorizedCapture(tab, provider, language, requestedSessionId = null) {
  validateCapturableTab(tab);

  if (!['local-funasr', 'qwen-cloud'].includes(provider)) {
    throw new Error("不支持的转写方式。");
  }
  if (!['auto', 'zh', 'en'].includes(language)) {
    throw new Error("不支持的识别语言。");
  }

  const saved = await chrome.storage.local.get(["activeCapture", "captureStarting"]);
  if (saved.captureStarting) {
    if (Date.now() - saved.captureStarting.startedAt <= 30_000) {
      emitToUi({ type: "capture.preparing" });
      return saved.captureStarting;
    }
    await chrome.storage.local.remove("captureStarting");
  }
  if (saved.activeCapture) {
    const capturedTabs = await chrome.tabCapture.getCapturedTabs();
    const isStillCaptured = capturedTabs.some(
      (item) => item.tabId === saved.activeCapture.tab?.id && item.status === "active"
    );
    if (isStillCaptured) {
      emitToUi({ type: "capture.already-active", sessionId: saved.activeCapture.sessionId });
      return saved.activeCapture;
    }
    await chrome.storage.local.remove("activeCapture");
  }

  await chrome.storage.local.set({
    captureStarting: {
      tabId: tab.id,
      title: tab.title || "Untitled page",
      provider,
      language,
      sessionId: requestedSessionId,
      startedAt: Date.now()
    }
  });
  emitToUi({ type: "capture.preparing" });

  await ensureOffscreenDocument();
  const mediaState = await installMediaPlaybackMonitor(tab.id);

  let session = requestedSessionId ? await loadExistingSession(requestedSessionId) : null;
  // The toolbar action granted activeTab for this page. The grant remains valid on the same
  // origin, so the side-panel button can ask this service worker to consume it later.
  const streamId = await chrome.tabCapture.getMediaStreamId({ targetTabId: tab.id });
  if (!session) session = await createSession(tab, provider, language);
  const response = await chrome.runtime.sendMessage({
    target: "offscreen",
    type: "capture.start",
    streamId,
    sessionId: session.id,
    provider,
    language,
    mediaState,
    title: tab.title || "Untitled page",
    url: tab.url,
    tabId: tab.id
  });
  if (!response?.ok) throw new Error(response?.error || "离屏音频采集启动失败。");

  const activeCapture = {
    sessionId: session.id,
    provider,
    language,
    tab: { id: tab.id, title: tab.title, url: tab.url },
    startedAt: Date.now()
  };
  await chrome.storage.local.set({
    activeCapture,
    lastSessionId: session.id,
    lastCaptureError: null
  });
  await chrome.storage.local.remove("captureStarting");
  return activeCapture;
}

async function handleActionClick(tab) {
  validateCapturableTab(tab);
  const authorization = {
    tabId: tab.id,
    title: tab.title || "Untitled page",
    url: tab.url,
    authorizedAt: Date.now()
  };
  await Promise.all([
    chrome.sidePanel.open({ tabId: tab.id }),
    chrome.storage.session.set({ captureAuthorization: authorization })
  ]);
  emitToUi({ type: "capture.authorized", tab: authorization });
}

chrome.action.onClicked.addListener((tab) => {
  handleActionClick(tab).catch((error) => {
    chrome.storage.local.set({ lastCaptureError: error.message }).catch(() => {});
    emitToUi({ type: "capture.error", error: error.message });
  });
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.target === "offscreen") return false;

  if (message.type === "media.playback") {
    chrome.runtime.sendMessage({ target: "offscreen", type: "media.playback", state: message.state })
      .catch(() => {});
    emitToUi({ type: "media.playback", state: message.state });
    return false;
  }

  if (message.type === "capture.start") {
    Promise.all([
      chrome.storage.session.get("captureAuthorization"),
      chrome.tabs.query({ active: true, currentWindow: true })
    ]).then(async ([saved, [tab]]) => {
      const authorization = saved.captureAuthorization || null;
      if (!authorizationMatchesTab(authorization, tab)) {
        throw new Error("请先点击浏览器工具栏中的 Study Companion 图标，授权当前标签页后再开始采集。");
      }
      const activeCapture = await startAuthorizedCapture(
        tab,
        message.provider || "local-funasr",
        message.language || "auto",
        message.sessionId || null
      );
      sendResponse({ ok: true, activeCapture });
    }).catch(async (error) => {
      await chrome.storage.local.remove("captureStarting");
      await chrome.storage.local.set({ lastCaptureError: error.message });
      const permissionExpired = /invoked|activeTab|permission/i.test(error.message);
      const detail = permissionExpired
        ? "当前页面的采音授权已失效，请重新点击工具栏图标授权后再试。"
        : error.message;
      sendResponse({ ok: false, error: detail });
    });
    return true;
  }

  if (message.type === "capture.stop") {
    chrome.storage.local.get("activeCapture")
      .then(async ({ activeCapture }) => {
        const response = await chrome.runtime.sendMessage({ target: "offscreen", type: "capture.stop" });
        if (!response?.ok) throw new Error(response?.error || "无法停止音频采集。");
        await removeMediaPlaybackMonitor(activeCapture?.tab?.id);
        await chrome.storage.local.remove(["activeCapture", "captureStarting"]);
        sendResponse({ ok: true });
      })
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (message.type === "capture.ended") {
    chrome.storage.local.get("activeCapture").then(async ({ activeCapture }) => {
      await removeMediaPlaybackMonitor(activeCapture?.tab?.id);
      await chrome.storage.local.remove(["activeCapture", "captureStarting"]);
    }).catch(() => {});
    return false;
  }

  if (message.type === "capture.status") {
    Promise.all([
      chrome.storage.local.get([
        "activeCapture", "captureStarting", "lastCaptureError", "lastSessionId"
      ]),
      chrome.storage.session.get("captureAuthorization"),
      chrome.tabCapture.getCapturedTabs(),
      chrome.tabs.query({ active: true, currentWindow: true })
    ]).then(async ([saved, authorizationState, capturedTabs, [tab]]) => {
      const active = saved.activeCapture || null;
      const authorization = authorizationState.captureAuthorization || null;
      const starting = saved.captureStarting && Date.now() - saved.captureStarting.startedAt <= 30_000
        ? saved.captureStarting
        : null;
      if (saved.captureStarting && !starting) await chrome.storage.local.remove("captureStarting");
      const isCaptured = Boolean(
        active?.tab?.id && capturedTabs.some(
          (item) => item.tabId === active.tab.id && item.status === "active"
        )
      );
      if (active && !isCaptured) await chrome.storage.local.remove("activeCapture");
      sendResponse({
        ok: true,
        activeCapture: isCaptured ? active : null,
        authorizedTab: authorizationMatchesTab(authorization, tab) ? authorization : null,
        captureStarting: starting,
        lastCaptureError: saved.lastCaptureError || null,
        lastSessionId: saved.lastSessionId || active?.sessionId || null
      });
    }).catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  if (message.type === "tab.current") {
    chrome.tabs.query({ active: true, currentWindow: true })
      .then(([tab]) => sendResponse({
        ok: Boolean(tab),
        tab: tab ? { id: tab.id, title: tab.title, url: tab.url } : null
      }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  return false;
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (!changeInfo.url) return;
  chrome.storage.session.get("captureAuthorization").then(({ captureAuthorization }) => {
    if (
      captureAuthorization?.tabId === tabId
      && !sameOrigin(captureAuthorization.url, changeInfo.url)
    ) {
      return chrome.storage.session.remove("captureAuthorization").then(() => {
        emitToUi({ type: "capture.authorization-expired" });
      });
    }
    return undefined;
  }).catch(() => {});
});

chrome.tabs.onRemoved.addListener((tabId) => {
  chrome.storage.session.get("captureAuthorization").then(({ captureAuthorization }) => {
    if (captureAuthorization?.tabId === tabId) {
      return chrome.storage.session.remove("captureAuthorization");
    }
    return undefined;
  }).catch(() => {});
});
