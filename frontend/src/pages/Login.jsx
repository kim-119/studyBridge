import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { authService } from '../services/api';
import { LogIn, Mail, Lock, AlertCircle } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';

export default function Login() {
  const navigate = useNavigate();
  const { login } = useAuth();

  const [formData, setFormData] = useState({
    email: '',
    password: '',
  });

  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [suspensionDetails, setSuspensionDetails] = useState(null);

  const handleChange = (e) => {
    const { name, value } = e.target;

    setFormData((prev) => ({
      ...prev,
      [name]: value,
    }));

    if (error) setError('');
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (!formData.email || !formData.password) {
      setError('이메일과 비밀번호를 입력해주세요.');
      return;
    }

    setLoading(true);
    setError('');

    try {
      const result = await authService.login({
        email: formData.email,
        password: formData.password,
      });

      console.log('로그인 응답:', result);

      const userId = result.id || result.userId || result.user?.id;
      const userEmail = result.email || result.user?.email || formData.email;

      if (!userId) {
        console.error('로그인 응답에 userId가 없습니다:', result);
        setError('로그인 응답에 사용자 ID가 없습니다.');
        return;
      }

      // JWT 토큰을 로컬스토리지에 선제적으로 저장 (프로필 및 기타 API 요청 시 헤더에 자동 포함)
      if (result.accessToken) {
        localStorage.setItem('token', result.accessToken);
      }
      if (result.refreshToken) {
        localStorage.setItem('refreshToken', result.refreshToken);
      }

      let profile = {};
      try {
        profile = await authService.getProfile(userId);
      } catch (e) {
        console.warn('프로필 조회 실패, 로그인 응답 값 사용:', e);
      }

      const normalizedUser = {
        ...result,
        ...profile,
        id: profile.userId || profile.id || userId,
        userId: profile.userId || profile.id || userId,
        displayName: profile.displayName || profile.display_name || profile.name || profile.nickname || result.displayName || '',
        email: profile.email || userEmail,
        major: profile.major || result.major || ''
      };

      login(normalizedUser);

      navigate('/dashboard');
    } catch (err) {
      console.error('로그인 실패:', err);
      const errMsg = err.message || (typeof err === 'string' ? err : '');
      const errStatus = err.status || 401;

      if (errStatus === 403 || errMsg.includes('정지된 계정') || errMsg.includes('제재') || errMsg.includes('일시정지') || errMsg.includes('일시 정지') || errMsg.includes('영구정지') || errMsg.includes('영구 정지')) {
        let isPermanent = errMsg.includes('영구정지') || errMsg.includes('영구 정지');
        let reason = '운영 정책 위반';
        let endDate = '';

        // Parse reason and date
        const reasonMatch = errMsg.match(/사유:\s*([^,\)\(]+)/) || errMsg.match(/사유:\s*([^\s]+)/);
        if (reasonMatch) {
          reason = reasonMatch[1].trim();
        }
        const dateMatch = errMsg.match(/정지 만료일:\s*([^,\)\(]+)/) || errMsg.match(/만료일:\s*([^,\)\(]+)/);
        if (dateMatch) {
          endDate = dateMatch[1].trim();
        }

        setSuspensionDetails({
          isSuspended: true,
          type: isPermanent ? '영구정지' : '일시정지',
          reason,
          endDate: isPermanent ? '영구 정지' : endDate,
          originalMessage: errMsg
        });
      } else {
        setError(errMsg || '로그인에 실패했습니다.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      display: 'flex',
      justifyContent: 'center',
      alignItems: 'center',
      minHeight: 'calc(100vh - 120px)',
      padding: '24px'
    }}>
      <div
        className="glass-panel animate-fade-in"
        style={{
          width: '100%',
          maxWidth: '420px',
          padding: '36px',
          boxSizing: 'border-box'
        }}
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
            <LogIn size={32} />
          </div>

          <h1
            style={{
              fontSize: '28px',
              fontWeight: '700',
              color: 'var(--color-text)',
              margin: 0,
            }}
          >
            로그인
          </h1>

          <p
            style={{
              color: 'var(--color-text-muted)',
              marginTop: '8px',
            }}
          >
            계정에 로그인하여 서비스를 이용하세요.
          </p>
        </div>

        {error && (
          <div
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

        <form onSubmit={handleSubmit}>
          <div style={{ marginBottom: '16px' }}>
            <label
              style={{
                display: 'block',
                marginBottom: '8px',
                color: 'var(--color-text)',
                fontWeight: '600',
              }}
            >
              이메일
            </label>

            <div style={{ position: 'relative' }}>
              <Mail
                size={20}
                style={{
                  position: 'absolute',
                  left: '14px',
                  top: '50%',
                  transform: 'translateY(-50%)',
                  color: 'var(--color-text-muted)',
                }}
              />

              <input
                type="email"
                name="email"
                value={formData.email}
                onChange={handleChange}
                placeholder="이메일을 입력하세요"
                style={{
                  width: '80%',
                  padding: '13px 14px 13px 44px',
                  borderRadius: '10px',
                  border: '1px solid var(--color-border)',
                  outline: 'none',
                }}
              />
            </div>
          </div>

          <div style={{ marginBottom: '22px' }}>
            <label
              style={{
                display: 'block',
                marginBottom: '8px',
                color: 'var(--color-text)',
                fontWeight: '600',
              }}
            >
              비밀번호
            </label>

            <div style={{ position: 'relative' }}>
              <Lock
                size={20}
                style={{
                  position: 'absolute',
                  left: '14px',
                  top: '50%',
                  transform: 'translateY(-50%)',
                  color: 'var(--color-text-muted)',
                }}
              />

              <input
                type="password"
                name="password"
                value={formData.password}
                onChange={handleChange}
                placeholder="비밀번호를 입력하세요"
                style={{
                  width: '80%',
                  padding: '13px 14px 13px 44px',
                  borderRadius: '10px',
                  border: '1px solid var(--color-border)',
                  outline: 'none',
                }}
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={loading}
            style={{
              width: '100%',
              padding: '14px',
              borderRadius: '10px',
              border: 'none',
              background: 'var(--color-primary)',
              color: '#fff',
              fontWeight: '700',
              cursor: loading ? 'not-allowed' : 'pointer',
              opacity: loading ? 0.7 : 1,
            }}
          >
            {loading ? '로그인 중...' : '로그인'}
          </button>
        </form>

        <p
          style={{
            textAlign: 'center',
            marginTop: '20px',
            color: 'var(--color-text-muted)',
          }}
        >
          계정이 없으신가요?{' '}
          <Link
            to="/register"
            style={{
              color: 'var(--color-primary)',
              fontWeight: '600',
              textDecoration: 'none',
            }}
          >
            회원가입
          </Link>
        </p>
      </div>
      {/* 제재 안내 모달 */}
      {suspensionDetails && (
        <div style={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          backgroundColor: 'rgba(0,0,0,0.5)',
          backdropFilter: 'blur(4px)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          zIndex: 100000,
          fontFamily: '"Malgun Gothic", sans-serif'
        }}>
          <div className="glass-panel animate-fade-in" style={{
            width: '100%',
            maxWidth: '480px',
            padding: '36px',
            backgroundColor: '#ffffff',
            borderRadius: '16px',
            boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1), 0 10px 10px -5px rgba(0,0,0,0.04)',
            textAlign: 'center'
          }}>
            <div style={{
              width: '72px',
              height: '72px',
              borderRadius: '50%',
              backgroundColor: '#fee2e2',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              margin: '0 auto 20px',
              color: '#ef4444'
            }}>
              <AlertCircle size={36} />
            </div>

            <h2 style={{ fontSize: '22px', fontWeight: '700', color: '#111827', margin: '0 0 12px 0' }}>
              서비스 이용이 제한된 계정입니다
            </h2>
            
            <p style={{ fontSize: '14px', color: '#4b5563', lineHeight: '1.6', margin: '0 0 24px 0' }}>
              고객님의 계정은 운영정책 위반으로 인해 서비스 이용이 정지되었습니다. 정지 기간 동안은 로그인을 포함한 모든 기능 사용이 제한됩니다.
            </p>

            <div style={{
              backgroundColor: '#f9fafb',
              borderRadius: '12px',
              padding: '20px',
              textAlign: 'left',
              border: '1px solid #e5e7eb',
              marginBottom: '24px'
            }}>
              <div style={{ display: 'flex', marginBottom: '10px' }}>
                <div style={{ width: '90px', fontWeight: '700', color: '#374151', fontSize: '13px' }}>제재 구분</div>
                <div style={{ flex: 1, color: '#ef4444', fontWeight: '700', fontSize: '13px' }}>
                  {suspensionDetails.type === '영구정지' ? '영구 활동 정지' : '일시 활동 정지'}
                </div>
              </div>
              <div style={{ display: 'flex', marginBottom: '10px' }}>
                <div style={{ width: '90px', fontWeight: '700', color: '#374151', fontSize: '13px' }}>제재 사유</div>
                <div style={{ flex: 1, color: '#1f2937', fontSize: '13px' }}>{suspensionDetails.reason}</div>
              </div>
              <div style={{ display: 'flex' }}>
                <div style={{ width: '90px', fontWeight: '700', color: '#374151', fontSize: '13px' }}>정지 만료일</div>
                <div style={{ flex: 1, color: '#1f2937', fontSize: '13px' }}>
                  {suspensionDetails.endDate === '영구 정지' ? '영구 정지 (해제 불가)' : suspensionDetails.endDate}
                </div>
              </div>
            </div>

            <button
              onClick={() => setSuspensionDetails(null)}
              style={{
                width: '100%',
                padding: '12px',
                borderRadius: '8px',
                border: 'none',
                backgroundColor: 'var(--color-primary)',
                color: '#fff',
                fontWeight: '700',
                cursor: 'pointer',
                fontSize: '15px'
              }}
            >
              확인
            </button>
          </div>
        </div>
      )}
    </div>
  );
}