// ─────────────────────────────────────────────────────────────────────────────
// 교수 답변 그래프(마인드맵)를 의존성 없이 PDF로 만들어 로컬에 저장한다.
//   흐름: graph model → 자기완결 SVG 문자열 → <img>로 로드 → canvas 래스터화(JPEG)
//        → 손수 만든 최소 PDF(JPEG XObject 임베드) → Blob 다운로드.
//   · 외부 라이브러리(jsPDF/html2canvas) 불필요. 백엔드/계약 변경 없음.
//   · 래스터화 안정성을 위해 export SVG는 foreignObject/HTML 없이 순수 SVG(rect/line/text)만 쓴다.
// ─────────────────────────────────────────────────────────────────────────────

const escapeXml = (s) => String(s ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&apos;');

// 대략적 문자수 기반 줄바꿈(한글/영문 혼용). maxChars/줄, maxLines 제한.
const wrapText = (text, maxChars, maxLines) => {
  const words = String(text ?? '').replace(/\s+/g, ' ').trim().split(' ');
  const lines = [];
  let cur = '';
  for (const w of words) {
    if (!cur) { cur = w; }
    else if ((cur + ' ' + w).length <= maxChars) { cur += ' ' + w; }
    else { lines.push(cur); cur = w; }
    if (lines.length >= maxLines) break;
  }
  if (cur && lines.length < maxLines) lines.push(cur);
  // 매우 긴 단일 토큰은 강제로 자른다.
  const clipped = lines.slice(0, maxLines).map((l) => (l.length > maxChars ? l.slice(0, maxChars - 1) + '…' : l));
  if (clipped.length === maxLines) {
    const used = clipped.join(' ').length;
    if (used < String(text || '').length) clipped[maxLines - 1] = clipped[maxLines - 1].replace(/.$/, '…');
  }
  return clipped;
};

// graph model → 자기완결 SVG 문자열.
function buildSvg({ nodes, edges, pos, W, H, roleColor, relationStyle, title }) {
  const FONT = "-apple-system, 'Malgun Gothic', 'Apple SD Gothic Neo', sans-serif";
  const parts = [];
  parts.push(`<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">`);
  parts.push(`<rect x="0" y="0" width="${W}" height="${H}" fill="#f6f8fc"/>`);
  if (title) {
    parts.push(`<text x="${W / 2}" y="22" text-anchor="middle" font-family="${FONT}" font-size="13" font-weight="700" fill="#64748b">${escapeXml(title)}</text>`);
  }

  // 화살표 marker
  parts.push('<defs>');
  Object.entries(relationStyle).forEach(([rel, st]) => {
    parts.push(`<marker id="ar-${rel}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="${st.color}"/></marker>`);
  });
  parts.push('</defs>');

  // 간선 + 라벨
  edges.forEach((edge) => {
    const s = pos[edge.source];
    const t = pos[edge.target];
    if (!s || !t) return;
    const dx = t.x - s.x;
    const dy = t.y - s.y;
    const len = Math.hypot(dx, dy) || 1;
    const ux = dx / len;
    const uy = dy / len;
    const insetPt = (p, sign) => {
      const halfW = p.w / 2 + 6;
      const halfH = p.h / 2 + 6;
      const tx = ux !== 0 ? halfW / Math.abs(ux) : Infinity;
      const ty = uy !== 0 ? halfH / Math.abs(uy) : Infinity;
      const k = Math.min(tx, ty);
      return { x: p.x + sign * ux * k, y: p.y + sign * uy * k };
    };
    const p1 = insetPt(s, 1);
    const p2 = insetPt(t, -1);
    const st = relationStyle[edge.relation] || relationStyle.feedback;
    const mx = (p1.x + p2.x) / 2;
    const my = (p1.y + p2.y) / 2;
    const label = `${edge.label}${edge.derived ? '·예시' : ''}`;
    const lw = label.length * 11 + 18;
    parts.push(`<line x1="${p1.x}" y1="${p1.y}" x2="${p2.x}" y2="${p2.y}" stroke="${st.color}" stroke-width="2" ${edge.derived ? 'stroke-dasharray="6 5" opacity="0.55"' : 'opacity="0.9"'} marker-end="url(#ar-${edge.relation})"/>`);
    parts.push(`<rect x="${mx - lw / 2}" y="${my - 12}" width="${lw}" height="24" rx="12" fill="#ffffff" stroke="${st.color}" stroke-width="1.5"/>`);
    parts.push(`<text x="${mx}" y="${my + 4}" text-anchor="middle" font-family="${FONT}" font-size="12" font-weight="800" fill="${st.color}">${escapeXml(label)}</text>`);
  });

  // 노드 카드
  nodes.forEach((n) => {
    const p = pos[n.id];
    if (!p) return;
    const isQ = n.type === 'question';
    const accent = roleColor[n.role] || roleColor.question || '#2563eb';
    const x = p.x - p.w / 2;
    const y = p.y - p.h / 2;
    const bg = isQ ? '#0f172a' : '#ffffff';
    const nameColor = isQ ? '#f8fafc' : '#111827';
    const bodyColor = isQ ? '#e2e8f0' : '#374151';
    parts.push(`<rect x="${x}" y="${y}" width="${p.w}" height="${p.h}" rx="16" fill="${bg}" stroke="${isQ ? '#0f172a' : '#e6e9f2'}"/>`);
    parts.push(`<rect x="${x}" y="${y}" width="${p.w}" height="4" rx="2" fill="${isQ ? '#38bdf8' : accent}"/>`);
    // head
    parts.push(`<circle cx="${x + 16}" cy="${y + 22}" r="5" fill="${accent}"/>`);
    const nameMax = Math.floor((p.w - 40) / 8);
    const name = wrapText(n.title, nameMax, 1)[0] || '';
    parts.push(`<text x="${x + 28}" y="${y + 26}" font-family="${FONT}" font-size="13.5" font-weight="800" fill="${nameColor}">${escapeXml(name)}</text>`);
    if (!isQ && n.badge) {
      const b = wrapText(n.badge, 10, 1)[0] || '';
      const bw = b.length * 8 + 14;
      parts.push(`<rect x="${x + p.w - bw - 12}" y="${y + 14}" width="${bw}" height="18" rx="9" fill="#f1f5f9"/>`);
      parts.push(`<text x="${x + p.w - bw / 2 - 12}" y="${y + 26}" text-anchor="middle" font-family="${FONT}" font-size="10.5" font-weight="800" fill="#475569">${escapeXml(b)}</text>`);
    }
    // body
    const bodyMax = Math.floor((p.w - 28) / 6.6);
    const lines = wrapText(n.content, bodyMax, isQ ? 2 : 3);
    lines.forEach((ln, i) => {
      parts.push(`<text x="${x + 14}" y="${y + 48 + i * 18}" font-family="${FONT}" font-size="12.5" fill="${bodyColor}">${escapeXml(ln)}</text>`);
    });
    // status
    if (!isQ) {
      const stLabel = n.status === 'answer' ? '답변' : n.status === 'validation' ? '검증' : n.status === 'error' ? '오류' : n.status === 'pending' ? '생성 중' : '완료';
      const sw = stLabel.length * 8 + 16;
      parts.push(`<rect x="${x + 14}" y="${y + p.h - 26}" width="${sw}" height="18" rx="9" fill="#eff6ff"/>`);
      parts.push(`<text x="${x + 14 + sw / 2}" y="${y + p.h - 13}" text-anchor="middle" font-family="${FONT}" font-size="10.5" font-weight="800" fill="${accent}">${escapeXml(stLabel)}</text>`);
    }
  });

  parts.push('</svg>');
  return parts.join('');
}

// 최소 PDF(JPEG를 DCTDecode XObject로 1페이지에 배치). 반환: latin1 문자열.
function jpegToPdf(jpegBin, pxW, pxH) {
  const maxW = 1400;
  const scale = Math.min(1, maxW / pxW);
  const pageW = Math.round(pxW * scale);
  const pageH = Math.round(pxH * scale);

  const offsets = [];
  let pdf = '';
  const mark = (n) => { offsets[n] = pdf.length; };

  pdf += '%PDF-1.3\n%\xE2\xE3\xCF\xD3\n';
  mark(1); pdf += '1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n';
  mark(2); pdf += '2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n';
  mark(3); pdf += `3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${pageW} ${pageH}] /Resources << /XObject << /Im0 5 0 R >> >> /Contents 4 0 R >>\nendobj\n`;
  const content = `q\n${pageW} 0 0 ${pageH} 0 0 cm\n/Im0 Do\nQ\n`;
  mark(4); pdf += `4 0 obj\n<< /Length ${content.length} >>\nstream\n${content}endstream\nendobj\n`;
  mark(5); pdf += `5 0 obj\n<< /Type /XObject /Subtype /Image /Width ${pxW} /Height ${pxH} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length ${jpegBin.length} >>\nstream\n`;
  pdf += jpegBin;
  pdf += '\nendstream\nendobj\n';

  const xrefStart = pdf.length;
  const count = 6;
  pdf += `xref\n0 ${count}\n0000000000 65535 f \n`;
  for (let i = 1; i < count; i += 1) {
    pdf += `${String(offsets[i]).padStart(10, '0')} 00000 n \n`;
  }
  pdf += `trailer\n<< /Size ${count} /Root 1 0 R >>\nstartxref\n${xrefStart}\n%%EOF`;
  return pdf;
}

const loadImage = (src) => new Promise((resolve, reject) => {
  const img = new Image();
  img.onload = () => resolve(img);
  img.onerror = reject;
  img.src = src;
});

// public: graph model을 받아 PDF를 만들어 다운로드한다.
export async function exportGraphPdf(model, filename = 'studymate-mindmap.pdf') {
  const svg = buildSvg(model);
  const svgUrl = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
  const scale = 2; // 선명도
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(model.W * scale);
  canvas.height = Math.round(model.H * scale);
  const ctx = canvas.getContext('2d');
  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  const img = await loadImage(svgUrl);
  ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

  const jpegDataUrl = canvas.toDataURL('image/jpeg', 0.92);
  const jpegBin = atob(jpegDataUrl.split(',')[1]);
  const pdfStr = jpegToPdf(jpegBin, canvas.width, canvas.height);

  const bytes = new Uint8Array(pdfStr.length);
  for (let i = 0; i < pdfStr.length; i += 1) bytes[i] = pdfStr.charCodeAt(i) & 0xff;
  const blob = new Blob([bytes], { type: 'application/pdf' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1500);
}
