/* Browser-scoped history with one automatically chained chapter per request. */
"use strict";

// Match the visible viewport when a mobile keyboard or browser toolbar resizes it.
function updateViewportHeight() {
  document.documentElement.style.setProperty(
    "--app-height", `${window.visualViewport?.height || window.innerHeight}px`
  );
}
updateViewportHeight();
window.visualViewport?.addEventListener("resize", updateViewportHeight);
window.addEventListener("resize", updateViewportHeight);

const ui = {
  messages: document.getElementById("messages"),
  input: document.getElementById("input"),
  send: document.getElementById("send"),
  stop: document.getElementById("stop"),
  lang: document.getElementById("lang"),
  newTask: document.getElementById("new-task"),
  refTotal: document.getElementById("ref-total"),
  refGen: document.getElementById("ref-gen"),
  refOutput: document.getElementById("ref-output"),
  chapterCount: document.getElementById("chapter-count"),
  chapterLength: document.getElementById("chapter-length"),
  novelGen: document.getElementById("novel-gen"),
  wordExport: document.getElementById("word-export"),
  novelStatus: document.getElementById("novel-status"),
  manuscript: document.getElementById("manuscript"),
  viewChat: document.getElementById("view-chat"),
  viewNovel: document.getElementById("view-novel"),
  textModel: document.getElementById("text-model"),
  record: document.getElementById("record"),
  speechStatus: document.getElementById("speech-status"),
  history: document.getElementById("history-list"),
  historyPanel: document.getElementById("history-panel"),
  historyOpen: document.getElementById("history-open"),
  historyClose: document.getElementById("history-close"),
  historyShade: document.getElementById("history-shade"),
};

const app = {
  sid: null,
  language: "zh-CN",
  generating: false,
  aborter: null,
  prevScrollTop: 0,
  refBusy: false,
  state: null,
  novelBusy: false,
  exportBusy: false,
  stopRequest: null,
  textModel: "deepseek-1017",
  modelBusy: false,
  modelOptions: {},
  speechBusy: false,
};

const speechInput = window.createSpeechInput({
  button: ui.record, input: ui.input, status: ui.speechStatus,
  getSession: () => app.sid,
  onBusyChange: busy => { app.speechBusy = busy; updateNovelControls(); },
});
/* ------------------------------------------------------------------ */
/* Session / task lifecycle                                            */
/* ------------------------------------------------------------------ */

async function loadModels() {
  const res = await fetch("/api/models");
  if (!res.ok) throw new Error(t("modelLoadFail"));
  const data = await res.json();
  for (const [key, input] of [
    ["chapters_count", ui.chapterCount],
    ["chapter_length", ui.chapterLength],
    ["images_count", ui.refTotal],
  ]) {
    const settings = data.generation[key];
    input.min = settings.min;
    input.max = settings.max;
    input.defaultValue = settings.default;
    input.value = settings.default;
  }
  app.modelOptions = Object.fromEntries(data.models.map(model => [model.id, model]));
  ui.textModel.replaceChildren(...data.models.map(model => {
    const option = document.createElement("option");
    option.value = model.id;
    option.textContent = t("tokenBudget", model);
    return option;
  }));
  app.textModel = data.default;
  ui.textModel.value = app.textModel;
  speechInput.configure(data.speech);
}

async function createSession() {
  const res = await fetch("/api/sessions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ language: app.language, text_model: app.textModel }),
  });
  if (!res.ok) throw new Error(t("sessionCreateFail"));
  const data = await res.json();
  app.sid = data.session_id;
  localStorage.setItem("msa-active-task", app.sid);
  ui.messages.replaceChildren();
  showRefEmpty(t("refEmpty"));
  renderProject(data.state);
  appendSystem(t("newTaskReady"));
  await loadHistory();
}

