const SERVER_WS = "ws://127.0.0.1:8765/ws/transcribe";

let mediaStream = null;
let audioContext = null;
let processorNode = null;
let sourceNode = null;
let silentGain = null;
let socket = null;
let captureStartedAt = null;
let stopping = false;
let mediaPlaybackState = { known: false, playing: true, playbackRate: 1, observedAt: 0 };

function applyMediaPlaybackState(state) {
  if (!state || Number(state.observedAt || 0) < Number(mediaPlaybackState.observedAt || 0)) return;
  mediaPlaybackState = {
    known: Boolean(state.known),
    playing: state.known ? Boolean(state.playing) : true,
    playbackRate: Number(state.playbackRate || 1),
    observedAt: Number(state.observedAt || Date.now())
  };
}

function downsampleTo16k(float32, sourceRate) {
  if (sourceRate === 16000) return float32;
  const ratio = sourceRate / 16000;
  const outputLength = Math.floor(float32.length / ratio);
  const output = new Float32Array(outputLength);
  let offset = 0;
  for (let i = 0; i < outputLength; i += 1) {
    const nextOffset = Math.floor((i + 1) * ratio);
    let sum = 0;
    let count = 0;
    for (; offset < nextOffset && offset < float32.length; offset += 1) {
      sum += float32[offset];
      count += 1;
    }
    output[i] = count ? sum / count : 0;
  }
  return output;
}

function floatToPcm16(samples) {
  const buffer = new ArrayBuffer(samples.length * 2);
  const view = new DataView(buffer);
  for (let i = 0; i < samples.length; i += 1) {
    const value = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(i * 2, value < 0 ? value * 0x8000 : value * 0x7fff, true);
  }
  return buffer;
}

function emitToUi(payload) {
  chrome.runtime.sendMessage({ target: "sidepanel", ...payload }).catch(() => {});
}

async function stopCapture(reason = "user") {
  stopping = true;
  if (socket?.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: "stop", reason }));
    await Promise.race([
      new Promise((resolve) => socket.addEventListener("close", resolve, { once: true })),
      new Promise((resolve) => setTimeout(resolve, 5000))
    ]);
  }
  processorNode?.disconnect();
  sourceNode?.disconnect();
  silentGain?.disconnect();
  mediaStream?.getTracks().forEach((track) => track.stop());
  if (audioContext && audioContext.state !== "closed") await audioContext.close();

  mediaStream = null;
  audioContext = null;
  processorNode = null;
  sourceNode = null;
  silentGain = null;
  captureStartedAt = null;

  if (socket && socket.readyState < WebSocket.CLOSING) socket.close(1000, reason);
  socket = null;
  emitToUi({ type: "capture.stopped", reason });
  chrome.runtime.sendMessage({ target: "background", type: "capture.ended", reason }).catch(() => {});
  stopping = false;
}

async function startCapture(message) {
  await stopCapture("restart");
  stopping = false;
  captureStartedAt = Date.now();
  applyMediaPlaybackState(message.mediaState);

  mediaStream = await navigator.mediaDevices.getUserMedia({
    audio: {
      mandatory: {
        chromeMediaSource: "tab",
        chromeMediaSourceId: message.streamId
      }
    },
    video: false
  });

  audioContext = new AudioContext();
  await audioContext.resume();
  sourceNode = audioContext.createMediaStreamSource(mediaStream);

  // tabCapture suppresses the tab's normal audio output. Reconnect it explicitly.
  sourceNode.connect(audioContext.destination);

  processorNode = audioContext.createScriptProcessor(4096, 1, 1);
  silentGain = audioContext.createGain();
  silentGain.gain.value = 0;
  sourceNode.connect(processorNode);
  processorNode.connect(silentGain);
  silentGain.connect(audioContext.destination);

  socket = new WebSocket(SERVER_WS);
  socket.binaryType = "arraybuffer";

  socket.addEventListener("open", () => {
    socket.send(JSON.stringify({
      type: "start",
      session_id: message.sessionId,
      provider: message.provider,
      language: message.language,
      sample_rate: 16000,
      format: "pcm_s16le",
      page: { title: message.title, url: message.url, tab_id: message.tabId }
    }));
    emitToUi({
      type: "capture.started",
      sessionId: message.sessionId,
      startedAt: captureStartedAt,
      mediaState: mediaPlaybackState
    });
  });

  socket.addEventListener("message", (event) => {
    try {
      emitToUi(JSON.parse(event.data));
    } catch (_error) {
      emitToUi({ type: "capture.error", error: "本机服务返回了无法解析的数据。" });
    }
  });

  socket.addEventListener("error", () => {
    emitToUi({ type: "capture.error", error: "无法连接本机服务 ws://127.0.0.1:8765。" });
  });

  socket.addEventListener("close", (event) => {
    if (mediaStream && !stopping) {
      if (event.code !== 1000) {
        emitToUi({
          type: "capture.error",
          error: event.reason || `转写连接已关闭（${event.code}）。`
        });
      }
      stopCapture("socket-closed").catch((error) => {
        emitToUi({ type: "capture.error", error: error.message });
      });
    }
  });

  processorNode.onaudioprocess = (event) => {
    if (socket?.readyState !== WebSocket.OPEN) return;
    if (mediaPlaybackState.known && !mediaPlaybackState.playing) return;
    const input = event.inputBuffer.getChannelData(0);
    const downsampled = downsampleTo16k(input, audioContext.sampleRate);
    socket.send(floatToPcm16(downsampled));
  };

  mediaStream.getAudioTracks()[0]?.addEventListener("ended", () => stopCapture("track-ended"));
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message.target !== "offscreen") return false;

  if (message.type === "media.playback") {
    applyMediaPlaybackState(message.state);
    return false;
  }

  if (message.type === "capture.start") {
    startCapture(message)
      .then(() => sendResponse({ ok: true }))
      .catch((error) => {
        emitToUi({ type: "capture.error", error: error.message });
        sendResponse({ ok: false, error: error.message });
      });
    return true;
  }

  if (message.type === "capture.stop") {
    stopCapture("user")
      .then(() => sendResponse({ ok: true }))
      .catch((error) => sendResponse({ ok: false, error: error.message }));
    return true;
  }

  return false;
});
