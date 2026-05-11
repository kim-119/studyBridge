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

  const [agreements, setAgreements] = useState({
    privacy: false,
    terms: false,
    thirdParty: false
  });
  const [showPolicy, setShowPolicy] = useState(null);

  const allAgreed = agreements.privacy && agreements.terms && agreements.thirdParty;

  const handleCheckboxChange = (e) => {
    setAgreements({ ...agreements, [e.target.name]: e.target.checked });
  };

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

            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginTop: '10px', padding: '16px', backgroundColor: 'var(--color-bg-base)', borderRadius: '8px', border: '1px solid var(--color-border)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '0.9rem', color: 'var(--color-text-main)' }}>
                  <input type="checkbox" name="privacy" checked={agreements.privacy} onChange={handleCheckboxChange} style={{ cursor: 'pointer', width: '16px', height: '16px', accentColor: 'var(--color-primary)' }} />
                  [필수] 개인정보 처리방침 동의
                </label>
                <button type="button" onClick={() => setShowPolicy('privacy')} style={{ background: 'none', border: 'none', color: 'var(--color-text-muted)', textDecoration: 'underline', fontSize: '0.8rem', cursor: 'pointer' }}>내용 보기</button>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '0.9rem', color: 'var(--color-text-main)' }}>
                  <input type="checkbox" name="terms" checked={agreements.terms} onChange={handleCheckboxChange} style={{ cursor: 'pointer', width: '16px', height: '16px', accentColor: 'var(--color-primary)' }} />
                  [필수] 이용약관 동의
                </label>
                <button type="button" onClick={() => setShowPolicy('terms')} style={{ background: 'none', border: 'none', color: 'var(--color-text-muted)', textDecoration: 'underline', fontSize: '0.8rem', cursor: 'pointer' }}>내용 보기</button>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '0.9rem', color: 'var(--color-text-main)' }}>
                  <input type="checkbox" name="thirdParty" checked={agreements.thirdParty} onChange={handleCheckboxChange} style={{ cursor: 'pointer', width: '16px', height: '16px', accentColor: 'var(--color-primary)' }} />
                  [필수] AI 제3자 제공 및 위탁 동의
                </label>
                <button type="button" onClick={() => setShowPolicy('thirdParty')} style={{ background: 'none', border: 'none', color: 'var(--color-text-muted)', textDecoration: 'underline', fontSize: '0.8rem', cursor: 'pointer' }}>내용 보기</button>
              </div>
            </div>

            <button 
              type="submit" 
              className="btn-primary" 
              style={{ 
                marginTop: '12px', 
                opacity: (loading || !allAgreed) ? 0.6 : 1, 
                cursor: (loading || !allAgreed) ? 'not-allowed' : 'pointer',
                backgroundColor: (loading || !allAgreed) ? 'var(--color-text-muted)' : 'var(--color-primary)'
              }} 
              disabled={loading || !allAgreed}
            >
              {loading ? '가입 중...' : '회원가입 완료'}
            </button>
          </form>
        )}

        <div style={styles.footer}>
          <span>이미 계정이 있으신가요?</span>
          <Link to="/login" style={{ fontWeight: '600' }}>로그인</Link>
        </div>
      </div>

      {showPolicy && (
        <div style={{
          position: 'fixed', top: 0, left: 0, width: '100%', height: '100%', 
          backgroundColor: 'rgba(0,0,0,0.5)', display: 'flex', justifyContent: 'center', alignItems: 'center', zIndex: 1000
        }}>
          <div className="glass-panel" style={{ width: '90%', maxWidth: '500px', padding: '30px', maxHeight: '80vh', overflowY: 'auto' }}>
            <h3 style={{ marginTop: 0, color: 'var(--color-primary)', borderBottom: '1px solid var(--color-border)', paddingBottom: '12px', marginBottom: '16px' }}>
              {showPolicy === 'privacy' && '개인정보 처리방침'}
              {showPolicy === 'terms' && '이용약관'}
              {showPolicy === 'thirdParty' && '제3자 제공 및 처리 위탁 동의'}
            </h3>
            <div style={{ fontSize: '0.95rem', color: 'var(--color-text-main)', lineHeight: '1.6', whiteSpace: 'pre-wrap' }}>
              {showPolicy === 'privacy' && `StudyBridge는 회원가입 및 서비스 제공을 위해 아래 개인정보를 수집·이용합니다.\n\n[수집 항목]\n이메일, 닉네임, 비밀번호, 전공, 학습 기록, Todo 정보, 스터디 참여 정보, AI 채팅 이용 기록\n\n[수집 목적]\n회원 식별, 로그인 및 계정 관리, 학습 시간 기록, Todo 관리, 스터디 및 AI 학습 보조 기능 제공, 서비스 오류 확인 및 개선\n\n[보관 기간]\n회원 탈퇴 시까지 보관하며, 탈퇴 요청 시 지체 없이 삭제합니다. 단, 서비스 운영상 필요한 최소한의 기록은 관련 법령 또는 내부 정책에 따라 일정 기간 보관될 수 있습니다.\n\n[삭제 정책]\n회원 탈퇴 시 계정 정보와 개인 학습 데이터는 삭제되며, 복구가 불가능합니다. 단, 익명화된 통계 데이터는 서비스 개선 목적으로 활용될 수 있습니다.`}
              {showPolicy === 'terms' && `StudyBridge는 사용자의 학습 관리와 그룹 스터디, AI 기반 학습 보조 기능을 제공하는 서비스입니다.\n\n[서비스 목적]\n개인 학습 시간 관리, Todo 관리, 그룹 스터디 참여, 멀티 에이전트 기반 학습 지원을 제공합니다.\n\n[회원 의무]\n회원은 정확한 정보를 입력해야 하며, 본인의 계정을 안전하게 관리해야 합니다. 타인의 계정을 무단으로 사용하거나 허위 정보를 입력해서는 안 됩니다.\n\n[금지 행위]\n- 타인의 개인정보 도용\n- 욕설, 비방, 차별, 혐오 표현 작성\n- 서비스 장애를 유발하는 행위\n- AI 기능 악용\n- 데이터 무단 수집 및 유출\n\n[서비스 이용 제한]\n약관 위반 시 서비스 이용 제한 또는 계정 정지가 가능합니다.`}
              {showPolicy === 'thirdParty' && `StudyBridge는 AI 학습 보조 기능 제공을 위해 사용자의 일부 입력 데이터를 외부 AI 서비스에 전달할 수 있습니다.\n\n[전달되는 정보]\n사용자가 AI 채팅 기능에 입력한 메시지, 생성한 에이전트의 이름·역할·성격 설명, 학습 질문 내용\n\n[전달 목적]\nAI 답변 생성, 학습 보조 응답 제공, 멀티 에이전트 대화 기능 제공\n\n[주의 사항]\n주민등록번호, 전화번호, 주소, 비밀번호 등 민감정보 입력 금지`}
            </div>
            <div style={{ marginTop: '24px', textAlign: 'right' }}>
              <button className="btn-primary" style={{ width: 'auto', padding: '10px 24px' }} onClick={() => setShowPolicy(null)}>확인</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

const styles = {
  pageWrap: {
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    minHeight: 'calc(100vh - 120px)',
    padding: '24px',
    boxSizing: 'border-box'
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
