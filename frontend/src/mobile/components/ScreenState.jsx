import React from 'react';
import { AlertCircle, Inbox, RefreshCw } from 'lucide-react';

export function LoadingState({ label = '불러오는 중입니다' }) {
  return (
    <div className="mobile-state" role="status">
      <span className="mobile-state__spinner" />
      <p className="mobile-state__text">{label}</p>
    </div>
  );
}

export function ErrorState({ message, onRetry }) {
  return (
    <div className="mobile-state">
      <AlertCircle size={32} className="mobile-state__icon mobile-state__icon--danger" />
      <p className="mobile-state__text">{message}</p>
      {onRetry && (
        <button type="button" className="mobile-button mobile-button--ghost" onClick={onRetry}>
          <RefreshCw size={16} />
          다시 시도
        </button>
      )}
    </div>
  );
}

export function EmptyState({ message, action }) {
  return (
    <div className="mobile-state">
      <Inbox size={32} className="mobile-state__icon" />
      <p className="mobile-state__text">{message}</p>
      {action}
    </div>
  );
}

export default function ScreenState({ query, emptyWhen, emptyMessage, children, loadingLabel }) {
  if (query.isLoading && !query.data) return <LoadingState label={loadingLabel} />;
  if (query.isError) return <ErrorState message={query.errorMessage} onRetry={query.reload} />;
  if (emptyWhen && emptyWhen(query.data)) return <EmptyState message={emptyMessage} />;
  return children;
}