async function loadHistory() {
  const res = await fetch("/api/sessions");
  if (!res.ok) throw new Error(await responseError(res));
  const { tasks } = await res.json();
  ui.history.innerHTML = tasks.length ? tasks.map(task => `
    <div class="history-row ${task.session_id === app.sid ? "selected" : ""}">
      <button class="history-select ghost" data-task="${esc(task.session_id)}">
        <span class="history-title">${esc(task.title)}</span>
        <span class="muted">${esc(new Date(task.updated_at * 1000).toLocaleString(app.language))}</span>
        <span class="muted">${task.completed}/${task.total} · ${esc(t("taskStatus_" + task.status))}</span>
      </button>
      <button class="history-delete ghost" data-delete="${esc(task.session_id)}"
        aria-label="${esc(t("deleteTask"))}" title="${esc(t("deleteTask"))}">×</button>
    </div>`).join("") : `<div class="empty">${esc(t("historyEmpty"))}</div>`;
}

function historyDrawer(open) {
  ui.historyPanel.classList.toggle("drawer-open", open);
  ui.historyShade.classList.toggle("hidden", !open);
  ui.historyOpen.setAttribute("aria-expanded", String(open));
  if (open) ui.historyClose.focus();
}

async function restoreSession(sid) {
  const res = await fetch(`/api/sessions/${sid}`);
  if (!res.ok) throw new Error(await responseError(res));
  const data = await res.json();
  app.sid = sid;
  localStorage.setItem("msa-active-task", sid);
  app.language = data.state.language;
  ui.lang.value = app.language;
  applyI18n(app.language);
  ui.messages.replaceChildren();
  for (const message of data.history) appendMessage(message.role, message.content);
  renderProject(data.state);
  ui.chapterCount.value = data.state.writing.chapters_count;
  ui.chapterLength.value = data.state.writing.chapter_length;
  const images = await fetch(`/api/sessions/${sid}/images`);
  const rows = images.ok ? (await images.json()).images : [];
  if (rows.length) renderReferences(rows);
  else showRefEmpty(t("refEmpty"));
  await loadHistory();
  historyDrawer(false);
  if (data.auto_run) generateNovel(true);
}

setInterval(() => {
  loadHistory().catch(() => {});
}, 20000);

/* ------------------------------------------------------------------ */
/* Chat                                                                */
/* ------------------------------------------------------------------ */

function appendSystem(text) {
  const el = document.createElement("div");
  el.className = "message system";
  el.textContent = text;
  ui.messages.appendChild(el);
  scrollToBottom();
}

function appendMessage(role, text) {
  const el = document.createElement("div");
  el.className = `message ${role}`;
  el.innerHTML = `<div class="avatar">${role === "user" ? "U" : "A"}</div>
    <div class="bubble"><div class="reply-text"></div></div>`;
  el.querySelector(".reply-text").textContent = text;
  ui.messages.appendChild(el);
  scrollToBottom();
}

function createAssistantPlaceholder() {
  const el = document.createElement("div");
  el.className = "message assistant streaming";
  el.innerHTML = `
    <div class="avatar">A</div>
    <div class="bubble">
      <div class="thought">
        <button class="thought-toggle" type="button"></button>
        <span class="thought-label"></span>
        <div class="thought-body"></div>
      </div>
      <div class="reply-text"></div>
    </div>`;
  el.querySelector(".thought-label").textContent = t("thinking");
  el.querySelector(".thought-toggle").setAttribute("aria-label", t("thoughtToggle"));
  ui.messages.appendChild(el);
  scrollToBottom();
  return el;
}

function scrollToBottom() {
  ui.messages.scrollTop = ui.messages.scrollHeight;
}

function setButtons(mode) {
  ui.send.classList.toggle("hidden", mode === "stop");
  ui.stop.classList.toggle("hidden", mode === "send");
  ui.lang.disabled = mode === "stop";
  ui.textModel.disabled = mode === "stop" || app.refBusy || app.modelBusy;
  ui.newTask.disabled = mode === "stop";
  ui.refGen.disabled = mode === "stop" || app.refBusy;
  ui.novelGen.disabled = mode === "stop" || !app.state?.characters?.length || !app.state?.outline;
  updateNovelControls();
}

