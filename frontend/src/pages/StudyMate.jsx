import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { roomService } from '../services/api';
import { Bot, Plus, Trash2, Send, AlertCircle, X, Sparkles, Users, ChevronRight, CheckCircle, Info } from 'lucide-react';

const PREDEFINED_PROFILES = [
  { id: 'theme1', name: '블루 톤', bgColor: '#EFF6FF', color: '#3B82F6' },
  { id: 'theme2', name: '레드 톤', bgColor: '#FEF2F2', color: '#EF4444' },
  { id: 'theme3', name: '그린 톤', bgColor: '#ECFDF5', color: '#10B981' },
  { id: 'theme4', name: '퍼플 톤', bgColor: '#F5F3FF', color: '#8B5CF6' },
  { id: 'theme5', name: '옐로우 톤', bgColor: '#FEFCE8', color: '#EAB308' },
];

const PERSONALITY_OPTIONS = ['친절한 설명형', '비판적 분석형', '논리적 탐구형', '창의적 확장형', '간결한 요약형', '직접 입력'];
const KNOWLEDGE_OPTIONS = ['입문 수준', '학사 수준', '석사 수준', '박사 수준', '전문가 수준'];

export default function StudyMate() {
  const { userId } = useAuth();
  const navigate = useNavigate();
  const MAX_ROOMS = 3;

  const [rooms, setRooms] = useState([]);
  const [selectedRoom, setSelectedRoom] = useState(null);
  const [chatHistory, setChatHistory] = useState([]);
  const [message, setMessage] = useState('');
  const [typingStatus, setTypingStatus] = useState({}); // { [roomId]: boolean }
  const [showModal, setShowModal] = useState(false);
  const [currentAgentIndex, setCurrentAgentIndex] = useState(0);
  const [deleteModal, setDeleteModal] = useState({ show: false, roomId: null });
  const [roomDetailModal, setRoomDetailModal] = useState(null); // room object

  const isLimitReached = rooms.length >= MAX_ROOMS;

  const [newRoomName, setNewRoomName] = useState('');
  const [configuredAgents, setConfiguredAgents] = useState([]);
  const [currentAgent, setCurrentAgent] = useState({
    profileId: 'theme1',
    name: '',
    personality: '친절한 설명형',
    customPersonality: '',
    knowledge: '입문 수준'
  });

  const chatEndRef = useRef(null);
  const selectedRoomRef = useRef(null);

  // 현재 선택된 방을 ref에 동기화 (비동기 콜백에서 최신값 참조용)
  useEffect(() => {
    selectedRoomRef.current = selectedRoom;
  }, [selectedRoom]);

  useEffect(() => {
    if (userId) {
      loadRooms();
    } else {
      setRooms([]);
      setSelectedRoom(null);
      setChatHistory([]);
    }
  }, [userId]);

  const checkAuth = (e) => {
    if (!userId) {
      if (e) e.preventDefault();
      alert('로그인이 필요한 기능입니다. 로그인 페이지로 이동합니다.');
      navigate('/login');
      return false;
    }
    return true;
  };

  const getRoomId = (room) => room?.agentRoomId ?? room?.roomId ?? room?.id;

  useEffect(() => {
    scrollToBottom();
  }, [chatHistory, typingStatus, selectedRoom]);

  const loadRooms = async () => {
    try {
      const data = await roomService.getRooms(userId);
      setRooms(data || []);
    } catch (err) {
      console.error('채팅방 목록 조회 실패:', err);
    }
  };

  const handleDeleteRoom = async () => {
    if (!deleteModal.roomId) return;
    try {
      await roomService.deleteRoom(userId, deleteModal.roomId);
      setDeleteModal({ show: false, roomId: null });
      if (getRoomId(selectedRoom) === deleteModal.roomId) {
        setSelectedRoom(null);
        setChatHistory([]);
      }
      loadRooms();
    } catch (err) {
      alert('채팅방 삭제에 실패했습니다.');
    }
  };

  const handleAddAgent = () => {
    if (!currentAgent.name.trim()) return alert('에이전트 이름을 입력해주세요.');
    if (currentAgent.personality === '직접 입력' && !currentAgent.customPersonality.trim()) {
      return alert('성격을 직접 입력해주세요.');
    }
    if (configuredAgents.length >= 3) return alert('최대 3명까지만 추가할 수 있습니다.');
    
    setConfiguredAgents(prev => [...prev, currentAgent]);
    setCurrentAgent({
      profileId: 'theme1',
      name: '',
      personality: '친절한 설명형',
      customPersonality: '',
      knowledge: '입문 수준'
    });
  };

  const removeAgent = (idx) => {
    setConfiguredAgents(prev => prev.filter((_, i) => i !== idx));
  };

  const handleCreateRoom = async (e) => {
    if (e) e.preventDefault();

    if (!newRoomName.trim()) return alert('채팅방 이름을 입력해주세요.');
    if (configuredAgents.length === 0) return alert('최소 1명의 AI 메이트를 추가해주세요.');

    try {
      const selectedAgents = configuredAgents.map(agent => ({
        name: agent.name.trim(),
        role: agent.knowledge,
        persona: agent.personality === '직접 입력' ? agent.customPersonality : agent.personality,
        tone: agent.personality === '직접 입력' ? agent.customPersonality : agent.personality,
        goal: agent.profileId // Store profileId in goal
      }));

      const payload = {
        roomName: newRoomName.trim(),
        agents: selectedAgents
      };
      console.log('채팅방 생성 요청 페이로드:', JSON.stringify(payload, null, 2));
      await roomService.createRoom(userId, payload);
      setShowModal(false);
      setNewRoomName('');
      setConfiguredAgents([]);
      loadRooms();
    } catch (err) {
      alert(err.message || '채팅방 생성에 실패했습니다.');
    }
  };

  const selectRoom = async (room) => {
    const roomId = getRoomId(room);
    if (!roomId) {
      console.error("roomId 없음:", room);
      return;
    }

    setSelectedRoom({ ...room, roomId });
    try {
      const history = await roomService.getChatHistory(userId, roomId);
      setChatHistory(history || []);
    } catch (err) {
      console.error('채팅 내역 조회 실패:', err);
      setChatHistory([]);
    }
  };

  const sendMessage = async (e) => {
    e.preventDefault();
    if (!checkAuth()) return;
    
    const roomId = getRoomId(selectedRoom);
    if (!message.trim() || !roomId || typingStatus[roomId]) return;

    const userMsg = {
      id: Date.now(),
      messageId: Date.now(),
      content: message,
      sender: 'USER',
      createdAt: new Date().toISOString()
    };

    setChatHistory(prev => [...prev, userMsg]);
    const inputMsg = message;
    setMessage('');
    
    // 해당 방의 타이핑 상태 활성화
    setTypingStatus(prev => ({ ...prev, [roomId]: true }));

    try {
      const res = await roomService.sendMessage(userId, roomId, inputMsg);
      
      // [정합성 검사] 응답이 왔을 때 사용자가 여전히 같은 방에 있는지 확인
      if (getRoomId(selectedRoomRef.current) !== roomId) {
        console.log(`방 이동 감지: ${roomId} 응답을 무시합니다.`);
        return;
      }

      if (res && res.replies) {
        const newMessages = res.replies.map((reply, idx) => ({
          id: Date.now() + idx + 1,
          content: reply.answer,
          sender: 'AI',
          senderName: selectedRoom.agents?.find(a => a.id === reply.agentId)?.name || '에이전트',
          createdAt: new Date().toISOString()
        }));
        setChatHistory(prev => [...prev, ...newMessages]);
      } else {
        const aiMsg = {
          id: Date.now() + 1,
          content: res.answer || '응답이 없습니다.',
          sender: 'AI',
          createdAt: new Date().toISOString()
        };
        setChatHistory(prev => [...prev, aiMsg]);
      }
    } catch (err) {
      // 에러 시에도 현재 방이면 복구 로직 실행
      if (getRoomId(selectedRoomRef.current) === roomId) {
        alert('메시지 전송에 실패했습니다.');
        setChatHistory(prev => prev.filter(m => m.id !== userMsg.id));
        setMessage(inputMsg);
      }
    } finally {
      // 해당 방의 타이핑 상태 해제
      setTypingStatus(prev => ({ ...prev, [roomId]: false }));
    }
  };

  const scrollToBottom = () => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  const formatTime = (isoString) => {
    if (!isoString) return '';
    const d = new Date(isoString);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  const getAvatarColor = (index) => {
    const colors = [
      { bg: '#E8F5E9', text: '#2E7D32' },
      { bg: '#E3F2FD', text: '#1565C0' },
      { bg: '#FFF3E0', text: '#E65100' },
    ];
    return colors[index % colors.length];
  };

  const isCurrentRoomTyping = typingStatus[getRoomId(selectedRoom)];

  return (
    <div className="container-main studymate-page">
      <div className="layout-split">
        {/* 좌측: 채팅방 리스트 패널 */}
        <div className="glass-panel layout-pane-left animate-fade-in">
          <div className="room-list-header">
            <h2 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '8px', fontSize: '18px' }}>
              <Users size={20} color="var(--color-primary)" /> 내 채팅방
              <span className={`limit-badge ${isLimitReached ? 'reached' : ''}`}>
                {rooms.length} / {MAX_ROOMS}
              </span>
            </h2>
            <button
              className={`btn-outline btn-create-room ${isLimitReached ? 'disabled' : ''}`}
              style={{ width: 'auto', height: '28px', padding: '0 10px', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px', transition: 'all 0.2s ease' }}
              onClick={() => checkAuth() && setShowModal(true)}
              disabled={isLimitReached}
              title={isLimitReached ? "채팅방은 최대 3개까지 생성 가능합니다." : ""}
            >
              <Plus size={16} /> 방 만들기
            </button>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', overflowY: 'auto', paddingRight: '4px' }}>
            {rooms.length === 0 ? (
              <div className="empty-state" style={{ padding: '40px 0' }}>
                <p>생성된 채팅방이 없습니다.</p>
                <p style={{ fontSize: '12px' }}>나만의 스터디 그룹을 만들어보세요!</p>
              </div>
            ) : (
              rooms.map((room, index) => {
                const rId = getRoomId(room);
                const isActive = getRoomId(selectedRoom) === rId;
                const avatarColor = getAvatarColor(index);

                return (
                  <div
                    key={rId || index}
                    className={`room-card ${isActive ? 'active' : ''}`}
                    onClick={() => selectRoom(room)}
                  >
                    <div className="avatar" style={{ backgroundColor: avatarColor.bg, color: avatarColor.text }}>
                      <Users size={20} />
                    </div>

                    <div style={{ flex: 1, overflow: 'hidden' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                        <div style={{ fontWeight: 'bold', fontSize: '15px', color: 'var(--color-text-main)', marginBottom: '4px' }}>{room.roomName || `채팅방 ${index + 1}`}</div>
                      </div>
                      <div style={{ fontSize: '12px', color: 'var(--color-text-muted)', lineHeight: '1.4' }}>
                        {room.agents?.map(a => a.name).join(', ')} ({room.agents?.length || 0}명)
                      </div>
                    </div>

                    <div className="room-actions" style={{ display: 'flex', gap: '4px' }}>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setRoomDetailModal(room);
                        }}
                        title="상세 보기"
                        style={{ background: 'none', border: 'none', color: 'var(--color-primary)', cursor: 'pointer', padding: '4px' }}
                      >
                        <Info size={16} />
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setDeleteModal({ show: true, roomId: rId });
                        }}
                        title="삭제"
                        style={{ background: 'none', border: 'none', color: '#EF4444', cursor: 'pointer', padding: '4px' }}
                      >
                        <Trash2 size={16} />
                      </button>
                    </div>
                  </div>
                )
              })
            )}
          </div>
        </div>

        {/* 우측: 채팅 영역 */}
        <div className="glass-panel layout-pane-right animate-fade-in">
          {!selectedRoom ? (
            <div className="empty-state">
              <Bot size={50} color="#E5E7EB" style={{ marginBottom: '16px' }} />
              <h3 style={{ margin: '0 0 8px 0', color: 'var(--color-text-main)' }}>AI 학습메이트</h3>
              <p style={{ margin: 0, color: 'var(--color-text-muted)', fontSize: '14px' }}>
                좌측에서 대화할 채팅방을 선택하거나 새로 생성해주세요.
              </p>
            </div>
          ) : (
            <div className="chat-container">
              <div className="chat-header">
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <div className="avatar-sm" style={{ backgroundColor: 'var(--color-primary)', color: 'white' }}>
                    <Users size={16} />
                  </div>
                  <div>
                    <div style={{ fontWeight: 'bold', fontSize: '15px' }}>{selectedRoom.roomName || '채팅방'}</div>
                    <div style={{ fontSize: '12px', color: 'var(--color-text-muted)' }}>에이전트: {selectedRoom.agents?.map(a => a.name).join(', ')}</div>
                  </div>
                </div>
              </div>

              <div className="chat-history">
                {chatHistory.length === 0 ? (
                  <div className="empty-state" style={{ marginTop: '40px' }}>
                    <p>대화 내역이 없습니다. 인사를 건네보세요!</p>
                  </div>
                ) : (
                  chatHistory.map((msg, idx) => {
                    const isUser = msg.sender === 'USER';
                    const msgKey = msg.messageId ?? msg.id ?? idx;
                    
                    // agent 정보 파악해서 색상 입히기
                    let msgBgColor = isUser ? 'var(--color-primary)' : 'white';
                    let msgTextColor = isUser ? 'white' : 'var(--color-text-main)';
                    let msgBorderColor = isUser ? 'none' : '1px solid var(--color-border)';
                    let agentName = !isUser ? (msg.senderName || msg.sender) : null;
                    let prof = null;

                    if (!isUser) {
                      const agentDef = selectedRoom.agents?.find(a => a.name === agentName);
                      if (agentDef && agentDef.goal) {
                        prof = PREDEFINED_PROFILES.find(p => p.id === agentDef.goal);
                        if (prof) {
                          msgBgColor = prof.bgColor;
                          msgTextColor = '#111827';
                          msgBorderColor = `1px solid ${prof.color}40`;
                        }
                      }
                    }

                    return (
                      <div key={msgKey} className={`chat-bubble-container ${isUser ? 'user' : 'ai'}`}>
                        {!isUser && (
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '4px', alignSelf: 'flex-start' }}>
                            <div style={{ width: '28px', height: '28px', borderRadius: '50%', backgroundColor: prof ? prof.bgColor : 'white', display: 'flex', alignItems: 'center', justifyContent: 'center', border: `1px solid ${prof ? prof.color + '40' : 'var(--color-border)'}`, color: prof ? prof.color : 'var(--color-text-muted)' }}>
                              <Bot size={16} />
                            </div>
                            <span style={{ fontSize: '12px', fontWeight: 'bold', color: 'var(--color-text-muted)' }}>{agentName}</span>
                          </div>
                        )}
                        <div className={`chat-bubble ${isUser ? 'user' : 'ai'}`} style={{ backgroundColor: msgBgColor, color: msgTextColor, border: msgBorderColor }}>
                          {msg.content}
                        </div>
                        <div className="chat-bubble-time">
                          {formatTime(msg.createdAt)}
                        </div>
                      </div>
                    );
                  })
                )}
                {isCurrentRoomTyping && (
                  <div className="chat-bubble-container ai">
                    <div className="chat-bubble ai" style={{ padding: '12px 16px', display: 'flex', alignItems: 'center', minHeight: '20px' }}>
                      <span className="dot"></span><span className="dot"></span><span className="dot"></span>
                    </div>
                  </div>
                )}
                <div ref={chatEndRef} />
              </div>

              <form onSubmit={sendMessage} className="chat-input-wrapper">
                <input
                  type="text"
                  className="input-field"
                  style={{ flex: 1, borderRadius: '24px', paddingLeft: '20px', backgroundColor: '#F3F4F6', border: 'none' }}
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  onFocus={checkAuth}
                  placeholder="메시지 보내기..."
                  disabled={isCurrentRoomTyping}
                />
                <button type="submit" className="btn-primary" style={{ width: '42px', height: '42px', borderRadius: '50%', padding: 0, flexShrink: 0, display: 'flex', justifyContent: 'center', alignItems: 'center' }} disabled={isCurrentRoomTyping || !message.trim()}>
                  <Send size={18} />
                </button>
              </form>
            </div>
          )}
        </div>
      </div>

      {/* 커스텀 AI 에이전트 생성 모달 */}
      {showModal && (
        <div className="modal-overlay" style={{ zIndex: 1000 }}>
          <div className="glass-panel modal-content animate-fade-in" style={{ width: '92vw', maxWidth: '800px', maxHeight: '85vh', padding: 0 }}>
            <div className="modal-header" style={{ padding: '24px 32px 20px' }}>
              <div>
                <h3 style={{ margin: '0 0 4px 0', fontSize: '20px' }}>나만의 AI 학습메이트 방 만들기</h3>
                <p style={{ margin: 0, color: 'var(--color-text-muted)', fontSize: '13px' }}>나만의 AI 에이전트를 직접 설정해 방에 추가하세요.</p>
              </div>
              <button className="btn-close" onClick={() => { setShowModal(false); setConfiguredAgents([]); setNewRoomName(''); }}><X size={20} /></button>
            </div>

            <div className="modal-body" style={{ padding: '0 32px 20px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
              <div>
                <label style={{ display: 'block', marginBottom: '8px', fontWeight: 'bold', fontSize: '14px', color: 'var(--color-text-main)' }}>방 이름</label>
                <input
                  type="text"
                  className="input-field"
                  placeholder="예: 토익 스피킹 연습방, 알고리즘 박살내기"
                  value={newRoomName}
                  onChange={(e) => setNewRoomName(e.target.value)}
                  style={{ width: '100%', padding: '14px 16px', borderRadius: '12px' }}
                />
              </div>

              {/* 에이전트 생성 폼 */}
              <div style={{ backgroundColor: '#F9FAFB', borderRadius: '16px', padding: '24px', border: '1px solid var(--color-border)' }}>
                <h4 style={{ margin: '0 0 16px', fontSize: '15px' }}>새 에이전트 조립하기</h4>
                
                {/* 테마 선택 */}
                <div style={{ marginBottom: '20px' }}>
                  <label style={{ display: 'block', marginBottom: '10px', fontSize: '13px', fontWeight: 'bold', color: 'var(--color-text-muted)' }}>테마 색상</label>
                  <div style={{ display: 'flex', gap: '12px', overflowX: 'auto', padding: '6px 4px 12px 4px' }}>
                    {PREDEFINED_PROFILES.map(prof => (
                      <button
                        key={prof.id}
                        onClick={() => setCurrentAgent({...currentAgent, profileId: prof.id})}
                        style={{
                          width: '72px', flexShrink: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px',
                          border: 'none', background: 'none', cursor: 'pointer', opacity: currentAgent.profileId === prof.id ? 1 : 0.6,
                          transform: currentAgent.profileId === prof.id ? 'translateY(-2px)' : 'none', transition: 'all 0.2s ease',
                          padding: 0, outline: 'none'
                        }}
                      >
                        <div style={{ 
                          width: '56px', height: '56px', borderRadius: '50%', backgroundColor: prof.bgColor, 
                          display: 'flex', alignItems: 'center', justifyContent: 'center', 
                          boxShadow: currentAgent.profileId === prof.id ? `0 0 0 2px white, 0 0 0 4px ${prof.color}, 0 4px 10px rgba(0,0,0,0.1)` : '0 2px 6px rgba(0,0,0,0.05)'
                        }}>
                          <Bot size={28} color={prof.color} />
                        </div>
                        <span style={{ fontSize: '11px', fontWeight: currentAgent.profileId === prof.id ? '700' : '500', color: currentAgent.profileId === prof.id ? prof.color : 'var(--color-text-muted)' }}>{prof.name}</span>
                      </button>
                    ))}
                  </div>
                </div>

                {/* 이름 입력 */}
                <div style={{ marginBottom: '20px' }}>
                  <label style={{ display: 'block', marginBottom: '8px', fontSize: '13px', fontWeight: 'bold', color: 'var(--color-text-muted)' }}>에이전트 이름</label>
                  <input
                    type="text"
                    className="input-field"
                    placeholder="에이전트 이름을 지어주세요"
                    value={currentAgent.name}
                    onChange={(e) => setCurrentAgent({...currentAgent, name: e.target.value})}
                    style={{ width: '100%', padding: '12px 16px', borderRadius: '8px', backgroundColor: 'white' }}
                  />
                </div>

                {/* 성격 선택 */}
                <div style={{ marginBottom: '20px' }}>
                  <label style={{ display: 'block', marginBottom: '8px', fontSize: '13px', fontWeight: 'bold', color: 'var(--color-text-muted)' }}>성격</label>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                    {PERSONALITY_OPTIONS.map(opt => (
                      <button
                        key={opt}
                        onClick={() => setCurrentAgent({...currentAgent, personality: opt})}
                        style={{
                          padding: '8px 14px', borderRadius: '20px', fontSize: '13px', transition: 'all 0.2s',
                          border: `1px solid ${currentAgent.personality === opt ? 'var(--color-primary)' : 'var(--color-border)'}`,
                          backgroundColor: currentAgent.personality === opt ? 'var(--color-primary)' : 'white',
                          color: currentAgent.personality === opt ? 'white' : 'var(--color-text-main)',
                          fontWeight: currentAgent.personality === opt ? 'bold' : 'normal'
                        }}
                      >
                        {opt}
                      </button>
                    ))}
                  </div>
                  {currentAgent.personality === '직접 입력' && (
                    <input
                      type="text"
                      className="input-field"
                      placeholder="원하는 성격을 자세히 입력해주세요"
                      value={currentAgent.customPersonality}
                      onChange={(e) => setCurrentAgent({...currentAgent, customPersonality: e.target.value})}
                      style={{ width: '100%', padding: '10px 14px', borderRadius: '8px', backgroundColor: 'white', marginTop: '10px', fontSize: '13px' }}
                    />
                  )}
                </div>

                {/* 지식수준 선택 */}
                <div style={{ marginBottom: '24px' }}>
                  <label style={{ display: 'block', marginBottom: '8px', fontSize: '13px', fontWeight: 'bold', color: 'var(--color-text-muted)' }}>지식수준</label>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                    {KNOWLEDGE_OPTIONS.map(opt => (
                      <button
                        key={opt}
                        onClick={() => setCurrentAgent({...currentAgent, knowledge: opt})}
                        style={{
                          padding: '8px 14px', borderRadius: '20px', fontSize: '13px', transition: 'all 0.2s',
                          border: `1px solid ${currentAgent.knowledge === opt ? 'var(--color-primary)' : 'var(--color-border)'}`,
                          backgroundColor: currentAgent.knowledge === opt ? 'var(--color-primary)' : 'white',
                          color: currentAgent.knowledge === opt ? 'white' : 'var(--color-text-main)',
                          fontWeight: currentAgent.knowledge === opt ? 'bold' : 'normal'
                        }}
                      >
                        {opt}
                      </button>
                    ))}
                  </div>
                </div>

                <button onClick={handleAddAgent} className="btn-outline" style={{ width: '100%', padding: '12px', borderRadius: '10px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', fontWeight: 'bold' }}>
                  <Plus size={16} /> 이 에이전트 추가하기 ({configuredAgents.length}/3)
                </button>
              </div>

              {/* 추가된 에이전트 목록 */}
              {configuredAgents.length > 0 && (
                <div>
                  <h4 style={{ margin: '0 0 12px', fontSize: '14px', color: 'var(--color-text-main)' }}>추가된 에이전트</h4>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                    {configuredAgents.map((ag, idx) => {
                      const prof = PREDEFINED_PROFILES.find(p => p.id === ag.profileId);
                      return (
                        <div key={idx} style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '12px 16px', backgroundColor: prof?.bgColor || '#f9f9f9', borderRadius: '12px', border: `1px solid ${prof?.color || '#ddd'}40` }}>
                          <div style={{ width: '40px', height: '40px', borderRadius: '50%', backgroundColor: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center', color: prof?.color || 'var(--color-primary)' }}>
                            <Bot size={20} />
                          </div>
                          <div style={{ flex: 1 }}>
                            <div style={{ fontWeight: 'bold', fontSize: '14px', color: prof?.color || 'black', marginBottom: '2px' }}>{ag.name}</div>
                            <div style={{ fontSize: '12px', color: 'var(--color-text-muted)' }}>{ag.personality === '직접 입력' ? ag.customPersonality : ag.personality} • {ag.knowledge}</div>
                          </div>
                          <button onClick={() => removeAgent(idx)} style={{ border: 'none', background: 'none', cursor: 'pointer', color: '#EF4444', padding: '4px' }}>
                            <X size={16} />
                          </button>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>

            <div className="modal-footer" style={{ padding: '20px 32px' }}>
              <button className="btn-primary" style={{ width: '100%', height: '48px', fontSize: '16px' }} onClick={handleCreateRoom}>채팅방 생성하기</button>
            </div>
          </div>
        </div>
      )}

      {/* 채팅방 상세 보기 모달 */}
      {roomDetailModal && (
        <div className="modal-overlay" style={{ zIndex: 1000 }}>
          <div className="glass-panel modal-content animate-fade-in" style={{ width: '540px', maxWidth: '95vw' }}>
            <div className="modal-header">
              <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Info size={20} color="var(--color-primary)" />
                채팅방 상세 정보
              </h3>
              <button className="btn-close" onClick={() => setRoomDetailModal(null)}><X size={20} /></button>
            </div>

            <div className="modal-body" style={{ padding: '24px 32px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
              {/* 방 기본 정보 */}
              <div style={{ backgroundColor: '#F9FAFB', borderRadius: '12px', padding: '20px', border: '1px solid var(--color-border)' }}>
                <div style={{ fontSize: '12px', fontWeight: 'bold', color: 'var(--color-text-muted)', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>채팅방</div>
                <div style={{ fontSize: '20px', fontWeight: 'bold', color: 'var(--color-text-main)' }}>{roomDetailModal.roomName || '이름 없음'}</div>
                <div style={{ fontSize: '13px', color: 'var(--color-text-muted)', marginTop: '6px' }}>
                  에이전트 {roomDetailModal.agents?.length || 0}명 참여 중
                </div>
              </div>

              {/* 에이전트 목록 */}
              <div>
                <div style={{ fontSize: '14px', fontWeight: 'bold', color: 'var(--color-text-main)', marginBottom: '14px' }}>AI 메이트 구성</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                  {(roomDetailModal.agents || []).map((agent, idx) => {
                    // Try to extract profileId from goal, fallback to 'theme1'
                    const profileId = agent.goal || 'theme1';
                    const prof = PREDEFINED_PROFILES.find(p => p.id === profileId);
                    const accentColor = prof?.color || 'var(--color-primary)';
                    const bgColor = prof?.bgColor || '#F0F9FF';
                    return (
                      <div key={idx} style={{ border: `1.5px solid ${accentColor}33`, borderRadius: '12px', padding: '16px', backgroundColor: bgColor, display: 'flex', gap: '14px', alignItems: 'flex-start' }}>
                        <div style={{ width: '48px', height: '48px', borderRadius: '50%', backgroundColor: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0, boxShadow: '0 2px 8px rgba(0,0,0,0.08)', color: accentColor }}>
                          <Bot size={24} />
                        </div>
                        <div style={{ flex: 1 }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
                            <span style={{ fontWeight: 'bold', fontSize: '15px', color: accentColor }}>{agent.name || '-'}</span>
                            <span style={{ fontSize: '11px', fontWeight: 'bold', padding: '2px 8px', borderRadius: '20px', backgroundColor: `${accentColor}22`, color: accentColor }}>{agent.role || '-'}</span>
                          </div>
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                            <div style={{ fontSize: '12px', color: 'var(--color-text-muted)' }}>
                              <span style={{ fontWeight: 'bold' }}>성향: </span>{agent.persona || '-'}
                            </div>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>

            <div className="modal-footer" style={{ padding: '20px 32px' }}>
              <button
                className="btn-primary"
                style={{ width: '100%', height: '44px' }}
                onClick={() => { setRoomDetailModal(null); selectRoom(roomDetailModal); }}
              >
                이 채팅방 입장하기
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 삭제 확인 모달 */}
      {deleteModal.show && (
        <div className="modal-overlay">
          <div className="glass-panel modal-content" style={{ maxWidth: '400px' }}>
            <div style={{ textAlign: 'center', padding: '20px 0' }}>
              <Trash2 size={48} color="#EF4444" style={{ marginBottom: '16px' }} />
              <h3 style={{ marginBottom: '12px' }}>정말 삭제하시겠습니까?</h3>
              <p style={{ color: 'var(--color-text-muted)', fontSize: '14px', lineHeight: '1.5' }}>
                채팅방을 삭제하면 해당 채팅방의<br />
                <strong>에이전트 설정 및 모든 대화 내역</strong>이<br />
                함께 삭제되며 복구할 수 없습니다.
              </p>
            </div>
            <div style={{ display: 'flex', gap: '12px', marginTop: '24px' }}>
              <button className="btn-outline" onClick={() => setDeleteModal({ show: false, roomId: null })} style={{ flex: 1 }}>취소</button>
              <button className="btn-primary" onClick={handleDeleteRoom} style={{ flex: 1, backgroundColor: '#EF4444' }}>삭제하기</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
