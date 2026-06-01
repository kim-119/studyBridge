import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { roomService } from '../services/api';
import { Plus, X, Users, Send } from 'lucide-react';
import AgentNode from '../components/studymate/AgentNode';
import AgentDiscussionThread from '../components/studymate/AgentDiscussionThread';
import '../components/studymate/studymate-premium.css';

const AI_PERSONAS = [
  { id: 'bomi', name: '봄이', role: '열정 응원단장', color: '#ec4899', description: '"넌 할 수 있어!"' },
  { id: 'byeol', name: '별이', role: '공감 요정', color: '#8b5cf6', description: '"힘들었지? 괜찮아"' },
  { id: 'energizer', name: '에너자이저', role: '자극 응원단', color: '#f97316', description: '"파이팅!"' },
  { id: 'fighter', name: '열정 파이터', role: '동기부여 친구', color: '#ef4444', description: '"포기는 없어!"' },
  { id: 'brain', name: '두뇌풀가동', role: '논리형 분석가', color: '#38bdf8', description: '"이 문제의 핵심은..."' }
];

export default function StudyMate() {
  const { userId } = useAuth();
  const navigate = useNavigate();
  const MAX_ROOMS = 3;

  const [rooms, setRooms] = useState([]);
  const [selectedRoom, setSelectedRoom] = useState(null);
  const [chatHistory, setChatHistory] = useState([]);
  const [message, setMessage] = useState('');
  
  // Real-time Simulation State
  const [activeAgents, setActiveAgents] = useState({}); 
  const [typingAgents, setTypingAgents] = useState([]);
  
  const [showModal, setShowModal] = useState(false);
  const [newRoom, setNewRoom] = useState({ roomName: '', agents: [] });

  useEffect(() => {
    if (userId) {
      loadRooms();
    }
  }, [userId]);

  const loadRooms = async () => {
    try {
      const data = await roomService.getRooms(userId);
      setRooms(data || []);
    } catch (err) {
      console.error('채팅방 목록 조회 실패:', err);
    }
  };

  const getRoomId = (room) => room?.agentRoomId ?? room?.roomId ?? room?.id;

  const handleCreateRoom = async (e) => {
    e?.preventDefault();
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
      await roomService.createRoom(userId, payload);
      setShowModal(false);
      setNewRoom({ roomName: '', agents: [] });
      loadRooms();
    } catch (err) {
      alert('채팅방 생성에 실패했습니다.');
    }
  };

  const selectRoom = async (room) => {
    const roomId = getRoomId(room);
    if (!roomId) return;
    setSelectedRoom({ ...room, roomId });
    try {
      const history = await roomService.getChatHistory(userId, roomId);
      setChatHistory(history || []);
    } catch (err) {
      setChatHistory([]);
    }
  };

  const sendMessage = async (e) => {
    e.preventDefault();
    if (!userId || !message.trim() || !selectedRoom) return;

    const roomId = getRoomId(selectedRoom);
    if (typingAgents.length > 0) return; // Prevent sending while agents are responding

    const userMsg = {
      id: Date.now(),
      content: message,
      sender: 'USER',
      createdAt: new Date().toISOString()
    };

    setChatHistory(prev => [...prev, userMsg]);
    const inputMsg = message;
    setMessage('');

    const agents = selectedRoom.agents || [];
    
    // 1. Initial Analysis
    let currentTyping = agents.map(a => ({ ...a, action: '질문 분석 중...' }));
    setTypingAgents(currentTyping);
    
    const newStatuses = {};
    agents.forEach(a => newStatuses[a.id] = 'analyzing');
    setActiveAgents(newStatuses);

    try {
      const res = await roomService.sendMessage(userId, roomId, inputMsg);
      
      // 2. Peer Review Phase (Simulation)
      setTimeout(() => {
        let reviewTyping = agents.map((a, idx) => ({ 
          ...a, 
          action: idx === 0 ? '답변 초안 작성 중...' : '초안 논리 검토 중...' 
        }));
        setTypingAgents(reviewTyping);
        
        const reviewStatuses = {};
        agents.forEach(a => reviewStatuses[a.id] = 'reviewing');
        setActiveAgents(reviewStatuses);

        // 3. Finalization Phase
        setTimeout(() => {
          setTypingAgents([]);
          
          const doneStatuses = {};
          agents.forEach(a => doneStatuses[a.id] = 'done');
          setActiveAgents(doneStatuses);

          if (res && res.replies) {
            const newMessages = res.replies.map((reply, idx) => {
              const agentData = agents.find(a => a.name === reply.agentName) || agents[0] || {};
              const isFinal = idx === res.replies.length - 1;
              return {
                id: Date.now() + idx + 1,
                content: reply.answer,
                sender: 'AI',
                senderName: agentData.name || reply.agentName || 'AI',
                agentColor: agentData.color || 'var(--color-primary)',
                actionType: isFinal ? '최종 답변 완료' : (idx === 0 ? '답변 초안 제안' : '피드백 및 보완'),
                createdAt: new Date().toISOString()
              };
            });
            setChatHistory(prev => [...prev, ...newMessages]);
          } else {
            setChatHistory(prev => [...prev, {
              id: Date.now() + 1,
              content: res.answer || '응답이 없습니다.',
              sender: 'AI',
              agentColor: 'var(--color-primary)',
              actionType: '최종 답변 완료',
              createdAt: new Date().toISOString()
            }]);
          }
          
          setTimeout(() => setActiveAgents({}), 2000);
        }, 2000); // Wait 2s for review

      }, 1500); // Wait 1.5s for analysis

    } catch (err) {
      alert('메시지 전송 실패');
      setTypingAgents([]);
      setActiveAgents({});
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

  return (
    <div className="studymate-premium-container">
      {!selectedRoom ? (
        // Room Selection View (Light Premium)
        <div style={{ maxWidth: '600px', margin: '40px auto' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
            <h2 style={{ margin: 0, color: 'var(--color-text-main)', fontSize: '24px' }}>나의 AI 협업 스터디 그룹</h2>
            <button 
              onClick={() => setShowModal(true)} 
              disabled={rooms.length >= MAX_ROOMS}
              className="btn-primary"
              style={{ width: 'auto', padding: '0 20px', borderRadius: '8px' }}
            >
              <Plus size={18} /> 새 그룹 생성
            </button>
          </div>
          
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {rooms.length === 0 ? (
              <div style={{ padding: '60px', textAlign: 'center', color: 'var(--color-text-muted)', background: '#FFFFFF', borderRadius: '16px', border: '1px solid var(--color-border)' }}>
                생성된 스터디 그룹이 없습니다. 새로운 AI 학습메이트 그룹을 구성해보세요.
              </div>
            ) : (
              rooms.map((room, idx) => (
                <div key={idx} style={{ padding: '24px', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center', background: '#FFFFFF', borderRadius: '16px', border: '1px solid var(--color-border)', boxShadow: '0 2px 10px rgba(0,0,0,0.02)', transition: 'all 0.2s ease' }} 
                     onClick={() => selectRoom(room)}
                     onMouseOver={(e) => e.currentTarget.style.borderColor = 'var(--color-primary)'}
                     onMouseOut={(e) => e.currentTarget.style.borderColor = 'var(--color-border)'}>
                  <div>
                    <h3 style={{ margin: '0 0 8px 0', color: 'var(--color-text-main)' }}>{room.roomName}</h3>
                    <div style={{ fontSize: '13px', color: 'var(--color-text-muted)' }}>참여 에이전트: {room.agents?.map(a => a.name).join(', ')}</div>
                  </div>
                  <div style={{ width: '40px', height: '40px', borderRadius: '50%', background: 'rgba(96, 201, 90, 0.1)', display: 'flex', justifyContent: 'center', alignItems: 'center', color: 'var(--color-primary)' }}>
                    <Users size={20} />
                  </div>
                </div>
              ))
            )}
          </div>
        </div>
      ) : (
        // Orchestration UX View
        <>
          <div className="orchestration-layout">
            {/* Left: Agent Nodes */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <h3 style={{ margin: 0, fontSize: '16px', color: 'var(--color-text-muted)' }}>참여 중인 에이전트</h3>
                <button 
                  onClick={() => setSelectedRoom(null)}
                  style={{ background: 'transparent', color: 'var(--color-text-muted)', border: '1px solid var(--color-border)', padding: '6px 12px', borderRadius: '6px', cursor: 'pointer', fontSize: '12px', fontWeight: 'bold' }}
                >
                  방 나가기
                </button>
              </div>
              
              {selectedRoom.agents?.map((agent, idx) => {
                const aiPersonaInfo = AI_PERSONAS.find(p => p.name === agent.name) || {};
                const color = aiPersonaInfo.color || 'var(--color-primary)';
                return (
                  <AgentNode 
                    key={idx}
                    index={idx}
                    agent={{ ...agent, color }}
                    status={activeAgents[agent.id] || 'idle'}
                    isActive={!!activeAgents[agent.id]}
                  />
                );
              })}
            </div>

            {/* Right: Collaborative Thread & Input */}
            <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
              <div style={{ flex: 1, minHeight: 0 }}>
                <AgentDiscussionThread 
                  messages={chatHistory} 
                  typingAgents={typingAgents} 
                />
              </div>
              
              <form className="chat-input-premium" onSubmit={sendMessage} style={{ marginTop: '16px' }}>
                <input 
                  type="text" 
                  placeholder="디지털 트윈을 기반으로 AI 그룹에게 피드백을 요청해보세요." 
                  value={message}
                  onChange={(e) => setMessage(e.target.value)}
                  disabled={typingAgents.length > 0}
                />
                <button type="submit" disabled={!message.trim() || typingAgents.length > 0}>
                  <Send size={18} />
                </button>
              </form>
            </div>
          </div>
        </>
      )}

      {/* Create Room Modal (Light Premium) */}
      {showModal && (
        <div className="modal-overlay">
          <div className="modal-content" style={{ maxWidth: '600px', background: '#FFFFFF', borderRadius: '16px' }}>
            <div className="modal-header">
              <h3 style={{ margin: 0, color: 'var(--color-text-main)' }}>새로운 AI 스터디 그룹 구성</h3>
              <button className="btn-close" onClick={() => setShowModal(false)}><X size={20} /></button>
            </div>
            <div className="modal-body">
              <div style={{ marginBottom: '24px' }}>
                <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px', fontWeight: '600' }}>스터디 그룹 이름</label>
                <input 
                  type="text" 
                  className="input-field" 
                  value={newRoom.roomName} 
                  onChange={e => setNewRoom({ ...newRoom, roomName: e.target.value })} 
                  placeholder="예: 알고리즘 마스터 과정 팀" 
                />
              </div>
              <div style={{ marginBottom: '24px' }}>
                <label style={{ display: 'block', marginBottom: '8px', fontSize: '14px', fontWeight: '600' }}>
                  에이전트 페르소나 선택 <span style={{ color: 'var(--color-text-muted)', fontWeight: 'normal' }}>(최대 3명)</span>
                </label>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                  {AI_PERSONAS.map(persona => {
                    const isSelected = newRoom.agents.some(a => a.id === persona.id);
                    return (
                      <div 
                        key={persona.id}
                        onClick={() => toggleAgentSelection(persona)}
                        style={{
                          padding: '16px',
                          border: `2px solid ${isSelected ? 'var(--color-primary)' : 'var(--color-border)'}`,
                          borderRadius: '12px',
                          background: isSelected ? 'rgba(96, 201, 90, 0.05)' : '#F9FAFB',
                          cursor: 'pointer',
                          transition: 'all 0.2s'
                        }}
                      >
                        <div style={{ fontWeight: '800', color: isSelected ? 'var(--color-primary)' : 'var(--color-text-main)', marginBottom: '4px' }}>
                          {persona.name}
                        </div>
                        <div style={{ fontSize: '13px', color: 'var(--color-text-muted)' }}>{persona.role}</div>
                      </div>
                    );
                  })}
                </div>
              </div>
              <button 
                onClick={handleCreateRoom}
                className="btn-primary"
                style={{ height: '48px', fontSize: '16px' }}
              >
                그룹 구성 완료
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