function handleEvent(ev, els) {
  if (ev.type === "thought") {
    els.thought.classList.add("active");
    els.thoughtBody.textContent += ev.delta;
    scrollToBottom();
  } else if (ev.type === "output") {
    els.reply.textContent += ev.delta;
    scrollToBottom();
  } else if (ev.type === "done") {
    if (ev.reply) els.reply.textContent = ev.reply;
    els.msg.classList.remove("streaming");
    els.msg.classList.add("done");
    // After the actual output, the thought process collapses automatically.
    collapseThought(els.thought, true);
    renderProject(ev.state);
    scrollToBottom();
  } else if (ev.type === "interrupted") {
    rollback(els.msg);
  } else if (ev.type === "error") {
    els.msg.classList.remove("streaming");
    els.msg.querySelector(".reply-text").textContent =
      "\u26a0 " + (ev.localized ? ev.message : localizedError(ev.message));
    els.thought.remove();
  }
}

function collapseThought(thoughtEl, collapsed) {
  thoughtEl.classList.toggle("collapsed", collapsed);
  const label = thoughtEl.querySelector(".thought-label");
  label.textContent = collapsed ? t("thought") : t("thinking");
  thoughtEl.querySelector(".thought-toggle").setAttribute(
    "aria-expanded", collapsed ? "false" : "true"
  );
}

function rollback(msgEl) {
  // Remove the partial assistant output and scroll back to the previous state.
  msgEl.remove();
  ui.messages.scrollTop = app.prevScrollTop;
}

