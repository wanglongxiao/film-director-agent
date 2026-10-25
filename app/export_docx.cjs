/* Read manuscript JSON from stdin, write a real Word document to stdout. */
"use strict";
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, AlignmentType,
  Footer, PageNumber, ImageRun,
} = require("docx");

const labels = {
  "zh-CN": ["小说式电影剧本", "章节索引", "小说正文", "附录", "背景设定", "人物侧写", "故事大纲", "电影剧本", "未完成稿"],
  "zh-TW": ["小說式電影劇本", "章節索引", "小說正文", "附錄", "背景設定", "人物側寫", "故事大綱", "電影劇本", "未完成稿"],
  en: ["Film novella", "Chapter index", "Manuscript", "Appendix", "Background", "Character profiles", "Outline", "Film script", "Incomplete draft"],
  ja: ["映画小説", "章一覧", "小説本文", "付録", "背景設定", "人物紹介", "あらすじ", "映画脚本", "未完成稿"],
  ko: ["영화 소설", "장 목록", "소설 본문", "부록", "배경 설정", "인물 소개", "줄거리", "영화 대본", "미완성 원고"],
};
const fonts = { ascii: "Arial", hAnsi: "Arial", eastAsia: "Microsoft YaHei", cs: "Arial" };
const heading = (text, level = HeadingLevel.HEADING_1, pageBreakBefore = false) =>
  new Paragraph({ text, heading: level, pageBreakBefore });
const paragraphs = (text, indent = true) => String(text || "").split(/\r?\n/).filter(p => p.trim())
  .map(p => new Paragraph({
    children: [new TextRun(p)],
    indent: indent ? { firstLine: 480 } : undefined,
    spacing: { after: 120, line: 360 },
  }));

async function build(state) {
  const l = labels[state.language] || labels.en;
  const novel = state.novel;
  const finished = novel ? novel.chapters.filter(c => c.content) : [];
  const title = state.title || (novel ? novel.title : state.episodes?.[0]?.title) || l[7];
  const portraits = new Map((state.character_images || []).map(im => [im.character_name, im]));
  const children = [
    new Paragraph({ text: title, heading: HeadingLevel.TITLE, alignment: AlignmentType.CENTER }),
    new Paragraph({ text: l[0], alignment: AlignmentType.CENTER }),
  ];
  if (novel && finished.length !== novel.chapters_count) {
    children.push(new Paragraph({
      text: `${l[8]} · ${finished.length} / ${novel.chapters_count}`,
      alignment: AlignmentType.CENTER,
    }));
  }
  if (finished.length) {
    children.push(heading(l[1], HeadingLevel.HEADING_1, true));
    for (const c of finished) children.push(...paragraphs(`${c.number}. ${c.title}`, false));
    children.push(heading(l[2], HeadingLevel.HEADING_1, true));
    for (const [i, c] of finished.entries()) {
      children.push(heading(`${c.number}. ${c.title}`, HeadingLevel.HEADING_2, i > 0));
      children.push(...paragraphs(c.content));
    }
  } else if (state.episodes?.length) {
    children.push(heading(l[1], HeadingLevel.HEADING_1, true));
    for (const ep of state.episodes) children.push(...paragraphs(`${ep.number}. ${ep.title}`, false));
    children.push(heading(l[2], HeadingLevel.HEADING_1, true));
    for (const [i, ep] of state.episodes.entries()) {
      children.push(heading(`${ep.number}. ${ep.title}`, HeadingLevel.HEADING_2, i > 0));
      for (const sb of ep.storyboards) {
        for (const text of [sb.scene, sb.shot, sb.dialogue]) children.push(...paragraphs(text));
      }
    }
  }
  children.push(heading(l[3], HeadingLevel.HEADING_1, true));
  children.push(heading(l[4], HeadingLevel.HEADING_2));
  children.push(...paragraphs(state.background));
  children.push(...paragraphs(
    [state.genre, state.tone, state.script_type, state.style, state.rating].filter(Boolean).join(" · "),
    false,
  ));
  children.push(heading(l[5], HeadingLevel.HEADING_2));
  for (const c of state.characters || []) {
    children.push(heading(`${c.name} · ${c.role}`, HeadingLevel.HEADING_3));
    for (const text of [c.background, c.personality, c.arc]) children.push(...paragraphs(text));
    const portrait = portraits.get(c.name);
    if (portrait) {
      children.push(new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [new ImageRun({
          type: "png", data: Buffer.from(portrait.data, "base64"),
          transformation: { width: portrait.width, height: portrait.height },
          altText: { title: c.name, description: c.name, name: c.name },
        })],
        spacing: { before: 120, after: 240 },
      }));
    }
  }
  const doc = new Document({
    title,
    creator: "Movie Script Agent",
    styles: {
      default: { document: { run: { font: fonts, size: 24 } } },
      paragraphStyles: [
        { id: "Title", name: "Title", basedOn: "Normal",
          run: { font: fonts, size: 48, bold: true }, paragraph: { spacing: { before: 720, after: 360 } } },
        ...[1, 2, 3].map(n => ({
          id: `Heading${n}`, name: `Heading ${n}`, basedOn: "Normal", next: "Normal",
          quickFormat: true, run: { font: fonts, size: [32, 28, 26][n - 1], bold: true },
          paragraph: { outlineLevel: n - 1, keepNext: true, spacing: { before: 240, after: 200 } },
        })),
      ],
    },
    sections: [{
      properties: { page: {
        size: { width: 11906, height: 16838 },
        margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
      } },
      footers: { default: new Footer({ children: [
        new Paragraph({ alignment: AlignmentType.CENTER, children: [
          new TextRun({ children: [PageNumber.CURRENT], font: fonts, size: 20 }),
        ] }),
      ] }) },
      children,
    }],
  });
  process.stdout.write(await Packer.toBuffer(doc));
}

let input = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", chunk => { input += chunk; });
process.stdin.on("end", () => {
  build(JSON.parse(input)).catch(err => { console.error(err.message); process.exitCode = 1; });
});
