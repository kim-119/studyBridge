import React, { useState, useEffect, useRef } from 'react';
import { useAuth } from '../hooks/useAuth';
import { authService } from '../services/api';
import { ShieldAlert, MessageCircle, X, CheckCircle, AlertTriangle, Ban, User, Lock, Mail, BookOpen, Key, Camera } from 'lucide-react';

export default function MyPage() {
  const { userId, userEmail, user, updateUser } = useAuth();
  
  const [name, setName] = useState('');
  const [major, setMajor] = useState('');
  const [email, setEmail] = useState('');
  const [isEditing, setIsEditing] = useState(false);
  const [activeSettingsTab, setActiveSettingsTab] = useState('profile');
  const [profileImage, setProfileImage] = useState(null);
  const fileInputRef = useRef(null);

  const handleImageUpload = (e) => {
    const file = e.target.files[0];
    if (file) {
      const imageUrl = URL.createObjectURL(file);
      setProfileImage(imageUrl);
    }
  };

  useEffect(() => {
    if (!userId) return;
    const fetchProfile = async () => {
      try {
        const res = await authService.getProfile(userId);
        setName(res.displayName || res.display_name || res.name || '');
        setMajor(res.major || '');
        setEmail(res.email || userEmail || '');
      } catch (err) {
        console.warn('서버에서 프로필을 불러오지 못했습니다. 로컬 데이터를 사용합니다.');
        setName(user?.displayName || '');
        setMajor(user?.major || '');
        setEmail(user?.email || userEmail || '');
      }
    };
    fetchProfile();
  }, [userId, userEmail]);

  // 나의 1:1 문의 상태
  const [myInquiries, setMyInquiries] = useState([
    { id: 1, type: '버그 및 오류신고', title: '강의계획서 업로드 오류', content: 'PDF 파일을 올리는데 계속 실패합니다. 확인 부탁드려요.', date: '2026-05-20', status: '대기중', reply: '' },
    { id: 2, type: '이용문의', title: '비밀번호 초기화 메일 안옴', content: '비밀번호 재설정 메일이 오지 않습니다.', date: '2026-05-21', status: '답변완료', reply: '스팸 메일함을 확인해주세요. 그래도 없으면 고객센터로 전화주세요.' },
  ]);
  const [showInquiryModal, setShowInquiryModal] = useState(false);
  const [newInquiryType, setNewInquiryType] = useState('이용문의');
  const [newInquiryTitle, setNewInquiryTitle] = useState('');
  const [newInquiryContent, setNewInquiryContent] = useState('');

  const handleSubmitInquiry = () => {
    if (!newInquiryTitle.trim() || !newInquiryContent.trim()) {
      alert('제목과 내용을 모두 입력해주세요.');
      return;
    }
    const newInq = {
      id: Date.now(),
      type: newInquiryType,
      title: newInquiryTitle,
      content: newInquiryContent,
      date: new Date().toISOString().split('T')[0],
      status: '대기중',
      reply: ''
    };
    setMyInquiries([newInq, ...myInquiries]);
    setShowInquiryModal(false);
    setNewInquiryTitle('');
    setNewInquiryContent('');
    setNewInquiryType('이용문의');
    alert('문의가 성공적으로 접수되었습니다.');
  };

  // 비밀번호 변경 관련 상태
  const [verifyEmail, setVerifyEmail] = useState('');
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [passwordError, setPasswordError] = useState('');
  const [passwordSuccess, setPasswordSuccess] = useState('');
  const [isVerified, setIsVerified] = useState(false);

  const handleSave = async () => {
    const finalName = name.trim() || email.split('@')[0] || '';
    const finalMajor = major.trim() || '전공 미설정';

    try {
      if (userId) {
        await authService.updateProfile(userId, { displayName: finalName, major: finalMajor });
        
        let refreshed = { displayName: finalName, major: finalMajor, email: email };
        try {
          refreshed = await authService.getProfile(userId);
        } catch (e) {
          console.warn('저장 후 프로필 재조회 실패:', e);
        }

        updateUser(refreshed);

        setName(refreshed.displayName || refreshed.display_name || refreshed.name || finalName);
        setMajor(refreshed.major || finalMajor);
        setEmail(refreshed.email || email);
      }
      
      setIsEditing(false);
      alert('프로필이 성공적으로 업데이트되었습니다.');
    } catch (error) {
      alert(error.message || '프로필 업데이트에 실패했습니다.');
    }
  };

  const handleCancel = () => {
    setName(user?.displayName || '');
    setMajor(user?.major || '');
    setIsEditing(false);
  };

  const handleVerifyPassword = async () => {
    setPasswordError('');
    setPasswordSuccess('');

    if (!verifyEmail || !currentPassword) {
      setPasswordError('이메일과 현재 비밀번호를 입력해주세요.');
      return;
    }

    try {
      const res = await authService.verifyPassword({ 
        email: verifyEmail, 
        password: currentPassword 
      });
      
      if (res.verified) {
        setIsVerified(true);
        setPasswordSuccess('본인 확인이 완료되었습니다. 새 비밀번호를 입력해주세요.');
      }
    } catch (error) {
      setPasswordError('이메일 또는 현재 비밀번호가 일치하지 않습니다.');
    }
  };

  const handleCancelPasswordChange = () => {
    setIsVerified(false);
    setVerifyEmail('');
    setCurrentPassword('');
    setNewPassword('');
    setConfirmPassword('');
    setPasswordError('');
    setPasswordSuccess('');
  };

  const handleFinalPasswordChange = async () => {
    setPasswordError('');
    setPasswordSuccess('');

    if (!newPassword || !confirmPassword) {
      setPasswordError('새 비밀번호를 입력해주세요.');
      return;
    }

    if (newPassword !== confirmPassword) {
      setPasswordError('새 비밀번호가 일치하지 않습니다.');
      return;
    }

    try {
      await authService.updatePassword({ 
        email: verifyEmail,
        currentPassword: currentPassword, 
        newPassword: newPassword,
        newPasswordConfirm: confirmPassword
      });
      alert('비밀번호가 성공적으로 변경되었습니다.');
      handleCancelPasswordChange();
    } catch (error) {
      setPasswordError(error.message || '비밀번호 변경에 실패했습니다.');
    }
  };

  return (
    <div className="mypage-page" style={{ padding: '40px 5%', width: '100%', maxWidth: '100%', boxSizing: 'border-box', margin: '0 auto' }}>
      <div className="glass-panel animate-fade-in" style={{ padding: '0', boxSizing: 'border-box', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
        <div style={{ display: 'flex', borderBottom: '1px solid #E5E7EB', backgroundColor: '#F9FAFB' }}>
          <button 
            style={{ flex: 1, padding: '20px', fontWeight: 'bold', fontSize: '16px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', cursor: 'pointer', backgroundColor: activeSettingsTab === 'profile' ? 'white' : 'transparent', color: activeSettingsTab === 'profile' ? '#10B981' : '#6B7280', border: 'none', borderBottom: activeSettingsTab === 'profile' ? '3px solid #10B981' : '3px solid transparent', outline: 'none', transition: 'all 0.2s' }}
            onClick={() => setActiveSettingsTab('profile')}
          >
            <User size={20} /> 기본 프로필 설정
          </button>
          <button 
            style={{ flex: 1, padding: '20px', fontWeight: 'bold', fontSize: '16px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', cursor: 'pointer', backgroundColor: activeSettingsTab === 'password' ? 'white' : 'transparent', color: activeSettingsTab === 'password' ? '#10B981' : '#6B7280', border: 'none', borderBottom: activeSettingsTab === 'password' ? '3px solid #10B981' : '3px solid transparent', outline: 'none', transition: 'all 0.2s' }}
            onClick={() => setActiveSettingsTab('password')}
          >
            <Key size={20} /> 비밀번호 및 보안
          </button>
        </div>

        {activeSettingsTab === 'profile' && (
          <div className="animate-fade-in">
          <div style={{ background: 'linear-gradient(135deg, #ECFDF5 0%, #D1FAE5 100%)', padding: '40px 20px', textAlign: 'center', borderBottom: '1px solid #E5E7EB' }}>
            <div 
              className="profile-avatar" 
              style={{ 
                margin: '0 auto 16px auto', width: '100px', height: '100px', fontSize: '36px', 
                boxShadow: '0 4px 6px rgba(16, 185, 129, 0.2)', position: 'relative', cursor: isEditing ? 'pointer' : 'default',
                backgroundImage: profileImage ? `url(${profileImage})` : 'none',
                backgroundSize: 'cover', backgroundPosition: 'center',
                color: profileImage ? 'transparent' : 'inherit'
              }}
              onClick={() => isEditing && fileInputRef.current && fileInputRef.current.click()}
            >
              {!profileImage && (name ? name.charAt(0).toUpperCase() : '?')}
              
              {isEditing && (
                <div style={{ position: 'absolute', bottom: 0, right: 0, backgroundColor: 'white', borderRadius: '50%', padding: '6px', boxShadow: '0 2px 4px rgba(0,0,0,0.1)', color: '#10B981', display: 'flex' }}>
                  <Camera size={16} />
                </div>
              )}
            </div>
            <input type="file" ref={fileInputRef} style={{ display: 'none' }} accept="image/*" onChange={handleImageUpload} />
            <h3 style={{ margin: 0, fontSize: '22px', color: '#065F46' }}>{name || '이름 없음'}</h3>
            <p style={{ margin: '8px 0 0', color: '#047857', fontWeight: '500' }}>
              {major || '전공 미설정'}
            </p>
          </div>

          <div style={{ padding: '30px', flex: 1, display: 'flex', flexDirection: 'column' }}>
            <div className="form-grid" style={{ marginBottom: 'auto' }}>
              <div className="form-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><User size={16} /> 이름</label>
                <input
                  className="input-field"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  disabled={!isEditing}
                  placeholder="이름을 입력하세요"
                />
              </div>

              <div className="form-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><BookOpen size={16} /> 전공</label>
                <input
                  className="input-field"
                  value={major}
                  onChange={(e) => setMajor(e.target.value)}
                  disabled={!isEditing}
                  placeholder="전공을 입력하세요"
                />
              </div>

              <div className="form-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><Mail size={16} /> 이메일</label>
                <input className="input-field" value={email} disabled />
              </div>
            </div>

            <div className="btn-group" style={{ marginTop: '30px' }}>
              {isEditing ? (
                <>
                  <button className="btn-primary" onClick={handleSave} style={{ flex: 1 }}>
                    저장
                  </button>
                  <button className="btn-outline" onClick={handleCancel} style={{ flex: 1 }}>
                    취소
                  </button>
                </>
              ) : (
                <button className="btn-primary" onClick={() => setIsEditing(true)} style={{ width: '100%' }}>
                  프로필 수정
                </button>
              )}
            </div>
            </div>
          </div>
        )}

        {activeSettingsTab === 'password' && (
          <div className="animate-fade-in" style={{ padding: '40px', boxSizing: 'border-box' }}>
            <h3 style={{ margin: '0 0 30px 0', color: '#065F46', display: 'flex', alignItems: 'center', gap: '10px', fontSize: '22px' }}>
              <Key size={24} /> 계정 보안 및 비밀번호 변경
            </h3>
        
        {!isVerified ? (
          <div style={{ display: 'grid', gap: '24px' }}>
            <div style={{ padding: '32px', backgroundColor: '#F9FAFB', borderRadius: '16px', border: '1px solid #E5E7EB' }}>
              <p style={{ margin: '0 0 20px 0', fontSize: '14px', color: '#4B5563', lineHeight: '1.5' }}>
                안전한 비밀번호 변경을 위해 현재 이메일과 비밀번호로 본인 인증을 먼저 진행해 주세요.
              </p>
              <div style={{ marginBottom: '16px' }}>
                <label style={{ display: 'block', marginBottom: '8px', fontWeight: 'bold', fontSize: '14px' }}>가입 이메일</label>
                <input
                  type="email"
                  className="input-field"
                  value={verifyEmail}
                  onChange={(e) => setVerifyEmail(e.target.value)}
                  placeholder="user@example.com"
                />
              </div>
              <div>
                <label style={{ display: 'block', marginBottom: '8px', fontWeight: 'bold', fontSize: '14px' }}>현재 비밀번호</label>
                <input
                  type="password"
                  className="input-field"
                  value={currentPassword}
                  onChange={(e) => setCurrentPassword(e.target.value)}
                  placeholder="현재 비밀번호를 입력하세요"
                />
              </div>
              {passwordError && <div style={{ color: '#DC2626', marginTop: '12px', fontSize: '14px', fontWeight: 'bold' }}>{passwordError}</div>}
              <button className="btn-primary" onClick={handleVerifyPassword} style={{ width: '100%', marginTop: '24px', padding: '12px' }}>
                본인 인증하기
              </button>
            </div>
          </div>
        ) : (
          <div className="animate-fade-in">
            <div style={{ padding: '20px', backgroundColor: '#ECFDF5', borderRadius: '16px', border: '1px solid #D1FAE5', marginBottom: '30px', color: '#065F46', display: 'flex', alignItems: 'center', gap: '10px' }}>
              <CheckCircle size={20} />
              <div><strong>본인 인증이 완료되었습니다.</strong><br/>새로운 비밀번호를 설정해 주세요.</div>
            </div>
            
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px', marginBottom: '30px' }}>
              <div className="form-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 'bold' }}><Lock size={16} /> 새 비밀번호</label>
                <input
                  type="password"
                  className="input-field"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  placeholder="새로운 비밀번호 입력"
                />
              </div>
              <div className="form-group">
                <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontWeight: 'bold' }}><CheckCircle size={16} /> 새 비밀번호 확인</label>
                <input
                  type="password"
                  className="input-field"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  placeholder="새로운 비밀번호 다시 입력"
                />
              </div>
            </div>
            
            {passwordError && <div style={{ color: '#DC2626', marginBottom: '20px', fontSize: '14px', fontWeight: 'bold' }}>{passwordError}</div>}
            
            <div style={{ display: 'flex', gap: '16px', maxWidth: '300px' }}>
              <button className="btn-outline" onClick={handleCancelPasswordChange} style={{ flex: 1, padding: '12px', borderRadius: '12px' }}>
                취소
              </button>
              <button className="btn-primary" onClick={handleFinalPasswordChange} style={{ flex: 2, padding: '12px', borderRadius: '12px' }}>
                비밀번호 변경 완료
              </button>
            </div>
          </div>
        )}
          </div>
        )}
      </div>

      {/* 나의 1:1 문의 메뉴 */}
      <div className="glass-panel animate-fade-in" style={{ padding: '30px', marginTop: '24px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
          <h3 style={{ margin: 0, color: 'var(--color-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <MessageCircle size={20} /> 나의 1:1 문의 내역
          </h3>
          <button className="btn-primary" style={{ width: 'auto', padding: '8px 16px', borderRadius: '8px', fontSize: '14px' }} onClick={() => setShowInquiryModal(true)}>
            새 문의하기
          </button>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {myInquiries.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '40px', color: 'var(--color-text-muted)' }}>등록된 문의 내역이 없습니다.</div>
          ) : myInquiries.map(inq => (
            <div key={inq.id} style={{ padding: '24px', borderRadius: '16px', border: '1px solid #E5E7EB', backgroundColor: 'white', boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.05)', transition: 'transform 0.2s ease, box-shadow 0.2s ease', cursor: 'pointer' }} onMouseEnter={(e) => { e.currentTarget.style.transform = 'translateY(-4px)'; e.currentTarget.style.boxShadow = '0 10px 15px -3px rgba(0, 0, 0, 0.1)'; }} onMouseLeave={(e) => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = '0 4px 6px -1px rgba(0, 0, 0, 0.05)'; }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '12px' }}>
                <div>
                  <span style={{ display: 'inline-block', padding: '4px 8px', borderRadius: '6px', fontSize: '12px', fontWeight: 'bold', backgroundColor: '#F3F4F6', color: '#4B5563', marginBottom: '8px' }}>
                    {inq.type}
                  </span>
                  <div style={{ fontWeight: 'bold', fontSize: '16px', color: '#111827' }}>{inq.title}</div>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: '8px' }}>
                  <span style={{ 
                    padding: '4px 10px', borderRadius: '20px', fontSize: '12px', fontWeight: 'bold',
                    backgroundColor: inq.status === '대기중' ? '#FEF08A' : '#BBF7D0',
                    color: inq.status === '대기중' ? '#854D0E' : '#166534'
                  }}>
                    {inq.status}
                  </span>
                  <span style={{ fontSize: '13px', color: 'var(--color-text-muted)' }}>{inq.date}</span>
                </div>
              </div>
              <p style={{ margin: '0 0 16px 0', fontSize: '14px', color: 'var(--color-text-main)', lineHeight: '1.5' }}>{inq.content}</p>
              
              {inq.reply && (
                <div style={{ padding: '16px', backgroundColor: '#F9FAFB', borderRadius: '8px', borderLeft: '4px solid var(--color-primary)', marginTop: '12px', fontSize: '14px' }}>
                  <div style={{ fontWeight: 'bold', marginBottom: '8px', color: 'var(--color-primary)', display: 'flex', alignItems: 'center', gap: '6px' }}>
                    <MessageCircle size={16} /> 관리자 답변
                  </div>
                  <div style={{ color: '#374151', lineHeight: '1.5' }}>{inq.reply}</div>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* 새 문의 작성 모달 */}
      {showInquiryModal && (
        <div className="modal-overlay" style={{ zIndex: 1000, backdropFilter: 'blur(4px)' }}>
          <div className="glass-panel modal-content animate-fade-in" style={{ width: '500px', padding: '32px', borderRadius: '24px', boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.1)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
              <h3 style={{ margin: 0, fontSize: '20px', fontWeight: 'bold', color: '#111827' }}>1:1 문의하기</h3>
              <button className="btn-close" onClick={() => setShowInquiryModal(false)}><X size={24} /></button>
            </div>
            
            <div className="form-group" style={{ marginBottom: '16px' }}>
              <label style={{ display: 'block', marginBottom: '8px', fontWeight: 'bold', fontSize: '14px' }}>문의 유형</label>
              <select 
                className="input-field"
                value={newInquiryType}
                onChange={(e) => setNewInquiryType(e.target.value)}
                style={{ cursor: 'pointer' }}
              >
                <option value="이용문의">이용문의</option>
                <option value="버그 및 오류신고">버그 및 오류신고</option>
                <option value="기타">기타</option>
              </select>
            </div>

            <div className="form-group" style={{ marginBottom: '16px' }}>
              <label style={{ display: 'block', marginBottom: '8px', fontWeight: 'bold', fontSize: '14px' }}>제목</label>
              <input 
                type="text"
                className="input-field"
                placeholder="문의 제목을 입력해주세요"
                value={newInquiryTitle}
                onChange={(e) => setNewInquiryTitle(e.target.value)}
              />
            </div>

            <div className="form-group" style={{ marginBottom: '24px' }}>
              <label style={{ display: 'block', marginBottom: '8px', fontWeight: 'bold', fontSize: '14px' }}>내용</label>
              <textarea 
                className="input-field" 
                placeholder="문의하실 내용을 상세히 적어주세요."
                value={newInquiryContent}
                onChange={(e) => setNewInquiryContent(e.target.value)}
                style={{ minHeight: '150px', resize: 'vertical', padding: '16px' }}
              />
            </div>

            <div style={{ display: 'flex', gap: '12px' }}>
              <button className="btn-outline" style={{ flex: 1, padding: '12px', borderRadius: '8px', fontWeight: 'bold' }} onClick={() => setShowInquiryModal(false)}>취소</button>
              <button className="btn-primary" style={{ flex: 2, padding: '12px', borderRadius: '8px', fontWeight: 'bold' }} onClick={handleSubmitInquiry}>문의 접수</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}