async function sendMessage() {
  const text = ui.input.value.trim();
  if (!text || !app.sid || app.generating || app.modelBusy || app.speechBusy) return;
  if (!ui.chapterCount.reportValidity() || !ui.chapterLength.reportValidity()) return;
  const writing = {
    chapters_count: Number(ui.chapterCount.value),
    chapter_length: Number(ui.chapterLength.value),
  };

  ui.input.value = "";
  appendMessage("user", text);
  app.prevScrollTop = ui.messages.scrollTop;

  app.generating = true;
  app.stopRequest = null;
  setButtons("stop");

  const els = {
    msg: createAssistantPlaceholder(),
    thought: null,
    thoughtBody: null,
    reply: null,
  };
  els.thought = els.msg.querySelector(".thought");
  els.thoughtBody = els.msg.querySelector(".thought-body");
  els.reply = els.msg.querySelector(".reply-text");

  app.aborter = new AbortController();
  try {
    const res = await fetch(`/api/sessions/${app.sid}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, ...writing }),
      signal: app.aborter.signal,
    });
    if (!res.ok || !res.body) throw new Error(await responseError(res));

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf("\n")) >= 0) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (!line) continue;
        let ev;
        try { ev = JSON.parse(line); } catch (_) { continue; }
        handleEvent(ev, els);
      }
    }
  } catch (err) {
    if (err.name === "AbortError") {
      rollback(els.msg); // Stop was pressed
    } else {
      handleEvent({ type: "error", localized: true, message: err instanceof TypeError ? t("networkFail") : err.message }, els);
    }
  } finally {
    if (app.stopRequest) await app.stopRequest;
    app.stopRequest = null;
    app.generating = false;
    app.aborter = null;
    setButtons("send");
    ui.input.focus();
  }
}

function stopGeneration() {
  if (!app.generating) return;
  if (app.aborter) app.aborter.abort(); // stops the client stream
  // Ask the backend to cancel the in-flight LLM call too.
  if (app.sid) requestStop(app.sid);
}

function requestStop(sid) {
  // Send one stop request and finish it before enabling a new generation.
  if (!app.stopRequest) {
    app.stopRequest = fetch(`/api/sessions/${sid}/stop`, { method: "POST" }).catch(() => {});
  }
  return app.stopRequest;
}

/* ------------------------------------------------------------------ */
/* Reference images (right panel)                                      */
/* ------------------------------------------------------------------ */

function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function renderProject(state) {
  app.state = state;
  app.textModel = state.text_model || "deepseek-1017";
  ui.textModel.value = app.textModel;
  if (!state.novel) {
    ui.chapterCount.value = state.writing.chapters_count;
    ui.chapterLength.value = state.writing.chapter_length;
  }
  renderManuscript();
  updateNovelControls();
}

function showView(novelView) {
  ui.messages.classList.toggle("hidden", novelView);
  ui.manuscript.classList.toggle("hidden", !novelView);
  ui.viewChat.className = novelView ? "ghost" : "secondary";
  ui.viewNovel.className = novelView ? "secondary" : "ghost";
}

function textLength(text) {
  return app.language === "en"
    ? (text.match(/\b[\w]+(?:['’-][\w]+)*\b/g) || []).length
    : Array.from(text.replace(/\s/g, "")).length;
}

function progressText() {
  const novel = app.state?.novel;
  if (!novel) return t("novelHint");
  const completed = novel.chapters.filter(c => c.content);
  return t("novelProgress", {
    done: completed.length, total: novel.chapters_count,
    length: completed.reduce((sum, c) => sum + textLength(c.content), 0),
  });
}

function updateNovelControls() {
  const novel = app.state?.novel;
  const completed = novel?.chapters.filter(c => c.content).length || 0;
  ui.textModel.disabled = app.generating || app.refBusy || app.modelBusy || app.speechBusy;
  ui.send.disabled = app.modelBusy || app.speechBusy;
  ui.lang.disabled = app.generating || app.refBusy || app.modelBusy || app.speechBusy;
  ui.newTask.disabled = app.generating || app.refBusy || app.modelBusy || app.speechBusy;
  for (const button of ui.history.querySelectorAll("button")) {
    button.disabled = app.generating || app.refBusy || app.modelBusy || app.speechBusy || app.exportBusy;
  }
  ui.novelGen.disabled = app.generating || app.refBusy || app.modelBusy || app.speechBusy
    || !app.state?.characters?.length || !app.state?.outline
    || (novel && completed === novel.chapters_count);
  ui.novelGen.textContent = t(novel ? "resumeNovel" : "generateNovel");
  ui.chapterCount.disabled = app.generating || !!novel;
  ui.chapterLength.disabled = app.generating || !!novel;
  if (novel) {
    ui.chapterCount.value = novel.chapters_count;
    ui.chapterLength.value = novel.chapter_length;
  }
  ui.wordExport.disabled = app.exportBusy || !(completed || app.state?.episodes?.length);
  speechInput.refresh(app.generating || app.refBusy || app.modelBusy);
}

function renderManuscript() {
  const novel = app.state?.novel;
  if (!novel) {
    ui.manuscript.innerHTML = `<div class="empty">${esc(t("novelEmpty"))}</div>`;
  } else {
    ui.manuscript.innerHTML = `<h1>${esc(novel.title)}</h1>` + novel.chapters.map(c => `
      <details class="chapter" id="chapter-${c.number}">
        <summary>${c.number}. ${esc(c.title)}</summary>
        <div class="chapter-synopsis">${esc(c.synopsis)}</div>
        <div class="chapter-content">${esc(c.content)}</div>
      </details>`).join("");
  }
  if (!app.novelBusy) ui.novelStatus.textContent = progressText();
  ui.novelStatus.title = ui.novelStatus.textContent;
}

const statusObserver = new MutationObserver(() => {
  ui.novelStatus.title = ui.novelStatus.textContent;
});
statusObserver.observe(ui.novelStatus, { childList: true, characterData: true, subtree: true });

async function selectTextModel() {
  if (!app.sid || app.generating || app.refBusy || app.modelBusy || app.speechBusy) return;
  const selected = ui.textModel.value;
  app.modelBusy = true;
  updateNovelControls();
  try {
    const res = await fetch(`/api/sessions/${app.sid}/model`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text_model: selected }),
    });
    if (!res.ok) throw new Error(await responseError(res));
    renderProject((await res.json()).state);
    appendSystem(t("modelSelected", app.modelOptions[selected]));
  } catch (err) {
    ui.textModel.value = app.textModel;
    appendSystem(err.message);
  } finally {
    app.modelBusy = false;
    updateNovelControls();
  }
}

function localizedError(message, status) {
  const messages = {
    "session not found": "taskMissing",
    "missing_prerequisites": "needPrereq",
    "请先完成角色侧写和故事大纲。": "needPrereq",
    "正文生成中，请先停止生成。": "generationBusy",
    "请先停止正文生成，再切换模型。": "generationBusy",
    "正文生成中，请勿重复提交。": "generationBusy",
    "已有章节规划，请使用原篇幅设置继续，或新建任务。": "planConflict",
    "请先生成至少一章正文或分镜剧本。": "exportPrereq",
    "Word 导出需要 Node.js，请安装 Node.js 并运行 npm ci。": "nodeRequired",
    "Word 导出失败，请确认已运行 npm ci。": "exportSetupFail",
  };
  if (messages[message]) return t(messages[message]);
  const chapter = /^第 (\d+) 章未达到目标篇幅/.exec(message || "");
  if (chapter) return t("chapterIncomplete", chapter[1]);
  const portrait = /^角色「(.+?)」的图片无法读取/.exec(message || "");
  if (portrait) return t("portraitReadFail", portrait[1]);
  if (/^章节规划/.test(message || "")) return t("planFailed");
  if (/^模型输出达到/.test(message || "")) return t("tokenLimit");
  if (status === 422) return t("validationFail");
  return status ? t("requestFail", status) : t("genericFail");
}

async function responseError(res) {
  try {
    const body = await res.json();
    return localizedError(body.detail, res.status);
  } catch (_) { return t("requestFail", res.status); }
}

async function generateNovel(resumeExisting = false) {
  if (!app.sid || app.generating || app.refBusy || app.modelBusy || app.speechBusy) return;
  if (!ui.chapterCount.checkValidity() || !ui.chapterLength.checkValidity()) {
    ui.chapterCount.reportValidity();
    ui.chapterLength.reportValidity();
    return;
  }
  const sid = app.sid;
  app.generating = true;
  app.novelBusy = true;
  app.stopRequest = null;
  app.aborter = new AbortController();
  setButtons("stop");
  updateNovelControls();
  showView(true);
  let completedStream = false;
  let status = "";
  let more = true;
  let failures = 0;
  let started = resumeExisting;
  try {
    while (more && !app.aborter.signal.aborted) {
    more = false;
    completedStream = false;
    try {
    const current = await fetch(`/api/sessions/${sid}`);
    if (!current.ok) throw new Error(await responseError(current));
    const snapshot = await current.json();
    if (snapshot.busy) {
      ui.novelStatus.textContent = t("waitingChapter");
      await pause(3000, app.aborter.signal);
      more = true;
      continue;
    }
    if (started && !snapshot.auto_run) {
      status = snapshot.status === "completed" ? t("novelFinished") : t("novelStopped");
      renderProject(snapshot.state);
      break;
    }
    renderProject(snapshot.state);
    const res = await fetch(`/api/sessions/${sid}/novel/generate`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chapters_count: Number(ui.chapterCount.value),
        chapter_length: Number(ui.chapterLength.value),
      }),
      signal: app.aborter.signal,
    });
    if (res.status === 409 || res.status >= 500) throw new TypeError("retry");
    if (!res.ok || !res.body) throw new Error(await responseError(res));
    started = true;
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    const handle = ev => {
      if (ev.type === "planning") ui.novelStatus.textContent = t("novelPlanning");
      if (ev.type === "plan") {
        renderProject(ev.state);
        ui.novelStatus.textContent = progressText();
      }
      if (ev.type === "chapter_start") {
        const el = document.getElementById(`chapter-${ev.number}`);
        el.open = true;
        el.classList.add("writing");
        el.querySelector(".chapter-content").textContent = "";
        el.scrollIntoView({ block: "nearest" });
        ui.novelStatus.textContent = `${progressText()} · ${t("novelWriting", ev.number)}`;
      }
      if (ev.type === "chapter_delta") {
        const el = document.querySelector(`#chapter-${ev.number} .chapter-content`);
        const atBottom = ui.manuscript.scrollHeight - ui.manuscript.scrollTop - ui.manuscript.clientHeight < 100;
        el.appendChild(document.createTextNode(ev.delta));
        if (atBottom) ui.manuscript.scrollTop = ui.manuscript.scrollHeight;
      }
      if (ev.type === "chapter_done") {
        const index = app.state.novel.chapters.findIndex(c => c.number === ev.chapter.number);
        app.state.novel.chapters[index] = ev.chapter;
        const el = document.getElementById(`chapter-${ev.chapter.number}`);
        el.classList.remove("writing");
        el.querySelector(".chapter-content").textContent = ev.chapter.content;
        ui.novelStatus.textContent = progressText();
        updateNovelControls();
      }
      if (ev.type === "done") {
        app.state = ev.state;
        completedStream = true;
        status = t("novelFinished");
      }
      if (ev.type === "next") {
        app.state = ev.state;
        completedStream = true;
        more = true;
      }
      if (ev.type === "interrupted") {
        completedStream = true;
        status = t("novelStopped");
      }
      if (ev.type === "error") throw new Error(localizedError(ev.message));
    };
    for (;;) {
      const { done, value } = await reader.read();
      buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
      let nl;
      while ((nl = buffer.indexOf("\n")) >= 0) {
        const line = buffer.slice(0, nl).trim();
        buffer = buffer.slice(nl + 1);
        if (line) handle(JSON.parse(line));
      }
      if (done) break;
    }
    if (buffer.trim()) handle(JSON.parse(buffer));
    if (!completedStream) throw new TypeError("incomplete stream");
    failures = 0;
    await loadHistory().catch(() => {});
    } catch (err) {
      if (err instanceof TypeError && ++failures <= 8 && !app.aborter.signal.aborted) {
        ui.novelStatus.textContent = t("reconnecting");
        await pause(3000, app.aborter.signal);
        more = true; // The next iteration reloads durable progress before POST.
      } else throw err;
    }
    }
  } catch (err) {
    status = err.name === "AbortError" ? t("novelStopped") : `${t("novelFailed")} ${err.message}`;
  } finally {
    if (app.stopRequest) await app.stopRequest;
    app.stopRequest = null;
    // Reload only committed chapters: partial prose must not look like a saved chapter.
    try {
      const res = await fetch(`/api/sessions/${sid}`);
      if (res.ok) app.state = (await res.json()).state;
    } catch (_) {}
    app.generating = false;
    app.novelBusy = false;
    app.aborter = null;
    renderManuscript();
    setButtons("send");
    ui.novelStatus.textContent = `${progressText()} · ${status}`;
    loadHistory().catch(() => {});
  }
}

