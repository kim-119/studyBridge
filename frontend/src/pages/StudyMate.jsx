import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { roomService } from '../services/api';
import { Bot, Plus, Trash2, Send, AlertCircle, X, Sparkles, Users, ChevronRight, Check } from 'lucide-react';

const AI_PERSONAS = [
  {
    id: 'bomi',
    name: '봄이',
    role: '열정 응원단장',
    description: '"넌 할 수 있어! 오늘도 최고야!" 항상 포근하게 응원해주는 관심집중 꽃같은 아이',
    color: '#EC4899', // Pink
    bgLight: '#FDF2F8'
  },
  {
    id: 'byeol',
    name: '별이',
    role: '공감 요정',
    description: '"힘들었지? 괜찮아, 내가 있잖아" 공감과 위로로 마음을 치유해주는 아이',
    color: '#8B5CF6', // Purple
    bgLight: '#F5F3FF'
  },
  {
    id: 'energizer',
    name: '에너자이저',
    role: '자극 응원단',
    description: '"파이팅! 파이팅! 우리 같이하면 무한 긍정 에너지로 이끌어주는 친구"',
    color: '#F97316', // Orange
    bgLight: '#FFF7ED'
  },
  {
    id: 'fighter',
    name: '열정 파이터',
    role: '동기부여 친구',
    description: '"포기는 없어! 끝까지 해보자" 불타는 열정으로 함께 달려가는 친구',
    color: '#EF4444', // Red
    bgLight: '#FEF2F2'
  },
  {
    id: 'brain',
    name: '두뇌풀가동',
    role: '논리형 분석가',
    description: '"이 문제의 핵심은 단계별로 보면..." 논리적으로 도와주는 나야나 친구',
    color: '#3B82F6', // Blue
    bgLight: '#EFF6FF'
  }
];

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

  const isLimitReached = rooms.length >= MAX_ROOMS;

  const [newRoom, setNewRoom] = useState({
    roomName: '',
    agents: []
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

  const toggleAgentSelection = (persona) => {
    setNewRoom(prev => {
      const isSelected = prev.agents.some(a => a.id === persona.id);
      if (isSelected) {
        return { ...prev, agents: prev.agents.filter(a => a.id !== persona.id) };
      } else {
        if (prev.agents.length >= 3) {
          alert('최대 3명까지만 선택할 수 있습니다.');
          return prev;
        }
        return { ...prev, agents: [...prev.agents, persona] };
      }
    });
  };

  const handleCreateRoom = async (e) => {
    if (e) e.preventDefault();

    if (!newRoom.roomName.trim()) return alert('채팅방 이름을 입력해주세요.');
    if (newRoom.agents.length === 0) return alert('최소 1명 이상의 AI 페르소나를 선택해주세요.');

    try {
      const payload = {
        roomName: newRoom.roomName,
        agents: newRoom.agents.map(p => ({
          name: p.name,
          role: p.role,
          persona: p.description,
          tone: '친절한',
          goal: ''
        }))
      };
      console.log('채팅방 생성 요청 페이로드:', JSON.stringify(payload, null, 2));
      await roomService.createRoom(userId, payload);
      setShowModal(false);
      setNewRoom({
        roomName: '',
        agents: []
      });
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

                    <div className="room-actions">
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          setDeleteModal({ show: true, roomId: rId });
                        }}
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
                    return (
                      <div key={msgKey} className={`chat-bubble-container ${isUser ? 'user' : 'ai'}`}>
                        <div className="chat-bubble-sender">
                          {!isUser && (msg.senderName || msg.sender)}
                        </div>
                        <div className={`chat-bubble ${isUser ? 'user' : 'ai'}`}>
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

      {/* 채팅방 생성 모달 */}
      {showModal && (
        <div className="modal-overlay">
          <div className="glass-panel modal-content" style={{ maxWidth: '800px', width: '100%' }}>
            <div className="modal-header" style={{ marginBottom: '16px' }}>
              <h3 style={{ margin: 0, fontSize: '20px' }}>새로운 학습메이트 방 만들기</h3>
              <button className="btn-close" onClick={() => setShowModal(false)}><X size={20} /></button>
            </div>

            <p style={{ color: 'var(--color-text-muted)', fontSize: '14px', marginBottom: '24px' }}>
              AI 메이트를 최대 3명 선택하고 나만의 스터디 방을 만들어보세요
            </p>

            <div className="modal-body" style={{ padding: '0 4px' }}>
              <div style={{ marginBottom: '24px' }}>
                <label style={{ display: 'block', fontSize: '14px', fontWeight: '700', color: 'var(--color-text-main)', marginBottom: '8px' }}>채팅방 이름</label>
                <input 
                  type="text" 
                  className="input-field" 
                  value={newRoom.roomName} 
                  onChange={e => setNewRoom({ ...newRoom, roomName: e.target.value })} 
                  placeholder="예: 토익 스피킹 연습방, 자료구조 벼락치기" 
                  style={{ width: '100%', padding: '12px 16px', borderRadius: '12px' }}
                />
              </div>

              <div>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                  <label style={{ fontSize: '14px', fontWeight: '700', color: 'var(--color-text-main)' }}>AI 페르소나 선택 <span style={{ color: 'var(--color-text-muted)', fontWeight: 'normal', fontSize: '13px' }}>(최대 3명)</span></label>
                  <div style={{ fontSize: '13px', fontWeight: '700', color: 'var(--color-primary)' }}>
                    {newRoom.agents.length}명 선택됨
                  </div>
                </div>

                {/* 페르소나 카드 리스트 (가로 스크롤) */}
                <div style={{ 
                  display: 'flex', 
                  gap: '16px', 
                  overflowX: 'auto', 
                  padding: '4px 4px 16px 4px',
                  // 스크롤바 숨기기
                  msOverflowStyle: 'none',
                  scrollbarWidth: 'none',
                }}>
                  {AI_PERSONAS.map(persona => {
                    const isSelected = newRoom.agents.some(a => a.id === persona.id);
                    return (
                      <div 
                        key={persona.id}
                        onClick={() => toggleAgentSelection(persona)}
                        style={{
                          flex: '0 0 200px',
                          height: '280px',
                          borderRadius: '16px',
                          padding: '24px 16px',
                          cursor: 'pointer',
                          border: `2px solid ${isSelected ? persona.color : '#E5E7EB'}`,
                          backgroundColor: isSelected ? persona.bgLight : '#FFFFFF',
                          boxShadow: isSelected ? `0 4px 12px ${persona.color}20` : '0 2px 8px rgba(0,0,0,0.05)',
                          display: 'flex',
                          flexDirection: 'column',
                          alignItems: 'center',
                          textAlign: 'center',
                          transition: 'all 0.2s ease-in-out',
                          position: 'relative'
                        }}
                      >
                        {isSelected && (
                          <div style={{
                            position: 'absolute',
                            top: '12px',
                            right: '12px',
                            backgroundColor: persona.color,
                            color: 'white',
                            borderRadius: '50%',
                            width: '24px',
                            height: '24px',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center'
                          }}>
                            <Check size={14} strokeWidth={3} />
                          </div>
                        )}

                        <div style={{
                          width: '70px',
                          height: '70px',
                          borderRadius: '50%',
                          backgroundColor: persona.bgLight,
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          marginBottom: '16px',
                          border: `2px solid ${persona.color}40`,
                          color: persona.color
                        }}>
                          <Bot size={32} />
                        </div>
                        
                        <div style={{ color: persona.color, fontSize: '16px', fontWeight: '800', marginBottom: '4px' }}>{persona.name}</div>
                        <div style={{ color: 'var(--color-text-muted)', fontSize: '12px', marginBottom: '16px' }}>{persona.role}</div>
                        
                        <div style={{ fontSize: '13px', lineHeight: '1.5', color: 'var(--color-text-main)', wordBreak: 'keep-all' }}>
                          {persona.description}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>

            <div className="modal-footer" style={{ marginTop: '24px', borderTop: 'none', paddingTop: 0 }}>
              <button 
                className="btn-primary" 
                style={{ width: '100%', height: '52px', fontSize: '16px', fontWeight: '700', borderRadius: '12px' }} 
                onClick={handleCreateRoom}
              >
                채팅방 생성하기
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
