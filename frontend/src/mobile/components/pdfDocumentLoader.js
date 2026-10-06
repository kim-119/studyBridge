import { PdfDownloadError, canDownloadPdfNatively, downloadPdfBytes } from '../platform/pdfBytes';

export const PDF_FAILURE = {
  BLOCKED: 'blocked',
  EXPIRED: 'expired',
  MISSING: 'missing',
  INVALID: 'invalid',
  RENDER: 'render',
  UNKNOWN: 'unknown',
};

export const PDF_FAILURE_MESSAGE = {
  [PDF_FAILURE.BLOCKED]: '문서 파일에 접근하지 못했습니다. 네트워크 상태를 확인하거나 외부 앱으로 열어주세요.',
  [PDF_FAILURE.EXPIRED]: '문서 열람 링크가 만료되었습니다. 다시 시도해주세요.',
  [PDF_FAILURE.MISSING]: '저장된 문서 파일을 찾을 수 없습니다.',
  [PDF_FAILURE.INVALID]: 'PDF 파일 형식이 올바르지 않아 표시할 수 없습니다.',
  [PDF_FAILURE.RENDER]: '페이지를 그리는 중 오류가 발생했습니다.',
  [PDF_FAILURE.UNKNOWN]: '문서를 표시하지 못했습니다.',
};

const EXPIRED_STATUSES = new Set([400, 401, 403]);

let pdfjsModule = null;

async function loadPdfjs() {
  if (!pdfjsModule) {
    pdfjsModule = Promise.all([
      import('pdfjs-dist/legacy/build/pdf.mjs'),
      import('pdfjs-dist/legacy/build/pdf.worker.min.mjs?url'),
    ]).then(([pdfjs, worker]) => {
      pdfjs.GlobalWorkerOptions.workerSrc = worker.default;
      return pdfjs;
    });
  }

  try {
    return await pdfjsModule;
  } catch (error) {
    pdfjsModule = null;
    throw error;
  }
}

function bundledPdfjsAssetUrl(directory) {
  return new URL(`pdfjs/${directory}/`, document.baseURI).href;
}

async function documentSourceOf(url) {
  const baseOptions = {
    isEvalSupported: false,
    disableRange: true,
    disableStream: true,
    cMapUrl: bundledPdfjsAssetUrl('cmaps'),
    cMapPacked: true,
    standardFontDataUrl: bundledPdfjsAssetUrl('standard_fonts'),
  };

  if (canDownloadPdfNatively()) {
    const bytes = await downloadPdfBytes(url);
    return { ...baseOptions, data: bytes };
  }

  return { ...baseOptions, url };
}

export function openPdfDocument(url) {
  let loadingTask = null;
  let isCancelled = false;
  let isSettled = false;

  const promise = (async () => {
    const [pdfjs, source] = await Promise.all([loadPdfjs(), documentSourceOf(url)]);
    if (isCancelled) return null;

    loadingTask = pdfjs.getDocument(source);
    const pdfDocument = await loadingTask.promise;
    isSettled = true;
    return pdfDocument;
  })();

  const cancel = () => {
    isCancelled = true;
    if (loadingTask && !isSettled) loadingTask.destroy();
  };

  return { promise, cancel };
}

export function classifyPdfFailure(error) {
  if (error instanceof PdfDownloadError) {
    if (error.status === 404) return PDF_FAILURE.MISSING;
    if (EXPIRED_STATUSES.has(error.status)) return PDF_FAILURE.EXPIRED;
    return PDF_FAILURE.BLOCKED;
  }

  if (error?.name === 'InvalidPDFException') return PDF_FAILURE.INVALID;
  if (error?.name === 'MissingPDFException') return PDF_FAILURE.MISSING;
  if (error?.name === 'UnexpectedResponseException' && EXPIRED_STATUSES.has(error.status)) {
    return PDF_FAILURE.EXPIRED;
  }
  if (error?.name === 'UnexpectedResponseException' || error instanceof TypeError) return PDF_FAILURE.BLOCKED;

  return PDF_FAILURE.UNKNOWN;
}

export function isRenderCancellation(error) {
  return error?.name === 'RenderingCancelledException';
}
