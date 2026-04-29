import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { authService } from '../services/api';
import { LogIn, Mail, Lock, AlertCircle } from 'lucide-react';

export default function Login() {
  const navigate = useNavigate();

  const [formData, setFormData] = useState({
    email: '',
    password: '',
  });

  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  // 입력값 변경 처리
  const handleChange = (e) => {
    const { name, value } = e.target;

    setFormData((prev) => ({
      ...prev,
      [name]: value,
    }));

    if (error) setError('');
  };

  // 로그인 처리
  const handleSubmit = async (e) => {
    e.preventDefault();

    if (!formData.email || !formData.password) {
      setError('이메일과 비밀번호를 입력해주세요.');
      return;
    }

    setLoading(true);

    try {
      await authService.login(formData);

      // 백엔드 인증 API 완성 전까지 임시 로그인 상태 저장
      localStorage.setItem('userEmail', formData.email);

      navigate('/');
    } catch (err) {
      setError(err.message || '로그인 실패');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={styles.pageWrap}>
      <div className="glass-panel" style={styles.card}>
        <div style={styles.header}>
          <div style={styles.iconBox}>
            <LogIn size={28} color="white" />
          </div>
          <h2>Welcome back</h2>
          <p style={styles.subtitle}>StudyBridge에 다시 오신 것을 환영합니다.</p>
        </div>

        <form onSubmit={handleSubmit} style={styles.form}>
          <div style={styles.inputGroup}>
            <label style={styles.label}>이메일</label>
            <div style={styles.inputIconWrap}>
              <Mail size={18} style={styles.inputIcon} />
              <input
                type="email"
                name="email"
                className="input-field"
                style={{ paddingLeft: '40px' }}
                placeholder="name@example.com"
                value={formData.email}
                onChange={handleChange}
              />
            </div>
          </div>

          <div style={styles.inputGroup}>
            <label style={styles.label}>비밀번호</label>
            <div style={styles.inputIconWrap}>
              <Lock size={18} style={styles.inputIcon} />
              <input
                type="password"
                name="password"
                className="input-field"
                style={{ paddingLeft: '40px' }}
                placeholder="••••••••"
                value={formData.password}
                onChange={handleChange}
              />
            </div>
          </div>

          {error && (
            <div className="error-text">
              <AlertCircle size={16} />
              {error}
            </div>
          )}

          <button
            type="submit"
            className="btn-primary"
            style={{ marginTop: '12px' }}
            disabled={loading}
          >
            {loading ? '로그인 중...' : '로그인'}
          </button>
        </form>

        <div style={styles.footer}>
          <span>계정이 없으신가요?</span>
          <Link to="/register" style={{ fontWeight: '600' }}>
            회원가입
          </Link>
        </div>
      </div>
    </div>
  );
}

const styles = {
  pageWrap: {
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    minHeight: 'calc(100vh - 120px)',
  },
  card: {
    width: '100%',
    maxWidth: '420px',
    padding: '40px',
    boxSizing: 'border-box',
  },
  header: {
    textAlign: 'center',
    marginBottom: '32px',
  },
  iconBox: {
    width: '56px',
    height: '56px',
    backgroundColor: 'var(--color-primary)',
    borderRadius: '16px',
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    margin: '0 auto 16px auto',
    boxShadow: '0 8px 16px rgba(99, 136, 97, 0.25)',
  },
  subtitle: {
    color: 'var(--color-text-muted)',
    fontSize: '0.95rem',
    marginTop: '4px',
  },
  form: {
    display: 'flex',
    flexDirection: 'column',
    gap: '20px',
  },
  inputGroup: {
    display: 'flex',
    flexDirection: 'column',
    gap: '6px',
  },
  label: {
    fontSize: '0.9rem',
    fontWeight: '500',
    color: 'var(--color-text-main)',
  },
  inputIconWrap: {
    position: 'relative',
    display: 'flex',
    alignItems: 'center',
  },
  inputIcon: {
    position: 'absolute',
    left: '14px',
    color: 'var(--color-text-muted)',
    opacity: 0.7,
  },
  footer: {
    marginTop: '32px',
    textAlign: 'center',
    fontSize: '0.9rem',
    color: 'var(--color-text-muted)',
    display: 'flex',
    justifyContent: 'center',
    gap: '8px',
  },
};