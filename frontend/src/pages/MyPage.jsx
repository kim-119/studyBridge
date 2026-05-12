import React, { useState } from 'react';

export default function MyPage() {
  const savedEmail = localStorage.getItem('userEmail') || 'guest@example.com';
  const initialName = localStorage.getItem('userName') || savedEmail.split('@')[0];
  const initialMajor = localStorage.getItem('userMajor') || '전공 미설정';

  const [name, setName] = useState(initialName);
  const [major, setMajor] = useState(initialMajor);
  const [email] = useState(savedEmail);
  const [isEditing, setIsEditing] = useState(false);

  const handleSave = () => {
    const finalName = name.trim() || email.split('@')[0];
    const finalMajor = major.trim() || '전공 미설정';

    localStorage.setItem('userName', finalName);
    localStorage.setItem('userMajor', finalMajor);

    setName(finalName);
    setMajor(finalMajor);
    setIsEditing(false);
  };

  const handleCancel = () => {
    setName(localStorage.getItem('userName') || email.split('@')[0]);
    setMajor(localStorage.getItem('userMajor') || '전공 미설정');
    setIsEditing(false);
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
      <div className="glass-panel animate-fade-in" style={{ padding: '30px', marginBottom: '24px' }}>
        <h2 style={{ margin: 0, color: 'var(--color-primary)' }}>마이페이지</h2>
        <p style={{ marginTop: '8px', color: 'var(--color-text-muted)' }}>
          내 프로필 정보를 확인하고 관리할 수 있습니다.
        </p>
      </div>

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
            {name.charAt(0).toUpperCase()}
          </div>

          <div>
            <h3 style={{ margin: 0 }}>{name}</h3>
            <p style={{ margin: '6px 0 0', color: 'var(--color-text-muted)' }}>
              {major}
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
    </div>
  );
}