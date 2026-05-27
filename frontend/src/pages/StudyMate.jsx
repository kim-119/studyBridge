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
  
  // 멀티 에이전트 동적 추가를 위해 상태를 배열로 정의
  const [createdAgents, setCreatedAgents] = useState([{ ...DEFAULT_AGENT }]);
  const [roomName, setRoomName] = useState('');

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

  const handleOpenModal = () => {
    setCreatedAgents([{ ...DEFAULT_AGENT }]);
    setRoomName('');
    setShowModal(true);
  };

  const handleCreateAgent = async (e) => {
    e.preventDefault();
    if (agents.length >= 3) {
      alert('생성된 학습방은 최대 3개까지 가질 수 있습니다.');
      return;
    }

    for (const agent of createdAgents) {
      if (!agent.name.trim() || !agent.role.trim()) {
        alert('모든 에이전트의 이름과 역할을 입력해야 합니다.');
        return;
      }
      if (agent.customInstruction && agent.customInstruction.trim().length < 5 && agent.customInstruction.trim().length > 0) {
        alert('에이전트 설명 또는 추가 요구사항은 공백이거나 최소 5자 이상이어야 합니다.');
        return;
      }
    }

    const payloadAgents = createdAgents.map(agent => buildCanonicalAgentPayload(agent));
    const finalRoomName = roomName.trim() || createdAgents.map(a => a.name.trim()).join(' & ') + '의 그룹 스터디';

    const payload = {
      roomName: finalRoomName,
      agents: payloadAgents
    };

    try {
      console.debug('[StudyMate] create agent room payload', payload);
      await agentService.createAgent(userId, payload);
      setShowModal(false);
      setCreatedAgents([{ ...DEFAULT_AGENT }]);
      setRoomName('');
      await loadAgents();
    } catch (err) {
      console.error('에이전트 스터디방 생성 실패:', err);
      alert(err.message || '에이전트 스터디방 생성에 실패했습니다.');
    }
  };

  const handleDeleteAgent = async (e, agentId) => {
    e.stopPropagation();
    if (!window.confirm('정말 이 에이전트 스터디방을 삭제하시겠습니까? 모든 대화 내용이 완전히 삭제됩니다.')) return;

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
      
      if (res.replies && res.replies.length > 0) {
        const newMsgs = res.replies.map((reply, index) => ({
          id: Date.now() + 1 + index,
          content: reply.answer || reply.content,
          sender: 'AI',
          senderName: reply.agentName || reply.agent_name,
          agentId: reply.agentId,
          createdAt: new Date().toISOString()
        }));
        setChatHistory((prev) => [...prev, ...newMsgs]);
      } else {
        const aiMsg = {
          id: Date.now() + 1,
          content: res.answer,
          sender: 'AI',
          senderName: selectedAgent.name,
          createdAt: new Date().toISOString()
        };
        setChatHistory((prev) => [...prev, aiMsg]);
      }
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
              onClick={handleOpenModal}
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
                      borderWidth: '1px',
                      borderStyle: 'solid',
                      borderColor: isActive ? 'var(--color-primary)' : 'var(--color-border)',
                      backgroundColor: isActive ? 'rgba(96, 201, 90, 0.05)' : 'var(--color-bg-base)',
                      boxShadow: isActive ? '0 2px 8px rgba(96, 201, 90, 0.1)' : 'none',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: '12px',
                      transition: 'all 0.2s ease'
                    }}
                    onClick={() => selectAgent(agent)}
                  >
                    <div className="avatar" style={{ backgroundColor: avatarColor.bg, color: avatarColor.text }}>
                      {(agent.roomName || agent.name)?.charAt(0)}
                    </div>

                    <div style={{ flex: 1, overflow: 'hidden' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                        <div style={{ fontWeight: 'bold', fontSize: '15px', color: 'var(--color-text-main)', marginBottom: '4px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {agent.roomName || agent.name}
                        </div>
                        <button
                          style={{ background: 'none', border: 'none', color: '#D1D5DB', cursor: 'pointer', padding: '2px' }}
                          onClick={(e) => handleDeleteAgent(e, agentId)}
                          aria-label="에이전트 삭제"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                      <div style={{ marginBottom: '6px', display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                        {agent.agents && agent.agents.length > 0 ? (
                          agent.agents.map((ag, idx) => (
                            <span key={idx} className="tag">#{ag.name}</span>
                          ))
                        ) : (
                          <>
                            <span className="tag">#{agent.role}</span>
                            <span className="tag">#{knowledgeLevel}</span>
                            <span className="tag">#{personality}</span>
                          </>
                        )}
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
              <div className="chat-header" style={{ paddingBottom: '16px', borderBottom: '1px solid var(--color-border)' }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <div className="avatar-sm" style={{ backgroundColor: 'var(--color-primary)', color: 'white', fontWeight: 'bold' }}>
                      {(selectedAgent.roomName || selectedAgent.name)?.charAt(0)}
                    </div>
                    <div>
                      <div style={{ fontWeight: 'bold', fontSize: '16px', color: 'var(--color-text-main)' }}>
                        {selectedAgent.roomName || `${selectedAgent.name}의 그룹 스터디`}
                      </div>
                    </div>
                  </div>
                  
                  {/* 스터디방 에이전트 목록 표시 */}
                  {selectedAgent.agents && selectedAgent.agents.length > 0 && (
                    <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginTop: '2px' }}>
                      {selectedAgent.agents.map((ag, idx) => {
                        const avatarColor = getAvatarColor(idx);
                        return (
                          <div
                            key={ag.id || idx}
                            style={{
                              display: 'flex',
                              alignItems: 'center',
                              gap: '6px',
                              padding: '4px 10px',
                              backgroundColor: 'rgba(96, 201, 90, 0.04)',
                              border: '1px solid rgba(96, 201, 90, 0.15)',
                              borderRadius: '16px',
                              fontSize: '11px',
                              color: 'var(--color-text-main)'
                            }}
                          >
                            <span
                              style={{
                                display: 'inline-block',
                                width: '6px',
                                height: '6px',
                                borderRadius: '50%',
                                backgroundColor: avatarColor.text
                              }}
                            />
                            <span style={{ fontWeight: '600' }}>{ag.name}</span>
                            <span style={{ color: 'var(--color-text-muted)', fontSize: '10px' }}>({ag.role})</span>
                          </div>
                        );
                      })}
                    </div>
                  )}
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
                    const senderName = isUser ? '나' : (msg.senderName || msg.sender_name || selectedAgent.name);
                    
                    return (
                      <div key={msg.id || idx} className={`chat-bubble-container ${isUser ? 'user' : 'ai'}`}>
                        <div className="chat-bubble-sender">{senderName}</div>
                        <div className={`chat-bubble ${isUser ? 'user' : 'ai'}`} style={{ whiteSpace: 'pre-wrap' }}>
                          {msg.content}
                        </div>
                        <div className="chat-bubble-time">
                          {formatTime(msg.createdAt)}
                        </div>
                      </div>
                    );
                  })
                )}
                {isTyping && (
                  <div className="chat-bubble-container ai">
                    <div className="chat-bubble-sender">AI 에이전트들이 검토 중...</div>
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
                  placeholder="메시지를 입력해보세요..."
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
          <div className="glass-panel modal-content" style={{ width: '95%', maxWidth: '600px', maxHeight: '85vh', overflow: 'hidden' }}>
            <div className="modal-header">
              <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '8px' }}>
                <Sparkles size={20} color="var(--color-primary)" /> 새 AI 그룹 스터디 생성
              </h3>
              <button style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-text-muted)' }} onClick={() => setShowModal(false)} aria-label="닫기"><X size={20} /></button>
            </div>
            
            <form onSubmit={handleCreateAgent} style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
              <div style={{ flex: 1, overflowY: 'auto', paddingRight: '4px', display: 'flex', flexDirection: 'column', gap: '16px', marginBottom: '16px' }}>
                
                {/* 스터디방 이름 설정 */}
                <div>
                  <label style={{ display: 'block', fontSize: '13px', fontWeight: '700', color: 'var(--color-text-main)', marginBottom: '6px' }}>
                    그룹 스터디방 이름
                  </label>
                  <input
                    type="text"
                    className="input-field"
                    maxLength="50"
                    value={roomName}
                    onChange={(e) => setRoomName(e.target.value)}
                    placeholder={roomName ? "" : createdAgents.map(a => a.name.trim() || '새 에이전트').join(' & ') + '의 그룹 스터디'}
                  />
                </div>

                <div className="divider" style={{ margin: '8px 0' }} />

                {/* 에이전트 동적 폼 리스트 */}
                {createdAgents.map((agent, index) => (
                  <div
                    key={index}
                    style={{
                      border: '1px solid var(--color-border)',
                      borderRadius: '12px',
                      padding: '16px',
                      backgroundColor: 'rgba(249, 250, 251, 0.7)',
                      position: 'relative',
                      display: 'flex',
                      flexDirection: 'column',
                      gap: '12px'
                    }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <h4 style={{ margin: 0, color: 'var(--color-primary)', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '14px', fontWeight: '700' }}>
                        <Bot size={18} /> AI 학습메이트 #{index + 1}
                      </h4>
                      {createdAgents.length > 1 && (
                        <button
                          type="button"
                          style={{
                            background: 'none',
                            border: 'none',
                            color: '#EF4444',
                            cursor: 'pointer',
                            fontSize: '12px',
                            fontWeight: '600',
                            display: 'flex',
                            alignItems: 'center',
                            gap: '4px'
                          }}
                          onClick={() => {
                            setCreatedAgents(createdAgents.filter((_, i) => i !== index));
                          }}
                        >
                          <X size={14} /> 제거
                        </button>
                      )}
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                      <div>
                        <label style={{ display: 'block', fontSize: '12px', fontWeight: '600', color: 'var(--color-text-main)', marginBottom: '4px' }}>이름</label>
                        <input
                          type="text"
                          className="input-field"
                          maxLength="30"
                          required
                          value={agent.name}
                          onChange={(e) => {
                            const list = [...createdAgents];
                            list[index].name = e.target.value;
                            setCreatedAgents(list);
                          }}
                          placeholder="예: 김도끼"
                        />
                      </div>
                      <div>
                        <label style={{ display: 'block', fontSize: '12px', fontWeight: '600', color: 'var(--color-text-main)', marginBottom: '4px' }}>역할</label>
                        <input
                          type="text"
                          className="input-field"
                          maxLength="20"
                          required
                          value={agent.role}
                          onChange={(e) => {
                            const list = [...createdAgents];
                            list[index].role = e.target.value;
                            setCreatedAgents(list);
                          }}
                          placeholder="예: 자바 전공교수"
                        />
                      </div>
                    </div>

                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                      <div>
                        <label style={{ display: 'block', fontSize: '12px', fontWeight: '600', color: 'var(--color-text-main)', marginBottom: '4px' }}>성격/말투</label>
                        <select
                          className="input-field"
                          value={agent.personality}
                          onChange={(e) => {
                            const list = [...createdAgents];
                            list[index].personality = e.target.value;
                            setCreatedAgents(list);
                          }}
                        >
                          {PERSONALITY_OPTIONS.map((option) => <option key={option} value={option}>{option}</option>)}
                        </select>
                      </div>
                      <div>
                        <label style={{ display: 'block', fontSize: '12px', fontWeight: '600', color: 'var(--color-text-main)', marginBottom: '4px' }}>지식수준</label>
                        <select
                          className="input-field"
                          value={agent.knowledgeLevel}
                          onChange={(e) => {
                            const list = [...createdAgents];
                            list[index].knowledgeLevel = e.target.value;
                            setCreatedAgents(list);
                          }}
                        >
                          {KNOWLEDGE_LEVEL_OPTIONS.map((option) => <option key={option} value={option}>{option}</option>)}
                        </select>
                      </div>
                    </div>

                    <div>
                      <label style={{ display: 'block', fontSize: '12px', fontWeight: '600', color: 'var(--color-text-main)', marginBottom: '4px' }}>목표</label>
                      <input
                        type="text"
                        className="input-field"
                        maxLength="100"
                        value={agent.goal}
                        onChange={(e) => {
                          const list = [...createdAgents];
                          list[index].goal = e.target.value;
                          setCreatedAgents(list);
                        }}
                        placeholder="예: 자바 개념에 대해 알기 쉽게 설명하기"
                      />
                    </div>

                    <div>
                      <label style={{ display: 'block', fontSize: '12px', fontWeight: '600', color: 'var(--color-text-main)', marginBottom: '4px' }}>사용자 추가 요구사항</label>
                      <textarea
                        className="input-field"
                        style={{ height: '50px', paddingTop: '6px', resize: 'none' }}
                        maxLength="1000"
                        value={agent.customInstruction}
                        onChange={(e) => {
                          const list = [...createdAgents];
                          list[index].customInstruction = e.target.value;
                          setCreatedAgents(list);
                        }}
                        placeholder="예: 원어민처럼 영어로만 답변해줘"
                      />
                    </div>
                  </div>
                ))}

                {/* 에이전트 동적 추가 버튼 */}
                {createdAgents.length < 3 && (
                  <button
                    type="button"
                    className="btn-outline"
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      gap: '6px',
                      width: '100%',
                      padding: '10px',
                      borderRadius: '8px',
                      fontSize: '13px',
                      fontWeight: '600',
                      borderStyle: 'dashed'
                    }}
                    onClick={() => setCreatedAgents([...createdAgents, { ...DEFAULT_AGENT }])}
                  >
                    <Plus size={16} /> AI 학습메이트 추가 ({createdAgents.length}/3)
                  </button>
                )}
              </div>

              <div style={{ display: 'flex', gap: '10px', marginTop: 'auto', paddingTop: '10px', borderTop: '1px solid var(--color-border)' }}>
                <button
                  type="button"
                  className="btn-outline"
                  style={{ flex: 1 }}
                  onClick={() => setShowModal(false)}
                >
                  취소
                </button>
                <button
                  type="submit"
                  className="btn-primary"
                  style={{ flex: 2 }}
                >
                  스터디방 생성하기
                </button>
              </div>
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
