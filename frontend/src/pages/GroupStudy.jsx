import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Plus, Search, Lock, Globe, Filter, X, AlertTriangle, Settings, Check, ArrowLeft, Pencil, LogIn } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import { groupService, authService } from '../services/api';
import StudyRoom from '../components/StudyRoom';
import GroupCard from '../components/groupstudy/GroupCard';
import GroupEditModal from '../components/groupstudy/GroupEditModal';
import GroupSettingsFields, { DEFAULT_SETTINGS_FORM } from '../components/groupstudy/GroupSettingsFields';
import SettingRow from '../components/groupstudy/SettingRow';
import { ToggleSwitch } from '../components/groupstudy/ToggleSwitch';
import { validateCoverImageFile } from '../components/groupstudy/GroupProfileField';
import GroupProfileImage from '../components/groupstudy/GroupProfileImage';
import GroupInvitePanel from '../components/groupstudy/GroupInvitePanel';
import PendingMemberSection from '../components/groupstudy/PendingMemberSection';
import PreJoinMediaPanel from '../components/groupstudy/prejoin/PreJoinMediaPanel';
import {
  normalizeGroup, buildSettingsPayload, validateSettingsForm, validateJoinInputs,
  studyTypeLabel, formatTargetMinutes, formatStudySeconds, formatAttendanceRate,
  JOIN_ANSWER_MAX_LENGTH, NICKNAME_MAX_LENGTH,
  isCamStudy, resolveLeaderConsoleSections, buildMicConstraints, buildCameraPreviewConstraints,
  AVATAR_MODES, resolveParticipantAvatar,
} from '../utils/groupStudy';

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

