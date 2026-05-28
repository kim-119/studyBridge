import React, { useEffect, useRef, useState } from 'react';
import { useAuth } from '../hooks/useAuth';
import { agentService } from '../services/api';
import { AlertCircle, Bot, Plus, Send, Sparkles, Trash2, X, Info } from 'lucide-react';

const PERSONALITY_OPTIONS = ['전문적', '친근함', '솔직함', '독특함', '효율적', '냉소적'];
const PERSONALITY_STRENGTH_OPTIONS = [
  { value: 'medium', label: '보통' },
  { value: 'high', label: '강함' },
  { value: 'extreme', label: '매우 강함' },
];
const PERSONALITY_STRENGTH_LABELS = {
  low: '낮음',
  medium: '보통',
  high: '강함',
  extreme: '매우 강함',
};
const PERSONALITY_DESCRIPTIONS = {
  '전문적': '정제되어 있고 정확함',
  '친근함': '따뜻하고 수다스러움',
  '솔직함': '직설적이면서도 객관적',
  '독특함': '유쾌하고 상상력이 풍부함',
  '효율적': '간결하고 꾸밈없음',
  '냉소적': '비꼬면서 비판적임',
};
const KNOWLEDGE_LEVEL_OPTIONS = ['입문 수준', '학사 수준', '석사 수준', '박사 수준', '전문가 수준'];

const DEFAULT_AGENT = {
  name: '',
  role: '',
  personality: '전문적',
  personalityStrength: 'extreme',
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

const getAgentPersonalityStrength = (agent) => {
  const raw = agent?.personalityStrength
    || agent?.personality_strength
    || parsePersonaTag(agent?.persona, '성격강도')
    || 'extreme';
  return ['low', 'medium', 'high', 'extreme'].includes(raw) ? raw : 'extreme';
};

const getPersonalityStrengthLabel = (strength) => (
  PERSONALITY_STRENGTH_LABELS[strength] || PERSONALITY_STRENGTH_LABELS.extreme
);

const sanitizeCustomInstruction = (value) => {
  return String(value || '')
    .replace(/\[[^\]]*지식수준[^\]]*\]/gi, '')
    .replace(/\[[^\]]*knowledge\s*level[^\]]*\]/gi, '')
    .replace(/\[[^\]]*성격[^\]]*\]/gi, '')
    .replace(/\[[^\]]*personality[^\]]*\]/gi, '')
    .replace(/\[[^\]]*tone[^\]]*\]/gi, '')
    .trim();
};

const buildDiscussionAgentsPayload = (selectedAgent) => {
  const sourceAgents = Array.isArray(selectedAgent?.agents) && selectedAgent.agents.length > 0
    ? selectedAgent.agents
    : selectedAgent
      ? [selectedAgent]
      : [];

  return sourceAgents.map((agent, index) => {
    const personality = getAgentPersonality(agent);
    const personalityStrength = getAgentPersonalityStrength(agent);
    const knowledgeLevel = getAgentKnowledgeLevel(agent);
    const customInstruction = sanitizeCustomInstruction(
      agent?.customInstruction || agent?.custom_instruction || agent?.persona || ''
    );

    return {
      agentId: String(agent?.id || agent?.agentId || index + 1),
      name: agent?.name || `AI 도우미 ${index + 1}`,
      role: agent?.role || 'AI 학습 도우미',
      personality,
      personalityStrength,
      personality_strength: personalityStrength,
      style: personality,
      tone: personality,
      knowledgeLevel,
      knowledge_level: knowledgeLevel,
      customInstruction,
      custom_instruction: customInstruction,
      persona: agent?.persona || ''
    };
  });
};

