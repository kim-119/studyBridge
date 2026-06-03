import React, { useState, useEffect } from 'react';
import {
  Users, User, X, MicOff, Video, VideoOff, Maximize, Minimize, Gift, UserPlus,
  Settings, MessageSquare, Calendar, ClipboardList, Mic,
  Search, AlertTriangle, Play, RefreshCw, VolumeX, Volume2, Monitor, Edit2, Send, Check
} from 'lucide-react';
import { Client } from '@stomp/stompjs';
import SockJS from 'sockjs-client';
import { useAuth } from '../hooks/useAuth';
import { groupService } from '../services/api';

function VideoFeed({ stream, isLocal, displayName, isMuted, isCamOn, isMicOn = true }) {
  const videoRef = React.useRef(null);
  const [isSpeaking, setIsSpeaking] = React.useState(false);

  useEffect(() => {
    if (videoRef.current && stream && isCamOn) {
      videoRef.current.srcObject = stream;
    }
  }, [stream, isCamOn]);

  useEffect(() => {
    if (!stream || !isMicOn) {
      setIsSpeaking(false);
      return;
    }

    const audioTracks = stream.getAudioTracks();
    if (audioTracks.length === 0) {
      setIsSpeaking(false);
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
      }, 150);
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

  if (!isCamOn || !stream) {
    return (
      <div style={{ position: 'relative', backgroundColor: '#1E293B', borderRadius: '16px', overflow: 'hidden', aspectRatio: '16/9', border: `${speakBorderWidth} solid ${speakBorderColor}`, display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: speakBoxShadow, transition: 'all 0.2s ease' }}>
        <div style={{ width: '64px', height: '64px', borderRadius: '50%', backgroundColor: '#334155', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 8px 24px rgba(0,0,0,0.4)' }}>
          <User size={32} color="#9CA3AF" />
        </div>
        <div style={{ position: 'absolute', bottom: '12px', left: '12px', padding: '4px 10px', borderRadius: '20px', backgroundColor: 'rgba(15, 23, 42, 0.6)', backdropFilter: 'blur(8px)', border: '1px solid rgba(255,255,255,0.1)' }}>
          <span style={{ color: 'white', fontSize: '13px', fontWeight: '600' }}>
            {displayName} {isLocal ? '(나)' : ''}
          </span>
        </div>
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
        style={{ width: '100%', height: '100%', objectFit: 'cover' }}
      />
      <div style={{ position: 'absolute', bottom: '12px', left: '12px', padding: '4px 10px', borderRadius: '20px', backgroundColor: 'rgba(15, 23, 42, 0.6)', backdropFilter: 'blur(8px)', border: '1px solid rgba(255,255,255,0.1)' }}>
        <span style={{ color: 'white', fontSize: '13px', fontWeight: '600' }}>
          {displayName} {isLocal ? '(나)' : ''}
        </span>
      </div>
    </div>
  );
}

export default function StudyRoom({ study, onClose }) {
  const { userId } = useAuth();
  const [members, setMembers] = useState([]);
  const [applications, setApplications] = useState([]);
  const [activeTab, setActiveTab] = useState('chat');
  const [isMicOn, setIsMicOn] = useState(false);
  const [isVideoOn, setIsVideoOn] = useState(true);
  const [showSettings, setShowSettings] = useState(false);
  const [showStatsModal, setShowStatsModal] = useState(false);
  const [showRoomManageModal, setShowRoomManageModal] = useState(false);
  const [roomManageTab, setRoomManageTab] = useState('settings'); // 'settings' | 'members'
  const [showAdminReportModal, setShowAdminReportModal] = useState(false);
  const [adminReportTab, setAdminReportTab] = useState('inquiry'); // 'inquiry' | 'report'
  const [isCamFullScreen, setIsCamFullScreen] = useState(false);

  const [chatMessages, setChatMessages] = useState([]);
  const [chatInput, setChatInput] = useState('');
  const [stompClient, setStompClient] = useState(null);
  
  const [activeQuiz, setActiveQuiz] = useState(null);
  const [quizTimer, setQuizTimer] = useState(0);
  const [quizScoreboard, setQuizScoreboard] = useState(null);
  const [quizSelectedAnswer, setQuizSelectedAnswer] = useState(null);
  const [quizHasSubmitted, setQuizHasSubmitted] = useState(false);
  const [quizStartTime, setQuizStartTime] = useState(null);
  const [quizIdInput, setQuizIdInput] = useState('1');
  
  const [localStream, setLocalStream] = useState(null);
  const localStreamRef = React.useRef(null);
  useEffect(() => {
    localStreamRef.current = localStream;
  }, [localStream]);

  const peerConnections = React.useRef({});
  const [peerStreams, setPeerStreams] = useState({});

  const myMember = members.find(m => Number(m.userId) === Number(userId));
  const myDisplayName = myMember ? myMember.displayName : `User_${userId}`;

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

  // 1. Local Media Stream 획득
  useEffect(() => {
    let stream = null;
    async function getMedia() {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: isVideoOn,
          audio: isMicOn
        });
        setLocalStream(stream);
      } catch (e) {
        console.warn("Failed to get media devices, playing dummy visual.", e);
      }
    }
    getMedia();

    return () => {
      if (stream) {
        stream.getTracks().forEach(track => track.stop());
      }
    };
  }, [isVideoOn, isMicOn]);

  // 2. WebRTC Peer Connection Helpers
  const rtcConfig = {
    iceServers: [
      { urls: 'stun:stun.l.google.com:19302' },
      { urls: 'stun:stun1.l.google.com:19302' },
    ]
  };

  const createPeerConnection = async (peerId, peerName, isOffer, client) => {
    if (peerConnections.current[peerId]) {
      peerConnections.current[peerId].pc.close();
    }

    const pc = new RTCPeerConnection(rtcConfig);
    peerConnections.current[peerId] = { pc, displayName: peerName };

    if (localStreamRef.current) {
      localStreamRef.current.getTracks().forEach(track => {
        pc.addTrack(track, localStreamRef.current);
      });
    }

    pc.onicecandidate = (event) => {
      if (event.candidate && client && client.connected) {
        client.publish({
          destination: `/topic/group/${study.id}/webrtc`,
          body: JSON.stringify({
            senderId: userId,
            senderName: myDisplayName,
            targetId: peerId,
            type: 'CANDIDATE',
            candidate: event.candidate
          })
        });
      }
    };

    pc.ontrack = (event) => {
      console.log(`ontrack event from peerId=${peerId}`);
      const remoteStream = event.streams[0];
      setPeerStreams(prev => ({
        ...prev,
        [peerId]: { stream: remoteStream, displayName: peerName }
      }));
    };

    if (isOffer) {
      const offer = await pc.createOffer();
      await pc.setLocalDescription(offer);
      
      if (client && client.connected) {
        client.publish({
          destination: `/topic/group/${study.id}/webrtc`,
          body: JSON.stringify({
            senderId: userId,
            senderName: myDisplayName,
            targetId: peerId,
            type: 'OFFER',
            sdp: offer
          })
        });
      }
    }

    return pc;
  };

  const handleOffer = async (peerId, peerName, sdp, client) => {
    const pc = await createPeerConnection(peerId, peerName, false, client);
    await pc.setRemoteDescription(new RTCSessionDescription(sdp));
    
    const answer = await pc.createAnswer();
    await pc.setLocalDescription(answer);

    if (client && client.connected) {
      client.publish({
        destination: `/topic/group/${study.id}/webrtc`,
        body: JSON.stringify({
          senderId: userId,
          senderName: myDisplayName,
          targetId: peerId,
          type: 'ANSWER',
          sdp: answer
        })
      });
    }
  };

  const handleAnswer = async (peerId, sdp) => {
    const connection = peerConnections.current[peerId];
    if (connection) {
      await connection.pc.setRemoteDescription(new RTCSessionDescription(sdp));
    }
  };

  const handleCandidate = async (peerId, candidate) => {
    const connection = peerConnections.current[peerId];
    if (connection) {
      await connection.pc.addIceCandidate(new RTCIceCandidate(candidate));
    }
  };

  const closePeerConnection = (peerId) => {
    const connection = peerConnections.current[peerId];
    if (connection) {
      connection.pc.close();
      delete peerConnections.current[peerId];
    }
    setPeerStreams(prev => {
      const copy = { ...prev };
      delete copy[peerId];
      return copy;
    });
  };

  // 3. STOMP & WebRTC Lifecycle
  useEffect(() => {
    if (!study?.id || !userId) return;

    const hostname = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
    const protocol = typeof window !== 'undefined' && window.location.protocol === 'https:' ? 'wss' : 'ws';
    const defaultBrokerURL = `${protocol}://${hostname}:8080/ws-group/websocket`;
    const brokerURL = import.meta.env.VITE_WS_URL || defaultBrokerURL;

    const client = new Client({
      brokerURL,
      reconnectDelay: 5000,
      heartbeatIncoming: 4000,
      heartbeatOutgoing: 4000,
    });

    client.onConnect = (frame) => {
      console.log('Connected to group study socket: ' + frame);
      
      client.subscribe(`/topic/group/${study.id}/chat`, (message) => {
        const payload = JSON.parse(message.body);
        setChatMessages(prev => [...prev, payload]);
      });

      client.subscribe(`/topic/group/${study.id}/quiz/question`, (message) => {
        const payload = JSON.parse(message.body);
        console.log('Received quiz question:', payload);
        setActiveQuiz(payload);
        setQuizTimer(payload.timeLimitSeconds);
        setQuizSelectedAnswer(null);
        setQuizHasSubmitted(false);
        setQuizStartTime(Date.now());
        setQuizScoreboard(null);
      });

      client.subscribe(`/topic/group/${study.id}/quiz/scoreboard`, (message) => {
        const payload = JSON.parse(message.body);
        console.log('Received quiz scoreboard:', payload);
        setQuizScoreboard(payload);
      });

      client.subscribe(`/topic/group/${study.id}/webrtc`, async (message) => {
        const payload = JSON.parse(message.body);
        
        if (Number(payload.senderId) === Number(userId)) return;

        console.log(`WebRTC signal: ${payload.type} from=${payload.senderId}`);

        if (payload.type === 'JOIN') {
          await createPeerConnection(payload.senderId, payload.senderName, true, client);
        } else if (payload.type === 'OFFER') {
          if (Number(payload.targetId) === Number(userId)) {
            await handleOffer(payload.senderId, payload.senderName, payload.sdp, client);
          }
        } else if (payload.type === 'ANSWER') {
          if (Number(payload.targetId) === Number(userId)) {
            await handleAnswer(payload.senderId, payload.sdp);
          }
        } else if (payload.type === 'CANDIDATE') {
          if (Number(payload.targetId) === Number(userId)) {
            await handleCandidate(payload.senderId, payload.candidate);
          }
        } else if (payload.type === 'LEAVE') {
          closePeerConnection(payload.senderId);
        }
      });

      client.publish({
        destination: `/topic/group/${study.id}/webrtc`,
        body: JSON.stringify({
          senderId: userId,
          senderName: myDisplayName,
          type: 'JOIN'
        })
      });
    };

    client.onStompError = (frame) => {
      console.error('STOMP error', frame);
    };

    client.activate();
    setStompClient(client);

    return () => {
      if (client) {
        if (client.connected) {
          client.publish({
            destination: `/topic/group/${study.id}/webrtc`,
            body: JSON.stringify({
              senderId: userId,
              senderName: myDisplayName,
              type: 'LEAVE'
            })
          });
        }
        client.deactivate();
      }
    };
  }, [study?.id, userId, myDisplayName]);

  // 4. Local Stream 변경 시 Peer Connection의 오디오/비디오 트랙 동적 대체
  useEffect(() => {
    if (!localStream) return;
    Object.keys(peerConnections.current).forEach(peerId => {
      const conn = peerConnections.current[peerId];
      if (conn && conn.pc) {
        const senders = conn.pc.getSenders();
        localStream.getTracks().forEach(track => {
          const sender = senders.find(s => s.track && s.track.kind === track.kind);
          if (sender) {
            sender.replaceTrack(track).catch(err => {
              console.warn("Failed to replace track for peer", peerId, err);
            });
          } else {
            conn.pc.addTrack(track, localStream);
          }
        });
      }
    });
  }, [localStream]);

  useEffect(() => {
    return () => {
      Object.keys(peerConnections.current).forEach(peerId => {
        peerConnections.current[peerId].pc.close();
      });
      peerConnections.current = {};
    };
  }, []);

  // 퀴즈 타이머 이펙트
  useEffect(() => {
    if (activeQuiz && quizTimer > 0 && !quizHasSubmitted) {
      const interval = setInterval(() => {
        setQuizTimer(prev => {
          if (prev <= 1) {
            handleQuizSubmit(-1);
            return 0;
          }
          return prev - 1;
        });
      }, 1000);
      return () => clearInterval(interval);
    }
  }, [activeQuiz, quizTimer, quizHasSubmitted]);

  const handleQuizSubmit = (answerIndex) => {
    if (quizHasSubmitted || !activeQuiz || !stompClient || !stompClient.connected) return;

    setQuizSelectedAnswer(answerIndex);
    setQuizHasSubmitted(true);

    const timeTaken = quizStartTime ? Math.round((Date.now() - quizStartTime) / 1000) : 5;

    stompClient.publish({
      destination: `/pub/group/${study.id}/quiz/submit`,
      body: JSON.stringify({
        userId: userId,
        questionId: activeQuiz.questionId,
        submittedAnswer: String(answerIndex),
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

    stompClient.publish({
      destination: `/pub/group/${study.id}/quiz/start`,
      body: JSON.stringify({
        quizId: Number(quizId)
      })
    });
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

  useEffect(() => {
    if (study?.id) {
      loadMembers();
      loadApplications();
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
      `}</style>

      {/* Header - Glassmorphic Dark */}
      {!isCamFullScreen && (
        <div style={{ height: '60px', backgroundColor: 'rgba(15, 23, 42, 0.7)', backdropFilter: 'blur(16px)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 24px', borderBottom: '1px solid rgba(255,255,255,0.08)', zIndex: 10 }}>

          <div style={{ display: 'flex', alignItems: 'center', gap: '24px' }}>
            {/* Text Logo Area */}
            <div style={{ display: 'flex', alignItems: 'center', cursor: 'pointer', gap: '6px' }}>
              <span style={{ fontSize: '20px', fontWeight: '900', letterSpacing: '-0.5px', background: 'linear-gradient(90deg, #84cc16, #eab308, #f97316)', WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent' }}>
                StudyBridge
              </span>
            </div>

            <div style={{ width: '1px', height: '20px', backgroundColor: 'rgba(255,255,255,0.1)' }} />

            {/* Title Area */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <h1 style={{ margin: 0, color: '#F3F4F6', fontSize: '16px', fontWeight: '600' }}>{study.title}</h1>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', backgroundColor: 'rgba(59, 130, 246, 0.15)', color: '#60A5FA', padding: '4px 10px', borderRadius: '12px', fontSize: '12px', fontWeight: '600' }}>
                <Users size={14} /> {study.currentMembers || 2} / {study.maxMembers || 16}
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

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '20px', height: '100%', alignContent: 'start' }}>

            {/* Local Video Feed */}
            <VideoFeed
              stream={localStream}
              isLocal={true}
              displayName={myDisplayName}
              isMuted={true}
              isCamOn={isVideoOn}
              isMicOn={isMicOn}
            />

            {/* Remote Peer Video Feeds */}
            {Object.keys(peerStreams).map(peerId => {
              const peer = peerStreams[peerId];
              return (
                <VideoFeed
                  key={peerId}
                  stream={peer.stream}
                  isLocal={false}
                  displayName={peer.displayName}
                  isMuted={false}
                  isCamOn={true}
                />
              );
            })}

            {/* Empty Slots */}
            {Array.from({ length: Math.max(0, (study.maxMembers || 16) - 1 - Object.keys(peerStreams).length) }).map((_, i) => (
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
          <div style={{ width: '340px', backgroundColor: '#0F172A', display: 'flex', flexDirection: 'column', borderLeft: '1px solid rgba(255,255,255,0.05)' }}>

            {/* Participants Area */}
            <div style={{ padding: '20px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
                <div style={{ fontSize: '14px', fontWeight: '700', color: '#F3F4F6', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  참여자 목록
                  <span style={{ backgroundColor: 'rgba(59, 130, 246, 0.2)', color: '#60A5FA', padding: '2px 8px', borderRadius: '10px', fontSize: '12px' }}>2 / {study.maxMembers || 16}</span>
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
                    const peerFeed = peerStreams[member.userId];
                    if (peerFeed && peerFeed.stream) {
                      isUserMicOn = peerFeed.stream.getAudioTracks().some(t => t.enabled && t.readyState === 'live');
                      isUserVideoOn = peerFeed.stream.getVideoTracks().some(t => t.enabled && t.readyState === 'live');
                    }
                  }

                  return (
                    <div key={member.userId} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px', borderRadius: '12px', backgroundColor: 'rgba(255,255,255,0.02)' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <div style={{ width: '32px', height: '32px', borderRadius: '50%', backgroundColor: member.role === 'LEADER' ? '#3B82F6' : '#334155', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '13px', fontWeight: '700', color: 'white' }}>
                          {member.displayName ? member.displayName.charAt(0) : 'U'}
                        </div>
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

            {/* Chat Area */}
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', backgroundColor: '#111827' }}>
              <div style={{ padding: '16px 20px', borderBottom: '1px solid rgba(255,255,255,0.05)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '14px', fontWeight: '700', color: '#F3F4F6' }}>채팅</span>
              </div>

              <div className="custom-scrollbar" style={{ flex: 1, padding: '20px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {/* Notice Box */}
                <div style={{ backgroundColor: 'rgba(239, 68, 68, 0.1)', border: '1px solid rgba(239, 68, 68, 0.2)', borderRadius: '12px', padding: '16px', position: 'relative' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#F87171', fontSize: '13px', fontWeight: '700', marginBottom: '8px' }}>
                    <AlertTriangle size={16} /> 서비스 이용 안내
                  </div>
                  <div style={{ color: '#FCA5A5', fontSize: '12px', lineHeight: '1.6', wordBreak: 'keep-all' }}>
                    불건전한 행동이나 욕설 발견 시 즉각 강제 퇴장 및 계정 정지 조치가 이루어질 수 있습니다. 모두가 집중할 수 있는 분위기를 만들어주세요.
                  </div>
                </div>

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
                  <select style={{ width: '100%', backgroundColor: 'transparent', border: 'none', outline: 'none', color: '#F3F4F6', fontSize: '14px', cursor: 'pointer' }}>
                    <option value="cam1" style={{ backgroundColor: '#1E293B' }}>기본 카메라 (FaceTime HD Camera)</option>
                    <option value="cam2" style={{ backgroundColor: '#1E293B' }}>OBS Virtual Camera</option>
                  </select>
                </div>
                <div style={{ fontSize: '12px', color: '#34D399', marginTop: '6px', marginLeft: '4px' }}>정상적으로 작동중입니다</div>
              </div>

              {/* 마이크 설정 */}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#9CA3AF', marginBottom: '8px' }}>
                  <Mic size={16} /> <span style={{ fontSize: '14px', fontWeight: '600' }}>마이크</span>
                </div>
                <div style={{ backgroundColor: '#0F172A', borderRadius: '12px', padding: '12px', border: '1px solid rgba(255,255,255,0.05)' }}>
                  <select style={{ width: '100%', backgroundColor: 'transparent', border: 'none', outline: 'none', color: '#F3F4F6', fontSize: '14px', cursor: 'pointer' }}>
                    <option value="mic1" style={{ backgroundColor: '#1E293B' }}>기본 마이크 (Built-in Microphone)</option>
                  </select>
                </div>
                <div style={{ fontSize: '12px', color: '#34D399', marginTop: '6px', marginLeft: '4px' }}>정상적으로 작동중입니다</div>
              </div>

              {/* 스피커 설정 */}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#9CA3AF', marginBottom: '8px' }}>
                  <Volume2 size={16} /> <span style={{ fontSize: '14px', fontWeight: '600' }}>스피커</span>
                </div>
                <div style={{ backgroundColor: '#0F172A', borderRadius: '12px', padding: '12px', border: '1px solid rgba(255,255,255,0.05)' }}>
                  <select style={{ width: '100%', backgroundColor: 'transparent', border: 'none', outline: 'none', color: '#F3F4F6', fontSize: '14px', cursor: 'pointer' }}>
                    <option value="spk1" style={{ backgroundColor: '#1E293B' }}>시스템 기본값 (Built-in Output)</option>
                  </select>
                </div>
                <div style={{ fontSize: '12px', color: '#34D399', marginTop: '6px', marginLeft: '4px' }}>정상적으로 작동중입니다</div>
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
                        <th style={{ padding: '12px 16px', fontWeight: '500' }}>최근 출석시간</th>
                        <th style={{ padding: '12px 16px', fontWeight: '500' }}>최근 공부시간</th>
                        <th style={{ padding: '12px 16px', fontWeight: '500' }}>누적 공부시간</th>
                        <th style={{ padding: '12px 16px', fontWeight: '500' }}></th>
                      </tr>
                    </thead>
                    <tbody>
                      {/* 방장 */}
                      <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.02)' }}>
                        <td style={{ padding: '16px' }}>
                          <div style={{ color: '#3B82F6', fontWeight: '600', fontSize: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <div style={{ width: '24px', height: '24px', borderRadius: '50%', backgroundColor: '#3B82F6', color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '12px' }}>M</div>
                            mindcontrol (나)
                          </div>
                        </td>
                        <td style={{ padding: '16px', color: '#E5E7EB', fontSize: '14px' }}>오늘 09:30</td>
                        <td style={{ padding: '16px', color: '#E5E7EB', fontSize: '14px' }}>1시간 20분</td>
                        <td style={{ padding: '16px', color: '#E5E7EB', fontSize: '14px' }}>32시간 15분</td>
                        <td style={{ padding: '16px', color: '#9CA3AF', fontSize: '13px', fontWeight: '500', textAlign: 'right' }}>방장</td>
                      </tr>
                      {/* 일반 멤버 */}
                      <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.02)' }}>
                        <td style={{ padding: '16px' }}>
                          <div style={{ color: '#F3F4F6', fontWeight: '500', fontSize: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <div style={{ width: '24px', height: '24px', borderRadius: '50%', backgroundColor: '#6366F1', color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '12px' }}>잠</div>
                            잠재용
                          </div>
                        </td>
                        <td style={{ padding: '16px', color: '#E5E7EB', fontSize: '14px' }}>어제 22:10</td>
                        <td style={{ padding: '16px', color: '#E5E7EB', fontSize: '14px' }}>0시간</td>
                        <td style={{ padding: '16px', color: '#E5E7EB', fontSize: '14px' }}>14시간 50분</td>
                        <td style={{ padding: '16px', textAlign: 'right' }}>
                          <button style={{ padding: '6px 12px', backgroundColor: 'rgba(239,68,68,0.1)', color: '#EF4444', borderRadius: '6px', border: '1px solid rgba(239,68,68,0.2)', fontSize: '12px', fontWeight: '600', cursor: 'pointer', transition: '0.2s' }} onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = 'rgba(239,68,68,0.2)'; }} onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'rgba(239,68,68,0.1)'; }}>
                            강제 퇴장
                          </button>
                        </td>
                      </tr>
                      {/* AI 에이전트 */}
                      <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.02)' }}>
                        <td style={{ padding: '16px' }}>
                          <div style={{ color: '#F3F4F6', fontWeight: '500', fontSize: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                            <div style={{ width: '24px', height: '24px', borderRadius: '50%', backgroundColor: '#10B981', color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '12px' }}>S</div>
                            StudyMate
                          </div>
                        </td>
                        <td style={{ padding: '16px', color: '#9CA3AF', fontSize: '14px' }}>-</td>
                        <td style={{ padding: '16px', color: '#9CA3AF', fontSize: '14px' }}>-</td>
                        <td style={{ padding: '16px', color: '#9CA3AF', fontSize: '14px' }}>-</td>
                        <td style={{ padding: '16px', textAlign: 'right' }}>
                          <button style={{ padding: '6px 12px', backgroundColor: 'rgba(239,68,68,0.1)', color: '#EF4444', borderRadius: '6px', border: '1px solid rgba(239,68,68,0.2)', fontSize: '12px', fontWeight: '600', cursor: 'pointer', transition: '0.2s' }} onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = 'rgba(239,68,68,0.2)'; }} onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'rgba(239,68,68,0.1)'; }}>
                            강제 퇴장
                          </button>
                        </td>
                      </tr>
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

                  {Number(study.leaderId) === Number(userId) ? (
                    <div style={{ backgroundColor: 'rgba(59, 130, 246, 0.05)', border: '1px solid rgba(59, 130, 246, 0.1)', borderRadius: '12px', padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                        <div style={{ width: '120px', color: '#E5E7EB', fontWeight: '600', fontSize: '14px' }}>퀴즈 번호 (ID)</div>
                        <input
                          type="number"
                          min="1"
                          value={quizIdInput}
                          onChange={(e) => setQuizIdInput(e.target.value)}
                          placeholder="퀴즈 ID (예: 1)"
                          style={{ width: '120px', backgroundColor: '#1E293B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '10px 16px', color: '#F3F4F6', fontSize: '14px', outline: 'none' }}
                        />
                      </div>
                      <div style={{ display: 'flex', justifyContent: 'flex-start' }}>
                        <button
                          onClick={() => {
                            handleQuizStart(quizIdInput);
                            setShowRoomManageModal(false);
                          }}
                          style={{ padding: '12px 24px', backgroundColor: '#3B82F6', color: 'white', borderRadius: '8px', border: 'none', fontWeight: '700', cursor: 'pointer', transition: '0.2s', boxShadow: '0 4px 12px rgba(59,130,246,0.3)', display: 'flex', alignItems: 'center', gap: '8px' }}
                          onMouseEnter={(e) => e.currentTarget.style.backgroundColor = '#2563EB'}
                          onMouseLeave={(e) => e.currentTarget.style.backgroundColor = '#3B82F6'}
                        >
                          <Play size={16} fill="white" /> 실시간 퀴즈 시작 (방 전체 공유)
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '12px', padding: '40px 0', opacity: 0.8 }}>
                      <AlertTriangle size={36} color="#F59E0B" />
                      <div style={{ color: '#E5E7EB', fontSize: '14px', fontWeight: '600' }}>퀴즈 시작 권한이 없습니다.</div>
                      <div style={{ color: '#9CA3AF', fontSize: '12px' }}>실시간 퀴즈는 스터디 방장(Leader)만 출제할 수 있습니다.</div>
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
                    <select style={{ width: '100%', backgroundColor: '#1E293B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '12px 16px', color: '#F3F4F6', fontSize: '14px', outline: 'none', cursor: 'pointer' }}>
                      <option>이용 문의</option>
                      <option>버그 및 오류 신고</option>
                      <option>기타</option>
                    </select>
                  </div>

                  {/* 제목 */}
                  <div>
                    <div style={{ color: '#E5E7EB', fontWeight: '600', fontSize: '14px', marginBottom: '12px' }}>제목</div>
                    <input type="text" placeholder="문의 제목을 입력하세요." style={{ width: '100%', boxSizing: 'border-box', backgroundColor: '#1E293B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '12px 16px', color: '#F3F4F6', fontSize: '14px', outline: 'none' }} />
                  </div>

                  {/* 내용 */}
                  <div>
                    <div style={{ color: '#E5E7EB', fontWeight: '600', fontSize: '14px', marginBottom: '12px' }}>문의 내용</div>
                    <textarea placeholder="문의하실 내용을 상세히 적어주세요.&#13;&#10;최대한 빠르고 정확하게 답변해 드리겠습니다." style={{ width: '100%', boxSizing: 'border-box', height: '160px', backgroundColor: '#1E293B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '12px 16px', color: '#F3F4F6', fontSize: '14px', outline: 'none', resize: 'none', lineHeight: '1.6' }} />
                  </div>
                </>
              ) : (
                <>
                  {/* 신고 대상 */}
                  <div>
                    <div style={{ color: '#EF4444', fontWeight: '600', fontSize: '14px', marginBottom: '12px' }}>신고할 유저</div>
                    <select style={{ width: '100%', backgroundColor: '#1E293B', border: '1px solid rgba(239,68,68,0.2)', borderRadius: '8px', padding: '12px 16px', color: '#F3F4F6', fontSize: '14px', outline: 'none', cursor: 'pointer' }}>
                      <option value="">신고할 멤버를 선택하세요</option>
                      <option value="user1">잠재용</option>
                      <option value="user2">StudyMate (AI 에이전트)</option>
                    </select>
                  </div>

                  {/* 신고 사유 */}
                  <div>
                    <div style={{ color: '#E5E7EB', fontWeight: '600', fontSize: '14px', marginBottom: '12px' }}>신고 사유</div>
                    <select style={{ width: '100%', backgroundColor: '#1E293B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '12px 16px', color: '#F3F4F6', fontSize: '14px', outline: 'none', cursor: 'pointer' }}>
                      <option>욕설 / 비방 / 혐오 발언</option>
                      <option>도배 및 스팸</option>
                      <option>부적절한 프로필 또는 닉네임</option>
                      <option>기타 (직접 작성)</option>
                    </select>
                  </div>

                  {/* 내용 */}
                  <div>
                    <div style={{ color: '#E5E7EB', fontWeight: '600', fontSize: '14px', marginBottom: '12px' }}>상세 사유</div>
                    <textarea placeholder="신고 사유를 상세히 적어주세요.&#13;&#10;허위 신고 시 서비스 이용에 불이익을 받을 수 있습니다." style={{ width: '100%', boxSizing: 'border-box', height: '160px', backgroundColor: '#1E293B', border: '1px solid rgba(255,255,255,0.1)', borderRadius: '8px', padding: '12px 16px', color: '#F3F4F6', fontSize: '14px', outline: 'none', resize: 'none', lineHeight: '1.6' }} />
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
                onClick={() => setShowAdminReportModal(false)}
              >
                {adminReportTab === 'inquiry' ? '문의 접수하기' : '신고 접수하기'}
              </button>
            </div>
          </div>
        </div>
      )}
      {/* 실시간 퀴즈 진행 모달 */}
      {activeQuiz && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, zIndex: 99999, display: 'flex', alignItems: 'center', justifyContent: 'center', backgroundColor: 'rgba(15, 23, 42, 0.8)', backdropFilter: 'blur(8px)' }}>
          <div style={{ backgroundColor: '#1E293B', borderRadius: '20px', padding: '32px', width: '500px', maxWidth: '90vw', border: '1px solid rgba(255,255,255,0.1)', boxShadow: '0 25px 50px -12px rgba(0,0,0,0.5)', display: 'flex', flexDirection: 'column', gap: '24px', animation: 'slideUp 0.3s ease-out' }}>
            
            {/* Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <span style={{ color: '#3B82F6', fontSize: '12px', fontWeight: '800', textTransform: 'uppercase', letterSpacing: '1px' }}>AI Live Quiz</span>
                <h2 style={{ margin: 0, fontSize: '18px', fontWeight: '700', color: '#F3F4F6' }}>{activeQuiz.quizTitle}</h2>
              </div>
              {quizScoreboard && (
                <div
                  onClick={() => {
                    setActiveQuiz(null);
                    setQuizScoreboard(null);
                  }}
                  style={{ width: '32px', height: '32px', borderRadius: '50%', backgroundColor: 'rgba(255,255,255,0.05)', display: 'flex', alignItems: 'center', justifyContent: 'center', cursor: 'pointer' }}
                >
                  <X size={16} color="#9CA3AF" />
                </div>
              )}
            </div>

            {/* Progress & Timer */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '13px', color: '#9CA3AF', fontWeight: '600' }}>
                <span>문제 {activeQuiz.currentIndex + 1} / {activeQuiz.totalQuestions}</span>
                <span style={{ color: quizTimer <= 5 ? '#EF4444' : '#10B981' }}>남은 시간: {quizTimer}초</span>
              </div>
              <div style={{ height: '6px', backgroundColor: 'rgba(255,255,255,0.05)', borderRadius: '3px', overflow: 'hidden' }}>
                <div style={{ width: `${(quizTimer / (activeQuiz.timeLimitSeconds || 30)) * 100}%`, height: '100%', backgroundColor: quizTimer <= 5 ? '#EF4444' : '#10B981', borderRadius: '3px', transition: 'width 1s linear' }} />
              </div>
            </div>

            {/* Question Text */}
            <div style={{ backgroundColor: '#0F172A', borderRadius: '12px', padding: '20px', border: '1px solid rgba(255,255,255,0.03)' }}>
              <p style={{ margin: 0, fontSize: '15px', color: '#E5E7EB', fontWeight: '600', lineHeight: '1.6', wordBreak: 'keep-all' }}>
                {activeQuiz.questionText}
              </p>
            </div>

            {/* Options */}
            {!quizScoreboard && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {activeQuiz.options.map((option, idx) => {
                  const isSelected = quizSelectedAnswer === idx;
                  return (
                    <button
                      key={idx}
                      disabled={quizHasSubmitted}
                      onClick={() => handleQuizSubmit(idx)}
                      style={{
                        width: '100%',
                        textAlign: 'left',
                        padding: '14px 20px',
                        borderRadius: '12px',
                        border: isSelected ? '2px solid #3B82F6' : '1px solid rgba(255,255,255,0.08)',
                        backgroundColor: isSelected ? 'rgba(59, 130, 246, 0.15)' : 'rgba(255,255,255,0.02)',
                        color: isSelected ? '#60A5FA' : '#D1D5DB',
                        fontSize: '14px',
                        fontWeight: isSelected ? '700' : '500',
                        cursor: quizHasSubmitted ? 'not-allowed' : 'pointer',
                        transition: 'all 0.2s',
                        outline: 'none'
                      }}
                    >
                      <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                        <div style={{ width: '24px', height: '24px', borderRadius: '50%', backgroundColor: isSelected ? '#3B82F6' : 'rgba(255,255,255,0.1)', color: isSelected ? 'white' : '#9CA3AF', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '12px', fontWeight: '700' }}>
                          {idx + 1}
                        </div>
                        <span style={{ flex: 1 }}>{option}</span>
                      </div>
                    </button>
                  );
                })}
              </div>
            )}

            {/* Submitting Message */}
            {quizHasSubmitted && !quizScoreboard && (
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '10px', color: '#9CA3AF', fontSize: '13px', padding: '10px 0' }}>
                <RefreshCw size={16} className="animate-spin" />
                <span>다른 멤버들이 제출할 때까지 대기 중...</span>
              </div>
            )}

            {/* Live Scoreboard */}
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

                {/* Next Button or Final Close */}
                {activeQuiz.currentIndex + 1 === activeQuiz.totalQuestions ? (
                  <button
                    onClick={() => {
                      setActiveQuiz(null);
                      setQuizScoreboard(null);
                    }}
                    style={{ padding: '12px', backgroundColor: '#EF4444', color: 'white', borderRadius: '8px', border: 'none', fontWeight: '700', cursor: 'pointer', transition: '0.2s', width: '100%' }}
                  >
                    퀴즈 종료
                  </button>
                ) : (
                  <div style={{ textAlign: 'center', color: '#9CA3AF', fontSize: '12px' }}>
                    방장이 다음 문제를 전송할 때까지 대기하고 있습니다...
                  </div>
                )}
              </div>
            )}

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
