import React, { useEffect, useRef, useState } from 'react';
import { useAuth } from '../hooks/useAuth';
import { agentService } from '../services/api';
import { AlertCircle, Bot, Plus, Send, Sparkles, Trash2, X } from 'lucide-react';

const PERSONALITY_OPTIONS = ['전문적', '친근함', '솔직함', '독특함', '효율적', '냉소적'];
const KNOWLEDGE_LEVEL_OPTIONS = ['입문 수준', '학사 수준', '석사 수준', '박사 수준', '전문가 수준'];

const DEFAULT_AGENT = {
  name: '',
  role: '',
  personality: '전문적',
  knowledgeLevel: '학사 수준',
  customInstruction: '',
  goal: '사용자의 학습을 돕는다'
};

const parsePersonaTag = (persona, tagName) => {
  const match = String(persona || '').match(new RegExp(`\\[${tagName}:\\s*([^\\]]+)\\]`));
  return match ? match[1].trim() : '';
};

const getAgentId = (agent) => agent?.id ?? agent?.agentId;

const getAgentKnowledgeLevel = (agent) => {
  return agent?.knowledgeLevel
    || agent?.knowledge_level
    || parsePersonaTag(agent?.persona, '지식수준')
    || '학사 수준';
};

const getAgentPersonality = (agent) => {
  return agent?.personality
    || agent?.style
    || agent?.tone
    || parsePersonaTag(agent?.persona, '성격')
    || '전문적';
};

const buildCanonicalAgentPayload = (agent) => {
  const personality = PERSONALITY_OPTIONS.includes(agent.personality) ? agent.personality : '전문적';
  const knowledgeLevel = KNOWLEDGE_LEVEL_OPTIONS.includes(agent.knowledgeLevel) ? agent.knowledgeLevel : '학사 수준';
  const customInstruction = String(agent.customInstruction || '').trim();
  const goal = String(agent.goal || '사용자의 학습을 돕는다').trim();
  const personaBody = customInstruction || goal;

  return {
    name: String(agent.name || '').trim(),
    role: String(agent.role || '').trim(),
    personality,
    style: personality,
    tone: personality,
    knowledgeLevel,
    knowledge_level: knowledgeLevel,
    goal,
    customInstruction,
    custom_instruction: customInstruction,
    persona: `[지식수준: ${knowledgeLevel}] [성격: ${personality}] ${personaBody}`
  };
};