function pause(ms, signal) {
  return new Promise((resolve, reject) => {
    const abort = () => { clearTimeout(timer); reject(new DOMException("Stopped", "AbortError")); };
    const timer = setTimeout(() => { signal.removeEventListener("abort", abort); resolve(); }, ms);
    if (signal.aborted) abort();
    else signal.addEventListener("abort", abort, { once: true });
  });
}

async function exportWord() {
  if (!app.sid || app.exportBusy) return;
  app.exportBusy = true;
  updateNovelControls();
  ui.wordExport.textContent = t("exporting");
  try {
    const res = await fetch(`/api/sessions/${app.sid}/export/word`);
    if (!res.ok) throw new Error(await responseError(res));
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = (app.state?.novel?.title || t("manuscriptFilename")).replace(/[\\/:*?"<>|]/g, "_") + ".docx";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (err) {
    ui.novelStatus.textContent = `${t("exportFail")} ${err.message}`;
  } finally {
    app.exportBusy = false;
    ui.wordExport.textContent = t("exportWord");
    updateNovelControls();
  }
}

function renderReferences(images) {
  ui.refOutput.innerHTML = images.map((im, index) => {
    const title = im.kind === "character"
      ? t("portraitTitle", im.character_name || im.title.split(" · ")[0])
      : t("sceneTitle", index + 1);
    return `
    <div class="ref-card">
      <div class="ref-title">${esc(title)}<span class="ref-kind">${im.kind === "character" ? esc(t("kindCharacter")) : esc(t("kindScene"))}</span></div>
      ${im.image_url && !im.image_url.startsWith("(")
        ? `<img src="${esc(im.image_url)}" alt="${esc(title)}" loading="lazy" referrerpolicy="no-referrer" />`
        : `<div class="ref-fail">${esc(t("imgFailed"))}</div>`}
      <div class="ref-prompt">${esc(im.prompt)}</div>
    </div>`;
  }).join("");
}

function showRefEmpty(msg) {
  ui.refOutput.innerHTML = `<div class="empty">${esc(msg)}</div>`;
}

async function generateReferences() {
  if (!app.sid || app.refBusy || app.generating || app.modelBusy || app.speechBusy) return;
  // Prerequisite (characters + outline) is validated server-side: the backend
  // will also try to recover them from chat history before giving up. So we
  // send the request and handle a 400 (missing_prerequisites) response here.
  if (!ui.refTotal.reportValidity()) return;
  const total = Number(ui.refTotal.value);

  app.refBusy = true;
  updateNovelControls();
  ui.refGen.disabled = true;
  const original = ui.refGen.textContent;
  ui.refGen.textContent = t("generating");
  ui.refOutput.innerHTML = `<div class="empty">${esc(t("generatingHint", total))}</div>`;
  try {
    const res = await fetch(`/api/sessions/${app.sid}/references/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ total }),
    });
    if (res.status === 400) {
      showRefEmpty(t("needPrereq"));
      return;
    }
    if (!res.ok) throw new Error(await responseError(res));
    const data = await res.json();
    renderReferences(data.images || []);
  } catch (err) {
    showRefEmpty(t("failPrefix") + (err instanceof TypeError ? t("networkFail") : err.message));
  } finally {
    app.refBusy = false;
    updateNovelControls();
    ui.refGen.disabled = false;
    ui.refGen.textContent = original;
  }
}

/* ------------------------------------------------------------------ */
/* Wire-up & init                                                      */
/* ------------------------------------------------------------------ */

ui.send.addEventListener("click", sendMessage);
ui.stop.addEventListener("click", stopGeneration);
ui.refGen.addEventListener("click", generateReferences);
ui.newTask.addEventListener("click", () => createSession().catch(err => appendSystem(err.message)));
ui.historyOpen.addEventListener("click", () => historyDrawer(true));
ui.historyClose.addEventListener("click", () => historyDrawer(false));
ui.historyShade.addEventListener("click", () => historyDrawer(false));
document.addEventListener("keydown", e => { if (e.key === "Escape") historyDrawer(false); });
ui.history.addEventListener("click", async e => {
  if (app.generating || app.refBusy || app.modelBusy || app.speechBusy || app.exportBusy) return;
  const selected = e.target.closest("[data-task]");
  const removed = e.target.closest("[data-delete]");
  try {
    if (selected) await restoreSession(selected.dataset.task);
    if (removed && confirm(t("deleteConfirm"))) {
      const sid = removed.dataset.delete;
      const res = await fetch(`/api/sessions/${sid}`, { method: "DELETE" });
      if (!res.ok) throw new Error(await responseError(res));
      if (sid === app.sid) await createSession();
      else await loadHistory();
    }
  } catch (err) { appendSystem(err.message); }
});
ui.novelGen.addEventListener("click", () => generateNovel());
ui.wordExport.addEventListener("click", exportWord);
ui.viewChat.addEventListener("click", () => showView(false));
ui.viewNovel.addEventListener("click", () => showView(true));
ui.textModel.addEventListener("change", selectTextModel);

ui.input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    if (!app.generating) sendMessage();
  }
});

// Thought panel toggle (works for both live and collapsed states).
ui.messages.addEventListener("click", (e) => {
  const t = e.target.closest(".thought-toggle");
  if (!t) return;
  const thought = t.closest(".thought");
  collapseThought(thought, !thought.classList.contains("collapsed"));
});

(async function init() {
  const saved = localStorage.getItem("msa-lang");
  if (saved && Object.hasOwn(window.I18N, saved)) app.language = saved;
  ui.lang.value = app.language;
  applyI18n(app.language);
  ui.lang.addEventListener("change", () => {
    app.language = ui.lang.value;
    localStorage.setItem("msa-lang", app.language);
    applyI18n(app.language);
    speechInput.refresh(app.generating || app.refBusy || app.modelBusy);
    for (const option of ui.textModel.options) {
      if (app.modelOptions[option.value]) {
        option.textContent = t("tokenBudget", app.modelOptions[option.value]);
      }
    }
    // Switching language resets the task so the agent replies in the new language.
    app.sid = null;
    ui.messages.innerHTML = "";
    ui.refOutput.innerHTML = `<div class="empty">${esc(t("refEmpty"))}</div>`;
    app.state = null;
    createSession().catch((err) => appendSystem(t("connectFail") + err.message));
  });
  try {
    await loadModels();
    const active = localStorage.getItem("msa-active-task");
    if (active) {
      try { await restoreSession(active); }
      catch (_) { await createSession(); }
    } else await createSession();
  } catch (err) {
    appendSystem(t("connectFail") + err.message);
  }
})();
