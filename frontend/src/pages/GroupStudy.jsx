import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Users, Plus, Search, User, Lock, Globe, Filter, ClipboardList, X, AlertTriangle, CheckCircle2, Video, VideoOff, Mic, MicOff, Settings, Volume2, Camera, Check, ArrowLeft } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import StudyRoom from '../components/StudyRoom';

const DUMMY_STUDIES = [
  {
    id: 1,
    title: '공무원 자율 스터디 1',
    description: '매일 아침 9시 출석체크 필수입니다. 카메라 켜고 빡공하실 분!',
    tags: ['공무원', '자율', '캠스터디'],
    currentMembers: 11,
    maxMembers: 16,
    leader: '합격요정',
    status: 'RECRUITING',
    isPrivate: false,
    thumbnailUrl: 'https://images.unsplash.com/photo-1524995997946-a1c2e315a42f?ixlib=rb-4.0.3&auto=format&fit=crop&w=800&q=80',
  },
  {
    id: 2,
    title: '임용, 경찰, 기세방 1',
    description: '합격은 기세다! 멘탈 관리하면서 같이 달릴 분 모십니다.',
    tags: ['임용', '경찰', '소방', '수능'],
    currentMembers: 15,
    maxMembers: 16,
    leader: '독기품은자',
    status: 'RECRUITING',
    isPrivate: true,
    thumbnailUrl: 'https://images.unsplash.com/photo-1434030216411-0b793f4b4173?ixlib=rb-4.0.3&auto=format&fit=crop&w=800&q=80',
  },
  {
    id: 3,
    title: '도파민 프리미엄 캠스터디',
    description: '딴짓 절대 금지. 시간 관리 철저하게 합니다. 하루 10시간 목표!',
    tags: ['프리미엄', '캠스터디', '관리형'],
    currentMembers: 15,
    maxMembers: 16,
    leader: '시간관리자',
    status: 'RECRUITING',
    isPrivate: false,
    thumbnailUrl: 'https://images.unsplash.com/photo-1517842645767-c639042777db?ixlib=rb-4.0.3&auto=format&fit=crop&w=800&q=80',
  },
  {
    id: 4,
    title: '비밀 아지트 (초대 전용)',
    description: '우리 스터디원들만 모이는 프라이빗 방입니다. 외부인 출입 금지.',
    tags: ['비공개', '친목', '집중'],
    currentMembers: 4,
    maxMembers: 8,
    leader: 'mindcontrol',
    status: 'RECRUITING',
    isPrivate: true,
    thumbnailUrl: 'https://images.unsplash.com/photo-1519389950473-47ba0277781c?ixlib=rb-4.0.3&auto=format&fit=crop&w=800&q=80',
  },
  {
    id: 5,
    title: '새벽 코딩 달리기',
    description: '밤 10시부터 새벽 2시까지 코딩하는 개발자들 모임',
    tags: ['개발', '코딩', '새벽반'],
    currentMembers: 6,
    maxMembers: 10,
    leader: '올빼미',
    status: 'CLOSED',
    isPrivate: false,
    thumbnailUrl: 'https://images.unsplash.com/photo-1555066931-4365d14bab8c?ixlib=rb-4.0.3&auto=format&fit=crop&w=800&q=80',
  },
  {
    id: 6,
    title: '의대 지망생 스파르타',
    description: '수능 만점 목표. 서로 질의응답하며 멘토링하는 스터디입니다.',
    tags: ['수능', '의대', '스파르타'],
    currentMembers: 8,
    maxMembers: 8,
    leader: '메디컬가이',
    status: 'CLOSED',
    isPrivate: true,
    thumbnailUrl: 'https://images.unsplash.com/photo-1532012197267-da84d127e765?ixlib=rb-4.0.3&auto=format&fit=crop&w=800&q=80',
  }
];

const DUMMY_RECRUITMENTS = [
  { id: 101, isPrivate: false, title: '[공시] 매일 아침 9시 출석체크 스터디원 구합니다 (캠필수)', author: '합격요정', date: '2023-10-27', status: 'RECRUITING', current: 11, max: 16, views: 142, content: '지방직 공무원 준비하시는 분들 모십니다. 매일 아침 9시 출석체크 후 캠 켜고 4시간 이상 빡공 필수입니다. 벌금제 운영하니 열심히 하실 분만 지원해주세요.' },
  { id: 102, isPrivate: true, title: '[임용] 기세방 1기 충원합니다 (1자리 급구)', author: '독기품은자', date: '2023-10-26', status: 'RECRUITING', current: 15, max: 16, views: 89, content: '결원 1명 생겨서 급하게 충원합니다. 스터디 분위기 좋고 다들 열정 넘칩니다. 중도 하차 없이 끝까지 달릴 분만 받습니다.' },
  { id: 103, isPrivate: true, title: '[프리미엄] 도파민 디톡스 캠스터디 (빡공하실분만)', author: '시간관리자', date: '2023-10-25', status: 'RECRUITING', current: 15, max: 16, views: 256, content: '휴대폰 잠금 앱 인증 필수. 일주일 50시간 이상 채우셔야 강퇴 면합니다. 철저한 관리형으로 운영되니 참고하세요.' },
  { id: 104, isPrivate: false, title: '[개발] 코딩테스트 스터디 주 3회 (Java/Python)', author: '알고리즘깎는노인', date: '2023-10-24', status: 'CLOSED', current: 4, max: 4, views: 312, content: '매주 화,목,토 1문제씩 풀고 구글밋에서 코드 리뷰 진행합니다. 백준 골드 이상.' },
  { id: 105, isPrivate: false, title: '토익 900+ 목표 LC/RC 리뷰 스터디', author: '토익마스터', date: '2023-10-23', status: 'RECRUITING', current: 2, max: 6, views: 45, content: '매주 일요일 저녁 8시 디스코드에서 모의고사 리뷰합니다. 현재 800점대이신 분들 위주로 모십니다.' },
];

const DUMMY_MY_STUDIES = [
  { id: 201, title: '리액트 프론트엔드 프로젝트' },
  { id: 202, title: '정보처리기사 실기 빡공방' },
  { id: 203, title: '토플 스피킹 연습방' }
];

