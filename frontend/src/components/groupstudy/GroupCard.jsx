import React from 'react';
import { User, Lock, Globe, Video, Users, Target, CalendarCheck, Clock } from 'lucide-react';
import {
  STUDY_TYPES, studyTypeLabel, formatTargetMinutes, formatStudySeconds, formatAttendanceRate, formatDateDot,
} from '../../utils/groupStudy';
import GroupProfileImage from './GroupProfileImage';

const MAX_VISIBLE_TAGS = 3;

// 그룹 목록 카드. 정보 위계: [타입/공개 배지] → 이름 → 설명 → 목표·인원·그룹장 → 출석률/평균 공부 → 시작일 → 태그 → 그룹장/CTA.
// 지표 숫자는 서버 값(normalizeGroup)을 포맷만 한다.
export default function GroupCard({ study, userId, applied, onOpen }) {
  const isMine = Number(study.leaderId) === Number(userId);
  const isClosed = study.status === 'CLOSED';
  const ctaDisabled = (isClosed && !isMine && !study.isPrivate) || applied;
  const ctaLabel = applied
    ? '신청완료'
    : (isMine ? '내 스터디' : (study.isPrivate ? '초대 전용' : (isClosed ? '모집마감' : '참여하기')));
  const ctaBg = applied ? '#E5E7EB' : (isMine ? '#DCFCE7' : (study.isPrivate ? 'rgba(139, 92, 246, 0.1)' : '#EFF6FF'));
  const ctaColor = applied ? '#6B7280' : (isMine ? '#16A34A' : (study.isPrivate ? '#8B5CF6' : '#3B82F6'));
  const isCam = study.studyType === STUDY_TYPES.CAM;

  return (
    <div
      className="glass-panel animate-fade-in"
      style={{ display: 'flex', flexDirection: 'column', height: '100%', cursor: 'pointer', overflow: 'hidden', padding: 0, border: '1px solid #e5e7eb', transition: 'transform 0.2s, box-shadow 0.2s' }}
      onMouseEnter={(e) => { e.currentTarget.style.transform = 'translateY(-4px)'; e.currentTarget.style.boxShadow = '0 10px 25px rgba(0,0,0,0.08)'; }}
      onMouseLeave={(e) => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = '0 4px 6px rgba(0,0,0,0.02)'; }}
      onClick={() => onOpen(study)}
    >
      {/* 썸네일 */}
      <div style={{ position: 'relative', width: '100%', paddingTop: '56.25%', backgroundColor: '#f3f4f6', overflow: 'hidden' }}>
        {/* 사용자 지정 이미지 → 없으면 스터디 타입별 기본 아이콘(GENERAL: Users / CAM: Video) */}
        <GroupProfileImage imageUrl={study.hasCoverImage ? study.thumbnailUrl : null} studyType={study.studyType} iconSize={48} fill alt={study.title} />
        <div style={{ position: 'absolute', bottom: 0, left: 0, width: '100%', height: '50%', background: 'linear-gradient(to top, rgba(0,0,0,0.7), transparent)' }} />

        <div className="gs-card-badges">
          <span className="gs-badge" style={{ backgroundColor: study.isPrivate ? 'rgba(139, 92, 246, 0.9)' : 'rgba(59, 130, 246, 0.9)' }}>
            {study.isPrivate ? <><Lock size={12} color="#ffffff" /> 비공개</> : <><Globe size={12} color="#ffffff" /> 공개방</>}
          </span>
          <span className={`gs-badge gs-badge-type${isCam ? ' is-cam' : ''}`}>
            {isCam ? <Video size={12} color="#ffffff" /> : <Users size={12} color="#ffffff" />} {studyTypeLabel(study.studyType)}
          </span>
        </div>

        <div className="gs-card-members" style={{ position: 'absolute', bottom: '12px', left: '12px', color: 'white', display: 'flex', alignItems: 'center', gap: '4px', fontSize: '13px', fontWeight: '600', textShadow: '0 1px 3px rgba(0,0,0,0.5)' }}>
          <User size={14} /> {study.currentMembers} / {study.maxMembers}명
        </div>
      </div>

      {/* 본문 */}
      <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', flex: 1, backgroundColor: 'white' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '6px', gap: '8px' }}>
          <h3 style={{ margin: 0, fontSize: '18px', fontWeight: '700', color: '#111827', lineHeight: '1.4', wordBreak: 'keep-all' }}>{study.title}</h3>
          {isClosed && (
            <span style={{ fontSize: '11px', fontWeight: '600', backgroundColor: '#FEE2E2', color: '#EF4444', padding: '4px 8px', borderRadius: '4px', whiteSpace: 'nowrap' }}>마감</span>
          )}
        </div>

        <p style={{ margin: '0 0 12px 0', fontSize: '14px', color: '#6B7280', lineHeight: '1.5', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
          {study.description}
        </p>

        {/* 목표 · 인원 · 그룹장 */}
        <div className="gs-card-meta">
          <span><Target size={13} /> 목표 <strong>{formatTargetMinutes(study.targetStudyMinutes)}</strong></span>
          <span>· 인원 <strong>{study.currentMembers}/{study.maxMembers}명</strong></span>
          <span>· 그룹장 <strong style={{ maxWidth: '96px', overflow: 'hidden', textOverflow: 'ellipsis' }}>{study.leader}</strong></span>
        </div>

        {/* 출석률 · 평균 공부 (최근 N일, 서버 계산) */}
        <div className="gs-card-stats">
          <div className="gs-stat">
            <div className="gs-stat-label"><CalendarCheck size={12} /> 출석률 · {study.activityWindowDays}일</div>
            <div className="gs-stat-value">{formatAttendanceRate(study.attendanceRate)}</div>
          </div>
          <div className="gs-stat">
            <div className="gs-stat-label"><Clock size={12} /> 평균 공부 · 1일</div>
            <div className="gs-stat-value">{formatStudySeconds(study.avgStudySeconds)}</div>
          </div>
        </div>

        <div className="gs-card-date">시작일 {formatDateDot(study.startDate) || '미정'}</div>

        {study.tags.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '16px' }}>
            {study.tags.slice(0, MAX_VISIBLE_TAGS).map((tag, idx) => (
              <span key={idx} style={{ fontSize: '12px', fontWeight: '500', color: '#4B5563', backgroundColor: '#F3F4F6', padding: '4px 10px', borderRadius: '16px' }}>#{tag}</span>
            ))}
          </div>
        )}

        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: '14px', borderTop: '1px solid #E5E7EB', gap: '12px', marginTop: 'auto' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', color: '#374151', fontWeight: '600', minWidth: 0 }}>
            {study.leaderPhotoUrl ? (
              <img src={study.leaderPhotoUrl} alt={study.leader} style={{ width: '24px', height: '24px', borderRadius: '50%', objectFit: 'cover' }} />
            ) : (
              <div style={{ minWidth: '24px', width: '24px', height: '24px', borderRadius: '50%', backgroundColor: 'var(--color-primary)', color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '12px' }}>
                {study.leader.charAt(0)}
              </div>
            )}
            <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{study.leader}</span>
          </div>

          <button
            className="btn-outline"
            style={{
              width: 'auto', flexShrink: 0, height: '32px', padding: '0 16px', fontSize: '13px', fontWeight: '600', borderRadius: '8px', border: 'none',
              backgroundColor: ctaBg, color: ctaColor,
              cursor: ctaDisabled ? 'not-allowed' : 'pointer',
              opacity: (isClosed && !isMine && !study.isPrivate) ? 0.5 : 1,
            }}
            disabled={ctaDisabled}
            onClick={(e) => { e.stopPropagation(); onOpen(study); }}
          >
            {ctaLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
