import React, { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { authService } from '../services/api';
import { UserPlus, Mail, Lock, User, AlertCircle, BookOpen } from 'lucide-react';

export default function Register() {
  const navigate = useNavigate();
  const [formData, setFormData] = useState({
    email: '',
    password: '',
    passwordConfirm: '',
    displayName: '',
    major: ''
  });
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [loading, setLoading] = useState(false);

  const handleChange = (e) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
    setError('');
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    
    if (formData.password !== formData.passwordConfirm) {
      setError('비밀번호가 일치하지 않습니다.');
      return;
    }

    setLoading(true);
    try {
      await authService.register(formData);
      setSuccess('회원가입이 완료되었습니다! 2초 뒤 로그인 페이지로 이동합니다.');
      setTimeout(() => {
        navigate('/login');
      }, 2000);
    } catch (err) {
      setError(err.message || '회원가입 중 오류가 발생했습니다.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={styles.pageWrap}>
      <div className="glass-panel animate-fade-in" style={styles.card}>
        <div style={styles.header}>
          <div style={styles.iconBox}>
            <UserPlus size={28} color="white" />
          </div>
          <h2>계정 만들기</h2>
          <p style={styles.subtitle}>StudyBridge와 함께 학습을 시작하세요.</p>
        </div>

        {success ? (
          <div style={styles.successBox}>
            <div style={styles.successIcon}>✓</div>
            <p>{success}</p>
          </div>
        ) : (
          <form onSubmit={handleSubmit} style={styles.form}>
            <div style={styles.inputRow}>
              <div style={styles.inputGroup}>
                <label style={styles.label}>이메일</label>
                <div style={styles.inputIconWrap}>
                  <Mail size={18} style={styles.inputIcon} />
                  <input type="email" name="email" className="input-field" style={{ paddingLeft: '40px' }} placeholder="name@example.com" value={formData.email} onChange={handleChange} required />
                </div>
              </div>
              <div style={styles.inputGroup}>
                <label style={styles.label}>닉네임</label>
                <div style={styles.inputIconWrap}>
                  <User size={18} style={styles.inputIcon} />
                  <input type="text" name="displayName" className="input-field" style={{ paddingLeft: '40px' }} placeholder="홍길동" value={formData.displayName} onChange={handleChange} required minLength="2" maxLength="10" />
                </div>
              </div>
            </div>

            <div style={styles.inputRow}>
              <div style={styles.inputGroup}>
                <label style={styles.label}>비밀번호</label>
                <div style={styles.inputIconWrap}>
                  <Lock size={18} style={styles.inputIcon} />
                  <input type="password" name="password" className="input-field" style={{ paddingLeft: '40px' }} placeholder="8자 이상" value={formData.password} onChange={handleChange} required minLength="8" />
                </div>
              </div>
              <div style={styles.inputGroup}>
                <label style={styles.label}>비밀번호 확인</label>
                <div style={styles.inputIconWrap}>
                  <Lock size={18} style={styles.inputIcon} />
                  <input type="password" name="passwordConfirm" className="input-field" style={{ paddingLeft: '40px' }} placeholder="다시 입력" value={formData.passwordConfirm} onChange={handleChange} required />
                </div>
              </div>
            </div>

            <div style={styles.inputGroup}>
              <label style={styles.label}>전공 (선택)</label>
              <div style={styles.inputIconWrap}>
                <BookOpen size={18} style={styles.inputIcon} />
                <input type="text" name="major" className="input-field" style={{ paddingLeft: '40px' }} placeholder="컴퓨터공학과" value={formData.major} onChange={handleChange} />
              </div>
            </div>

            {error && (
              <div className="error-text">
                <AlertCircle size={16} />
                {error}
              </div>
            )}

            <button type="submit" className="btn-primary" style={{ marginTop: '12px' }} disabled={loading}>
              {loading ? '가입 중...' : '회원가입 완료'}
            </button>
          </form>
        )}

        <div style={styles.footer}>
          <span>이미 계정이 있으신가요?</span>
          <Link to="/login" style={{ fontWeight: '600' }}>로그인</Link>
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
    maxWidth: '560px',
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
  inputRow: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: '16px',
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
  successBox: {
    backgroundColor: 'rgba(46, 204, 113, 0.1)',
    border: '1px solid var(--color-success)',
    borderRadius: '12px',
    padding: '30px',
    textAlign: 'center',
    color: 'var(--color-text-main)',
  },
  successIcon: {
    width: '48px',
    height: '48px',
    backgroundColor: 'var(--color-success)',
    color: 'white',
    borderRadius: '50%',
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    fontSize: '24px',
    margin: '0 auto 16px auto',
  }
};