const getAgentStyleTheme = (personality) => {
  const normalized = String(personality || '').trim();
  switch (normalized) {
    case '전문적':
      return {
        bg: 'rgba(219, 234, 254, 0.35)',
        border: 'none',
        text: 'var(--color-text-main)',
        icon: '🎓',
        tagBg: '#DBEAFE',
        accent: '#2563EB'
      };
    case '친근함':
      return {
        bg: 'rgba(254, 215, 170, 0.35)',
        border: 'none',
        text: 'var(--color-text-main)',
        icon: '✨',
        tagBg: '#FFEDD5',
        accent: '#EA580C'
      };
    case '솔직함':
      return {
        bg: 'rgba(209, 250, 229, 0.35)',
        border: 'none',
        text: 'var(--color-text-main)',
        icon: '🎤',
        tagBg: '#D1FAE5',
        accent: '#059669'
      };
    case '독특함':
      return {
        bg: 'rgba(237, 233, 254, 0.35)',
        border: 'none',
        text: 'var(--color-text-main)',
        icon: '👽',
        tagBg: '#EDE9FE',
        accent: '#7C3AED'
      };
    case '효율적':
      return {
        bg: 'rgba(243, 244, 246, 0.65)',
        border: 'none',
        text: 'var(--color-text-main)',
        icon: '⏱️',
        tagBg: '#F3F4F6',
        accent: '#374151'
      };
    case '냉소적':
      return {
        bg: 'rgba(254, 228, 230, 0.35)',
        border: 'none',
        text: 'var(--color-text-main)',
        icon: '😈',
        tagBg: '#FFE4E6',
        accent: '#E11D48'
      };
    default:
      return {
        bg: 'rgba(243, 244, 246, 0.5)',
        border: 'none',
        text: 'var(--color-text-main)',
        icon: '🤖',
        tagBg: '#E5E7EB',
        accent: '#4B5563'
      };
  }
};

const buildCanonicalAgentPayload = (agent) => {
  const personality = PERSONALITY_OPTIONS.includes(agent.personality) ? agent.personality : '전문적';
  const personalityStrength = ['low', 'medium', 'high', 'extreme'].includes(agent.personalityStrength)
    ? agent.personalityStrength
    : 'extreme';
  const knowledgeLevel = KNOWLEDGE_LEVEL_OPTIONS.includes(agent.knowledgeLevel) ? agent.knowledgeLevel : '학사 수준';
  const customInstruction = String(agent.customInstruction || '').trim();
  const goal = String(agent.goal || '사용자의 학습을 돕는다').trim();
  const personaBody = customInstruction || goal;

  return {
    name: String(agent.name || '').trim(),
    role: String(agent.role || '').trim(),
    personality,
    personalityStrength,
    personality_strength: personalityStrength,
    style: personality,
    tone: personality,
    knowledgeLevel,
    knowledge_level: knowledgeLevel,
    goal,
    customInstruction,
    custom_instruction: customInstruction,
    persona: `[지식수준: ${knowledgeLevel}] [성격: ${personality}] [성격강도: ${personalityStrength}] ${personaBody}`
  };
};

const buildChatAgentSettingsPayload = (selectedAgent, inputMsg, agentId) => {
  const personality = getAgentPersonality(selectedAgent);
  const personalityStrength = getAgentPersonalityStrength(selectedAgent);
  const knowledgeLevel = getAgentKnowledgeLevel(selectedAgent);
  const customInstruction = sanitizeCustomInstruction(
    selectedAgent?.customInstruction
      || selectedAgent?.custom_instruction
      || selectedAgent?.persona
      || ''
  );
  const discussionAgents = buildDiscussionAgentsPayload(selectedAgent);

  return {
    message: inputMsg,
    agentId,
    roomId: agentId,
    // 항상 single_answer 모드로 전송:
    //   - multi_agent_discussion 모드는 FastAPI에서 3라운드×3명=9회 LLM 순차 호출 → 매우 느림
    //   - single_answer → FastAPI 기본 경로(병렬 for-loop) 실행 → 에이전트 N명 병렬 처리
    mode: 'single_answer',
    rounds: 1,
    showFinalSynthesis: false,
    agents: discussionAgents,
    personality,
    personalityStrength,
    personality_strength: personalityStrength,
    style: personality,
    tone: personality,
    knowledgeLevel,
    knowledge_level: knowledgeLevel,
    customInstruction,
    custom_instruction: customInstruction,
    persona: selectedAgent?.persona
      || `[지식수준: ${knowledgeLevel}] [성격: ${personality}] [성격강도: ${personalityStrength}] ${customInstruction}`,
  };
};

