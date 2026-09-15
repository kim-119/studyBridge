import React, { useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { KeyRound, Mail, Lock, ShieldCheck, AlertCircle, CheckCircle2 } from 'lucide-react';
import { authService } from '../services/api';

/**
 * 비밀번호 찾기(이메일 인증번호) 3단계 화면.
 *  1) 이메일 입력 → 인증번호 발송   2) 인증번호 입력 → 서버 검증   3) 새 비밀번호 설정 → 로그인 이동
 * 권한 판단은 전부 Spring(Redis verified 상태)이 한다. 화면 상태는 안내용일 뿐이며 3단계 요청도 서버가 재검증한다.
 */
const EMAIL_REGEX = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;
// 회원가입/서버(PasswordResetService.PASSWORD_POLICY)와 동일 정책: 8~16자, 영문+숫자+특수문자, 공백 불가
const PASSWORD_REGEX = /^(?=.*[A-Za-z])(?=.*\d)(?=.*[^A-Za-z0-9\s])[^\s]{8,16}$/;

const inputStyle = {
  width: '100%',
  boxSizing: 'border-box',
  padding: '13px 14px 13px 44px',
  borderRadius: '10px',
  border: '1px solid var(--color-border)',
  outline: 'none',
};

const iconStyle = {
  position: 'absolute',
  left: '14px',
  top: '50%',
  transform: 'translateY(-50%)',
  color: 'var(--color-text-muted)',
};

const labelStyle = {
  display: 'block',
  marginBottom: '8px',
  color: 'var(--color-text)',
  fontWeight: '600',
};

const primaryButton = (disabled) => ({
  width: '100%',
  padding: '14px',
  borderRadius: '10px',
  border: 'none',
  background: 'var(--color-primary)',
  color: '#fff',
  fontWeight: '700',
  cursor: disabled ? 'not-allowed' : 'pointer',
  opacity: disabled ? 0.7 : 1,
});

const secondaryButton = (disabled) => ({
  width: '100%',
  padding: '12px',
  borderRadius: '10px',
  border: '1px solid var(--color-border)',
  background: 'transparent',
  color: 'var(--color-text)',
  fontWeight: '600',
  cursor: disabled ? 'not-allowed' : 'pointer',
  opacity: disabled ? 0.6 : 1,
  marginTop: '10px',
});

// 서버 오류 응답({status, message, reason, retryAfterSeconds}) → 사용자 문구. 스택트레이스/원문 노출 없음.
function describeError(err, fallback) {
  if (!err) return fallback;
  if (err.networkError) return '서버에 연결할 수 없습니다. 네트워크 상태를 확인해주세요.';
  const status = err.status;
  if (status >= 500 && status !== 503) return '서버 오류가 발생했습니다. 잠시 후 다시 시도해주세요.';
  if (err.message && typeof err.message === 'string') return err.message;
  return fallback;
}

export default function ForgotPassword() {
  const navigate = useNavigate();

  const [step, setStep] = useState(1); // 1: 이메일, 2: 인증번호, 3: 새 비밀번호, 4: 완료
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newPasswordConfirm, setNewPasswordConfirm] = useState('');

  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [resendLeft, setResendLeft] = useState(0); // 재전송 가능까지 남은 초
  const [codeLeft, setCodeLeft] = useState(0); // 인증번호 유효시간 남은 초
  const timerRef = useRef(null);

  // 1초 틱: 재전송 제한/인증번호 유효시간 카운트다운
  useEffect(() => {
    if (resendLeft <= 0 && codeLeft <= 0) return undefined;
    timerRef.current = setInterval(() => {
      setResendLeft((s) => (s > 0 ? s - 1 : 0));
      setCodeLeft((s) => (s > 0 ? s - 1 : 0));
    }, 1000);
    return () => clearInterval(timerRef.current);
  }, [resendLeft > 0, codeLeft > 0]);

  const clearMessages = () => {
    if (error) setError('');
    if (notice) setNotice('');
  };

  const formatMmSs = (sec) => {
    const m = Math.floor(sec / 60);
    const s = sec % 60;
    return `${m}:${String(s).padStart(2, '0')}`;
  };

  // ── 1) 인증번호 발송 / 재전송 ──
  const handleSendCode = async (e) => {
    if (e) e.preventDefault();
    clearMessages();
    const trimmed = email.trim();
    if (!EMAIL_REGEX.test(trimmed)) {
      setError('올바른 이메일 형식을 입력해주세요.');
      return;
    }
    if (resendLeft > 0) {
      setError(`인증번호는 ${resendLeft}초 후에 다시 요청할 수 있습니다.`);
      return;
    }
    setLoading(true);
    try {
      const isResend = step === 2;
      const res = await authService.sendPasswordResetCode(trimmed);
      setEmail(trimmed);
      setCode('');
      setResendLeft(Number(res?.resendAfterSeconds) || 60);
      setCodeLeft(Number(res?.expiresInSeconds) || 300);
      // 재전송 성공 = 서버가 새 인증번호로 교체(마지막 발급분만 유효). 같은 제목이라 Gmail 은 한 스레드로 묶으므로
      //  "가장 최근 메일" 을 보라고 명시해 이전 메일의 번호를 입력하는 혼동을 막는다.
      setNotice(isResend
        ? '새 인증번호를 발송했습니다. 가장 최근에 받은 메일의 인증번호를 입력해 주세요. 이전 인증번호는 더 이상 사용할 수 없습니다.'
        : (res?.message || '인증번호를 발송했습니다. 메일함을 확인해 주세요.'));
      setStep(2);
    } catch (err) {
      if (err?.reason === 'RESEND_COOLDOWN') {
        const left = Number(err.retryAfterSeconds) || 60;
        setResendLeft(left);
        setError(`인증번호 재전송은 ${left}초 후에 가능합니다.`);
        if (step === 1) setStep(2);
      } else if (err?.reason === 'TOO_MANY_REQUESTS') {
        setError(describeError(err, '요청이 너무 많습니다. 잠시 후 다시 시도해주세요.'));
      } else if (err?.reason === 'MAIL_NOT_CONFIGURED' || err?.reason === 'MAIL_SEND_FAILED' || err?.reason === 'STORE_UNAVAILABLE') {
        setError(describeError(err, '인증메일을 발송할 수 없습니다. 잠시 후 다시 시도해주세요.'));
      } else {
        setError(describeError(err, '인증번호 발송에 실패했습니다.'));
      }
    } finally {
      setLoading(false);
    }
  };

  // ── 2) 인증번호 검증 ──
  const handleVerifyCode = async (e) => {
    e.preventDefault();
    clearMessages();
    const trimmedCode = code.trim();
    if (!/^\d{6}$/.test(trimmedCode)) {
      setError('인증번호 6자리 숫자를 입력해주세요.');
      return;
    }
    setLoading(true);
    try {
      const res = await authService.verifyPasswordResetCode(email, trimmedCode);
      setCodeLeft(0);
      setNotice(res?.message || '인증이 완료되었습니다. 새 비밀번호를 설정해 주세요.');
      setStep(3);
    } catch (err) {
      if (err?.reason === 'CODE_EXPIRED') {
        setCodeLeft(0);
        setError('인증번호가 만료되었습니다. 인증번호를 다시 요청해주세요.');
      } else if (err?.reason === 'CODE_ATTEMPTS_EXCEEDED') {
        setCodeLeft(0);
        setError('인증 시도 횟수를 초과했습니다. 인증번호를 다시 요청해주세요.');
      } else if (err?.reason === 'CODE_MISMATCH') {
        setError(describeError(err, '인증번호가 올바르지 않습니다.'));
      } else {
        setError(describeError(err, '인증에 실패했습니다.'));
      }
    } finally {
      setLoading(false);
    }
  };

  // ── 3) 새 비밀번호 설정 ──
  const handleReset = async (e) => {
    e.preventDefault();
    clearMessages();
    if (!PASSWORD_REGEX.test(newPassword)) {
      setError('비밀번호는 8~16자이며 영문, 숫자, 특수문자를 모두 포함해야 합니다.');
      return;
    }
    if (newPassword !== newPasswordConfirm) {
      setError('새 비밀번호 확인이 일치하지 않습니다.');
      return;
    }
    setLoading(true);
    try {
      const res = await authService.resetPassword(email, newPassword, newPasswordConfirm);
      setNotice(res?.message || '비밀번호가 변경되었습니다. 새 비밀번호로 로그인해 주세요.');
      setNewPassword('');
      setNewPasswordConfirm('');
      setStep(4);
    } catch (err) {
      if (err?.reason === 'NOT_VERIFIED') {
        // 서버 인증 상태(10분)가 없거나 만료 → 처음부터 다시
        setError('인증 유효시간이 지났거나 인증이 확인되지 않았습니다. 이메일 인증을 다시 진행해주세요.');
        setStep(1);
        setCode('');
      } else if (err?.reason === 'PASSWORD_POLICY' || err?.reason === 'PASSWORD_CONFIRM_MISMATCH' || err?.reason === 'PASSWORD_SAME_AS_OLD') {
        setError(describeError(err, '비밀번호 조건을 확인해주세요.'));
      } else {
        setError(describeError(err, '비밀번호 변경에 실패했습니다.'));
      }
    } finally {
      setLoading(false);
    }
  };

  const restart = () => {
    clearMessages();
    setStep(1);
    setCode('');
    setCodeLeft(0);
  };

  const stepTitle = {
    1: '가입한 이메일을 입력하면 인증번호를 보내드립니다.',
    2: '이메일로 받은 6자리 인증번호를 입력해 주세요.',
    3: '새로 사용할 비밀번호를 입력해 주세요.',
    4: '비밀번호 변경이 완료되었습니다.',
  }[step];

  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        minHeight: 'calc(100vh - 120px)',
        padding: 'clamp(16px, 4vw, 24px)',
      }}
    >
      <div
        className="glass-panel animate-fade-in"
        style={{ width: '100%', maxWidth: '420px', padding: 'clamp(20px, 5vw, 36px)', boxSizing: 'border-box' }}
      >
        <div style={{ textAlign: 'center', marginBottom: '28px' }}>
          <div
            style={{
              width: '64px',
              height: '64px',
              borderRadius: '18px',
              background: 'var(--color-primary)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              margin: '0 auto 16px',
              color: '#fff',
            }}
          >
            {step === 4 ? <CheckCircle2 size={32} /> : <KeyRound size={32} />}
          </div>
          <h1 style={{ fontSize: '28px', fontWeight: '700', color: 'var(--color-text)', margin: 0 }}>비밀번호 찾기</h1>
          <p style={{ color: 'var(--color-text-muted)', marginTop: '8px' }}>{stepTitle}</p>
          {step < 4 && (
            <div style={{ display: 'flex', justifyContent: 'center', gap: '6px', marginTop: '14px' }}>
              {[1, 2, 3].map((n) => (
                <span
                  key={n}
                  aria-label={`${n}단계`}
                  style={{
                    width: '28px',
                    height: '6px',
                    borderRadius: '3px',
                    background: n <= step ? 'var(--color-primary)' : 'var(--color-border)',
                  }}
                />
              ))}
            </div>
          )}
        </div>

        {error && (
          <div
            role="alert"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              padding: '12px',
              borderRadius: '10px',
              background: '#fee2e2',
              color: '#dc2626',
              marginBottom: '18px',
              fontSize: '14px',
            }}
          >
            <AlertCircle size={18} />
            <span>{error}</span>
          </div>
        )}
        {notice && !error && (
          <div
            role="status"
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              padding: '12px',
              borderRadius: '10px',
              background: '#dcfce7',
              color: '#15803d',
              marginBottom: '18px',
              fontSize: '14px',
            }}
          >
            <CheckCircle2 size={18} />
            <span>{notice}</span>
          </div>
        )}

        {/* 1단계: 이메일 */}
        {step === 1 && (
          <form onSubmit={handleSendCode}>
            <div style={{ marginBottom: '22px' }}>
              <label style={labelStyle} htmlFor="reset-email">이메일</label>
              <div style={{ position: 'relative' }}>
                <Mail size={20} style={iconStyle} />
                <input
                  id="reset-email"
                  type="email"
                  name="email"
                  autoComplete="email"
                  value={email}
                  onChange={(e) => { setEmail(e.target.value); clearMessages(); }}
                  placeholder="가입한 이메일을 입력하세요"
                  style={inputStyle}
                />
              </div>
            </div>
            <button type="submit" disabled={loading} style={primaryButton(loading)}>
              {loading ? '인증번호 발송 중...' : '인증번호 발송'}
            </button>
          </form>
        )}

        {/* 2단계: 인증번호 */}
        {step === 2 && (
          <form onSubmit={handleVerifyCode}>
            <div style={{ marginBottom: '16px' }}>
              <label style={labelStyle}>이메일</label>
              <div style={{ position: 'relative' }}>
                <Mail size={20} style={iconStyle} />
                <input type="email" value={email} readOnly style={{ ...inputStyle, background: '#f3f4f6', color: 'var(--color-text-muted)' }} />
              </div>
            </div>
            <div style={{ marginBottom: '8px' }}>
              <label style={labelStyle} htmlFor="reset-code">인증번호</label>
              <div style={{ position: 'relative' }}>
                <ShieldCheck size={20} style={iconStyle} />
                <input
                  id="reset-code"
                  type="text"
                  inputMode="numeric"
                  autoComplete="one-time-code"
                  maxLength={6}
                  value={code}
                  onChange={(e) => { setCode(e.target.value.replace(/\D/g, '').slice(0, 6)); clearMessages(); }}
                  placeholder="6자리 숫자"
                  style={{ ...inputStyle, letterSpacing: '6px', fontWeight: '700' }}
                />
              </div>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px', color: 'var(--color-text-muted)', marginBottom: '18px' }}>
              <span>{codeLeft > 0 ? `유효시간 ${formatMmSs(codeLeft)}` : '인증번호가 만료되었을 수 있습니다.'}</span>
              <span>{resendLeft > 0 ? `재전송 ${resendLeft}초 후 가능` : '재전송 가능'}</span>
            </div>
            <button type="submit" disabled={loading || code.length !== 6} style={primaryButton(loading || code.length !== 6)}>
              {loading ? '인증 확인 중...' : '인증 확인'}
            </button>
            <button type="button" onClick={handleSendCode} disabled={loading || resendLeft > 0} style={secondaryButton(loading || resendLeft > 0)}>
              {resendLeft > 0 ? `인증번호 재전송 (${resendLeft}초)` : '인증번호 재전송'}
            </button>
            <button type="button" onClick={restart} disabled={loading} style={{ ...secondaryButton(loading), border: 'none', color: 'var(--color-text-muted)' }}>
              이메일 다시 입력
            </button>
          </form>
        )}

        {/* 3단계: 새 비밀번호 */}
        {step === 3 && (
          <form onSubmit={handleReset}>
            <div style={{ marginBottom: '16px' }}>
              <label style={labelStyle} htmlFor="reset-new-password">새 비밀번호</label>
              <div style={{ position: 'relative' }}>
                <Lock size={20} style={iconStyle} />
                <input
                  id="reset-new-password"
                  type="password"
                  autoComplete="new-password"
                  value={newPassword}
                  onChange={(e) => { setNewPassword(e.target.value); clearMessages(); }}
                  placeholder="8~16자, 영문+숫자+특수문자"
                  style={inputStyle}
                />
              </div>
            </div>
            <div style={{ marginBottom: '22px' }}>
              <label style={labelStyle} htmlFor="reset-new-password-confirm">새 비밀번호 확인</label>
              <div style={{ position: 'relative' }}>
                <Lock size={20} style={iconStyle} />
                <input
                  id="reset-new-password-confirm"
                  type="password"
                  autoComplete="new-password"
                  value={newPasswordConfirm}
                  onChange={(e) => { setNewPasswordConfirm(e.target.value); clearMessages(); }}
                  placeholder="새 비밀번호를 한 번 더 입력하세요"
                  style={inputStyle}
                />
              </div>
            </div>
            <button type="submit" disabled={loading} style={primaryButton(loading)}>
              {loading ? '비밀번호 변경 중...' : '비밀번호 변경'}
            </button>
          </form>
        )}

        {/* 4단계: 완료 */}
        {step === 4 && (
          <button type="button" onClick={() => navigate('/login', { replace: true })} style={primaryButton(false)}>
            로그인 화면으로 이동
          </button>
        )}

        <p style={{ textAlign: 'center', marginTop: '20px', color: 'var(--color-text-muted)' }}>
          <Link to="/login" style={{ color: 'var(--color-primary)', fontWeight: '600', textDecoration: 'none' }}>
            로그인으로 돌아가기
          </Link>
        </p>
      </div>
    </div>
  );
}
