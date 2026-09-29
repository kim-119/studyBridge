import React, { useCallback, useEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, ExternalLink, RefreshCw } from 'lucide-react';
import { openExternalUrl } from '../platform/externalLink';
import {
  PDF_FAILURE,
  PDF_FAILURE_MESSAGE,
  classifyPdfFailure,
  isRenderCancellation,
  openPdfDocument,
} from './pdfDocumentLoader';

const PRESIGNED_URL_MAX_AGE_MS = 50 * 60 * 1000;
const MAX_PIXEL_RATIO = 2;

const VIEWER_STATUS = {
  LOADING: 'loading',
  READY: 'ready',
  FAILED: 'failed',
};

function useElementWidth(elementRef) {
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const element = elementRef.current;
    if (!element) return undefined;

    setWidth(element.clientWidth);
    if (typeof ResizeObserver === 'undefined') return undefined;

    const observer = new ResizeObserver(([entry]) => setWidth(Math.floor(entry.contentRect.width)));
    observer.observe(element);
    return () => observer.disconnect();
  }, [elementRef]);

  return width;
}

function useUrlAge(url) {
  const receivedAt = useRef(Date.now());

  useEffect(() => {
    receivedAt.current = Date.now();
  }, [url]);

  return useCallback(() => Date.now() - receivedAt.current > PRESIGNED_URL_MAX_AGE_MS, []);
}

function drawPage(page, canvas, cssWidth) {
  const pixelRatio = Math.min(window.devicePixelRatio || 1, MAX_PIXEL_RATIO);
  const naturalViewport = page.getViewport({ scale: 1 });
  const viewport = page.getViewport({ scale: (cssWidth / naturalViewport.width) * pixelRatio });

  canvas.width = Math.floor(viewport.width);
  canvas.height = Math.floor(viewport.height);

  return page.render({ canvasContext: canvas.getContext('2d'), viewport });
}

function ViewerFailure({ failure, isRetrying, onRetry, onOpenExternally }) {
  return (
    <div className="mobile-pdf__failure" role="alert">
      <p className="mobile-state__text">{PDF_FAILURE_MESSAGE[failure] || PDF_FAILURE_MESSAGE[PDF_FAILURE.UNKNOWN]}</p>
      <div className="mobile-card__actions">
        <button type="button" className="mobile-button mobile-button--ghost" disabled={isRetrying} onClick={onRetry}>
          <RefreshCw size={16} />
          다시 시도
        </button>
        <button type="button" className="mobile-button mobile-button--secondary" onClick={onOpenExternally}>
          <ExternalLink size={16} />
          외부 앱으로 열기
        </button>
      </div>
    </div>
  );
}

export default function PdfDocumentViewer({ url, title, onRefreshUrl }) {
  const frameRef = useRef(null);
  const canvasRef = useRef(null);
  const expiredRefreshUsed = useRef(false);
  const refreshHandler = useRef(onRefreshUrl);
  const width = useElementWidth(frameRef);
  const isUrlStale = useUrlAge(url);

  const [pdf, setPdf] = useState(null);
  const [pageNumber, setPageNumber] = useState(1);
  const [status, setStatus] = useState(VIEWER_STATUS.LOADING);
  const [failure, setFailure] = useState(null);
  const [reloadToken, setReloadToken] = useState(0);
  const [isRetrying, setRetrying] = useState(false);

  useEffect(() => {
    refreshHandler.current = onRefreshUrl;
  }, [onRefreshUrl]);

  const fail = useCallback((kind) => {
    setFailure(kind);
    setStatus(VIEWER_STATUS.FAILED);
  }, []);

  const refreshUrl = useCallback(async () => {
    if (!refreshHandler.current) return url;
    return (await refreshHandler.current()) || url;
  }, [url]);

  useEffect(() => {
    if (!url) return undefined;

    let isActive = true;
    const loading = openPdfDocument(url);
    setStatus(VIEWER_STATUS.LOADING);
    setFailure(null);

    loading.promise
      .then((document) => {
        if (!document) return;
        if (!isActive) {
          document.destroy();
          return;
        }
        setPdf(document);
        setPageNumber((current) => Math.min(current, document.numPages));
        setStatus(VIEWER_STATUS.READY);
      })
      .catch((error) => {
        if (!isActive) return;
        const kind = classifyPdfFailure(error);

        if (kind === PDF_FAILURE.EXPIRED && refreshHandler.current && !expiredRefreshUsed.current) {
          expiredRefreshUsed.current = true;
          refreshHandler.current().catch(() => fail(PDF_FAILURE.EXPIRED));
          return;
        }

        fail(kind);
      });

    return () => {
      isActive = false;
      loading.cancel();
    };
  }, [url, reloadToken, fail]);

  useEffect(() => {
    if (!pdf || !width || !canvasRef.current) return undefined;

    let isActive = true;
    let renderTask = null;

    pdf
      .getPage(pageNumber)
      .then((page) => {
        if (!isActive) return undefined;
        renderTask = drawPage(page, canvasRef.current, width);
        return renderTask.promise;
      })
      .catch((error) => {
        if (!isActive || isRenderCancellation(error)) return;
        fail(PDF_FAILURE.RENDER);
      });

    return () => {
      isActive = false;
      if (renderTask) renderTask.cancel();
    };
  }, [pdf, pageNumber, width, fail]);

  useEffect(() => () => pdf?.destroy(), [pdf]);

  const retry = async () => {
    expiredRefreshUsed.current = false;
    setRetrying(true);
    try {
      const freshUrl = await refreshUrl();
      if (freshUrl === url) setReloadToken((token) => token + 1);
    } catch {
      fail(PDF_FAILURE.EXPIRED);
    } finally {
      setRetrying(false);
    }
  };

  const openExternally = async () => {
    try {
      const targetUrl = isUrlStale() ? await refreshUrl() : url;
      await openExternalUrl(targetUrl);
    } catch {
      fail(PDF_FAILURE.EXPIRED);
    }
  };

  const pageCount = pdf?.numPages || 0;
  const isReady = status === VIEWER_STATUS.READY;

  return (
    <section className="mobile-pdf" aria-label={title ? `${title} 원본 문서` : '원본 문서'}>
      <div ref={frameRef} className="mobile-pdf__frame">
        <canvas ref={canvasRef} className="mobile-pdf__canvas" hidden={!isReady} />

        {status === VIEWER_STATUS.LOADING && (
          <div className="mobile-state" role="status">
            <span className="mobile-state__spinner" />
            <p className="mobile-state__text">문서를 불러오는 중입니다</p>
          </div>
        )}

        {status === VIEWER_STATUS.FAILED && (
          <ViewerFailure
            failure={failure}
            isRetrying={isRetrying}
            onRetry={retry}
            onOpenExternally={openExternally}
          />
        )}
      </div>

      {isReady && (
        <div className="mobile-pdf__toolbar">
          <button
            type="button"
            className="mobile-pdf__nav"
            aria-label="이전 페이지"
            disabled={pageNumber <= 1}
            onClick={() => setPageNumber((current) => current - 1)}
          >
            <ChevronLeft size={20} />
          </button>
          <span className="mobile-pdf__page">
            {pageNumber} / {pageCount}
          </span>
          <button
            type="button"
            className="mobile-pdf__nav"
            aria-label="다음 페이지"
            disabled={pageNumber >= pageCount}
            onClick={() => setPageNumber((current) => current + 1)}
          >
            <ChevronRight size={20} />
          </button>
          <button type="button" className="mobile-pdf__external" onClick={openExternally}>
            <ExternalLink size={16} />
            외부 앱
          </button>
        </div>
      )}
    </section>
  );
}
