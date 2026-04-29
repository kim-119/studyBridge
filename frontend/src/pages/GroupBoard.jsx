import React from 'react';

export default function GroupBoard() {
  const handleClick = () => {
    alert('그룹 스터디 기능은 준비 중입니다.');
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
      <div
        className="glass-panel animate-fade-in"
        style={{ padding: '30px', marginBottom: '24px' }}
      >
        <h2 style={{ margin: 0, color: 'var(--color-primary)' }}>
          그룹게시판
        </h2>
        <p style={{ marginTop: '8px', color: 'var(--color-text-muted)' }}>
          함께 학습할 스터디 그룹을 확인하고 참여할 수 있습니다.
        </p>
      </div>

      <div className="glass-panel animate-fade-in" style={{ padding: '30px' }}>
        <h3>그룹 스터디</h3>
        <p style={{ color: 'var(--color-text-muted)', marginBottom: '24px' }}>
          현재 그룹게시판 상세 기능은 준비 중입니다. 버튼 UI만 제공합니다.
        </p>

        <button className="btn-primary" onClick={handleClick}>
          그룹 스터디 참여하기
        </button>
      </div>
    </div>
  );
}