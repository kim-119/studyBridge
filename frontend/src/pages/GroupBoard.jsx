import React, { useState, useEffect, useRef } from 'react';
import { useAuth } from '../hooks/useAuth';
import { agentService } from '../services/api';
import { Users, Bot, Plus, Trash2, Send, MessageCircle, AlertCircle, X } from 'lucide-react';

export default function GroupBoard() {
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
      id: Date.now(), // 임시 ID
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
      setChatHistory(prev => prev.filter(m => m.id !== userMsg.id)); // 롤백
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

  if (!userId) {
    return (
      <div style={styles.container}>
        <div className="glass-panel" style={{ padding: '40px', textAlign: 'center' }}>
          <AlertCircle size={48} color="var(--color-text-muted)" style={{ margin: '0 auto 16px' }} />
          <h3>로그인이 필요합니다</h3>
          <p style={{ color: 'var(--color-text-muted)' }}>그룹 스터디 및 AI 에이전트 기능은 로그인 후 이용 가능합니다.</p>
        </div>
      </div>
    );
  }

  return (
    <div style={styles.container}>
      <div style={styles.layout}>
        {/* Left: Group Study Content */}
        <div style={styles.leftPane}>
          <div className="glass-panel animate-fade-in" style={{ padding: '30px', marginBottom: '24px' }}>
            <h2 style={{ margin: 0, color: 'var(--color-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <Users size={24} /> 그룹게시판
            </h2>
            <p style={{ marginTop: '8px', color: 'var(--color-text-muted)' }}>
              함께 학습할 스터디 그룹을 확인하고 참여할 수 있습니다.
            </p>
          </div>

          <div className="glass-panel animate-fade-in" style={{ padding: '30px' }}>
            <h3>현재 스터디 그룹 (준비 중)</h3>
            <div style={styles.placeholderCard}>
              <p style={{ margin: 0, color: 'var(--color-text-muted)' }}>참여 중인 스터디 그룹이 없습니다.</p>
            </div>
            <button className="btn-primary" style={{ marginTop: '16px' }} onClick={() => alert('준비 중입니다.')}>
              스터디 탐색하기
            </button>
          </div>
        </div>

        {/* Right: AI Agent Panel */}
        <div style={styles.rightPane}>
          <div className="glass-panel animate-fade-in" style={styles.aiPanel}>
            
            {/* AI Agent Header & List */}
            <div style={styles.agentHeader}>
              <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Bot size={20} color="var(--color-primary)" /> AI Study Agents
              </h3>
              <button 
                className="btn-outline" 
                style={styles.createBtn} 
                onClick={() => setShowModal(true)}
                disabled={agents.length >= 3}
              >
                <Plus size={16} /> 에이전트 생성 ({agents.length}/3)
              </button>
            </div>

            <div style={styles.agentList}>
              {agents.length === 0 ? (
                <p style={{ fontSize: '13px', color: 'var(--color-text-muted)', textAlign: 'center', padding: '10px' }}>
                  생성된 AI 에이전트가 없습니다.
                </p>
              ) : (
                agents.map(agent => (
                  <div 
                    key={agent.id} 
                    style={{
                      ...styles.agentCard,
                      ...(selectedAgent?.id === agent.id ? styles.agentCardActive : {})
                    }}
                    onClick={() => selectAgent(agent)}
                  >
                    <div style={{ flex: 1 }}>
                      <div style={styles.agentCardTitle}>{agent.name}</div>
                      <div style={styles.agentCardRole}>{agent.role}</div>
                    </div>
                    <button 
                      style={styles.deleteBtn}
                      onClick={(e) => handleDeleteAgent(e, agent.id)}
                    >
                      <Trash2 size={16} />
                    </button>
                  </div>
                ))
              )}
            </div>

            {/* Chat Interface */}
            <div style={styles.chatContainer}>
              {!selectedAgent ? (
                <div style={styles.emptyChat}>
                  <MessageCircle size={40} color="#E5E7EB" style={{ marginBottom: '12px' }} />
                  <p style={{ margin: 0, color: 'var(--color-text-muted)', fontSize: '14px' }}>
                    대화할 AI 에이전트를 선택해주세요.
                  </p>
                </div>
              ) : (
                <>
                  <div style={styles.chatHeader}>
                    <strong>{selectedAgent.name}</strong> 
                    <span style={{ fontSize: '12px', color: 'var(--color-text-muted)' }}>({selectedAgent.role})</span>
                  </div>
                  
                  <div style={styles.chatHistory}>
                    {chatHistory.length === 0 ? (
                      <div style={styles.emptyHistory}>
                        <p>대화 내역이 없습니다. 인사를 건네보세요!</p>
                      </div>
                    ) : (
                      chatHistory.map((msg, idx) => {
                        const isUser = msg.sender === 'USER';
                        return (
                          <div key={idx} style={{ ...styles.msgWrapper, justifyContent: isUser ? 'flex-end' : 'flex-start' }}>
                            <div style={{ ...styles.msgBubble, ...(isUser ? styles.msgUser : styles.msgAI) }}>
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
                      <div style={{ ...styles.msgWrapper, justifyContent: 'flex-start' }}>
                        <div style={{ ...styles.msgBubble, ...styles.msgAI, ...styles.typingIndicator }}>
                          <span className="dot"></span><span className="dot"></span><span className="dot"></span>
                        </div>
                      </div>
                    )}
                    <div ref={chatEndRef} />
                  </div>

                  <form onSubmit={sendMessage} style={styles.chatInputWrapper}>
                    <input 
                      type="text" 
                      className="input-field" 
                      style={styles.chatInput}
                      value={message}
                      onChange={(e) => setMessage(e.target.value)}
                      placeholder={`${selectedAgent.name}에게 메시지 보내기...`}
                      disabled={isTyping}
                    />
                    <button type="submit" className="btn-primary" style={styles.sendBtn} disabled={isTyping || !message.trim()}>
                      <Send size={18} />
                    </button>
                  </form>
                </>
              )}
            </div>

          </div>
        </div>
      </div>

      {/* Agent Creation Modal */}
      {showModal && (
        <div style={styles.modalOverlay}>
          <div className="glass-panel" style={styles.modalContent}>
            <div style={styles.modalHeader}>
              <h3 style={{ margin: 0 }}>새로운 AI 에이전트 생성</h3>
              <button style={styles.closeBtn} onClick={() => setShowModal(false)}><X size={20} /></button>
            </div>
            <form onSubmit={handleCreateAgent} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div>
                <label style={styles.label}>이름 (최대 30자)</label>
                <input type="text" className="input-field" maxLength="30" required value={newAgent.name} onChange={e => setNewAgent({...newAgent, name: e.target.value})} placeholder="예: 츤데레 수학쌤" />
              </div>
              <div>
                <label style={styles.label}>역할 (최대 50자)</label>
                <input type="text" className="input-field" maxLength="50" required value={newAgent.role} onChange={e => setNewAgent({...newAgent, role: e.target.value})} placeholder="예: 학습 도우미" />
              </div>
              <div>
                <label style={styles.label}>성격/특징 (최소 5자, 최대 1000자)</label>
                <textarea className="input-field" style={{ height: '80px', paddingTop: '10px', resize: 'none' }} minLength="5" maxLength="1000" required value={newAgent.persona} onChange={e => setNewAgent({...newAgent, persona: e.target.value})} placeholder="예: 까칠하지만 핵심을 잘 짚어줌" />
              </div>
              <div>
                <label style={styles.label}>말투</label>
                <input type="text" className="input-field" value={newAgent.tone} onChange={e => setNewAgent({...newAgent, tone: e.target.value})} />
              </div>
              <div>
                <label style={styles.label}>목표</label>
                <input type="text" className="input-field" value={newAgent.goal} onChange={e => setNewAgent({...newAgent, goal: e.target.value})} />
              </div>
              <button type="submit" className="btn-primary" style={{ marginTop: '8px' }}>에이전트 생성하기</button>
            </form>
          </div>
        </div>
      )}

      {/* Typing Animation CSS */}
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

const styles = {
  container: {
    width: '100%',
    maxWidth: '1280px',
    margin: '0 auto',
    padding: '24px',
    boxSizing: 'border-box',
  },
  layout: {
    display: 'flex',
    gap: '24px',
    flexWrap: 'wrap',
  },
  leftPane: {
    flex: '1 1 400px',
    display: 'flex',
    flexDirection: 'column',
    gap: '24px',
  },
  rightPane: {
    flex: '1 1 600px',
    display: 'flex',
    flexDirection: 'column',
  },
  placeholderCard: {
    padding: '40px',
    backgroundColor: 'var(--color-bg-base)',
    borderRadius: '8px',
    border: '1px dashed var(--color-border)',
    textAlign: 'center',
  },
  aiPanel: {
    display: 'flex',
    flexDirection: 'column',
    height: '700px',
    padding: '20px',
  },
  agentHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '16px',
  },
  createBtn: {
    width: 'auto',
    height: '32px',
    padding: '0 12px',
    fontSize: '12px',
    display: 'flex',
    alignItems: 'center',
    gap: '4px',
  },
  agentList: {
    display: 'flex',
    gap: '12px',
    overflowX: 'auto',
    paddingBottom: '12px',
    marginBottom: '8px',
    borderBottom: '1px solid var(--color-border)',
  },
  agentCard: {
    minWidth: '200px',
    padding: '12px',
    borderRadius: '10px',
    border: '1px solid var(--color-border)',
    backgroundColor: 'var(--color-bg-base)',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'flex-start',
    gap: '8px',
    transition: 'all 0.2s ease',
  },
  agentCardActive: {
    borderColor: 'var(--color-primary)',
    backgroundColor: '#F0FDF4', // 연두색 아주 옅은 배경
    boxShadow: '0 2px 8px rgba(96, 201, 90, 0.15)',
  },
  agentCardTitle: {
    fontWeight: 'bold',
    fontSize: '14px',
    color: 'var(--color-text-main)',
    marginBottom: '2px',
  },
  agentCardRole: {
    fontSize: '12px',
    color: 'var(--color-text-muted)',
  },
  deleteBtn: {
    background: 'none',
    border: 'none',
    color: '#9CA3AF',
    cursor: 'pointer',
    padding: '4px',
  },
  chatContainer: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    backgroundColor: 'var(--color-bg-base)',
    borderRadius: '12px',
    overflow: 'hidden',
    marginTop: '8px',
  },
  emptyChat: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    justifyContent: 'center',
    alignItems: 'center',
  },
  chatHeader: {
    padding: '12px 16px',
    backgroundColor: 'white',
    borderBottom: '1px solid var(--color-border)',
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  },
  chatHistory: {
    flex: 1,
    padding: '20px',
    overflowY: 'auto',
    display: 'flex',
    flexDirection: 'column',
    gap: '16px',
  },
  emptyHistory: {
    textAlign: 'center',
    color: 'var(--color-text-muted)',
    fontSize: '13px',
    marginTop: '40px',
  },
  msgWrapper: {
    display: 'flex',
    flexDirection: 'column',
    maxWidth: '80%',
  },
  msgBubble: {
    padding: '10px 14px',
    borderRadius: '14px',
    fontSize: '14px',
    lineHeight: '1.4',
    wordBreak: 'break-word',
  },
  msgUser: {
    backgroundColor: 'var(--color-primary)',
    color: 'white',
    borderBottomRightRadius: '4px',
    alignSelf: 'flex-end',
  },
  msgAI: {
    backgroundColor: 'white',
    color: 'var(--color-text-main)',
    border: '1px solid var(--color-border)',
    borderBottomLeftRadius: '4px',
    alignSelf: 'flex-start',
  },
  typingIndicator: {
    padding: '8px 14px',
    display: 'flex',
    alignItems: 'center',
    minHeight: '20px',
  },
  chatInputWrapper: {
    padding: '16px',
    backgroundColor: 'white',
    borderTop: '1px solid var(--color-border)',
    display: 'flex',
    gap: '8px',
  },
  chatInput: {
    flex: 1,
    borderRadius: '20px',
    paddingLeft: '16px',
  },
  sendBtn: {
    width: '40px',
    height: '40px',
    borderRadius: '50%',
    padding: 0,
    flexShrink: 0,
  },
  modalOverlay: {
    position: 'fixed',
    top: 0, left: 0, right: 0, bottom: 0,
    backgroundColor: 'rgba(0,0,0,0.5)',
    display: 'flex',
    justifyContent: 'center',
    alignItems: 'center',
    zIndex: 9999,
  },
  modalContent: {
    width: '100%',
    maxWidth: '460px',
    padding: '24px',
  },
  modalHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '20px',
  },
  closeBtn: {
    background: 'none',
    border: 'none',
    cursor: 'pointer',
    color: 'var(--color-text-muted)',
  },
  label: {
    display: 'block',
    fontSize: '13px',
    fontWeight: '600',
    color: 'var(--color-text-main)',
    marginBottom: '6px',
  }
};