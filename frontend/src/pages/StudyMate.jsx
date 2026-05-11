import React, { useState, useEffect, useRef } from 'react';
import { useAuth } from '../hooks/useAuth';
import { roomService } from '../services/api';
import { Bot, Plus, Trash2, Send, AlertCircle, X, Sparkles, Users, ChevronRight } from 'lucide-react';

export default function StudyMate() {
  const { userId } = useAuth();

  const [rooms, setRooms] = useState([]);
  const [selectedRoom, setSelectedRoom] = useState(null);
  const [chatHistory, setChatHistory] = useState([]);
  const [message, setMessage] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [currentAgentIndex, setCurrentAgentIndex] = useState(0);
  const [deleteModal, setDeleteModal] = useState({ show: false, roomId: null });

  const [newRoom, setNewRoom] = useState({
    roomName: '',
    roomDescription: '',
    agents: [{
      name: '',
      role: '',
      persona: '',
      tone: '친절한',
      goal: ''
    }]
  });

  const chatEndRef = useRef(null);

  useEffect(() => {
    if (userId) {
      loadRooms();
    } else {
      setRooms([]);
      setSelectedRoom(null);
      setChatHistory([]);
    }
  }, [userId]);

  useEffect(() => {
    scrollToBottom();
  }, [chatHistory, isTyping]);

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
    setNewRoom(prev => {
      if (prev.agents.length >= 3) {
        alert('최대 3명의 에이전트까지 추가할 수 있습니다.');
        return prev;
      }
      const newAgent = { name: '', role: '', persona: '', tone: '친절한', goal: '' };
      const nextAgents = [...prev.agents, newAgent];
      setCurrentAgentIndex(nextAgents.length - 1);
      return { ...prev, agents: nextAgents };
    });
  };

  const handleRemoveAgent = (index) => {
    if (newRoom.agents.length <= 1) return;
    const updatedAgents = newRoom.agents.filter((_, i) => i !== index);
    setNewRoom(prev => ({ ...prev, agents: updatedAgents }));
    if (currentAgentIndex >= updatedAgents.length) {
      setCurrentAgentIndex(updatedAgents.length - 1);
    }
  };

  const handleAgentChange = (index, field, value) => {
    const updatedAgents = [...newRoom.agents];
    updatedAgents[index][field] = value;
    setNewRoom(prev => ({ ...prev, agents: updatedAgents }));
  };

  const handleCreateRoom = async (e) => {
    if (e) e.preventDefault();

    if (!newRoom.roomName) return alert('채팅방 이름을 입력해주세요.');
    if (newRoom.agents.some(a => !a.name || !a.role || a.persona.length < 5)) {
      alert('모든 에이전트의 정보를 올바르게 입력해주세요. (성격 5자 이상)');
      return;
    }

    try {
      const payload = {
        roomName: newRoom.roomName,
        agents: newRoom.agents
      };
      console.log('채팅방 생성 요청 페이로드:', JSON.stringify(payload, null, 2));
      await roomService.createRoom(userId, payload);
      setShowModal(false);
      setCurrentAgentIndex(0);
      setNewRoom({
        roomName: '',
        roomDescription: '',
        agents: [{ name: '', role: '', persona: '', tone: '친절한', goal: '' }]
      });
      loadRooms();
    } catch (err) {
      alert(err.message || '채팅방 생성에 실패했습니다.');
    }
  };

  const getRoomId = (room) => room?.agentRoomId ?? room?.roomId ?? room?.id;

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
    if (!message.trim() || !selectedRoom || isTyping) return;

    const roomId = getRoomId(selectedRoom);
    if (!roomId) {
      alert("채팅방 ID를 찾을 수 없습니다.");
      return;
    }

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
    setIsTyping(true);

    try {
      const res = await roomService.sendMessage(userId, roomId, inputMsg);
      // res는 MultiChatResponse 형태이며, replies 필드에 답변 배열이 존재함
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
        // 단일 응답 fallback (혹시 구조가 다를 경우 대비)
        const aiMsg = {
          id: Date.now() + 1,
          content: res.answer || '응답이 없습니다.',
          sender: 'AI',
          createdAt: new Date().toISOString()
        };
        setChatHistory(prev => [...prev, aiMsg]);
      }
    } catch (err) {
      alert('메시지 전송에 실패했습니다.');
      setChatHistory(prev => prev.filter(m => m.id !== userMsg.id));
      setMessage(inputMsg);
    } finally {
      setIsTyping(false);
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

  if (!userId) {
    return (
      <div className="container-main">
        <div className="glass-panel empty-state" style={{ padding: '40px' }}>
          <AlertCircle size={48} color="var(--color-text-muted)" style={{ margin: '0 auto 16px' }} />
          <h3>로그인이 필요합니다</h3>
          <p style={{ color: 'var(--color-text-muted)' }}>AI 학습메이트 기능은 로그인 후 이용 가능합니다.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="container-main">
      <div className="layout-split">
        {/* 좌측: 채팅방 리스트 패널 */}
        <div className="glass-panel layout-pane-left animate-fade-in">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
            <h2 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '8px', fontSize: '18px' }}>
              <Users size={20} color="var(--color-primary)" /> 내 채팅방
            </h2>
            <button
              className="btn-outline"
              style={{ width: 'auto', height: '28px', padding: '0 10px', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px' }}
              onClick={() => setShowModal(true)}
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
                    className="room-card"
                    style={{
                      padding: '16px', borderRadius: '12px', border: '1px solid var(--color-border)', backgroundColor: 'var(--color-bg-base)', cursor: 'pointer', display: 'flex', alignItems: 'flex-start', gap: '12px', transition: 'all 0.2s ease',
                      position: 'relative',
                      ...(isActive ? { borderColor: 'var(--color-primary)', backgroundColor: 'rgba(96, 201, 90, 0.05)', boxShadow: '0 2px 8px rgba(96, 201, 90, 0.1)' } : {})
                    }}
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
                      <div key={msgKey} style={{ display: 'flex', flexDirection: 'column', maxWidth: '75%', alignSelf: isUser ? 'flex-end' : 'flex-start' }}>
                        <div style={{ fontSize: '12px', marginBottom: '4px', marginLeft: '4px', color: 'var(--color-text-muted)', textAlign: isUser ? 'right' : 'left' }}>
                          {!isUser && (msg.senderName || msg.sender)}
                        </div>
                        <div className={`chat-bubble ${isUser ? 'user' : 'ai'}`}>
                          {msg.content}
                        </div>
                        <div style={{ fontSize: '11px', color: '#9CA3AF', marginTop: '4px', textAlign: isUser ? 'right' : 'left' }}>
                          {formatTime(msg.createdAt)}
                        </div>
                      </div>
                    );
                  })
                )}
                {isTyping && (
                  <div style={{ display: 'flex', flexDirection: 'column', maxWidth: '75%', alignSelf: 'flex-start' }}>
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
                  placeholder="메시지 보내기..."
                  disabled={isTyping}
                />
                <button type="submit" className="btn-primary" style={{ width: '42px', height: '42px', borderRadius: '50%', padding: 0, flexShrink: 0, display: 'flex', justifyContent: 'center', alignItems: 'center' }} disabled={isTyping || !message.trim()}>
                  <Send size={18} />
                </button>
              </form>
            </div>
          )}
        </div>
      </div>

      {/* 채팅방 생성 모달 (가로 슬라이더 개편) */}
      {showModal && (
        <div className="modal-overlay">
          <div className="glass-panel modal-content" style={{ maxWidth: '550px', width: '95%', maxHeight: '90vh', display: 'flex', flexDirection: 'column' }}>
            <div className="modal-header" style={{ paddingBottom: '16px', borderBottom: '1px solid var(--color-border)', marginBottom: '20px' }}>
              <h3 style={{ margin: 0 }}>새로운 채팅방 생성</h3>
              <button style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-text-muted)' }} onClick={() => { setShowModal(false); setCurrentAgentIndex(0); }}><X size={20} /></button>
            </div>

            <div style={{ overflowY: 'auto', flex: 1, paddingRight: '4px' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                {/* 1. 채팅방 정보 */}
                <div style={{ padding: '4px' }}>
                  <label style={{ display: 'block', fontSize: '13px', fontWeight: '700', color: 'var(--color-text-main)', marginBottom: '10px' }}>채팅방 이름</label>
                  <input type="text" className="input-field" value={newRoom.roomName} onChange={e => setNewRoom({ ...newRoom, roomName: e.target.value })} placeholder="예: 수학 문제 풀이 스터디" />
                </div>

                <div style={{ width: '100%', height: '1px', backgroundColor: 'var(--color-border)' }} />

                {/* 2. 에이전트 섹션 헤더 */}
                <div>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
                    <div style={{ fontSize: '14px', fontWeight: '700', color: 'var(--color-text-main)' }}>
                      에이전트 설정 ({newRoom.agents.length}/3)
                    </div>
                    <button
                      type="button"
                      className="btn-outline"
                      onClick={handleAddAgent}
                      disabled={newRoom.agents.length >= 3}
                      style={{ width: 'auto', height: '32px', padding: '0 12px', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px' }}
                    >
                      <Plus size={14} /> 에이전트 추가
                    </button>
                  </div>

                  {/* 에이전트 슬라이더 네비게이션 */}
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '20px', marginBottom: '20px', backgroundColor: 'var(--color-bg-base)', padding: '12px', borderRadius: '8px' }}>
                    <button
                      type="button"
                      onClick={() => setCurrentAgentIndex(prev => Math.max(0, prev - 1))}
                      disabled={currentAgentIndex === 0}
                      style={{ background: 'none', border: 'none', cursor: currentAgentIndex === 0 ? 'default' : 'pointer', color: currentAgentIndex === 0 ? '#D1D5DB' : 'var(--color-primary)' }}
                    >
                      <ChevronRight size={24} style={{ transform: 'rotate(180deg)' }} />
                    </button>

                    <div style={{ fontSize: '15px', fontWeight: 'bold', color: 'var(--color-primary)', minWidth: '100px', textAlign: 'center' }}>
                      에이전트 {currentAgentIndex + 1}
                    </div>

                    <button
                      type="button"
                      onClick={() => setCurrentAgentIndex(prev => Math.min(newRoom.agents.length - 1, prev + 1))}
                      disabled={currentAgentIndex === newRoom.agents.length - 1}
                      style={{ background: 'none', border: 'none', cursor: currentAgentIndex === newRoom.agents.length - 1 ? 'default' : 'pointer', color: currentAgentIndex === newRoom.agents.length - 1 ? '#D1D5DB' : 'var(--color-primary)' }}
                    >
                      <ChevronRight size={24} />
                    </button>
                  </div>

                  {/* 현재 선택된 에이전트 폼 */}
                  {newRoom.agents[currentAgentIndex] ? (
                    <div key={currentAgentIndex} className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', gap: '16px', padding: '4px' }}>
                      <div style={{ display: 'flex', gap: '12px' }}>
                        <div style={{ flex: 1 }}>
                          <label style={{ display: 'block', fontSize: '12px', fontWeight: '600', marginBottom: '6px' }}>이름</label>
                          <input type="text" className="input-field" value={newRoom.agents[currentAgentIndex].name} onChange={e => handleAgentChange(currentAgentIndex, 'name', e.target.value)} placeholder="예: 수학 선생님" />
                        </div>
                        <div style={{ flex: 1 }}>
                          <label style={{ display: 'block', fontSize: '12px', fontWeight: '600', marginBottom: '6px' }}>역할 (Role)</label>
                          <input type="text" className="input-field" value={newRoom.agents[currentAgentIndex].role} onChange={e => handleAgentChange(currentAgentIndex, 'role', e.target.value)} placeholder="예: 힌트형" />
                        </div>
                      </div>

                      <div>
                        <label style={{ display: 'block', fontSize: '12px', fontWeight: '600', marginBottom: '6px' }}>학습 목표 (Goal)</label>
                        <input type="text" className="input-field" value={newRoom.agents[currentAgentIndex].goal} onChange={e => handleAgentChange(currentAgentIndex, 'goal', e.target.value)} placeholder="예: 사용자의 수학 학습을 돕는다" />
                      </div>

                      <div>
                        <label style={{ display: 'block', fontSize: '12px', fontWeight: '600', marginBottom: '6px' }}>말투 (Tone)</label>
                        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '8px' }}>
                          {['친절한', '엄격한', '코치형', '논리형', '동기부여형', '짧고 간결한'].map(t => (
                            <button
                              key={t}
                              type="button"
                              onClick={() => handleAgentChange(currentAgentIndex, 'tone', t)}
                              style={{
                                padding: '4px 10px', fontSize: '11px', borderRadius: '16px', border: '1px solid',
                                borderColor: newRoom.agents[currentAgentIndex].tone === t ? 'var(--color-primary)' : 'var(--color-border)',
                                backgroundColor: newRoom.agents[currentAgentIndex].tone === t ? 'rgba(96, 201, 90, 0.1)' : 'white',
                                color: newRoom.agents[currentAgentIndex].tone === t ? 'var(--color-primary)' : 'var(--color-text-muted)',
                                cursor: 'pointer'
                              }}
                            >
                              {t}
                            </button>
                          ))}
                        </div>
                        <input type="text" className="input-field" value={newRoom.agents[currentAgentIndex].tone} onChange={e => handleAgentChange(currentAgentIndex, 'tone', e.target.value)} placeholder="예: 설명형, 리뷰어형 등 직접 입력" />
                      </div>

                    <div>
                      <label style={{ display: 'block', fontSize: '12px', fontWeight: '600', marginBottom: '6px' }}>성격 및 설명</label>
                      <textarea className="input-field" style={{ height: '80px', paddingTop: '12px', resize: 'none' }} value={newRoom.agents[currentAgentIndex].persona} onChange={e => handleAgentChange(currentAgentIndex, 'persona', e.target.value)} placeholder="예: 풀이 과정을 중심으로 차근차근 설명해주는 AI" />
                    </div>

                      {newRoom.agents.length > 1 && (
                        <button
                          type="button"
                          onClick={() => handleRemoveAgent(currentAgentIndex)}
                          style={{ alignSelf: 'flex-end', color: '#EF4444', fontSize: '12px', background: 'none', border: 'none', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '4px', marginTop: '8px' }}
                        >
                          <Trash2 size={14} /> 현재 에이전트 삭제
                        </button>
                      )}
                    </div>
                  ) : null}
                </div>
              </div>
            </div>

            <div style={{ paddingTop: '20px', borderTop: '1px solid var(--color-border)', marginTop: '20px' }}>
              <button className="btn-primary" style={{ width: '100%', height: '44px' }} onClick={handleCreateRoom}>채팅방 생성하기</button>
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
              <button
                className="btn-outline"
                onClick={() => setDeleteModal({ show: false, roomId: null })}
                style={{ flex: 1 }}
              >
                취소
              </button>
              <button
                className="btn-primary"
                onClick={handleDeleteRoom}
                style={{ flex: 1, backgroundColor: '#EF4444' }}
              >
                삭제하기
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 스타일 */}
      <style>
        {`
          .room-actions {
            position: absolute;
            top: 8px;
            right: 8px;
            opacity: 0;
            transition: opacity 0.2s ease;
          }
          .room-card:hover .room-actions {
            opacity: 1;
          }
          @keyframes typing {
            0%, 100% { transform: translateY(0); opacity: 0.5; }
            50% { transform: translateY(-3px); opacity: 1; }
          }
          .dot {
            display: inline-block;
            width: 4px; height: 4px;
            background-color: #6B7280;
            border-radius: 50%;
            margin: 0 2px;
            animation: typing 1s infinite;
          }
          .dot:nth-child(2) { animation-delay: 0.2s; }
          .dot:nth-child(3) { animation-delay: 0.4s; }
        `}
      </style>
    </div>
  );
}
