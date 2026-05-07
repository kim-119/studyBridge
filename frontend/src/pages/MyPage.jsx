import React, { useState, useEffect } from 'react';
import { useAuth } from '../hooks/useAuth';
import { authService } from '../services/api';

export default function MyPage() {
  const { userId, userEmail, user, updateUser } = useAuth();
  
  const [name, setName] = useState('');
  const [major, setMajor] = useState('');
  const [email, setEmail] = useState('');
  const [isEditing, setIsEditing] = useState(false);

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

  // 비밀번호 변경 관련 상태
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [passwordError, setPasswordError] = useState('');
  const [passwordSuccess, setPasswordSuccess] = useState('');

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

  const handlePasswordChange = async () => {
    setPasswordError('');
    setPasswordSuccess('');

    if (!currentPassword || !newPassword || !confirmPassword) {
      setPasswordError('모든 필드를 입력해주세요.');
      return;
    }

    if (newPassword !== confirmPassword) {
      setPasswordError('새 비밀번호가 일치하지 않습니다.');
      return;
    }

    try {
      await authService.updatePassword({ 
        email: email, 
        currentPassword: currentPassword, 
        newPassword: newPassword, 
        newPasswordConfirm: confirmPassword 
      });
      setPasswordSuccess('비밀번호가 성공적으로 변경되었습니다.');
      setCurrentPassword('');
      setNewPassword('');
      setConfirmPassword('');
    } catch (error) {
      setPasswordError(error.message || '비밀번호 변경에 실패했습니다.');
    }
  };

  return (
    <div
      style={{
        width: '100%',
        maxWidth: '900px',
        margin: '0 auto',
        padding: '24px',
        boxSizing: 'border-box',
      }}
    >
      <div className="glass-panel animate-fade-in" style={{ padding: '30px' }}>
        <div
          style={{
            display: 'flex',
            gap: '24px',
            alignItems: 'center',
            marginBottom: '28px',
          }}
        >
          <div
            style={{
              width: '88px',
              height: '88px',
              borderRadius: '50%',
              backgroundColor: 'rgba(96, 201, 90, 0.15)',
              color: 'var(--color-primary)',
              display: 'flex',
              justifyContent: 'center',
              alignItems: 'center',
              fontSize: '32px',
              fontWeight: 700,
              flexShrink: 0,
            }}
          >
            {name ? name.charAt(0).toUpperCase() : '?'}
          </div>

          <div>
            <h3 style={{ margin: 0 }}>{name || '이름 없음'}</h3>
            <p style={{ margin: '6px 0 0', color: 'var(--color-text-muted)' }}>
              {major || '전공 미설정'}
            </p>
          </div>
        </div>

        <div style={{ display: 'grid', gap: '18px' }}>
          <div>
            <label style={{ display: 'block', marginBottom: '8px', fontWeight: 600 }}>
              이름
            </label>
            <input
              className="input-field"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={!isEditing}
              placeholder="이름을 입력하세요"
            />
          </div>

          <div>
            <label style={{ display: 'block', marginBottom: '8px', fontWeight: 600 }}>
              전공
            </label>
            <input
              className="input-field"
              value={major}
              onChange={(e) => setMajor(e.target.value)}
              disabled={!isEditing}
              placeholder="전공을 입력하세요"
            />
          </div>

          <div>
            <label style={{ display: 'block', marginBottom: '8px', fontWeight: 600 }}>
              이메일
            </label>
            <input className="input-field" value={email} disabled />
          </div>
        </div>

        <div style={{ display: 'flex', gap: '10px', marginTop: '24px' }}>
          {isEditing ? (
            <>
              <button className="btn-primary" onClick={handleSave}>
                저장
              </button>
              <button className="btn-outline" onClick={handleCancel}>
                취소
              </button>
            </>
          ) : (
            <button className="btn-primary" onClick={() => setIsEditing(true)}>
              프로필 수정
            </button>
          )}
        </div>
      </div>

      <div className="glass-panel animate-fade-in" style={{ padding: '30px', marginTop: '24px' }}>
        <h3 style={{ margin: '0 0 20px 0', color: 'var(--color-primary)' }}>비밀번호 변경</h3>
        
        <div style={{ display: 'grid', gap: '18px' }}>
          <div>
            <label style={{ display: 'block', marginBottom: '8px', fontWeight: 600 }}>현재 비밀번호</label>
            <input
              type="password"
              className="input-field"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              placeholder="현재 비밀번호"
            />
          </div>
          <div>
            <label style={{ display: 'block', marginBottom: '8px', fontWeight: 600 }}>새 비밀번호</label>
            <input
              type="password"
              className="input-field"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="새 비밀번호"
            />
          </div>
          <div>
            <label style={{ display: 'block', marginBottom: '8px', fontWeight: 600 }}>새 비밀번호 확인</label>
            <input
              type="password"
              className="input-field"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="새 비밀번호 확인"
            />
          </div>
        </div>

        {passwordError && <div style={{ color: 'red', marginTop: '15px' }}>{passwordError}</div>}
        {passwordSuccess && <div style={{ color: 'green', marginTop: '15px' }}>{passwordSuccess}</div>}

        <div style={{ marginTop: '24px' }}>
          <button className="btn-primary" onClick={handlePasswordChange}>
            비밀번호 변경
          </button>
        </div>
      </div>
    </div>
  );
}