export default function GroupStudy() {
  const { userId, user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  const [studies, setStudies] = useState([]);
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
    description: '',
    ...DEFAULT_SETTINGS_FORM,
  });
  // 가입 신청 입력(그룹이 켠 경우에만 요구): 가입 질문 답변 / 그룹 닉네임
  const [joinAnswer, setJoinAnswer] = useState('');
  const [joinNickname, setJoinNickname] = useState('');
  // 방장 전용 설정 수정 모달 대상(normalizeGroup 결과)
  const [editingStudy, setEditingStudy] = useState(null);

  // 프리조인(입장 준비) 상태
  const [preJoinStudy, setPreJoinStudy] = useState(null);
  const [activeStudyRoom, setActiveStudyRoom] = useState(null);
  // 입장 시 프리뷰에서 켜둔 카메라 트랙을 clone해 StudyRoom publisher로 그대로 넘긴다.
  //  · 프리뷰 stop → 같은 deviceId 재획득 과정에서 일부 장치가 "정지 프레임"을 돌려주는 freeze를 근절한다.
  const [handoffVideoTrack, setHandoffVideoTrack] = useState(null);
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
  // 현재 살아있는 프리뷰 스트림(입장 시 트랙 clone 출처). 프리뷰 effect가 갱신/정리한다.
  const previewStreamRef = React.useRef(null);
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
  // 마이크 입력 장치 선택(GENERAL/CAM 공통). '' = 기본 마이크. 입장 시 StudyRoom publisher audioSource 로 전달.
  const [selectedMic, setSelectedMic] = useState('');
  // GENERAL 입장 프로필(이번 입장 전용 visual identity): 'profile' | 'default' | 'upload'
  const [profileMode, setProfileMode] = useState(AVATAR_MODES.DEFAULT);
  const [profileFile, setProfileFile] = useState(null);
  const [profilePreviewUrl, setProfilePreviewUrl] = useState(null); // objectURL(즉시 미리보기)
  const [uploadingProfile, setUploadingProfile] = useState(false);
  // StudyRoom 으로 넘기는 세션 아바타 { mode, url(presigned, 원격 전파용), localUrl(내 타일용) }
  const [sessionAvatar, setSessionAvatar] = useState(null);
  const myDisplayName = user?.displayName || user?.nickname || (userId ? `User_${userId}` : '');

  const releaseProfilePreview = () => {
    setProfilePreviewUrl(prev => {
      if (prev) { try { URL.revokeObjectURL(prev); } catch (e) { /* ignore */ } }
      return null;
    });
    setProfileFile(null);
  };

  // 업로드 파일 선택: 형식 검증은 ProfileSelector 가 끝냈고, 여기서는 objectURL 로 미리보기를 즉시 반영한다.
  const handlePickProfileFile = (file) => {
    setProfilePreviewUrl(prev => {
      if (prev) { try { URL.revokeObjectURL(prev); } catch (e) { /* ignore */ } }
      try { return URL.createObjectURL(file); } catch (e) { return null; }
    });
    setProfileFile(file);
    setProfileMode(AVATAR_MODES.UPLOAD);
  };

  // 입장 준비 화면이 열릴 때 프로필 선택 초기화(계정 프로필 있으면 그것, 없으면 기본 아바타).
  useEffect(() => {
    if (!preJoinStudy) return;
    setProfileMode((user?.photoUrl || user?.photo_url) ? AVATAR_MODES.PROFILE : AVATAR_MODES.DEFAULT);
    setShowPreJoinSettings(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [preJoinStudy?.id]);

  // 미리보기용 아바타(우선순위: 이번 업로드 > 계정 프로필 > 기본). resolveParticipantAvatar 와 같은 규칙.
  const preJoinAvatar = resolveParticipantAvatar({
    avatarMode: profileMode,
    avatarUrl: profileMode === AVATAR_MODES.UPLOAD ? profilePreviewUrl : null,
    profilePhotoUrl: profileMode === AVATAR_MODES.PROFILE ? (user?.photoUrl || user?.photo_url || null) : null,
  });

  // 입장 확정: (CAM) 프리뷰 카메라 트랙 handoff, (GENERAL) 업로드 이미지는 기존 S3 프로필 업로드 API 로 올린 뒤 세션 아바타로 전달.
  const enterStudyRoom = async (target) => {
    const cam = isCamStudy(target.studyType);
    let handoff = null;
    if (cam) {
      // 프리뷰 카메라 트랙을 clone해 StudyRoom으로 넘긴다(stop→재획득 freeze 제거).
      //  · clone은 원본과 독립 생명주기 → 곧 이어질 프리뷰 cleanup의 stop에 영향받지 않는다.
      try {
        const vTrack = previewStreamRef.current?.getVideoTracks?.()[0];
        if (vTrack && vTrack.readyState === 'live') handoff = vTrack.clone();
      } catch (e) { handoff = null; }
    }
    const profileUrl = user?.photoUrl || user?.photo_url || null;
    let avatar = profileMode === AVATAR_MODES.DEFAULT
      ? { mode: AVATAR_MODES.DEFAULT, url: null, localUrl: null }
      : { mode: AVATAR_MODES.PROFILE, url: profileUrl, localUrl: profileUrl };
    if (!cam && profileMode === AVATAR_MODES.UPLOAD && profileFile) {
      setUploadingProfile(true);
      try {
        const res = await authService.uploadProfileImage(profileFile); // 기존 S3 업로드 API 재사용(신규 API/컬럼 없음)
        avatar = { mode: AVATAR_MODES.UPLOAD, url: res?.photoUrl || null, localUrl: profilePreviewUrl || res?.photoUrl || null };
      } catch (err) {
        setUploadingProfile(false);
        showAlert('프로필 업로드 실패', (err?.message || '이미지를 업로드하지 못했습니다.') + ' 다른 이미지를 선택하거나 기본 아이콘으로 입장해주세요.');
        return;
      }
      setUploadingProfile(false);
    }
    setHandoffVideoTrack(handoff);
    setSessionAvatar(avatar);
    setActiveStudyRoom(target);
    setPreJoinStudy(null);
  };
  // 열리지 않는(stale/고장) 카메라 deviceId를 기억해 무한 재시도/재선택 루프를 방지한다.
  const badCamerasRef = React.useRef(new Set());

  // 권한을 얻은 후 장치 목록을 가져오는 함수
  const fetchDevices = async () => {
    if (!navigator.mediaDevices || !navigator.mediaDevices.enumerateDevices) return;
    try {
      const devices = await navigator.mediaDevices.enumerateDevices();
      const videoInputs = devices.filter(device => device.kind === 'videoinput');
      const audioInputs = devices.filter(device => device.kind === 'audioinput');
      setMics(audioInputs);
      // 선택 마이크가 목록에서 사라지면(핫플러그 해제) 기본 마이크로 되돌린다.
      if (selectedMic && !audioInputs.some(a => a.deviceId === selectedMic)) {
        setSelectedMic('');
      }
      // GENERAL 은 카메라 장치를 다루지 않는다(목록도 비움).
      if (!isCamStudy(preJoinStudy?.studyType)) {
        setCameras([]);
        return;
      }
      setCameras(videoInputs);

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
    // GENERAL(일반 스터디): 카메라 preview/권한 요청 자체를 하지 않는다(video permission 요청은 버그).
    if (!isCamStudy(preJoinStudy.studyType)) {
      setCameraStatus('off');
      setCamError('');
      previewStreamRef.current = null;
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
      const constraints = buildCameraPreviewConstraints(selectedCamera); // CAM 전용: { video, audio:false }
      try {
        const s = await navigator.mediaDevices.getUserMedia(constraints);
        if (!isMounted) {
          s.getTracks().forEach(t => t.stop());
          return;
        }
        stream = s;
        previewStreamRef.current = s; // 입장 시 이 스트림의 video track을 clone해 publisher로 넘긴다
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
      // 원본 프리뷰 스트림 참조 해제(입장 시 넘긴 clone은 독립 생명주기라 영향 없음).
      if (previewStreamRef.current === stream) previewStreamRef.current = null;
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
        // GENERAL/CAM 공통: 마이크만 요청(video:false). 선택 마이크가 있으면 deviceId exact.
        micStream = await navigator.mediaDevices.getUserMedia(buildMicConstraints(selectedMic));
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
        // 선택 마이크가 stale/제약 불일치면 기본 마이크로 자동 복귀(effect 재실행).
        if ((err.name === 'OverconstrainedError' || err.name === 'ConstraintNotSatisfiedError') && selectedMic) {
          setSelectedMic('');
          return;
        }
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
  }, [preJoinStudy, isMicOn, selectedMic]);

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
      
      // 서버 계약 → 화면 모델 변환은 utils/groupStudy.normalizeGroup 단일 지점에서 수행한다.
      const normalized = data.map(normalizeGroup);

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
      setApplications((data || []).filter(app => app.status === 'PENDING')); // 서버 enum GroupStudyJoinStatus.PENDING
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



  // 설정 수정 저장 후: 목록/프리조인/상세 모달 state 를 서버 응답으로 즉시 갱신(새로고침 없이 반영, R12 는 reload 로 재확인).
  const handleStudyUpdated = (updated) => {
    setStudies(prev => prev.map(g => (g.id === updated.id ? updated : g)));
    setMyStudies(prev => prev.map(g => (g.id === updated.id ? updated : g)));
    setPreJoinStudy(prev => (prev && prev.id === updated.id ? { ...prev, ...updated } : prev));
    setSelectedPost(prev => (prev && prev.id === updated.id ? { ...prev, ...updated } : prev));
    setEditingStudy(null);
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

  // 방장 콘솔 섹션 노출 정책(utils 단일 지점): 초대 관리 = 비공개, 대기자 명단 = 승인 정책 or 실제 대기자 존재.
  const leaderSections = resolveLeaderConsoleSections(preJoinStudy, applications.length);
  const preJoinNavProps = preJoinStudy ? {
    isLeader: Number(preJoinStudy.leaderId) === Number(userId),
    showInfo: showPreJoinInfo,
    showSettings: showPreJoinSettings,
    showLeaderConsole,
    onInfo: () => setShowPreJoinInfo(true),
    onLeaderConsole: () => setShowLeaderConsole(true),
    onSettings: () => setShowPreJoinSettings(v => !v),
  } : null;

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
        <div className="glass-panel gs-create-panel" style={{ maxWidth: '900px', margin: '0 auto 60px', display: 'flex', flexDirection: 'column', gap: '36px', boxSizing: 'border-box' }}>
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

          <h3 className="gs-section-title">기본 정보</h3>

          {/* 공개 여부 */}
          <SettingRow label="공개 여부" required hint="* 공개 여부는 스터디를 만든 후 변경이 불가능합니다." align="center">
              <div style={{ display: 'flex', gap: '24px', alignItems: 'center', flexWrap: 'wrap', minHeight: '44px' }}>
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
          </SettingRow>

          {/* 스터디 이름 */}
          <SettingRow label="그룹명" required>
              <input
                type="text"
                className="gs-input"
                placeholder="스터디 이름을 입력하세요"
                value={createForm.title}
                maxLength={100}
                onChange={(e) => setCreateForm({ ...createForm, title: e.target.value })}
              />
          </SettingRow>

          {/* 스터디 공지사항(설명) */}
          <SettingRow label="설명" required hint={`(${createForm.description.length} / 1000)`}>
              <textarea
                className="gs-textarea"
                placeholder="스터디 규칙, 공지 사항 등을 입력해주세요"
                value={createForm.description}
                style={{ minHeight: '160px' }}
                onChange={(e) => {
                  if (e.target.value.length <= 1000) {
                    setCreateForm({ ...createForm, description: e.target.value });
                  }
                }}
              />
          </SettingRow>

          {/* 해시태그 */}
          <SettingRow label="해시태그">
              <input
                type="text"
                className="gs-input"
                placeholder="스터디를 대표하는 키워드를 입력하세요. (최대 3개)"
                value={createForm.tags}
                onChange={(e) => setCreateForm({ ...createForm, tags: e.target.value })}
              />
          </SettingRow>

          {/* 기간 */}
          <SettingRow label="기간" hint="92일 동안 스터디가 유지됩니다.">
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
                <input
                  type="date"
                  className="gs-input gs-form-fixed"
                  value={createForm.startDate}
                  onChange={(e) => setCreateForm({ ...createForm, startDate: e.target.value })}
                  style={{ width: '200px' }}
                />
                <span style={{ color: '#6B7280' }}>~</span>
                <input
                  type="date"
                  className="gs-input gs-form-fixed"
                  value={createForm.endDate}
                  onChange={(e) => setCreateForm({ ...createForm, endDate: e.target.value })}
                  style={{ width: '200px' }}
                />
              </div>
          </SettingRow>

          {/* 스터디 정원 */}
          <SettingRow label="최대 인원" required hint="최소 2명 ~ 최대 10명 (화상통화 안정 성능 보장)">
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <input
                  type="number"
                  className="gs-input gs-form-fixed"
                  min={2}
                  max={10}
                  placeholder="최대 참여 인원을 입력하세요"
                  value={createForm.capacity}
                  onChange={(e) => setCreateForm({ ...createForm, capacity: e.target.value })}
                  style={{ width: '200px' }}
                />
                <span style={{ color: '#6B7280', fontSize: '15px' }}>명</span>
              </div>
          </SettingRow>

          {/* 스터디 방식 / 학습 목표 / 가입 설정 / 그룹 닉네임 (생성·수정 공용) */}
          <GroupSettingsFields value={createForm} onChange={(next) => setCreateForm({ ...createForm, ...next })} />

          <h3 className="gs-section-title">그룹 프로필</h3>

          {/* 그룹 프로필(대표 이미지). 스터디콘 asset 은 추후 제공 예정 → 현재는 이미지 업로드/기본 프리셋만. */}
          <SettingRow label="프로필 이미지" hint="스터디콘(아이콘) 선택은 추후 제공됩니다.">
              <div style={{ position: 'relative', width: '100%', maxWidth: '300px', aspectRatio: '3 / 2', borderRadius: '12px', overflow: 'hidden', backgroundImage: `url(${createForm.thumbnail})`, backgroundSize: 'cover', backgroundPosition: 'center' }}>
                <div
                  style={{ position: 'absolute', bottom: '12px', left: '12px', backgroundColor: 'rgba(0,0,0,0.6)', padding: '6px 12px', borderRadius: '6px', color: 'white', display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer', fontSize: '13px', fontWeight: '600' }}
                  onClick={() => setShowImageSelectModal(true)}
                >
                  <Camera size={14} /> 편집
                </div>
              </div>
          </SettingRow>

          {/* 초기 장치 설정 */}
          <SettingRow label="초기 장치 설정" align="center">
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px', minHeight: '44px' }}>
                <ToggleSwitch checked={createForm.cameraOn} onChange={(checked) => setCreateForm({ ...createForm, cameraOn: checked })} label="카메라" />
                <span style={{ fontSize: '15px', color: '#374151' }}>카메라</span>
              </div>
          </SettingRow>

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
                const settingsError = validateSettingsForm(createForm);
                if (settingsError) {
                  showAlert('알림', settingsError);
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
                    ...buildSettingsPayload(createForm),
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
                      description: '',
                      ...DEFAULT_SETTINGS_FORM,
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
            <div className="glass-panel gs-searchbar" style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '12px 20px', borderRadius: '12px' }}>
              <Search size={20} color="#9CA3AF" style={{ flexShrink: 0 }} />
              <input
                type="text"
                className="gs-search-input"
                placeholder="관심있는 스터디나 기술 스택(태그)을 검색해보세요"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                style={{ flex: 1, minWidth: 0, border: 'none', outline: 'none', backgroundColor: 'transparent', fontSize: '15px', color: 'var(--color-text-main)' }}
              />
              <div className="gs-search-divider" style={{ width: '1px', height: '24px', backgroundColor: 'var(--color-border)', margin: '0 4px' }} />
              <button
                className="btn-primary gs-create-btn"
                style={{ width: 'auto', height: '36px', padding: '0 16px', fontSize: '14px', flexShrink: 0, whiteSpace: 'nowrap' }}
                onClick={() => {
                  if (!checkAuth()) return;
                  setIsCreateStudyMode(true);
                }}
              >
                <Plus size={16} /> 스터디 만들기
              </button>
            </div>
            {/* 스터디 목록 그리드 */}
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(min(320px, 100%), 1fr))', gap: '24px', marginTop: '24px' }}>
              {filteredStudies.length === 0 ? (
                <div style={{ gridColumn: '1 / -1', padding: '60px 0', textAlign: 'center', color: 'var(--color-text-muted)', backgroundColor: '#f9fafb', borderRadius: '16px' }}>
                  <Filter size={40} style={{ margin: '0 auto 16px', opacity: 0.3 }} />
                  <p style={{ fontSize: '16px', fontWeight: '500' }}>조건에 맞는 스터디가 없습니다.</p>
                </div>
              ) : (
                filteredStudies.map(study => (
                  <GroupCard
                    key={study.id}
                    study={study}
                    userId={userId}
                    applied={appliedStudies.includes(study.id)}
                    onOpen={handleCardClick}
                  />
                ))
              )}
            </div>

          {/* 모집글 상세 모달 */}
          {selectedPost && (
            <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: '20px' }} onClick={() => { setSelectedPost(null); setApplyMessage(''); setJoinAnswer(''); setJoinNickname(''); }}>
              <div style={{ backgroundColor: 'white', borderRadius: '12px', width: '100%', maxWidth: '420px', maxHeight: 'calc(100vh - 40px)', overflow: 'hidden', boxShadow: '0 25px 50px -12px rgba(0,0,0,0.25)', display: 'flex', flexDirection: 'column', animation: 'slideUp 0.3s ease-out' }} onClick={(e) => e.stopPropagation()}>

                {/* 상단 이미지 및 제목 영역 */}
                <div style={{ position: 'relative', height: '160px', backgroundColor: '#1F2937', color: 'white', display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', padding: '20px' }}>
                  <GroupProfileImage imageUrl={selectedPost.hasCoverImage ? selectedPost.thumbnailUrl : null} studyType={selectedPost.studyType} iconSize={72} fill alt="Background" style={{ opacity: 0.3 }} />
                  <button onClick={() => { setSelectedPost(null); setApplyMessage(''); setJoinAnswer(''); setJoinNickname(''); }} style={{ position: 'absolute', top: '16px', right: '16px', background: 'none', border: 'none', color: 'white', cursor: 'pointer', padding: '4px', zIndex: 2 }}>
                    <X size={20} />
                  </button>

                  <div style={{ position: 'relative', zIndex: 1 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
                      {selectedPost.isPrivate ? (
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', backgroundColor: 'rgba(0,0,0,0.5)', color: '#fff', padding: '4px 8px', borderRadius: '4px', fontSize: '12px', fontWeight: '600' }}><Lock size={14} /> 비공개 스터디 모집</span>
                      ) : (
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', backgroundColor: 'rgba(59, 130, 246, 0.8)', color: '#fff', padding: '4px 8px', borderRadius: '4px', fontSize: '12px', fontWeight: '600' }}><Globe size={14} /> 공개 스터디 모집</span>
                      )}
                      <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', backgroundColor: 'rgba(0,0,0,0.5)', color: '#fff', padding: '4px 8px', borderRadius: '4px', fontSize: '12px', fontWeight: '600' }}>{studyTypeLabel(selectedPost.studyType)}</span>
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
                      <div style={{ fontSize: '13px', color: '#6B7280', marginBottom: '6px' }}>스터디 기간 <span style={{ backgroundColor: '#FEF3C7', color: '#D97706', padding: '2px 6px', borderRadius: '4px', fontSize: '11px', fontWeight: '700', marginLeft: '4px' }}>D-{selectedPost.startDate ? Math.max(0, Math.ceil((new Date(selectedPost.startDate).getTime() - new Date().getTime()) / (1000 * 3600 * 24))) : '0'}</span></div>
                      <div style={{ fontSize: '15px', fontWeight: '700', color: '#111827' }}>{selectedPost.startDate ? selectedPost.startDate.split('T')[0] : ''} - {selectedPost.endDate ? selectedPost.endDate.split('T')[0] : ''}</div>
                    </div>
                  </div>

                  {/* 운영 정책 · 활동 지표 (서버 값) */}
                  <div className="gs-join-block">
                    <div style={{ fontSize: '13px', color: '#6B7280', marginBottom: '8px' }}>스터디 운영</div>
                    <div className="gs-policy-list">
                      <div><span>스터디 방식</span><strong>{studyTypeLabel(selectedPost.studyType)}</strong></div>
                      <div><span>하루 목표</span><strong>{formatTargetMinutes(selectedPost.targetStudyMinutes)}</strong></div>
                      <div><span>출석률 · {selectedPost.activityWindowDays}일</span><strong>{formatAttendanceRate(selectedPost.attendanceRate)}</strong></div>
                      <div><span>평균 공부 · 1일</span><strong>{formatStudySeconds(selectedPost.avgStudySeconds)}</strong></div>
                      {selectedPost.nicknameRuleEnabled && (
                        <div><span>닉네임 규칙</span><strong style={{ wordBreak: 'keep-all' }}>{selectedPost.nicknameRule}</strong></div>
                      )}
                    </div>
                  </div>

                  <div style={{ marginBottom: '24px' }}>
                    <div style={{ fontSize: '13px', color: '#6B7280', marginBottom: '8px' }}>모집글 내용</div>
                    <div style={{ backgroundColor: '#F9FAFB', padding: '16px', borderRadius: '8px', fontSize: '14px', color: '#374151', lineHeight: '1.6', wordBreak: 'keep-all', border: '1px solid #F3F4F6' }}>
                      {selectedPost.content}
                    </div>
                  </div>

                  {/* 가입 질문 답변 / 그룹 닉네임 — 그룹이 켠 경우에만, 미가입자에게만 */}
                  {!selectedPost.isAlreadyJoined && !appliedStudies.includes(selectedPost.id) && selectedPost.joinQuestionEnabled && (
                    <div className="gs-join-block">
                      <div style={{ fontSize: '13px', color: '#6B7280', marginBottom: '8px', display: 'flex', justifyContent: 'space-between' }}>
                        <span>가입 질문</span>
                        <span style={{ fontSize: '11px', color: '#EF4444' }}>(필수)</span>
                      </div>
                      <div className="gs-join-question">Q. {selectedPost.joinQuestion}</div>
                      <textarea
                        className="gs-textarea"
                        placeholder="질문에 대한 답변을 입력해주세요."
                        value={joinAnswer}
                        maxLength={JOIN_ANSWER_MAX_LENGTH}
                        onChange={(e) => setJoinAnswer(e.target.value)}
                        style={{ minHeight: '80px', fontSize: '13px' }}
                        aria-label="가입 질문 답변"
                      />
                    </div>
                  )}
                  {!selectedPost.isAlreadyJoined && !appliedStudies.includes(selectedPost.id) && selectedPost.nicknameRuleEnabled && (
                    <div className="gs-join-block">
                      <div style={{ fontSize: '13px', color: '#6B7280', marginBottom: '8px', display: 'flex', justifyContent: 'space-between' }}>
                        <span>그룹 닉네임</span>
                        <span style={{ fontSize: '11px', color: '#EF4444' }}>(필수)</span>
                      </div>
                      <div className="gs-join-question">규칙: {selectedPost.nicknameRule}</div>
                      <input
                        type="text"
                        className="gs-input"
                        placeholder="규칙에 맞는 그룹 닉네임을 입력해주세요."
                        value={joinNickname}
                        maxLength={NICKNAME_MAX_LENGTH}
                        onChange={(e) => setJoinNickname(e.target.value)}
                        style={{ fontSize: '13px' }}
                        aria-label="그룹 닉네임"
                      />
                    </div>
                  )}

                  {selectedPost.isPrivate && !selectedPost.isAlreadyJoined && !appliedStudies.includes(selectedPost.id) && (
                    <div style={{ marginBottom: '24px', padding: '14px', borderRadius: '8px', backgroundColor: 'var(--color-secondary)', border: '1px solid var(--color-border)', display: 'flex', alignItems: 'flex-start', gap: '8px' }}>
                      <Lock size={16} color="#8B5CF6" style={{ flexShrink: 0, marginTop: '2px' }} />
                      <div style={{ fontSize: '13px', color: 'var(--color-text-main)', lineHeight: 1.6 }}>
                        <strong>초대 전용 비공개 스터디</strong>
                        <div style={{ color: 'var(--color-text-muted)', marginTop: '2px' }}>방장이 공유한 초대 링크로만 참여할 수 있습니다. 검색이나 주소 직접 입력으로는 가입할 수 없습니다.</div>
                      </div>
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
                <div style={{ backgroundColor: isFull ? '#9CA3AF' : '#3B82F6', padding: '0', display: 'flex' }}>
                  {Number(selectedPost.leaderId) === Number(userId) && (
                    <button
                      type="button"
                      onClick={() => setEditingStudy(selectedPost)}
                      style={{ flexShrink: 0, padding: '16px 18px', fontSize: '14px', fontWeight: '600', color: '#fff', backgroundColor: 'rgba(0,0,0,0.18)', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px' }}
                      aria-label="스터디 설정 수정"
                    >
                      <Pencil size={16} color="#fff" /> 설정
                    </button>
                  )}
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
                      // 그룹 정책 입력(가입 질문 답변/그룹 닉네임) 1차 검증 — 서버가 최종 검증한다.
                      const joinInputError = validateJoinInputs(selectedPost, { joinAnswer, nickname: joinNickname });
                      if (joinInputError) {
                        showAlert('알림', joinInputError);
                        return;
                      }
                      const joinExtras = {
                        ...(selectedPost.joinQuestionEnabled ? { joinAnswer: joinAnswer.trim() } : {}),
                        ...(selectedPost.nicknameRuleEnabled ? { nickname: joinNickname.trim() } : {}),
                      };
                      if (selectedPost.isPrivate) {
                        // 서버(GroupStudyService.applyToGroupStudy)가 비공개 직접 가입을 403 으로 차단한다. 프론트는 안내만.
                        showAlert('초대 전용 스터디', '비공개 스터디는 방장의 초대 링크로만 참여할 수 있습니다.');
                        return;
                        // eslint-disable-next-line no-unreachable
                        const processApplication = async () => {
                          showConfirm('참가 신청', `'${selectedPost.title}' 방장에게 참가 신청서를 전송하시겠습니까?`, async () => {
                            try {
                              await groupService.applyGroup(selectedPost.id, { introduction: applyMessage || '안녕하세요! 가입 신청합니다.', ...joinExtras });
                              setAppliedStudies(prev => [...prev, selectedPost.id]);
                              showAlert('신청 완료', `신청 완료!\n\n[방장에게 전송된 메시지]\n${applyMessage || '안녕하세요! 가입 신청합니다.'}\n\n방장의 승인을 기다려주세요.`, () => {
                                setSelectedPost(null);
                                setApplyMessage('');
                                setJoinAnswer('');
                                setJoinNickname('');
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
                            await groupService.applyGroup(selectedPost.id, { introduction: '공개 스터디 바로 참가', ...joinExtras });
                            setAppliedStudies(prev => [...prev, selectedPost.id]);
                            setSelectedPost(null);
                            setJoinAnswer('');
                            setJoinNickname('');
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
                      : (selectedPost.isAlreadyJoined ? '스터디 입장' : (selectedPost.isPrivate ? '초대 링크로만 참여 가능' : '바로 참여하기'))}
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
                  <div style={{ width: '40px', height: '40px', borderRadius: '8px', overflow: 'hidden', position: 'relative', flexShrink: 0 }}>
                    <GroupProfileImage imageUrl={preJoinStudy.hasCoverImage ? preJoinStudy.thumbnailUrl : null} studyType={preJoinStudy.studyType} iconSize={20} fill alt="thumbnail" />
                  </div>
                  <h2 style={{ margin: 0, fontSize: '18px', fontWeight: '700', color: '#111827' }}>{preJoinStudy.title} <span style={{ fontWeight: '500', color: '#6B7280', fontSize: '15px', marginLeft: '8px' }}>입장 준비</span></h2>
                </div>
                <button onClick={() => { releaseProfilePreview(); setPreJoinStudy(null); }} aria-label="입장 준비 닫기" style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6B7280', padding: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: '50%', transition: 'background-color 0.2s' }} onMouseEnter={(e) => e.currentTarget.style.backgroundColor = '#F3F4F6'} onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'transparent'}>
                  <X size={24} />
                </button>
              </div>

              {/* Body */}
              <div className="prejoin-body" style={{
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
                    {isCamStudy(preJoinStudy.studyType) ? (
                      <>
                        <h1 style={{ margin: '0 0 12px', fontSize: '22px', fontWeight: '700', color: '#111827' }}>스터디룸에 입장하기 전에 내 화면을 마음대로 꾸며보세요.</h1>
                        <p style={{ margin: 0, fontSize: '14px', color: '#6B7280' }}>지금 보이는 영상은 다른 사람이 볼 수 없습니다.</p>
                      </>
                    ) : (
                      <>
                        <h1 style={{ margin: '0 0 12px', fontSize: '22px', fontWeight: '700', color: '#111827' }}>입장하기 전에 프로필과 마이크를 확인하세요.</h1>
                        <p style={{ margin: 0, fontSize: '14px', color: '#6B7280' }}>일반 스터디는 카메라 없이 프로필 이미지와 음성으로 함께 공부합니다.</p>
                      </>
                    )}
                  </div>

                  {/* 스터디 타입별 미디어 패널: 서버 studyType(GENERAL/CAM) 기준 분기. GENERAL 은 카메라 요소/권한 요청 없음 */}
                  <PreJoinMediaPanel
                    studyType={preJoinStudy.studyType}
                    general={{
                      avatar: preJoinAvatar,
                      displayName: myDisplayName,
                      profile: {
                        mode: profileMode,
                        profilePhotoUrl: user?.photoUrl || user?.photo_url || null,
                        uploadedFileName: profileFile?.name || null,
                        onSelectMode: (mode) => setProfileMode(mode),
                        onPickFile: handlePickProfileFile,
                        onError: (msg) => showAlert('이미지 형식 오류', msg),
                      },
                      mic: {
                        isMicOn, micStatus, micLevel, onToggle: () => setIsMicOn(v => !v),
                        mics, selectedMic, onSelectMic: setSelectedMic,
                        showDeviceSelector: showPreJoinSettings,
                      },
                      nav: preJoinNavProps,
                    }}
                    cam={{
                      camera: {
                        videoRef, isVideoOn, cameraStatus, camError,
                        photoUrl: user?.photoUrl || null,
                        onToggle: () => { setCamError(''); setIsVideoOn(v => !v); },
                        onRetry: () => { setCamError(''); setIsVideoOn(false); setTimeout(() => setIsVideoOn(true), 100); },
                        onUseDefaultCamera: () => { badCamerasRef.current.clear(); setSelectedCamera(''); setCamError(''); setIsVideoOn(false); setTimeout(() => setIsVideoOn(true), 100); },
                        onEnterWithoutCamera: () => { setCamError(''); setIsVideoOn(false); },
                      },
                      mic: {
                        isMicOn, micStatus, micLevel, onToggle: () => setIsMicOn(v => !v),
                        mics, selectedMic, onSelectMic: setSelectedMic,
                      },
                      devices: { show: showPreJoinSettings, cameras, selectedCamera, onCameraChange: setSelectedCamera },
                      nav: preJoinNavProps,
                    }}
                  />

                <button
                  data-testid="prejoin-enter-button"
                  disabled={uploadingProfile}
                  style={{ padding: '16px 80px', borderRadius: '8px', backgroundColor: preJoinStudy.isPrivate ? '#8B5CF6' : '#3B82F6', color: 'white', fontSize: '18px', fontWeight: '700', border: 'none', cursor: uploadingProfile ? 'wait' : 'pointer', opacity: uploadingProfile ? 0.7 : 1, boxShadow: preJoinStudy.isPrivate ? '0 4px 12px rgba(139, 92, 246, 0.3)' : '0 4px 12px rgba(59, 130, 246, 0.3)', transition: 'background-color 0.2s', display: 'flex', alignItems: 'center', gap: '8px' }}
                  onMouseEnter={(e) => e.currentTarget.style.backgroundColor = preJoinStudy.isPrivate ? '#7C3AED' : '#2563EB'}
                  onMouseLeave={(e) => e.currentTarget.style.backgroundColor = preJoinStudy.isPrivate ? '#8B5CF6' : '#3B82F6'}
                  onClick={() => {
                    const isMember = preJoinMembers.some(m => Number(m.userId) === Number(userId)) || Number(preJoinStudy.leaderId) === Number(userId);
                    
                    if (isMember) {
                      if (uploadingProfile) return;
                      showAlert('입장', `[${preJoinStudy.title}] 스터디룸으로 입장합니다!`, () => { enterStudyRoom(preJoinStudy); });
                    } else {
                      if (!preJoinStudy.isPrivate && (preJoinStudy.joinQuestionEnabled || preJoinStudy.nicknameRuleEnabled)) {
                        // 가입 질문/닉네임 입력이 필요한 그룹은 상세 모달에서 입력 후 가입한다.
                        const target = preJoinStudy;
                        setPreJoinStudy(null);
                        setSelectedPost({ ...target, isAlreadyJoined: false });
                        return;
                      }
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
                        showAlert('권한 없음', '이 비공개 스터디의 멤버가 아닙니다. 방장이 공유한 초대 링크로만 참여할 수 있습니다.');
                      }
                    }
                  }}
                >
                  <LogIn size={20} />
                  {uploadingProfile ? '프로필 업로드 중…' : '입장'}
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
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px', marginBottom: '8px' }}>
                        <span style={{ color: '#6B7280' }}>가입 인원</span>
                        <span style={{ fontWeight: '700', color: '#111827' }}>
                          {preJoinStudy.currentMembers} / {preJoinStudy.maxMembers}명
                        </span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px', marginBottom: '8px' }}>
                        <span style={{ color: '#6B7280' }}>스터디 방식 · 목표</span>
                        <span style={{ fontWeight: '700', color: '#111827' }}>{studyTypeLabel(preJoinStudy.studyType)} · {formatTargetMinutes(preJoinStudy.targetStudyMinutes)}</span>
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px' }}>
                        <span style={{ color: '#6B7280' }}>가입 질문 · 닉네임 규칙</span>
                        <span style={{ fontWeight: '700', color: '#111827' }}>{preJoinStudy.joinQuestionEnabled ? 'ON' : 'OFF'} · {preJoinStudy.nicknameRuleEnabled ? 'ON' : 'OFF'}</span>
                      </div>
                    </div>

                    <button
                      type="button"
                      onClick={() => setEditingStudy(preJoinStudy)}
                      className="btn-outline"
                      style={{ height: '40px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', fontWeight: '700' }}
                    >
                      <Pencil size={16} /> 스터디 설정 수정
                    </button>

                    {/* 가입 신청 대기자 명단: 승인 정책(approvalRequired/JOIN_REQUEST)이거나 실제 대기자가 있을 때만 DOM 에 렌더 */}
                    {leaderSections.showPendingMembers && (
                      <PendingMemberSection
                        applications={applications}
                        loading={loadingApps}
                        onApprove={handleApproveApp}
                        onReject={handleRejectApp}
                      />
                    )}

                    {/* 관리 액션 */}
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', borderTop: '1px solid #E5E7EB', paddingTop: '16px', marginTop: 'auto' }}>
                      {/* 비공개(INVITE_ONLY/JOIN_REQUEST) 스터디 사용자 초대/초대 관리(방장 전용, 서버 403 검증) */}
                      {leaderSections.showInviteManagement && (
                        <div data-testid="invite-management">
                          <GroupInvitePanel groupId={preJoinStudy.id} onNotify={showAlert} />
                        </div>
                      )}

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
                      <div style={{ fontSize: '13px', color: '#6B7280', marginBottom: '6px', display: 'flex', alignItems: 'center', justifyContent: 'flex-end' }}>스터디 기간 <span style={{ backgroundColor: '#FEF3C7', color: '#D97706', padding: '2px 6px', borderRadius: '4px', fontSize: '11px', fontWeight: '700', marginLeft: '4px' }}>D-{preJoinStudy.startDate ? Math.max(0, Math.ceil((new Date(preJoinStudy.startDate).getTime() - new Date().getTime()) / (1000 * 3600 * 24))) : '0'}</span></div>
                      <div style={{ fontSize: '15px', fontWeight: '700', color: '#111827' }}>{preJoinStudy.startDate ? preJoinStudy.startDate.split('T')[0].replace(/-/g, '.') : '미정'} - {preJoinStudy.endDate ? preJoinStudy.endDate.split('T')[0].replace(/-/g, '.') : '미정'}</div>
                    </div>
                  </div>

                  <div className="gs-policy-list" style={{ marginBottom: '24px' }}>
                    <div><span>스터디 방식</span><strong>{studyTypeLabel(preJoinStudy.studyType)}</strong></div>
                    <div><span>하루 목표</span><strong>{formatTargetMinutes(preJoinStudy.targetStudyMinutes)}</strong></div>
                    <div><span>출석률 · {preJoinStudy.activityWindowDays}일</span><strong>{formatAttendanceRate(preJoinStudy.attendanceRate)}</strong></div>
                    <div><span>평균 공부 · 1일</span><strong>{formatStudySeconds(preJoinStudy.avgStudySeconds)}</strong></div>
                    {preJoinStudy.nicknameRuleEnabled && <div><span>닉네임 규칙</span><strong>{preJoinStudy.nicknameRule}</strong></div>}
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
              onClose={() => {
                setActiveStudyRoom(null);
                // publisher가 안 썼을 수 있는 handoff clone을 정리(카메라 점유 해제).
                if (handoffVideoTrack) {
                  try { handoffVideoTrack.stop(); } catch (e) { /* ignore */ }
                  setHandoffVideoTrack(null);
                }
                // 이번 입장에서 쓴 프로필 objectURL 정리(세션 전용 identity 종료).
                releaseProfilePreview();
                setSessionAvatar(null);
              }}
              selectedCamera={selectedCamera}
              selectedMic={selectedMic}
              sessionAvatar={sessionAvatar}
              initialMicOn={isMicOn}
              initialVideoOn={isCamStudy(activeStudyRoom.studyType) ? isVideoOn : false}
              handoffVideoTrack={handoffVideoTrack}
            />
          )}
        </>
      )}

      {/* 방장 전용 스터디 설정 수정 모달 */}
      {editingStudy && (
        <GroupEditModal
          study={editingStudy}
          onClose={() => setEditingStudy(null)}
          onSaved={handleStudyUpdated}
          notify={showAlert}
        />
      )}

      {/* 이미지 등록 모달 */}
      {showImageSelectModal && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.5)', zIndex: 100000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div style={{ backgroundColor: 'white', borderRadius: '16px', width: '500px', maxWidth: '92vw', boxSizing: 'border-box', overflow: 'hidden', display: 'flex', flexDirection: 'column', boxShadow: '0 20px 40px rgba(0,0,0,0.2)' }}>

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
          <div style={{ backgroundColor: '#ffffff', borderRadius: '12px', padding: '24px 24px 20px', width: '320px', maxWidth: '92vw', boxSizing: 'border-box', boxShadow: '0 4px 20px rgba(0,0,0,0.15)', animation: 'fadeIn 0.2s ease-out' }}>
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
