import { sanitizeList, sanitizeMarkdownText } from '../../../utils/markdown.js';
import { filterLearningList } from '../../../utils/learningContent.js';

const PLACEHOLDER_KEYWORDS = new Set(['ㅇㅇ', '#ㅇㅇ', 'ㅎㅎ', 'ㅋㅋ', 'test', 'keyword', 'keywords', '테스트', 'null', 'undefined']);

function parseMaybeJson(value, fallback) {
  if (value == null) return fallback;
  if (typeof value !== 'string') return value;

  const trimmed = value.trim();
  if (!trimmed) return fallback;

  try {
    return JSON.parse(trimmed);
  } catch {
    return fallback;
  }
}

function envelopeOf(summary) {
  const parsed = parseMaybeJson(summary?.coreContents, null);
  if (parsed && !Array.isArray(parsed) && typeof parsed === 'object') return parsed;
  return { sections: Array.isArray(parsed) ? parsed : null };
}

function firstFilledText(...candidates) {
  const found = candidates.find((value) => value && String(value).trim());
  return found ? String(found) : '';
}

export function summaryOverview(summary) {
  if (!summary) return '';
  return sanitizeMarkdownText(summary.overview || summary.summary || summary.gpt_raw || '');
}

function removePlaceholderKeywords(keywords) {
  const list = Array.isArray(keywords) ? keywords : String(keywords || '').split(',');
  const seen = new Set();

  return list
    .map((keyword) => String(keyword || '').trim().replace(/^#+/, '').trim())
    .filter((keyword) => keyword.length > 1 && !PLACEHOLDER_KEYWORDS.has(keyword.toLowerCase()))
    .filter((keyword) => /[가-힣A-Za-z0-9]/.test(keyword))
    .filter((keyword) => {
      const key = keyword.toLowerCase();
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
}

export function summaryKeywords(summary, material) {
  const envelope = envelopeOf(summary);
  const fromSummary = summary?.keywords?.length
    ? summary.keywords
    : summary?.key_points?.length
      ? summary.key_points
      : envelope.keywords || envelope.key_points || [];
  const source = removePlaceholderKeywords(fromSummary);
  const keywords = source.length > 0 ? source : removePlaceholderKeywords(material?.keywords);

  return filterLearningList(keywords.map(sanitizeMarkdownText).filter(Boolean), material?.title);
}

export function summaryList(summary, key) {
  if (!summary) return [];
  if (Array.isArray(summary[key]) && summary[key].length > 0) return sanitizeList(summary[key]);

  const fromEnvelope = envelopeOf(summary)[key];
  return sanitizeList(Array.isArray(fromEnvelope) ? fromEnvelope : []);
}

function sectionFromItem(item, index) {
  const fallbackTitle = `${index + 1}. 핵심 요약`;
  if (typeof item === 'string') return { title: fallbackTitle, content: item };
  if (!item || typeof item !== 'object') return null;

  return {
    title: item.title || item.heading || fallbackTitle,
    content: item.content || item.description || item.summary || '',
  };
}

function sectionsFromPlainText(text) {
  return text
    .split('\n')
    .map((line) => line.replace(/^[-\d.\s*]+/, '').trim())
    .filter(Boolean)
    .map((line, index) => ({ title: `${index + 1}. 핵심 요약`, content: line }));
}

export function summarySections(summary) {
  if (!summary) return [];

  const envelope = envelopeOf(summary);
  const candidates = summary.sections || envelope.sections || summary.coreContents;
  const parsed = parseMaybeJson(candidates, candidates);

  if (Array.isArray(parsed) && parsed.length > 0) {
    return parsed.map(sectionFromItem).filter((section) => section && section.content);
  }

  const plain = typeof summary.coreContents === 'string' ? summary.coreContents.trim() : '';
  if (plain && plain !== '[]' && plain !== '{}') return sectionsFromPlainText(plain);

  return [];
}

function contentTextOf(item) {
  if (typeof item === 'string') return sanitizeMarkdownText(item);
  return sanitizeMarkdownText(item?.content || item?.description || item?.summary || '');
}

function uniqueByPrefix(lines) {
  const seen = new Set();
  return lines.filter((line) => {
    const key = line.slice(0, 60);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function coreContentLines(summary) {
  const envelope = envelopeOf(summary);
  const direct = summary.core_contents || envelope.core_contents;
  if (Array.isArray(direct) && direct.length > 0) return direct.map(contentTextOf).filter(Boolean);

  const keyPoints = summary.key_points?.length ? summary.key_points : summary.keywords;
  const lines = [
    ...summarySections(summary).map((section) => sanitizeMarkdownText(section.content)),
    ...sanitizeList(summary.practicePoints),
    ...sanitizeList(summary.learningPoints),
  ].filter(Boolean);

  return uniqueByPrefix(lines.length >= 10 ? lines : [...lines, ...sanitizeList(keyPoints)]);
}

function splitSentences(text) {
  return sanitizeMarkdownText(text)
    .split(/\n+/)
    .flatMap((line) => line.split(/(?<=[.。!?])\s+/))
    .map((sentence) => sentence.trim())
    .filter((sentence) => sentence.length > 3);
}

function detailedContentLines(summary) {
  const envelope = envelopeOf(summary);
  const direct = summary.detailed_core_contents || envelope.detailed_core_contents;
  if (Array.isArray(direct) && direct.length > 0) return direct.map(contentTextOf).filter(Boolean);

  const keyPoints = summary.key_points?.length ? summary.key_points : summary.keywords;
  const sources = [
    ...summarySections(summary).map((section) => section.content),
    ...sanitizeList(summary.practicePoints),
    ...sanitizeList(summary.learningPoints),
    ...sanitizeList(summary.studyQuestions),
    ...sanitizeList(keyPoints),
  ];

  return uniqueByPrefix(sources.flatMap(splitSentences));
}

export function coreContentText(summary) {
  if (!summary) return '';
  const envelope = envelopeOf(summary);
  const direct = firstFilledText(
    summary.core_content_text,
    envelope.core_content_text,
    summary.coreContentText,
    envelope.coreContentText
  );
  if (direct) return sanitizeMarkdownText(direct);
  return coreContentLines(summary).join('\n');
}

export function detailedContentText(summary) {
  if (!summary) return '';
  const envelope = envelopeOf(summary);
  const direct = firstFilledText(
    summary.detailed_content_text,
    envelope.detailed_content_text,
    summary.detailedContentText,
    envelope.detailedContentText
  );
  if (direct) return sanitizeMarkdownText(direct);
  return detailedContentLines(summary).join('\n');
}
