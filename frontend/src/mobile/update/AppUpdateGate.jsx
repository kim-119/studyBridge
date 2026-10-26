import React, { useEffect, useState } from 'react';
import Button from '../components/Button';
import { useBackDismiss } from '../platform/useBackDismiss';
import { appUpdateSession } from './appUpdateCheck';
import { UPDATE_KIND, formatFileSize } from './releaseManifest';
import { openUpdateDownload } from './updateDownload';

const DOWNLOAD_FAILURE_MESSAGE = '다운로드 페이지를 열지 못했습니다. 잠시 후 다시 시도해주세요.';

function ignoreBackPress() {}

function shouldShowUpdate(decision, session) {
  if (!decision || decision.kind === UPDATE_KIND.NONE) return false;
  if (decision.kind === UPDATE_KIND.FORCED) return true;
  return !session.isDismissed(decision.versionCode);
}

function VersionRow({ label, value }) {
  return (
    <div className="mobile-update__version">
      <span className="mobile-update__version-label">{label}</span>
      <span className="mobile-update__version-value">{value}</span>
    </div>
  );
}

function ReleaseNotes({ notes }) {
  if (notes.length === 0) return null;

  return (
    <div className="mobile-update__notes">
      <p className="mobile-update__notes-title">업데이트 내용</p>
      <ul className="mobile-update__notes-list">
        {notes.map((note) => (
          <li key={note}>{note}</li>
        ))}
      </ul>
    </div>
  );
}

export function AppUpdateDialog({ decision, onLater, onUpdate, isOpening, errorMessage }) {
  const isForced = decision.kind === UPDATE_KIND.FORCED;
  const title = isForced ? '업데이트가 필요합니다' : '새로운 업데이트가 있습니다';
  const fileSize = formatFileSize(decision.fileSize);

  useBackDismiss(true, isForced ? ignoreBackPress : onLater);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, []);

  return (
    <div className="mobile-sheet mobile-update" role="alertdialog" aria-modal="true" aria-label={title}>
      <div className="mobile-sheet__scrim" />

      <div className="mobile-sheet__panel">
        <div className="mobile-sheet__header">
          <h2 className="mobile-sheet__title">{title}</h2>
        </div>

        <div className="mobile-sheet__body">
          {isForced && (
            <p className="mobile-update__message">
              StudyBridge를 계속 사용하려면 최신 버전으로 업데이트해야 합니다.
            </p>
          )}

          <div className="mobile-update__versions">
            <VersionRow label="현재 버전" value={decision.currentVersionName} />
            <VersionRow label="최신 버전" value={decision.latestVersionName} />
            {fileSize && <VersionRow label="파일 크기" value={fileSize} />}
          </div>

          <ReleaseNotes notes={decision.releaseNotes} />

          {errorMessage && (
            <p className="mobile-update__error" role="alert">
              {errorMessage}
            </p>
          )}

          <div className="mobile-update__actions">
            {!isForced && (
              <Button variant="secondary" fullWidth onClick={onLater}>
                나중에
              </Button>
            )}
            <Button variant="primary" fullWidth isLoading={isOpening} onClick={onUpdate}>
              업데이트
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

export default function AppUpdateGate({ children, session = appUpdateSession, openDownload = openUpdateDownload }) {
  const [decision, setDecision] = useState(null);
  const [isOpening, setOpening] = useState(false);
  const [errorMessage, setErrorMessage] = useState(null);

  useEffect(() => {
    let isMounted = true;

    session.check().then((result) => {
      if (isMounted) setDecision(result);
    });

    return () => {
      isMounted = false;
    };
  }, [session]);

  const closeForThisSession = () => {
    session.dismiss(decision.versionCode);
    setDecision(null);
  };

  const startDownload = async () => {
    setOpening(true);
    setErrorMessage(null);

    const isOpened = await openDownload(decision.downloadUrl);

    setOpening(false);
    if (!isOpened) {
      setErrorMessage(DOWNLOAD_FAILURE_MESSAGE);
      return;
    }
    if (decision.kind === UPDATE_KIND.OPTIONAL) closeForThisSession();
  };

  return (
    <>
      {children}
      {shouldShowUpdate(decision, session) && (
        <AppUpdateDialog
          decision={decision}
          onLater={closeForThisSession}
          onUpdate={startDownload}
          isOpening={isOpening}
          errorMessage={errorMessage}
        />
      )}
    </>
  );
}
