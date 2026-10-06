// ─────────────────────────────────────────────────────────────────────────────
// Obsidian Markdown 내보내기(frontmatter + Wikilink 섹션 + Mermaid).
//  · 자료보관함 mindmap 은 Graph 가 기본 뷰. Markdown 은 export/복사용 보조.
// ─────────────────────────────────────────────────────────────────────────────
import { NODE_TYPES, MINDMAP_VIEW_TYPE } from './graphTypes';
import { makeWikilink, escapeYaml, escapeMarkdown } from './wikilink';
import { generateMermaidGraph } from './mermaidExport';

const nodesOfType = (graph, type) => graph.nodes.filter((n) => n.type === type);

function frontmatter(graph, meta) {
  const center = graph.nodes.find((n) => n.id === graph.centerNodeId);
  const aliases = center ? (center.aliases || []) : [];
  const tags = Array.from(new Set(graph.nodes.flatMap((n) => n.tags || [])));
  const lines = ['---'];
  lines.push('type: mindmap');
  lines.push(`viewType: ${MINDMAP_VIEW_TYPE}`);
  lines.push('source: StudyBridge');
  lines.push(`title: ${escapeYaml(meta?.title || (center && center.title) || '마인드맵')}`);
  lines.push(`created: ${escapeYaml(meta?.created || new Date().toISOString())}`);
  lines.push(`updated: ${escapeYaml(meta?.updated || new Date().toISOString())}`);
  lines.push(`sourceType: ${escapeYaml(meta?.sourceType || (center && center.sourceType) || 'multi_agent_chat')}`);
  lines.push(`sourceId: ${escapeYaml(String(meta?.sourceId ?? (center && center.sourceId) ?? ''))}`);
  if (center) lines.push(`centerNode: ${escapeYaml(makeWikilink(center.obsidianName))}`);
  lines.push('aliases:');
  aliases.forEach((a) => lines.push(`  - ${escapeYaml(a)}`));
  lines.push('tags:');
  tags.forEach((t) => lines.push(`  - ${t}`));
  lines.push('cssclasses:');
  lines.push('  - studybridge-mindmap');
  lines.push('---');
  return lines.join('\n');
}

/**
 * @param {{nodes:any[], edges:any[], centerNodeId?:string}} graph
 * @param {{title?:string, created?:string, updated?:string, sourceType?:string, sourceId?:string, includeRawJson?:boolean}} [meta]
 * @returns {string}
 */
export function buildObsidianMarkdown(graph, meta = {}) {
  const center = graph.nodes.find((n) => n.id === graph.centerNodeId);
  const out = [];
  out.push(frontmatter(graph, meta));
  out.push('');
  out.push(`# ${escapeMarkdown(meta.title || (center && center.title) || '마인드맵')}`);
  out.push('');

  // 1. 중심 질문.
  if (center) {
    out.push('## 1. 중심 질문');
    out.push('');
    out.push(makeWikilink(center.obsidianName, '질문'));
    out.push('');
    String(center.body || '').split('\n').forEach((ln) => out.push(`> ${escapeMarkdown(ln)}`));
    out.push('');
  }

  // 2. 교수 답변 요약표.
  const agents = nodesOfType(graph, NODE_TYPES.AGENT);
  const answers = nodesOfType(graph, NODE_TYPES.ANSWER);
  if (answers.length) {
    out.push('## 2. 교수 답변 요약');
    out.push('');
    out.push('| 교수 | 역할 | 핵심 요약 | 링크 |');
    out.push('| --- | --- | --- | --- |');
    answers.forEach((a) => {
      out.push(`| ${escapeMarkdown(a.agentName || '')} | ${escapeMarkdown(a.agentRole || '')} | ${escapeMarkdown(a.shortLabel || '')} | ${makeWikilink(a.obsidianName)} |`);
    });
    out.push('');
    // 교수별 전체 답변.
    out.push('### 교수별 전체 답변');
    out.push('');
    answers.forEach((a) => {
      out.push(`#### ${makeWikilink(a.obsidianName, a.title)}`);
      out.push('');
      out.push(escapeMarkdown(a.body || ''));
      out.push('');
    });
  }

  // 3. 핵심 개념.
  const concepts = nodesOfType(graph, NODE_TYPES.CONCEPT).sort((x, y) => (y.importance || 0) - (x.importance || 0));
  if (concepts.length) {
    out.push('## 3. 핵심 개념');
    out.push('');
    concepts.forEach((c) => out.push(`- ${makeWikilink(c.obsidianName)}`));
    out.push('');
  }

  // 4. 상호검증.
  const validations = nodesOfType(graph, NODE_TYPES.VALIDATION);
  if (validations.length) {
    out.push('## 4. 상호검증');
    out.push('');
    validations.forEach((v) => { out.push(`- ${escapeMarkdown(v.body || '')}`); });
    out.push('');
  }

  // 5. 반박 및 보완.
  const rebuttals = nodesOfType(graph, NODE_TYPES.REBUTTAL);
  if (rebuttals.length) {
    out.push('## 5. 반박 및 보완');
    out.push('');
    rebuttals.forEach((r) => { out.push(`- ${escapeMarkdown(r.body || '')}`); });
    out.push('');
  }

  // 6. 연결된 자료/로드맵/플래너.
  const linked = [
    ...nodesOfType(graph, NODE_TYPES.SOURCE),
    ...nodesOfType(graph, NODE_TYPES.ROADMAP),
    ...nodesOfType(graph, NODE_TYPES.PLANNER),
  ];
  if (linked.length) {
    out.push('## 6. 연결된 자료');
    out.push('');
    linked.forEach((s) => out.push(`- ${makeWikilink(s.obsidianName)}`));
    out.push('');
  }

  // 7. 관계 그래프(Mermaid).
  out.push('## 7. 관계 그래프');
  out.push('');
  out.push('```mermaid');
  out.push(generateMermaidGraph(graph));
  out.push('```');
  out.push('');

  if (meta.includeRawJson) {
    out.push('## 부록: rawGraphJson');
    out.push('');
    out.push('```json');
    out.push(JSON.stringify({ nodes: graph.nodes, edges: graph.edges, centerNodeId: graph.centerNodeId }, null, 2));
    out.push('```');
    out.push('');
  }

  return out.join('\n');
}
