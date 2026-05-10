import React, { useState, useEffect, useRef } from 'react';
import { useAuth } from '../hooks/useAuth';
import { roomService } from '../services/api';
import { Bot, Plus, Trash2, Send, AlertCircle, X, Sparkles, Users } from 'lucide-react';

export default function StudyMate() {
  const { userId } = useAuth();
  
  const [rooms, setRooms] = useState([]);
  const [selectedRoom, setSelectedRoom] = useState(null);
  const [chatHistory, setChatHistory] = useState([]);
  const [message, setMessage] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [showModal, setShowModal] = useState(false);
  
  const [newRoom, setNewRoom] = useState({
    roomName: '',
    agents: [{
      name: '', 
      role: '',
      persona: '',
      tone: '친절하고 전문적인 말투',
      goal: '사용자의 학습을 돕는다'
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

  const handleAddAgentToNewRoom = () => {
    if (newRoom.agents.length >= 3) {
      alert('한 방에 최대 3명의 에이전트만 추가할 수 있습니다.');
      return;
    }
    setNewRoom(prev => ({
      ...prev,
      agents: [...prev.agents, {
        name: '', role: '', persona: '', tone: '친절하고 전문적인 말투', goal: '사용자의 학습을 돕는다'
      }]
    }));
  };

  const handleRemoveAgentFromNewRoom = (index) => {
    if (newRoom.agents.length <= 1) {
      alert('최소 1명의 에이전트가 필요합니다.');
      return;
    }
    setNewRoom(prev => ({
      ...prev,
      agents: prev.agents.filter((_, i) => i !== index)
    }));
  };

  const handleAgentChange = (index, field, value) => {
    const updatedAgents = [...newRoom.agents];
    updatedAgents[index][field] = value;
    setNewRoom(prev => ({ ...prev, agents: updatedAgents }));
  };

  const handleCreateRoom = async (e) => {
    e.preventDefault();
    if (newRoom.agents.some(a => a.persona.length < 5)) {
      alert('각 에이전트의 성격/특징은 최소 5자 이상 입력해야 합니다.');
      return;
    }

    try {
      await roomService.createRoom(userId, newRoom);
      setShowModal(false);
      setNewRoom({
        roomName: '',
        agents: [{ name: '', role: '', persona: '', tone: '친절하고 전문적인 말투', goal: '사용자의 학습을 돕는다' }]
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
                    style={{
                      padding: '16px', borderRadius: '12px', border: '1px solid var(--color-border)', backgroundColor: 'var(--color-bg-base)', cursor: 'pointer', display: 'flex', alignItems: 'flex-start', gap: '12px', transition: 'all 0.2s ease',
                      ...(isActive ? { borderColor: 'var(--color-primary)', backgroundColor: 'rgba(96, 201, 90, 0.05)', boxShadow: '0 2px 8px rgba(96, 201, 90, 0.1)' } : {})
                    }}
                    onClick={() => selectRoom(room)}
                  >
                    <div className="avatar" style={{ backgroundColor: avatarColor.bg, color: avatarColor.text }}>
                      <Users size={20} />
                    </div>
                    
                    <div style={{ flex: 1, overflow: 'hidden' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                        <div style={{ fontWeight: 'bold', fontSize: '15px', color: 'var(--color-text-main)', marginBottom: '4px' }}>{room.roomName || `채팅방 ${index+1}`}</div>
                      </div>
                      <div style={{ fontSize: '12px', color: 'var(--color-text-muted)', lineHeight: '1.4' }}>
                        {room.agents?.map(a => a.name).join(', ')} ({room.agents?.length || 0}명)
                      </div>
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

      {/* 채팅방 생성 모달 */}
      {showModal && (
        <div className="modal-overlay">
          <div className="glass-panel modal-content" style={{ maxWidth: '600px', width: '90%', maxHeight: '90vh', display: 'flex', flexDirection: 'column' }}>
            <div className="modal-header" style={{ paddingBottom: '16px', borderBottom: '1px solid var(--color-border)', marginBottom: '16px' }}>
              <h3 style={{ margin: 0 }}>새로운 채팅방 생성</h3>
              <button style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-text-muted)' }} onClick={() => setShowModal(false)}><X size={20} /></button>
            </div>
            
            <div style={{ overflowY: 'auto', flex: 1, paddingRight: '8px' }}>
              <form id="create-room-form" onSubmit={handleCreateRoom} style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '13px', fontWeight: '600', color: 'var(--color-text-main)', marginBottom: '6px' }}>채팅방 이름</label>
                  <input type="text" className="input-field" required value={newRoom.roomName} onChange={e => setNewRoom({...newRoom, roomName: e.target.value})} placeholder="예: 코딩 스터디" />
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: '10px' }}>
                  <label style={{ fontSize: '14px', fontWeight: '600', color: 'var(--color-text-main)' }}>에이전트 목록 ({newRoom.agents.length}/3)</label>
                  <button type="button" className="btn-outline" onClick={handleAddAgentToNewRoom} disabled={newRoom.agents.length >= 3} style={{ padding: '6px 12px', fontSize: '12px' }}>
                    + 에이전트 추가
                  </button>
                </div>

                {newRoom.agents.map((agent, index) => (
                  <div key={index} style={{ padding: '16px', border: '1px solid var(--color-border)', borderRadius: '8px', position: 'relative' }}>
                    {newRoom.agents.length > 1 && (
                      <button type="button" onClick={() => handleRemoveAgentFromNewRoom(index)} style={{ position: 'absolute', top: '10px', right: '10px', background: 'none', border: 'none', color: 'red', cursor: 'pointer' }}>
                        <X size={16} />
                      </button>
                    )}
                    <h4 style={{ margin: '0 0 12px 0', fontSize: '14px', color: 'var(--color-primary)' }}>에이전트 {index + 1}</h4>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                      <div>
                        <label style={{ display: 'block', fontSize: '12px', fontWeight: '600', marginBottom: '4px' }}>이름</label>
                        <input type="text" className="input-field" required value={agent.name} onChange={e => handleAgentChange(index, 'name', e.target.value)} placeholder="예: 알고리즘 코치" />
                      </div>
                      <div>
                        <label style={{ display: 'block', fontSize: '12px', fontWeight: '600', marginBottom: '4px' }}>역할</label>
                        <input type="text" className="input-field" required value={agent.role} onChange={e => handleAgentChange(index, 'role', e.target.value)} placeholder="예: 힌트형" />
                      </div>
                      <div>
                        <label style={{ display: 'block', fontSize: '12px', fontWeight: '600', marginBottom: '4px' }}>성격 및 설명</label>
                        <textarea className="input-field" style={{ height: '60px', paddingTop: '8px', resize: 'none' }} minLength="5" required value={agent.persona} onChange={e => handleAgentChange(index, 'persona', e.target.value)} placeholder="예: 풀이 과정을 중심으로 도와주는 AI" />
                      </div>
                    </div>
                  </div>
                ))}
              </form>
            </div>
            
            <div style={{ paddingTop: '16px', borderTop: '1px solid var(--color-border)', marginTop: '16px' }}>
              <button type="submit" form="create-room-form" className="btn-primary" style={{ width: '100%' }}>채팅방 생성하기</button>
            </div>
          </div>
        </div>
      )}

      {/* 타이핑 애니메이션 CSS */}
      <style>
        {`
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
