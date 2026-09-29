// ─────────────────────────────────────────────────────────────────────────────
// 내보내기 부수효과(다운로드/복사). PDF 경로는 의도적으로 포함하지 않는다.
// ─────────────────────────────────────────────────────────────────────────────
import { buildObsidianMarkdown } from './obsidianMarkdownExport';
import { generateJsonCanvas } from './jsonCanvasExport';

const safeFileName = (raw, ext) => {
  const base = String(raw || '마인드맵').replace(/[\\/:*?"<>|]+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 60) || '마인드맵';
  return `${base}.${ext}`;
};

function downloadBlob(filename, text, mime) {
  const blob = new Blob([text], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export async function copyTextToClipboard(text) {
  try {
    if (navigator?.clipboard?.writeText) { await navigator.clipboard.writeText(text); return true; }
  } catch { /* fall through */ }
  return false;
}

/** Obsidian Markdown(.md) 다운로드. */
export function downloadObsidianMarkdown(graph, meta = {}) {
  const md = buildObsidianMarkdown(graph, meta);
  downloadBlob(safeFileName(meta.title, 'md'), md, 'text/markdown;charset=utf-8');
}

/** JSON Canvas(.canvas) 다운로드. */
export function downloadJsonCanvas(graph, meta = {}) {
  const canvas = generateJsonCanvas(graph);
  downloadBlob(safeFileName(meta.title, 'canvas'), JSON.stringify(canvas, null, 2), 'application/json;charset=utf-8');
}
