import React, { useState, useEffect, useCallback } from 'react';
import {
  Users, User, X, MicOff, Video, VideoOff, Maximize, Minimize, Gift, UserPlus,
  Settings, MessageSquare, Calendar, ClipboardList, Mic,
  Search, AlertTriangle, Play, RefreshCw, VolumeX, Volume2, Monitor, Edit2, Send, Check,
  Upload, Download, FileText, MessageCircle
} from 'lucide-react';
import { Client } from '@stomp/stompjs';
import SockJS from 'sockjs-client';
import { OpenVidu } from 'openvidu-browser';
import { useAuth } from '../hooks/useAuth';
import { groupService, timerService, inquiryService } from '../services/api';

// 토론 섹션(1차 의견/서로 피드백/보완 답변)을 "에이전트별 독립 카드"로 재그룹핑한다.
// - 기존 렌더는 섹션 중심(한 카드에 모든 에이전트가 섞임)이라 에이전트별 사고가 구분되지 않았다.
// - 그룹 키는 agentIndex(가장 안정적) → agentId → agentName 순으로 안정적으로 잡아,
//   스트림 재도착/재렌더링이나 응답 순서 변동에도 카드가 뒤섞이지 않게 한다.
// - 같은 에이전트의 1차/보완 답변은 같은 카드에 귀속(중복 카드 생성 방지), 피드백은 작성자(fromAgent)에게 귀속한다.
// - 종합 요약(debateSummary)은 여기서 다루지 않고 별도 카드로 분리해 렌더한다.
const buildDebateAgentCards = (sections) => {
  const sec = sections || {};
  const order = [];
  const byKey = new Map();

  const resolveKey = (idx, id, name) => {
    if (idx !== undefined && idx !== null && idx !== '') return `idx:${idx}`;
    if (id !== undefined && id !== null && id !== '') return `id:${id}`;
    if (name) return `name:${name}`;
    return null;
  };

  const ensure = (key, seedName, seedIndex) => {
    if (!byKey.has(key)) {
      byKey.set(key, { agentKey: key, name: '', index: seedIndex, stage: null, initial: '', revised: '', feedbacks: [] });
      order.push(key);
    }
    const card = byKey.get(key);
    if (!card.name && seedName) card.name = seedName;
    if (card.index == null && seedIndex != null) card.index = seedIndex;
    return card;
  };

  (sec.initialAnswers || []).forEach((it, i) => {
    const key = resolveKey(it.agentIndex, it.agentId, it.agentName) || `fallback:initial:${i}`;
    const card = ensure(key, it.displayName || it.agentName, it.agentIndex);
    if (it.answer) card.initial = it.answer;
    if (it.stage != null) card.stage = it.stage;
  });

  (sec.revisedAnswers || []).forEach((it, i) => {
    const key = resolveKey(it.agentIndex, it.agentId, it.agentName) || `fallback:revised:${i}`;
    const card = ensure(key, it.displayName || it.agentName, it.agentIndex);
    if (it.answer) card.revised = it.answer;
  });

  // 피드백은 "준 사람(fromAgent)" 카드에 귀속시켜 에이전트별로 분리 유지한다.
  (sec.peerFeedbacks || []).forEach((it, i) => {
    const key = resolveKey(it.fromAgentIndex, undefined, it.fromAgentName) || `fallback:fb:${i}`;
    const card = ensure(key, it.fromAgentName, it.fromAgentIndex);
    if (it.feedback) {
      card.feedbacks.push({
        to: it.toAgentName || (it.toAgentIndex != null ? `에이전트 ${it.toAgentIndex}` : ''),
        text: it.feedback,
      });
    }
  });

  return order.map((k) => byKey.get(k));
};