export default function GroupStudy() {
  const { userId } = useAuth();
  const navigate = useNavigate();

  const [studies] = useState(DUMMY_STUDIES);
  const [recruitments, setRecruitments] = useState(DUMMY_RECRUITMENTS);
  const [appliedStudies, setAppliedStudies] = useState([]);
  const [filter, setFilter] = useState('PUBLIC'); // 'PUBLIC', 'PRIVATE', 'RECRUIT'
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedPost, setSelectedPost] = useState(null);
  const [applyMessage, setApplyMessage] = useState('');

  const [isWriteModalOpen, setIsWriteModalOpen] = useState(false);
  const [writeForm, setWriteForm] = useState({ studyId: '', title: '', content: '' });

  const [isCreateStudyMode, setIsCreateStudyMode] = useState(false);
  const [showImageSelectModal, setShowImageSelectModal] = useState(false);
  const [createForm, setCreateForm] = useState({
    title: '',
    tags: '',
    thumbnail: 'https://images.unsplash.com/photo-1517842645767-c639042777db?ixlib=rb-4.0.3&auto=format&fit=crop&w=800&q=80',
    startDate: '2026-06-02',
    endDate: '2026-09-02',
    isPublic: true,
    cameraOn: true,
    description: ''
  });

  // 프리조인(입장 준비) 상태
  const [preJoinStudy, setPreJoinStudy] = useState(null);
  const [activeStudyRoom, setActiveStudyRoom] = useState(null);
  const [resolution, setResolution] = useState('');
  const [isVideoOn, setIsVideoOn] = useState(true);
  const [isMicOn, setIsMicOn] = useState(true);
  const [showPreJoinInfo, setShowPreJoinInfo] = useState(false);
  const [showPreJoinSettings, setShowPreJoinSettings] = useState(false);

  // 커스텀 알림/컨펌 모달 상태
  const [customAlert, setCustomAlert] = useState({
    isOpen: false,
    title: '',
    message: '',
    type: 'alert', // 'alert' | 'confirm'
    onConfirm: null,
    onCancel: null,
  });

  const showAlert = (title, message, onConfirm = null) => {
    setCustomAlert({ isOpen: true, title, message, type: 'alert', onConfirm: () => { setCustomAlert(prev => ({ ...prev, isOpen: false })); if (onConfirm) onConfirm(); } });
  };

  const showConfirm = (title, message, onConfirm) => {
    setCustomAlert({ isOpen: true, title, message, type: 'confirm', onConfirm: () => { setCustomAlert(prev => ({ ...prev, isOpen: false })); onConfirm(); }, onCancel: () => setCustomAlert(prev => ({ ...prev, isOpen: false })) });
  };

  const checkAuth = () => {
    if (!userId) {
      showAlert('로그인 필요', '로그인이 필요한 기능입니다. 로그인 페이지로 이동합니다.', () => navigate('/login'));
      return false;
    }
    return true;
  };

  const [studies] = useState([]);

  const handleApply = (study, e) => {
    e.stopPropagation(); // 카드 클릭 이벤트 방지
    if (!checkAuth()) return;

    if (appliedStudies.includes(studyId)) {
      alert('이미 신청한 스터디입니다.');

    if (appliedStudies.includes(study.id)) {
      showAlert('알림', '이미 신청한 스터디입니다.');
      return;
    }

    if (study.leader === 'mindcontrol') {
      setPreJoinStudy(study);
      return;
    }

    if (study.isPrivate) {
      setPreJoinStudy(study);
      return;
    }

    showConfirm('참가 신청', `'${study.title}' 스터디에 참가 신청하시겠습니까?\n(리더의 승인 후 참여가 확정됩니다.)`, () => {
      setAppliedStudies(prev => [...prev, study.id]);
      showAlert('알림', '참가 신청이 완료되었습니다.');
    });
  };

  // 필터링 적용
  const filteredStudies = studies.filter(study => {
    if (filter === 'PUBLIC' && study.isPrivate) return false;
    if (filter === 'PRIVATE' && !study.isPrivate) return false;
    if (searchQuery && !study.title.includes(searchQuery) && !study.tags.some(t => t.includes(searchQuery))) return false;
    return true;
  });

  return (
    <div className="container-main" style={{ paddingTop: '24px' }}>

      {isCreateStudyMode ? (
        <div className="glass-panel" style={{ padding: '50px 70px', maxWidth: '900px', margin: '0 auto 60px', display: 'flex', flexDirection: 'column', gap: '36px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px', borderBottom: '1px solid #e5e7eb', paddingBottom: '24px' }}>
            <button
              onClick={() => setIsCreateStudyMode(false)}
              style={{ cursor: 'pointer', width: '44px', height: '44px', borderRadius: '50%', backgroundColor: '#F3F4F6', display: 'flex', alignItems: 'center', justifyContent: 'center', border: 'none', transition: 'all 0.2s', padding: 0 }}
              onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = '#E5E7EB'; e.currentTarget.style.transform = 'scale(1.05)'; }}
              onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = '#F3F4F6'; e.currentTarget.style.transform = 'scale(1)'; }}
            >
              <ArrowLeft size={24} color="#4B5563" strokeWidth={2.5} />
            </button>
            <h2 style={{ fontSize: '26px', fontWeight: '700', color: '#111827', margin: 0, letterSpacing: '-0.5px' }}>새로운 스터디 개설하기</h2>
          </div>

          {/* 공개 여부 */}
          <div style={{ display: 'flex', gap: '24px' }}>
            <div style={{ width: '120px', fontWeight: '600', color: '#374151', display: 'flex', alignItems: 'center' }}>
              공개 여부 <span style={{ color: '#EF4444', marginLeft: '4px' }}>*</span> <span style={{ color: '#9CA3AF', marginLeft: '6px', fontSize: '14px', cursor: 'help' }}>?</span>
            </div>
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div style={{ display: 'flex', gap: '24px', alignItems: 'center' }}>
                <div
                  onClick={() => setCreateForm({...createForm, isPublic: true})}
                  style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '15px', color: createForm.isPublic ? '#111827' : '#6B7280' }}
                >
                  <div style={{ width: '22px', height: '22px', borderRadius: '50%', backgroundColor: createForm.isPublic ? '#3B82F6' : '#E5E7EB', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <Check size={14} color="white" strokeWidth={3} />
                  </div>
                  공개 스터디
                </div>
                <div
                  onClick={() => setCreateForm({...createForm, isPublic: false})}
                  style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '15px', color: !createForm.isPublic ? '#111827' : '#6B7280' }}
                >
                  <div style={{ width: '22px', height: '22px', borderRadius: '50%', backgroundColor: !createForm.isPublic ? '#3B82F6' : '#E5E7EB', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                    <Check size={14} color="white" strokeWidth={3} />
                  </div>
                  비공개 스터디
                </div>
              </div>
              <div style={{ color: '#6B7280', fontSize: '14px' }}>
                * 공개 여부는 스터디를 만든 후 변경이 불가능합니다.
              </div>
            </div>
          </div>

          {/* 스터디 이름 */}
          <div style={{ display: 'flex', gap: '24px' }}>
            <div style={{ width: '120px', fontWeight: '600', color: '#374151', display: 'flex', alignItems: 'center' }}>
              스터디 이름 <span style={{ color: '#EF4444', marginLeft: '4px' }}>*</span>
            </div>
            <div style={{ flex: 1 }}>
              <input
                type="text"
                placeholder="스터디 이름을 입력하세요"
                value={createForm.title}
                onChange={(e) => setCreateForm({ ...createForm, title: e.target.value })}
                style={{ width: '100%', padding: '12px 16px', borderRadius: '8px', border: '1px solid #D1D5DB', fontSize: '15px', outline: 'none' }}
              />
            </div>
          </div>

          {/* 해시태그 */}
          <div style={{ display: 'flex', gap: '24px' }}>
            <div style={{ width: '120px', fontWeight: '600', color: '#374151', display: 'flex', alignItems: 'center' }}>
              해시태그
            </div>
            <div style={{ flex: 1 }}>
              <input
                type="text"
                placeholder="스터디를 대표하는 키워드를 입력하세요. (최대 3개)"
                value={createForm.tags}
                onChange={(e) => setCreateForm({ ...createForm, tags: e.target.value })}
                style={{ width: '100%', padding: '12px 16px', borderRadius: '8px', border: '1px solid #D1D5DB', fontSize: '15px', outline: 'none' }}
              />
            </div>
          </div>

          {/* 대표 이미지 */}
          <div style={{ display: 'flex', gap: '24px' }}>
            <div style={{ width: '120px', fontWeight: '600', color: '#374151', paddingTop: '8px' }}>
              대표 이미지
            </div>
            <div style={{ flex: 1 }}>
              <div style={{ position: 'relative', width: '300px', height: '200px', borderRadius: '12px', overflow: 'hidden', backgroundImage: `url(${createForm.thumbnail})`, backgroundSize: 'cover', backgroundPosition: 'center' }}>
                <div
                  style={{ position: 'absolute', bottom: '12px', left: '12px', backgroundColor: 'rgba(0,0,0,0.6)', padding: '6px 12px', borderRadius: '6px', color: 'white', display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer', fontSize: '13px', fontWeight: '600' }}
                  onClick={() => setShowImageSelectModal(true)}
                >
                  <Camera size={14} /> 편집
                </div>
              </div>
            </div>
          </div>

          {/* 기간 */}
          <div style={{ display: 'flex', gap: '24px' }}>
            <div style={{ width: '120px', fontWeight: '600', color: '#374151', paddingTop: '14px' }}>
              기간 <span style={{ color: '#9CA3AF', marginLeft: '4px', fontSize: '14px', cursor: 'help' }}>?</span>
            </div>
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <input
                  type="date"
                  value={createForm.startDate}
                  onChange={(e) => setCreateForm({ ...createForm, startDate: e.target.value })}
                  style={{ padding: '12px 16px', borderRadius: '8px', border: '1px solid #D1D5DB', fontSize: '15px', outline: 'none', color: '#374151', width: '200px' }}
                />
                <span style={{ color: '#6B7280' }}>~</span>
                <input
                  type="date"
                  value={createForm.endDate}
                  onChange={(e) => setCreateForm({ ...createForm, endDate: e.target.value })}
                  style={{ padding: '12px 16px', borderRadius: '8px', border: '1px solid #D1D5DB', fontSize: '15px', outline: 'none', color: '#374151', width: '200px' }}
                />
              </div>
              <div style={{ color: '#6B7280', fontSize: '14px' }}>
                92일 동안 스터디가 유지됩니다.
              </div>
            </div>
          </div>

          {/* 초기 장치 설정 */}
          <div style={{ display: 'flex', gap: '24px' }}>
            <div style={{ width: '120px', fontWeight: '600', color: '#374151', display: 'flex', alignItems: 'center' }}>
              초기 장치 설정 <span style={{ color: '#9CA3AF', marginLeft: '6px', fontSize: '14px', cursor: 'help' }}>?</span>
            </div>
            <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: '12px' }}>
              <div
                style={{ width: '44px', height: '24px', borderRadius: '24px', backgroundColor: createForm.cameraOn ? '#3B82F6' : '#E5E7EB', position: 'relative', cursor: 'pointer', transition: 'background-color 0.2s' }}
                onClick={() => setCreateForm({...createForm, cameraOn: !createForm.cameraOn})}
              >
                <div style={{ width: '20px', height: '20px', borderRadius: '50%', backgroundColor: 'white', position: 'absolute', top: '2px', left: createForm.cameraOn ? '22px' : '2px', transition: 'left 0.2s', boxShadow: '0 1px 2px rgba(0,0,0,0.1)' }} />
              </div>
              <span style={{ fontSize: '15px', color: '#374151' }}>카메라</span>
            </div>
          </div>

          {/* 스터디 공지사항 */}
          <div style={{ display: 'flex', gap: '24px' }}>
            <div style={{ width: '120px', fontWeight: '600', color: '#374151', paddingTop: '8px' }}>
              스터디 공지사항
            </div>
            <div style={{ flex: 1 }}>
              <textarea
                placeholder="스터디 규칙, 공지 사항 등을 입력해주세요"
                value={createForm.description}
                onChange={(e) => {
                  if (e.target.value.length <= 1000) {
                    setCreateForm({ ...createForm, description: e.target.value });
                  }
                }}
                style={{ width: '100%', height: '240px', padding: '16px', borderRadius: '8px', border: '1px solid #D1D5DB', fontSize: '15px', outline: 'none', resize: 'none', color: '#374151', boxSizing: 'border-box' }}
              />
              <div style={{ fontSize: '13px', color: '#6B7280', marginTop: '6px' }}>
                ({createForm.description.length} / 1000)
              </div>
            </div>
          </div>

          {/* Submit Button */}
          <div style={{ display: 'flex', justifyContent: 'center', marginTop: '16px' }}>
            <button
              className="btn-primary"
              style={{ padding: '14px 48px', fontSize: '16px', fontWeight: '700', backgroundColor: '#22C55E' }}
              onClick={() => {
                showAlert('성공', '스터디가 성공적으로 개설되었습니다!', () => setIsCreateStudyMode(false));
              }}
            >
              + 스터디 만들기
            </button>
          </div>
        </div>
      ) : (
        <>
          {/* 상단 컨트롤 영역 (검색 & 필터) */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', marginBottom: '32px' }}>

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
        <button className="btn-primary" style={{ width: 'auto', height: '36px', padding: '0 16px', fontSize: '13px' }} onClick={() => checkAuth() && alert('스터디 생성 기능은 준비 중입니다.')}>
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
            {/* 필터 탭 */}
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
              <button
                onClick={() => setFilter('PUBLIC')}
                style={{
                  padding: '8px 20px', borderRadius: '30px', fontSize: '14px', fontWeight: '600', cursor: 'pointer', transition: 'all 0.2s', border: 'none',
                  backgroundColor: filter === 'PUBLIC' ? '#3B82F6' : '#f3f4f6',
                  color: filter === 'PUBLIC' ? '#fff' : 'var(--color-text-muted)',
                  display: 'flex', alignItems: 'center', gap: '6px'
                }}
              >
                <Globe size={16} /> 공개 스터디
              </button>
              <button
                onClick={() => setFilter('PRIVATE')}
                style={{
                  padding: '8px 20px', borderRadius: '30px', fontSize: '14px', fontWeight: '600', cursor: 'pointer', transition: 'all 0.2s', border: 'none',
                  backgroundColor: filter === 'PRIVATE' ? '#8B5CF6' : '#f3f4f6',
                  color: filter === 'PRIVATE' ? '#fff' : 'var(--color-text-muted)',
                  display: 'flex', alignItems: 'center', gap: '6px'
                }}
              >
                <Lock size={16} /> 비공개방
              </button>
              <button
                onClick={() => setFilter('RECRUIT')}
                style={{
                  padding: '8px 20px', borderRadius: '30px', fontSize: '14px', fontWeight: '600', cursor: 'pointer', transition: 'all 0.2s', border: 'none',
                  backgroundColor: filter === 'RECRUIT' ? '#10B981' : '#f3f4f6',
                  color: filter === 'RECRUIT' ? '#fff' : 'var(--color-text-muted)',
                  display: 'flex', alignItems: 'center', gap: '6px'
                }}
              >
                <ClipboardList size={16} /> 모집게시판
              </button>
            </div>

            {/* 검색 바 */}
            <div className="glass-panel" style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '12px 20px', borderRadius: '12px' }}>
              <Search size={20} color="#9CA3AF" />
              <input
                type="text"
                placeholder="관심있는 스터디나 기술 스택(태그)을 검색해보세요"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                style={{ flex: 1, border: 'none', outline: 'none', backgroundColor: 'transparent', fontSize: '15px', color: 'var(--color-text-main)' }}
              />
              <div style={{ width: '1px', height: '24px', backgroundColor: 'var(--color-border)', margin: '0 4px' }} />
              <button
                className="btn-primary"
                style={{ width: 'auto', height: '36px', padding: '0 16px', fontSize: '14px' }}
                onClick={() => {
                  if (!checkAuth()) return;
                  if (filter === 'RECRUIT') {
                    setIsWriteModalOpen(true);
                  } else {
                    setIsCreateStudyMode(true);
                  }
                }}
              >
                <Plus size={16} /> {filter === 'RECRUIT' ? '모집글 쓰기' : '스터디 만들기'}
              </button>
            </div>
          </div>

          {filter === 'RECRUIT' ? (
            // 모집게시판 UI (게시글 목록 형태)
            <div className="glass-panel" style={{ padding: '0', overflow: 'hidden', borderRadius: '12px', border: '1px solid #e5e7eb' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                <thead style={{ backgroundColor: '#f9fafb', borderBottom: '1px solid #e5e7eb' }}>
                  <tr>
                    <th style={{ padding: '16px 20px', color: '#6B7280', fontWeight: '600', fontSize: '13px', width: '10%' }}>상태</th>
                    <th style={{ padding: '16px 20px', color: '#6B7280', fontWeight: '600', fontSize: '13px', width: '60%' }}>제목</th>
                    <th style={{ padding: '16px 20px', color: '#6B7280', fontWeight: '600', fontSize: '13px', width: '15%' }}>작성자</th>
                    <th style={{ padding: '16px 20px', color: '#6B7280', fontWeight: '600', fontSize: '13px', width: '15%' }}>작성일</th>
                  </tr>
                </thead>
                <tbody>
                  {recruitments.filter(post => !searchQuery || post.title.includes(searchQuery)).map((post, idx) => (
                    <tr
                      key={post.id}
                      style={{ borderBottom: idx === recruitments.length - 1 ? 'none' : '1px solid #e5e7eb', transition: 'background-color 0.2s', cursor: 'pointer' }}
                      onMouseEnter={(e) => e.currentTarget.style.backgroundColor = '#f9fafb'}
                      onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
                      onClick={() => setSelectedPost(post)}
                    >
                      <td style={{ padding: '16px 20px' }}>
                        {post.status === 'RECRUITING' ?
                          <span style={{ backgroundColor: '#DEF7EC', color: '#03543F', padding: '4px 8px', borderRadius: '4px', fontSize: '11px', fontWeight: '700' }}>모집중</span> :
                          <span style={{ backgroundColor: '#F3F4F6', color: '#6B7280', padding: '4px 8px', borderRadius: '4px', fontSize: '11px', fontWeight: '700' }}>마감</span>
                        }
                      </td>
                      <td style={{ padding: '16px 20px', fontWeight: '600', color: '#111827', fontSize: '15px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          {post.isPrivate ? (
                            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', backgroundColor: '#F3F4F6', color: '#4B5563', padding: '2px 6px', borderRadius: '4px', fontSize: '11px', fontWeight: '700' }}><Lock size={12} /> 비공개</span>
                          ) : (
                            <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', backgroundColor: '#EFF6FF', color: '#3B82F6', padding: '2px 6px', borderRadius: '4px', fontSize: '11px', fontWeight: '700' }}><Globe size={12} /> 공개</span>
                          )}
                          <span>{post.title}</span>
                          <span style={{ fontSize: '12px', color: '#6B7280', fontWeight: '500' }}>[{post.current}/{post.max}]</span>
                        </div>
                      </td>
                      <td style={{ padding: '16px 20px', color: '#4B5563', fontSize: '14px' }}>{post.author}</td>
                      <td style={{ padding: '16px 20px', color: '#9CA3AF', fontSize: '13px' }}>{post.date}</td>
                    </tr>
                  ))}
                  {recruitments.filter(post => !searchQuery || post.title.includes(searchQuery)).length === 0 && (
                    <tr>
                      <td colSpan="5" style={{ padding: '60px 0', textAlign: 'center', color: '#9CA3AF' }}>검색 결과가 없습니다.</td>
                    </tr>
                  )}
                </tbody>
              </table>
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
          ) : (
            /* 스터디 목록 그리드 */
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '24px' }}>
              {filteredStudies.length === 0 ? (
                <div style={{ gridColumn: '1 / -1', padding: '60px 0', textAlign: 'center', color: 'var(--color-text-muted)', backgroundColor: '#f9fafb', borderRadius: '16px' }}>
                  <Filter size={40} style={{ margin: '0 auto 16px', opacity: 0.3 }} />
                  <p style={{ fontSize: '16px', fontWeight: '500' }}>조건에 맞는 스터디가 없습니다.</p>
                </div>
              ) : (
                filteredStudies.map(study => (
                  <div
                    key={study.id}
                    className="glass-panel animate-fade-in"
                    style={{ display: 'flex', flexDirection: 'column', height: '100%', cursor: 'pointer', overflow: 'hidden', padding: 0, border: '1px solid #e5e7eb', transition: 'transform 0.2s, box-shadow 0.2s' }}
                    onMouseEnter={(e) => { e.currentTarget.style.transform = 'translateY(-4px)'; e.currentTarget.style.boxShadow = '0 10px 25px rgba(0,0,0,0.08)'; }}
                    onMouseLeave={(e) => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = '0 4px 6px rgba(0,0,0,0.02)'; }}
                    onClick={() => {
                      if (!checkAuth()) return;
                      setPreJoinStudy(study);
                    }}
                  >
                    {/* 썸네일 영역 */}
                    <div style={{ position: 'relative', width: '100%', paddingTop: '56.25%', backgroundColor: '#f3f4f6', overflow: 'hidden' }}>
                      <img
                        src={study.thumbnailUrl}
                        alt={study.title}
                        style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', objectFit: 'cover' }}
                      />

                      {/* 딤 처리 (하단 그라데이션) */}
                      <div style={{ position: 'absolute', bottom: 0, left: 0, width: '100%', height: '50%', background: 'linear-gradient(to top, rgba(0,0,0,0.7), transparent)' }} />

                      {/* 공개/비공개 배지 */}
                      <div style={{ position: 'absolute', top: '12px', left: '12px', backgroundColor: study.isPrivate ? 'rgba(139, 92, 246, 0.9)' : 'rgba(59, 130, 246, 0.9)', backdropFilter: 'blur(4px)', color: '#ffffff', padding: '6px 10px', borderRadius: '20px', display: 'flex', alignItems: 'center', gap: '4px', fontSize: '11px', fontWeight: '700', boxShadow: '0 2px 10px rgba(0,0,0,0.1)' }}>
                        {study.isPrivate ? <><Lock size={12} color="#ffffff" /> 비공개</> : <><Globe size={12} color="#ffffff" /> 공개방</>}
                      </div>

                      {/* 멤버 수 오버레이 */}
                      <div style={{ position: 'absolute', bottom: '12px', left: '12px', color: 'white', display: 'flex', alignItems: 'center', gap: '4px', fontSize: '13px', fontWeight: '600', textShadow: '0 1px 3px rgba(0,0,0,0.5)' }}>
                        <User size={14} /> {study.currentMembers} / {study.maxMembers}명
                      </div>
                    </div>

                    {/* 콘텐츠 영역 */}
                    <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', flex: 1, backgroundColor: 'white' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '8px' }}>
                        <h3 style={{ margin: 0, fontSize: '18px', fontWeight: '700', color: '#111827', lineHeight: '1.4', wordBreak: 'keep-all' }}>
                          {study.title}
                        </h3>
                        {study.status === 'CLOSED' && (
                          <span style={{ fontSize: '11px', fontWeight: '600', backgroundColor: '#FEE2E2', color: '#EF4444', padding: '4px 8px', borderRadius: '4px', whiteSpace: 'nowrap' }}>마감</span>
                        )}
                      </div>

                      <p style={{ margin: '0 0 16px 0', fontSize: '14px', color: '#6B7280', lineHeight: '1.5', flex: 1, display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                        {study.description}
                      </p>

                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '20px' }}>
                        {study.tags.map((tag, idx) => (
                          <span key={idx} style={{ fontSize: '12px', fontWeight: '500', color: '#4B5563', backgroundColor: '#F3F4F6', padding: '4px 10px', borderRadius: '16px' }}>
                            #{tag}
                          </span>
                        ))}
                      </div>

                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: '16px', borderTop: '1px solid #E5E7EB', gap: '12px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '13px', color: '#374151', fontWeight: '600', minWidth: 0 }}>
                          <div style={{ minWidth: '24px', width: '24px', height: '24px', borderRadius: '50%', backgroundColor: 'var(--color-primary)', color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '12px' }}>
                            {study.leader.charAt(0)}
                          </div>
                          <span style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{study.leader}</span>
                        </div>

                        <button
                          className="btn-outline"
                          style={{
                            width: 'auto', flexShrink: 0,
                            height: '32px', padding: '0 16px', fontSize: '13px', fontWeight: '600', borderRadius: '8px', border: 'none',
                            backgroundColor: appliedStudies.includes(study.id) ? '#E5E7EB' : (study.leader === 'mindcontrol' ? '#DCFCE7' : (study.isPrivate ? 'rgba(139, 92, 246, 0.1)' : '#EFF6FF')),
                            color: appliedStudies.includes(study.id) ? '#6B7280' : (study.leader === 'mindcontrol' ? '#16A34A' : (study.isPrivate ? '#8B5CF6' : '#3B82F6')),
                            cursor: (study.status === 'CLOSED' && study.leader !== 'mindcontrol' && !study.isPrivate || appliedStudies.includes(study.id)) ? 'not-allowed' : 'pointer',
                            opacity: (study.status === 'CLOSED' && study.leader !== 'mindcontrol' && !study.isPrivate) ? 0.5 : 1
                          }}
                          disabled={study.status === 'CLOSED' && study.leader !== 'mindcontrol' && !study.isPrivate || appliedStudies.includes(study.id)}
                          onClick={(e) => handleApply(study, e)}
                        >
                          {appliedStudies.includes(study.id) ? '신청완료' : (study.leader === 'mindcontrol' ? '내 스터디 입장' : (study.isPrivate ? '스터디 입장' : (study.status === 'CLOSED' ? '모집마감' : '참여하기')))}
                        </button>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}

          {/* 모집글 상세 모달 */}
          {selectedPost && (
            <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: '20px' }} onClick={() => { setSelectedPost(null); setApplyMessage(''); }}>
              <div style={{ backgroundColor: 'white', borderRadius: '12px', width: '100%', maxWidth: '420px', overflow: 'hidden', boxShadow: '0 25px 50px -12px rgba(0,0,0,0.25)', display: 'flex', flexDirection: 'column', animation: 'slideUp 0.3s ease-out' }} onClick={(e) => e.stopPropagation()}>

                {/* 상단 이미지 및 제목 영역 */}
                <div style={{ position: 'relative', height: '160px', backgroundColor: '#1F2937', color: 'white', display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', padding: '20px' }}>
                  <img src="https://images.unsplash.com/photo-1516321497487-e288fb19713f?ixlib=rb-4.0.3&auto=format&fit=crop&w=800&q=80" alt="Background" style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', objectFit: 'cover', opacity: 0.3 }} />
                  <button onClick={() => { setSelectedPost(null); setApplyMessage(''); }} style={{ position: 'absolute', top: '16px', right: '16px', background: 'none', border: 'none', color: 'white', cursor: 'pointer', padding: '4px', zIndex: 2 }}>
                    <X size={20} />
                  </button>

                  <div style={{ position: 'relative', zIndex: 1 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                      {selectedPost.isPrivate ? (
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', backgroundColor: 'rgba(0,0,0,0.5)', color: '#fff', padding: '4px 8px', borderRadius: '4px', fontSize: '12px', fontWeight: '600' }}><Lock size={14} /> 비공개 스터디 모집</span>
                      ) : (
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', backgroundColor: 'rgba(59, 130, 246, 0.8)', color: '#fff', padding: '4px 8px', borderRadius: '4px', fontSize: '12px', fontWeight: '600' }}><Globe size={14} /> 공개 스터디 모집</span>
                      )}
                    </div>
                    <h2 style={{ margin: '0 0 12px 0', fontSize: '20px', fontWeight: '700', color: '#fff', textShadow: '0 2px 4px rgba(0,0,0,0.5)', wordBreak: 'keep-all', lineHeight: '1.3' }}>{selectedPost.title}</h2>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <div style={{ width: '24px', height: '24px', borderRadius: '50%', backgroundColor: 'var(--color-primary)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '12px', fontWeight: '700', boxShadow: '0 2px 4px rgba(0,0,0,0.3)' }}>
                        {selectedPost.author.charAt(0)}
                      </div>
                      <span style={{ fontSize: '14px', fontWeight: '500', textShadow: '0 1px 2px rgba(0,0,0,0.5)' }}>{selectedPost.author}</span>
                    </div>
                  </div>
                </div>

                {/* 하단 상세 내용 영역 */}
                <div style={{ padding: '24px', flex: 1, overflowY: 'auto' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '24px', paddingBottom: '24px', borderBottom: '1px solid #E5E7EB' }}>
                    <div>
                      <div style={{ fontSize: '13px', color: '#6B7280', marginBottom: '6px' }}>스터디 정원</div>
                      <div style={{ fontSize: '15px', fontWeight: '700', color: '#111827' }}>{selectedPost.current} / {selectedPost.max} 명</div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontSize: '13px', color: '#6B7280', marginBottom: '6px' }}>스터디 기간 <span style={{ backgroundColor: '#FEF3C7', color: '#D97706', padding: '2px 6px', borderRadius: '4px', fontSize: '11px', fontWeight: '700', marginLeft: '4px' }}>D-7</span></div>
                      <div style={{ fontSize: '15px', fontWeight: '700', color: '#111827' }}>2026.10.05 - 2026.12.09</div>
                    </div>
                  </div>

                  <div style={{ marginBottom: '24px' }}>
                    <div style={{ fontSize: '13px', color: '#6B7280', marginBottom: '8px' }}>모집글 내용</div>
                    <div style={{ backgroundColor: '#F9FAFB', padding: '16px', borderRadius: '8px', fontSize: '14px', color: '#374151', lineHeight: '1.6', wordBreak: 'keep-all', border: '1px solid #F3F4F6' }}>
                      {selectedPost.content}
                    </div>
                  </div>

                  {selectedPost.isPrivate && (
                    <div style={{ marginBottom: '24px' }}>
                      <div style={{ fontSize: '13px', color: '#6B7280', marginBottom: '8px', display: 'flex', justifyContent: 'space-between' }}>
                        <span>방장에게 보낼 참가 신청 메시지</span>
                        <span style={{ fontSize: '11px', color: '#9CA3AF' }}>(선택)</span>
                      </div>
                      <textarea
                        placeholder="자기소개나 각오 등 방장에게 어필할 메시지를 남겨보세요!"
                        value={applyMessage}
                        onChange={(e) => setApplyMessage(e.target.value)}
                        style={{
                          width: '100%', height: '80px', padding: '12px', borderRadius: '8px', border: '1px solid #D1D5DB',
                          fontSize: '13px', resize: 'none', outline: 'none', fontFamily: 'inherit',
                          boxSizing: 'border-box'
                        }}
                        onFocus={(e) => e.target.style.borderColor = '#3B82F6'}
                        onBlur={(e) => e.target.style.borderColor = '#D1D5DB'}
                      />
                    </div>
                  )}

                  {/* 경고 안내 박스 */}
                  <div style={{ backgroundColor: '#FEF2F2', borderRadius: '8px', padding: '16px', border: '1px solid #FCA5A5' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#DC2626', fontWeight: '700', fontSize: '13px', marginBottom: '8px' }}>
                      <AlertTriangle size={16} /> 불량(음란) 사용자 신고 안내
                    </div>
                    <p style={{ margin: 0, fontSize: '12px', color: '#DC2626', lineHeight: '1.5' }}>
                      신고 접수된 사용자는 운영정책에 따라 스터디 입장이 제한됩니다. 허위로 신고 시 서비스 사용이 제한될 수 있으니 주의해 주세요.
                      <br />
                      <a href="#" style={{ color: '#6B7280', textDecoration: 'underline', marginTop: '8px', display: 'inline-block' }}>자세히 보기</a>
                    </p>
                  </div>
                </div>

                {/* 버튼 영역 */}
                <div style={{ backgroundColor: '#3B82F6', padding: '0' }}>
                  <button
                    style={{ width: '100%', padding: '16px', fontSize: '15px', fontWeight: '600', color: 'white', backgroundColor: 'transparent', border: 'none', cursor: 'pointer', transition: 'background-color 0.2s' }}
                    onMouseEnter={(e) => e.currentTarget.style.backgroundColor = '#2563EB'}
                    onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
                    onClick={() => {
                      if (!checkAuth()) return;
                      if (appliedStudies.includes(`recruit_${selectedPost.id}`)) {
                        showAlert('알림', '이미 신청한 스터디입니다.');
                        return;
                      }
                      if (selectedPost.status === 'CLOSED') {
                        showAlert('알림', '마감된 스터디입니다.');
                        return;
                      }
                      if (selectedPost.isPrivate) {
                        const processApplication = () => {
                          showConfirm('참가 신청', `'${selectedPost.title}' 방장에게 참가 신청서를 전송하시겠습니까?`, () => {
                            setAppliedStudies(prev => [...prev, `recruit_${selectedPost.id}`]);
                            showAlert('신청 완료', `신청 완료!\n\n[방장에게 전송된 메시지]\n${applyMessage || '(메시지 없음)'}\n\n방장의 승인을 기다려주세요.`, () => {
                              setSelectedPost(null);
                              setApplyMessage('');
                            });
                          });
                        };

                        if (!applyMessage.trim()) {
                          showConfirm('알림', '메시지 없이 신청하시겠습니까? (방장이 거절할 확률이 높아질 수 있습니다)', processApplication);
                        } else {
                          processApplication();
                        }
                      } else {
                        showConfirm('바로 참여', `'${selectedPost.title}' 스터디에 바로 참여하시겠습니까?`, () => {
                          setAppliedStudies(prev => [...prev, `recruit_${selectedPost.id}`]);
                          setSelectedPost(null);
                          setPreJoinStudy(selectedPost);
                        });
                      }
                    }}
                  >
                    {selectedPost.isPrivate ? '신청하기' : '바로 참여하기'}
                  </button>
                </div>

              </div>
            </div>
          )}

          {/* 모집글 작성 모달 */}
          {isWriteModalOpen && (
            <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: '20px' }} onClick={() => setIsWriteModalOpen(false)}>
              <div style={{ backgroundColor: 'white', borderRadius: '12px', width: '100%', maxWidth: '500px', overflow: 'hidden', boxShadow: '0 25px 50px -12px rgba(0,0,0,0.25)', display: 'flex', flexDirection: 'column', animation: 'slideUp 0.3s ease-out' }} onClick={(e) => e.stopPropagation()}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '20px 24px', borderBottom: '1px solid #E5E7EB' }}>
                  <h2 style={{ margin: 0, fontSize: '18px', fontWeight: '700', color: '#111827' }}>모집글 작성</h2>
                  <button onClick={() => setIsWriteModalOpen(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6B7280' }}>
                    <X size={20} />
                  </button>
                </div>

                <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '13px', fontWeight: '600', color: '#374151', marginBottom: '8px' }}>연결할 내 스터디 <span style={{ color: '#EF4444' }}>*</span></label>
                    <select
                      value={writeForm.studyId}
                      onChange={(e) => setWriteForm(prev => ({ ...prev, studyId: e.target.value }))}
                      style={{ width: '100%', padding: '10px 12px', borderRadius: '8px', border: '1px solid #D1D5DB', fontSize: '14px', outline: 'none', backgroundColor: '#fff', cursor: 'pointer' }}
                    >
                      <option value="">스터디를 선택해주세요</option>
                      {DUMMY_MY_STUDIES.map(study => (
                        <option key={study.id} value={study.id}>{study.title}</option>
                      ))}
                    </select>
                    <p style={{ margin: '6px 0 0', fontSize: '12px', color: '#6B7280' }}>내가 방장으로 있는 스터디 목록입니다.</p>
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '13px', fontWeight: '600', color: '#374151', marginBottom: '8px' }}>모집글 제목 <span style={{ color: '#EF4444' }}>*</span></label>
                    <input
                      type="text"
                      placeholder="예) [프론트엔드] 사이드 프로젝트 인원 구합니다"
                      value={writeForm.title}
                      onChange={(e) => setWriteForm(prev => ({ ...prev, title: e.target.value }))}
                      style={{ width: '100%', padding: '10px 12px', borderRadius: '8px', border: '1px solid #D1D5DB', fontSize: '14px', outline: 'none', boxSizing: 'border-box' }}
                    />
                  </div>

                  <div>
                    <label style={{ display: 'block', fontSize: '13px', fontWeight: '600', color: '#374151', marginBottom: '8px' }}>모집 상세 내용 <span style={{ color: '#EF4444' }}>*</span></label>
                    <textarea
                      placeholder="모집 대상, 진행 방식, 필수 조건 등을 상세하게 적어주세요."
                      value={writeForm.content}
                      onChange={(e) => setWriteForm(prev => ({ ...prev, content: e.target.value }))}
                      style={{ width: '100%', height: '140px', padding: '12px', borderRadius: '8px', border: '1px solid #D1D5DB', fontSize: '14px', resize: 'none', outline: 'none', fontFamily: 'inherit', boxSizing: 'border-box' }}
                    />
                  </div>
                </div>

                <div style={{ padding: '16px 24px', backgroundColor: '#F9FAFB', borderTop: '1px solid #E5E7EB', display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
                  <button
                    onClick={() => setIsWriteModalOpen(false)}
                    style={{ padding: '10px 16px', borderRadius: '8px', border: '1px solid #D1D5DB', backgroundColor: '#fff', color: '#374151', fontSize: '14px', fontWeight: '500', cursor: 'pointer' }}
                  >
                    취소
                  </button>
                  <button
                    onClick={() => {
                      if (!writeForm.studyId || !writeForm.title || !writeForm.content) {
                        showAlert('알림', '모든 필수 항목을 입력해주세요.');
                        return;
                      }
                      const selectedStudy = DUMMY_MY_STUDIES.find(s => s.id === parseInt(writeForm.studyId));
                      const newPost = {
                        id: Date.now(),
                        isPrivate: selectedStudy.title.includes('빡공') || selectedStudy.title.includes('토플') ? true : false, // 임의 지정
                        title: writeForm.title,
                        author: '나(방장)',
                        date: new Date().toISOString().split('T')[0],
                        status: 'RECRUITING',
                        current: 1,
                        max: 4,
                        views: 0,
                        content: writeForm.content
                      };
                      setRecruitments(prev => [newPost, ...prev]);
                      showAlert('성공', `'${selectedStudy.title}' 스터디의 모집글이 등록되었습니다!`, () => {
                        setIsWriteModalOpen(false);
                        setWriteForm({ studyId: '', title: '', content: '' });
                      });
                    }}
                    style={{ padding: '10px 24px', borderRadius: '8px', border: 'none', backgroundColor: '#10B981', color: '#fff', fontSize: '14px', fontWeight: '600', cursor: 'pointer' }}
                  >
                    등록하기
                  </button>
                </div>
              </div>
            </div>
          )}
          {/* 프리조인(입장 준비) 모달 */}
          {preJoinStudy && (
            <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: '#F9FAFB', zIndex: 9999, display: 'flex', flexDirection: 'column', animation: 'fadeIn 0.2s ease-out' }}>
              {/* Header */}
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '16px 24px', backgroundColor: 'white', borderBottom: '1px solid #E5E7EB', boxShadow: '0 1px 2px rgba(0,0,0,0.05)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  <div style={{ width: '40px', height: '40px', borderRadius: '8px', overflow: 'hidden' }}>
                    <img src={preJoinStudy.thumbnailUrl} alt="thumbnail" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                  </div>
                  <h2 style={{ margin: 0, fontSize: '18px', fontWeight: '700', color: '#111827' }}>{preJoinStudy.title} <span style={{ fontWeight: '500', color: '#6B7280', fontSize: '15px', marginLeft: '8px' }}>입장 준비</span></h2>
                </div>
                <button onClick={() => setPreJoinStudy(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6B7280', padding: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: '50%', transition: 'background-color 0.2s' }} onMouseEnter={(e) => e.currentTarget.style.backgroundColor = '#F3F4F6'} onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}>
                  <X size={24} />
                </button>
              </div>

              {/* Body */}
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '20px', gap: '32px', overflowY: 'auto' }}>

                <div style={{ textAlign: 'center' }}>
                  <h1 style={{ margin: '0 0 12px', fontSize: '24px', fontWeight: '700', color: '#111827' }}>스터디룸에 입장하기 전에 내 화면을 마음대로 꾸며보세요.</h1>
                  <p style={{ margin: 0, fontSize: '15px', color: '#6B7280' }}>지금 보이는 영상은 다른 사람이 볼 수 없습니다.</p>
                </div>

                {/* Video Box */}
                <div style={{ width: '100%', maxWidth: '800px', backgroundColor: 'black', borderRadius: '16px', overflow: 'hidden', boxShadow: '0 25px 50px -12px rgba(0,0,0,0.3)', display: 'flex', flexDirection: 'column' }}>
                  <div style={{ position: 'relative', width: '100%', paddingTop: '56.25%', display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: isVideoOn ? '#1F2937' : 'black' }}>
                    {!isVideoOn ? (
                      <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px', color: '#4B5563' }}>
                        <div style={{ width: '80px', height: '80px', borderRadius: '50%', backgroundColor: '#374151', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                          <User size={40} color="#9CA3AF" />
                        </div>
                      </div>
                    ) : (
                      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundImage: 'url(https://images.unsplash.com/photo-1573496359142-b8d87734a5a2?ixlib=rb-4.0.3&auto=format&fit=crop&w=800&q=80)', backgroundSize: 'cover', backgroundPosition: 'center', opacity: 0.8 }}>
                        {/* 가상 카메라 화면 예시 */}
                      </div>
                    )}


                    {/* 장치 설정 패널 (토글) - 비디오 영역 위에 오버레이 */}
                    {showPreJoinSettings && (
                      <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, backgroundColor: '#F9FAFB', borderTop: '1px solid #E5E7EB', display: 'flex', padding: '24px', zIndex: 20 }}>
                        {/* Camera */}
                        <div style={{ flex: 1, padding: '0 16px', borderRight: '1px solid #E5E7EB' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#4B5563', marginBottom: '12px' }}>
                            <Video size={16} /> <span style={{ fontSize: '14px', fontWeight: '600' }}>카메라</span>
                          </div>
                          <div style={{ position: 'relative', marginBottom: '8px' }}>
                            <select style={{ width: '100%', appearance: 'none', border: 'none', backgroundColor: 'transparent', fontSize: '15px', color: '#111827', cursor: 'pointer', outline: 'none' }}>
                              <option>camera1</option>
                            </select>
                            <div style={{ position: 'absolute', right: 0, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }}>▼</div>
                          </div>
                          <div style={{ fontSize: '12px', color: '#9CA3AF' }}>정상적으로 작동중입니다</div>
                        </div>
                        {/* Mic */}
                        <div style={{ flex: 1, padding: '0 16px', borderRight: '1px solid #E5E7EB' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#4B5563', marginBottom: '12px' }}>
                            <Mic size={16} /> <span style={{ fontSize: '14px', fontWeight: '600' }}>마이크</span>
                          </div>
                          <div style={{ position: 'relative', marginBottom: '8px' }}>
                            <select style={{ width: '100%', appearance: 'none', border: 'none', backgroundColor: 'transparent', fontSize: '15px', color: '#111827', cursor: 'pointer', outline: 'none' }}>
                              <option>기본 마이크</option>
                            </select>
                            <div style={{ position: 'absolute', right: 0, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }}>▼</div>
                          </div>
                          <div style={{ fontSize: '12px', color: '#EF4444' }}>연결된 장치를 찾을 수 없습니다</div>
                        </div>
                        {/* Speaker */}
                        <div style={{ flex: 1, padding: '0 16px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#4B5563', marginBottom: '12px' }}>
                            <Volume2 size={16} /> <span style={{ fontSize: '14px', fontWeight: '600' }}>스피커</span>
                          </div>
                          <div style={{ position: 'relative', marginBottom: '8px' }}>
                            <select style={{ width: '100%', appearance: 'none', border: 'none', backgroundColor: 'transparent', fontSize: '15px', color: '#111827', cursor: 'pointer', outline: 'none' }}>
                              <option>default</option>
                            </select>
                            <div style={{ position: 'absolute', right: 0, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }}>▼</div>
                          </div>
                          <div style={{ fontSize: '12px', color: '#9CA3AF' }}>정상적으로 작동중입니다</div>
                        </div>
                      </div>
                    )}
                  </div>

                  {/* Bottom Device Controls */}
                  <div style={{ display: 'flex', justifyContent: 'space-around', alignItems: 'center', padding: '16px', backgroundColor: 'white', borderTop: '1px solid #E5E7EB' }}>
                    <button
                      style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px', background: 'none', border: 'none', cursor: 'pointer', color: showPreJoinInfo ? '#3B82F6' : '#6B7280', flex: 1 }}
                      onClick={() => setShowPreJoinInfo(true)}
                    >
                      <AlertTriangle size={24} />
                      <span style={{ fontSize: '12px', fontWeight: '500' }}>정보</span>
                    </button>
                    <button
                      style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px', background: 'none', border: 'none', cursor: 'pointer', color: showPreJoinSettings ? '#3B82F6' : '#6B7280', flex: 1 }}
                      onClick={() => setShowPreJoinSettings(!showPreJoinSettings)}
                    >
                      <Settings size={24} />
                      <span style={{ fontSize: '12px', fontWeight: '500' }}>장치 설정</span>
                    </button>
                  </div>
                </div>

                <button
                  style={{ padding: '16px 80px', borderRadius: '8px', backgroundColor: preJoinStudy.isPrivate ? '#8B5CF6' : '#3B82F6', color: 'white', fontSize: '18px', fontWeight: '700', border: 'none', cursor: 'pointer', boxShadow: preJoinStudy.isPrivate ? '0 4px 12px rgba(139, 92, 246, 0.3)' : '0 4px 12px rgba(59, 130, 246, 0.3)', transition: 'background-color 0.2s', display: 'flex', alignItems: 'center', gap: '8px' }}
                  onMouseEnter={(e) => e.currentTarget.style.backgroundColor = preJoinStudy.isPrivate ? '#7C3AED' : '#2563EB'}
                  onMouseLeave={(e) => e.currentTarget.style.backgroundColor = preJoinStudy.isPrivate ? '#8B5CF6' : '#3B82F6'}
                  onClick={() => {
                    showAlert('입장', `[${preJoinStudy.title}] 스터디룸으로 입장합니다!`, () => {
                      setActiveStudyRoom(preJoinStudy);
                      setPreJoinStudy(null);
                    });
                  }}
                >
                  <div style={{ width: '16px', height: '20px', border: '2px solid white', borderRight: 'none', borderTopLeftRadius: '4px', borderBottomLeftRadius: '4px', position: 'relative' }}>
                    <div style={{ position: 'absolute', right: '-2px', top: '50%', transform: 'translateY(-50%)', width: '4px', height: '12px', backgroundColor: 'white' }}></div>
                  </div>
                  입장
                </button>
              </div>
            </div>
          )}

          {/* 프리조인 "정보" 모달 */}
          {showPreJoinInfo && preJoinStudy && (
            <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 10000, padding: '20px' }} onClick={() => setShowPreJoinInfo(false)}>
              <div style={{ backgroundColor: 'white', borderRadius: '12px', width: '100%', maxWidth: '420px', overflow: 'hidden', display: 'flex', flexDirection: 'column', animation: 'slideUp 0.3s ease-out' }} onClick={(e) => e.stopPropagation()}>
                <div style={{ padding: '24px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '24px', paddingBottom: '24px', borderBottom: '1px solid #E5E7EB' }}>
                    <div>
                      <div style={{ fontSize: '13px', color: '#6B7280', marginBottom: '6px' }}>스터디 정원</div>
                      <div style={{ fontSize: '15px', fontWeight: '700', color: '#111827' }}>{preJoinStudy.maxMembers} 명</div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontSize: '13px', color: '#6B7280', marginBottom: '6px', display: 'flex', alignItems: 'center', justifyContent: 'flex-end' }}>스터디 기간 <span style={{ backgroundColor: '#FEF3C7', color: '#D97706', padding: '2px 6px', borderRadius: '4px', fontSize: '11px', fontWeight: '700', marginLeft: '4px' }}>D-308</span></div>
                      <div style={{ fontSize: '15px', fontWeight: '700', color: '#111827' }}>2021.11.22 - 2027.04.06</div>
                    </div>
                  </div>

                  <div style={{ marginBottom: '24px' }}>
                    <div style={{ fontSize: '14px', color: '#6B7280', marginBottom: '16px' }}>스터디 공지사항</div>
                    <div style={{ fontSize: '14px', color: '#374151', lineHeight: '1.6', wordBreak: 'keep-all' }}>
                      {preJoinStudy.description}
                      <br /><br />
                      해당 스터디룸은 StudyBridge에서 개설한 화상 스터디룸으로,<br />
                      입장한 지 3일 이상 경과된 상황에서 카메라 송출이 되고 있지 않는다면 발견되는 즉시 무통보 강제 퇴장 조치를 진행할 수 있습니다.
                    </div>
                  </div>

                  <div style={{ backgroundColor: '#F9FAFB', borderRadius: '8px', padding: '16px', border: '1px solid #F3F4F6' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#DC2626', fontWeight: '700', fontSize: '13px', marginBottom: '8px' }}>
                      <AlertTriangle size={16} /> 불량(음란) 사용자 신고 안내
                    </div>
                    <p style={{ margin: 0, fontSize: '12px', color: '#DC2626', lineHeight: '1.5' }}>
                      신고 접수된 사용자는 화상 스터디 운영정책에 따라 스터디 입장이 제한됩니다. 허위로 신고 시 서비스 사용이 제한될 수 있으니 주의해 주세요.
                      <br />
                      <a href="#" style={{ color: '#6B7280', textDecoration: 'underline', marginTop: '8px', display: 'inline-block' }}>자세히 보기</a>
                    </p>
                  </div>
                </div>

                <button
                  style={{ width: '100%', padding: '16px', fontSize: '15px', fontWeight: '600', color: 'white', backgroundColor: '#3B82F6', border: 'none', cursor: 'pointer', transition: 'background-color 0.2s' }}
                  onMouseEnter={(e) => e.currentTarget.style.backgroundColor = '#2563EB'}
                  onMouseLeave={(e) => e.currentTarget.style.backgroundColor = '#3B82F6'}
                  onClick={() => setShowPreJoinInfo(false)}
                >
                  확인
                </button>
              </div>
            </div>
          )}


          {/* 화상 스터디 본방 */}
          {activeStudyRoom && (
            <StudyRoom
              study={activeStudyRoom}
              onClose={() => setActiveStudyRoom(null)}
            />
          )}
        </>
      )}

      {/* 이미지 등록 모달 */}
      {showImageSelectModal && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.5)', zIndex: 100000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ backgroundColor: 'white', borderRadius: '16px', width: '500px', overflow: 'hidden', display: 'flex', flexDirection: 'column', boxShadow: '0 20px 40px rgba(0,0,0,0.2)' }}>

            <div style={{ padding: '20px', display: 'flex', justifyContent: 'center', position: 'relative', borderBottom: '1px solid #E5E7EB' }}>
              <h3 style={{ margin: 0, fontSize: '18px', fontWeight: '700', color: '#111827' }}>이미지 등록</h3>
              <div
                style={{ position: 'absolute', right: '20px', top: '20px', cursor: 'pointer' }}
                onClick={() => setShowImageSelectModal(false)}
              >
                <X size={20} color="#6B7280" />
              </div>
            </div>

            <div style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
              {/* Preview */}
              <div style={{ width: '100%', height: '260px', borderRadius: '12px', backgroundImage: `url(${createForm.thumbnail})`, backgroundSize: 'cover', backgroundPosition: 'center', border: '1px solid #E5E7EB' }} />

              {/* Selectors */}
              <div style={{ display: 'flex', gap: '12px', justifyContent: 'space-between' }}>
                {['https://images.unsplash.com/photo-1517842645767-c639042777db?ixlib=rb-4.0.3&auto=format&fit=crop&w=400&q=80', 'https://images.unsplash.com/photo-1434030216411-0b793f4b4173?ixlib=rb-4.0.3&auto=format&fit=crop&w=400&q=80', 'https://images.unsplash.com/photo-1519389950473-47ba0277781c?ixlib=rb-4.0.3&auto=format&fit=crop&w=400&q=80'].map((url, idx) => (
                  <div
                    key={idx}
                    style={{ flex: 1, height: '80px', borderRadius: '8px', backgroundImage: `url(${url})`, backgroundSize: 'cover', backgroundPosition: 'center', cursor: 'pointer', position: 'relative', border: createForm.thumbnail === url ? '2px solid #3B82F6' : '1px solid #E5E7EB', overflow: 'hidden' }}
                    onClick={() => setCreateForm({ ...createForm, thumbnail: url })}
                  >
                    {createForm.thumbnail === url && (
                      <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(59,130,246,0.3)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                        <Check size={24} color="white" strokeWidth={3} />
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>

            <div style={{ display: 'flex', height: '56px' }}>
              <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: '#F3F4F6', color: '#6B7280', fontWeight: '600', cursor: 'pointer' }}>
                이미지 불러오기
              </div>
              <div
                style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: '#3B82F6', color: 'white', fontWeight: '600', cursor: 'pointer' }}
                onClick={() => setShowImageSelectModal(false)}
              >
                완료
              </div>
            </div>

          </div>
        </div>
      )}
      {/* 커스텀 알림 모달 */}
      {customAlert.isOpen && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, zIndex: 100000, display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(0,0,0,0.4)', backdropFilter: 'blur(2px)' }}>
          <div style={{ backgroundColor: '#ffffff', borderRadius: '12px', padding: '24px 24px 20px', width: '320px', boxShadow: '0 4px 20px rgba(0,0,0,0.15)', animation: 'fadeIn 0.2s ease-out' }}>
            <h3 style={{ margin: '0 0 12px 0', fontSize: '16px', fontWeight: '700', color: '#111827', textAlign: 'center' }}>{customAlert.title || '알림'}</h3>
            <p style={{ margin: '0 0 24px 0', fontSize: '14px', color: '#4B5563', lineHeight: '1.5', whiteSpace: 'pre-wrap', textAlign: 'center' }}>{customAlert.message}</p>
            <div style={{ display: 'flex', justifyContent: 'center', gap: '8px' }}>
              {customAlert.type === 'confirm' && (
                <button
                  style={{ flex: 1, padding: '10px 0', backgroundColor: '#F3F4F6', color: '#4B5563', border: '1px solid #E5E7EB', borderRadius: '8px', cursor: 'pointer', fontWeight: '600', fontSize: '14px' }}
                  onClick={customAlert.onCancel}
                >
                  취소
                </button>
              )}
              <button
                style={{ flex: 1, padding: '10px 0', backgroundColor: '#22C55E', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: '600', fontSize: '14px' }}
                onClick={customAlert.onConfirm}
              >
                확인
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
