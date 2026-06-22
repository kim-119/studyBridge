import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Users, Plus, Search, User, Lock, Globe, Filter, ClipboardList, X, AlertTriangle, CheckCircle2, Video, VideoOff, Mic, MicOff, Settings, Volume2, Camera, Check, ArrowLeft, Shield } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import { groupService } from '../services/api';
import StudyRoom from '../components/StudyRoom';

// 대표 이미지 전용 검증 — 학습 자료(문서 PDF/DOCX/TXT) validator 와 완전히 분리한다.
// 허용: image/jpeg, image/png, image/webp (확장자 fallback 포함), 최대 5MB. 통과 시 null, 실패 시 에러 문구 반환.
const COVER_IMAGE_MIME_TYPES = new Set(['image/jpeg', 'image/png', 'image/webp']);
const COVER_IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.webp'];
const validateCoverImageFile = (file) => {
  const name = (file?.name || '').toLowerCase();
  const validMime = COVER_IMAGE_MIME_TYPES.has(file?.type);
  const validExt = COVER_IMAGE_EXTENSIONS.some((ext) => name.endsWith(ext));
  if (!validMime && !validExt) {
    return '대표 이미지는 JPG, PNG, WEBP 파일만 업로드할 수 있습니다.';
  }
  if (file.size > 5 * 1024 * 1024) {
    return '대표 이미지는 5MB 이하만 업로드할 수 있습니다.';
  }
  return null;
};

