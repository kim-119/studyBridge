import React from 'react';
import { RefreshCw } from 'lucide-react';
import { SEMANTIC_REASON_KO } from '../../../components/graph/SemanticGraphStatus';

const REASONS_WITHOUT_RETRY = new Set(['NO_ANSWERS', 'EMPTY_ANSWER']);

function RetryButton({ label, onRetry }) {
  return (
    <button type="button" className="mobile-button mobile-button--ghost" onClick={() => onRetry(true)}>
      <RefreshCw size={16} />
      {label}
    </button>
  );
}

export default function SemanticStatusNotice({ state, reason, onRetry }) {
  if (state === 'loading') {
    return (
      <p className="mobile-notice" role="status" aria-live="polite">
        AI가 답변에서 개념 구조를 추출하는 중입니다. 몇 초 걸릴 수 있어요.
      </p>
    );
  }

  if (state === 'degraded') {
    return (
      <div className="mobile-notice" role="status" data-semantic-status="DEGRADED">
        <p className="mobile-paragraph">개념 구조가 축약 모드(DEGRADED)로 생성되었습니다.</p>
        {onRetry && <RetryButton label="다시 생성" onRetry={onRetry} />}
      </div>
    );
  }

  if (state === 'failed') {
    const canRetry = onRetry && !REASONS_WITHOUT_RETRY.has(reason);
    return (
      <div className="mobile-notice" role="alert" data-semantic-status="FAILED">
        <p className="mobile-auth__error">
          개념 구조를 생성하지 못했습니다. {SEMANTIC_REASON_KO[reason] || (reason ? `(${reason})` : '')}
        </p>
        {canRetry && <RetryButton label="다시 시도" onRetry={onRetry} />}
      </div>
    );
  }

  return null;
}
