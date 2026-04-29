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

      login(String(userId), userEmail);

      navigate('/dashboard');
    } catch (err) {
      console.error('로그인 실패:', err);
      setError(err.message || '로그인에 실패했습니다.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div
        className="glass-panel animate-fade-in"
        style={{
          width: '100%',
          maxWidth: '420px',
          padding: '36px',
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
                  width: '100%',
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
                  width: '100%',
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
            to="/signup"
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
    </div>
  );
}