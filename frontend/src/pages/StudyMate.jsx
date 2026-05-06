import React, { useState, useEffect, useRef } from 'react';
import { useAuth } from '../hooks/useAuth';
import { agentService } from '../services/api';
import { Bot, Plus, Trash2, Send, MessageCircle, AlertCircle, X, Sparkles } from 'lucide-react';

export default function StudyMate() {
  const { userId } = useAuth();
  
  const [agents, setAgents] = useState([]);
  const [selectedAgent, setSelectedAgent] = useState(null);
  const [chatHistory, setChatHistory] = useState([]);
  const [message, setMessage] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [showModal, setShowModal] = useState(false);
  
  const [newAgent, setNewAgent] = useState({
    name: '', 
    role: '',
    persona: '',
    tone: '친절하고 전문적인 말투',
    goal: '사용자의 학습을 돕는다'
  });

  const chatEndRef = useRef(null);

  useEffect(() => {
    if (userId) {
      loadAgents();
    } else {
      setAgents([]);
      setSelectedAgent(null);
      setChatHistory([]);
    }
  }, [userId]);

  useEffect(() => {
    scrollToBottom();
  }, [chatHistory, isTyping]);

  const loadAgents = async () => {
    try {
      const data = await agentService.getAgents(userId);
      setAgents(data || []);
    } catch (err) {
      console.error('에이전트 목록 조회 실패:', err);
    }
  };

  const handleCreateAgent = async (e) => {
    e.preventDefault();
    if (agents.length >= 3) {
      alert('AI 에이전트는 최대 3개까지만 생성할 수 있습니다.');
      return;
    }
    
    if (newAgent.persona.length < 5) {
      alert('성격/특징은 최소 5자 이상 입력해야 합니다.');
      return;
    }

    try {
      await agentService.createAgent(userId, newAgent);
      setShowModal(false);
      setNewAgent({
        name: '', role: '', persona: '', tone: '친절하고 전문적인 말투', goal: '사용자의 학습을 돕는다'
      });
      loadAgents();
    } catch (err) {
      alert(err.message || '생성에 실패했습니다.');
    }
  };

  const handleDeleteAgent = async (e, agentId) => {
    e.stopPropagation();
    if (!window.confirm('정말 이 에이전트를 삭제하시겠습니까? 대화 내용이 모두 사라집니다.')) return;
    
    try {
      await agentService.deleteAgent(userId, agentId);
      if (selectedAgent?.id === agentId) {
        setSelectedAgent(null);
        setChatHistory([]);
      }
      loadAgents();
    } catch (err) {
      alert('삭제에 실패했습니다.');
    }
  };

  const selectAgent = async (agent) => {
    setSelectedAgent(agent);
    try {
      const history = await agentService.getChatHistory(userId, agent.id);
      setChatHistory(history || []);
    } catch (err) {
      console.error('채팅 내역 조회 실패:', err);
      setChatHistory([]);
    }
  };

  const sendMessage = async (e) => {
    e.preventDefault();
    if (!message.trim() || !selectedAgent || isTyping) return;

    const userMsg = {
      id: Date.now(),
      content: message,
      sender: 'USER',
      createdAt: new Date().toISOString()
    };

    setChatHistory(prev => [...prev, userMsg]);
    const inputMsg = message;
    setMessage('');
    setIsTyping(true);

    try {
      const res = await agentService.sendMessage(userId, selectedAgent.id, inputMsg);
      const aiMsg = {
        id: Date.now() + 1,
        content: res.answer,
        sender: 'AI',
        createdAt: new Date().toISOString()
      };
      setChatHistory(prev => [...prev, aiMsg]);
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

  // 프로필 색상 매핑용 헬퍼 함수
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
        {/* 좌측: 에이전트 리스트 패널 */}
        <div className="glass-panel layout-pane-left animate-fade-in">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '20px' }}>
            <h2 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '8px', fontSize: '18px' }}>
              <Sparkles size={20} color="var(--color-primary)" /> AI 학습메이트
            </h2>
            <button 
              className="btn-outline" 
              style={{ width: 'auto', height: '28px', padding: '0 10px', fontSize: '12px', display: 'flex', alignItems: 'center', gap: '4px' }}
              onClick={() => setShowModal(true)}
              disabled={agents.length >= 3}
            >
              <Plus size={16} /> 에이전트 생성 ({agents.length}/3)
            </button>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', overflowY: 'auto', paddingRight: '4px' }}>
            {agents.length === 0 ? (
              <div className="empty-state" style={{ padding: '40px 0' }}>
                <p>생성된 에이전트가 없습니다.</p>
                <p style={{ fontSize: '12px' }}>나만의 학습 도우미를 만들어보세요!</p>
              </div>
            ) : (
              agents.map((agent, index) => {
                const isActive = selectedAgent?.id === agent.id;
                const avatarColor = getAvatarColor(index);
                
                return (
                  <div 
                    key={agent.id} 
                    style={{
                      padding: '16px', borderRadius: '12px', border: '1px solid var(--color-border)', backgroundColor: 'var(--color-bg-base)', cursor: 'pointer', display: 'flex', alignItems: 'flex-start', gap: '12px', transition: 'all 0.2s ease',
                      ...(isActive ? { borderColor: 'var(--color-primary)', backgroundColor: 'rgba(96, 201, 90, 0.05)', boxShadow: '0 2px 8px rgba(96, 201, 90, 0.1)' } : {})
                    }}
                    onClick={() => selectAgent(agent)}
                  >
                    <div className="avatar" style={{ backgroundColor: avatarColor.bg, color: avatarColor.text }}>
                      {agent.name.charAt(0)}
                    </div>
                    
                    <div style={{ flex: 1, overflow: 'hidden' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                        <div style={{ fontWeight: 'bold', fontSize: '15px', color: 'var(--color-text-main)', marginBottom: '4px' }}>{agent.name}</div>
                        <button 
                          style={{ background: 'none', border: 'none', color: '#D1D5DB', cursor: 'pointer', padding: '2px' }}
                          onClick={(e) => handleDeleteAgent(e, agent.id)}
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                      <div style={{ marginBottom: '6px' }}>
                        <span className="tag">#{agent.role}</span>
                      </div>
                      <div style={{ fontSize: '12px', color: 'var(--color-text-muted)', lineHeight: '1.4' }}>
                        {agent.persona.length > 25 ? agent.persona.substring(0, 25) + '...' : agent.persona}
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
          {!selectedAgent ? (
            <div className="empty-state">
              <Bot size={50} color="#E5E7EB" style={{ marginBottom: '16px' }} />
              <h3 style={{ margin: '0 0 8px 0', color: 'var(--color-text-main)' }}>AI 학습메이트</h3>
              <p style={{ margin: 0, color: 'var(--color-text-muted)', fontSize: '14px' }}>
                좌측에서 대화할 에이전트를 선택하거나 새로 생성해주세요.
              </p>
            </div>
          ) : (
            <div className="chat-container">
              <div className="chat-header">
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <div className="avatar-sm" style={{ backgroundColor: 'var(--color-primary)', color: 'white' }}>
                    {selectedAgent.name.charAt(0)}
                  </div>
                  <div>
                    <div style={{ fontWeight: 'bold', fontSize: '15px' }}>{selectedAgent.name}</div>
                    <div style={{ fontSize: '12px', color: 'var(--color-text-muted)' }}>{selectedAgent.role}</div>
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
                    return (
                      <div key={idx} style={{ display: 'flex', flexDirection: 'column', maxWidth: '75%', alignSelf: isUser ? 'flex-end' : 'flex-start' }}>
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
                  placeholder={`${selectedAgent.name}에게 메시지 보내기...`}
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

      {/* 에이전트 생성 모달 */}
      {showModal && (
        <div className="modal-overlay">
          <div className="glass-panel modal-content">
            <div className="modal-header">
              <h3 style={{ margin: 0 }}>새로운 AI 에이전트 생성</h3>
              <button style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-text-muted)' }} onClick={() => setShowModal(false)}><X size={20} /></button>
            </div>
            <form onSubmit={handleCreateAgent} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '13px', fontWeight: '600', color: 'var(--color-text-main)', marginBottom: '6px' }}>이름 (최대 30자)</label>
                <input type="text" className="input-field" maxLength="30" required value={newAgent.name} onChange={e => setNewAgent({...newAgent, name: e.target.value})} placeholder="예: 알고리즘 코치" />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '13px', fontWeight: '600', color: 'var(--color-text-main)', marginBottom: '6px' }}>역할 (태그용, 최대 20자)</label>
                <input type="text" className="input-field" maxLength="20" required value={newAgent.role} onChange={e => setNewAgent({...newAgent, role: e.target.value})} placeholder="예: 힌트형" />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '13px', fontWeight: '600', color: 'var(--color-text-main)', marginBottom: '6px' }}>성격 및 설명 (최소 5자, 최대 1000자)</label>
                <textarea className="input-field" style={{ height: '80px', paddingTop: '10px', resize: 'none' }} minLength="5" maxLength="1000" required value={newAgent.persona} onChange={e => setNewAgent({...newAgent, persona: e.target.value})} placeholder="예: 풀이 과정을 중심으로 도와주는 AI" />
              </div>
              <button type="submit" className="btn-primary" style={{ marginTop: '8px' }}>에이전트 생성하기</button>
            </form>
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
