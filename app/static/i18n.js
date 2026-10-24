/* UI i18n dictionary. Chat replies come from the backend in the session language;
 * these strings cover only the UI chrome. */
"use strict";

window.I18N = {
  "zh-CN": {
    title: "剧本 Agent",
    brand: "剧本 Agent",
    language: "语言",
    newTask: "新任务",
    send: "发送",
    stop: "停止",
    inputPlaceholder: "描述你的剧本创意…",
    referenceImages: "参考图",
    refEmpty: "生成的角色定妆图和分镜参考图将显示在这里。",
    totalImages: "图片数",
    refTotalHint: "1-8 张（角色图 + 分镜图之和）",
    generateRefs: "生成",
    generating: "生成中…",
    generatingHint: (n) => `正在生成 ${n} 张参考图，请稍候…`,
    needPrereq: "请先在左栏生成剧本和角色侧写",
    failPrefix: "生成失败：",
    kindCharacter: "角色",
    kindScene: "分镜",
    imgFailed: "生成失败",
    thinking: "思考中…",
    thought: "思考过程",
    newTaskReady: "新任务已就绪，请描述你的剧本创意。",
    connectFail: "连接后端失败：",
    genericFail: "生成失败。",
  },
  "zh-TW": {
    title: "劇本 Agent",
    brand: "劇本 Agent",
    language: "語言",
    newTask: "新任務",
    send: "發送",
    stop: "停止",
    inputPlaceholder: "描述你的劇本創意…",
    referenceImages: "參考圖",
    refEmpty: "生成的角色定妝圖與分鏡參考圖將顯示在這裡。",
    totalImages: "圖片數",
    refTotalHint: "1-8 張（角色圖 + 分鏡圖之和）",
    generateRefs: "生成",
    generating: "生成中…",
    generatingHint: (n) => `正在生成 ${n} 張參考圖，請稍候…`,
    needPrereq: "請先在左欄生成劇本與角色側寫",
    failPrefix: "生成失敗：",
    kindCharacter: "角色",
    kindScene: "分鏡",
    imgFailed: "生成失敗",
    thinking: "思考中…",
    thought: "思考過程",
    newTaskReady: "新任務已就緒，請描述你的劇本創意。",
    connectFail: "連接後端失敗：",
    genericFail: "生成失敗。",
  },
  en: {
    title: "Movie Script Agent",
    brand: "Movie Script Agent",
    language: "Language",
    newTask: "New Task",
    send: "Send",
    stop: "Stop",
    inputPlaceholder: "Describe your script idea…",
    referenceImages: "Reference Images",
    refEmpty: "Character portraits and key scene references will appear here.",
    totalImages: "Images",
    refTotalHint: "1-8 (characters + scenes)",
    generateRefs: "Generate",
    generating: "Generating…",
    generatingHint: (n) => `Generating ${n} reference image(s), please wait…`,
    needPrereq: "Please generate the script and character profiles on the left first.",
    failPrefix: "Generation failed: ",
    kindCharacter: "Character",
    kindScene: "Scene",
    imgFailed: "Image failed",
    thinking: "Thinking…",
    thought: "Thought process",
    newTaskReady: "New task ready. Describe your script idea to begin.",
    connectFail: "Failed to connect to the backend: ",
    genericFail: "Generation failed.",
  },
  ja: {
    title: "脚本エージェント",
    brand: "脚本エージェント",
    language: "言語",
    newTask: "新規タスク",
    send: "送信",
    stop: "停止",
    inputPlaceholder: "脚本のアイデアを入力…",
    referenceImages: "参考画像",
    refEmpty: "キャラクター設定画とキーシーンの参考画像がここに表示されます。",
    totalImages: "画像数",
    refTotalHint: "1〜8 枚（キャラクター + シーン）",
    generateRefs: "生成",
    generating: "生成中…",
    generatingHint: (n) => `${n} 枚の参考画像を生成しています…`,
    needPrereq: "先に左側で脚本とキャラクタープロファイルを生成してください。",
    failPrefix: "生成失敗：",
    kindCharacter: "キャラ",
    kindScene: "シーン",
    imgFailed: "生成に失敗しました",
    thinking: "考え中…",
    thought: "思考プロセス",
    newTaskReady: "新しいタスクが準備できました。脚本のアイデアを入力してください。",
    connectFail: "バックエンドへの接続に失敗しました：",
    genericFail: "生成に失敗しました。",
  },
  ko: {
    title: "시나리오 에이전트",
    brand: "시나리오 에이전트",
    language: "언어",
    newTask: "새 작업",
    send: "전송",
    stop: "중지",
    inputPlaceholder: "시나리오 아이디어를 입력하세요…",
    referenceImages: "참고 이미지",
    refEmpty: "캐릭터 설정도와 주요 장면 참고 이미지가 여기에 표시됩니다.",
    totalImages: "이미지 수",
    refTotalHint: "1-8 장 (캐릭터 + 장면)",
    generateRefs: "생성",
    generating: "생성 중…",
    generatingHint: (n) => `${n}장의 참고 이미지를 생성 중입니다…`,
    needPrereq: "먼저 왼쪽에서 시나리오와 캐릭터 프로필을 생성하세요.",
    failPrefix: "생성 실패: ",
    kindCharacter: "캐릭터",
    kindScene: "장면",
    imgFailed: "생성 실패",
    thinking: "생각 중…",
    thought: "사고 과정",
    newTaskReady: "새 작업이 준비되었습니다. 시나리오 아이디어를 입력하세요.",
    connectFail: "백엔드 연결 실패: ",
    genericFail: "생성에 실패했습니다.",
  },
};

