import { quizIdOf } from './quizGenerationModel.js';

export const MATERIAL_UPLOAD_ACCEPT = 'application/pdf';
export const MAX_MATERIAL_UPLOAD_BYTES = 30 * 1024 * 1024;

const DEFAULT_MATERIAL_TITLE = '학습자료';
const PDF_EXTENSION_PATTERN = /\.pdf$/i;

export function groupMaterialUploadTaskKey(groupId) {
  return `group:${groupId}:material-upload`;
}

function isPdfFile(file) {
  const type = (file?.type || '').toLowerCase();
  return type === MATERIAL_UPLOAD_ACCEPT || PDF_EXTENSION_PATTERN.test(file?.name || '');
}

export function validateMaterialFile(file) {
  if (!file) return 'PDF 파일을 선택해주세요.';
  if (!isPdfFile(file)) return 'PDF 파일만 업로드할 수 있습니다.';
  if (!file.size) return '빈 파일은 업로드할 수 없습니다.';
  if (file.size > MAX_MATERIAL_UPLOAD_BYTES) return 'PDF 파일은 30MB 이하만 업로드할 수 있습니다.';
  return null;
}

export function materialTitleFromFileName(fileName) {
  const title = String(fileName || '').replace(PDF_EXTENSION_PATTERN, '').trim();
  return title || DEFAULT_MATERIAL_TITLE;
}

export function withUploadedMaterial(list, material) {
  const others = (Array.isArray(list) ? list : []).filter((item) => String(item.id) !== String(material.id));
  return [material, ...others];
}

export function quizIdsOf(quizzes) {
  return new Set((Array.isArray(quizzes) ? quizzes : []).map((quiz) => String(quizIdOf(quiz))));
}

export function describeUploadOutcome({ material, title, quizIdsBefore, refreshedQuizzes }) {
  const createdQuizzes = (Array.isArray(refreshedQuizzes) ? refreshedQuizzes : []).filter(
    (quiz) => !quizIdsBefore.has(String(quizIdOf(quiz)))
  );
  const hasCreatedQuiz = createdQuizzes.length > 0;

  return {
    isSuccess: true,
    materialId: material?.id ?? null,
    hasCreatedQuiz,
    message: hasCreatedQuiz
      ? `"${title}" 자료를 올리고 퀴즈를 만들었습니다.`
      : `"${title}" 자료를 올렸습니다. 퀴즈는 만들어지지 않았습니다. '이 자료로 퀴즈 만들기'로 다시 시도해주세요.`,
  };
}

export function describeUploadListRefreshFailure({ material, title, reason }) {
  return {
    isSuccess: true,
    materialId: material?.id ?? null,
    hasCreatedQuiz: false,
    message: `"${title}" 자료를 올렸지만 목록을 새로고침하지 못했습니다. ${reason}`,
  };
}

export function describeUploadFailure(reason) {
  return `자료를 올리지 못했습니다. ${reason}`;
}
