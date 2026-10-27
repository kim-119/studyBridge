import React, { useEffect, useId, useState } from 'react';
import { Link } from 'react-router-dom';
import { Download, CalendarDays, Sparkles, ShieldCheck, ChevronDown, AlertCircle, RefreshCw } from 'lucide-react';
import api from '../services/api';
import {
  RELEASE_NOTES_PLACEHOLDER,
  toUserReleaseNotes,
  formatReleaseDate,
  formatFileSize,
  safeDownloadUrl,
} from '../utils/appRelease';
import './AppDownload.css';

/**
 * /app — Android APK 다운로드 전용 단일 페이지(공개, 로그인 불필요).
 *  · 데이터 원천: GET /api/app/version (서버가 S3 latest/version.json 을 중계). 캐시하지 않는다.
 *  · 다운로드 버튼은 API 의 downloadUrl(안정 URL, /downloads/android/StudyBridge-latest.apk)만 사용한다.
 *  · 릴리즈가 아직 없으면(404 NO_RELEASE) "준비 중" 상태를 보여준다. 업데이트 체크/자동 설치는 이 페이지 범위가 아니다.
 *  · releaseNotes 는 utils/appRelease 정책으로 개발용(커밋/CI) 문장을 걸러 보여 주고,
 *    packageName/versionCode/SHA-256 은 일반 사용자 화면에서 빼고 "기술 정보" 안에 접어 둔다.
 */
export default function AppDownload() {
  const [state, setState] = useState({ status: 'loading', data: null });

  const load = async () => {
    setState({ status: 'loading', data: null });
    try {
      const res = await api.get('/api/app/version');
      const data = res?.data;
      // SPA 폴백 HTML 등 JSON 이 아닌 응답은 오류로 본다(빈 "v" 표시 방지).
      if (!data || typeof data !== 'object' || !data.versionName) {
        setState({ status: 'error', data: null });
        return;
      }
      setState({ status: 'ready', data });
    } catch (err) {
      const status = err?.response?.status;
      const code = err?.response?.data?.code;
      setState({ status: status === 404 && code === 'NO_RELEASE' ? 'empty' : 'error', data: null });
    }
  };

  useEffect(() => { load(); }, []);

  const { status, data } = state;

  return (
    <div className="app-dl-page">
      <div className="app-dl-card glass-panel">
        <header className="app-dl-header">
          <img src="/studybridge-main-logo.png" alt="" className="app-dl-logo" />
          <h1 className="app-dl-title">StudyBridge</h1>
          <p className="app-dl-subtitle">AI와 함께하는 스마트 학습 플랫폼</p>
        </header>

        {status === 'loading' && (
          <p className="app-dl-status" role="status" aria-live="polite">최신 버전 정보를 확인하는 중…</p>
        )}

        {status === 'error' && (
          <div className="app-dl-status app-dl-status--error" role="alert">
            <AlertCircle size={18} aria-hidden="true" />
            <span>버전 정보를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.</span>
            <button type="button" className="btn-outline app-dl-retry" onClick={load}>
              <RefreshCw size={14} aria-hidden="true" /> 다시 시도
            </button>
          </div>
        )}

        {status === 'empty' && (
          <div className="app-dl-status" role="status">
            <p className="app-dl-empty-title">앱 준비 중</p>
            <p>아직 배포된 Android 버전이 없습니다. 첫 버전이 올라오면 이 페이지에서 바로 내려받을 수 있습니다.</p>
          </div>
        )}

        {status === 'ready' && data && (
          <>
            <VersionCard data={data} />
            <ReleaseNotes notes={toUserReleaseNotes(data.releaseNotes)} />
            <DownloadSection url={safeDownloadUrl(data.downloadUrl)} />
            <TechInfo data={data} />
          </>
        )}

        <footer className="app-dl-footer">
          <Link to="/">웹에서 StudyBridge 이용하기</Link>
        </footer>
      </div>
    </div>
  );
}

function VersionCard({ data }) {
  const size = formatFileSize(data.fileSize);
  const date = formatReleaseDate(data.releaseDate);
  return (
    <section className="app-dl-version" aria-label="최신 버전 정보">
      <span className="app-dl-label">최신 버전</span>
      <span className="app-dl-version-value">v{data.versionName}</span>
      <span className="app-dl-meta">{size ? `Android · ${size}` : 'Android'}</span>
      {date && (
        <span className="app-dl-meta app-dl-meta--date">
          <CalendarDays size={14} aria-hidden="true" /> {date} 업데이트
        </span>
      )}
    </section>
  );
}

function ReleaseNotes({ notes }) {
  return (
    <section className="app-dl-section" aria-labelledby="app-dl-notes-title">
      <h2 id="app-dl-notes-title" className="app-dl-section-title">
        <Sparkles size={16} aria-hidden="true" /> 이번 업데이트에서 달라진 점
      </h2>
      {notes.length > 0 ? (
        <ol className="app-dl-notes">
          {notes.map((note, i) => (
            <li key={`${i}-${note.body}`} className="app-dl-note">
              <span className="app-dl-note-num" aria-hidden="true">{i + 1}</span>
              <div className="app-dl-note-text">
                {note.title && <strong className="app-dl-note-title">{note.title}</strong>}
                <span className="app-dl-note-body">{note.body}</span>
              </div>
            </li>
          ))}
        </ol>
      ) : (
        <p className="app-dl-muted">{RELEASE_NOTES_PLACEHOLDER}</p>
      )}
    </section>
  );
}

function DownloadSection({ url }) {
  if (!url) {
    return <p className="app-dl-status app-dl-status--error" role="alert">다운로드 링크를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.</p>;
  }
  return (
    <section className="app-dl-section" aria-label="다운로드 및 설치 안내">
      <a className="btn-primary app-dl-button" href={url} rel="noopener">
        <Download size={18} aria-hidden="true" /> Android 앱 다운로드
      </a>
      <div className="app-dl-guide">
        <h2 className="app-dl-guide-title">설치 방법</h2>
        <ol className="app-dl-guide-steps">
          <li>위 버튼을 눌러 설치 파일(APK)을 내려받습니다.</li>
          <li>다운로드가 끝나면 알림 또는 ‘내 파일’ 앱에서 파일을 엽니다.</li>
          <li>처음 설치한다면 <strong>‘알 수 없는 앱 설치’</strong> 허용을 묻는 화면이 나올 수 있습니다. 허용한 뒤 설치를 계속하세요.</li>
        </ol>
      </div>
    </section>
  );
}

function TechInfo({ data }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  return (
    <section className="app-dl-tech">
      <button
        type="button"
        className="app-dl-tech-toggle"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
      >
        <ShieldCheck size={14} aria-hidden="true" />
        <span>{open ? '기술 정보 숨기기' : '기술 정보 보기'}</span>
        <ChevronDown size={14} aria-hidden="true" className="app-dl-tech-chevron" />
      </button>
      <dl id={panelId} className="app-dl-tech-list" hidden={!open}>
        <div className="app-dl-tech-row">
          <dt>패키지 이름</dt>
          <dd><code>{data.packageName || '-'}</code></dd>
        </div>
        <div className="app-dl-tech-row">
          <dt>버전 코드</dt>
          <dd><code>{data.versionCode ?? '-'}</code></dd>
        </div>
        <div className="app-dl-tech-row">
          <dt>SHA-256</dt>
          <dd><code>{data.sha256 || '-'}</code></dd>
        </div>
      </dl>
    </section>
  );
}