export default function StudyMate() {
  const { userId } = useAuth();

  const [agents, setAgents] = useState([]);
  const [selectedAgent, setSelectedAgent] = useState(null);
  const [chatHistory, setChatHistory] = useState([]);
  const [message, setMessage] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [newAgent, setNewAgent] = useState(DEFAULT_AGENT);

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
      alert('AI 에이전트는 최대 3개까지 생성할 수 있습니다.');
      return;
    }

    const payload = buildCanonicalAgentPayload(newAgent);
    if (!payload.name || !payload.role) {
      alert('이름과 역할을 입력해야 합니다.');
      return;
    }

    if (payload.persona.length < 5) {
      alert('에이전트 설명 또는 추가 요구사항을 최소 5자 이상 입력해야 합니다.');
      return;
    }

    try {
      console.debug('[StudyMate] create agent payload', payload);
      await agentService.createAgent(userId, payload);
      setShowModal(false);
      setNewAgent(DEFAULT_AGENT);
      await loadAgents();
    } catch (err) {
      console.error('에이전트 생성 실패:', err);
      alert(err.message || '에이전트 생성에 실패했습니다.');
    }
  };

  const handleDeleteAgent = async (e, agentId) => {
    e.stopPropagation();
    if (!window.confirm('정말 이 에이전트를 삭제하시겠습니까? 대화 내용도 함께 삭제될 수 있습니다.')) return;

    try {
      await agentService.deleteAgent(userId, agentId);
      if (getAgentId(selectedAgent) === agentId) {
        setSelectedAgent(null);
        setChatHistory([]);
      }
      await loadAgents();
    } catch (err) {
      console.error('에이전트 삭제 실패:', err);
      alert('삭제에 실패했습니다.');
    }
  };

  const selectAgent = async (agent) => {
    const agentId = getAgentId(agent);
    setSelectedAgent(agent);
    console.debug('[StudyMate] selected agent', agent);

    try {
      const history = await agentService.getChatHistory(userId, agentId);
      setChatHistory(history || []);
    } catch (err) {
      console.error('채팅 이력 조회 실패:', err);
      setChatHistory([]);
    }
  };

  const sendMessage = async (e) => {
    e.preventDefault();
    if (!message.trim() || !selectedAgent || isTyping) return;

    const agentId = getAgentId(selectedAgent);
    const inputMsg = message.trim();
    const userMsg = {
      id: Date.now(),
      content: inputMsg,
      sender: 'USER',
      createdAt: new Date().toISOString()
    };

    setChatHistory((prev) => [...prev, userMsg]);
    setMessage('');
    setIsTyping(true);

    try {
      console.debug('[StudyMate] chat request', {
        userId,
        agentId,
        message: inputMsg,
        selectedAgent
      });
      const res = await agentService.sendMessage(userId, agentId, inputMsg);
      console.debug('[StudyMate] chat response', res);
      const aiMsg = {
        id: Date.now() + 1,
        content: res.answer,
        sender: 'AI',
        createdAt: new Date().toISOString()
      };
      setChatHistory((prev) => [...prev, aiMsg]);
    } catch (err) {
      console.error('메시지 전송 실패:', err);
      alert('메시지 전송에 실패했습니다.');
      setChatHistory((prev) => prev.filter((m) => m.id !== userMsg.id));
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
      { bg: '#FFF3E0', text: '#E65100' }
    ];
    return colors[index % colors.length];
  };

  if (!userId) {
    return (
      <div className="container-main">
        <div className="glass-panel empty-state" style={{ padding: '40px' }}>
          <AlertCircle size={48} color="var(--color-text-muted)" style={{ margin: '0 auto 16px' }} />
          <h3>로그인이 필요합니다</h3>
          <p style={{ color: 'var(--color-text-muted)' }}>AI 학습메이트 기능은 로그인 후 사용할 수 있습니다.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="container-main">
      <div className="layout-split">
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
              <Plus size={16} /> 생성 ({agents.length}/3)
            </button>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', overflowY: 'auto', paddingRight: '4px' }}>
            {agents.length === 0 ? (
              <div className="empty-state" style={{ padding: '40px 0' }}>
                <p>생성된 에이전트가 없습니다.</p>
                <p style={{ fontSize: '12px' }}>학습 목적에 맞는 AI 에이전트를 만들어보세요.</p>
              </div>
            ) : (
              agents.map((agent, index) => {
                const agentId = getAgentId(agent);
                const isActive = getAgentId(selectedAgent) === agentId;
                const avatarColor = getAvatarColor(index);
                const knowledgeLevel = getAgentKnowledgeLevel(agent);
                const personality = getAgentPersonality(agent);

                return (
                  <div
                    key={agentId}
                    style={{
                      padding: '16px',
                      borderRadius: '12px',
                      border: '1px solid var(--color-border)',
                      backgroundColor: 'var(--color-bg-base)',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: '12px',
                      transition: 'all 0.2s ease',
                      ...(isActive ? { borderColor: 'var(--color-primary)', backgroundColor: 'rgba(96, 201, 90, 0.05)', boxShadow: '0 2px 8px rgba(96, 201, 90, 0.1)' } : {})
                    }}
                    onClick={() => selectAgent(agent)}
                  >
                    <div className="avatar" style={{ backgroundColor: avatarColor.bg, color: avatarColor.text }}>
                      {agent.name?.charAt(0)}
                    </div>

                    <div style={{ flex: 1, overflow: 'hidden' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                        <div style={{ fontWeight: 'bold', fontSize: '15px', color: 'var(--color-text-main)', marginBottom: '4px' }}>{agent.name}</div>
                        <button
                          style={{ background: 'none', border: 'none', color: '#D1D5DB', cursor: 'pointer', padding: '2px' }}
                          onClick={(e) => handleDeleteAgent(e, agentId)}
                          aria-label="에이전트 삭제"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                      <div style={{ marginBottom: '6px', display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                        <span className="tag">#{agent.role}</span>
                        <span className="tag">#{knowledgeLevel}</span>
                        <span className="tag">#{personality}</span>
                      </div>
                      <div style={{ fontSize: '12px', color: 'var(--color-text-muted)', lineHeight: '1.4' }}>
                        {String(agent.persona || agent.goal || '').length > 35
                          ? `${String(agent.persona || agent.goal || '').substring(0, 35)}...`
                          : String(agent.persona || agent.goal || '')}
                      </div>
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>

        <div className="glass-panel layout-pane-right animate-fade-in">
          {!selectedAgent ? (
            <div className="empty-state">
              <Bot size={50} color="#E5E7EB" style={{ marginBottom: '16px' }} />
              <h3 style={{ margin: '0 0 8px 0', color: 'var(--color-text-main)' }}>AI 학습메이트</h3>
              <p style={{ margin: 0, color: 'var(--color-text-muted)', fontSize: '14px' }}>
                왼쪽에서 대화할 에이전트를 선택하거나 새로 생성하세요.
              </p>
            </div>
          ) : (
            <div className="chat-container">
              <div className="chat-header">
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <div className="avatar-sm" style={{ backgroundColor: 'var(--color-primary)', color: 'white' }}>
                    {selectedAgent.name?.charAt(0)}
                  </div>
                  <div>
                    <div style={{ fontWeight: 'bold', fontSize: '15px' }}>{selectedAgent.name}</div>
                    <div style={{ fontSize: '12px', color: 'var(--color-text-muted)' }}>
                      {selectedAgent.role} · {getAgentKnowledgeLevel(selectedAgent)} · {getAgentPersonality(selectedAgent)}
                    </div>
                  </div>
                </div>
              </div>

              <div className="chat-history">
                {chatHistory.length === 0 ? (
                  <div className="empty-state" style={{ marginTop: '40px' }}>
                    <p>대화 이력이 없습니다. 질문을 입력해보세요.</p>
                  </div>
                ) : (
                  chatHistory.map((msg, idx) => {
                    const isUser = msg.sender === 'USER';
                    return (
                      <div key={msg.id || idx} style={{ display: 'flex', flexDirection: 'column', maxWidth: '75%', alignSelf: isUser ? 'flex-end' : 'flex-start' }}>
                        <div className={`chat-bubble ${isUser ? 'user' : 'ai'}`}>{msg.content}</div>
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

      {showModal && (
        <div className="modal-overlay">
          <div className="glass-panel modal-content">
            <div className="modal-header">
              <h3 style={{ margin: 0 }}>새 AI 에이전트 생성</h3>
              <button style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-text-muted)' }} onClick={() => setShowModal(false)} aria-label="닫기"><X size={20} /></button>
            </div>
            <form onSubmit={handleCreateAgent} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '13px', fontWeight: '600', color: 'var(--color-text-main)', marginBottom: '6px' }}>이름</label>
                <input type="text" className="input-field" maxLength="30" required value={newAgent.name} onChange={(e) => setNewAgent({ ...newAgent, name: e.target.value })} placeholder="예: 영어 선생님" />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '13px', fontWeight: '600', color: 'var(--color-text-main)', marginBottom: '6px' }}>역할</label>
                <input type="text" className="input-field" maxLength="20" required value={newAgent.role} onChange={(e) => setNewAgent({ ...newAgent, role: e.target.value })} placeholder="예: 학습 도우미" />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '13px', fontWeight: '600', color: 'var(--color-text-main)', marginBottom: '6px' }}>성격/말투</label>
                <select className="input-field" value={newAgent.personality} onChange={(e) => setNewAgent({ ...newAgent, personality: e.target.value })}>
                  {PERSONALITY_OPTIONS.map((option) => <option key={option} value={option}>{option}</option>)}
                </select>
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '13px', fontWeight: '600', color: 'var(--color-text-main)', marginBottom: '6px' }}>지식수준</label>
                <select className="input-field" value={newAgent.knowledgeLevel} onChange={(e) => setNewAgent({ ...newAgent, knowledgeLevel: e.target.value })}>
                  {KNOWLEDGE_LEVEL_OPTIONS.map((option) => <option key={option} value={option}>{option}</option>)}
                </select>
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '13px', fontWeight: '600', color: 'var(--color-text-main)', marginBottom: '6px' }}>목표</label>
                <input type="text" className="input-field" maxLength="100" value={newAgent.goal} onChange={(e) => setNewAgent({ ...newAgent, goal: e.target.value })} placeholder="예: 사용자가 알기 쉽게 설명하기" />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '13px', fontWeight: '600', color: 'var(--color-text-main)', marginBottom: '6px' }}>사용자 추가 요구사항</label>
                <textarea className="input-field" style={{ height: '80px', paddingTop: '10px', resize: 'none' }} maxLength="1000" value={newAgent.customInstruction} onChange={(e) => setNewAgent({ ...newAgent, customInstruction: e.target.value })} placeholder="예: 원어민 선생님처럼 영어로 대답해" />
              </div>
              <button type="submit" className="btn-primary" style={{ marginTop: '8px' }}>에이전트 생성하기</button>
            </form>
          </div>
        </div>
      )}

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