// getUserMedia 장치 오류를 원인별로 구분해 사용자 메시지로 변환한다.
const friendlyDeviceMessage = (err) => {
  switch (err?.name) {
    case 'NotAllowedError':
    case 'PermissionDeniedError':
      return '브라우저 주소창의 카메라/마이크 권한을 허용해주세요.';
    case 'NotReadableError':
    case 'TrackStartError':
      return '다른 화상 앱 또는 브라우저 탭에서 카메라를 사용 중인지 확인해주세요.';
    case 'OverconstrainedError':
    case 'ConstraintNotSatisfiedError':
      return '선택한 카메라를 사용할 수 없어 기본 카메라로 다시 시도합니다.';
    case 'NotFoundError':
    case 'DevicesNotFoundError':
      return '사용 가능한 카메라를 찾을 수 없습니다. 오디오/시청 모드로 입장할 수 있습니다.';
    default:
      return err?.message || '카메라를 불러오지 못했습니다.';
  }
};

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
  const { userId, user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [studies, setStudies] = useState([]);
  const [recruitments, setRecruitments] = useState([]);
  const [myStudies, setMyStudies] = useState([]);
  const [appliedStudies, setAppliedStudies] = useState([]);
  const [filter, setFilter] = useState('PUBLIC'); // 'PUBLIC', 'PRIVATE'
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
    capacity: 10,
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
  const [showLeaderConsole, setShowLeaderConsole] = useState(false);
  const [preJoinMembers, setPreJoinMembers] = useState([]);
  const [loadingMembers, setLoadingMembers] = useState(false);

  // 커스텀 알림/컨펌 모달 상태
  const [customAlert, setCustomAlert] = useState({
    isOpen: false,
    title: '',
    message: '',
    type: 'alert',
    onConfirm: null,
    onCancel: null,
  });

  const videoRef = React.useRef(null);
  const [camError, setCamError] = useState('');
  // 카메라/마이크 감지 단계. 'checking'을 먼저 보여주고, 권한·retry가 끝난 뒤에만 실패로 확정한다.
  //  cameraStatus: 'idle' | 'checking' | 'available' | 'unavailable' | 'error' | 'off'
  //  micStatus:    'idle' | 'checking' | 'available' | 'unavailable' | 'error' | 'off'
  const [cameraStatus, setCameraStatus] = useState('idle');
  const [micStatus, setMicStatus] = useState('idle');
  const [micLevel, setMicLevel] = useState(0);

  const [cameras, setCameras] = useState([]);
  const [mics, setMics] = useState([]);
  const [selectedCamera, setSelectedCamera] = useState('');
  // 열리지 않는(stale/고장) 카메라 deviceId를 기억해 무한 재시도/재선택 루프를 방지한다.
  const badCamerasRef = React.useRef(new Set());

  // 권한을 얻은 후 장치 목록을 가져오는 함수
  const fetchDevices = async () => {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return;
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const videoInputs = devices.filter(device => device.kind === 'videoinput');
      const audioInputs = devices.filter(device => device.kind === 'audioinput');
      setCameras(videoInputs);
      setMics(audioInputs);

      // 선택된 카메라가 목록에 더 이상 없으면 stale → 초기화
      if (selectedCamera && !videoInputs.some(v => v.deviceId === selectedCamera)) {
        setSelectedCamera('');
        return;
      }
      // 선택 카메라가 없거나 고장난 카메라면, 정상으로 알려진 카메라를 자동 선택
      if ((!selectedCamera || badCamerasRef.current.has(selectedCamera)) && videoInputs.length > 0) {
        const good = videoInputs.find(v => v.deviceId && !badCamerasRef.current.has(v.deviceId));
        if (good) setSelectedCamera(good.deviceId);
      }
    } catch (err) {
      console.error("장치 목록을 가져오는데 실패했습니다.", err);
    }
  };

  useEffect(() => {
    let stream = null;
    let isMounted = true;
    let retryTimer = null;

    if (!preJoinStudy) {
      return undefined;
    }
    if (!isVideoOn) {
      setCameraStatus('off');
      setCamError('');
      return undefined;
    }

    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setCameraStatus('error');
      setCamError('브라우저가 카메라 API를 지원하지 않습니다 (HTTPS 또는 localhost 필요).');
      return undefined;
    }

    // 입장 직후 곧바로 "카메라 없음"으로 표시하지 않고, 먼저 확인 중 상태를 보여준다.
    setCameraStatus('checking');
    setCamError('');

    // 장치가 늦게 잡히거나(약 10초 지연) 직전 화면이 카메라를 늦게 릴리즈하는 경우를 위해
    // 일시적 오류(NotReadable/NotFound 등)는 곧바로 실패로 확정하지 않고 backoff로 최대 3회 재시도한다.
    const attempt = async (tryNo) => {
      const constraints = {
        video: selectedCamera ? { deviceId: { exact: selectedCamera } } : true,
        audio: false
      };
      try {
        const s = await navigator.mediaDevices.getUserMedia(constraints);
        if (!isMounted) {
          s.getTracks().forEach(t => t.stop());
          return;
        }
        stream = s;
        if (videoRef.current) {
          videoRef.current.srcObject = s;
        }
        setCamError('');
        setCameraStatus('available');
        // 스트림 획득(권한 허용) 성공 후 장치 목록 갱신 (label을 읽어오기 위함)
        fetchDevices();
      } catch (err) {
        if (!isMounted) return;
        console.error("카메라 에러:", err?.name, err?.message, 'try', tryNo);

        // 선택한 카메라가 stale/제약 불일치면 해당 장치를 불량으로 표시하고 기본 카메라로 자동 재시도
        if ((err.name === 'OverconstrainedError' || err.name === 'ConstraintNotSatisfiedError') && selectedCamera) {
          badCamerasRef.current.add(selectedCamera);
          setSelectedCamera(''); // effect 재실행 → video:true(기본 장치)로 재시도
          return;
        }

        // 권한 거부는 재시도해도 의미 없음 → 즉시 error 확정
        if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') {
          setCameraStatus('error');
          setCamError(friendlyDeviceMessage(err));
          fetchDevices();
          return;
        }

        // 일시적으로 장치가 안 잡히는 경우 → backoff 재시도
        const retriable = ['NotReadableError', 'TrackStartError', 'NotFoundError', 'DevicesNotFoundError', 'AbortError'].includes(err.name);
        if (retriable && tryNo < 3) {
          setCameraStatus('checking');
          retryTimer = setTimeout(() => { if (isMounted) attempt(tryNo + 1); }, 700 * tryNo);
          return;
        }

        // 재시도까지 끝난 최종 실패
        setCameraStatus((err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') ? 'unavailable' : 'error');
        setCamError(friendlyDeviceMessage(err));
        // 권한은 있으나 비디오만 실패한 경우라도 마이크 목록은 보여줄 수 있게 시도
        fetchDevices();
      }
    };

    attempt(1);

    return () => {
      isMounted = false;
      if (retryTimer) clearTimeout(retryTimer);
      if (stream) {
        stream.getTracks().forEach(track => track.stop());
      }
    };
  }, [preJoinStudy, isVideoOn, selectedCamera]);

  // 입장 전 마이크 입력 미터 — 마이크가 실제로 입력을 받는지(말하면 레벨이 오르는지) 보여준다.
  useEffect(() => {
    if (!preJoinStudy || !isMicOn) {
      setMicStatus(isMicOn ? 'checking' : 'off');
      setMicLevel(0);
      return undefined;
    }
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      setMicStatus('error');
      return undefined;
    }

    let micStream = null;
    let audioContext = null;
    let rafId = null;
    let cancelled = false;
    setMicStatus('checking');

    (async () => {
      try {
        micStream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
        if (cancelled) {
          micStream.getTracks().forEach(t => t.stop());
          return;
        }
        fetchDevices();
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const source = audioContext.createMediaStreamSource(micStream);
        const analyser = audioContext.createAnalyser();
        analyser.fftSize = 256;
        source.connect(analyser);
        const dataArray = new Uint8Array(analyser.frequencyBinCount);
        setMicStatus('available');

        const tick = () => {
          if (cancelled) return;
          analyser.getByteFrequencyData(dataArray);
          let sum = 0;
          for (let i = 0; i < dataArray.length; i++) sum += dataArray[i];
          const average = sum / dataArray.length;
          setMicLevel(Math.min(100, Math.round((average / 60) * 100)));
          rafId = requestAnimationFrame(tick);
        };
        tick();
      } catch (err) {
        if (cancelled) return;
        console.error('마이크 에러:', err?.name, err?.message);
        if (err.name === 'NotAllowedError' || err.name === 'PermissionDeniedError') setMicStatus('error');
        else if (err.name === 'NotFoundError' || err.name === 'DevicesNotFoundError') setMicStatus('unavailable');
        else setMicStatus('error');
        setMicLevel(0);
      }
    })();

    return () => {
      cancelled = true;
      if (rafId) cancelAnimationFrame(rafId);
      if (audioContext && audioContext.state !== 'closed') audioContext.close();
      if (micStream) micStream.getTracks().forEach(t => t.stop());
    };
  }, [preJoinStudy, isMicOn]);

  // 장치 핫플러그(연결/해제) 감지 시 목록을 갱신한다.
  useEffect(() => {
    if (!navigator.mediaDevices || !navigator.mediaDevices.addEventListener) return;
    const onDeviceChange = () => fetchDevices();
    navigator.mediaDevices.addEventListener('devicechange', onDeviceChange);
    return () => {
      navigator.mediaDevices.removeEventListener('devicechange', onDeviceChange);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

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

  const loadGroups = async () => {
    try {
      const data = await groupService.getGroups();
      
      const normalized = data.map(group => {
        let tags = ['자율', '캠스터디'];
        if (group.hashtags) {
          tags = group.hashtags.split(/[\s,#]+/).map(s => s.trim()).filter(Boolean);
        }
        return {
          id: group.id,
          title: group.title,
          description: group.description || '스터디 설명이 없습니다.',
          content: group.description || '스터디 설명이 없습니다.',
          hashtags: group.hashtags || '',
          tags: tags,
          currentMembers: group.currentCount || 1,
          maxMembers: group.capacity || 10,
          current: group.currentCount || 1,
          max: group.capacity || 10,
          leader: group.leaderName || '방장',
          author: group.leaderName || '방장',
          leaderId: group.leaderId,
          leaderPhotoUrl: group.leaderPhotoUrl,
          status: group.status, // 'RECRUITING', 'ACTIVE', 'COMPLETED'
          isPrivate: !group.isPublic,
          thumbnailUrl: group.coverImageUrl || 'https://images.unsplash.com/photo-1517842645767-c639042777db?ixlib=rb-4.0.3&auto=format&fit=crop&w=800&q=80',
          startDate: group.startDate,
          endDate: group.endDate,
          createdAt: group.createdAt,
          date: group.createdAt ? group.createdAt.split('T')[0] : (group.startDate || new Date().toISOString().split('T')[0])
        };
      });

      // Sort by id desc
      normalized.sort((a, b) => b.id - a.id);

      setStudies(normalized.filter(g => g.status === 'ACTIVE' || g.status === 'RECRUITING'));
      
      // myStudies: groups where I am the leader
      if (userId) {
        setMyStudies(normalized.filter(g => Number(g.leaderId) === Number(userId)));
      }
    } catch (err) {
      console.error('Failed to load group studies', err);
    }
  };

  useEffect(() => {
    loadGroups();
  }, [userId]);

  useEffect(() => {
    if (preJoinStudy && userId) {
      setLoadingMembers(true);
      groupService.getMembers(preJoinStudy.id)
        .then(members => {
          setPreJoinMembers(members);
        })
        .catch(err => {
          console.error('Failed to load group members', err);
        })
        .finally(() => {
          setLoadingMembers(false);
        });
    } else {
      setPreJoinMembers([]);
    }
  }, [preJoinStudy, userId]);

  const [applications, setApplications] = useState([]);
  const [loadingApps, setLoadingApps] = useState(false);

  const loadApplications = async (groupId) => {
    setLoadingApps(true);
    try {
      const data = await groupService.getApplications(groupId);
      setApplications((data || []).filter(app => app.status === 'WAITING'));
    } catch (err) {
      console.error('Failed to load applications', err);
    } finally {
      setLoadingApps(false);
    }
  };

  useEffect(() => {
    if (preJoinStudy && Number(preJoinStudy.leaderId) === Number(userId)) {
      loadApplications(preJoinStudy.id);
    }
  }, [preJoinStudy, userId]);

  const handleApproveApp = async (appId) => {
    try {
      await groupService.approveApplication(appId);
      showAlert('성공', '가입 신청을 승인했습니다.');
      if (preJoinStudy) {
        loadApplications(preJoinStudy.id);
        loadGroups();
      }
    } catch (err) {
      showAlert('오류', err.response?.data?.message || '승인 처리에 실패했습니다.');
    }
  };

  const handleRejectApp = async (appId) => {
    try {
      await groupService.rejectApplication(appId);
      showAlert('성공', '가입 신청을 거절했습니다.');
      if (preJoinStudy) {
        loadApplications(preJoinStudy.id);
        loadGroups();
      }
    } catch (err) {
      showAlert('오류', err.response?.data?.message || '거절 처리에 실패했습니다.');
    }
  };



  const handleDeleteStudy = async () => {
    if (!preJoinStudy) return;
    showConfirm('스터디 해체', '정말로 이 스터디 그룹을 해체하시겠습니까? 해체 시 다시 복구할 수 없습니다.', async () => {
      try {
        await groupService.deleteGroup(preJoinStudy.id);
        showAlert('성공', '스터디 그룹이 해체(삭제)되었습니다.');
        setPreJoinStudy(null);
        loadGroups();
      } catch (err) {
        showAlert('오류', err.response?.data?.message || '스터디 해체에 실패했습니다.');
      }
    });
  };

  const handleCardClick = async (study) => {
    if (!checkAuth()) return;
    
    let isAlreadyJoined = false;
    if (Number(study.leaderId) === Number(userId)) {
      isAlreadyJoined = true;
    } else {
      try {
        const members = await groupService.getMembers(study.id);
        if (members.some(m => Number(m.userId) === Number(userId))) {
          isAlreadyJoined = true;
        }
      } catch (err) {
        console.warn("Failed to check group membership in handleCardClick", err);
      }
    }
    
    setSelectedPost({ ...study, isAlreadyJoined });
  };

  useEffect(() => {
    const searchParams = new URLSearchParams(location.search);
    const openModalId = searchParams.get('openModal');
    
    if (openModalId && studies.length > 0) {
      const study = studies.find(s => String(s.id) === String(openModalId));
      if (study && (!selectedPost || String(selectedPost.id) !== String(openModalId))) {
        handleCardClick(study);
        // Prevent re-triggering by removing the query param
        navigate(location.pathname, { replace: true });
      }
    }
  }, [location.search, studies, navigate, selectedPost]);

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

          {/* 스터디 정원 */}
          <div style={{ display: 'flex', gap: '24px' }}>
            <div style={{ width: '120px', fontWeight: '600', color: '#374151', display: 'flex', alignItems: 'center' }}>
              스터디 정원 <span style={{ color: '#EF4444', marginLeft: '4px' }}>*</span>
            </div>
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <input
                  type="number"
                  min={2}
                  max={10}
                  placeholder="최대 참여 인원을 입력하세요"
                  value={createForm.capacity}
                  onChange={(e) => setCreateForm({ ...createForm, capacity: e.target.value })}
                  style={{ width: '200px', padding: '12px 16px', borderRadius: '8px', border: '1px solid #D1D5DB', fontSize: '15px', outline: 'none', color: '#374151' }}
                />
                <span style={{ color: '#6B7280', fontSize: '15px' }}>명</span>
              </div>
              <div style={{ color: '#9CA3AF', fontSize: '13px' }}>
                최소 2명 ~ 최대 10명 (화상통화 안정 성능 보장)
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
              onClick={async () => {
                if (!createForm.title || !createForm.description) {
                  showAlert('알림', '스터디 이름과 공지사항은 필수 항목입니다.');
                  return;
                }
                const cap = parseInt(createForm.capacity, 10);
                if (!cap || cap < 2) {
                  showAlert('알림', '스터디 정원은 최소 2명 이상이어야 합니다.');
                  return;
                }
                if (cap > 10) {
                  showAlert('알림', '스터디 정원은 최대 10명까지 설정할 수 있습니다.');
                  return;
                }
                try {
                  const payload = {
                    title: createForm.title,
                    hashtags: createForm.tags || '',
                    description: createForm.description,
                    startDate: createForm.startDate,
                    endDate: createForm.endDate,
                    capacity: cap,
                    isPublic: createForm.isPublic,
                    image: createForm.imageFile || null
                  };
                  await groupService.createGroup(payload);
                  showAlert('성공', '스터디가 성공적으로 개설되었습니다!', () => {
                    setIsCreateStudyMode(false);
                    setCreateForm({
                      title: '',
                      tags: '',
                      thumbnail: 'https://images.unsplash.com/photo-1517842645767-c639042777db?ixlib=rb-4.0.3&auto=format&fit=crop&w=800&q=80',
                      imageFile: null,
                      startDate: '2026-06-02',
                      endDate: '2026-09-02',
                      capacity: 10,
                      isPublic: true,
                      cameraOn: true,
                      description: ''
                    });
                    loadGroups();
                  });
                } catch (err) {
                  showAlert('오류', err.response?.data?.message || '스터디 개설에 실패했습니다.');
                }
              }}
            >
              + 스터디 만들기
            </button>
          </div>
        </div>
      ) : (
        <>
          {/* 필터 탭 */}
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '16px' }}>
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
                  setIsCreateStudyMode(true);
                }}
              >
                <Plus size={16} /> 스터디 만들기
              </button>
            </div>
            {/* 스터디 목록 그리드 */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: '24px', marginTop: '24px' }}>
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
                    onClick={() => handleCardClick(study)}
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
                          {study.leaderPhotoUrl ? (
                            <img
                              src={study.leaderPhotoUrl}
                              alt={study.leader}
                              style={{ width: '24px', height: '24px', borderRadius: '50%', objectFit: 'cover' }}
                            />
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
                            width: 'auto', flexShrink: 0,
                            height: '32px', padding: '0 16px', fontSize: '13px', fontWeight: '600', borderRadius: '8px', border: 'none',
                            backgroundColor: appliedStudies.includes(study.id) ? '#E5E7EB' : (Number(study.leaderId) === Number(userId) ? '#DCFCE7' : (study.isPrivate ? 'rgba(139, 92, 246, 0.1)' : '#EFF6FF')),
                            color: appliedStudies.includes(study.id) ? '#6B7280' : (Number(study.leaderId) === Number(userId) ? '#16A34A' : (study.isPrivate ? '#8B5CF6' : '#3B82F6')),
                            cursor: (study.status === 'CLOSED' && Number(study.leaderId) !== Number(userId) && !study.isPrivate || appliedStudies.includes(study.id)) ? 'not-allowed' : 'pointer',
                            opacity: (study.status === 'CLOSED' && Number(study.leaderId) !== Number(userId) && !study.isPrivate) ? 0.5 : 1
                          }}
                          disabled={study.status === 'CLOSED' && Number(study.leaderId) !== Number(userId) && !study.isPrivate || appliedStudies.includes(study.id)}
                          onClick={(e) => {
                            e.stopPropagation();
                            handleCardClick(study);
                          }}
                        >
                          {appliedStudies.includes(study.id) ? '신청완료' : (Number(study.leaderId) === Number(userId) ? '내 스터디' : (study.isPrivate ? '참여신청' : (study.status === 'CLOSED' ? '모집마감' : '참여하기')))}
                        </button>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>

          {/* 모집글 상세 모달 */}
          {selectedPost && (
            <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: '20px' }} onClick={() => { setSelectedPost(null); setApplyMessage(''); }}>
              <div style={{ backgroundColor: 'white', borderRadius: '12px', width: '100%', maxWidth: '420px', overflow: 'hidden', boxShadow: '0 25px 50px -12px rgba(0,0,0,0.25)', display: 'flex', flexDirection: 'column', animation: 'slideUp 0.3s ease-out' }} onClick={(e) => e.stopPropagation()}>

                {/* 상단 이미지 및 제목 영역 */}
                <div style={{ position: 'relative', height: '160px', backgroundColor: '#1F2937', color: 'white', display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', padding: '20px' }}>
                  <img src={selectedPost.thumbnailUrl || "https://images.unsplash.com/photo-1516321497487-e288fb19713f?ixlib=rb-4.0.3&auto=format&fit=crop&w=800&q=80"} alt="Background" style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', objectFit: 'cover', opacity: 0.3 }} />
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
                      {selectedPost.leaderPhotoUrl ? (
                        <img
                          src={selectedPost.leaderPhotoUrl}
                          alt={selectedPost.author}
                          style={{ width: '24px', height: '24px', borderRadius: '50%', objectFit: 'cover', boxShadow: '0 2px 4px rgba(0,0,0,0.3)' }}
                        />
                      ) : (
                        <div style={{ width: '24px', height: '24px', borderRadius: '50%', backgroundColor: 'var(--color-primary)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '12px', fontWeight: '700', boxShadow: '0 2px 4px rgba(0,0,0,0.3)' }}>
                          {selectedPost.author.charAt(0)}
                        </div>
                      )}
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

                  {selectedPost.isPrivate && !selectedPost.isAlreadyJoined && !appliedStudies.includes(selectedPost.id) && (
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
                {(() => {
                  // 정원 마감 여부: 이미 가입한 사용자는 입장 버튼을 그대로 노출한다.
                  const isFull = !selectedPost.isAlreadyJoined
                    && Number(selectedPost.currentMembers) >= Number(selectedPost.maxMembers);
                  return (
                <div style={{ backgroundColor: isFull ? '#9CA3AF' : '#3B82F6', padding: '0' }}>
                  <button
                    disabled={isFull}
                    style={{ width: '100%', padding: '16px', fontSize: '15px', fontWeight: '600', color: 'white', backgroundColor: 'transparent', border: 'none', cursor: isFull ? 'not-allowed' : 'pointer', transition: 'background-color 0.2s' }}
                    onMouseEnter={(e) => { if (!isFull) e.currentTarget.style.backgroundColor = '#2563EB'; }}
                    onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
                    onClick={async () => {
                      if (!checkAuth()) return;

                      // 1. 이미 리더이거나 가입 완료된 회원인지 체크
                      const isMeLeader = Number(selectedPost.leaderId) === Number(userId);
                      let isAlreadyJoined = isMeLeader;

                      try {
                        const members = await groupService.getMembers(selectedPost.id);
                        if (members.some(m => Number(m.userId) === Number(userId))) {
                          isAlreadyJoined = true;
                        }
                      } catch (e) {
                        console.warn("Failed to check group membership", e);
                      }

                      if (isAlreadyJoined) {
                        setSelectedPost(null);
                        setPreJoinStudy(selectedPost);
                        return;
                      }

                      if (appliedStudies.includes(selectedPost.id)) {
                        showAlert('알림', '이미 신청한 스터디입니다.');
                        return;
                      }
                      if (selectedPost.status === 'CLOSED' || selectedPost.currentMembers >= selectedPost.maxMembers) {
                        showAlert('알림', '마감되었거나 정원이 가득 찬 스터디입니다.');
                        return;
                      }
                      if (selectedPost.isPrivate) {
                        const processApplication = async () => {
                          showConfirm('참가 신청', `'${selectedPost.title}' 방장에게 참가 신청서를 전송하시겠습니까?`, async () => {
                            try {
                              await groupService.applyGroup(selectedPost.id, { introduction: applyMessage || '안녕하세요! 가입 신청합니다.' });
                              setAppliedStudies(prev => [...prev, selectedPost.id]);
                              showAlert('신청 완료', `신청 완료!\n\n[방장에게 전송된 메시지]\n${applyMessage || '안녕하세요! 가입 신청합니다.'}\n\n방장의 승인을 기다려주세요.`, () => {
                                setSelectedPost(null);
                                setApplyMessage('');
                                loadGroups();
                              });
                            } catch (err) {
                              showAlert('오류', err.response?.data?.message || '참가 신청에 실패했습니다.');
                            }
                          });
                        };

                        if (!applyMessage.trim()) {
                          showConfirm('알림', '메시지 없이 신청하시겠습니까? (방장이 거절할 확률이 높아질 수 있습니다)', processApplication);
                        } else {
                          processApplication();
                        }
                      } else {
                        showConfirm('바로 참여', `'${selectedPost.title}' 스터디에 바로 참여하시겠습니까?`, async () => {
                          try {
                            await groupService.applyGroup(selectedPost.id, { introduction: '공개 스터디 바로 참가' });
                            setAppliedStudies(prev => [...prev, selectedPost.id]);
                            setSelectedPost(null);
                            setPreJoinStudy(selectedPost);
                            loadGroups();
                          } catch (err) {
                            showAlert('오류', err.response?.data?.message || '가입에 실패했습니다.');
                          }
                        });
                      }
                    }}
                  >
                    {isFull
                      ? '정원이 마감되었습니다'
                      : (selectedPost.isAlreadyJoined ? '스터디 입장' : (selectedPost.isPrivate ? '참가신청' : '바로 참여하기'))}
                  </button>
                </div>
                  );
                })()}

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
                      {myStudies.map(study => (
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
                    onClick={async () => {
                      if (!writeForm.title || !writeForm.content) {
                        showAlert('알림', '모집글 제목과 상세 내용을 입력해주세요.');
                        return;
                      }
                      const selectedStudy = myStudies.find(s => s.id === parseInt(writeForm.studyId));
                      try {
                        const payload = {
                          title: writeForm.title,
                          hashtags: selectedStudy ? selectedStudy.hashtags : '',
                          description: writeForm.content,
                          startDate: selectedStudy ? selectedStudy.startDate : new Date().toISOString().split('T')[0],
                          endDate: selectedStudy ? selectedStudy.endDate : new Date(Date.now() + 90*24*60*60*1000).toISOString().split('T')[0],
                          capacity: selectedStudy ? selectedStudy.maxMembers : 10,
                          isPublic: selectedStudy ? !selectedStudy.isPrivate : true
                        };
                        await groupService.createGroup(payload);
                        showAlert('성공', '스터디 모집글이 성공적으로 등록되었습니다!', () => {
                          setIsWriteModalOpen(false);
                          setWriteForm({ studyId: '', title: '', content: '' });
                          loadGroups();
                        });
                      } catch (err) {
                        showAlert('오류', err.response?.data?.message || '모집글 등록에 실패했습니다.');
                      }
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
              <div style={{ 
                flex: 1, 
                display: 'flex', 
                flexDirection: Number(preJoinStudy.leaderId) === Number(userId) ? 'row' : 'column', 
                alignItems: Number(preJoinStudy.leaderId) === Number(userId) ? 'stretch' : 'center', 
                justifyContent: 'center', 
                padding: '40px 20px', 
                gap: '40px', 
                overflowY: 'auto',
                maxWidth: '1200px',
                width: '100%',
                margin: '0 auto',
                boxSizing: 'border-box'
              }}>

                <div style={{ 
                  flex: 1, 
                  display: 'flex', 
                  flexDirection: 'column', 
                  alignItems: 'center', 
                  justifyContent: 'center', 
                  gap: '24px', 
                  maxWidth: Number(preJoinStudy.leaderId) === Number(userId) ? '640px' : '800px',
                  width: '100%'
                }}>
                  <div style={{ textAlign: 'center' }}>
                    <h1 style={{ margin: '0 0 12px', fontSize: '22px', fontWeight: '700', color: '#111827' }}>스터디룸에 입장하기 전에 내 화면을 마음대로 꾸며보세요.</h1>
                    <p style={{ margin: 0, fontSize: '14px', color: '#6B7280' }}>지금 보이는 영상은 다른 사람이 볼 수 없습니다.</p>
                  </div>

                  {/* Video Box */}
                  <div style={{ width: '100%', backgroundColor: 'black', borderRadius: '16px', overflow: 'hidden', boxShadow: '0 25px 50px -12px rgba(0,0,0,0.3)', display: 'flex', flexDirection: 'column' }}>
                  <div style={{ position: 'relative', width: '100%', paddingTop: '56.25%', display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: isVideoOn ? '#1F2937' : 'black' }}>
                    {!isVideoOn ? (
                      <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px', color: '#4B5563' }}>
                        {user?.photoUrl ? (
                          <img src={user.photoUrl} alt="avatar" style={{ width: '80px', height: '80px', borderRadius: '50%', objectFit: 'cover', boxShadow: '0 8px 24px rgba(0,0,0,0.4)' }} />
                        ) : (
                          <div style={{ width: '80px', height: '80px', borderRadius: '50%', backgroundColor: '#374151', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 8px 24px rgba(0,0,0,0.4)' }}>
                            <User size={40} color="#9CA3AF" />
                          </div>
                        )}
                      </div>
                    ) : (
                      <>
                        <video
                          ref={videoRef}
                          autoPlay
                          playsInline
                          muted
                          style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: '100%', objectFit: 'cover' }}
                        />
                        {/* 권한/장치 확인이 끝나기 전에는 "확인 중"을 보여주고, 실패 메시지는 retry가 끝난 뒤에만 노출 */}
                        {cameraStatus === 'checking' && !camError && (
                          <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', backgroundColor: 'rgba(0,0,0,0.6)', color: '#E5E7EB', padding: '14px 18px', borderRadius: '8px', textAlign: 'center', zIndex: 10, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px' }}>
                            <Camera size={28} color="#60A5FA" />
                            <div style={{ fontSize: '13px', fontWeight: '600' }}>카메라를 확인하는 중입니다…</div>
                          </div>
                        )}
                        {camError && (
                          <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', backgroundColor: 'rgba(0,0,0,0.7)', color: '#FCA5A5', padding: '16px', borderRadius: '8px', textAlign: 'center', maxWidth: '80%', zIndex: 10 }}>
                            <AlertTriangle size={32} color="#EF4444" style={{ marginBottom: '8px' }} />
                            <div style={{ fontSize: '14px', fontWeight: 'bold' }}>카메라 사용에 문제가 있습니다.</div>
                            <div style={{ fontSize: '12px', marginTop: '4px', wordBreak: 'break-all' }}>{camError}</div>
                            <div style={{ display: 'flex', gap: '8px', marginTop: '12px', flexWrap: 'wrap', justifyContent: 'center' }}>
                              <button
                                onClick={() => { setCamError(''); setIsVideoOn(false); setTimeout(() => setIsVideoOn(true), 100); }}
                                style={{ padding: '6px 12px', borderRadius: '4px', border: '1px solid #FCA5A5', background: 'transparent', color: '#FCA5A5', cursor: 'pointer', fontSize: '12px' }}>
                                다시 시도
                              </button>
                              <button
                                onClick={() => { badCamerasRef.current.clear(); setSelectedCamera(''); setCamError(''); setIsVideoOn(false); setTimeout(() => setIsVideoOn(true), 100); }}
                                style={{ padding: '6px 12px', borderRadius: '4px', border: '1px solid #93C5FD', background: 'transparent', color: '#93C5FD', cursor: 'pointer', fontSize: '12px' }}>
                                기본 카메라로 전환
                              </button>
                              <button
                                onClick={() => { setCamError(''); setIsVideoOn(false); }}
                                style={{ padding: '6px 12px', borderRadius: '4px', border: '1px solid #D1D5DB', background: 'transparent', color: '#D1D5DB', cursor: 'pointer', fontSize: '12px' }}>
                                카메라 없이 입장
                              </button>
                            </div>
                          </div>
                        )}
                      </>
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
                            <select 
                              value={selectedCamera}
                              onChange={(e) => setSelectedCamera(e.target.value)}
                              style={{ width: '100%', appearance: 'none', border: 'none', backgroundColor: 'transparent', fontSize: '15px', color: '#111827', cursor: 'pointer', outline: 'none' }}
                            >
                              {cameras.length === 0 ? (
                                <option value="">카메라 찾는 중...</option>
                              ) : (
                                cameras.map((cam, idx) => (
                                  <option key={cam.deviceId} value={cam.deviceId}>
                                    {cam.label || `카메라 ${idx + 1}`}
                                  </option>
                                ))
                              )}
                            </select>
                            <div style={{ position: 'absolute', right: 0, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }}>▼</div>
                          </div>
                          <div style={{ fontSize: '12px', color: '#9CA3AF' }}>목록에서 다른 카메라를 선택해보세요</div>
                        </div>
                        {/* Mic */}
                        <div style={{ flex: 1, padding: '0 16px', borderRight: '1px solid #E5E7EB' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#4B5563', marginBottom: '12px' }}>
                            <Mic size={16} /> <span style={{ fontSize: '14px', fontWeight: '600' }}>마이크</span>
                          </div>
                          <div style={{ position: 'relative', marginBottom: '8px' }}>
                            <select style={{ width: '100%', appearance: 'none', border: 'none', backgroundColor: 'transparent', fontSize: '15px', color: '#111827', cursor: 'pointer', outline: 'none' }}>
                              {mics.length === 0 ? (
                                <option value="">기본 마이크</option>
                              ) : (
                                mics.map((mic, idx) => (
                                  <option key={mic.deviceId || idx} value={mic.deviceId}>
                                    {mic.label || `마이크 ${idx + 1}`}
                                  </option>
                                ))
                              )}
                            </select>
                            <div style={{ position: 'absolute', right: 0, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }}>▼</div>
                          </div>
                          {mics.length === 0 ? (
                            <div style={{ fontSize: '12px', color: '#EF4444' }}>연결된 마이크가 없어 음소거로 입장합니다</div>
                          ) : (
                            <div style={{ fontSize: '12px', color: '#9CA3AF' }}>{mics.length}개의 마이크가 연결되어 있습니다</div>
                          )}
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

                  {/* 카메라/마이크 ON·OFF 토글 + 실시간 입력 상태(레벨 미터) — 입장 전에 실제로 동작하는지 확인 */}
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '14px', padding: '12px 16px', backgroundColor: '#0F172A', borderTop: '1px solid #1F2937', flexWrap: 'wrap' }}>
                    {/* 카메라 토글 */}
                    <button
                      onClick={() => { setCamError(''); setIsVideoOn(v => !v); }}
                      style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 14px', borderRadius: '999px', border: '1px solid', borderColor: isVideoOn ? 'rgba(96,165,250,0.5)' : 'rgba(148,163,184,0.4)', backgroundColor: isVideoOn ? 'rgba(59,130,246,0.15)' : 'rgba(148,163,184,0.1)', color: isVideoOn ? '#93C5FD' : '#94A3B8', cursor: 'pointer', fontSize: '13px', fontWeight: 600 }}
                    >
                      {isVideoOn ? <Video size={16} /> : <VideoOff size={16} />}
                      <span>
                        {!isVideoOn ? '카메라 꺼짐'
                          : cameraStatus === 'checking' ? '카메라 확인 중…'
                          : cameraStatus === 'available' ? '카메라 켜짐'
                          : cameraStatus === 'unavailable' ? '카메라 없음'
                          : cameraStatus === 'error' ? '카메라 권한/오류'
                          : '카메라'}
                      </span>
                    </button>

                    {/* 마이크 토글 */}
                    <button
                      onClick={() => setIsMicOn(v => !v)}
                      style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '8px 14px', borderRadius: '999px', border: '1px solid', borderColor: isMicOn ? 'rgba(34,197,94,0.5)' : 'rgba(148,163,184,0.4)', backgroundColor: isMicOn ? 'rgba(34,197,94,0.12)' : 'rgba(148,163,184,0.1)', color: isMicOn ? '#86EFAC' : '#94A3B8', cursor: 'pointer', fontSize: '13px', fontWeight: 600 }}
                    >
                      {isMicOn ? <Mic size={16} /> : <MicOff size={16} />}
                      <span>
                        {!isMicOn ? '마이크 꺼짐'
                          : micStatus === 'checking' ? '마이크 확인 중…'
                          : micStatus === 'unavailable' ? '마이크 없음'
                          : micStatus === 'error' ? '마이크 권한/오류'
                          : micLevel > 12 ? '말하는 중'
                          : micLevel > 0 ? '입력 감지 중'
                          : '입력 대기 중'}
                      </span>
                    </button>

                    {/* 마이크 입력 레벨 미터: 말하면 막대가 차오른다(실제 입력 여부 가시화) */}
                    {isMicOn && (micStatus === 'available' || micStatus === 'checking') && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', minWidth: '120px' }}>
                        <div style={{ flex: 1, height: '6px', borderRadius: '4px', backgroundColor: 'rgba(255,255,255,0.12)', overflow: 'hidden', minWidth: '90px' }}>
                          <div style={{ width: `${micLevel}%`, height: '100%', backgroundColor: micLevel > 12 ? '#22C55E' : '#60A5FA', transition: 'width 0.1s linear' }} />
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
                    
                    {Number(preJoinStudy.leaderId) === Number(userId) && (
                      <button
                        style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px', background: 'none', border: 'none', cursor: 'pointer', color: showLeaderConsole ? '#10B981' : '#6B7280', flex: 1 }}
                        onClick={() => setShowLeaderConsole(true)}
                      >
                        <Shield size={24} />
                        <span style={{ fontSize: '12px', fontWeight: '500' }}>방장 관리</span>
                      </button>
                    )}

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
                    const isMember = preJoinMembers.some(m => Number(m.userId) === Number(userId)) || Number(preJoinStudy.leaderId) === Number(userId);
                    
                    if (isMember) {
                      showAlert('입장', `[${preJoinStudy.title}] 스터디룸으로 입장합니다!`, () => {
                        setActiveStudyRoom(preJoinStudy);
                        setPreJoinStudy(null);
                      });
                    } else {
                      if (!preJoinStudy.isPrivate) {
                        showConfirm('참가 신청', `'${preJoinStudy.title}' 스터디에 바로 참여하시겠습니까?`, async () => {
                          try {
                            await groupService.applyGroup(preJoinStudy.id, { introduction: '공개 스터디 바로 참가' });
                            setAppliedStudies(prev => [...prev, preJoinStudy.id]);
                            showAlert('가입 완료', '스터디에 정상적으로 가입되었습니다. 다시 입장 버튼을 눌러 스터디룸으로 들어가실 수 있습니다.', () => {
                              loadGroups();
                              // Refresh members
                              groupService.getMembers(preJoinStudy.id).then(setPreJoinMembers);
                            });
                          } catch (err) {
                            showAlert('오류', err.response?.data?.message || '가입에 실패했습니다.');
                          }
                        });
                      } else {
                        showAlert('권한 없음', '이 비공개 스터디의 멤버가 아닙니다. 모집게시판을 통해 가입 신청을 해주세요.');
                      }
                    }
                  }}
                >
                  <div style={{ width: '16px', height: '20px', border: '2px solid white', borderRight: 'none', borderTopLeftRadius: '4px', borderBottomLeftRadius: '4px', position: 'relative' }}>
                    <div style={{ position: 'absolute', right: '-2px', top: '50%', transform: 'translateY(-50%)', width: '4px', height: '12px', backgroundColor: 'white' }}></div>
                  </div>
                  입장
                </button>
              </div>

              {/* Leader Console Panel - Changed to Modal */}
              {showLeaderConsole && Number(preJoinStudy.leaderId) === Number(userId) && (
                <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 10000, padding: '20px' }} onClick={() => setShowLeaderConsole(false)}>
                  <div className="glass-panel animate-fade-in" style={{ 
                    width: '100%',
                    maxWidth: '420px', 
                    display: 'flex', 
                    flexDirection: 'column', 
                    gap: '24px', 
                    padding: '24px', 
                    boxSizing: 'border-box',
                    backgroundColor: '#ffffff',
                    border: '1px solid #e5e7eb',
                    borderRadius: '16px',
                    boxShadow: '0 4px 20px rgba(0, 0, 0, 0.05)',
                    height: 'fit-content',
                    maxHeight: '90vh',
                    overflowY: 'auto'
                  }} onClick={(e) => e.stopPropagation()}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <h3 style={{ margin: 0, fontSize: '18px', fontWeight: '700', color: '#111827', display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <Settings size={20} color="#10B981" /> 방장 관리 콘솔
                      </h3>
                      <button onClick={() => setShowLeaderConsole(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}>
                        <X size={24} color="#9CA3AF" />
                      </button>
                    </div>
                    
                    {/* 스터디 상태 표시 */}
                    <div style={{ backgroundColor: '#F9FAFB', border: '1px solid #E5E7EB', borderRadius: '8px', padding: '12px 16px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px', fontSize: '13px' }}>
                        <span style={{ color: '#6B7280' }}>스터디 상태</span>
                        <span style={{ 
                          fontWeight: '700', 
                          color: preJoinStudy.status === 'RECRUITING' ? '#10B981' : '#3B82F6'
                        }}>
                          {preJoinStudy.status === 'RECRUITING' ? '모집중' : '진행중 (모집종료)'}
                        </span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px' }}>
                        <span style={{ color: '#6B7280' }}>가입 인원</span>
                        <span style={{ fontWeight: '700', color: '#111827' }}>
                          {preJoinStudy.currentMembers} / {preJoinStudy.maxMembers}명
                        </span>
                      </div>
                    </div>

                    {/* 가입 신청자 대기 명단 */}
                    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '240px' }}>
                      <h4 style={{ margin: '0 0 12px 0', fontSize: '14px', fontWeight: '700', color: '#374151' }}>
                        가입 신청 대기자 명단 ({applications.length})
                      </h4>
                      
                      <div style={{ flex: 1, overflowY: 'auto', border: '1px solid #E5E7EB', borderRadius: '8px', padding: '10px', backgroundColor: '#F9FAFB', display: 'flex', flexDirection: 'column', gap: '10px', maxHeight: '300px' }}>
                        {loadingApps ? (
                          <div style={{ padding: '20px 0', textAlign: 'center', fontSize: '13px', color: '#9CA3AF' }}>불러오는 중...</div>
                        ) : applications.length === 0 ? (
                          <div style={{ padding: '40px 0', textAlign: 'center', fontSize: '13px', color: '#9CA3AF' }}>대기 중인 신청자가 없습니다.</div>
                        ) : (
                          applications.map(app => (
                            <div key={app.applicationId} style={{ backgroundColor: '#ffffff', border: '1px solid #E5E7EB', borderRadius: '8px', padding: '12px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                  {app.applicantPhotoUrl ? (
                                    <img
                                      src={app.applicantPhotoUrl}
                                      alt={app.applicantName}
                                      style={{ width: '24px', height: '24px', borderRadius: '50%', objectFit: 'cover' }}
                                    />
                                  ) : (
                                    <div style={{ width: '24px', height: '24px', borderRadius: '50%', backgroundColor: 'var(--color-primary)', color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '11px', fontWeight: 'bold' }}>
                                      {app.applicantName ? app.applicantName.charAt(0) : '?'}
                                    </div>
                                  )}
                                  <span style={{ fontWeight: '700', fontSize: '14px', color: '#111827' }}>{app.applicantName}</span>
                                </div>
                                <span style={{ fontSize: '11px', color: '#9CA3AF' }}>
                                  {app.createdAt ? app.createdAt.split('T')[0] : ''}
                                </span>
                              </div>
                              <p style={{ margin: 0, fontSize: '13px', color: '#4B5563', backgroundColor: '#F3F4F6', padding: '8px 10px', borderRadius: '6px', wordBreak: 'break-all', lineHeight: '1.4' }}>
                                {app.introduction}
                              </p>
                              <div style={{ display: 'flex', gap: '8px', marginTop: '4px' }}>
                                <button 
                                  onClick={() => handleApproveApp(app.applicationId)}
                                  style={{ flex: 1, height: '32px', backgroundColor: '#10B981', color: 'white', border: 'none', borderRadius: '6px', fontWeight: '700', fontSize: '12px', cursor: 'pointer' }}
                                >
                                  승인
                                </button>
                                <button 
                                  onClick={() => handleRejectApp(app.applicationId)}
                                  style={{ flex: 1, height: '32px', backgroundColor: '#EF4444', color: 'white', border: 'none', borderRadius: '6px', fontWeight: '700', fontSize: '12px', cursor: 'pointer' }}
                                >
                                  거절
                                </button>
                              </div>
                            </div>
                          ))
                        )}
                      </div>
                    </div>

                    {/* 관리 액션 */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', borderTop: '1px solid #E5E7EB', paddingTop: '16px', marginTop: 'auto' }}>

                      <button 
                        onClick={handleDeleteStudy}
                        style={{ width: '100%', height: '40px', backgroundColor: 'transparent', color: '#EF4444', border: '1px solid #EF4444', borderRadius: '8px', fontWeight: '700', fontSize: '14px', cursor: 'pointer', boxSizing: 'border-box' }}
                        onMouseEnter={(e) => e.currentTarget.style.backgroundColor = '#FEE2E2'}
                        onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}
                      >
                        스터디 강제 해체
                      </button>
                    </div>
                  </div>
                </div>
              )}
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
              selectedCamera={selectedCamera}
              initialMicOn={isMicOn}
              initialVideoOn={isVideoOn}
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
              <label
                htmlFor="create-study-image"
                style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: '#F3F4F6', color: '#6B7280', fontWeight: '600', cursor: 'pointer', margin: 0 }}
              >
                이미지 불러오기
                <input
                  type="file"
                  id="create-study-image"
                  accept="image/jpeg,image/png,image/webp"
                  onChange={(e) => {
                    const file = e.target.files[0];
                    if (!file) return;
                    const imageError = validateCoverImageFile(file);
                    if (imageError) {
                      showAlert('알림', imageError);
                      e.target.value = ''; // 동일 파일 재선택 가능하도록 input 초기화
                      return;
                    }
                    setCreateForm(prev => ({
                      ...prev,
                      imageFile: file,
                      thumbnail: URL.createObjectURL(file)
                    }));
                  }}
                  style={{ display: 'none' }}
                />
              </label>
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