const manuscriptStrings = {
  "zh-CN": {
    discussion: "创作讨论", manuscript: "小说正文", chapterCount: "章节数", chapterLength: "每章目标字数",
    generateNovel: "生成完整正文", resumeNovel: "继续生成正文", exportWord: "导出 Word",
    novelHint: "先完成角色侧写和大纲；默认 12 章，约 3 万字，逐章生成并保存。刷新会新建任务，请先导出。",
    novelEmpty: "章节目录和完整正文将显示在这里。",
    novelPlanning: "正在规划完整章节和结局…",
    novelWriting: (n) => `正在写作第 ${n} 章…`,
    novelProgress: (v) => `已完成 ${v.done}/${v.total} 章 · ${v.length.toLocaleString()} 字`,
    novelStopped: "已停止，保留已完成章节。可继续生成。",
    novelFailed: "生成未完成，已完成章节保留。", novelFinished: "全文已完成，可导出 Word。",
    exporting: "正在导出…",
  },
  "zh-TW": {
    discussion: "創作討論", manuscript: "小說正文", chapterCount: "章節數", chapterLength: "每章目標字數",
    generateNovel: "生成完整正文", resumeNovel: "繼續生成正文", exportWord: "匯出 Word",
    novelHint: "先完成角色側寫與大綱；預設 12 章，約 3 萬字，逐章生成並保存。重新整理會新建任務，請先匯出。",
    novelEmpty: "章節目錄與完整正文將顯示在這裡。",
    novelPlanning: "正在規劃完整章節與結局…", novelWriting: (n) => `正在寫作第 ${n} 章…`,
    novelProgress: (v) => `已完成 ${v.done}/${v.total} 章 · ${v.length.toLocaleString()} 字`,
    novelStopped: "已停止，保留已完成章節。可繼續生成。",
    novelFailed: "生成未完成，已完成章節保留。", novelFinished: "全文已完成，可匯出 Word。",
    exporting: "正在匯出…",
  },
  en: {
    discussion: "Discussion", manuscript: "Manuscript", chapterCount: "Chapters", chapterLength: "Target words/chapter",
    generateNovel: "Generate full manuscript", resumeNovel: "Continue manuscript", exportWord: "Export Word",
    novelHint: "Complete characters and outline first. Default: 12 chapters, about 30,000 words, saved chapter by chapter. Export before refreshing to a new task.",
    novelEmpty: "Chapter plan and full prose will appear here.",
    novelPlanning: "Planning all chapters and the ending…", novelWriting: (n) => `Writing chapter ${n}…`,
    novelProgress: (v) => `${v.done}/${v.total} chapters complete · ${v.length.toLocaleString()} words`,
    novelStopped: "Stopped. Completed chapters are saved. You can continue.",
    novelFailed: "Generation incomplete. Completed chapters are saved.", novelFinished: "Manuscript complete. Ready to export Word.",
    exporting: "Exporting…",
  },
  ja: {
    discussion: "制作相談", manuscript: "小説本文", chapterCount: "章数", chapterLength: "各章の目標文字数",
    generateNovel: "全文を生成", resumeNovel: "生成を続ける", exportWord: "Word に出力",
    novelHint: "先に人物設定とあらすじを完成させてください。既定は12章、約3万字。章ごとに保存します。更新前に出力してください。",
    novelEmpty: "章一覧と本文がここに表示されます。",
    novelPlanning: "章構成と結末を計画中…", novelWriting: (n) => `第${n}章を執筆中…`,
    novelProgress: (v) => `${v.done}/${v.total}章完成 · ${v.length.toLocaleString()}字`,
    novelStopped: "停止しました。完成した章は保存されています。続行できます。",
    novelFailed: "生成未完了。完成した章は保存されています。", novelFinished: "全文完成。Word に出力できます。",
    exporting: "出力中…",
  },
  ko: {
    discussion: "창작 대화", manuscript: "소설 본문", chapterCount: "장 수", chapterLength: "장당 목표 글자 수",
    generateNovel: "전체 본문 생성", resumeNovel: "본문 생성 계속", exportWord: "Word 내보내기",
    novelHint: "인물 설정과 줄거리를 먼저 완성하세요. 기본 12장, 약 3만 자. 장마다 저장됩니다. 새로고침 전에 내보내세요.",
    novelEmpty: "장 목록과 전체 본문이 여기에 표시됩니다.",
    novelPlanning: "장 구성과 결말 계획 중…", novelWriting: (n) => `${n}장 집필 중…`,
    novelProgress: (v) => `${v.done}/${v.total}장 완료 · ${v.length.toLocaleString()}자`,
    novelStopped: "중지되었습니다. 완성된 장은 저장되어 있으며 계속할 수 있습니다.",
    novelFailed: "생성 미완료. 완성된 장은 저장되었습니다.", novelFinished: "전체 본문 완료. Word로 내보낼 수 있습니다.",
    exporting: "내보내는 중…",
  },
};
for (const [language, strings] of Object.entries(manuscriptStrings)) {
  Object.assign(window.I18N[language], strings);
}
const modelLabels = {
  "zh-CN": ["剧本模型", "章数", "字/章", "已切换模型"],
  "zh-TW": ["劇本模型", "章數", "字/章", "已切換模型"],
  en: ["Script model", "Ch.", "Words/ch.", "Model selected"],
  ja: ["脚本モデル", "章数", "字/章", "モデルを変更"],
  ko: ["대본 모델", "장 수", "자/장", "모델 변경"],
};
const interfaceStrings = {
  "zh-CN": {
    viewLabel: "创作视图", modelLoadFail: "无法读取模型配置。",
    sessionCreateFail: "无法创建任务。", requestFail: (n) => `请求失败（HTTP ${n}）。`,
    networkFail: "网络连接失败，请重试。", exportFail: "Word 导出失败：",
    portraitTitle: (name) => `${name} · 定妆图`, sceneTitle: (n) => `场景参考 ${n}`,
    manuscriptFilename: "小说正文", thoughtToggle: "展开或收起创作思路",
    tokenBudget: (v) => `${v.id} · ${Number(v.max_tokens).toLocaleString("zh-CN")} tokens`,
    taskMissing: "任务不存在，请新建任务。", generationBusy: "正在生成，请先停止后再操作。",
    planConflict: "已有章节规划，请使用原篇幅设置继续，或新建任务。",
    exportPrereq: "请先生成至少一章正文或分镜剧本。",
    nodeRequired: "Word 导出需要 Node.js；请安装后运行 npm ci。",
    exportSetupFail: "Word 导出失败，请确认已运行 npm ci。",
  },
  "zh-TW": {
    viewLabel: "創作檢視", modelLoadFail: "無法讀取模型設定。",
    sessionCreateFail: "無法建立任務。", requestFail: (n) => `請求失敗（HTTP ${n}）。`,
    networkFail: "網路連線失敗，請重試。", exportFail: "Word 匯出失敗：",
    portraitTitle: (name) => `${name} · 定妝圖`, sceneTitle: (n) => `場景參考 ${n}`,
    manuscriptFilename: "小說正文", thoughtToggle: "展開或收起創作思路",
    tokenBudget: (v) => `${v.id} · ${Number(v.max_tokens).toLocaleString("zh-TW")} tokens`,
    taskMissing: "任務不存在，請建立新任務。", generationBusy: "正在生成，請先停止再操作。",
    planConflict: "已有章節規劃，請使用原篇幅設定繼續，或建立新任務。",
    exportPrereq: "請先生成至少一章正文或分鏡劇本。",
    nodeRequired: "Word 匯出需要 Node.js；請安裝後執行 npm ci。",
    exportSetupFail: "Word 匯出失敗，請確認已執行 npm ci。",
  },
  en: {
    viewLabel: "Writing view", modelLoadFail: "Could not load model settings.",
    sessionCreateFail: "Could not create a task.", requestFail: (n) => `Request failed (HTTP ${n}).`,
    networkFail: "Network connection failed. Please try again.", exportFail: "Word export failed: ",
    portraitTitle: (name) => `${name} · Portrait`, sceneTitle: (n) => `Scene reference ${n}`,
    manuscriptFilename: "manuscript", thoughtToggle: "Expand or collapse writing notes",
    tokenBudget: (v) => `${v.id} · ${Number(v.max_tokens).toLocaleString("en-US")} tokens`,
    taskMissing: "Task not found. Start a new task.", generationBusy: "Generation is running. Stop it before continuing.",
    planConflict: "Continue with the existing chapter count and length, or start a new task.",
    exportPrereq: "Generate at least one chapter or storyboard script before exporting.",
    nodeRequired: "Word export needs Node.js. Install it and run npm ci.",
    exportSetupFail: "Word export failed. Check that npm ci has been run.",
  },
  ja: {
    viewLabel: "制作ビュー", modelLoadFail: "モデル設定を読み込めません。",
    sessionCreateFail: "タスクを作成できません。", requestFail: (n) => `リクエスト失敗（HTTP ${n}）。`,
    networkFail: "接続に失敗しました。再試行してください。", exportFail: "Word 出力失敗：",
    portraitTitle: (name) => `${name} · 人物設定画`, sceneTitle: (n) => `シーン参考 ${n}`,
    manuscriptFilename: "小説本文", thoughtToggle: "制作メモを展開・折りたたむ",
    tokenBudget: (v) => `${v.id} · ${Number(v.max_tokens).toLocaleString("ja-JP")} トークン`,
    taskMissing: "タスクがありません。新規タスクを作成してください。", generationBusy: "生成中です。先に停止してください。",
    planConflict: "元の章数と文字数で続けるか、新規タスクを作成してください。",
    exportPrereq: "先に本文を1章以上、または絵コンテ脚本を生成してください。",
    nodeRequired: "Word 出力には Node.js が必要です。インストール後 npm ci を実行してください。",
    exportSetupFail: "Word 出力に失敗しました。npm ci の実行を確認してください。",
  },
  ko: {
    viewLabel: "창작 보기", modelLoadFail: "모델 설정을 불러올 수 없습니다.",
    sessionCreateFail: "작업을 만들 수 없습니다.", requestFail: (n) => `요청 실패 (HTTP ${n}).`,
    networkFail: "네트워크 연결에 실패했습니다. 다시 시도하세요.", exportFail: "Word 내보내기 실패: ",
    portraitTitle: (name) => `${name} · 캐릭터 설정도`, sceneTitle: (n) => `장면 참고 ${n}`,
    manuscriptFilename: "소설본문", thoughtToggle: "창작 메모 펼치기 또는 접기",
    tokenBudget: (v) => `${v.id} · ${Number(v.max_tokens).toLocaleString("ko-KR")} 토큰`,
    taskMissing: "작업이 없습니다. 새 작업을 만드세요.", generationBusy: "생성 중입니다. 먼저 중지하세요.",
    planConflict: "기존 장 수와 글자 수로 계속하거나 새 작업을 만드세요.",
    exportPrereq: "먼저 본문 한 장 이상 또는 스토리보드 대본을 생성하세요.",
    nodeRequired: "Word 내보내기에는 Node.js가 필요합니다. 설치 후 npm ci를 실행하세요.",
    exportSetupFail: "Word 내보내기에 실패했습니다. npm ci 실행 여부를 확인하세요.",
  },
};
for (const [language, strings] of Object.entries(interfaceStrings)) {
  Object.assign(window.I18N[language], strings);
}
const errorStrings = {
  "zh-CN": {
    validationFail: "输入不符合要求，请检查章节数、篇幅或模型选项。",
    chapterIncomplete: (n) => `第 ${n} 章未完成；已完成章节保留，可继续生成。`,
    portraitReadFail: (name) => `角色「${name}」的图片无法读取，请重试或重新生成参考图后导出。`,
    planFailed: "章节规划不完整，请重试。",
    tokenLimit: "模型输出达到上限，请缩小单次生成范围后重试。",
  },
  "zh-TW": {
    validationFail: "輸入不符合要求，請檢查章節數、篇幅或模型選項。",
    chapterIncomplete: (n) => `第 ${n} 章未完成；已完成章節保留，可繼續生成。`,
    portraitReadFail: (name) => `角色「${name}」的圖片無法讀取，請重試或重新生成參考圖後匯出。`,
    planFailed: "章節規劃不完整，請重試。",
    tokenLimit: "模型輸出達到上限，請縮小單次生成範圍後重試。",
  },
  en: {
    validationFail: "Check the chapter count, target length, or model selection.",
    chapterIncomplete: (n) => `Chapter ${n} is incomplete. Completed chapters are saved; you can continue.`,
    portraitReadFail: (name) => `Could not read the portrait for ${name}. Retry or generate it again before exporting.`,
    planFailed: "The chapter plan is incomplete. Please try again.",
    tokenLimit: "The model reached its output limit. Reduce the request size and try again.",
  },
  ja: {
    validationFail: "章数、目標文字数、モデル選択を確認してください。",
    chapterIncomplete: (n) => `第${n}章は未完成です。完成した章は保存されており、続行できます。`,
    portraitReadFail: (name) => `${name}の画像を読み込めません。再試行するか、参考画像を再生成してから出力してください。`,
    planFailed: "章構成が不完全です。再試行してください。",
    tokenLimit: "モデルの出力上限に達しました。生成範囲を小さくして再試行してください。",
  },
  ko: {
    validationFail: "장 수, 목표 글자 수 또는 모델 선택을 확인하세요.",
    chapterIncomplete: (n) => `${n}장이 미완성입니다. 완성된 장은 저장되어 있으며 계속할 수 있습니다.`,
    portraitReadFail: (name) => `${name}의 이미지를 읽을 수 없습니다. 다시 시도하거나 참고 이미지를 재생성한 후 내보내세요.`,
    planFailed: "장 구성이 불완전합니다. 다시 시도하세요.",
    tokenLimit: "모델의 출력 한도에 도달했습니다. 생성 범위를 줄여 다시 시도하세요.",
  },
};
for (const [language, strings] of Object.entries(errorStrings)) {
  Object.assign(window.I18N[language], strings);
}
for (const [language, values] of Object.entries(modelLabels)) {
  Object.assign(window.I18N[language], {
    textModel: values[0], chapterCountShort: values[1], chapterLengthShort: values[2],
    modelSelected: (model) => `${values[3]}: ${interfaceStrings[language].tokenBudget(model)}`,
  });
}

window.t = function t(key, arg) {
  const lang = window.__lang || "zh-CN";
  const dict = window.I18N[lang] || window.I18N["en"];
  const v = dict[key] ?? window.I18N.en[key];
  if (typeof v === "function") return v(arg);
  return v == null ? key : v;
};

window.applyI18n = function applyI18n(lang) {
  lang = Object.hasOwn(window.I18N, lang) ? lang : "zh-CN";
  window.__lang = lang;
  document.documentElement.setAttribute("lang", lang);
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    const key = el.getAttribute("data-i18n");
    el.textContent = window.t(key);
  });
  document.querySelectorAll("[data-i18n-attr]").forEach((el) => {
    const spec = el.getAttribute("data-i18n-attr"); // "attr:key" or comma-separated
    spec.split(",").forEach((pair) => {
      const [attr, key] = pair.split(":").map((s) => s.trim());
      if (attr && key) el.setAttribute(attr, window.t(key));
    });
  });
};
