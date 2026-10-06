import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Smartphone, Download, CalendarDays, ListChecks, ShieldCheck, AlertCircle, RefreshCw } from 'lucide-react';
import api from '../services/api';
import './AppDownload.css';

/**
 * /app — Android APK 다운로드 전용 단일 페이지(공개, 로그인 불필요).
 *  · 데이터 원천: GET /api/app/version (서버가 S3 latest/version.json 을 중계). 캐시하지 않는다.
 *  · 다운로드 버튼은 API 의 downloadUrl(안정 URL, /downloads/android/StudyBridge-latest.apk)만 사용한다.
 *  · 릴리즈가 아직 없으면(404 NO_RELEASE) "준비 중" 상태를 보여준다. 업데이트 체크/자동 설치는 이 페이지 범위가 아니다.
 */
export default function AppDownload() {
  const [state, setState] = useState({ status: 'loading', data: null, message: '' });

  const load = async () => {
    setState({ status: 'loading', data: null, message: '' });
    try {
      const res = await api.get('/api/app/version');
      setState({ status: 'ready', data: res.data, message: '' });
    } catch (err) {
      const status = err?.response?.status;
      const code = err?.response?.data?.code;
      if (status === 404 && code === 'NO_RELEASE') {
        setState({ status: 'empty', data: null, message: '' });
      } else {
        setState({ status: 'error', data: null, message: '버전 정보를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.' });
      }
    }
  };

  useEffect(() => { load(); }, []);

  const { status, data } = state;

  return (
    <div className="app-dl-page">
      <div className="app-dl-card glass-panel">
        <header className="app-dl-header">
          <img src="/studybridge-main-logo.png" alt="StudyBridge" className="app-dl-logo" />
          <h1 className="app-dl-title">StudyBridge</h1>
          <p className="app-dl-subtitle"><Smartphone size={16} aria-hidden="true" /> Android Application</p>
        </header>

        {status === 'loading' && (
          <p className="app-dl-status">최신 버전 정보를 확인하는 중…</p>
        )}

        {status === 'error' && (
          <div className="app-dl-status app-dl-status--error" role="alert">
            <AlertCircle size={16} aria-hidden="true" />
            <span>{state.message}</span>
            <button type="button" className="btn-outline app-dl-retry" onClick={load}>
              <RefreshCw size={14} aria-hidden="true" /> 다시 시도
            </button>
          </div>
        )}

        {status === 'empty' && (
          <div className="app-dl-status" role="status">
            <p className="app-dl-empty-title">앱 준비 중</p>
            <p>아직 배포된 Android 버전이 없습니다. 첫 릴리즈가 올라오면 이 페이지에서 바로 내려받을 수 있습니다.</p>
          </div>
        )}

        {status === 'ready' && data && (
          <>
            <section className="app-dl-version">
              <span className="app-dl-label">최신 버전</span>
              <span className="app-dl-version-value">v{data.versionName}</span>
              <span className="app-dl-meta">versionCode {data.versionCode}{data.fileSize ? ` · ${formatSize(data.fileSize)}` : ''}</span>
            </section>

            <section className="app-dl-row">
              <span className="app-dl-label"><CalendarDays size={14} aria-hidden="true" /> 업데이트 날짜</span>
              <span className="app-dl-value">{formatDate(data.releaseDate)}</span>
            </section>

            <section className="app-dl-row app-dl-row--notes">
              <span className="app-dl-label"><ListChecks size={14} aria-hidden="true" /> 변경사항</span>
              {Array.isArray(data.releaseNotes) && data.releaseNotes.length > 0 ? (
                <ul className="app-dl-notes">
                  {data.releaseNotes.map((note, i) => <li key={i}>{note}</li>)}
                </ul>
              ) : (
                <span className="app-dl-value app-dl-value--muted">등록된 변경사항이 없습니다.</span>
              )}
            </section>

            <a className="btn-primary app-dl-button" href={data.downloadUrl} rel="noopener">
              <Download size={18} aria-hidden="true" /> Android 앱 다운로드
            </a>

            <p className="app-dl-hint">
              설치 시 브라우저/설정에서 <strong>출처를 알 수 없는 앱 설치 허용</strong>이 필요할 수 있습니다.
              패키지: <code>{data.packageName}</code>
            </p>

            {data.sha256 && (
              <p className="app-dl-sha">
                <ShieldCheck size={14} aria-hidden="true" /> SHA-256 <code>{data.sha256}</code>
              </p>
            )}
          </>
        )}

        <footer className="app-dl-footer">
          <Link to="/">웹에서 StudyBridge 이용하기</Link>
        </footer>
      </div>
    </div>
  );
}

function formatDate(iso) {
  if (!iso) return '-';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString('ko-KR', { year: 'numeric', month: 'long', day: 'numeric' });
}

function formatSize(bytes) {
  const n = Number(bytes);
  if (!Number.isFinite(n) || n <= 0) return '';
  if (n >= 1024 * 1024) return `${(n / (1024 * 1024)).toFixed(1)} MB`;
  if (n >= 1024) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}
