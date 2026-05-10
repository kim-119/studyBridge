import React, { useState } from 'react';
import { Users, Plus, Search, Calendar, User, ChevronRight } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';

export default function GroupStudy() {
  const { userId } = useAuth();
  
  // 임시 데이터
  const [studies] = useState([
    {
      id: 1,
      title: '더미 데이터1',
      leader: '개발자킴',
      status: 'RECRUITING', // RECRUITING, CLOSED
      currentMembers: 3,
      maxMembers: 6,
      tags: ['Spring', 'React', 'Project'],
      description: '매주 토요일 오후 2시 강남역에서 진행하는 사이드 프로젝트 스터디입니다.',
    },
    {
      id: 2,
      title: '더미 데이터2',
      leader: 'algo_master',
      status: 'RECRUITING',
      currentMembers: 2,
      maxMembers: 4,
      tags: ['Algorithm', 'Python', '코딩테스트'],
      description: '백준 골드 달성을 목표로 주 2회 온라인으로 진행합니다.',
    },
    {
      id: 3,
      title: '더미 데이터3',
      leader: '취준생A',
      status: 'CLOSED',
      currentMembers: 5,
      maxMembers: 5,
      tags: ['CS', '면접', '운영체제'],
      description: '비대면으로 진행되는 CS 전공지식 정리 스터디입니다. (모집 마감)',
    }
  ]);

  const [appliedStudies, setAppliedStudies] = useState([]); // 신청한 스터디 ID 목록 (임시)

  const handleApply = (studyId) => {
    if (!userId) {
      alert('로그인이 필요합니다.');
      return;
    }
    
    if (appliedStudies.includes(studyId)) {
      alert('이미 신청한 스터디입니다.');
      return;
    }

    if (window.confirm('이 스터디에 참가 신청하시겠습니까?\n(리더의 승인 후 참여가 확정됩니다.)')) {
      setAppliedStudies(prev => [...prev, studyId]);
      alert('참가 신청이 완료되었습니다.');
    }
  };

  const getStatusBadge = (status) => {
    if (status === 'RECRUITING') {
      return <div className="badge recruiting">모집중</div>;
    }
    return <div className="badge closed">모집완료</div>;
  };

  return (
    <div className="container-main">
      <div style={{ marginBottom: '24px' }}>
        <h2 style={{ margin: 0, color: 'var(--color-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <Users size={28} /> 그룹스터디 탐색
        </h2>
        <p style={{ marginTop: '8px', color: 'var(--color-text-muted)' }}>
          함께 성장할 스터디원을 찾거나 새로운 스터디에 참여해보세요.
        </p>
      </div>

      {/* 검색 바 (UI 개선) */}
      <div className="glass-panel" style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '12px 20px', marginBottom: '32px', borderRadius: '12px' }}>
        <Search size={20} color="#9CA3AF" />
        <input 
          type="text" 
          placeholder="관심있는 스터디나 기술 스택을 검색해보세요" 
          style={{ flex: 1, border: 'none', outline: 'none', backgroundColor: 'transparent', fontSize: '15px', color: 'var(--color-text-main)' }}
        />
        <button className="btn-outline" style={{ width: 'auto', height: '36px', padding: '0 20px', fontSize: '13px' }}>
          검색
        </button>
        <div style={{ width: '1px', height: '24px', backgroundColor: 'var(--color-border)', margin: '0 4px' }} />
        <button className="btn-primary" style={{ width: 'auto', height: '36px', padding: '0 16px', fontSize: '13px' }} onClick={() => alert('스터디 생성 기능은 준비 중입니다.')}>
          <Plus size={16} /> 스터디 만들기
        </button>
      </div>

      {/* 스터디 목록 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(350px, 1fr))', gap: '24px' }}>
        {studies.map(study => (
          <div key={study.id} className="glass-panel animate-fade-in" style={{ display: 'flex', flexDirection: 'column', height: '100%', cursor: 'pointer' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              {getStatusBadge(study.status)}
              <div style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '13px', color: 'var(--color-text-muted)', fontWeight: '600' }}>
                <User size={14} /> {study.currentMembers} / {study.maxMembers}
              </div>
            </div>
            
            <h3 style={{ margin: '0 0 12px 0', fontSize: '18px', fontWeight: '700', color: 'var(--color-text-main)', lineHeight: '1.4' }}>
              {study.title}
            </h3>
            
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '16px' }}>
              {study.tags.map((tag, idx) => (
                <span key={idx} className="tag">#{tag}</span>
              ))}
            </div>
            
            <p style={{ margin: '0 0 24px 0', fontSize: '14px', color: 'var(--color-text-muted)', lineHeight: '1.5', flex: 1 }}>
              {study.description}
            </p>
            
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: '16px', borderTop: '1px solid var(--color-border)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', color: 'var(--color-text-main)', fontWeight: '500' }}>
                <div className="avatar-sm" style={{ backgroundColor: 'rgba(96, 201, 90, 0.15)', color: 'var(--color-primary)' }}>
                  {study.leader.charAt(0)}
                </div>
                <span>{study.leader}</span>
              </div>
              
              <button 
                className={study.status === 'CLOSED' ? 'btn-outline' : 'btn-primary'} 
                style={{
                  width: 'auto',
                  height: '32px',
                  padding: '0 16px',
                  fontSize: '13px',
                  borderRadius: '6px',
                  opacity: study.status === 'CLOSED' ? 0.6 : 1,
                  backgroundColor: appliedStudies.includes(study.id) ? '#E5E7EB' : undefined,
                  color: appliedStudies.includes(study.id) ? '#6B7280' : undefined,
                  borderColor: appliedStudies.includes(study.id) ? '#D1D5DB' : undefined,
                }}
                disabled={study.status === 'CLOSED' || appliedStudies.includes(study.id)}
                onClick={() => handleApply(study.id)}
              >
                {appliedStudies.includes(study.id) ? '신청완료' : (study.status === 'CLOSED' ? '마감됨' : '참가 신청')}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