export default function StudyMate() {
  const { userId } = useAuth();

  const [agents, setAgents] = useState([]);
  const [selectedAgent, setSelectedAgent] = useState(null);
  const [chatHistory, setChatHistory] = useState([]);
  const [message, setMessage] = useState('');
  const [typingRoomId, setTypingRoomId] = useState(null);
  const [showModal, setShowModal] = useState(false);
  const [showDetailsModal, setShowDetailsModal] = useState(false);

  const selectedAgentIdRef = useRef(null);
  useEffect(() => {
    selectedAgentIdRef.current = getAgentId(selectedAgent);
  }, [selectedAgent]);

  // 멀티 에이전트 동적 추가를 위해 상태를 배열로 정의
  const [createdAgents, setCreatedAgents] = useState([{ ...DEFAULT_AGENT }]);
  const [roomName, setRoomName] = useState('');

  const chatEndRef = useRef(null);

  // ── localStorage 헬퍼 ──────────────────────────────────────────────────────
  const LS_AGENT_KEY = userId ? `sm_agent_${userId}` : null;
  const lsChatKey = (agentId) => userId ? `sm_chat_${userId}_${agentId}` : null;

  const saveAgentToStorage = (agentId) => {
    if (LS_AGENT_KEY) localStorage.setItem(LS_AGENT_KEY, String(agentId));
  };

  const saveChatToStorage = (agentId, history) => {
    const key = lsChatKey(agentId);
    if (key && history.length > 0) {
      try {
        localStorage.setItem(key, JSON.stringify(history.slice(-60)));
      } catch (e) { /* storage full 등 무시 */ }
    }
  };

  const loadChatFromStorage = (agentId) => {
    const key = lsChatKey(agentId);
    if (!key) return null;
    try {
      const raw = localStorage.getItem(key);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : null;
    } catch (e) { return null; }
  };

  // 채팅 기록 변경 시 localStorage 자동 저장
  useEffect(() => {
    if (selectedAgent && userId && chatHistory.length > 0) {
      saveChatToStorage(getAgentId(selectedAgent), chatHistory);
    }
  }, [chatHistory]); // eslint-disable-line react-hooks/exhaustive-deps

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
  }, [chatHistory, typingRoomId]);

  const loadAgents = async () => {
    try {
      const data = await agentService.getAgents(userId);
      const agentList = data || [];
      setAgents(agentList);

      // 이전에 선택했던 에이전트를 localStorage에서 복원
      if (!selectedAgent && LS_AGENT_KEY && agentList.length > 0) {
        const savedId = localStorage.getItem(LS_AGENT_KEY);
        if (savedId) {
          const restored = agentList.find(a => String(getAgentId(a)) === String(savedId));
          if (restored) {
            const agentId = getAgentId(restored);
            setSelectedAgent(restored);
            selectedAgentIdRef.current = agentId;

            // localStorage 캐시 즉시 표시
            const cached = loadChatFromStorage(agentId);
            if (cached && cached.length > 0) setChatHistory(cached);

            // 서버에서 최신 이력 로드
            try {
              const history = await agentService.getChatHistory(userId, agentId);
              if (history && history.length > 0) {
                setChatHistory(history);
              }
            } catch (e) { /* 캐시 사용 */ }
          }
        }
      }
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
      // localStorage 정리
      const chatKey = lsChatKey(agentId);
      if (chatKey) localStorage.removeItem(chatKey);
      if (getAgentId(selectedAgent) === agentId) {
        if (LS_AGENT_KEY) localStorage.removeItem(LS_AGENT_KEY);
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
    selectedAgentIdRef.current = agentId;
    saveAgentToStorage(agentId);

    // localStorage 캐시를 먼저 보여줘서 즉각적인 UI 피드백
    const cached = loadChatFromStorage(agentId);
    if (cached && cached.length > 0) setChatHistory(cached);
    else setChatHistory([]);

    // 서버에서 최신 이력 로드
    try {
      const history = await agentService.getChatHistory(userId, agentId);
      const hist = history || [];
      setChatHistory(hist);
    } catch (err) {
      console.error('채팅 이력 조회 실패:', err);
      // 캐시가 있으면 유지, 없으면 빈 배열
      if (!cached || cached.length === 0) setChatHistory([]);
    }
  };

  const detectTargetAgentId = (msg, agents) => {
    if (!msg || !agents || agents.length === 0) return null;
    const atMatch = msg.match(/@(\S+)/);
    if (atMatch) {
      const atName = atMatch[1].replace(/[^\w가-힣]/g, '').toLowerCase();
      const found = agents.find(a => {
        const n = (a.name || '').replace(/[^\w가-힣]/g, '').toLowerCase();
        return n === atName || n.includes(atName);
      });
      if (found) return String(found.id || found.agentId);
    }
    const singlePatterns = [/(\d)[번]\s*(에이전트)?\s*(만|답해|대답)/];
    for (const pattern of singlePatterns) {
      const m = msg.match(pattern);
      if (m) {
        const num = parseInt(m[1]) - 1;
        if (num >= 0 && num < agents.length) return String(agents[num].id || agents[num].agentId);
      }
    }
    return null;
  };

  const sendMessage = async (e) => {
    e.preventDefault();
    if (!message.trim() || !selectedAgent || typingRoomId) return;

    const agentId = getAgentId(selectedAgent);
    const inputMsg = message.trim();
    const targetAgentId = detectTargetAgentId(inputMsg, selectedAgent?.agents || []);
    const userMsg = {
      id: Date.now(),
      content: inputMsg,
      sender: 'USER',
      createdAt: new Date().toISOString()
    };

    setChatHistory((prev) => [...prev, userMsg]);
    setMessage('');
    setTypingRoomId(agentId);

    try {
      console.debug('[StudyMate] chat request', {
        userId,
        agentId,
        message: inputMsg,
        selectedAgent
      });
      const chatPayload = {
        ...buildChatAgentSettingsPayload(selectedAgent, inputMsg, agentId),
        ...(targetAgentId ? { targetAgentId } : {}),
      };
      console.debug('[StudyMate] chat payload', chatPayload);
      const res = await agentService.sendMessage(userId, agentId, chatPayload);
      console.debug('[StudyMate] chat response', res);

      if (selectedAgentIdRef.current === agentId) {
        // 200이지만 errorMessage가 있는 경우 (FastAPI/timeout 오류를 500 대신 200으로 반환)
        if (res.errorMessage || res.success === false) {
          setChatHistory((prev) => [
            ...prev,
            {
              id: `error-${Date.now()}`,
              content: `오류: ${res.errorMessage || 'AI 응답을 받지 못했습니다.'}`,
              sender: 'AI',
              senderName: '시스템',
              isError: true,
              createdAt: new Date().toISOString(),
            },
          ]);
        } else if (res.messages && Array.isArray(res.messages)) {
          const newMsgs = res.messages.map((m) => ({
            id: `${m.round}-${m.agentId}-${Date.now()}-${Math.random()}`,
            content: m.content,
            text: m.content,
            sender: 'AI',
            agentId: m.agentId,
            senderName: m.agentName,
            agentName: m.agentName,
            role: m.role,
            personality: m.personality,
            personalityStrength: m.personalityStrength,
            knowledgeLevel: m.knowledgeLevel,
            round: m.round,
            speechType: m.speechType,
            targetAgentId: m.targetAgentId,
            createdAt: new Date().toISOString()
          }));
          if (res.finalSynthesis) {
            newMsgs.push({
              id: `synthesis-${Date.now()}`,
              content: res.finalSynthesis,
              text: res.finalSynthesis,
              sender: 'AI',
              senderName: '핵심 정리',
              speechType: 'final_synthesis',
              createdAt: new Date().toISOString()
            });
          }
          setChatHistory((prev) => [...prev, ...newMsgs]);
        } else if (res.replies && res.replies.length > 0) {
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
      }
    } catch (err) {
      console.error('메시지 전송 실패:', err);
      const errMsg = err?.response?.data?.errorMessage
        || err?.response?.data?.message
        || err?.message
        || '메시지 전송에 실패했습니다. 잠시 후 다시 시도해주세요.';
      if (selectedAgentIdRef.current === agentId) {
        // alert() 대신 채팅창 안에 에러 카드 표시
        setChatHistory((prev) => [
          ...prev,
          {
            id: `error-${Date.now()}`,
            content: `오류: ${errMsg}`,
            sender: 'AI',
            senderName: '시스템',
            isError: true,
            createdAt: new Date().toISOString(),
          },
        ]);
      }
      // 실패한 입력은 입력창에 복원
      setMessage(inputMsg);
    } finally {
      setTypingRoomId(null);
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
                const personalityStrength = getAgentPersonalityStrength(agent);

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
                            <React.Fragment key={idx}>
                              <span className="tag">#{ag.name}</span>
                              <span className="tag">#{getAgentPersonality(ag)}</span>
                              <span className="tag">#{getPersonalityStrengthLabel(getAgentPersonalityStrength(ag))}</span>
                            </React.Fragment>
                          ))
                        ) : (
                          <>
                            <span className="tag">#{agent.role}</span>
                            <span className="tag">#{knowledgeLevel}</span>
                            <span className="tag">#{personality}</span>
                            <span className="tag">#{getPersonalityStrengthLabel(personalityStrength)}</span>
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
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
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

                    <button
                      onClick={() => setShowDetailsModal(true)}
                      className="btn-secondary"
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '6px',
                        fontSize: '12px',
                        padding: '6px 12px',
                        borderRadius: '20px',
                        backgroundColor: 'rgba(96, 201, 90, 0.1)',
                        border: '1px solid rgba(96, 201, 90, 0.2)',
                        color: 'var(--color-primary)',
                        fontWeight: '600',
                        cursor: 'pointer'
                      }}
                    >
                      <Info size={14} /> 에이전트 상세보기
                    </button>
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

                    let agentTheme = {
                      bg: '#F3F4F6',
                      border: '#D1D5DB',
                      text: '#374151',
                      icon: '🤖',
                      tagBg: '#E5E7EB',
                      accent: '#4B5563'
                    };
                    let agentPersonality = '';
                    let agentPersonalityStrength = '';
                    let agentRole = '';

                    if (!isUser && selectedAgent && selectedAgent.agents) {
                      const matchedAgent = selectedAgent.agents.find(
                        (ag) => String(ag.id || ag.agentId) === String(msg.agentId) || ag.name === senderName || ag.name === msg.senderName || ag.name === msg.sender_name
                      );
                      if (matchedAgent) {
                        agentPersonality = getAgentPersonality(matchedAgent);
                        agentPersonalityStrength = getAgentPersonalityStrength(matchedAgent);
                        agentTheme = getAgentStyleTheme(agentPersonality);
                        agentRole = matchedAgent.role;
                      }
                    }
                    if (!agentPersonality && msg.personality) {
                      agentPersonality = msg.personality;
                      agentPersonalityStrength = msg.personalityStrength || agentPersonalityStrength;
                      agentTheme = getAgentStyleTheme(agentPersonality);
                    }

                    return (
                      <div key={msg.id || idx} className={`chat-bubble-container ${isUser ? 'user' : 'ai'}`}>
                        <div
                          className="chat-bubble-sender"
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '6px',
                            color: isUser ? undefined : agentTheme.accent
                          }}
                        >
                          {!isUser && (
                            <span
                              style={{
                                display: 'inline-flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                                width: '20px',
                                height: '20px',
                                borderRadius: '50%',
                                backgroundColor: agentTheme.tagBg,
                                fontSize: '11px',
                                boxShadow: '0 1px 2px rgba(0,0,0,0.05)'
                              }}
                            >
                              {agentTheme.icon}
                            </span>
                          )}
                          <span style={{ fontWeight: '700' }}>{senderName}</span>
                          {!isUser && agentRole && (
                            <span style={{ fontSize: '10px', color: 'var(--color-text-muted)', opacity: 0.8 }}>
                              ({agentRole})
                            </span>
                          )}
                          {!isUser && agentPersonality && (
                            <span
                              style={{
                                fontSize: '9px',
                                padding: '1px 5px',
                                borderRadius: '4px',
                                backgroundColor: agentTheme.tagBg,
                                color: agentTheme.accent,
                                fontWeight: 'bold'
                              }}
                            >
                              {agentPersonality}
                            </span>
                          )}
                          {!isUser && agentPersonalityStrength && (
                            <span
                              style={{
                                fontSize: '9px',
                                padding: '1px 5px',
                                borderRadius: '4px',
                                backgroundColor: '#FEF3C7',
                                color: '#92400E',
                                fontWeight: 'bold'
                              }}
                            >
                              {getPersonalityStrengthLabel(agentPersonalityStrength)}
                            </span>
                          )}
                          {!isUser && msg.knowledgeLevel && (
                            <span
                              style={{
                                fontSize: '9px',
                                padding: '1px 5px',
                                borderRadius: '4px',
                                backgroundColor: '#EEF2FF',
                                color: '#4F46E5',
                                fontWeight: 'bold'
                              }}
                            >
                              {msg.knowledgeLevel}
                            </span>
                          )}
                          {!isUser && msg.round && (
                            <span
                              style={{
                                fontSize: '9px',
                                padding: '1px 5px',
                                borderRadius: '999px',
                                backgroundColor: '#F3F4F6',
                                color: 'var(--color-text-muted)',
                                fontWeight: 'bold'
                              }}
                            >
                              R{msg.round}{msg.speechType ? ` · ${msg.speechType}` : ''}
                            </span>
                          )}
                        </div>
                        <div
                          className={`chat-bubble ${isUser ? 'user' : 'ai'}`}
                          style={{
                            whiteSpace: 'pre-wrap',
                            backgroundColor: isUser ? undefined : agentTheme.bg,
                            color: isUser ? '#FFFFFF' : 'var(--color-text-main)',
                            border: 'none'
                          }}
                        >
                          {msg.content || msg.text}
                        </div>
                        <div className="chat-bubble-time">
                          {formatTime(msg.createdAt)}
                        </div>
                      </div>
                    );
                  })
                )}
                {typingRoomId === getAgentId(selectedAgent) && (
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
                  disabled={typingRoomId === getAgentId(selectedAgent)}
                />
                <button type="submit" className="btn-primary" style={{ width: '42px', height: '42px', borderRadius: '50%', padding: 0, flexShrink: 0, display: 'flex', justifyContent: 'center', alignItems: 'center' }} disabled={typingRoomId === getAgentId(selectedAgent) || !message.trim()}>
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
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                        <h4 style={{ margin: 0, color: 'var(--color-primary)', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', fontWeight: '700' }}>
                          <Bot size={16} /> AI 학습메이트 #{index + 1}
                        </h4>

                        {/* 추천 에이전트 생성 버튼 모음 */}
                        <div style={{ display: 'flex', gap: '4px', marginLeft: '4px', flexWrap: 'wrap' }}>
                          <button
                            type="button"
                            onClick={() => {
                              const list = [...createdAgents];
                              list[index] = {
                                ...list[index],
                                name: '김민성',
                                role: '명문대 교수',
                                personality: '전문적',
                                personalityStrength: 'extreme',
                                knowledgeLevel: '박사 수준'
                              };
                              setCreatedAgents(list);
                            }}
                            style={{
                              padding: '2px 8px',
                              borderRadius: '12px',
                              border: '1px solid rgba(59, 130, 246, 0.2)',
                              backgroundColor: 'rgba(59, 130, 246, 0.05)',
                              fontSize: '10px',
                              fontWeight: '600',
                              color: '#2563EB',
                              cursor: 'pointer'
                            }}
                          >
                            🎓 전문교수
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              const list = [...createdAgents];
                              list[index] = {
                                ...list[index],
                                name: '둘리',
                                role: '친한친구',
                                personality: '친근함',
                                personalityStrength: 'extreme',
                                knowledgeLevel: '입문 수준'
                              };
                              setCreatedAgents(list);
                            }}
                            style={{
                              padding: '2px 8px',
                              borderRadius: '12px',
                              border: '1px solid rgba(249, 115, 22, 0.2)',
                              backgroundColor: 'rgba(249, 115, 22, 0.05)',
                              fontSize: '10px',
                              fontWeight: '600',
                              color: '#EA580C',
                              cursor: 'pointer'
                            }}
                          >
                            ✨ 친근한친구
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              const list = [...createdAgents];
                              list[index] = {
                                ...list[index],
                                name: '장동탁',
                                role: '4차원 강사',
                                personality: '독특함',
                                personalityStrength: 'extreme',
                                knowledgeLevel: '전문가 수준'
                              };
                              setCreatedAgents(list);
                            }}
                            style={{
                              padding: '2px 8px',
                              borderRadius: '12px',
                              border: '1px solid rgba(139, 92, 246, 0.2)',
                              backgroundColor: 'rgba(139, 92, 246, 0.05)',
                              fontSize: '10px',
                              fontWeight: '600',
                              color: '#7C3AED',
                              cursor: 'pointer'
                            }}
                          >
                            👽 독창적강사
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              const list = [...createdAgents];
                              list[index] = {
                                ...list[index],
                                name: '김영환',
                                role: '까칠한 스승',
                                personality: '냉소적',
                                personalityStrength: 'extreme',
                                knowledgeLevel: '학사 수준'
                              };
                              setCreatedAgents(list);
                            }}
                            style={{
                              padding: '2px 8px',
                              borderRadius: '12px',
                              border: '1px solid rgba(244, 63, 94, 0.2)',
                              backgroundColor: 'rgba(244, 63, 94, 0.05)',
                              fontSize: '10px',
                              fontWeight: '600',
                              color: '#E11D48',
                              cursor: 'pointer'
                            }}
                          >
                            😈 냉철한멘토
                          </button>
                        </div>
                      </div>
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
                          placeholder="예: 김영한"
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

                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '12px' }}>
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
                          {PERSONALITY_OPTIONS.map((option) => (
                            <option key={option} value={option}>
                              {option} / {PERSONALITY_DESCRIPTIONS[option] || option}
                            </option>
                          ))}
                        </select>
                      </div>
                      <div>
                        <label style={{ display: 'block', fontSize: '12px', fontWeight: '600', color: 'var(--color-text-main)', marginBottom: '4px' }}>성격 강도</label>
                        <select
                          className="input-field"
                          value={agent.personalityStrength || 'extreme'}
                          onChange={(e) => {
                            const list = [...createdAgents];
                            list[index].personalityStrength = e.target.value;
                            setCreatedAgents(list);
                          }}
                        >
                          {PERSONALITY_STRENGTH_OPTIONS.map((option) => (
                            <option key={option.value} value={option.value}>{option.label}</option>
                          ))}
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

      {showDetailsModal && selectedAgent && (
        <div className="modal-overlay" onClick={() => setShowDetailsModal(false)}>
          <div
            className="glass-panel modal-content"
            style={{
              width: '95%',
              maxWidth: '650px',
              maxHeight: '85vh',
              overflow: 'hidden',
              display: 'flex',
              flexDirection: 'column',
              backgroundColor: 'rgba(255, 255, 255, 0.98)',
              backdropFilter: 'blur(16px)',
              boxShadow: '0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)',
              border: '1px solid rgba(255, 255, 255, 0.5)'
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="modal-header" style={{ paddingBottom: '16px', borderBottom: '1px solid var(--color-border)' }}>
              <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '8px', color: 'var(--color-text-main)' }}>
                <Bot size={20} color="var(--color-primary)" /> 스터디방 에이전트 상세 정보
              </h3>
              <button
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'var(--color-text-muted)' }}
                onClick={() => setShowDetailsModal(false)}
                aria-label="닫기"
              >
                <X size={20} />
              </button>
            </div>

            <div style={{ flex: 1, overflowY: 'auto', padding: '16px 0', display: 'flex', flexDirection: 'column', gap: '20px' }}>
              <div style={{ padding: '0 4px' }}>
                <h4 style={{ margin: '0 0 4px 0', fontSize: '15px', fontWeight: '700', color: 'var(--color-text-main)' }}>
                  스터디 그룹
                </h4>
                <p style={{ margin: 0, fontSize: '13px', color: 'var(--color-text-muted)' }}>
                  {selectedAgent.roomName || `${selectedAgent.name}의 그룹 스터디`}
                </p>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                {(selectedAgent.agents && selectedAgent.agents.length > 0 ? selectedAgent.agents : [selectedAgent]).map((ag, idx) => {
                  const agPersonality = getAgentPersonality(ag);
                  const agPersonalityStrength = getAgentPersonalityStrength(ag);
                  const agTheme = getAgentStyleTheme(agPersonality);
                  const agKnowledge = getAgentKnowledgeLevel(ag);

                  return (
                    <div
                      key={ag.id || idx}
                      style={{
                        border: '1px solid var(--color-border)',
                        borderRadius: '12px',
                        padding: '16px',
                        backgroundColor: '#FFFFFF',
                        display: 'flex',
                        flexDirection: 'column',
                        gap: '12px',
                        boxShadow: '0 2px 4px rgba(0, 0, 0, 0.02)'
                      }}
                    >
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <span
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              justifyContent: 'center',
                              width: '28px',
                              height: '28px',
                              borderRadius: '50%',
                              backgroundColor: agTheme.tagBg,
                              fontSize: '16px'
                            }}
                          >
                            {agTheme.icon}
                          </span>
                          <div>
                            <span style={{ fontWeight: 'bold', fontSize: '15px', color: 'var(--color-text-main)' }}>{ag.name}</span>
                            <span style={{ color: 'var(--color-text-muted)', fontSize: '11px', marginLeft: '6px' }}>({ag.role || '학습 메이트'})</span>
                          </div>
                        </div>

                        <div style={{ display: 'flex', gap: '6px' }}>
                          <span
                            style={{
                              fontSize: '11px',
                              padding: '2px 8px',
                              borderRadius: '12px',
                              backgroundColor: 'rgba(96, 201, 90, 0.08)',
                              color: 'var(--color-primary)',
                              fontWeight: '600'
                            }}
                          >
                            {agKnowledge}
                          </span>
                          <span
                            style={{
                              fontSize: '11px',
                              padding: '2px 8px',
                              borderRadius: '12px',
                              backgroundColor: agTheme.tagBg,
                              color: agTheme.accent,
                              fontWeight: '600'
                            }}
                          >
                            {agPersonality}
                          </span>
                          <span
                            style={{
                              fontSize: '11px',
                              padding: '2px 8px',
                              borderRadius: '12px',
                              backgroundColor: '#FEF3C7',
                              color: '#92400E',
                              fontWeight: '600'
                            }}
                          >
                            강도: {getPersonalityStrengthLabel(agPersonalityStrength)}
                          </span>
                        </div>
                      </div>

                      {(ag.customInstruction || ag.custom_instruction || ag.persona) && (
                        <div style={{ fontSize: '13px', lineHeight: '1.5', color: 'var(--color-text-main)' }}>
                          <div style={{ fontWeight: '600', marginBottom: '4px', color: 'var(--color-text-muted)' }}>사용자 지침 / 페르소나 설정</div>
                          <div
                            style={{
                              padding: '10px 12px',
                              backgroundColor: '#F9FAFB',
                              borderRadius: '8px',
                              border: '1px solid var(--color-border)',
                              fontStyle: 'normal',
                              whiteSpace: 'pre-wrap',
                              color: 'var(--color-text-main)'
                            }}
                          >
                            {ag.customInstruction || ag.custom_instruction || ag.persona}
                          </div>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </div>

            <div style={{ display: 'flex', gap: '10px', marginTop: 'auto', paddingTop: '16px', borderTop: '1px solid var(--color-border)' }}>
              <button
                type="button"
                className="btn-primary"
                style={{ width: '100%', borderRadius: '8px' }}
                onClick={() => setShowDetailsModal(false)}
              >
                닫기
              </button>
            </div>
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
