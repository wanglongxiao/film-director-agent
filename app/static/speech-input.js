/* Explicit microphone capture, WAV encoding and server-side Seed-Speech ASR. */
"use strict";

function encodeSpeechWav(chunks, sampleRate, maxSeconds = 120) {
  const length = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const samples = new Float32Array(length);
  let offset = 0;
  for (const chunk of chunks) { samples.set(chunk, offset); offset += chunk.length; }
  const targetRate = 16000;
  const frames = Math.min(Math.floor(length * targetRate / sampleRate), maxSeconds * targetRate);
  const buffer = new ArrayBuffer(44 + frames * 2), view = new DataView(buffer);
  const text = (at, value) => [...value].forEach((letter, i) => view.setUint8(at + i, letter.charCodeAt(0)));
  text(0, "RIFF"); view.setUint32(4, buffer.byteLength - 8, true);
  text(8, "WAVE"); text(12, "fmt "); view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); view.setUint16(22, 1, true);
  view.setUint32(24, targetRate, true); view.setUint32(28, targetRate * 2, true);
  view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  text(36, "data"); view.setUint32(40, frames * 2, true);
  for (let i = 0; i < frames; i++) {
    // Average the input samples within each output interval when downsampling.
    const from = Math.floor(i * sampleRate / targetRate);
    const to = Math.max(from + 1, Math.floor((i + 1) * sampleRate / targetRate));
    let value = 0;
    for (let j = from; j < to && j < length; j++) value += samples[j];
    value = Math.max(-1, Math.min(1, value / (to - from)));
    view.setInt16(44 + i * 2, value < 0 ? value * 32768 : value * 32767, true);
  }
  return new Blob([buffer], { type: "audio/wav" });
}

window.createSpeechInput = function ({ button, input, status, getSession, onBusyChange }) {
  let enabled = false, maxSeconds = 120, phase = "idle";
  let stream, context, source, node, timer, chunks = [], sampleCount = 0, stopped;
  let session, discarded = false, aborter;
  const busy = () => phase !== "idle";
  function refresh(blocked = false) {
    button.textContent = t(phase === "recording" ? "stopRecording" : phase === "transcribing" ? "transcribing" : "recordAudio");
    button.setAttribute("aria-pressed", String(phase === "recording"));
    button.disabled = !enabled || phase === "starting" || phase === "transcribing"
      || (phase === "idle" && (blocked || !getSession()));
  }
  function setPhase(value) {
    phase = value;
    onBusyChange(busy());
    refresh();
  }
  async function release() {
    clearInterval(timer);
    stream?.getTracks().forEach(track => track.stop());
    node?.disconnect(); source?.disconnect();
    if (context && context.state !== "closed") await context.close();
    stream = context = source = node = null;
  }
  function fail(error) {
    const key = error?.name === "NotAllowedError" ? "micDenied"
      : error?.name === "NotFoundError" ? "micMissing" : "speech_failed";
    status.textContent = t(key);
  }
  async function start() {
    session = getSession(); discarded = false; chunks = []; sampleCount = 0;
    setPhase("starting"); status.textContent = t("micPermission");
    try {
      const AudioContext = window.AudioContext || window.webkitAudioContext;
      // Start the audio context in the user gesture, including on iOS.
      context = new AudioContext();
      await context.resume();
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      if (discarded) { await release(); setPhase("idle"); return; }
      await context.audioWorklet.addModule("/pcm-recorder.js?v=20261025-4");
      node = new AudioWorkletNode(context, "pcm-recorder");
      node.port.onmessage = event => {
        if (event.data.samples) {
          chunks.push(event.data.samples); sampleCount += event.data.samples.length;
        }
        if (event.data.stopped) stopped?.();
      };
      source = context.createMediaStreamSource(stream);
      source.connect(node);
      // The worklet outputs silence; connecting keeps Safari's processor active.
      node.connect(context.destination);
      setPhase("recording");
      const started = Date.now();
      status.textContent = t("recordingHint", { seconds: 0, max: maxSeconds });
      timer = setInterval(() => {
        const seconds = Math.floor((Date.now() - started) / 1000);
        status.textContent = t("recordingHint", { seconds, max: maxSeconds });
        if (seconds >= maxSeconds) stop();
      }, 250);
    } catch (error) {
      await release(); if (!discarded) fail(error); setPhase("idle");
    }
  }
  async function stop() {
    if (phase !== "recording") return;
    setPhase("transcribing"); clearInterval(timer); status.textContent = t("transcribingHint");
    try {
      const rate = context.sampleRate;
      await new Promise(resolve => {
        const timeout = setTimeout(resolve, 1000);
        stopped = () => { clearTimeout(timeout); resolve(); };
        node.port.postMessage("stop");
      });
      const audio = encodeSpeechWav(chunks, rate, maxSeconds);
      await release(); chunks = [];
      if (discarded) return;
      if (sampleCount / rate < 0.25) { status.textContent = t("speech_invalid_audio"); return; }
      aborter = new AbortController();
      const timeout = setTimeout(() => aborter.abort(), 75000);
      let response;
      try {
        response = await fetch(`/api/sessions/${session}/speech`, {
          method: "POST", headers: { "Content-Type": "audio/wav" }, body: audio,
          signal: aborter.signal,
        });
      } finally { clearTimeout(timeout); }
      const result = await response.json();
      if (discarded || getSession() !== session) return;
      if (!response.ok) { status.textContent = t(result.detail in window.I18N[document.documentElement.lang] ? result.detail : "speech_failed"); return; }
      // Preserve any text the user typed while waiting; do not send automatically.
      input.value = [input.value.trim(), result.text].filter(Boolean).join(" ");
      input.dispatchEvent(new Event("input", { bubbles: true }));
      status.textContent = t("speechReady"); input.focus();
    } catch (error) {
      if (!discarded) status.textContent = t(error.name === "AbortError" ? "speech_timeout" : "speech_failed");
    } finally {
      await release(); chunks = []; aborter = null; setPhase("idle");
    }
  }
  button.addEventListener("click", () => phase === "recording" ? stop() : phase === "idle" ? start() : null);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden && phase === "recording") stop();
  });
  window.addEventListener("pagehide", () => {
    discarded = true; aborter?.abort(); release(); chunks = [];
  });
  return {
    refresh,
    configure(settings) {
      maxSeconds = settings?.max_seconds || 120;
      enabled = !!settings?.enabled && window.isSecureContext
        && !!navigator.mediaDevices?.getUserMedia && !!window.AudioWorkletNode;
      if (!enabled) status.textContent = t(settings?.enabled ? "micUnsupported" : "speech_unavailable");
      refresh();
    },
  };
};