const forceOpenViduWssTransport = (openviduInstance) => {
  if (!openviduInstance || openviduInstance.__studybridgeWssPatched) return;

  const originalStartWs = openviduInstance.startWs?.bind(openviduInstance);
  if (!originalStartWs) return;

  openviduInstance.startWs = (...args) => {
    if (
      typeof window !== 'undefined' &&
      window.location.protocol === 'https:' &&
      typeof openviduInstance.wsUri === 'string' &&
      /^ws:\/\//i.test(openviduInstance.wsUri)
    ) {
      openviduInstance.wsUri = openviduInstance.wsUri.replace(/^ws:\/\//i, 'wss://');
    }

    return originalStartWs(...args);
  };

  openviduInstance.__studybridgeWssPatched = true;
};


// OpenVidu token은 URL 전체가 인증 토큰이므로 원본 그대로 사용한다.
// HTTPS 운영환경에서는 token 문자열이 아니라 실제 WebSocket transport만 wss:// 로 보정한다.
const toSecureWsToken = (token) => {
  return token;
};

// getUserMedia / OpenVidu 장치 오류를 원인별로 구분해 사용자 메시지로 변환한다.
const friendlyDeviceMessage = (err) => {
  const name = err?.name || '';
  const raw = String(err?.name || '') + ' ' + String(err?.message || '');
  switch (name) {
    case 'NotAllowedError':
    case 'PermissionDeniedError':
      return '브라우저 주소창의 카메라/마이크 권한을 허용해주세요.';
    case 'NotReadableError':
    case 'TrackStartError':
      return '다른 화상 앱 또는 브라우저 탭에서 카메라/마이크를 사용 중인지 확인해주세요.';
    case 'OverconstrainedError':
    case 'ConstraintNotSatisfiedError':
      return '선택한 장치를 사용할 수 없어 기본 장치로 다시 시도합니다.';
    case 'NotFoundError':
    case 'DevicesNotFoundError':
      return '사용 가능한 카메라/마이크를 찾을 수 없습니다.';
    default:
      if (/DEVICE_ALREADY_IN_USE/i.test(raw)) {
        return '카메라/마이크가 다른 앱에서 사용 중입니다. 해당 앱을 종료한 뒤 다시 시도해주세요.';
      }
      return err?.message || '카메라/마이크를 초기화할 수 없습니다.';
  }
};

function VideoFeed({ stream, isLocal, displayName, isMuted, isCamOn, isMicOn = true, photoUrl, speakerId, onSpeakingChange }) {
  const videoRef = React.useRef(null);
  const [isSpeaking, setIsSpeaking] = React.useState(false);
  const [micLevel, setMicLevel] = React.useState(0);
  // 실제 비디오 element가 재생을 시작했는지. attach 직후 잠깐은 false → "카메라 연결 중…" 표시.
  const [videoPlaying, setVideoPlaying] = React.useState(false);

  // 발화 상태 변화를 부모로 끌어올려 참여자 목록 등 다른 UI에서도 동일하게 표시한다.
  useEffect(() => {
    if (onSpeakingChange) onSpeakingChange(speakerId, isSpeaking);
  }, [isSpeaking, speakerId, onSpeakingChange]);

  // 언마운트(타일 제거/퇴장) 시 발화 잔상 ring 제거
  useEffect(() => {
    return () => {
      if (onSpeakingChange) onSpeakingChange(speakerId, false);
    };
  }, [speakerId, onSpeakingChange]);

  // 스트림이 바뀌면 재생 준비 상태 초기화(새 트랙 attach 대기).
  useEffect(() => {
    setVideoPlaying(false);
  }, [stream]);

  // 실제 살아있는 video track 유무를 직접 확인한다. isCamOn(켜짐 의도)만 보고 판단하지 않는다.
  //  - 트랙이 진짜 없을 때만 avatar로 떨어진다.
  //  - 트랙이 있는데 아직 재생 전이면 avatar 대신 "카메라 연결 중…"을 보여준다.
  const videoTracks = stream && stream.getVideoTracks ? stream.getVideoTracks() : [];
  const hasLiveVideoTrack = videoTracks.some((t) => t.readyState === 'live');
  const showVideo = !!(isCamOn && stream && hasLiveVideoTrack);
  const showConnecting = showVideo && !videoPlaying;

  // 렌더 후 ref가 생겼을 때 raw MediaStream을 video element에 연결한다(타일 remount/스트림 교체 대응).
  useEffect(() => {
    const v = videoRef.current;
    if (v && stream && showVideo && v.srcObject !== stream) {
      v.srcObject = stream;
    }
  }, [stream, showVideo]);

  // 로컬/원격 오디오 입력 레벨 측정 → 말하는 중 표시 + 입력 레벨 바(실제 입력 감지 여부 가시화).
  useEffect(() => {
    if (!stream || !isMicOn) {
      setIsSpeaking(false);
      setMicLevel(0);
      return;
    }

    const audioTracks = stream.getAudioTracks();
    if (audioTracks.length === 0) {
      setIsSpeaking(false);
      setMicLevel(0);
      return;
    }

    let audioContext;
    let source;
    let analyser;
    let intervalId;

    try {
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
      source = audioContext.createMediaStreamSource(stream);
      analyser = audioContext.createAnalyser();
      analyser.fftSize = 256;
      source.connect(analyser);

      const bufferLength = analyser.frequencyBinCount;
      const dataArray = new Uint8Array(bufferLength);

      intervalId = setInterval(() => {
        if (audioTracks[0] && !audioTracks[0].enabled) {
          setIsSpeaking(false);
          setMicLevel(0);
          return;
        }

        analyser.getByteFrequencyData(dataArray);
        let sum = 0;
        for (let i = 0; i < bufferLength; i++) {
          sum += dataArray[i];
        }
        const average = sum / bufferLength;
        // Average frequency volume threshold: 10
        setIsSpeaking(average > 10);
        // 평균 진폭(대략 0~60)을 0~100% 레벨 바로 정규화.
        setMicLevel(Math.min(100, Math.round((average / 60) * 100)));
      }, 120);
    } catch (e) {
      console.warn("Failed to initialize audio speaking detector", e);
    }

    return () => {
      if (intervalId) clearInterval(intervalId);
      if (source) source.disconnect();
      if (analyser) analyser.disconnect();
      if (audioContext && audioContext.state !== 'closed') {
        audioContext.close();
      }
    };
  }, [stream, isMicOn]);

  const speakBorderColor = isSpeaking ? '#22C55E' : 'rgba(255,255,255,0.05)';
  const speakBoxShadow = isSpeaking
    ? '0 0 20px rgba(34, 197, 94, 0.6), inset 0 0 15px rgba(34, 197, 94, 0.2)'
    : (isLocal ? '0 4px 15px rgba(0,0,0,0.2)' : '0 10px 30px rgba(0,0,0,0.3)');
  const speakBorderWidth = isSpeaking ? '3px' : '1px';

  // 로컬 타일: 마이크가 실제로 입력을 받는지 보이는 레벨 미터 + 말하는 중/입력 대기 중 표시.
  const micMeter = (isLocal && isMicOn) ? (
    <div style={{ position: 'absolute', top: '12px', left: '12px', zIndex: 6, display: 'flex', flexDirection: 'column', gap: '4px', padding: '6px 9px', borderRadius: '10px', backgroundColor: 'rgba(15, 23, 42, 0.6)', backdropFilter: 'blur(8px)', border: `1px solid ${isSpeaking ? 'rgba(34,197,94,0.6)' : 'rgba(255,255,255,0.12)'}` }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
        <Mic size={12} color={isSpeaking ? '#22C55E' : '#9CA3AF'} />
        <span style={{ fontSize: '10px', fontWeight: 700, color: isSpeaking ? '#22C55E' : '#9CA3AF' }}>
          {isSpeaking ? '말하는 중' : (micLevel > 0 ? '입력 감지 중' : '입력 대기 중')}
        </span>
      </div>
      <div style={{ width: '72px', height: '5px', borderRadius: '3px', backgroundColor: 'rgba(255,255,255,0.15)', overflow: 'hidden' }}>
        <div style={{ width: `${micLevel}%`, height: '100%', backgroundColor: isSpeaking ? '#22C55E' : '#60A5FA', transition: 'width 0.1s linear' }} />
      </div>
    </div>
  ) : null;

  const nameTag = (
    <div style={{ position: 'absolute', bottom: '12px', left: '12px', padding: '4px 10px', borderRadius: '20px', backgroundColor: 'rgba(15, 23, 42, 0.6)', backdropFilter: 'blur(8px)', border: '1px solid rgba(255,255,255,0.1)', display: 'flex', alignItems: 'center', gap: '6px' }}>
      {!isMicOn && <MicOff size={13} color="#F87171" />}
      <span style={{ color: 'white', fontSize: '13px', fontWeight: '600' }}>
        {displayName} {isLocal ? '(나)' : ''}
      </span>
    </div>
  );

  if (!showVideo) {
    return (
      <div style={{ position: 'relative', backgroundColor: '#1E293B', borderRadius: '16px', overflow: 'hidden', aspectRatio: '16/9', border: `${speakBorderWidth} solid ${speakBorderColor}`, display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: speakBoxShadow, transition: 'all 0.2s ease' }}>
        {photoUrl ? (
          <img
            src={photoUrl}
            alt={displayName}
            style={{ width: '64px', height: '64px', borderRadius: '50%', objectFit: 'cover', boxShadow: '0 8px 24px rgba(0,0,0,0.4)' }}
          />
        ) : (
          <div style={{ width: '64px', height: '64px', borderRadius: '50%', backgroundColor: '#334155', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 8px 24px rgba(0,0,0,0.4)' }}>
            <User size={32} color="#9CA3AF" />
          </div>
        )}
        {micMeter}
        {nameTag}
      </div>
    );
  }

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%', backgroundColor: '#1E293B', borderRadius: '16px', overflow: 'hidden', aspectRatio: '16/9', border: `${speakBorderWidth} solid ${speakBorderColor}`, boxShadow: speakBoxShadow, transition: 'all 0.2s ease' }}>
      <video
        ref={videoRef}
        autoPlay
        playsInline
        muted={isMuted}
        onPlaying={() => setVideoPlaying(true)}
        onLoadedData={() => setVideoPlaying(true)}
        style={{ width: '100%', height: '100%', objectFit: 'cover' }}
      />
      {showConnecting && (
        <div style={{ position: 'absolute', inset: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '8px', backgroundColor: 'rgba(30,41,59,0.85)', color: '#CBD5E1', zIndex: 4 }}>
          <Video size={28} color="#60A5FA" />
          <span style={{ fontSize: '13px', fontWeight: 600 }}>카메라 연결 중…</span>
        </div>
      )}
      {!isMicOn && (
        <div style={{ position: 'absolute', top: '12px', right: '12px', width: '28px', height: '28px', borderRadius: '50%', backgroundColor: 'rgba(15, 23, 42, 0.7)', backdropFilter: 'blur(8px)', border: '1px solid rgba(248,113,113,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <MicOff size={15} color="#F87171" />
        </div>
      )}
      {micMeter}
      {nameTag}
    </div>
  );
}

export default function StudyRoom({ study, onClose, selectedCamera, initialMicOn, initialVideoOn }) {
  const { userId, user } = useAuth();
  
  const formatSecondsToStudyTime = (secs) => {
    if (!secs && secs !== 0) return '-';
    const hrs = Math.floor(secs / 3600);
    const mins = Math.floor((secs % 3600) / 60);
    return `${hrs}시간 ${mins}분`;
  };

  const formatAttendanceTime = (isoString) => {
    if (!isoString) return '-';
    try {
      const date = new Date(isoString);
      const today = new Date();
      const isToday = date.toDateString() === today.toDateString();
      const formatted = date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
      return isToday ? `오늘 ${formatted}` : `${date.getMonth() + 1}월 ${date.getDate()}일 ${formatted}`;
    } catch {
      return isoString;
    }
  };

  const [members, setMembers] = useState([]);
  const [applications, setApplications] = useState([]);
  const [activeTab, setActiveTab] = useState('chat');
  // 입장 전 미리보기에서 사용자가 선택한 카메라/마이크 ON/OFF 상태를 그대로 이어받는다(상태 불일치 방지).
  const [isMicOn, setIsMicOn] = useState(typeof initialMicOn === 'boolean' ? initialMicOn : false);
  const [isVideoOn, setIsVideoOn] = useState(typeof initialVideoOn === 'boolean' ? initialVideoOn : true);
  const [showSettings, setShowSettings] = useState(false);
  const [showStatsModal, setShowStatsModal] = useState(false);
  const [showRoomManageModal, setShowRoomManageModal] = useState(false);
  const [roomManageTab, setRoomManageTab] = useState('settings'); // 'settings' | 'members'
  const [showAdminReportModal, setShowAdminReportModal] = useState(false);
  const [adminReportTab, setAdminReportTab] = useState('inquiry'); // 'inquiry' | 'report'
  const [reportUserId, setReportUserId] = useState('');
  const [reportReasonType, setReportReasonType] = useState('욕설 / 비방 / 혐오 발언');
  const [reportDetail, setReportDetail] = useState('');
  const [inquiryType, setInquiryType] = useState('이용 문의');
  const [inquiryTitle, setInquiryTitle] = useState('');
  const [inquiryContent, setInquiryContent] = useState('');
  const [isCamFullScreen, setIsCamFullScreen] = useState(false);

  const [chatMessages, setChatMessages] = useState([]);
  const [chatInput, setChatInput] = useState('');
  const [stompClient, setStompClient] = useState(null);
  
  // 채팅 전용 드로어(왼쪽 사이드바 말풍선 아이콘으로 열고 닫음). 닫아도 메시지 상태는 상위 컴포넌트에 보존된다.
  const [showChatDrawer, setShowChatDrawer] = useState(false);

  // AI Multi-Agent SSE Streaming Chat states
  const [chatTab, setChatTab] = useState('normal'); // 'normal' | 'ai'
  const [aiMessages, setAiMessages] = useState([]);
  const [aiInput, setAiInput] = useState('');
  const [isAiStreaming, setIsAiStreaming] = useState(false);
  // 사용자가 직접 설정한 그룹스터디 AI 봇 (세션 단위). 비어있으면 기본 요약/퀴즈/검색봇을 사용한다.
  const [aiBots, setAiBots] = useState([]); // [{ name, personality, knowledgeLevel, requirement }]
  const [showAiBotConfig, setShowAiBotConfig] = useState(false);
  // 그룹스터디 AI 라이브 모드 (세션 단위). StudyMate와 동일한 6모드.
  const [aiMode, setAiMode] = useState('basic');

  // 동시 전송/중복 SSE 연결 방어.
  //  - isAiStreaming(state)는 setState가 비동기라 Enter키 + 전송버튼 동시 입력을 못 막는다 → ref로 동기 차단.
  //  - activeAiRequestRef: 이번 턴 requestId. 이전 요청에서 늦게 도착하는 이벤트는 전부 무시한다.
  //  - aiAbortRef: 진행 중인 fetch 스트림. 새 전송/언마운트 시 반드시 abort()로 끊는다.
  const aiSendingRef = React.useRef(false);
  const activeAiRequestRef = React.useRef(null);
  const aiAbortRef = React.useRef(null);
  // 토론/상황극 멀티턴 상태(논제/세션/선택지/턴). 응답 이벤트에서 캡처해 다음 요청 payload에 echo한다.
  //  → ai07가 같은 논제 후보/선택지를 반복하지 않고 다음 단계(찬성·반대·반박·요약 / 반응·결과)로 진행한다.
  //  (FastAPI가 해당 필드를 보낼 때만 채워지며, 없으면 빈 객체로 무해하게 동작한다.)
  const aiConvStateRef = React.useRef({});

  // 새 메시지 도착 시 채팅 목록을 하단으로 자동 스크롤하기 위한 sentinel ref
  const chatEndRef = React.useRef(null);
  const aiEndRef = React.useRef(null);

  // 컴포넌트 unmount 시 진행 중인 AI 스트림을 반드시 끊는다(중복 연결/유령 append 방지).
  useEffect(() => {
    return () => {
      if (aiAbortRef.current) { try { aiAbortRef.current.abort(); } catch (e) { /* noop */ } }
      activeAiRequestRef.current = null;
      aiSendingRef.current = false;
    };
  }, []);
  
  const [activeQuiz, setActiveQuiz] = useState(null);
  const [quizSessionId, setQuizSessionId] = useState(null);
  const quizSessionIdRef = React.useRef(null);
  const quizQuestionIdRef = React.useRef(null);
  // 남은 시간 카운트다운 기준점(로컬 epoch ms). 서버 remainingSeconds를 기준으로 잡아
  // 서버/브라우저 타임존 차이에 영향받지 않게 한다.
  const quizDeadlineRef = React.useRef(null);
  const [quizPhase, setQuizPhase] = useState('IDLE');
  const [quizTimer, setQuizTimer] = useState(0);
  const [quizQuestionEndsAt, setQuizQuestionEndsAt] = useState(null);
  const [quizScoreboard, setQuizScoreboard] = useState(null);
  const [quizReveal, setQuizReveal] = useState(null);
  const [quizSelectedAnswer, setQuizSelectedAnswer] = useState(null);
  const [quizHasSubmitted, setQuizHasSubmitted] = useState(false);
  const [quizStartTime, setQuizStartTime] = useState(null);
  const [quizSubmissionAck, setQuizSubmissionAck] = useState(null);
  const [quizFinalResult, setQuizFinalResult] = useState(null);
  const [quizError, setQuizError] = useState(null);
  const [quizIdInput, setQuizIdInput] = useState('1');
  const [groupMaterials, setGroupMaterials] = useState([]);
  const [groupQuizzes, setGroupQuizzes] = useState([]);
  const [showPdfUploadModal, setShowPdfUploadModal] = useState(false);
  const [quizUploadTitle, setQuizUploadTitle] = useState('');
  const [quizUploadFile, setQuizUploadFile] = useState(null);
  const [isUploadingQuizPdf, setIsUploadingQuizPdf] = useState(false);
  const [quizUploadError, setQuizUploadError] = useState('');
  
  const [session, setSession] = useState(null);
  const sessionRef = React.useRef(null); // 강퇴 이벤트 수신 시 최신 세션에 즉시 접근하기 위한 ref
  const [publisher, setPublisher] = useState(null);
  const [subscribers, setSubscribers] = useState([]);
  const [ovError, setOvError] = useState('');
  // 장치 fallback 안내(치명적 오류 아님: camera-only / audio-only / viewer-only 입장 등)
  const [ovNotice, setOvNotice] = useState('');
  // 현재 발화 중인 사용자 id 집합 (참여자 목록 ring 표시용)
  const [speakingUsers, setSpeakingUsers] = useState(() => new Set());

  const handleSpeakingChange = useCallback((speakerId, speaking) => {
    if (speakerId === null || speakerId === undefined) return;
    const key = String(speakerId);
    setSpeakingUsers(prev => {
      const has = prev.has(key);
      if (speaking === has) return prev; // 변화 없으면 동일 참조 반환 → 불필요한 리렌더 방지
      const next = new Set(prev);
      if (speaking) next.add(key); else next.delete(key);
      return next;
    });
  }, []);

  const myMember = members.find(m => Number(m.userId) === Number(userId));
  const canUseGroupQuizMaterials = Boolean(myMember || members.some(m => Number(m.userId) === Number(userId)));
  const myDisplayName = user?.displayName || user?.nickname || `User_${userId}`;

  // OpenVidu subscriber의 connection.data에서 userId를 안전하게 추출한다.
  const parseSubscriberUserId = (sub) => {
    try {
      return JSON.parse(sub.stream.connection.data).userId;
    } catch (e) {
      return null;
    }
  };

  // 강퇴/퇴장된 유저를 참가자 목록과 화상 타일(subscribers)에서 한 번에 제거한다.
  const removeParticipantEverywhere = (targetUserId) => {
    if (targetUserId == null) return;
    console.log('[video:remove] userId=', targetUserId);
    setMembers(prev => prev.filter(m => String(m.userId) !== String(targetUserId)));
    setSubscribers(prev => prev.filter(sub => String(parseSubscriberUserId(sub)) !== String(targetUserId)));
  };

  const formatShortDateTime = (value) => {
    if (!value) return '-';
    try {
      return new Date(value).toLocaleString([], {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit'
      });
    } catch {
      return value;
    }
  };

  const formatFileSize = (bytes) => {
    if (!bytes && bytes !== 0) return '-';
    const size = Number(bytes);
    if (Number.isNaN(size)) return '-';
    if (size < 1024 * 1024) return `${Math.max(1, Math.round(size / 1024))}KB`;
    return `${(size / 1024 / 1024).toFixed(1)}MB`;
  };

  const loadMembers = async () => {
    try {
      const data = await groupService.getMembers(study.id);
      setMembers(data);
    } catch (err) {
      console.error('Failed to load members', err);
    }
  };

  const loadApplications = async () => {
    try {
      if (Number(study.leaderId) === Number(userId)) {
        const data = await groupService.getApplications(study.id);
        setApplications(data);
      }
    } catch (err) {
      console.error('Failed to load applications', err);
    }
  };

  const loadGroupMaterials = async () => {
    if (!study?.id) return;
    try {
      const data = await groupService.getGroupMaterials(study.id);
      setGroupMaterials(data || []);
    } catch (err) {
      console.error('Failed to load group materials', err);
    }
  };

  const loadGroupQuizzes = async () => {
    if (!study?.id) return;
    try {
      const data = await groupService.getGroupQuizzes(study.id);
      setGroupQuizzes(data || []);
    } catch (err) {
      console.error('Failed to load group quizzes', err);
    }
  };

  const applyQuizSessionPayload = (payload) => {
    if (!payload) return;
    const previousQuestionId = quizQuestionIdRef.current;
    const incomingQuestionId = payload.questionId ?? null;
    const isNewQuestion = previousQuestionId == null || incomingQuestionId == null
      ? true
      : Number(previousQuestionId) !== Number(incomingQuestionId);

    setQuizSessionId(payload.sessionId ?? null);
    quizSessionIdRef.current = payload.sessionId ?? null;
    setQuizPhase(payload.phase || 'QUESTION');
    setActiveQuiz({
      quizId: payload.quizId,
      quizTitle: payload.quizTitle,
      questionId: payload.questionId,
      questionText: payload.questionText,
      options: payload.options || [],
      currentIndex: payload.currentIndex ?? 0,
      totalQuestions: payload.totalQuestions ?? 0,
      timeLimitSeconds: payload.timeLimitSeconds ?? 30,
    });
    quizQuestionIdRef.current = payload.questionId ?? null;
    setQuizQuestionEndsAt(payload.questionEndsAt || null);
    // 타임존 안전: remainingSeconds가 있으면 로컬 시계 기준 deadline을 잡는다.
    if (typeof payload.remainingSeconds === 'number') {
      quizDeadlineRef.current = Date.now() + payload.remainingSeconds * 1000;
      setQuizTimer(payload.remainingSeconds);
    } else if (payload.questionEndsAt) {
      quizDeadlineRef.current = new Date(payload.questionEndsAt).getTime();
      setQuizTimer(Math.max(0, Math.ceil((quizDeadlineRef.current - Date.now()) / 1000)));
    } else {
      quizDeadlineRef.current = null;
      setQuizTimer(0);
    }
    const shouldShowScoreboard = payload.phase === 'REVEAL' || payload.phase === 'ENDED';
    setQuizScoreboard(shouldShowScoreboard && Array.isArray(payload.scoreboard) ? payload.scoreboard : null);
    setQuizReveal(payload.phase === 'REVEAL' || payload.phase === 'ENDED'
      ? {
          correctAnswer: payload.correctAnswer,
          pointsAwarded: payload.pointsAwarded,
          message: payload.message || '',
      }
      : null);
    if (typeof payload.userSubmitted === 'boolean') {
      setQuizSelectedAnswer(typeof payload.userSubmittedAnswer === 'number' ? payload.userSubmittedAnswer : null);
      setQuizHasSubmitted(payload.userSubmitted);
    } else if (isNewQuestion) {
      setQuizSelectedAnswer(null);
      setQuizHasSubmitted(false);
    }
    const resolvedTimeLimit = payload.timeLimitSeconds ?? 30;
    const resolvedRemaining = typeof payload.remainingSeconds === 'number' ? payload.remainingSeconds : null;
    setQuizStartTime(
      resolvedRemaining != null
        ? Date.now() - Math.max(0, (resolvedTimeLimit - resolvedRemaining) * 1000)
        : Date.now()
    );
    setQuizSubmissionAck(null);
    setQuizFinalResult(payload.phase === 'ENDED' ? payload : null);
  };

  const resetQuizRuntimeState = () => {
    setQuizSessionId(null);
    quizSessionIdRef.current = null;
    setQuizPhase('IDLE');
    setActiveQuiz(null);
    setQuizQuestionEndsAt(null);
    quizQuestionIdRef.current = null;
    quizDeadlineRef.current = null;
    setQuizTimer(0);
    setQuizScoreboard(null);
    setQuizReveal(null);
    setQuizSelectedAnswer(null);
    setQuizHasSubmitted(false);
    setQuizStartTime(null);
    setQuizSubmissionAck(null);
    setQuizFinalResult(null);
  };

  useEffect(() => {
    if (!study?.id) return;
    loadGroupMaterials();
    loadGroupQuizzes();
  }, [study?.id]);

  // 1. OpenVidu Video Call Lifecycle
  useEffect(() => {
    if (!study?.id || !userId) return;

    let OVInstance = null;
    let sessionInstance = null;
    let isMounted = true;

    async function joinSession() {
      try {
        let { token } = await groupService.getVideoToken(study.id);
        if (!isMounted) return;

        // OpenVidu token은 서버가 발급한 문자열을 그대로 사용한다.
        token = toSecureWsToken(token);
          OVInstance = new OpenVidu();
          forceOpenViduWssTransport(OVInstance);
          sessionInstance = OVInstance.initSession();
sessionInstance.on('streamCreated', (event) => {
          const subscriber = sessionInstance.subscribe(event.stream, undefined);
          if (isMounted) {
            setSubscribers(prev => [...prev, subscriber]);
          }
        });

        sessionInstance.on('streamDestroyed', (event) => {
          if (isMounted) {
            setSubscribers(prev => prev.filter(sub => sub !== event.stream.streamManager));
          }
        });

        // 연결 자체가 끊긴 경우(강퇴 후 자가 disconnect, 브라우저 종료 등) 잔존 타일을 추가로 정리한다.
        sessionInstance.on('connectionDestroyed', (event) => {
          if (!isMounted) return;
          let goneUserId = null;
          try {
            goneUserId = JSON.parse(event.connection.data).userId;
          } catch (e) { /* ignore */ }
          const goneConnId = event.connection.connectionId;
          setSubscribers(prev => prev.filter(sub => {
            try {
              return sub.stream.connection.connectionId !== goneConnId
                && String(JSON.parse(sub.stream.connection.data).userId) !== String(goneUserId);
            } catch (e) {
              return true;
            }
          }));
        });

        // 원격 참가자가 카메라/마이크를 끄거나 켜면(videoActive/audioActive 변경) 즉시 리렌더하여
        // avatar fallback 전환과 마이크 상태 아이콘이 실시간으로 반영되게 한다.
        sessionInstance.on('streamPropertyChanged', (event) => {
          if (isMounted) {
            setSubscribers(prev => [...prev]); // 새 배열 참조로 리렌더 트리거 (stream 객체의 최신 active 값 반영)
          }
        });

        sessionInstance.on('exception', (exception) => {
          console.warn('OpenVidu Exception:', exception);
        });

        const connectionData = JSON.stringify({ userId: userId, clientData: myDisplayName });
        await sessionInstance.connect(token, connectionData);
        if (!isMounted) return;

        setSession(sessionInstance);
        sessionRef.current = sessionInstance;

        // 이전 프리뷰 화면에서 사용하던 카메라 하드웨어가 완전히 릴리즈될 시간을 확보 (800ms).
        // 너무 짧으면 카메라가 아직 점유돼 NotReadableError가 나고, 아래 fallback이 곧바로
        // 오디오 전용으로 떨어뜨려 "카메라 ON인데 아바타로 보이는" 문제가 생긴다.
        await new Promise(resolve => setTimeout(resolve, 800));
        if (!isMounted) return;

        // ── 장치 유효성 사전 검증 (stale deviceId / 장치 부재 방어) ──
        // 선택된 카메라 deviceId가 현재 실제 장치 목록에 없으면 stale로 간주해 기본 카메라로 떨어뜨린다.
        let videoDeviceId = selectedCamera || undefined;
        let hasAnyVideo = true;
        let hasAnyAudio = true;
        try {
          const devices = await navigator.mediaDevices.enumerateDevices();
          const videoInputs = devices.filter(d => d.kind === 'videoinput');
          const audioInputs = devices.filter(d => d.kind === 'audioinput');
          hasAnyVideo = videoInputs.length > 0;
          hasAnyAudio = audioInputs.length > 0;
          if (videoDeviceId && !videoInputs.some(d => d.deviceId === videoDeviceId)) {
            console.warn('[StudyRoom] 선택 카메라가 stale → 기본 카메라로 대체. id=', String(videoDeviceId).slice(0, 4) + '****');
            videoDeviceId = undefined;
          }
          console.log('[StudyRoom] 장치 점검 video=%d audio=%d', videoInputs.length, audioInputs.length);
        } catch (enumErr) {
          console.warn('[StudyRoom] enumerateDevices 실패, 기본값으로 진행', enumErr?.name || enumErr);
        }

        const buildOpts = (vSource, aSource) => ({
          audioSource: aSource,
          videoSource: vSource,
          publishAudio: aSource !== false && isMicOn,
          publishVideo: vSource !== false && isVideoOn,
          resolution: '640x480',
          frameRate: 30,
          insertMode: 'APPEND',
          mirror: true
        });

        // fallback 순서: 카메라+마이크 → 카메라만 → 기본카메라만 → 마이크만 → 시청전용
        const attempts = [];
        if (hasAnyVideo && hasAnyAudio) attempts.push({ v: videoDeviceId, a: undefined, tag: 'camera+mic' });
        if (hasAnyVideo) attempts.push({ v: videoDeviceId, a: false, tag: 'camera-only' });
        if (hasAnyVideo && videoDeviceId) attempts.push({ v: undefined, a: false, tag: 'default-camera-only' });
        if (hasAnyAudio) attempts.push({ v: false, a: undefined, tag: 'audio-only' });
        attempts.push({ v: false, a: false, tag: 'viewer-only' });

        let publisherInstance = null;
        let chosen = null;
        let lastErr = null;
        // 카메라가 포함된 단계는 일시적 점유(NotReadableError/TrackStartError 등)일 수 있으므로
        // 곧바로 다음 단계(오디오 전용)로 떨어뜨리지 않고 짧은 backoff로 재시도한다.
        const tryInit = async (opts, retries) => {
          for (let i = 0; i <= retries; i += 1) {
            try {
              return await OVInstance.initPublisherAsync(undefined, opts);
            } catch (e) {
              lastErr = e;
              const transient = ['NotReadableError', 'TrackStartError', 'OverconstrainedError', 'AbortError'].includes(e?.name);
              console.warn('[StudyRoom] publisher 시도 실패 name=%s transient=%s retryLeft=%d', e?.name || e, transient, transient ? retries - i : 0);
              if (!transient || i === retries || !isMounted) return null;
              await new Promise((r) => setTimeout(r, 600 * (i + 1)));
            }
          }
          return null;
        };
        for (const att of attempts) {
          const isCameraAttempt = att.v !== false; // 카메라를 켜는 단계만 재시도(오디오/시청 전용은 1회)
          publisherInstance = await tryInit(buildOpts(att.v, att.a), isCameraAttempt ? 2 : 0);
          if (!isMounted) break;
          if (publisherInstance) {
            chosen = att;
            console.log('[StudyRoom] publisher 성공 단계=%s', att.tag);
            break;
          }
        }

        if (!isMounted) {
          if (publisherInstance) publisherInstance.dispose();
          return;
        }

        if (!publisherInstance) {
          // 모든 단계 실패: 세션 연결은 유지되므로 시청자 상태로 남긴다.
          setIsMicOn(false);
          setIsVideoOn(false);
          setOvError(friendlyDeviceMessage(lastErr));
          setOvNotice('');
          return;
        }

        // 실제 발행된 트랙 상태를 토글 UI와 동기화
        const noVideo = chosen.v === false;
        const noAudio = chosen.a === false;
        if (noAudio) setIsMicOn(false);
        if (noVideo) setIsVideoOn(false);
        if (noVideo && noAudio) {
          setOvNotice('사용 가능한 카메라/마이크가 없어 시청 모드로 입장했습니다.');
        } else if (noVideo) {
          setOvNotice('카메라 장치를 찾을 수 없어 오디오만 사용합니다.');
        } else if (noAudio) {
          setOvNotice('마이크 장치를 찾을 수 없어 음소거 상태로 입장했습니다.');
        } else {
          setOvNotice('');
        }

        if (noVideo && noAudio) {
          // 시청 전용: 발행할 트랙이 없으므로 publisher를 publish하지 않고 정리한다.
          publisherInstance.dispose();
          setOvError('');
        } else {
          await sessionInstance.publish(publisherInstance);
          setPublisher(publisherInstance);
          setOvError('');
        }

      } catch (err) {
        console.error('Failed to join OpenVidu video session:', err);
        if (isMounted) {
          setOvError(err.message || '카메라/마이크를 초기화할 수 없습니다. 장치를 확인해주세요.');
        }
      }
    }

    joinSession();

    return () => {
      isMounted = false;
      if (sessionInstance) {
        sessionInstance.disconnect();
      }
      sessionRef.current = null;
      setSession(null);
      setPublisher(null);
      setSubscribers([]);
    };
  }, [study?.id, userId, myDisplayName]);

  const updateStudyStatus = async (status) => {
    try {
      await groupService.updateStudyStatus(study.id, status);
      showAlert('성공', `스터디 상태가 '${status}'(으)로 변경되었습니다.`);
    } catch (error) {
      showAlert('오류', error.response?.data?.message || '스터디 상태 변경에 실패했습니다.');
    }
  };

  // 2. Local Stream Track Publish Control Effects
  useEffect(() => {
    if (publisher) {
      publisher.publishAudio(isMicOn);
    }
  }, [isMicOn, publisher]);

  useEffect(() => {
    if (publisher) {
      publisher.publishVideo(isVideoOn);
    }
  }, [isVideoOn, publisher]);

  // 3. STOMP & WebRTC Lifecycle
  useEffect(() => {
    if (!study?.id || !userId) return;

    const hostname = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
    const protocol = typeof window !== 'undefined' && window.location.protocol === 'https:' ? 'https' : 'http';
    // 운영(배포)에서는 같은 오리진으로 연결한다. Nginx가 /ws-group → Spring(8080)으로 프록시하며,
    // HTTPS 운영환경에서는 현재 origin(https://www.studybridge.co.kr) 기준으로 SockJS에 연결한다.
    const isLocalDev = ['localhost', '127.0.0.1'].includes(hostname);
    const serverURL =
      import.meta.env.VITE_API_BASE_URL ||
      import.meta.env.VITE_BACKEND_URL ||
      (isLocalDev ? `${protocol}://${hostname}:8080` : window.location.origin);

    const token = localStorage.getItem('token');

    const client = new Client({
      webSocketFactory: () => new SockJS(`${window.location.origin}/ws-group`, null, { credentials: false }),
      connectHeaders: {
        Authorization: token ? `Bearer ${token}` : ''
      },
      reconnectDelay: 5000,
      heartbeatIncoming: 4000,
      heartbeatOutgoing: 4000,
    });

    client.onConnect = (frame) => {
      console.log('Connected to group study socket: ' + frame);

      const shouldAcceptSession = (payload) => {
        if (!payload?.sessionId || !quizSessionIdRef.current) return true;
        return Number(payload.sessionId) === Number(quizSessionIdRef.current);
      };

      const applyPayload = (payload) => {
        if (!shouldAcceptSession(payload)) return;
        applyQuizSessionPayload(payload);
      };

      client.subscribe(`/topic/group/${study.id}/chat`, (message) => {
        const payload = JSON.parse(message.body);
        setChatMessages(prev => [...prev, payload]);
      });

      // 참가자 변동(강퇴/퇴장/정지) 실시간 수신: 화상 타일과 참가자 목록에서 즉시 제거한다.
      client.subscribe(`/topic/group/${study.id}/members`, (message) => {
        let event;
        try {
          event = JSON.parse(message.body);
        } catch (e) {
          console.warn('[video:event] parse failed', e);
          return;
        }
        console.log('[video:event] type=', event?.type, 'targetUserId=', event?.targetUserId);
        const removalTypes = ['PARTICIPANT_LEFT', 'PARTICIPANT_KICKED', 'PARTICIPANT_BANNED', 'PARTICIPANT_DISCONNECTED'];
        if (!removalTypes.includes(event?.type)) return;

        // 1) 대상이 본인이면 즉시 세션 종료 후 방에서 나간다.
        if (String(event.targetUserId) === String(userId)) {
          console.log('[video:self-kicked] userId=', userId);
          try {
            sessionRef.current?.disconnect();
          } catch (e) {
            console.warn('[video] disconnect failed after kick/leave', e);
          }
          const msg = event.type === 'PARTICIPANT_KICKED'
            ? '방장에 의해 그룹스터디에서 강제 퇴장되었습니다.'
            : '그룹스터디 참여가 종료되어 화상채팅에서 나갑니다.';
          alert(msg);
          onClose?.();
          return;
        }

        // 2) 그 외 참가자는 목록/타일에서 제거한다.
        removeParticipantEverywhere(event.targetUserId);
      });

      client.subscribe(`/topic/group/${study.id}/quiz/session`, (message) => {
        const payload = JSON.parse(message.body);
        applyPayload(payload);
      });

      client.subscribe(`/topic/group/${study.id}/quiz/question`, (message) => {
        const payload = JSON.parse(message.body);
        console.log('Received quiz question:', payload);
        applyPayload(payload);
      });

      client.subscribe(`/topic/group/${study.id}/quiz/next`, (message) => {
        const payload = JSON.parse(message.body);
        console.log('Received quiz next:', payload);
        applyPayload(payload);
      });

      client.subscribe(`/topic/group/${study.id}/quiz/timer`, (message) => {
        const payload = JSON.parse(message.body);
        if (!shouldAcceptSession(payload)) return;
        if (typeof payload.remainingSeconds === 'number') {
          // 서버 기준 남은 시간으로 로컬 deadline 재동기화 (타임존 무관).
          quizDeadlineRef.current = Date.now() + payload.remainingSeconds * 1000;
          setQuizTimer(payload.remainingSeconds);
        }
        if (payload.questionEndsAt) {
          setQuizQuestionEndsAt(payload.questionEndsAt);
        }
      });

      client.subscribe(`/topic/group/${study.id}/quiz/submitted`, (message) => {
        const payload = JSON.parse(message.body);
        if (!shouldAcceptSession(payload)) return;
        if (payload.questionId && quizQuestionIdRef.current && Number(payload.questionId) !== Number(quizQuestionIdRef.current)) return;
        setQuizSubmissionAck(payload);
        setQuizHasSubmitted(Boolean(payload.accepted));
        if (!payload.accepted) {
          setQuizSelectedAnswer(null);
        }
      });

      client.subscribe(`/topic/group/${study.id}/quiz/reveal`, (message) => {
        const payload = JSON.parse(message.body);
        if (!shouldAcceptSession(payload)) return;
        setQuizPhase('REVEAL');
        setQuizReveal({
          correctAnswer: payload.correctAnswer,
          pointsAwarded: payload.pointsAwarded,
          message: payload.message || '',
        });
        setQuizScoreboard(Array.isArray(payload.scoreboard) ? payload.scoreboard : null);
      });

      client.subscribe(`/topic/group/${study.id}/quiz/scoreboard`, (message) => {
        const payload = JSON.parse(message.body);
        console.log('Received quiz scoreboard:', payload);
        if (!shouldAcceptSession(payload)) return;
        setQuizScoreboard(Array.isArray(payload.scoreboard) ? payload.scoreboard : null);
        if (payload.phase === 'REVEAL') {
          setQuizPhase('REVEAL');
          setQuizReveal({
            correctAnswer: payload.correctAnswer,
            pointsAwarded: payload.pointsAwarded,
            message: payload.message || '',
          });
        }
        if (payload.phase === 'ENDED') {
          setQuizPhase('ENDED');
          setQuizFinalResult(payload);
        }
      });

      client.subscribe(`/topic/group/${study.id}/quiz/end`, (message) => {
        const payload = JSON.parse(message.body);
        if (!shouldAcceptSession(payload)) return;
        setQuizPhase('ENDED');
        setQuizFinalResult(payload);
        setQuizScoreboard(Array.isArray(payload.scoreboard) ? payload.scoreboard : null);
      });

      // 퀴즈 시작 실패: 가짜 문제/0초 화면 대신 명확한 에러를 보여준다.
      client.subscribe(`/topic/group/${study.id}/quiz/error`, (message) => {
        const payload = JSON.parse(message.body);
        console.warn('Received quiz error:', payload);
        resetQuizRuntimeState();
        setQuizError(payload?.message || '퀴즈를 시작하지 못했습니다.');
      });

      groupService.getQuizSession(study.id)
        .then((payload) => {
          if (payload) {
            applyPayload(payload);
          }
        })
        .catch((err) => {
          if (import.meta.env.DEV) console.debug('No active quiz session to restore', err?.response?.status || err?.message || err);
        });
    };

    client.onStompError = (frame) => {
      console.error('STOMP error', frame);
    };

    client.activate();
    setStompClient(client);

    return () => {
      if (client) {
        client.deactivate();
      }
    };
  }, [study?.id, userId, myDisplayName]);

  // 퀴즈 타이머 이펙트: 로컬 deadline(quizDeadlineRef) 기준으로 남은 시간을 매초 갱신한다.
  // QUESTION/NEXT 단계에서만 카운트다운하며, 서버 remainingSeconds로 anchor된 deadline을 사용해
  // 서버/브라우저 타임존 차이의 영향을 받지 않는다.
  useEffect(() => {
    if (quizPhase !== 'QUESTION' && quizPhase !== 'NEXT') {
      return;
    }
    if (!quizDeadlineRef.current) {
      return;
    }

    const syncTimer = () => {
      if (!quizDeadlineRef.current) return;
      const diff = Math.ceil((quizDeadlineRef.current - Date.now()) / 1000);
      setQuizTimer(Math.max(0, diff));
    };

    syncTimer();
    const interval = setInterval(syncTimer, 1000);
    return () => clearInterval(interval);
  }, [quizPhase, quizQuestionEndsAt]);

  const handleQuizSubmit = (answerIndex) => {
    if (quizHasSubmitted || !activeQuiz || !stompClient || !stompClient.connected) return;
    if (quizTimer <= 0) {
      showAlert('알림', '제한 시간이 종료되었습니다. 정답 공개를 기다려주세요.');
      return;
    }
    if (quizPhase !== 'QUESTION' && quizPhase !== 'NEXT') return;

    setQuizSelectedAnswer(answerIndex);
    setQuizHasSubmitted(true);

    const timeTaken = quizStartTime ? Math.round((Date.now() - quizStartTime) / 1000) : 5;

    stompClient.publish({
      destination: `/pub/group/${study.id}/quiz/submit`,
      body: JSON.stringify({
        userId: userId,
        questionId: activeQuiz.questionId,
        submittedAnswer: answerIndex,
        timeTakenSeconds: timeTaken
      })
    });
  };

  const handleQuizStart = (quizId) => {
    if (!stompClient || !stompClient.connected) {
      showAlert('오류', '웹소켓 서버가 연결되어 있지 않습니다. 잠시 후 다시 시도해주세요.');
      return;
    }
    if (!quizId) {
      showAlert('오류', '퀴즈 ID를 입력해주세요.');
      return;
    }
    setQuizError(null);

    stompClient.publish({
      destination: `/pub/group/${study.id}/quiz/start`,
      body: JSON.stringify({
        quizId: Number(quizId),
        userId: userId
      })
    });
  };

  const handleDownloadGroupMaterial = async (materialId) => {
    try {
      const data = await groupService.getGroupMaterialDownloadUrl(materialId);
      const url = data?.downloadUrl || data?.url;
      if (!url) {
        showAlert('오류', '다운로드 URL을 발급받지 못했습니다.');
        return;
      }
      window.open(url, '_blank', 'noopener,noreferrer');
    } catch (err) {
      showAlert('오류', err.response?.data?.message || '자료 다운로드 URL 발급에 실패했습니다.');
    }
  };

  const [regeneratingMaterialId, setRegeneratingMaterialId] = useState(null);
  const handleRegenerateQuiz = async (materialId) => {
    if (regeneratingMaterialId) return;
    setRegeneratingMaterialId(materialId);
    try {
      await groupService.generateMaterialQuiz(study.id, materialId);
      await loadGroupQuizzes();
      showAlert('완료', '해당 자료로 새 퀴즈를 생성했습니다.');
    } catch (err) {
      showAlert('오류', err.response?.data?.message || '퀴즈 생성에 실패했습니다. 잠시 후 다시 시도해주세요.');
    } finally {
      setRegeneratingMaterialId(null);
    }
  };

  const handleUploadQuizPdf = async () => {
    const title = quizUploadTitle.trim();

    if (!title) {
      showAlert('오류', '자료 제목을 입력해주세요.');
      return;
    }

    if (!quizUploadFile) {
      showAlert('오류', 'PDF 파일을 선택해주세요.');
      return;
    }

    const isPdf =
      quizUploadFile.type === 'application/pdf' ||
      quizUploadFile.name.toLowerCase().endsWith('.pdf');

    if (!isPdf) {
      showAlert('오류', 'PDF 파일만 업로드할 수 있습니다.');
      return;
    }

    if (quizUploadFile.size > 30 * 1024 * 1024) {
      showAlert('오류', 'PDF 파일은 30MB 이하만 업로드할 수 있습니다.');
      return;
    }

    setIsUploadingQuizPdf(true);
    setQuizUploadError('');

    try {
      await groupService.uploadQuizMaterial(study.id, title, quizUploadFile);

      showAlert('완료', 'PDF가 등록되었고 AI 퀴즈 생성이 완료되었습니다.');
      setShowPdfUploadModal(false);
      setQuizUploadTitle('');
      setQuizUploadFile(null);

      await Promise.all([loadGroupMaterials(), loadGroupQuizzes()]);

      if (stompClient?.connected) {
        stompClient.publish({
          destination: `/pub/group/${study.id}/chat`,
          body: JSON.stringify({
            senderId: userId,
            senderName: 'System',
            content: `${myDisplayName}님이 "${title}" PDF를 등록하고 퀴즈를 생성했습니다.`
          })
        });
      }
    } catch (err) {
      const message = err.response?.data?.message || err.message || 'PDF 등록/퀴즈 생성에 실패했습니다.';
      setQuizUploadError(message);
      showAlert('오류', message);
    } finally {
      setIsUploadingQuizPdf(false);
    }
  };

  const handleSendChat = () => {
    if (!chatInput.trim() || !stompClient || !stompClient.connected) return;
    
    stompClient.publish({
      destination: `/pub/group/${study.id}/chat`,
      body: JSON.stringify({
        senderId: userId,
        senderName: myDisplayName,
        content: chatInput
      })
    });
    setChatInput('');
  };

  const handleSendAiMessage = async () => {
    // ref 동기 가드: state(isAiStreaming)가 갱신되기 전에 들어오는 두 번째 호출
    // (Enter키 + 버튼클릭 동시 입력 / 빠른 더블클릭 / StrictMode 재호출)을 즉시 차단한다.
    if (aiSendingRef.current) {
      if (import.meta.env.DEV) console.debug('[AI-SSE] 중복 전송 차단');
      return;
    }
    if (!aiInput.trim() || isAiStreaming) return;
    aiSendingRef.current = true;

    // 이번 전송만의 고유 requestId. 이전 요청에서 늦게 도착하는 이벤트는 모두 무시한다.
    const requestId = `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    activeAiRequestRef.current = requestId;
    const isActive = () => activeAiRequestRef.current === requestId;

    // 이전에 열린 스트림이 있으면 반드시 닫는다(중복 fetch 연결 방지).
    if (aiAbortRef.current) { try { aiAbortRef.current.abort(); } catch (e) { /* noop */ } }
    const abortController = new AbortController();
    aiAbortRef.current = abortController;

    const userMsg = aiInput.trim();
    setAiInput('');
    setIsAiStreaming(true);

    // Add user message to state
    const userMsgObj = {
      id: `user-${requestId}`,
      senderName: myDisplayName,
      content: userMsg,
      isUser: true
    };
    setAiMessages(prev => [...prev, userMsgObj]);

    // 이번 턴의 토론 말풍선은 requestId로 식별되는 단 하나의 객체다.
    // 섹션이 다시 도착해도 새로 추가하지 않고 그 객체의 섹션만 upsert한다.
    const debateMsgId = `debate-${requestId}`;

    const token = localStorage.getItem('token');
    const hostname = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
try {
      const response = await fetch(`/api/groups/${study.id}/chats/stream`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': token ? `Bearer ${token}` : ''
        },
        body: JSON.stringify({
          message: userMsg,
          // 라이브 모드 토글 값 전달. basic은 그룹 멀티에이전트 기본 흐름, 그 외는 mode=learningMode로 명시.
          mode: aiMode === 'basic' ? 'multi_agent_discussion' : aiMode,
          learningMode: aiMode,
          rounds: 3,
          showFinalSynthesis: true,
          // 사용자가 설정한 봇이 있으면 그대로 전달(이름/성격/지식수준/요구사항).
          // 비어있으면 빈 배열 → 백엔드가 기본 요약/퀴즈/검색봇을 사용한다.
          agents: (aiBots || [])
            .filter((b) => b && (b.name || '').trim())
            .map((b, i) => ({
              id: i + 1,
              agentId: i + 1,
              name: (b.name || '').trim(),
              role: 'AI 학습 도우미',
              personality: (b.personality || '').trim(),
              knowledgeLevel: (b.knowledgeLevel || '').trim(),
              customInstruction: (b.requirement || '').trim(),
            })),
          // 직전 응답에서 캡처한 토론/상황극 멀티턴 상태를 다시 실어 보낸다(있을 때만).
          //  → 논제/선택지를 매번 처음부터 다시 고르게 만드는 반복을 방지한다.
          ...aiConvStateRef.current,
        }),
        signal: abortController.signal
      });

      if (!response.ok) {
        throw new Error(`스트리밍 오류 (HTTP ${response.status})`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        if (!isActive()) break; // 더 새로운 요청이 시작됨 → 이 스트림은 버린다

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() || ''; // Keep the last partial line in the buffer

        for (const line of lines) {
          const trimmed = line.trim();
          if (!trimmed) continue;
          if (trimmed.startsWith('data:')) {
            const dataStr = trimmed.slice(5).trim();
            if (!dataStr) continue;
            try {
              const parsed = JSON.parse(dataStr);

              // 토론/상황극 멀티턴 상태(있을 때만) 캡처 → 다음 요청에 echo (논제/선택지 반복 방지).
              // snake_case/camelCase 모두 수용. 값이 있는 키만 갱신해 이전 상태를 덮어쓰지 않는다.
              {
                const cur = aiConvStateRef.current;
                const setIf = (k, v) => { if (v !== undefined && v !== null && v !== '') cur[k] = v; };
                setIf('debateState', parsed.debateState ?? parsed.debate_state);
                setIf('selectedTopic', parsed.selectedTopic ?? parsed.selected_topic);
                setIf('debateSessionId', parsed.debateSessionId ?? parsed.debate_session_id ?? parsed.sessionId);
                setIf('simulationState', parsed.simulationState ?? parsed.simulation_state);
                setIf('scenarioId', parsed.scenarioId ?? parsed.scenario_id);
                const ti = parsed.turnIndex ?? parsed.turn_index;
                if (typeof ti === 'number') cur.turnIndex = ti;
              }

              // Intent Router 라우팅 이벤트: 안내(route_message)/경고(route_notice)를 AI 말풍선으로 표시.
              // terminal이면 백엔드가 이 이벤트 하나만 보내고 종료, WARN이면 notice 뒤로 기존 답변 스트림이 이어진다.
              if (parsed.type === 'route_message' || parsed.type === 'route_notice') {
                const msgText = parsed.message || '';
                if (msgText) {
                  setAiMessages(prev => {
                    if (!isActive()) return prev;
                    return [...prev, {
                      id: `route-${requestId}-${prev.length}`,
                      requestId,
                      isUser: false,
                      senderName: 'AI',
                      content: msgText,
                      routeAction: parsed.routeAction || null,
                      isNotice: parsed.type === 'route_notice',
                      createdAt: new Date().toISOString(),
                    }];
                  });
                }
                continue;
              }

              // 토론 모드: debate_section 이벤트는 일반 agent 메시지로 합치지 않고
              // requestId로 식별되는 단 하나의 debate 말풍선에 섹션별로 upsert한다.
              if (parsed.section || parsed.type === 'debate_section') {
                const { section, items, content } = parsed;
                if (import.meta.env.DEV) console.debug('[AI-SSE] debate_section', { requestId, section, count: items?.length });
                setAiMessages(prev => {
                  if (!isActive()) return prev;
                  const idx = prev.findIndex(m => m.id === debateMsgId);
                  const updated = [...prev];
                  const base = idx === -1
                    ? { id: debateMsgId, requestId, isUser: false, isDebate: true, sections: {} }
                    : { ...updated[idx], sections: { ...updated[idx].sections } };
                  if (section === 'debateSummary') {
                    base.sections.debateSummary = content || '';
                  } else if (section) {
                    base.sections[section] = items || [];
                  }
                  if (idx === -1) updated.push(base);
                  else updated[idx] = base;
                  return updated;
                });
                continue;
              }

              if (parsed.done) {
                if (import.meta.env.DEV) console.debug('[AI-SSE] done', { requestId });
                continue;
              }

              if (parsed.agentName && parsed.content) {
                setAiMessages(prev => {
                  if (!isActive()) return prev;
                  // 이번 요청(requestId)·같은 에이전트(senderName)의 기존 말풍선을 "위치와 무관하게" 찾아 이어붙인다.
                  // 백엔드가 에이전트를 교차로(agent1→agent2→agent3→agent1 …) 또는 단계별로 보내도
                  // 한 에이전트당 말풍선 1개만 유지된다 → 한 질문에 카드가 9개처럼 늘어나는 중복을 방지한다.
                  const existingIdx = prev.findIndex(
                    m => !m.isUser && m.requestId === requestId && m.senderName === parsed.agentName
                  );
                  if (existingIdx !== -1) {
                    const updated = [...prev];
                    updated[existingIdx] = {
                      ...updated[existingIdx],
                      content: updated[existingIdx].content + parsed.content
                    };
                    return updated;
                  }
                  // 새 에이전트 말풍선 생성 (requestId 태깅으로 다른 요청과 섞이지 않게 한다)
                  return [
                    ...prev,
                    {
                      id: `agent-${requestId}-${prev.length}`,
                      requestId,
                      senderName: parsed.agentName,
                      content: parsed.content,
                      isUser: false
                    }
                  ];
                });
              }
            } catch (jsonErr) {
              console.warn("JSON parsing chunk error:", jsonErr, "dataStr:", dataStr);
            }
          }
        }
      }
    } catch (err) {
      // 새 요청/언마운트로 인한 정상 중단은 메시지를 남기지 않는다.
      if (err?.name === 'AbortError') return;
      console.error("AI Stream connection error:", err);
      setAiMessages(prev => isActive() ? [
        ...prev,
        {
          id: `err-${requestId}`,
          senderName: 'System',
          content: `오류가 발생했습니다: ${err.message || err}`,
          isUser: false,
          isError: true
        }
      ] : prev);
    } finally {
      // 이 요청이 여전히 활성일 때만 로딩 상태/스트림 핸들을 정리한다.
      if (isActive()) {
        setIsAiStreaming(false);
        aiAbortRef.current = null;
        activeAiRequestRef.current = null;
      }
      aiSendingRef.current = false;
    }
  };

  useEffect(() => {
    if (study?.id) {
      loadMembers();
      loadApplications();
      timerService.syncTimer(study.id)
        .then(() => console.log('Timer synced with group study room'))
        .catch(err => console.error('Failed to sync timer:', err));
    }
  }, [study?.id, userId]);

  // 커스텀 모달 상태
  const [customAlert, setCustomAlert] = useState({
    isOpen: false,
    title: '',
    message: '',
    type: 'alert',
    inputPlaceholder: '',
    inputValue: '',
    onConfirm: null,
    onCancel: null,
  });

  const showAlert = (title, message, onConfirm = null) => {
    setCustomAlert({ isOpen: true, title, message, type: 'alert', onConfirm: () => { setCustomAlert(prev => ({ ...prev, isOpen: false })); if (onConfirm) onConfirm(); } });
  };

  const showConfirm = (title, message, onConfirm) => {
    setCustomAlert({ isOpen: true, title, message, type: 'confirm', onConfirm: () => { setCustomAlert(prev => ({ ...prev, isOpen: false })); onConfirm(); }, onCancel: () => setCustomAlert(prev => ({ ...prev, isOpen: false })) });
  };

  const showPrompt = (title, message, inputPlaceholder, onConfirm) => {
    setCustomAlert({ isOpen: true, title, message, type: 'prompt', inputPlaceholder, inputValue: '', onConfirm: (val) => { setCustomAlert(prev => ({ ...prev, isOpen: false })); onConfirm(val); }, onCancel: () => setCustomAlert(prev => ({ ...prev, isOpen: false })) });
  };

  // 실제 참여자 목록(members) 길이 = 상단/사이드바에 표시할 입장 인원. mock/maxMembers/capacity 사용 안 함.
  const participantCount = members.length;

  // 일반 채팅에 새 메시지가 오면 목록만 하단으로 스크롤
  useEffect(() => {
    if (chatTab === 'normal') {
      chatEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }
  }, [chatMessages, chatTab]);

  // AI 토론(SSE) 메시지가 갱신되면 목록만 하단으로 스크롤
  useEffect(() => {
    if (chatTab === 'ai') {
      aiEndRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
    }
  }, [aiMessages, chatTab]);

  // AI 대화 새로고침 영속화: 그룹별 sessionStorage 키. 새로고침/탭 복귀 후에도 직전 AI 답변이
  //  사라지지 않게 한다(서버 Redis 원본과 별개의 클라이언트 임시 캐시; 그룹 id로 격리).
  const aiChatStorageKey = study?.id ? `sb-ai-chat-${study.id}` : null;

  // 복원: 그룹 진입 시 1회. 현재 목록이 비어 있을 때만 채워 진행 중 상태를 보호한다.
  useEffect(() => {
    if (!aiChatStorageKey) return;
    try {
      const saved = sessionStorage.getItem(aiChatStorageKey);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed) && parsed.length > 0) {
          setAiMessages(prev => (prev.length === 0 ? parsed : prev));
        }
      }
    } catch (e) { /* 손상된 캐시는 무시 */ }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aiChatStorageKey]);

  // 저장: 메시지가 있을 때만 기록한다(빈 배열로 덮어써 캐시를 지우지 않는다).
  useEffect(() => {
    if (!aiChatStorageKey) return;
    try {
      if (aiMessages.length > 0) {
        sessionStorage.setItem(aiChatStorageKey, JSON.stringify(aiMessages));
      }
    } catch (e) { /* 용량 초과 등은 무시 */ }
  }, [aiMessages, aiChatStorageKey]);

  return (
    <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, zIndex: 99999, backgroundColor: '#0B0F19', display: 'flex', flexDirection: 'column', color: 'white', fontFamily: "'Inter', sans-serif" }}>
      <style>{`
        .custom-scrollbar::-webkit-scrollbar {
          width: 6px;
        }
        .custom-scrollbar::-webkit-scrollbar-track {
          background: rgba(255, 255, 255, 0.02);
          border-radius: 4px;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb {
          background: rgba(255, 255, 255, 0.1);
          border-radius: 4px;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover {
          background: rgba(255, 255, 255, 0.2);
        }
        .custom-scrollbar {
          scrollbar-width: thin;
          scrollbar-color: rgba(255, 255, 255, 0.1) rgba(255, 255, 255, 0.02);
        }
        /* 상단 StudyBridge 로고 — 다크 UI에 어울리는 깔끔한 블루→옐로 그라데이션 */
        .sb-logo {
          font-size: 20px;
          font-weight: 900;
          letter-spacing: -0.5px;
          background: linear-gradient(90deg, #60A5FA 0%, #818CF8 55%, #FACC15 100%);
          -webkit-background-clip: text;
          background-clip: text;
          -webkit-text-fill-color: transparent;
          color: transparent;
          user-select: none;
        }
      `}</style>

      {/* Header - Glassmorphic Dark */}
      {!isCamFullScreen && (
        <div style={{ height: '60px', backgroundColor: 'rgba(15, 23, 42, 0.7)', backdropFilter: 'blur(16px)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 24px', borderBottom: '1px solid rgba(255,255,255,0.08)', zIndex: 10 }}>

          <div style={{ display: 'flex', alignItems: 'center', gap: '24px' }}>
            {/* Text Logo Area */}
            <div style={{ display: 'flex', alignItems: 'center', cursor: 'pointer', gap: '6px' }}>
              <span className="sb-logo">
                StudyBridge
              </span>
            </div>

            <div style={{ width: '1px', height: '20px', backgroundColor: 'rgba(255,255,255,0.1)' }} />

            {/* Title Area */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <h1 style={{ margin: 0, color: '#F3F4F6', fontSize: '16px', fontWeight: '600' }}>{study.title}</h1>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', backgroundColor: 'rgba(59, 130, 246, 0.15)', color: '#60A5FA', padding: '4px 10px', borderRadius: '12px', fontSize: '12px', fontWeight: '600' }}>
                <Users size={14} /> {participantCount}명 입장
              </div>
            </div>
          </div>

          {/* Right Controls */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', backgroundColor: 'rgba(255,255,255,0.05)', padding: '6px 12px', borderRadius: '20px' }}>
              <div onClick={() => setIsMicOn(!isMicOn)} style={{ display: 'flex', alignItems: 'center' }}>
                {isMicOn ? <Mic size={18} color="#D1D5DB" cursor="pointer" /> : <MicOff size={18} color="#F87171" cursor="pointer" />}
              </div>
              <div onClick={() => setIsVideoOn(!isVideoOn)} style={{ display: 'flex', alignItems: 'center' }}>
                {isVideoOn ? <Video size={18} color="#D1D5DB" cursor="pointer" /> : <VideoOff size={18} color="#F87171" cursor="pointer" />}
              </div>
              <Settings size={18} color="#D1D5DB" cursor="pointer" onClick={() => setShowSettings(true)} />
            </div>

            <div style={{ width: '1px', height: '20px', backgroundColor: 'rgba(255,255,255,0.1)' }} />

            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <Maximize size={18} color="#9CA3AF" cursor="pointer" onClick={() => setIsCamFullScreen(true)} />
              <div
                onClick={onClose}
                style={{ width: '32px', height: '32px', borderRadius: '50%', backgroundColor: 'rgba(239, 68, 68, 0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', transition: 'all 0.2s' }}
                onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'rgba(239, 68, 68, 0.2)'}
                onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'rgba(239, 68, 68, 0.1)'}
              >
                <X size={16} color="#EF4444" />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Main Body */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>

        {/* Left Sidebar - Floating Dock Style */}
        {!isCamFullScreen && (
          <div style={{ width: '72px', backgroundColor: '#0F172A', display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '24px 0', borderRight: '1px solid rgba(255,255,255,0.05)' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', alignItems: 'center' }}>
              <div onClick={() => setShowStatsModal(true)} style={{ padding: '10px', borderRadius: '12px', color: '#9CA3AF', cursor: 'pointer', transition: '0.2s', ':hover': { color: 'white', backgroundColor: 'rgba(255,255,255,0.1)' } }}>
                <Calendar size={22} />
              </div>
              <div onClick={() => { setRoomManageTab('settings'); setShowRoomManageModal(true); }} style={{ padding: '10px', borderRadius: '12px', color: '#9CA3AF', cursor: 'pointer', transition: '0.2s', ':hover': { color: 'white', backgroundColor: 'rgba(255,255,255,0.1)' } }}>
                <ClipboardList size={22} />
              </div>
              <div onClick={() => { setRoomManageTab('quiz'); setShowRoomManageModal(true); }} style={{ padding: '10px', borderRadius: '12px', color: '#9CA3AF', cursor: 'pointer', transition: '0.2s', ':hover': { color: 'white', backgroundColor: 'rgba(255,255,255,0.1)' } }} title="실시간 퀴즈">
                <Edit2 size={22} />
              </div>
              {/* 채팅 드로어 토글 — 일반 채팅 + AI 토론을 넓은 패널로 분리해서 보여준다. */}
              <div
                onClick={() => setShowChatDrawer(v => !v)}
                style={{ position: 'relative', padding: '10px', borderRadius: '12px', color: showChatDrawer ? '#60A5FA' : '#9CA3AF', backgroundColor: showChatDrawer ? 'rgba(59,130,246,0.18)' : 'transparent', cursor: 'pointer', transition: '0.2s' }}
                title="채팅 (일반 / AI 토론)"
              >
                <MessageCircle size={22} />
                {chatMessages.length > 0 && !showChatDrawer && (
                  <span style={{ position: 'absolute', top: '4px', right: '4px', width: '8px', height: '8px', borderRadius: '50%', backgroundColor: '#22C55E', border: '2px solid #0F172A' }} />
                )}
              </div>
            </div>

            <div style={{ marginTop: 'auto' }}>
              <div
                style={{ padding: '10px', borderRadius: '12px', backgroundColor: 'rgba(59, 130, 246, 0.2)', color: '#60A5FA', cursor: 'pointer', boxShadow: '0 0 15px rgba(59, 130, 246, 0.1)' }}
                onClick={() => setShowAdminReportModal(true)}
              >
                <MessageSquare size={22} />
              </div>
            </div>
          </div>
        )}

        {/* Video Grid */}
        <div className="custom-scrollbar" style={{ flex: 1, padding: '24px', overflowY: 'auto', backgroundColor: '#0B0F19', position: 'relative' }}>

          {isCamFullScreen && (
            <div
              style={{ position: 'fixed', top: '24px', right: '24px', zIndex: 1000, backgroundColor: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)', padding: '8px 16px', borderRadius: '24px', border: '1px solid rgba(255,255,255,0.1)', display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', transition: '0.2s', boxShadow: '0 4px 12px rgba(0,0,0,0.5)' }}
              onClick={() => setIsCamFullScreen(false)}
              onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'rgba(0,0,0,0.8)'}
              onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'rgba(0,0,0,0.6)'}
            >
              <Minimize size={16} color="#E5E7EB" />
              <span style={{ color: '#E5E7EB', fontSize: '13px', fontWeight: '600' }}>전체화면 종료</span>
            </div>
          )}

          {ovNotice && (
            <div style={{ marginBottom: '12px', padding: '10px 14px', borderRadius: '10px', backgroundColor: 'rgba(234, 179, 8, 0.12)', border: '1px solid rgba(234, 179, 8, 0.35)', color: '#FCD34D', fontSize: '13px', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <AlertTriangle size={16} color="#FCD34D" />
              <span>{ovNotice}</span>
            </div>
          )}

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '20px', height: '100%', alignContent: 'start' }}>

            {/* Local Video Feed */}
            <div style={{ position: 'relative' }}>
              <VideoFeed
                stream={publisher ? publisher.stream.mediaStream : null}
                isLocal={true}
                displayName={myDisplayName}
                isMuted={true}
                isCamOn={isVideoOn}
                isMicOn={isMicOn}
                photoUrl={user?.photoUrl || user?.photo_url || null}
                speakerId={userId}
                onSpeakingChange={handleSpeakingChange}
              />
              {ovError && (
                <div style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.7)', color: '#FCA5A5', padding: '16px', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', textAlign: 'center', zIndex: 10, borderRadius: '16px' }}>
                  <AlertTriangle size={32} color="#EF4444" style={{ marginBottom: '8px' }} />
                  <div style={{ fontSize: '14px', fontWeight: 'bold' }}>장치 연결 실패</div>
                  <div style={{ fontSize: '12px', marginTop: '4px', wordBreak: 'break-all' }}>{ovError}</div>
                </div>
              )}
            </div>

            {/* Remote Peer Video Feeds */}
            {subscribers.map(sub => {
              let displayName = '알 수 없음';
              let subUserId = null;
              try {
                const connectionData = JSON.parse(sub.stream.connection.data);
                displayName = connectionData.clientData || '알 수 없음';
                subUserId = connectionData.userId;
              } catch (e) {
                // fallback
              }
              const memberObj = members.find(m => Number(m.userId) === Number(subUserId));
              const subPhotoUrl = memberObj?.photoUrl || null;
              return (
                <VideoFeed
                  key={sub.stream.streamId}
                  stream={sub.stream.mediaStream}
                  isLocal={false}
                  displayName={displayName}
                  isMuted={false}
                  isCamOn={sub.stream.videoActive}
                  isMicOn={sub.stream.audioActive}
                  photoUrl={subPhotoUrl}
                  speakerId={subUserId}
                  onSpeakingChange={handleSpeakingChange}
                />
              );
            })}

            {/* Empty Slots */}
            {Array.from({ length: Math.max(0, (study.maxMembers || 16) - 1 - subscribers.length) }).map((_, i) => (
              <div key={i} style={{ backgroundColor: 'rgba(30, 41, 59, 0.3)', borderRadius: '16px', display: 'flex', alignItems: 'center', justifyContent: 'center', aspectRatio: '16/9', border: '1px dashed rgba(255,255,255,0.1)' }}>
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px', opacity: 0.3 }}>
                  <Monitor size={36} color="#9CA3AF" />
                  <span style={{ color: '#9CA3AF', fontSize: '14px', fontWeight: '600', letterSpacing: '0.5px' }}>StudyBridge</span>
                </div>
              </div>
            ))}

          </div>
        </div>

        {/* Right Sidebar - Chat & Participants */}
        {!isCamFullScreen && (
          <div style={{ width: '340px', backgroundColor: '#0F172A', display: 'flex', flexDirection: 'column', minHeight: 0, borderLeft: '1px solid rgba(255,255,255,0.05)' }}>

            {/* Participants Area */}
            <div style={{ padding: '20px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                <div style={{ fontSize: '14px', fontWeight: '700', color: '#F3F4F6', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  참여자 목록
                  <span style={{ backgroundColor: 'rgba(59, 130, 246, 0.2)', color: '#60A5FA', padding: '2px 8px', borderRadius: '10px', fontSize: '12px' }}>{participantCount}명</span>
                </div>
                <div style={{ padding: '6px', backgroundColor: 'rgba(255,255,255,0.05)', borderRadius: '8px', cursor: 'pointer' }}>
                  <Search size={14} color="#9CA3AF" />
                </div>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                {members.map(member => {
                  const isMe = Number(member.userId) === Number(userId);
                  let isUserMicOn = false;
                  let isUserVideoOn = false;

                  if (isMe) {
                    isUserMicOn = isMicOn;
                    isUserVideoOn = isVideoOn;
                  } else {
                    const sub = subscribers.find(s => {
                      try {
                        const connData = JSON.parse(s.stream.connection.data);
                        return Number(connData.userId) === Number(member.userId);
                      } catch (e) {
                        return false;
                      }
                    });
                    if (sub) {
                      isUserMicOn = sub.stream.audioActive;
                      isUserVideoOn = sub.stream.videoActive;
                    }
                  }

                  // 발화 중이고 마이크가 켜진 경우에만 초록색 ring 표시 (mute 상태에서는 표시 안 함)
                  const isMemberSpeaking = isUserMicOn && speakingUsers.has(String(member.userId));
                  const avatarRing = isMemberSpeaking
                    ? { boxShadow: '0 0 0 2px #22C55E, 0 0 8px rgba(34,197,94,0.6)' }
                    : {};

                  return (
                    <div key={member.userId} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px', borderRadius: '12px', backgroundColor: 'rgba(255,255,255,0.02)' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        {member.photoUrl ? (
                          <img
                            src={member.photoUrl}
                            alt={member.displayName}
                            style={{ width: '32px', height: '32px', borderRadius: '50%', objectFit: 'cover', transition: 'box-shadow 0.15s ease', ...avatarRing }}
                          />
                        ) : (
                          <div style={{ width: '32px', height: '32px', borderRadius: '50%', backgroundColor: member.role === 'LEADER' ? '#3B82F6' : '#334155', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '13px', fontWeight: '700', color: 'white', transition: 'box-shadow 0.15s ease', ...avatarRing }}>
                            {member.displayName ? member.displayName.charAt(0) : 'U'}
                          </div>
                        )}
                        <span style={{ fontSize: '13px', color: '#E5E7EB', fontWeight: '500' }}>
                          {member.displayName} {isMe ? '(나)' : ''}
                        </span>
                      </div>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                        {isUserVideoOn ? (
                          <Video size={14} color="#10B981" />
                        ) : (
                          <VideoOff size={14} color="#EF4444" />
                        )}
                        {isUserMicOn ? (
                          <Mic size={14} color="#10B981" />
                        ) : (
                          <MicOff size={14} color="#EF4444" />
                        )}
                      </div>
                    </div>
                  );
                })}
                {members.length === 0 && (
                  <div style={{ color: '#9CA3AF', fontSize: '12px', textAlign: 'center', padding: '20px 0' }}>참여자가 없습니다.</div>
                )}
              </div>
            </div>

            {/* 방장 관리 콘솔 */}
            {myMember?.role === 'LEADER' && (
              <div style={{ padding: '20px', borderBottom: '1px solid rgba(255,255,255,0.05)', backgroundColor: 'rgba(15, 23, 42, 0.5)' }}>
                <div style={{ fontSize: '14px', fontWeight: '700', color: '#34D399', display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px' }}>
                  <Settings size={16} /> 방장 관리 콘솔
                </div>
                
                {/* 스터디 상태 */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', padding: '12px', backgroundColor: 'rgba(255,255,255,0.03)', borderRadius: '8px', marginBottom: '16px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}>
                    <span style={{ color: '#9CA3AF' }}>스터디 상태</span>
                    <span style={{ color: study.status === '모집중' ? '#34D399' : '#9CA3AF', fontWeight: '600' }}>{study.status}</span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '12px' }}>
                    <span style={{ color: '#9CA3AF' }}>가입 인원</span>
                    <span style={{ color: '#E5E7EB', fontWeight: '600' }}>{study.currentMembers} / {study.maxMembers}명</span>
                  </div>
                </div>

                {/* 가입 신청 대기자 */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '16px' }}>
                  <div style={{ fontSize: '12px', fontWeight: '600', color: '#E5E7EB', display: 'flex', justifyContent: 'space-between' }}>
                    가입 신청 대기자 명단 ({applications.length})
                    <span onClick={() => { setRoomManageTab('members'); setShowRoomManageModal(true); }} style={{ color: '#60A5FA', cursor: 'pointer', fontSize: '11px' }}>자세히 보기 &gt;</span>
                  </div>
                  <div className="custom-scrollbar" style={{ height: '80px', overflowY: 'auto', border: '1px solid rgba(255,255,255,0.05)', borderRadius: '8px', padding: '8px', backgroundColor: 'rgba(0,0,0,0.2)', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {applications.length > 0 ? (
                      applications.map(app => (
                        <div key={app.applicationId} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '11px', padding: '6px', backgroundColor: 'rgba(255,255,255,0.03)', borderRadius: '4px' }}>
                          <span style={{ color: '#D1D5DB' }}>{app.applicantName}</span>
                          <span style={{ color: '#60A5FA', cursor: 'pointer' }} onClick={() => { setRoomManageTab('members'); setShowRoomManageModal(true); }}>심사하기</span>
                        </div>
                      ))
                    ) : (
                      <div style={{ color: '#6B7280', fontSize: '11px', textAlign: 'center', marginTop: '24px' }}>대기 중인 신청자가 없습니다.</div>
                    )}
                  </div>
                </div>

                {/* 관리 버튼 */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>

                  <button onClick={() => updateStudyStatus('해체됨')} style={{ width: '100%', padding: '10px', backgroundColor: 'transparent', color: '#EF4444', borderRadius: '6px', border: '1px solid rgba(239,68,68,0.5)', fontSize: '12px', fontWeight: '600', cursor: 'pointer', transition: '0.2s', ':hover': { backgroundColor: 'rgba(239,68,68,0.1)' } }}>
                    스터디 강제 해체
                  </button>
                </div>
              </div>
            )}

            {/* 채팅 영역은 별도 드로어로 분리되었다. 오른쪽 사이드바에는 안내만 남기고, 실제 채팅은 아래 드로어에서 연다. */}
            <div style={{ padding: '16px 20px', borderTop: '1px solid rgba(255,255,255,0.05)' }}>
              <button
                onClick={() => setShowChatDrawer(true)}
                style={{ width: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px', padding: '12px', borderRadius: '12px', border: '1px solid rgba(96,165,250,0.35)', backgroundColor: 'rgba(37,99,235,0.14)', color: '#93C5FD', fontSize: '13px', fontWeight: 700, cursor: 'pointer' }}
              >
                <MessageCircle size={16} /> 채팅 / AI 토론 열기
                {chatMessages.length > 0 && (
                  <span style={{ backgroundColor: '#22C55E', color: '#06251A', borderRadius: '10px', fontSize: '11px', fontWeight: 800, padding: '1px 7px' }}>{chatMessages.length}</span>
                )}
              </button>
            </div>

            {/* === 채팅 드로어 (왼쪽 사이드바 말풍선으로 토글) === */}
            {showChatDrawer && (
              <div
                onClick={() => setShowChatDrawer(false)}
                style={{ position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.45)', zIndex: 90 }}
              />
            )}
            <div style={{
              position: 'fixed', top: 0, right: 0, bottom: 0,
              width: 'min(100vw, 480px)',
              transform: showChatDrawer ? 'translateX(0)' : 'translateX(110%)',
              transition: 'transform 0.25s ease',
              display: 'flex', flexDirection: 'column', minHeight: 0,
              backgroundColor: '#111827',
              borderLeft: '1px solid rgba(255,255,255,0.08)',
              boxShadow: '-8px 0 30px rgba(0,0,0,0.5)',
              zIndex: 95
            }}>

              {/* Drawer Header */}
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 20px', borderBottom: '1px solid rgba(255,255,255,0.06)', backgroundColor: '#0F172A' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#F3F4F6', fontWeight: 800, fontSize: '15px' }}>
                  <MessageCircle size={18} color="#60A5FA" /> 채팅
                </div>
                <div onClick={() => setShowChatDrawer(false)} style={{ cursor: 'pointer', padding: '6px', borderRadius: '8px', display: 'flex' }} title="닫기">
                  <X size={18} color="#9CA3AF" />
                </div>
              </div>

              {/* Chat Tabs */}
              <div style={{ padding: '0 20px', borderBottom: '1px solid rgba(255,255,255,0.05)', display: 'flex', gap: '16px', backgroundColor: '#0F172A' }}>
                <button
                  onClick={() => setChatTab('normal')}
                  style={{
                    padding: '14px 0',
                    border: 'none',
                    background: 'none',
                    color: chatTab === 'normal' ? '#3B82F6' : '#9CA3AF',
                    borderBottom: chatTab === 'normal' ? '2px solid #3B82F6' : '2px solid transparent',
                    fontSize: '14px',
                    fontWeight: '700',
                    cursor: 'pointer',
                    outline: 'none'
                  }}
                >
                  일반 채팅
                </button>
                <button
                  onClick={() => setChatTab('ai')}
                  style={{
                    padding: '14px 0',
                    border: 'none',
                    background: 'none',
                    color: chatTab === 'ai' ? '#3B82F6' : '#9CA3AF',
                    borderBottom: chatTab === 'ai' ? '2px solid #3B82F6' : '2px solid transparent',
                    fontSize: '14px',
                    fontWeight: '700',
                    cursor: 'pointer',
                    outline: 'none'
                  }}
                >
                  AI 토론 (SSE)
                </button>
              </div>

              {chatTab === 'normal' ? (
                <>
                  <div className="custom-scrollbar" style={{ flex: 1, minHeight: 0, padding: '20px', overflowY: 'auto', overscrollBehavior: 'contain', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    {/* Notice Box */}
                    <div style={{ backgroundColor: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgba(239, 68, 68, 0.2)', borderRadius: '12px', padding: '16px', position: 'relative' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#F87171', fontSize: '13px', fontWeight: '700', marginBottom: '8px' }}>
                        <AlertTriangle size={16} /> 서비스 이용 안내
                      </div>
                      <div style={{ color: '#FCA5A5', fontSize: '12px', lineHeight: '1.6', wordBreak: 'keep-all' }}>
                        불건전한 행동이나 욕설 발견 시 즉각 강제 퇴장 및 계정 정지 조치가 이루어질 수 있습니다. 모두가 집중할 수 있는 분위기를 만들어주세요.
                      </div>
                    </div>

                    {canUseGroupQuizMaterials && (
                      <div style={{ backgroundColor: 'rgba(15, 23, 42, 0.75)', border: '1px solid rgba(148, 163, 184, 0.18)', borderRadius: '12px', padding: '16px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px', flexWrap: 'wrap' }}>
                          <div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#E5E7EB', fontSize: '14px', fontWeight: '800', marginBottom: '6px' }}>
                              <FileText size={16} /> 공유 PDF 퀴즈
                            </div>
                            <div style={{ color: '#9CA3AF', fontSize: '12px', lineHeight: '1.5' }}>
                              그룹원이 업로드한 PDF로 AI 퀴즈를 생성하고, 생성된 퀴즈는 모든 멤버가 실시간으로 풀 수 있습니다.
                            </div>
                          </div>
                          <button
                            onClick={() => setShowPdfUploadModal(true)}
                            style={{ padding: '10px 14px', backgroundColor: '#2563EB', color: 'white', border: 'none', borderRadius: '8px', fontSize: '12px', fontWeight: '800', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px', whiteSpace: 'nowrap' }}
                          >
                            <Upload size={14} /> PDF 등록해서 퀴즈 생성
                          </button>
                        </div>

                        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '12px' }}>
                          <div style={{ backgroundColor: 'rgba(30, 41, 59, 0.7)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '10px', padding: '12px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
                              <div style={{ color: '#F3F4F6', fontSize: '13px', fontWeight: '800' }}>공유 PDF 자료</div>
                              <button onClick={loadGroupMaterials} style={{ background: 'none', border: 'none', color: '#93C5FD', cursor: 'pointer', display: 'flex', padding: 0 }} title="새로고침">
                                <RefreshCw size={14} />
                              </button>
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '180px', overflowY: 'auto' }}>
                              {groupMaterials.length === 0 ? (
                                <div style={{ color: '#64748B', fontSize: '12px', padding: '10px 0' }}>등록된 PDF 자료가 없습니다.</div>
                              ) : groupMaterials.map(material => (
                                <div key={material.id} style={{ display: 'flex', justifyContent: 'space-between', gap: '10px', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '8px' }}>
                                  <div style={{ minWidth: 0 }}>
                                    <div style={{ color: '#E5E7EB', fontSize: '12px', fontWeight: '700', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{material.title}</div>
                                    <div style={{ color: '#94A3B8', fontSize: '11px', marginTop: '3px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{material.originalFileName} · {formatFileSize(material.fileSize)}</div>
                                    <div style={{ color: '#64748B', fontSize: '11px', marginTop: '3px' }}>{material.uploaderName || '알 수 없음'} · {formatShortDateTime(material.createdAt)}</div>
                                  </div>
                                  <div style={{ display: 'flex', gap: '6px', flexShrink: 0 }}>
                                    <button
                                      onClick={() => handleRegenerateQuiz(material.id)}
                                      disabled={regeneratingMaterialId === material.id}
                                      style={{ flexShrink: 0, height: '30px', padding: '0 10px', borderRadius: '8px', border: '1px solid rgba(16,185,129,0.35)', backgroundColor: 'rgba(16,185,129,0.14)', color: '#6EE7B7', display: 'flex', alignItems: 'center', gap: '4px', cursor: regeneratingMaterialId === material.id ? 'not-allowed' : 'pointer', fontSize: '11px', fontWeight: 700, whiteSpace: 'nowrap' }}
                                      title="이 PDF로 퀴즈 생성"
                                    >
                                      {regeneratingMaterialId === material.id
                                        ? <RefreshCw size={13} className="animate-spin" style={{ animation: 'spin 1.5s linear infinite' }} />
                                        : <ClipboardList size={13} />}
                                      퀴즈
                                    </button>
                                    <button
                                      onClick={() => handleDownloadGroupMaterial(material.id)}
                                      style={{ flexShrink: 0, width: '30px', height: '30px', borderRadius: '8px', border: '1px solid rgba(96,165,250,0.35)', backgroundColor: 'rgba(37,99,235,0.14)', color: '#93C5FD', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' }}
                                      title="다운로드"
                                    >
                                      <Download size={14} />
                                    </button>
                                  </div>
                                </div>
                              ))}
                            </div>
                          </div>

                          <div style={{ backgroundColor: 'rgba(30, 41, 59, 0.7)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '10px', padding: '12px' }}>
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '10px' }}>
                              <div style={{ color: '#F3F4F6', fontSize: '13px', fontWeight: '800' }}>생성된 퀴즈</div>
                              <button onClick={loadGroupQuizzes} style={{ background: 'none', border: 'none', color: '#93C5FD', cursor: 'pointer', display: 'flex', padding: 0 }} title="새로고침">
                                <RefreshCw size={14} />
                              </button>
                            </div>
                            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '180px', overflowY: 'auto' }}>
                              {groupQuizzes.length === 0 ? (
                                <div style={{ color: '#64748B', fontSize: '12px', padding: '10px 0' }}>생성된 퀴즈가 없습니다.</div>
                              ) : groupQuizzes.map(quiz => (
                                <div key={quiz.id} style={{ display: 'flex', justifyContent: 'space-between', gap: '10px', borderTop: '1px solid rgba(255,255,255,0.05)', paddingTop: '8px' }}>
                                  <div style={{ minWidth: 0 }}>
                                    <div style={{ color: '#E5E7EB', fontSize: '12px', fontWeight: '700', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{quiz.title}</div>
                                    <div style={{ color: '#94A3B8', fontSize: '11px', marginTop: '3px' }}>{quiz.creatorName || '알 수 없음'} · {quiz.questionCount || 0}문항 · {formatShortDateTime(quiz.createdAt)}</div>
                                  </div>
                                  <button
                                    onClick={() => handleQuizStart(quiz.id)}
                                    style={{ flexShrink: 0, padding: '7px 10px', borderRadius: '8px', border: 'none', backgroundColor: '#16A34A', color: 'white', fontSize: '11px', fontWeight: '800', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '5px', whiteSpace: 'nowrap' }}
                                  >
                                    <Play size={12} fill="white" /> 시작
                                  </button>
                                </div>
                              ))}
                            </div>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Chat Messages */}
                    {chatMessages.map((msg, idx) => (
                      <div key={idx} style={{ display: 'flex', flexDirection: 'column', gap: '4px', alignSelf: Number(msg.senderId) === Number(userId) ? 'flex-end' : 'flex-start', maxWidth: '80%' }}>
                        <span style={{ fontSize: '11px', color: '#9CA3AF', alignSelf: Number(msg.senderId) === Number(userId) ? 'flex-end' : 'flex-start' }}>
                          {msg.senderName}
                        </span>
                        <div style={{
                          backgroundColor: Number(msg.senderId) === Number(userId) ? '#22C55E' : '#1E293B',
                          color: 'white',
                          padding: '8px 12px',
                          borderRadius: Number(msg.senderId) === Number(userId) ? '12px 12px 0 12px' : '12px 12px 12px 0',
                          fontSize: '13px',
                          lineHeight: '1.4',
                          wordBreak: 'break-all'
                        }}>
                          {msg.content}
                        </div>
                      </div>
                    ))}
                    <div ref={chatEndRef} />
                  </div>

                  {/* Chat Input */}
                  <div style={{ padding: '20px', backgroundColor: '#0F172A', borderTop: '1px solid rgba(255,255,255,0.05)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', backgroundColor: '#1E293B', borderRadius: '24px', padding: '8px 16px', border: '1px solid rgba(255,255,255,0.1)' }}>
                      <div style={{ fontSize: '13px', color: '#9CA3AF', paddingRight: '12px', borderRight: '1px solid rgba(255,255,255,0.1)', marginRight: '12px', display: 'flex', alignItems: 'center', gap: '6px', height: '20px', whiteSpace: 'nowrap' }}>
                        전체 <span style={{ fontSize: '8px', opacity: 0.8 }}>▼</span>
                      </div>
                      <input
                        type="text"
                        placeholder="메시지 입력..."
                        value={chatInput}
                        onChange={(e) => setChatInput(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') handleSendChat();
                        }}
                        style={{ flex: 1, border: 'none', outline: 'none', fontSize: '13px', color: '#F3F4F6', backgroundColor: 'transparent', height: '20px', lineHeight: '20px', padding: 0, margin: 0 }}
                      />
                      <button
                        onClick={handleSendChat}
                        style={{ background: 'linear-gradient(135deg, #22C55E, #16A34A)', border: 'none', width: '32px', height: '32px', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer', marginLeft: '8px', boxShadow: '0 2px 8px rgba(34, 197, 94, 0.3)' }}
                      >
                        <Send size={14} color="white" style={{ marginLeft: '-2px', marginTop: '2px' }} />
                      </button>
                    </div>
                  </div>
                </>
              ) : (
                <>
                  <div className="custom-scrollbar" style={{ flex: 1, minHeight: 0, padding: '20px', overflowY: 'auto', overscrollBehavior: 'contain', display: 'flex', flexDirection: 'column', gap: '16px' }}>
                    {/* Notice Box */}
                    <div style={{ backgroundColor: 'rgba(59, 130, 246, 0.1)', border: '1px solid rgba(59, 130, 246, 0.2)', borderRadius: '12px', padding: '16px', position: 'relative' }}>
                      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px', marginBottom: '8px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#60A5FA', fontSize: '13px', fontWeight: '700' }}>
                          <AlertTriangle size={16} /> AI 토론 안내
                        </div>
                        <button
                          type="button"
                          onClick={(e) => { e.stopPropagation(); setShowAiBotConfig((v) => !v); }}
                          style={{ position: 'relative', zIndex: 2, pointerEvents: 'auto', display: 'flex', alignItems: 'center', gap: '4px', background: 'rgba(59,130,246,0.15)', border: '1px solid rgba(59,130,246,0.35)', color: '#93C5FD', fontSize: '11px', fontWeight: 600, borderRadius: '14px', padding: '4px 10px', cursor: 'pointer' }}
                        >
                          <Settings size={12} /> AI 봇 설정 {aiBots.length > 0 ? `(${aiBots.length})` : ''}
                        </button>
                      </div>
                      <div style={{ color: '#93C5FD', fontSize: '12px', lineHeight: '1.6', wordBreak: 'keep-all' }}>
                        {aiBots.length > 0
                          ? '설정한 AI 봇이 각자의 성격·지식수준·요구사항대로 답변합니다.'
                          : '에이전트들에게 질문하면 요약봇, 퀴즈봇, 검색봇 등 다중 에이전트들이 실시간으로 토론하며 솔루션을 탐색합니다.'}
                      </div>
                    </div>

                    {/* 라이브 모드 토글 — 채팅 중 언제든 모드 변경 (AI봇 설정과 함께 전송) */}
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', alignItems: 'center' }}>
                      <span style={{ fontSize: '11px', color: '#94A3B8', marginRight: '2px' }}>모드</span>
                      {[
                        { value: 'basic', label: '기본', icon: '💬' },
                        { value: 'validation', label: '검증', icon: '✅' },
                        { value: 'collaboration', label: '협업', icon: '🤝' },
                        { value: 'debate', label: '토론', icon: '🗣️' },
                        { value: 'socratic', label: '소크라테스', icon: '🧭' },
                        { value: 'simulation', label: '상황극', icon: '🎭' },
                      ].map((m) => {
                        const active = aiMode === m.value;
                        return (
                          <button
                            key={m.value}
                            type="button"
                            onClick={() => { aiConvStateRef.current = {}; setAiMode(m.value); }}
                            disabled={isAiStreaming}
                            title={m.label}
                            style={{
                              display: 'flex', alignItems: 'center', gap: '4px',
                              padding: '4px 9px', borderRadius: '14px',
                              cursor: isAiStreaming ? 'not-allowed' : 'pointer',
                              fontSize: '11px', fontWeight: active ? 700 : 500,
                              border: `1px solid ${active ? '#3B82F6' : 'rgba(255,255,255,0.12)'}`,
                              backgroundColor: active ? '#3B82F6' : 'transparent',
                              color: active ? '#fff' : '#94A3B8',
                            }}
                          >
                            <span>{m.icon}</span>{m.label}
                          </button>
                        );
                      })}
                    </div>

                    {/* AI 봇 설정 패널 (세션 단위) */}
                    {showAiBotConfig && (
                      <div style={{ backgroundColor: '#0F172A', border: '1px solid rgba(255,255,255,0.08)', borderRadius: '12px', padding: '14px', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <span style={{ color: '#E5E7EB', fontSize: '12px', fontWeight: 700 }}>AI 봇 설정 (최대 3개)</span>
                          <button
                            onClick={() => setAiBots((prev) => prev.length >= 3 ? prev : [...prev, { name: '', personality: '', knowledgeLevel: '학사 수준', requirement: '' }])}
                            disabled={aiBots.length >= 3}
                            style={{ background: 'rgba(34,197,94,0.15)', border: '1px solid rgba(34,197,94,0.35)', color: '#86EFAC', fontSize: '11px', fontWeight: 600, borderRadius: '12px', padding: '4px 10px', cursor: aiBots.length >= 3 ? 'not-allowed' : 'pointer' }}
                          >
                            + 봇 추가
                          </button>
                        </div>
                        {aiBots.length === 0 && (
                          <div style={{ color: '#9CA3AF', fontSize: '11px', lineHeight: 1.6 }}>
                            봇을 추가하지 않으면 기본 요약/퀴즈/검색봇이 사용됩니다.
                          </div>
                        )}
                        {aiBots.map((bot, idx) => {
                          const updateBot = (field, value) => setAiBots((prev) => prev.map((b, i) => i === idx ? { ...b, [field]: value } : b));
                          const inputStyle = { width: '100%', boxSizing: 'border-box', background: '#1E293B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', color: '#F3F4F6', fontSize: '12px', padding: '7px 10px', outline: 'none' };
                          return (
                            <div key={idx} style={{ border: '1px solid rgba(255,255,255,0.08)', borderRadius: '10px', padding: '10px', display: 'flex', flexDirection: 'column', gap: '8px', backgroundColor: 'rgba(255,255,255,0.02)' }}>
                              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                                <span style={{ color: '#93C5FD', fontSize: '11px', fontWeight: 700 }}>봇 {idx + 1}</span>
                                <button onClick={() => setAiBots((prev) => prev.filter((_, i) => i !== idx))} style={{ background: 'none', border: 'none', color: '#F87171', cursor: 'pointer', fontSize: '11px' }}>삭제</button>
                              </div>
                              <input style={inputStyle} placeholder="봇 이름 (예: 친절한 튜터)" value={bot.name} onChange={(e) => updateBot('name', e.target.value)} />
                              <input style={inputStyle} placeholder="성격 (예: 친근하고 비유적)" value={bot.personality} onChange={(e) => updateBot('personality', e.target.value)} />
                              <input style={inputStyle} placeholder="지식수준 (예: 학사 수준)" value={bot.knowledgeLevel} onChange={(e) => updateBot('knowledgeLevel', e.target.value)} />
                              <textarea style={{ ...inputStyle, resize: 'vertical', minHeight: '44px' }} placeholder="요구사항 (예: 예시를 많이 들어 설명)" value={bot.requirement} onChange={(e) => updateBot('requirement', e.target.value)} />
                            </div>
                          );
                        })}
                      </div>
                    )}

                    {/* AI Chat Messages */}
                    {aiMessages.map((msg) => {
                      // 토론 모드 메시지: 1차 의견 → 서로 피드백 → 보완 답변 → 토론 정리 순서로 표시
                      if (msg.isDebate) {
                        const sec = msg.sections || {};
                        const agentCards = buildDebateAgentCards(sec);
                        const palette = ['#3B82F6', '#10B981', '#8B5CF6', '#F59E0B', '#EC4899'];
                        return (
                          <div key={msg.id} style={{ display: 'flex', flexDirection: 'column', gap: '10px', alignSelf: 'flex-start', maxWidth: '95%', width: '100%' }}>
                            <span style={{ fontSize: '11px', color: '#A5B4FC', display: 'flex', alignItems: 'center', gap: '4px' }}>
                              <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: '#6366F1' }} />
                              🤖 AI 토론
                            </span>
                            {/* 에이전트별 독립 카드: 각 카드에는 해당 에이전트의 답변/피드백만 들어간다. */}
                            {agentCards.map((card, ci) => {
                              const accent = palette[ci % palette.length];
                              const displayName = card.name || (card.index != null ? `에이전트 ${card.index}` : '에이전트');
                              const hasFeedback = card.feedbacks.length > 0;
                              return (
                                <div key={card.agentKey} style={{ backgroundColor: '#1E293B', border: `1px solid ${accent}55`, borderLeft: `3px solid ${accent}`, borderRadius: '10px', padding: '10px 14px' }}>
                                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px' }}>
                                    <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: accent }} />
                                    <span style={{ fontWeight: 700, fontSize: '13px', color: accent }}>{displayName}</span>
                                    {/* '단계 N' 숫자 배지는 발표 화면 단순화를 위해 제거(1차 의견/피드백/보완 답변 섹션 라벨로 충분). */}
                                  </div>
                                  {card.initial && (
                                    <div style={{ marginBottom: (hasFeedback || card.revised) ? '10px' : 0 }}>
                                      <div style={{ fontWeight: 600, fontSize: '11px', color: '#93C5FD', marginBottom: '2px' }}>1차 의견</div>
                                      <div style={{ fontSize: '13px', color: '#E5E7EB', lineHeight: '1.5', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{card.initial}</div>
                                    </div>
                                  )}
                                  {hasFeedback && (
                                    <div style={{ marginBottom: card.revised ? '10px' : 0 }}>
                                      <div style={{ fontWeight: 600, fontSize: '11px', color: '#FBBF24', marginBottom: '2px' }}>다른 에이전트에게 준 피드백</div>
                                      {card.feedbacks.map((fb, fi) => (
                                        <div key={fi} style={{ fontSize: '13px', color: '#E5E7EB', lineHeight: '1.5', whiteSpace: 'pre-wrap', wordBreak: 'break-word', marginBottom: fi === card.feedbacks.length - 1 ? 0 : '6px' }}>
                                          {fb.to ? <span style={{ color: '#FBBF24' }}>→ {fb.to}: </span> : null}{fb.text}
                                        </div>
                                      ))}
                                    </div>
                                  )}
                                  {card.revised && (
                                    <div>
                                      <div style={{ fontWeight: 600, fontSize: '11px', color: '#6EE7B7', marginBottom: '2px' }}>보완 답변</div>
                                      <div style={{ fontSize: '13px', color: '#E5E7EB', lineHeight: '1.5', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>{card.revised}</div>
                                    </div>
                                  )}
                                </div>
                              );
                            })}
                            {/* 종합 요약: 개별 에이전트 카드와 분리된 별도 카드 */}
                            {sec.debateSummary && (
                              <div style={{ backgroundColor: '#1E293B', border: '1px solid #FCD34D55', borderLeft: '3px solid #FCD34D', borderRadius: '10px', padding: '10px 14px' }}>
                                <div style={{ fontWeight: 700, fontSize: '12px', color: '#FCD34D', marginBottom: '8px' }}>종합 요약</div>
                                <div style={{ fontSize: '13px', color: '#FDE68A', lineHeight: '1.5', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                                  {sec.debateSummary}
                                </div>
                              </div>
                            )}
                          </div>
                        );
                      }

                      const isMe = msg.isUser;
                      let colors = { bg: '#1E293B', border: 'rgba(255,255,255,0.08)', text: '#E5E7EB' };
                      if (msg.senderName === 'SummaryAgent') {
                        colors = { bg: '#1E3A8A', border: '#3B82F6', text: '#93C5FD' };
                      } else if (msg.senderName === 'QuizAgent') {
                        colors = { bg: '#064E3B', border: '#10B981', text: '#A7F3D0' };
                      } else if (msg.senderName === 'SearchAgent') {
                        colors = { bg: '#581C87', border: '#8B5CF6', text: '#DDD6FE' };
                      } else if (msg.isUser) {
                        colors = { bg: '#16A34A', border: '#22C55E', text: '#FFFFFF' };
                      }
                      
                      return (
                        <div key={msg.id} style={{ display: 'flex', flexDirection: 'column', gap: '4px', alignSelf: isMe ? 'flex-end' : 'flex-start', maxWidth: '85%' }}>
                          <span style={{ fontSize: '11px', color: '#9CA3AF', alignSelf: isMe ? 'flex-end' : 'flex-start', display: 'flex', alignItems: 'center', gap: '4px' }}>
                            {!isMe && <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: colors.border }} />}
                            {msg.senderName}
                          </span>
                          <div style={{
                            backgroundColor: colors.bg,
                            color: colors.text,
                            border: `1px solid ${colors.border}`,
                            padding: '10px 14px',
                            borderRadius: isMe ? '16px 16px 0 16px' : '16px 16px 16px 0',
                            fontSize: '13px',
                            lineHeight: '1.5',
                            wordBreak: 'break-all',
                            boxShadow: '0 4px 6px rgba(0,0,0,0.1)'
                          }}>
                            {msg.content}
                          </div>
                        </div>
                      );
                    })}
                    
                    {isAiStreaming && (
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#9CA3AF', fontSize: '12px', paddingLeft: '8px' }}>
                        <RefreshCw size={14} className="animate-spin" style={{ animation: 'spin 1.5s linear infinite' }} />
                        <span>AI 에이전트들이 답변을 스트리밍하고 있습니다...</span>
                      </div>
                    )}
                    <div ref={aiEndRef} />
                  </div>

                  {/* AI Input */}
                  <div style={{ padding: '20px', backgroundColor: '#0F172A', borderTop: '1px solid rgba(255,255,255,0.05)' }}>
                    <div style={{ display: 'flex', alignItems: 'center', backgroundColor: '#1E293B', borderRadius: '24px', padding: '8px 16px', border: '1px solid rgba(255,255,255,0.1)' }}>
                      <input
                        type="text"
                        placeholder="AI에게 질문해보세요..."
                        value={aiInput}
                        onChange={(e) => setAiInput(e.target.value)}
                        disabled={isAiStreaming}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') handleSendAiMessage();
                        }}
                        style={{ flex: 1, border: 'none', outline: 'none', fontSize: '13px', color: '#F3F4F6', backgroundColor: 'transparent', height: '20px', lineHeight: '20px', padding: 0, margin: 0, opacity: isAiStreaming ? 0.6 : 1 }}
                      />
                      <button
                        onClick={handleSendAiMessage}
                        disabled={isAiStreaming || !aiInput.trim()}
                        style={{ background: isAiStreaming ? '#4B5563' : 'linear-gradient(135deg, #3B82F6, #2563EB)', border: 'none', width: '32px', height: '32px', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: isAiStreaming ? 'not-allowed' : 'pointer', marginLeft: '8px', boxShadow: isAiStreaming ? 'none' : '0 2px 8px rgba(59, 130, 246, 0.3)' }}
                      >
                        <Send size={14} color="white" style={{ marginLeft: '-2px', marginTop: '2px' }} />
                      </button>
                    </div>
                  </div>
                </>
              )}
            </div>
          </div>
        )}

      </div>

      {/* 장치 설정 모달 */}
      {showSettings && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100000 }}>
          <div style={{ backgroundColor: '#1E293B', borderRadius: '16px', width: '480px', padding: '32px', border: '1px solid rgba(255,255,255,0.1)', boxShadow: '0 20px 40px rgba(0,0,0,0.5)', display: 'flex', flexDirection: 'column', gap: '24px', animation: 'slideUp 0.3s ease-out' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <h2 style={{ margin: 0, fontSize: '18px', fontWeight: '700', color: '#F3F4F6' }}>장치 설정</h2>
              <X size={20} color="#9CA3AF" cursor="pointer" onClick={() => setShowSettings(false)} />
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
              {/* 카메라 설정 */}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#9CA3AF', marginBottom: '8px' }}>
                  <Video size={16} /> <span style={{ fontSize: '14px', fontWeight: '600' }}>카메라</span>
                </div>
                <div style={{ backgroundColor: '#0F172A', borderRadius: '12px', padding: '12px', border: '1px solid rgba(255,255,255,0.05)' }}>
                  <select disabled style={{ width: '100%', backgroundColor: 'transparent', border: 'none', outline: 'none', color: '#9CA3AF', fontSize: '14px', cursor: 'not-allowed' }}>
                    <option value="cam1" style={{ backgroundColor: '#1E293B' }}>카메라 변경은 입장 전 미리보기에서 가능합니다.</option>
                  </select>
                </div>
              </div>

              {/* 마이크 설정 */}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#9CA3AF', marginBottom: '8px' }}>
                  <Mic size={16} /> <span style={{ fontSize: '14px', fontWeight: '600' }}>마이크</span>
                </div>
                <div style={{ backgroundColor: '#0F172A', borderRadius: '12px', padding: '12px', border: '1px solid rgba(255,255,255,0.05)' }}>
                  <select disabled style={{ width: '100%', backgroundColor: 'transparent', border: 'none', outline: 'none', color: '#9CA3AF', fontSize: '14px', cursor: 'not-allowed' }}>
                    <option value="mic1" style={{ backgroundColor: '#1E293B' }}>마이크 변경은 입장 전 미리보기에서 가능합니다.</option>
                  </select>
                </div>
              </div>

              {/* 스피커 설정 */}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#9CA3AF', marginBottom: '8px' }}>
                  <Volume2 size={16} /> <span style={{ fontSize: '14px', fontWeight: '600' }}>스피커</span>
                </div>
                <div style={{ backgroundColor: '#0F172A', borderRadius: '12px', padding: '12px', border: '1px solid rgba(255,255,255,0.05)' }}>
                  <select disabled style={{ width: '100%', backgroundColor: 'transparent', border: 'none', outline: 'none', color: '#9CA3AF', fontSize: '14px', cursor: 'not-allowed' }}>
                    <option value="spk1" style={{ backgroundColor: '#1E293B' }}>기본 스피커</option>
                  </select>
                </div>
              </div>
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '8px' }}>
              <button
                style={{ padding: '8px 24px', backgroundColor: '#3B82F6', color: 'white', borderRadius: '8px', border: 'none', fontWeight: '600', cursor: 'pointer', boxShadow: '0 4px 12px rgba(59,130,246,0.3)' }}
                onClick={() => setShowSettings(false)}
              >
                확인
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 통계/멤버 모달 */}
      {showStatsModal && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100000 }}>
          <div style={{ backgroundColor: '#0F172A', borderRadius: '16px', width: '800px', maxWidth: '90vw', height: '600px', border: '1px solid rgba(255,255,255,0.1)', boxShadow: '0 20px 40px rgba(0,0,0,0.5)', display: 'flex', flexDirection: 'column', overflow: 'hidden', animation: 'slideUp 0.3s ease-out' }}>

            {/* Header Tabs */}
            <div style={{ display: 'flex', alignItems: 'center', borderBottom: '1px solid rgba(255,255,255,0.05)', backgroundColor: '#1E293B' }}>
              <div style={{ padding: '16px 32px', borderBottom: '2px solid #3B82F6', color: '#F3F4F6', fontWeight: '700', fontSize: '15px' }}>
                멤버 (학습통계)
              </div>
              <div style={{ flex: 1 }} />
              <div style={{ padding: '0 20px', cursor: 'pointer' }} onClick={() => setShowStatsModal(false)}>
                <X size={20} color="#9CA3AF" />
              </div>
            </div>

            {/* Content Area */}
            <div className="custom-scrollbar" style={{ flex: 1, padding: '0', overflowY: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                <thead>
                  <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', color: '#9CA3AF', fontSize: '13px' }}>
                    <th style={{ padding: '16px 32px', fontWeight: '500' }}>이름</th>
                    <th style={{ padding: '16px 16px', fontWeight: '500' }}>역할</th>
                    <th style={{ padding: '16px 16px', fontWeight: '500' }}>획득 포인트</th>
                    <th style={{ padding: '16px 32px', fontWeight: '500' }}>가입일</th>
                  </tr>
                </thead>
                <tbody>
                  {members.map(member => (
                    <tr key={member.userId} style={{ borderBottom: '1px solid rgba(255,255,255,0.02)', backgroundColor: Number(member.userId) === Number(userId) ? 'rgba(255, 255, 255, 0.02)' : 'transparent' }}>
                      <td style={{ padding: '16px 32px', color: Number(member.userId) === Number(userId) ? '#60A5FA' : '#E5E7EB', fontWeight: '600', fontSize: '14px' }}>
                        {member.displayName} {Number(member.userId) === Number(userId) ? '(나)' : ''}
                      </td>
                      <td style={{ padding: '16px 16px', color: '#9CA3AF', fontSize: '14px' }}>
                        {member.role === 'LEADER' ? '방장' : '그룹원'}
                      </td>
                      <td style={{ padding: '16px 16px', color: '#E5E7EB', fontSize: '14px' }}>
                        {member.points || 0} 점
                      </td>
                      <td style={{ padding: '16px 32px', color: '#E5E7EB', fontSize: '14px' }}>
                        {member.joinedAt ? new Date(member.joinedAt).toLocaleDateString() : '-'}
                      </td>
                    </tr>
                  ))}
                  {members.length === 0 && (
                    <tr>
                      <td colSpan="4" style={{ padding: '32px', textStyle: 'center', color: '#9CA3AF' }}>가입된 멤버가 없습니다.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>
      )}

      {/* 방 관리 (설정) 모달 */}
      {showRoomManageModal && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100000 }}>
          <div style={{ backgroundColor: '#0F172A', borderRadius: '16px', width: '800px', maxWidth: '90vw', height: '720px', maxHeight: '90vh', border: '1px solid rgba(255,255,255,0.1)', boxShadow: '0 20px 40px rgba(0,0,0,0.5)', display: 'flex', flexDirection: 'column', overflow: 'hidden', animation: 'slideUp 0.3s ease-out' }}>

            {/* Header Tabs */}
            <div style={{ display: 'flex', alignItems: 'center', borderBottom: '1px solid rgba(255,255,255,0.05)', backgroundColor: '#1E293B', padding: '0 8px' }}>
              <div
                style={{ padding: '16px 24px', borderBottom: roomManageTab === 'settings' ? '2px solid #3B82F6' : '2px solid transparent', color: roomManageTab === 'settings' ? '#F3F4F6' : '#9CA3AF', fontWeight: '700', fontSize: '15px', cursor: 'pointer', transition: '0.2s' }}
                onClick={() => setRoomManageTab('settings')}
              >
                방 관리 (설정)
              </div>
              <div
                style={{ padding: '16px 24px', borderBottom: roomManageTab === 'members' ? '2px solid #3B82F6' : '2px solid transparent', color: roomManageTab === 'members' ? '#F3F4F6' : '#9CA3AF', fontWeight: '700', fontSize: '15px', cursor: 'pointer', transition: '0.2s' }}
                onClick={() => setRoomManageTab('members')}
              >
                멤버 관리
              </div>
              {study?.isPrivate && (
                <div
                  style={{ padding: '16px 24px', borderBottom: roomManageTab === 'applications' ? '2px solid #3B82F6' : '2px solid transparent', color: roomManageTab === 'applications' ? '#F3F4F6' : '#9CA3AF', fontWeight: '700', fontSize: '15px', cursor: 'pointer', transition: '0.2s', display: 'flex', alignItems: 'center', gap: '6px' }}
                  onClick={() => setRoomManageTab('applications')}
                >
                  가입 신청 관리 <span style={{ backgroundColor: '#EF4444', color: 'white', fontSize: '11px', padding: '2px 6px', borderRadius: '10px' }}>{applications.length}</span>
                </div>
              )}
              <div
                style={{ padding: '16px 24px', borderBottom: roomManageTab === 'quiz' ? '2px solid #3B82F6' : '2px solid transparent', color: roomManageTab === 'quiz' ? '#F3F4F6' : '#9CA3AF', fontWeight: '700', fontSize: '15px', cursor: 'pointer', transition: '0.2s' }}
                onClick={() => setRoomManageTab('quiz')}
              >
                실시간 퀴즈
              </div>
              <div style={{ flex: 1 }} />
              <div style={{ padding: '0 20px', cursor: 'pointer' }} onClick={() => setShowRoomManageModal(false)}>
                <X size={20} color="#9CA3AF" />
              </div>
            </div>

            {/* Content Area */}
            <div className="custom-scrollbar" style={{ flex: 1, padding: '24px 32px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '24px' }}>

              {roomManageTab === 'settings' ? (
                <>
                  {/* 해시태그 */}
                  <div style={{ display: 'flex', borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: '24px' }}>
                    <div style={{ width: '160px', color: '#E5E7EB', fontWeight: '600', fontSize: '14px', paddingTop: '8px' }}>해시태그</div>
                    <div style={{ flex: 1, paddingRight: '4px' }}>
                      <input type="text" placeholder="스터디를 대표하는 키워드를 입력하세요. (최대 3개)" style={{ width: '100%', boxSizing: 'border-box', backgroundColor: '#1E293B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '12px 16px', color: '#F3F4F6', fontSize: '14px', outline: 'none' }} />
                    </div>
                  </div>

                  {/* 기간 */}
                  <div style={{ display: 'flex', borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: '24px' }}>
                    <div style={{ width: '160px', color: '#E5E7EB', fontWeight: '600', fontSize: '14px', paddingTop: '8px' }}>기간</div>
                    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '12px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <div style={{ backgroundColor: '#1E293B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '8px 16px', color: '#F3F4F6', fontSize: '14px' }}>2021.11.22</div>
                        <span style={{ color: '#9CA3AF' }}>~</span>
                        <div style={{ backgroundColor: '#1E293B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '8px 16px', color: '#F3F4F6', fontSize: '14px' }}>2027.04.06</div>
                      </div>
                      <div style={{ backgroundColor: 'rgba(245, 158, 11, 0.1)', color: '#F59E0B', padding: '4px 12px', borderRadius: '4px', fontSize: '13px', fontWeight: '700', width: 'fit-content' }}>총 1961 일</div>
                    </div>
                  </div>

                  {/* 목표시간 */}
                  <div style={{ display: 'flex', borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: '24px' }}>
                    <div style={{ width: '160px', color: '#E5E7EB', fontWeight: '600', fontSize: '14px', paddingTop: '8px' }}>목표시간</div>
                    <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: '12px' }}>
                      <select style={{ backgroundColor: '#1E293B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '8px 16px', color: '#F3F4F6', fontSize: '14px', outline: 'none' }}>
                        <option>매일</option>
                      </select>
                      <input type="number" defaultValue={1} style={{ width: '80px', backgroundColor: '#1E293B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '8px 16px', color: '#F3F4F6', fontSize: '14px', outline: 'none' }} />
                    </div>
                  </div>


                  {/* 초기 장치 설정 */}
                  <div style={{ display: 'flex', borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: '24px' }}>
                    <div style={{ width: '160px', color: '#E5E7EB', fontWeight: '600', fontSize: '14px', paddingTop: '4px' }}>초기 장치 설정</div>
                    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '8px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '24px' }}>
                        <label style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#F3F4F6', fontSize: '14px' }}>
                          카메라 <div style={{ width: '36px', height: '20px', backgroundColor: '#22C55E', borderRadius: '10px', position: 'relative' }}><div style={{ width: '16px', height: '16px', backgroundColor: 'white', borderRadius: '50%', position: 'absolute', right: '2px', top: '2px' }} /></div>
                        </label>
                        <label style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#F3F4F6', fontSize: '14px' }}>
                          마이크 <div style={{ width: '36px', height: '20px', backgroundColor: '#4B5563', borderRadius: '10px', position: 'relative' }}><div style={{ width: '16px', height: '16px', backgroundColor: 'white', borderRadius: '50%', position: 'absolute', left: '2px', top: '2px' }} /></div>
                        </label>
                      </div>
                      <div style={{ fontSize: '12px', color: '#9CA3AF' }}>* 입장하는 인원들의 초기장치를 제어합니다.</div>
                    </div>
                  </div>

                  {/* 스터디 공지사항 */}
                  <div style={{ display: 'flex' }}>
                    <div style={{ width: '160px', color: '#E5E7EB', fontWeight: '600', fontSize: '14px', paddingTop: '8px' }}>스터디 공지사항</div>
                    <div style={{ flex: 1, paddingRight: '4px' }}>
                      <textarea
                        className="custom-scrollbar"
                        defaultValue="자격증 자율 스터디입니다.&#10;누구나 함께 공부하며 스터디 친구를 사귈 수 있습니다.&#10;&#10;해당 스터디룸은 StudyBridge에서 개설한 스터디룸으로,&#10;입장한 지 3일 이상 경과된 상황에서 카메라 송출이 되고 있지 않는다면 발견되는 즉시 무통보 강제 퇴장 조치..."
                        style={{ width: '100%', boxSizing: 'border-box', height: '120px', backgroundColor: '#1E293B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '12px 16px', color: '#F3F4F6', fontSize: '14px', outline: 'none', resize: 'none', lineHeight: '1.6' }}
                      />
                    </div>
                  </div>
                </>
              ) : roomManageTab === 'members' ? (
                <div style={{ width: '100%', overflowX: 'auto', padding: '8px 0' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', color: '#9CA3AF', fontSize: '13px', fontWeight: '500' }}>
                        <th style={{ padding: '12px 16px', fontWeight: '500' }}>이름</th>
                        <th style={{ padding: '12px 16px', fontWeight: '500' }}>최근 출석 시간</th>
                        <th style={{ padding: '12px 16px', fontWeight: '500' }}>최근 공부 시간</th>
                        <th style={{ padding: '12px 16px', fontWeight: '500' }}>누적 공부 시간</th>
                        <th style={{ padding: '12px 16px', fontWeight: '500', textAlign: 'right' }}>관리</th>
                      </tr>
                    </thead>
                    <tbody>
                      {members.map(member => {
                        const isLeader = member.role === 'LEADER';
                        const isMe = Number(member.userId) === Number(userId);
                        return (
                          <tr key={member.userId} style={{ borderBottom: '1px solid rgba(255,255,255,0.02)' }}>
                            <td style={{ padding: '16px' }}>
                              <div style={{ color: isLeader ? '#3B82F6' : '#F3F4F6', fontWeight: isLeader ? '600' : '500', fontSize: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                                <div style={{ width: '24px', height: '24px', borderRadius: '50%', backgroundColor: isLeader ? '#3B82F6' : '#6366F1', color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '12px' }}>
                                  {member.displayName ? member.displayName.charAt(0) : 'U'}
                                </div>
                                {member.displayName} {isMe ? '(나)' : ''}
                              </div>
                            </td>
                            <td style={{ padding: '16px', color: '#E5E7EB', fontSize: '14px' }}>
                              {formatAttendanceTime(member.recentAttendanceTime)}
                            </td>
                            <td style={{ padding: '16px', color: '#E5E7EB', fontSize: '14px' }}>
                              {formatSecondsToStudyTime(member.recentStudyTimeSeconds)}
                            </td>
                            <td style={{ padding: '16px', color: '#E5E7EB', fontSize: '14px' }}>
                              {formatSecondsToStudyTime(member.cumulativeStudyTimeSeconds)}
                            </td>
                            <td style={{ padding: '16px', textAlign: 'right' }}>
                              {isLeader ? (
                                <span style={{ color: '#9CA3AF', fontSize: '13px', fontWeight: '500' }}>방장</span>
                              ) : (
                                Number(study.leaderId) === Number(userId) && (
                                  <button
                                    onClick={async () => {
                                      if (window.confirm(`${member.displayName} 멤버를 정말로 강제 퇴장시키겠습니까?`)) {
                                        try {
                                          await groupService.kickMember(study.id, member.userId);
                                          showAlert('알림', '멤버가 강제 퇴장 처리되었습니다.', () => {
                                            loadMembers();
                                          });
                                        } catch (err) {
                                          showAlert('오류', err.response?.data?.message || '강제 퇴장에 실패했습니다.');
                                        }
                                      }
                                    }}
                                    style={{ padding: '6px 12px', backgroundColor: 'rgba(239,68,68,0.1)', color: '#EF4444', borderRadius: '6px', border: '1px solid rgba(239,68,68,0.2)', fontSize: '12px', fontWeight: '600', cursor: 'pointer', transition: '0.2s' }}
                                    onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = 'rgba(239,68,68,0.2)'; }}
                                    onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'rgba(239,68,68,0.1)'; }}
                                  >
                                    강제 퇴장
                                  </button>
                                )
                              )}
                            </td>
                          </tr>
                        );
                      })}
                      {members.length === 0 && (
                        <tr>
                          <td colSpan="5" style={{ padding: '32px', textAlign: 'center', color: '#9CA3AF' }}>참여 멤버가 없습니다.</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              ) : roomManageTab === 'quiz' ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', padding: '8px 0' }}>
                  <div style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: '20px' }}>
                    <h3 style={{ margin: '0 0 8px 0', fontSize: '16px', color: '#F3F4F6', fontWeight: '700' }}>실시간 웹소켓 퀴즈 출제</h3>
                    <p style={{ margin: 0, fontSize: '13px', color: '#9CA3AF', lineHeight: '1.5' }}>
                      스터디에 등록된 PDF 학습자료를 바탕으로 AI가 생성한 퀴즈를 출제할 수 있습니다.<br />
                      퀴즈를 시작하면 그룹 방에 접속한 모든 멤버의 화면에 실시간으로 퀴즈 팝업이 노출되며,<br />
                      문제를 풀 때 남은 시간에 비례하여 스터디 포인트가 자동 가산됩니다.
                    </p>
                  </div>

                  {canUseGroupQuizMaterials ? (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>

                      {/* STEP 1. PDF 업로드 → AI 퀴즈 자동 생성 */}
                      <div style={{ backgroundColor: 'rgba(37, 99, 235, 0.06)', border: '1px solid rgba(59, 130, 246, 0.18)', borderRadius: '12px', padding: '20px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#93C5FD', fontSize: '14px', fontWeight: '800' }}>
                          <Upload size={16} /> 1. PDF 학습자료 업로드
                        </div>
                        <p style={{ margin: 0, color: '#9CA3AF', fontSize: '12px', lineHeight: '1.5' }}>
                          PDF를 업로드하면 S3에 저장되고, 해당 자료를 기반으로 AI가 실시간 퀴즈를 자동 생성합니다. (PDF, 최대 30MB)
                        </p>
                        <input
                          type="text"
                          value={quizUploadTitle}
                          onChange={(e) => setQuizUploadTitle(e.target.value)}
                          placeholder="자료 제목 (예: OOP 핵심 개념 자료)"
                          disabled={isUploadingQuizPdf}
                          style={{ width: '100%', boxSizing: 'border-box', backgroundColor: '#0F172A', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '10px', padding: '11px 14px', color: '#F3F4F6', fontSize: '13px', outline: 'none' }}
                        />
                        <input
                          type="file"
                          accept="application/pdf,.pdf"
                          disabled={isUploadingQuizPdf}
                          onChange={(e) => { setQuizUploadFile(e.target.files?.[0] || null); setQuizUploadError(''); }}
                          style={{ width: '100%', boxSizing: 'border-box', backgroundColor: '#0F172A', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '10px', padding: '9px 12px', color: '#CBD5E1', fontSize: '12px' }}
                        />
                        {quizUploadFile && (
                          <div style={{ color: '#A7F3D0', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <FileText size={13} /> {quizUploadFile.name} ({formatFileSize(quizUploadFile.size)})
                          </div>
                        )}
                        {quizUploadError && (
                          <div style={{ backgroundColor: 'rgba(239, 68, 68, 0.12)', border: '1px solid rgba(239, 68, 68, 0.22)', borderRadius: '10px', padding: '9px 12px', color: '#FCA5A5', fontSize: '12px', lineHeight: '1.5' }}>
                            {quizUploadError}
                          </div>
                        )}
                        <button
                          onClick={handleUploadQuizPdf}
                          disabled={isUploadingQuizPdf}
                          style={{ alignSelf: 'flex-start', padding: '11px 18px', borderRadius: '9px', border: 'none', backgroundColor: isUploadingQuizPdf ? '#475569' : '#2563EB', color: 'white', fontSize: '13px', fontWeight: '800', cursor: isUploadingQuizPdf ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', gap: '8px' }}
                        >
                          {isUploadingQuizPdf ? <RefreshCw size={14} className="animate-spin" style={{ animation: 'spin 1.5s linear infinite' }} /> : <Upload size={14} />}
                          {isUploadingQuizPdf ? 'PDF 업로드 및 AI 퀴즈 생성 중...' : 'PDF 업로드 + AI 퀴즈 생성'}
                        </button>
                      </div>

                      {/* STEP 2. 생성된 퀴즈를 방 전체에 실시간 출제 */}
                      <div style={{ backgroundColor: 'rgba(16, 185, 129, 0.05)', border: '1px solid rgba(16, 185, 129, 0.18)', borderRadius: '12px', padding: '20px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#6EE7B7', fontSize: '14px', fontWeight: '800' }}>
                            <Play size={16} /> 2. 실시간 퀴즈 시작
                          </div>
                          <button onClick={loadGroupQuizzes} style={{ background: 'none', border: 'none', color: '#93C5FD', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px', fontSize: '12px' }} title="새로고침">
                            <RefreshCw size={13} /> 새로고침
                          </button>
                        </div>
                        {groupQuizzes.length === 0 ? (
                          <div style={{ color: '#94A3B8', fontSize: '12px', padding: '8px 0', lineHeight: '1.6' }}>
                            아직 생성된 퀴즈가 없습니다. 먼저 PDF 학습자료를 업로드하거나, 아래 고급 옵션에서 기존 퀴즈 번호를 입력해주세요.
                          </div>
                        ) : (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '220px', overflowY: 'auto' }}>
                            {groupQuizzes.map(quiz => (
                              <div key={quiz.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '10px', backgroundColor: 'rgba(15, 23, 42, 0.6)', border: '1px solid rgba(255,255,255,0.06)', borderRadius: '10px', padding: '12px' }}>
                                <div style={{ minWidth: 0 }}>
                                  <div style={{ color: '#E5E7EB', fontSize: '13px', fontWeight: '700', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{quiz.title}</div>
                                  <div style={{ color: '#94A3B8', fontSize: '11px', marginTop: '3px' }}>#{quiz.id} · {quiz.creatorName || '알 수 없음'} · {quiz.questionCount || 0}문항</div>
                                </div>
                                <button
                                  onClick={() => { handleQuizStart(quiz.id); setShowRoomManageModal(false); }}
                                  style={{ flexShrink: 0, padding: '9px 16px', borderRadius: '8px', border: 'none', backgroundColor: '#16A34A', color: 'white', fontSize: '12px', fontWeight: '800', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px', whiteSpace: 'nowrap' }}
                                >
                                  <Play size={13} fill="white" /> 시작
                                </button>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>

                      {/* 고급: 퀴즈 번호로 직접 시작 (기존 수동 방식 유지) */}
                      <details style={{ backgroundColor: 'rgba(255,255,255,0.02)', border: '1px solid rgba(255,255,255,0.07)', borderRadius: '12px', padding: '14px 18px' }}>
                        <summary style={{ color: '#9CA3AF', fontSize: '13px', fontWeight: '700', cursor: 'pointer' }}>고급 · 퀴즈 번호(ID)로 직접 시작</summary>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginTop: '14px', flexWrap: 'wrap' }}>
                          <input
                            type="number"
                            min="1"
                            value={quizIdInput}
                            onChange={(e) => setQuizIdInput(e.target.value)}
                            placeholder="퀴즈 ID (예: 1)"
                            style={{ width: '120px', backgroundColor: '#1E293B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '10px 16px', color: '#F3F4F6', fontSize: '14px', outline: 'none' }}
                          />
                          <button
                            onClick={() => { handleQuizStart(quizIdInput); setShowRoomManageModal(false); }}
                            style={{ padding: '10px 20px', backgroundColor: '#3B82F6', color: 'white', borderRadius: '8px', border: 'none', fontWeight: '700', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '8px' }}
                          >
                            <Play size={15} fill="white" /> 번호로 시작
                          </button>
                        </div>
                      </details>
                    </div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px', padding: '40px 0', opacity: 0.8 }}>
                      <AlertTriangle size={36} color="#F59E0B" />
                      <div style={{ color: '#E5E7EB', fontSize: '14px', fontWeight: '600' }}>퀴즈 시작 권한이 없습니다.</div>
                      <div style={{ color: '#9CA3AF', fontSize: '12px' }}>가입 승인 완료된 그룹원만 실시간 퀴즈를 시작할 수 있습니다.</div>
                    </div>
                  )}
                </div>
              ) : (
                <div style={{ width: '100%', overflowX: 'auto', padding: '8px 0' }}>
                  <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '16px' }}>
                    <button
                      style={{ padding: '8px 16px', backgroundColor: '#22C55E', color: 'white', borderRadius: '8px', border: 'none', fontWeight: '600', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', transition: '0.2s', boxShadow: '0 4px 12px rgba(34,197,94,0.3)' }}
                      onMouseEnter={(e) => e.currentTarget.style.backgroundColor = '#16A34A'}
                      onMouseLeave={(e) => e.currentTarget.style.backgroundColor = '#22C55E'}
                      onClick={() => {
                        showPrompt('멤버 초대', '초대할 사용자의 이메일을 입력하세요:', '예: user@example.com', (email) => {
                          if (email) {
                            if (email.includes('@')) {
                              showAlert('초대 완료', `${email} 님에게 스터디 초대장을 발송했습니다!`);
                            } else {
                              showAlert('오류', '올바른 이메일 형식이 아닙니다.');
                            }
                          }
                        });
                      }}
                    >
                      <UserPlus size={14} /> 멤버 초대하기
                    </button>
                  </div>
                  <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                    <thead>
                      <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', color: '#9CA3AF', fontSize: '13px', fontWeight: '500' }}>
                        <th style={{ padding: '12px 16px', fontWeight: '500', width: '20%' }}>신청자</th>
                        <th style={{ padding: '12px 16px', fontWeight: '500', width: '50%' }}>신청 메시지</th>
                        <th style={{ padding: '12px 16px', fontWeight: '500', width: '15%' }}>신청일</th>
                        <th style={{ padding: '12px 16px', fontWeight: '500', width: '15%', textAlign: 'center' }}>관리</th>
                      </tr>
                    </thead>
                    <tbody>
                      {applications.map(app => (
                        <tr key={app.applicationId} style={{ borderBottom: '1px solid rgba(255,255,255,0.02)' }}>
                          <td style={{ padding: '16px' }}>
                            <div style={{ color: '#F3F4F6', fontWeight: '500', fontSize: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                              <div style={{ width: '28px', height: '28px', borderRadius: '50%', backgroundColor: '#8B5CF6', color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '13px' }}>
                                {app.applicantName ? app.applicantName.charAt(0) : 'U'}
                              </div>
                              {app.applicantName}
                            </div>
                          </td>
                          <td style={{ padding: '16px', color: '#E5E7EB', fontSize: '13px', lineHeight: '1.5' }}>
                            {app.introduction || <span style={{ fontStyle: 'italic', color: '#9CA3AF' }}>(메시지 없음)</span>}
                          </td>
                          <td style={{ padding: '16px', color: '#9CA3AF', fontSize: '13px' }}>
                            {app.createdAt ? new Date(app.createdAt).toLocaleDateString() : '-'}
                          </td>
                          <td style={{ padding: '16px', textAlign: 'center' }}>
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}>
                              <button
                                onClick={async () => {
                                  try {
                                    await groupService.approveApplication(app.applicationId);
                                    showAlert('알림', '가입이 승인되었습니다.', () => {
                                      loadApplications();
                                      loadMembers();
                                    });
                                  } catch (err) {
                                    showAlert('오류', err.response?.data?.message || '승인에 실패했습니다.');
                                  }
                                }}
                                style={{ width: '32px', height: '32px', display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(34,197,94,0.1)', color: '#22C55E', borderRadius: '6px', border: '1px solid rgba(34,197,94,0.2)', cursor: 'pointer', transition: '0.2s' }}
                                onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'rgba(34,197,94,0.2)'}
                                onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'rgba(34,197,94,0.1)'}
                                title="승인"
                              >
                                <Check size={16} />
                              </button>
                              <button
                                onClick={async () => {
                                  try {
                                    await groupService.rejectApplication(app.applicationId);
                                    showAlert('알림', '가입이 거절되었습니다.', () => {
                                      loadApplications();
                                    });
                                  } catch (err) {
                                    showAlert('오류', err.response?.data?.message || '거절에 실패했습니다.');
                                  }
                                }}
                                style={{ width: '32px', height: '32px', display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(239,68,68,0.1)', color: '#EF4444', borderRadius: '6px', border: '1px solid rgba(239,68,68,0.2)', cursor: 'pointer', transition: '0.2s' }}
                                onMouseEnter={(e) => e.currentTarget.style.backgroundColor = 'rgba(239,68,68,0.2)'}
                                onMouseLeave={(e) => e.currentTarget.style.backgroundColor = 'rgba(239,68,68,0.1)'}
                                title="거절"
                              >
                                <X size={16} />
                              </button>
                            </div>
                          </td>
                        </tr>
                      ))}
                      {applications.length === 0 && (
                        <tr>
                          <td colSpan="4" style={{ padding: '32px', textAlign: 'center', color: '#9CA3AF' }}>대기 중인 가입 신청이 없습니다.</td>
                        </tr>
                      )}
                    </tbody>
                  </table>
                </div>
              )}
            </div>

            {/* Save Button */}
            <div style={{ padding: '24px 32px', display: 'flex', justifyContent: 'flex-end', backgroundColor: '#0F172A', borderTop: '1px solid rgba(255,255,255,0.05)' }}>
              <button
                style={{ padding: '8px 24px', backgroundColor: '#22C55E', color: 'white', borderRadius: '8px', border: 'none', fontWeight: '600', cursor: 'pointer', boxShadow: '0 4px 12px rgba(34,197,94,0.3)', transition: '0.2s' }}
                onMouseEnter={(e) => e.currentTarget.style.backgroundColor = '#16A34A'}
                onMouseLeave={(e) => e.currentTarget.style.backgroundColor = '#22C55E'}
                onClick={() => setShowRoomManageModal(false)}
              >
                닫기
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 관리자 신고/문의 관리 모달 */}
      {showAdminReportModal && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100000 }}>
          <div style={{ backgroundColor: '#0F172A', borderRadius: '16px', width: '800px', maxWidth: '90vw', height: 'auto', maxHeight: '90vh', border: '1px solid rgba(255,255,255,0.1)', boxShadow: '0 20px 40px rgba(0,0,0,0.5)', display: 'flex', flexDirection: 'column', overflow: 'hidden', animation: 'slideUp 0.3s ease-out' }}>

            {/* Header Tabs */}
            <div style={{ display: 'flex', alignItems: 'center', borderBottom: '1px solid rgba(255,255,255,0.05)', backgroundColor: '#1E293B', padding: '0 8px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '16px 24px', color: '#60A5FA', fontWeight: '700', fontSize: '15px' }}>
                <MessageSquare size={18} />
                문의 및 신고하기
              </div>
              <div style={{ width: '1px', height: '20px', backgroundColor: 'rgba(255,255,255,0.1)', margin: '0 16px' }} />
              <div
                style={{ padding: '16px 24px', borderBottom: adminReportTab === 'inquiry' ? '2px solid #60A5FA' : '2px solid transparent', color: adminReportTab === 'inquiry' ? '#F3F4F6' : '#9CA3AF', fontWeight: '700', fontSize: '15px', cursor: 'pointer', transition: '0.2s' }}
                onClick={() => setAdminReportTab('inquiry')}
              >
                1:1 문의
              </div>
              <div
                style={{ padding: '16px 24px', borderBottom: adminReportTab === 'report' ? '2px solid #EF4444' : '2px solid transparent', color: adminReportTab === 'report' ? '#F3F4F6' : '#9CA3AF', fontWeight: '700', fontSize: '15px', cursor: 'pointer', transition: '0.2s' }}
                onClick={() => setAdminReportTab('report')}
              >
                유저 신고
              </div>
              <div style={{ flex: 1 }} />
              <div style={{ padding: '0 20px', cursor: 'pointer' }} onClick={() => setShowAdminReportModal(false)}>
                <X size={20} color="#9CA3AF" />
              </div>
            </div>

            {/* Content Area */}
            <div className="custom-scrollbar" style={{ flex: 1, padding: '32px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '24px' }}>
              {adminReportTab === 'inquiry' ? (
                <>
                  {/* 문의 카테고리 */}
                  <div>
                    <div style={{ color: '#E5E7EB', fontWeight: '600', fontSize: '14px', marginBottom: '12px' }}>문의 유형</div>
                    <select 
                      value={inquiryType}
                      onChange={(e) => setInquiryType(e.target.value)}
                      style={{ width: '100%', backgroundColor: '#1E293B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '12px 16px', color: '#F3F4F6', fontSize: '14px', outline: 'none', cursor: 'pointer' }}
                    >
                      <option>이용 문의</option>
                      <option>버그 및 오류 신고</option>
                      <option>기타</option>
                    </select>
                  </div>

                  {/* 제목 */}
                  <div>
                    <div style={{ color: '#E5E7EB', fontWeight: '600', fontSize: '14px', marginBottom: '12px' }}>제목</div>
                    <input 
                      type="text" 
                      placeholder="문의 제목을 입력하세요." 
                      value={inquiryTitle}
                      onChange={(e) => setInquiryTitle(e.target.value)}
                      style={{ width: '100%', boxSizing: 'border-box', backgroundColor: '#1E293B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '12px 16px', color: '#F3F4F6', fontSize: '14px', outline: 'none' }} 
                    />
                  </div>

                  {/* 내용 */}
                  <div>
                    <div style={{ color: '#E5E7EB', fontWeight: '600', fontSize: '14px', marginBottom: '12px' }}>문의 내용</div>
                    <textarea 
                      placeholder="문의하실 내용을 상세히 적어주세요.&#13;&#10;최대한 빠르고 정확하게 답변해 드리겠습니다." 
                      value={inquiryContent}
                      onChange={(e) => setInquiryContent(e.target.value)}
                      style={{ width: '100%', boxSizing: 'border-box', height: '160px', backgroundColor: '#1E293B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '12px 16px', color: '#F3F4F6', fontSize: '14px', outline: 'none', resize: 'none', lineHeight: '1.6' }} 
                    />
                  </div>
                </>
              ) : (
                <>
                  {/* 신고 대상 */}
                  <div>
                    <div style={{ color: '#EF4444', fontWeight: '600', fontSize: '14px', marginBottom: '12px' }}>신고할 유저</div>
                    <select
                      value={reportUserId}
                      onChange={(e) => setReportUserId(e.target.value)}
                      style={{ width: '100%', backgroundColor: '#1E293B', border: '1px solid rgba(239,68,68,0.2)', borderRadius: '8px', padding: '12px 16px', color: '#F3F4F6', fontSize: '14px', outline: 'none', cursor: 'pointer' }}
                    >
                      <option value="">신고할 멤버를 선택하세요</option>
                      {members.filter(m => Number(m.userId) !== Number(userId)).map(m => (
                        <option key={m.userId} value={m.userId}>{m.displayName}</option>
                      ))}
                    </select>
                  </div>

                  {/* 신고 사유 */}
                  <div>
                    <div style={{ color: '#E5E7EB', fontWeight: '600', fontSize: '14px', marginBottom: '12px' }}>신고 사유</div>
                    <select
                      value={reportReasonType}
                      onChange={(e) => setReportReasonType(e.target.value)}
                      style={{ width: '100%', backgroundColor: '#1E293B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '12px 16px', color: '#F3F4F6', fontSize: '14px', outline: 'none', cursor: 'pointer' }}
                    >
                      <option value="욕설 / 비방 / 혐오 발언">욕설 / 비방 / 혐오 발언</option>
                      <option value="도배 및 스팸">도배 및 스팸</option>
                      <option value="부적절한 프로필 또는 닉네임">부적절한 프로필 또는 닉네임</option>
                      <option value="기타 (직접 작성)">기타 (직접 작성)</option>
                    </select>
                  </div>

                  {/* 내용 */}
                  <div>
                    <div style={{ color: '#E5E7EB', fontWeight: '600', fontSize: '14px', marginBottom: '12px' }}>상세 사유</div>
                    <textarea
                      placeholder="신고 사유를 상세히 적어주세요.&#13;&#10;허위 신고 시 서비스 이용에 불이익을 받을 수 있습니다."
                      value={reportDetail}
                      onChange={(e) => setReportDetail(e.target.value)}
                      style={{ width: '100%', boxSizing: 'border-box', height: '160px', backgroundColor: '#1E293B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '12px 16px', color: '#F3F4F6', fontSize: '14px', outline: 'none', resize: 'none', lineHeight: '1.6' }}
                    />
                  </div>
                </>
              )}
            </div>

            {/* Submit Button Area */}
            <div style={{ padding: '24px 32px', display: 'flex', justifyContent: 'flex-end', gap: '12px', backgroundColor: '#0F172A', borderTop: '1px solid rgba(255,255,255,0.05)' }}>
              <button
                style={{ padding: '10px 24px', backgroundColor: 'transparent', color: '#9CA3AF', borderRadius: '8px', border: '1px solid rgba(255,255,255,0.1)', fontWeight: '600', cursor: 'pointer', transition: '0.2s' }}
                onClick={() => setShowAdminReportModal(false)}
                onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = 'rgba(255,255,255,0.05)'; e.currentTarget.style.color = '#F3F4F6'; }}
                onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'transparent'; e.currentTarget.style.color = '#9CA3AF'; }}
              >
                취소
              </button>
              <button
                style={{ padding: '10px 24px', backgroundColor: adminReportTab === 'inquiry' ? '#22C55E' : '#EF4444', color: 'white', borderRadius: '8px', border: 'none', fontWeight: '600', cursor: 'pointer', boxShadow: adminReportTab === 'inquiry' ? '0 4px 12px rgba(34,197,94,0.3)' : '0 4px 12px rgba(239,68,68,0.3)', transition: '0.2s' }}
                onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = adminReportTab === 'inquiry' ? '#16A34A' : '#DC2626'; }}
                onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = adminReportTab === 'inquiry' ? '#22C55E' : '#EF4444'; }}
                onClick={async () => {
                  if (adminReportTab === 'inquiry') {
                    if (!inquiryTitle.trim() || !inquiryContent.trim()) {
                      showAlert('알림', '문의 제목과 내용을 입력해주세요.');
                      return;
                    }
                    try {
                      await inquiryService.submitInquiry({
                        type: inquiryType,
                        title: inquiryTitle,
                        content: inquiryContent
                      });
                      showAlert('성공', '1:1 문의가 성공적으로 접수되었습니다.');
                      setShowAdminReportModal(false);
                      setInquiryTitle('');
                      setInquiryContent('');
                    } catch (err) {
                      showAlert('오류', err.response?.data?.message || '문의 접수에 실패했습니다.');
                    }
                  } else {
                    if (!reportUserId) {
                      showAlert('알림', '신고할 멤버를 선택해주세요.');
                      return;
                    }
                    try {
                      await groupService.reportUser(study.id, {
                        reportedUserId: Number(reportUserId),
                        reason: `${reportReasonType} - ${reportDetail}`
                      });
                      showAlert('성공', '신고가 정상 접수되었습니다.');
                      setShowAdminReportModal(false);
                      setReportUserId('');
                      setReportDetail('');
                    } catch (err) {
                      showAlert('오류', err.response?.data?.message || '신고 접수에 실패했습니다.');
                    }
                  }
                }}
              >
                {adminReportTab === 'inquiry' ? '문의 접수하기' : '신고 접수하기'}
              </button>
            </div>
          </div>
        </div>
      )}
      {showPdfUploadModal && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, zIndex: 99998, display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(15, 23, 42, 0.78)', backdropFilter: 'blur(6px)' }}>
          <div style={{ width: '440px', maxWidth: '92vw', backgroundColor: '#1E293B', borderRadius: '16px', border: '1px solid rgba(255,255,255,0.1)', boxShadow: '0 24px 48px rgba(0,0,0,0.35)', padding: '24px', display: 'flex', flexDirection: 'column', gap: '18px' }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '12px' }}>
              <div>
                <h3 style={{ margin: '0 0 6px 0', color: '#F3F4F6', fontSize: '18px', fontWeight: '800' }}>PDF 등록 및 AI 퀴즈 생성</h3>
                <p style={{ margin: 0, color: '#9CA3AF', fontSize: '12px', lineHeight: '1.5' }}>그룹스터디 공유 자료로 PDF를 등록하고, 해당 자료 기반 실시간 퀴즈를 생성합니다.</p>
              </div>
              <button
                onClick={() => {
                  if (!isUploadingQuizPdf) {
                    setShowPdfUploadModal(false);
                    setQuizUploadError('');
                  }
                }}
                disabled={isUploadingQuizPdf}
                style={{ width: '32px', height: '32px', borderRadius: '50%', border: 'none', backgroundColor: 'rgba(255,255,255,0.06)', color: '#CBD5E1', cursor: isUploadingQuizPdf ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
              >
                <X size={16} />
              </button>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <label style={{ color: '#E5E7EB', fontSize: '13px', fontWeight: '700' }}>퀴즈 자료 제목</label>
              <input
                type="text"
                value={quizUploadTitle}
                onChange={(e) => setQuizUploadTitle(e.target.value)}
                placeholder="예: OOP 핵심 개념 자료"
                disabled={isUploadingQuizPdf}
                style={{ width: '100%', boxSizing: 'border-box', backgroundColor: '#0F172A', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '10px', padding: '12px 14px', color: '#F3F4F6', fontSize: '14px', outline: 'none' }}
              />
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <label style={{ color: '#E5E7EB', fontSize: '13px', fontWeight: '700' }}>PDF 파일</label>
              <input
                type="file"
                accept="application/pdf,.pdf"
                disabled={isUploadingQuizPdf}
                onChange={(e) => {
                  setQuizUploadFile(e.target.files?.[0] || null);
                  setQuizUploadError('');
                }}
                style={{ width: '100%', boxSizing: 'border-box', backgroundColor: '#0F172A', border: '1px solid rgba(255,255,255,0.12)', borderRadius: '10px', padding: '10px 12px', color: '#CBD5E1', fontSize: '13px' }}
              />
              <div style={{ color: '#64748B', fontSize: '11px' }}>PDF만 업로드할 수 있으며 최대 30MB까지 허용됩니다.</div>
            </div>

            {quizUploadError && (
              <div style={{ backgroundColor: 'rgba(239, 68, 68, 0.12)', border: '1px solid rgba(239, 68, 68, 0.22)', borderRadius: '10px', padding: '10px 12px', color: '#FCA5A5', fontSize: '12px', lineHeight: '1.5' }}>
                {quizUploadError}
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', paddingTop: '4px' }}>
              <button
                onClick={() => {
                  setShowPdfUploadModal(false);
                  setQuizUploadError('');
                }}
                disabled={isUploadingQuizPdf}
                style={{ padding: '11px 16px', borderRadius: '9px', border: '1px solid rgba(255,255,255,0.12)', backgroundColor: 'transparent', color: '#CBD5E1', fontSize: '13px', fontWeight: '700', cursor: isUploadingQuizPdf ? 'not-allowed' : 'pointer' }}
              >
                취소
              </button>
              <button
                onClick={handleUploadQuizPdf}
                disabled={isUploadingQuizPdf}
                style={{ padding: '11px 16px', borderRadius: '9px', border: 'none', backgroundColor: isUploadingQuizPdf ? '#475569' : '#2563EB', color: 'white', fontSize: '13px', fontWeight: '800', cursor: isUploadingQuizPdf ? 'not-allowed' : 'pointer', display: 'flex', alignItems: 'center', gap: '8px' }}
              >
                {isUploadingQuizPdf ? <RefreshCw size={14} className="animate-spin" /> : <Upload size={14} />}
                {isUploadingQuizPdf ? 'PDF 업로드 및 AI 퀴즈 생성 중...' : '업로드 및 퀴즈 생성'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 실시간 퀴즈 진행 모달 */}
      {activeQuiz && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, zIndex: 99999, display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(15, 23, 42, 0.8)', backdropFilter: 'blur(8px)' }}>
          <div style={{ backgroundColor: '#1E293B', borderRadius: '20px', padding: '32px', width: '500px', maxWidth: '90vw', border: '1px solid rgba(255,255,255,0.1)', boxShadow: '0 25px 50px -12px rgba(0,0,0,0.5)', display: 'flex', flexDirection: 'column', gap: '24px', animation: 'slideUp 0.3s ease-out' }}>

            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <span style={{ color: '#3B82F6', fontSize: '12px', fontWeight: '800', textTransform: 'uppercase', letterSpacing: '1px' }}>AI Live Quiz</span>
                <h2 style={{ margin: 0, fontSize: '18px', fontWeight: '700', color: '#F3F4F6' }}>{activeQuiz.quizTitle}</h2>
              </div>
              {(quizPhase === 'ENDED' || quizFinalResult) && (
                <div
                  onClick={resetQuizRuntimeState}
                  style={{ width: '32px', height: '32px', borderRadius: '50%', backgroundColor: 'rgba(255,255,255,0.05)', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' }}
                >
                  <X size={16} color="#9CA3AF" />
                </div>
              )}
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px', color: '#9CA3AF', fontWeight: '600' }}>
                <span>문제 {activeQuiz.currentIndex + 1} / {activeQuiz.totalQuestions}</span>
                <span style={{ color: quizTimer <= 5 ? '#EF4444' : '#10B981' }}>남은 시간: {quizTimer}초</span>
              </div>
              <div style={{ height: '6px', backgroundColor: 'rgba(255,255,255,0.05)', borderRadius: '3px', overflow: 'hidden' }}>
                <div style={{ width: `${(quizTimer / (activeQuiz.timeLimitSeconds || 30)) * 100}%`, height: '100%', backgroundColor: quizTimer <= 5 ? '#EF4444' : '#10B981', borderRadius: '3px', transition: 'width 1s linear' }} />
              </div>
            </div>

            <div style={{ backgroundColor: '#0F172A', borderRadius: '12px', padding: '20px', border: '1px solid rgba(255,255,255,0.03)' }}>
              <p style={{ margin: 0, fontSize: '15px', color: '#E5E7EB', fontWeight: '600', lineHeight: '1.6', wordBreak: 'keep-all' }}>
                {activeQuiz.questionText}
              </p>
            </div>

            {quizPhase !== 'ENDED' && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {activeQuiz.options.map((option, idx) => {
                  const isSelected = quizSelectedAnswer === idx;
                  const isCorrect = quizReveal?.correctAnswer === idx;
                  return (
                    <button
                      key={idx}
                      disabled={quizHasSubmitted || quizTimer <= 0 || quizPhase === 'REVEAL' || quizPhase === 'ENDED'}
                      onClick={() => handleQuizSubmit(idx)}
                      style={{
                        width: '100%',
                        textAlign: 'left',
                        padding: '14px 20px',
                        borderRadius: '12px',
                        border: isCorrect ? '2px solid #10B981' : (isSelected ? '2px solid #3B82F6' : '1px solid rgba(255,255,255,0.08)'),
                        backgroundColor: isCorrect ? 'rgba(16, 185, 129, 0.15)' : (isSelected ? 'rgba(59, 130, 246, 0.15)' : 'rgba(255,255,255,0.02)'),
                        color: isCorrect ? '#6EE7B7' : (isSelected ? '#60A5FA' : '#D1D5DB'),
                        fontSize: '14px',
                        fontWeight: (isCorrect || isSelected) ? '700' : '500',
                        cursor: (quizHasSubmitted || quizTimer <= 0 || quizPhase === 'REVEAL' || quizPhase === 'ENDED') ? 'not-allowed' : 'pointer',
                        transition: 'all 0.2s',
                        outline: 'none'
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <div style={{ width: '24px', height: '24px', borderRadius: '50%', backgroundColor: isCorrect ? '#10B981' : (isSelected ? '#3B82F6' : 'rgba(255,255,255,0.1)'), color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '12px', fontWeight: '700' }}>
                          {idx + 1}
                        </div>
                        <span style={{ flex: 1 }}>{option}</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            )}

            {quizPhase === 'QUESTION' && quizHasSubmitted && (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '10px', color: '#9CA3AF', fontSize: '13px', padding: '10px 0' }}>
                <RefreshCw size={16} className="animate-spin" />
                <span>제출 완료. 30초 종료 후 정답이 공개됩니다.</span>
              </div>
            )}

            {quizPhase === 'REVEAL' && quizReveal && (
              <div style={{ backgroundColor: 'rgba(16, 185, 129, 0.08)', border: '1px solid rgba(16, 185, 129, 0.25)', borderRadius: '14px', padding: '16px' }}>
                <div style={{ color: '#6EE7B7', fontSize: '13px', fontWeight: '800', marginBottom: '6px' }}>정답 공개</div>
                <div style={{ color: '#E5E7EB', fontSize: '14px', lineHeight: '1.6' }}>
                  정답은 <span style={{ color: '#6EE7B7', fontWeight: '800' }}>보기 {quizReveal.correctAnswer + 1}</span>입니다.
                </div>
                <div style={{ color: '#94A3B8', fontSize: '12px', marginTop: '6px' }}>
                  포인트가 반영되었습니다.
                </div>
              </div>
            )}

            {quizPhase === 'ENDED' && (
              <div style={{ backgroundColor: 'rgba(59, 130, 246, 0.08)', border: '1px solid rgba(59, 130, 246, 0.25)', borderRadius: '14px', padding: '16px' }}>
                <div style={{ color: '#93C5FD', fontSize: '13px', fontWeight: '800', marginBottom: '6px' }}>퀴즈 종료</div>
                <div style={{ color: '#E5E7EB', fontSize: '14px', lineHeight: '1.6' }}>
                  모든 문제가 종료되었습니다. 최종 점수판을 확인하세요.
                </div>
              </div>
            )}

            {quizScoreboard && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                <div style={{ borderBottom: '1px solid rgba(255,255,255,0.05)', paddingBottom: '8px' }}>
                  <h3 style={{ margin: 0, fontSize: '14px', color: '#F3F4F6', fontWeight: '700' }}>실시간 랭킹 (누적 포인트)</h3>
                </div>
                <div className="custom-scrollbar" style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '180px', overflowY: 'auto' }}>
                  {quizScoreboard.map((entry, idx) => {
                    const isMe = Number(entry.userId) === Number(userId);
                    return (
                      <div key={idx} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '10px 16px', borderRadius: '8px', backgroundColor: isMe ? 'rgba(59,130,246,0.1)' : 'rgba(255,255,255,0.02)', border: isMe ? '1px solid rgba(59,130,246,0.2)' : '1px solid transparent' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                          <span style={{ fontSize: '13px', fontWeight: '800', color: idx === 0 ? '#F59E0B' : idx === 1 ? '#9CA3AF' : idx === 2 ? '#B45309' : '#4B5563' }}>
                            {idx + 1}위
                          </span>
                          <span style={{ fontSize: '13px', fontWeight: isMe ? '700' : '500', color: isMe ? '#60A5FA' : '#E5E7EB' }}>
                            {entry.displayName} {isMe ? '(나)' : ''}
                          </span>
                        </div>
                        <span style={{ fontSize: '13px', fontWeight: '700', color: '#10B981' }}>{entry.points} P</span>
                      </div>
                    );
                  })}
                </div>

                {quizPhase === 'ENDED' ? (
                  <button
                    onClick={resetQuizRuntimeState}
                    style={{ padding: '12px', backgroundColor: '#EF4444', color: 'white', borderRadius: '8px', border: 'none', fontWeight: '700', cursor: 'pointer', transition: '0.2s', width: '100%' }}
                  >
                    퀴즈 종료
                  </button>
                ) : (
                  <div style={{ textAlign: 'center', color: '#9CA3AF', fontSize: '12px' }}>
                    {quizPhase === 'REVEAL' ? '잠시 후 다음 문제가 자동으로 시작됩니다.' : '30초 카운트다운 중입니다.'}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      )}

      {/* 퀴즈 시작 실패 에러 모달 (가짜 문제/0초 화면 대신 표시) */}
      {quizError && !activeQuiz && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, zIndex: 99999, display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(15, 23, 42, 0.8)', backdropFilter: 'blur(8px)' }}>
          <div style={{ backgroundColor: '#1E293B', borderRadius: '20px', padding: '32px', width: '420px', maxWidth: '90vw', border: '1px solid rgba(239,68,68,0.3)', boxShadow: '0 25px 50px -12px rgba(0,0,0,0.5)', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px' }}>
            <AlertTriangle size={40} color="#F59E0B" />
            <h2 style={{ margin: 0, fontSize: '17px', fontWeight: '700', color: '#F3F4F6' }}>퀴즈를 시작할 수 없습니다</h2>
            <p style={{ margin: 0, fontSize: '14px', color: '#CBD5E1', textAlign: 'center', lineHeight: '1.6', wordBreak: 'keep-all' }}>{quizError}</p>
            <button
              onClick={() => setQuizError(null)}
              style={{ marginTop: '4px', padding: '11px 28px', backgroundColor: '#3B82F6', color: 'white', borderRadius: '8px', border: 'none', fontWeight: '700', cursor: 'pointer' }}
            >
              확인
            </button>
          </div>
        </div>
      )}

      {/* 커스텀 모달 UI */}
      {customAlert.isOpen && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, zIndex: 100000, display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(0,0,0,0.4)', backdropFilter: 'blur(2px)' }}>
          <div style={{ backgroundColor: '#ffffff', borderRadius: '12px', padding: '24px 24px 20px', width: '320px', boxShadow: '0 4px 20px rgba(0,0,0,0.15)', animation: 'fadeIn 0.2s ease-out' }}>
            <h3 style={{ margin: '0 0 12px 0', fontSize: '16px', fontWeight: '700', color: '#111827', textAlign: 'center' }}>{customAlert.title || '알림'}</h3>
            <p style={{ margin: '0 0 20px 0', fontSize: '14px', color: '#4B5563', lineHeight: '1.5', whiteSpace: 'pre-wrap', textAlign: 'center' }}>{customAlert.message}</p>

            {customAlert.type === 'prompt' && (
              <input
                autoFocus
                type="text"
                placeholder={customAlert.inputPlaceholder}
                value={customAlert.inputValue}
                onChange={(e) => setCustomAlert(prev => ({ ...prev, inputValue: e.target.value }))}
                onKeyDown={(e) => e.key === 'Enter' && customAlert.onConfirm(customAlert.inputValue)}
                style={{ width: '100%', boxSizing: 'border-box', padding: '10px 12px', borderRadius: '8px', border: '1px solid #D1D5DB', backgroundColor: '#F9FAFB', color: '#111827', marginBottom: '24px', outline: 'none', fontSize: '14px' }}
              />
            )}

            <div style={{ display: 'flex', justifyContent: 'center', gap: '8px' }}>
              {(customAlert.type === 'confirm' || customAlert.type === 'prompt') && (
                <button
                  style={{ flex: 1, padding: '10px 0', backgroundColor: '#F3F4F6', color: '#4B5563', border: '1px solid #E5E7EB', borderRadius: '8px', cursor: 'pointer', fontWeight: '600', fontSize: '14px' }}
                  onClick={customAlert.onCancel}
                >
                  취소
                </button>
              )}
              <button
                style={{ flex: 1, padding: '10px 0', backgroundColor: '#22C55E', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', fontWeight: '600', fontSize: '14px' }}
                onClick={() => customAlert.type === 'prompt' ? customAlert.onConfirm(customAlert.inputValue) : customAlert.onConfirm()}
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
