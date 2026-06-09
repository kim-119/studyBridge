import React, { useEffect, useRef, useState } from 'react';
import { useAuth } from '../hooks/useAuth';
import { agentService } from '../services/api';
import { Bot, Plus, Send, Sparkles, Trash2, X, MessageSquare, Network, ChevronLeft, ChevronRight, ChevronDown, CheckCircle2, Bookmark } from 'lucide-react';
import AgentDiscussionThread from '../components/studymate/AgentDiscussionThread';
import '../components/studymate/studymate-premium.css';
import { motion, AnimatePresence } from 'framer-motion';

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

// 정규 성격 키 → 한글 라벨 (백엔드 personalityType: creative/sardonic/logical/...)
const PERSONALITY_TYPE_LABELS = {
  creative: '독특함', sardonic: '냉소적', logical: '논리형',
  critical: '비판형', friendly: '친근함', concise: '효율적',
  professional: '전문적', custom: '맞춤형',
};
const personalityLabel = (t) => PERSONALITY_TYPE_LABELS[t] || t || '';
const stepContent = (row) => row?.content ?? row?.answer ?? row?.feedback ?? '';
const formatElapsed = (ms) => (typeof ms === 'number' && ms > 0 ? `${(ms / 1000).toFixed(1)}초` : '');

// 한 카드의 메타 헤더(에이전트명 / 성격 / 지식수준 / provider / 경과시간)를 만든다.
const buildCardMeta = (row, extra = []) => {
  const parts = [
    row?.agentName,
    personalityLabel(row?.personalityType),
    row?.knowledgeLevel,
    row?.provider,
    formatElapsed(row?.elapsedMs),
    ...extra,
  ];
  return parts.filter((p) => p !== undefined && p !== null && p !== '');
};

// ── 단계별 말풍선 (상세과정을 안 눌러도 1→2→3을 메인 대화에 순차 표시) ──────────
// 각 단계가 에이전트별 독립 말풍선으로 나온다: ⚡1차(빠른초안) → ✅2차(웹검증) → 💬3차(피드백)
const STAGE_META = {
  1: { badge: '⚡ 1차 · 빠른 초안', hint: 'Ollama', color: '#f59e0b' },
  2: { badge: '✅ 2차 · 검증 답안', hint: '웹 근거', color: '#16a34a' },
  3: { badge: '💬 3차 · 상호 피드백', hint: '', color: '#6366f1' },
};

const pvForName = (pvSummary, name) => (pvSummary || []).find((p) => p.agentName === name) || null;

// processSteps(전체 map) → 에이전트별 단계 말풍선 배열. parentId/createdAt는 부모 유저 메시지 기준.
const buildStageBubbles = (ps, parentId, createdAt) => {
  if (!ps) return [];
  const ts = createdAt || new Date().toISOString();
  const out = [];
  const mk = (stage, name, content, extra) => ({
    id: `${parentId}::${name}::s${stage}::${extra?.idx ?? 0}`,
    content,
    sender: 'AI',
    senderName: name,
    stage,
    createdAt: ts,
    parentId,
    ...extra,
  });
  (ps.initialAnswers || []).forEach((row, idx) => {
    out.push(mk(1, row.agentName, stepContent(row), { idx, provider: row.provider, elapsedMs: row.elapsedMs }));
  });
  (ps.validatedAnswers || []).forEach((row, idx) => {
    out.push(mk(2, row.agentName, stepContent(row), {
      idx, provider: row.provider, elapsedMs: row.elapsedMs, sources: row.sources || [],
    }));
  });
  (ps.peerFeedback || []).forEach((fb, idx) => {
    out.push(mk(3, fb.fromAgent, stepContent(fb), {
      idx, stageTo: fb.toAgent, pv: fb.personalityValidation || pvForName(ps.personalityValidationSummary, fb.fromAgent),
    }));
  });
  return out;
};

// DB 기록(에이전트마다 전체 map을 중복 저장)을 같은 턴당 1회만 단계 말풍선으로 폭발시킨다.
const explodeHistoryToStageBubbles = (history) => {
  if (!Array.isArray(history)) return history;
  const out = [];
  const seenTurn = new Set();
  for (const msg of history) {
    const ps = msg && msg.sender === 'AI' ? msg.processSteps : null;
    const hasStages = ps && ((ps.initialAnswers && ps.initialAnswers.length) || (ps.validatedAnswers && ps.validatedAnswers.length) || (ps.peerFeedback && ps.peerFeedback.length));
    if (hasStages) {
      const turnKey = msg.parentId ?? msg.id;
      if (seenTurn.has(turnKey)) continue; // 같은 턴 중복 에이전트 메시지는 건너뜀
      seenTurn.add(turnKey);
      const bubbles = buildStageBubbles(ps, turnKey, msg.createdAt);
      if (bubbles.length) { out.push(...bubbles); continue; }
    }
    out.push(msg);
  }
  return out;
};

// 멀티 에이전트 응답의 1차/2차/3차 생성 과정 — 선택된 에이전트 전원의 결과를 단계별로 모두 렌더링한다.
const ProcessStepsAccordion = ({ processSteps }) => {
  const [open, setOpen] = useState(false);
  if (!processSteps) return null;

  const initialAnswers = processSteps.initialAnswers || [];
  const validatedAnswers = processSteps.validatedAnswers || [];
  const peerFeedback = processSteps.peerFeedback || [];
  const pvSummary = processSteps.personalityValidationSummary || [];

  const hasAny = initialAnswers.length || validatedAnswers.length || peerFeedback.length || pvSummary.length;
  if (!hasAny) return null;

  const sectionTitleStyle = { fontWeight: '800', fontSize: '12px', margin: '2px 0' };
  const agentCardStyle = { padding: '10px 12px', borderRadius: '10px', backgroundColor: 'rgba(0,0,0,0.03)', fontSize: '12px' };
  const metaStyle = { fontWeight: '700', marginBottom: '4px', color: 'var(--color-text-main)' };
  const bodyTextStyle = {
    whiteSpace: 'pre-wrap', wordBreak: 'break-word', overflowWrap: 'anywhere',
    overflow: 'visible', maxHeight: 'none', color: 'var(--color-text-muted)',
  };

  const pvFor = (name) => pvSummary.find((p) => p.agentName === name) || null;

  return (
    <div style={{ marginTop: '8px' }}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: '4px',
          background: 'none', border: 'none', cursor: 'pointer',
          fontSize: '12px', fontWeight: '600', color: 'var(--color-text-muted)', padding: '2px 0',
        }}
      >
        <ChevronDown size={14} style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.15s' }} />
        {open ? '생성과정 접기' : '생성과정 보기'}
      </button>

      {open && (
        <div style={{ marginTop: '8px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
          {/* 1차 답변 생성 — 에이전트 전원 */}
          {initialAnswers.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div style={sectionTitleStyle}>1차 답변 생성</div>
              {initialAnswers.map((row, i) => (
                <div key={`ia-${i}`} style={agentCardStyle}>
                  <div style={metaStyle}>{buildCardMeta(row).join(' / ')}</div>
                  <div style={bodyTextStyle}>{stepContent(row)}</div>
                </div>
              ))}
            </div>
          )}

          {/* 2차 검증 답안 — 에이전트 전원 */}
          {validatedAnswers.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div style={sectionTitleStyle}>2차 검증 답안</div>
              {validatedAnswers.map((row, i) => {
                const extra = [];
                if (typeof row.score === 'number') extra.push(`score ${row.score.toFixed(2)}`);
                if (row.revised) extra.push('수정됨');
                return (
                  <div key={`va-${i}`} style={agentCardStyle}>
                    <div style={metaStyle}>{buildCardMeta(row, extra).join(' / ')}</div>
                    <div style={bodyTextStyle}>{stepContent(row)}</div>
                    {row.issues && row.issues.length > 0 && (
                      <ul style={{ margin: '6px 0 0', paddingLeft: '16px', color: 'var(--color-text-muted)' }}>
                        {row.issues.map((issue, j) => <li key={j}>{issue}</li>)}
                      </ul>
                    )}
                  </div>
                );
              })}
            </div>
          )}

          {/* 3차 상호 피드백 — 에이전트 전원 */}
          {peerFeedback.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div style={sectionTitleStyle}>3차 상호 피드백</div>
              {peerFeedback.map((fb, i) => {
                const pv = fb.personalityValidation || pvFor(fb.fromAgent);
                return (
                  <div key={`pf-${i}`} style={agentCardStyle}>
                    <div style={metaStyle}>
                      {fb.fromAgent} → {fb.toAgent}
                      {fb.personalityType && (
                        <span style={{ marginLeft: 6, fontWeight: 500, color: 'var(--color-text-muted)' }}>
                          ({personalityLabel(fb.personalityType)})
                        </span>
                      )}
                      {pv && typeof pv.score === 'number' && (
                        <span style={{ marginLeft: 6, fontSize: '10px', padding: '1px 6px', borderRadius: '4px', backgroundColor: 'rgba(0,0,0,0.06)' }}>
                          성격 {pv.score.toFixed(2)} {pv.passed ? '통과' : '보완'}
                        </span>
                      )}
                    </div>
                    <div style={bodyTextStyle}>{stepContent(fb)}</div>
                  </div>
                );
              })}
            </div>
          )}

          {/* 성격 검증 요약 (있으면) */}
          {pvSummary.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <div style={sectionTitleStyle}>성격 검증 요약</div>
              {pvSummary.map((p, i) => (
                <div key={`pv-${i}`} style={{ fontSize: '11px', color: 'var(--color-text-muted)' }}>
                  <strong>{p.agentName}</strong>
                  {p.personalityType && <span> · {personalityLabel(p.personalityType)}</span>}
                  {typeof p.score === 'number' && (
                    <span style={{ marginLeft: 6, padding: '1px 6px', borderRadius: '4px', backgroundColor: 'rgba(0,0,0,0.06)' }}>
                      score {p.score.toFixed(2)}
                    </span>
                  )}
                  <span style={{ marginLeft: 6, color: p.passed ? '#16a34a' : '#dc2626', fontWeight: 600 }}>
                    {p.passed ? '통과' : '보완 필요'}
                  </span>
                  {p.note && <div style={{ marginTop: 2 }}>{p.note}</div>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};

// 응답 생성 중 진행 단계를 경과 시간 기준으로 안내한다.
// (백엔드는 1차→2차→3차를 한 번의 호출에서 순차 수행하므로 경과 시간으로 단계명을 추정해 표시한다.)
const TYPING_STAGES = [
  { after: 0, label: '1차 빠른 답변 생성 중...' },
  { after: 12, label: '2차 검증 답안 작성 중...' },
  { after: 26, label: '3차 에이전트 피드백 정리 중...' },
];

const StagedTypingLabel = () => {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    const startedAt = Date.now();
    const timer = setInterval(() => setElapsed((Date.now() - startedAt) / 1000), 1000);
    return () => clearInterval(timer);
  }, []);
  const current = [...TYPING_STAGES].reverse().find((s) => elapsed >= s.after) || TYPING_STAGES[0];
  return <>{current.label}</>;
};

const parsePersonaTag = (persona, tagName) => {
  const match = String(persona || '').match(new RegExp(`\\[${tagName}:\\s*([^\\]]+)\\]`));
  return match ? match[1].trim() : '';
};

// 기록 로드 시에도 라이브와 동일하게 1→2→3 단계 말풍선으로 펼쳐 보여준다(상세과정 클릭 불필요).
const hydrateHistoryProcessSteps = (history) => explodeHistoryToStageBubbles(history);

const getAgentId = (agent) => agent?.id ?? agent?.agentId;

// 화면에 표시되는 채팅방/그룹 제목은 항상 '스터디 브릿지'로 고정한다.
// 내부 roomId, agentId, DB id 및 저장된 roomName 값은 절대 변경하지 않고 표시명만 고정한다.
const STUDYBRIDGE_ROOM_TITLE = '스터디 브릿지';
const getDisplayRoomTitle = () => STUDYBRIDGE_ROOM_TITLE;

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
  const [viewTab, setViewTab] = useState('chat'); // 'chat' | 'mindmap'
  const [message, setMessage] = useState('');
  
  // 멘션(@) 관련 상태
  const [showMentionPopup, setShowMentionPopup] = useState(false);
  const [mentionFilter, setMentionFilter] = useState('');
  const [bookmarkedIds, setBookmarkedIds] = useState(new Set());
  const [toastMsg, setToastMsg] = useState('');
  
  // 패널 토글 상태
  const [isLeftOpen, setIsLeftOpen] = useState(true);
  const [isRightOpen, setIsRightOpen] = useState(true);

  // 더 자세히 요청 시, 다음 AI 응답을 어떤 노드의 자식로 연결할지 추적
  const pendingDetailParentId = React.useRef(null);
  
  // 개별 채팅방별 캐시 및 상태 관리
  const [roomHistories, setRoomHistories] = useState({}); // { [roomId]: messages[] }
  const [typingRooms, setTypingRooms] = useState({});     // { [roomId]: boolean }
  const [roomDrafts, setRoomDrafts] = useState({});       // { [roomId]: string }

  const [showModal, setShowModal] = useState(false);
  const [showDetailsModal, setShowDetailsModal] = useState(false);

  const selectedAgentIdRef = useRef(null);
  useEffect(() => {
    selectedAgentIdRef.current = getAgentId(selectedAgent);
  }, [selectedAgent]);

  // 멀티 에이전트 동적 추가를 위해 상태를 배열로 정의
  const [createdAgents, setCreatedAgents] = useState([{ ...DEFAULT_AGENT }]);
  const [roomName, setRoomName] = useState('');
  // 학습 진행 모드: basic(기본 채팅) / socratic(소크라테스) / debate(토론)
  const [learningMode, setLearningMode] = useState('basic');

  const chatEndRef = useRef(null);

  useEffect(() => {
    if (userId) {
      loadAgents();
    } else {
      setAgents([]);
      setSelectedAgent(null);
      setChatHistory([]);
      setRoomHistories({});
      setTypingRooms({});
      setRoomDrafts({});
    }
  }, [userId]);

  useEffect(() => {
    scrollToBottom();
  }, [chatHistory, typingRooms]);

  const loadAgents = async () => {
    try {
      const data = await agentService.getAgents(userId);
      setAgents(data || []);
    } catch (err) {
      console.error('에이전트 목록 조회 실패:', err);
    }
  };

  const handleOpenModal = () => {
    if (!userId) return;
    setCreatedAgents([{ ...DEFAULT_AGENT }]);
    setRoomName('');
    setLearningMode('basic');
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
    // 표시명은 항상 '스터디 브릿지'로 고정되므로, 저장되는 기본 roomName도 동일하게 맞춘다.
    const finalRoomName = roomName.trim() || STUDYBRIDGE_ROOM_TITLE;

    const payload = {
      roomName: finalRoomName,
      agents: payloadAgents,
      learningMode
    };

    try {
      console.debug('[StudyMate] create agent room payload', payload);
      await agentService.createAgent(userId, payload);
      setShowModal(false);
      setCreatedAgents([{ ...DEFAULT_AGENT }]);
      setRoomName('');
      setLearningMode('basic');
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

    // 1. 이전 방의 질문이 보이지 않도록 즉각적으로 해당 방의 캐시된 기록을 UI에 노출 (없으면 빈 리스트)
    const cachedHistory = roomHistories[agentId] || [];
    setChatHistory(cachedHistory);

    // 2. 해당 방의 드래프트가 존재하면 입력 폼에 로드
    setMessage(roomDrafts[agentId] || '');

    // 3. 최신 채팅 이력을 비동기 조회하여 동기화
    try {
      const rawHistory = await agentService.getChatHistory(userId, agentId);
      // DB에 저장된 processSteps(전체 map)를 그대로 사용해 아코디언을 복원 (슬라이스 없이 전원 표시)
      const history = hydrateHistoryProcessSteps(rawHistory);
      // 캐시 갱신
      setRoomHistories(prev => ({ ...prev, [agentId]: history || [] }));

      // 비동기 복귀 시점에도 여전히 이 방이 활성화되어 있을 때만 UI에 반영하여 다른 방 간섭 방지
      if (selectedAgentIdRef.current === agentId) {
        setChatHistory(history || []);
      }
    } catch (err) {
      console.error('채팅 이력 조회 실패:', err);
      if (selectedAgentIdRef.current === agentId) {
        // 에러가 발생해도 이전 캐시를 그대로 보여줍니다.
      }
    }
  };

  const sendMessage = async (e, directMessage = null) => {
    if (e) e.preventDefault();
    const agentId = getAgentId(selectedAgent);
    const inputMsg = directMessage || message.trim();
    if (!inputMsg || !selectedAgent || typingRooms[agentId]) return;
    const userMsg = {
      id: Date.now(),
      content: inputMsg,
      sender: 'USER',
      createdAt: new Date().toISOString(),
      parentId: pendingDetailParentId.current || undefined
    };

    // 1. 현재 화면에 즉시 사용자 메시지 추가
    setChatHistory((prev) => [...prev, userMsg]);
    // 2. 해당 방의 캐시된 히스토리에도 사용자 메시지 추가
    setRoomHistories((prev) => ({
      ...prev,
      [agentId]: [...(prev[agentId] || []), userMsg]
    }));
    // 3. 입력 폼 비우기 및 드래프트 캐시 비우기
    setMessage('');
    setRoomDrafts((prev) => ({ ...prev, [agentId]: '' }));
    // 4. 해당 방의 타이핑/로딩 상태 활성화 (전체 방 블로킹 X)
    setTypingRooms((prev) => ({ ...prev, [agentId]: true }));

    // 이번 턴의 AI 메시지를 통째로 교체(누적 갱신)한다. 단계 도착마다 호출된다.
    const setTurnAiMessages = (aiMsgs) => {
      const merge = (list) => {
        const kept = (list || []).filter((m) => !(m.sender === 'AI' && m.parentId === userMsg.id));
        return [...kept, ...aiMsgs];
      };
      setRoomHistories((prev) => ({ ...prev, [agentId]: merge(prev[agentId]) }));
      if (selectedAgentIdRef.current === agentId) setChatHistory((prev) => merge(prev));
    };

    // 누적 processSteps(전체 map)로부터 단계별 말풍선(1차/2차/3차)을 만든다.
    // 단계가 도착할 때마다 1차→2차→3차 순으로 메인 대화에 누적 표시된다(상세과정 클릭 불필요).
    const buildStreamAiMsgs = (ps) => buildStageBubbles(ps, userMsg.id, new Date().toISOString());

    try {
      // ── P2: 단계별 SSE 선출력 우선 시도 (실패 시 블로킹 폴백) ──
      const STREAMING_ENABLED = (import.meta.env.VITE_STUDYMATE_SSE ?? 'true') !== 'false';
      if (STREAMING_ENABLED) {
        const fullPS = { initialAnswers: [], validatedAnswers: [], peerFeedback: [], personalityValidationSummary: [] };
        let streamRendered = false;
        let streamCompleted = false;
        try {
          await agentService.streamMessage(userId, agentId, {
            message: inputMsg,
            learningMode: selectedAgent?.learningMode || 'basic',
            rounds: 1,
          }, {
            onStageComplete: (d) => {
              if (!d) return;
              if (d.stage === 1) fullPS.initialAnswers = d.answers || [];
              else if (d.stage === 2) fullPS.validatedAnswers = d.answers || [];
              else if (d.stage === 3) {
                fullPS.peerFeedback = d.feedbacks || [];
                fullPS.personalityValidationSummary = d.personalityValidationSummary || [];
              }
              streamRendered = true;
              setTurnAiMessages(buildStreamAiMsgs(fullPS));
            },
            onAllComplete: (d) => {
              streamCompleted = true;
              const ps = (d && d.processSteps) || fullPS;
              setTurnAiMessages(buildStreamAiMsgs(ps));
            },
            onError: () => { throw new Error('stream error event'); },
          });
          if (!streamCompleted && !streamRendered) {
            throw new Error('empty stream');
          }
          pendingDetailParentId.current = null;
          return; // 성공 — 바깥 finally에서 typing 해제
        } catch (streamErr) {
          console.warn('[StudyMate] SSE 스트리밍 실패', streamErr);
          if (streamRendered) {
            // 일부 단계가 이미 렌더됨 → 블로킹 재실행 시 중복되므로 폴백하지 않는다.
            pendingDetailParentId.current = null;
            return;
          }
          // 아무것도 못 받음 → 아래 블로킹 로직으로 폴백
        }
      }

      console.debug('[StudyMate] chat request', {
        userId,
        agentId,
        message: inputMsg,
        selectedAgent
      });
      const res = await agentService.sendMessage(userId, agentId, {
        message: inputMsg,
        // 방에 저장된 학습 진행 모드를 그대로 전달 (없으면 기본 채팅 모드로 처리)
        learningMode: selectedAgent?.learningMode || 'basic',
        rounds: 1, // 프론트단에서 타임아웃 방지를 위해 강제로 1라운드(병렬 단답)만 요청
      });
      console.debug('[StudyMate] chat response', res);

      if (res.success === false || res.errorMessage) {
        // timeout 등 서버측 실패: alert로 흐름을 막지 않고 UI 내부 메시지로 부드럽게 안내한다.
        const isSoftTimeout = res.errorCode === 'AI_TIMEOUT';
        const noticeText = isSoftTimeout
          ? 'AI 답변 생성이 예상보다 오래 걸리고 있습니다. 소크라테스/토론 모드는 더 깊은 검토가 필요해 시간이 더 걸릴 수 있어요. 잠시 후 다시 시도하면 보통 정상 생성됩니다.'
          : (res.errorMessage || 'AI 응답 생성에 실패했습니다. 잠시 후 다시 시도해주세요.');
        const noticeMsg = {
          id: Date.now() + 1,
          content: noticeText,
          sender: 'AI',
          senderName: selectedAgent?.name || 'StudyMate',
          isError: true,
          createdAt: new Date().toISOString(),
          parentId: userMsg.id,
        };
        setRoomHistories((prev) => {
          const currentList = prev[agentId] || [];
          const hasUserMsg = currentList.some((m) => m.id === userMsg.id);
          const baseList = hasUserMsg ? currentList : [...currentList, userMsg];
          return { ...prev, [agentId]: [...baseList, noticeMsg] };
        });
        if (selectedAgentIdRef.current === agentId) {
          setChatHistory((prev) => {
            const hasUserMsg = prev.some((m) => m.id === userMsg.id);
            const baseList = hasUserMsg ? prev : [...prev, userMsg];
            return [...baseList, noticeMsg];
          });
        }
        pendingDetailParentId.current = null;
        return; // alert 없이 종료 (finally에서 typing 상태 해제)
      }

      // 블로킹 폴백도 단계 말풍선(1→2→3)으로 통일한다. 단계가 없으면 일반 답변 버블로 표시.
      let newMsgs = [];
      const blockingStages = buildStageBubbles(res.processSteps, userMsg.id, new Date().toISOString());
      if (blockingStages.length > 0) {
        newMsgs = blockingStages;
      } else if (res.replies && res.replies.length > 0) {
        newMsgs = res.replies.map((reply, index) => {
          const senderName = reply.agentName || reply.agent_name;
          return {
            id: Date.now() + 1 + index,
            content: reply.answer || reply.content,
            sender: 'AI',
            senderName,
            agentId: reply.agentId,
            createdAt: new Date().toISOString(),
            parentId: userMsg.id, // AI 응답은 방금 작성한 유저 질문의 자식이 됨
            processSteps: res.processSteps,
          };
        });
      } else {
        newMsgs = [{
          id: Date.now() + 1,
          content: res.answer,
          sender: 'AI',
          senderName: selectedAgent.name,
          createdAt: new Date().toISOString(),
          parentId: userMsg.id,
          processSteps: res.processSteps,
        }];
      }
      // 태깅 초기화
      pendingDetailParentId.current = null;

      // 5. 해당 방의 캐시 갱신 (사용자가 다른 방에 있더라도 백그라운드 캐시에 완벽히 반영)
      setRoomHistories((prev) => {
        const currentList = prev[agentId] || [];
        const hasUserMsg = currentList.some(m => m.id === userMsg.id);
        const baseList = hasUserMsg ? currentList : [...currentList, userMsg];
        return {
          ...prev,
          [agentId]: [...baseList, ...newMsgs]
        };
      });

      // 6. 현재 여전히 이 방을 보고 있는 경우에만 실시간 UI 업데이트 실행
      if (selectedAgentIdRef.current === agentId) {
        setChatHistory((prev) => {
          const hasUserMsg = prev.some(m => m.id === userMsg.id);
          const baseList = hasUserMsg ? prev : [...prev, userMsg];
          return [...baseList, ...newMsgs];
        });
      }
    } catch (err) {
      console.error('메시지 전송 실패:', err);
      // alert로 흐름을 막지 않고, 네트워크/서버 오류를 채팅 내부 메시지로 표시한다.
      const isNetwork = err?.code === 'ERR_NETWORK' || /Network|timeout|aborted/i.test(err?.message || '');
      const noticeText = isNetwork
        ? '서버 연결이 불안정합니다. 잠시 후 다시 시도해주세요.'
        : (err.message || 'AI 응답 생성에 실패했습니다. 잠시 후 다시 시도해주세요.');
      const noticeMsg = {
        id: Date.now() + 1,
        content: noticeText,
        sender: 'AI',
        senderName: selectedAgent?.name || 'StudyMate',
        isError: true,
        createdAt: new Date().toISOString(),
        parentId: userMsg.id,
      };
      setRoomHistories((prev) => {
        const currentList = prev[agentId] || [];
        const hasUserMsg = currentList.some((m) => m.id === userMsg.id);
        const baseList = hasUserMsg ? currentList : [...currentList, userMsg];
        return { ...prev, [agentId]: [...baseList, noticeMsg] };
      });
      if (selectedAgentIdRef.current === agentId) {
        setChatHistory((prev) => {
          const hasUserMsg = prev.some((m) => m.id === userMsg.id);
          const baseList = hasUserMsg ? prev : [...prev, userMsg];
          return [...baseList, noticeMsg];
        });
      }
    } finally {
      // 8. 해당 방의 타이핑/로딩 상태만 해제
      setTypingRooms((prev) => ({ ...prev, [agentId]: false }));
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

  // 로그아웃 상태일 때도 UI는 렌더링되도록 함

  const handleBookmark = (node) => {
    setBookmarkedIds((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(node.id)) {
        newSet.delete(node.id);
        setToastMsg('❌ 메모가 취소되었습니다.');
      } else {
        newSet.add(node.id);
        setToastMsg('📌 메모에 저장되었습니다.');
      }
      setTimeout(() => setToastMsg(''), 2500);
      return newSet;
    });
  };

  const handleScrollToNode = (id) => {
    const element = document.getElementById(`node-${id}`);
    if (element) {
      element.scrollIntoView({ behavior: 'smooth', block: 'center' });
      // 반짝이는 효과 주기
      element.style.transition = 'box-shadow 0.3s ease-in-out';
      element.style.boxShadow = '0 0 0 4px rgba(16, 185, 129, 0.4)';
      setTimeout(() => {
        element.style.boxShadow = '';
      }, 1500);
    }
  };

  return (
    <div className="container-workspace">
      {/* ── 토스트 알림 ── */}
      {toastMsg && (
        <div style={{
          position: 'fixed', bottom: 28, left: '50%', transform: 'translateX(-50%)',
          background: '#111827', color: '#fff', padding: '10px 20px', borderRadius: 12,
          fontSize: 13, fontWeight: 600, zIndex: 9999, whiteSpace: 'nowrap',
          boxShadow: '0 8px 24px rgba(0,0,0,0.2)', animation: 'fadeInUp 0.25s ease',
        }}>
          {toastMsg}
        </div>
      )}
      <div className="layout-3-panel">
        {/* ════ 1. 좌측: 트윈 컨트롤 패널 ════ */}
        {isLeftOpen && (
          <div className="pane-left animate-fade-in">
            <div className="dt-left-panel">

            {/* 헤더 */}
            <div className="dt-left-header">
              <div className="dt-left-title">
                <div className="dt-left-title-icon">
                  <Sparkles size={14} color="white" />
                </div>
                AI 학습메이트
              </div>
            </div>

            {/* 트윈 동기화 상태 배너 */}
            <div className="dt-sync-banner">
              <div className="dt-sync-dot" />
              <div>
                <span className="dt-sync-text">트윈 세션 활성화</span>
                <span style={{ marginLeft: 4 }}>·</span>
                <span style={{ marginLeft: 4 }}>{agents.length}개 그룹</span>
              </div>
            </div>

            {/* 에이전트 카드 스크롤 영역 */}
            <div className="dt-agent-scroll">
              {agents.length === 0 ? (
                <div className="dt-empty-state">
                  <div className="dt-empty-icon">
                    <Bot size={28} color="#60C95A" />
                  </div>
                  <div style={{ fontWeight: 700, fontSize: 14, color: '#374151', marginBottom: 6 }}>에이전트가 없습니다</div>
                  <div style={{ fontSize: 12, color: '#9ca3af', lineHeight: 1.5 }}>학습 목적에 맞는<br/>
                    AI 에이전트를 만들어보세요.
                  </div>
                </div>
              ) : (
                agents.map((agent, index) => {
                  const agentId = getAgentId(agent);
                  const isActive = getAgentId(selectedAgent) === agentId;
                  const avatarColor = getAvatarColor(index);
                  const knowledgeLevel = getAgentKnowledgeLevel(agent);
                  const personality = getAgentPersonality(agent);
                  const isTyping = typingRooms[agentId];

                  return (
                    <div
                      key={agentId}
                      className={`dt-agent-card ${isActive ? 'active' : ''}`}
                      onClick={() => selectAgent(agent)}
                    >
                      <div className="dt-agent-card-row">
                        <div className="dt-avatar-wrap">
                          <div className="dt-avatar" style={{ backgroundColor: avatarColor.bg, color: avatarColor.text }} title="StudyBridge AI">
                            <Bot size={18} />
                          </div>
                          <div className={`dt-status-dot ${isTyping ? 'busy' : isActive ? 'online' : 'idle'}`} />
                        </div>
                        <div className="dt-agent-info">
                          <div className="dt-agent-name">{getDisplayRoomTitle(agent)}</div>
                          <div className="dt-agent-tags">
                            {agent.agents && agent.agents.length > 0 ? (
                              agent.agents.map((ag, idx) => (
                                <span key={idx} className="dt-tag">#{ag.name}</span>
                              ))
                            ) : (
                              <>
                                <span className="dt-tag">#{personality}</span>
                                <span className="dt-tag">#{knowledgeLevel}</span>
                              </>
                            )}
                          </div>
                          <div className="dt-agent-desc">
                            {String(agent.persona || agent.goal || '').substring(0, 38) || '학습 메이트'}
                          </div>
                        </div>
                        <button
                          className="dt-delete-btn"
                          onClick={(e) => handleDeleteAgent(e, agentId)}
                          aria-label="에이전트 삭제"
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                      {isActive && <div className="dt-neural-bar" />}
                    </div>
                  );
                })
              )}
            </div>

            {/* 하단 고정 생성 버튼 */}
            <div className="dt-create-btn-wrap">
              <button
                className="dt-create-btn"
                onClick={handleOpenModal}
                disabled={agents.length >= 3}
              >
                <Plus size={15} /> 새 AI 그룹 생성 ({agents.length}/3)
              </button>
            </div>

          </div>
        </div>
        )}

        {/* 좌측 패널 토글 버튼 */}
        <button 
          onClick={() => setIsLeftOpen(!isLeftOpen)}
          style={{
            position: 'absolute', left: isLeftOpen ? '300px' : '0', top: '50%', transform: 'translateY(-50%)', zIndex: 50,
            background: 'white', border: '1px solid #e5e7eb', borderLeft: 'none', borderRadius: '0 12px 12px 0', padding: '10px 4px', cursor: 'pointer',
            boxShadow: '4px 0 12px rgba(0,0,0,0.05)', transition: 'left 0.3s ease', display: 'flex', alignItems: 'center', justifyContent: 'center'
          }}
        >
          {isLeftOpen ? <ChevronLeft size={16} color="#9ca3af" /> : <ChevronRight size={16} color="#9ca3af" />}
        </button>

        {/* ════ 2. 중앙: 메인 학습 캔버스 ════ */}
        <div className="pane-center animate-fade-in">
          {!selectedAgent ? (
            <div className="empty-state" style={{ 
              display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', 
              height: '100%', background: 'linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)', position: 'relative' 
            }}>
              <div style={{ position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)', width: '300px', height: '300px', background: 'radial-gradient(circle, rgba(96,201,90,0.05) 0%, transparent 70%)', borderRadius: '50%', animation: 'pulseDot 4s infinite alternate' }}></div>
              <div style={{ background: 'white', padding: '24px', borderRadius: '24px', boxShadow: '0 8px 30px rgba(0,0,0,0.04)', marginBottom: '24px', position: 'relative', zIndex: 1 }}>
                <Sparkles size={48} color="#60C95A" />
              </div>
              <h2 style={{ 
                margin: '0 0 12px 0', fontSize: '28px', fontWeight: '900', letterSpacing: '-0.5px',
                background: 'linear-gradient(135deg, #111827 0%, #374151 100%)',
                WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent', position: 'relative', zIndex: 1 
              }}>스터디 브릿지</h2>
              <p style={{ margin: 0, color: '#6b7280', fontSize: '15px', fontWeight: '500', textAlign: 'center', lineHeight: '1.6', position: 'relative', zIndex: 1 }}>
                왼쪽 패널에서 에이전트를 선택하여 지식 동기화를 시작하거나<br/>
                새로운 AI 학습메이트를 생성하세요.
              </p>
            </div>
          ) : (
            <div className="chat-container">
              {/* ── 스터디 브릿지 세션 헤더 ── */}
              <div className="dt-session-header">
                {/* 상단: 아이덴티티 + 상세보기 (전체화면 시 숨김) */}
                { (isLeftOpen || isRightOpen) && (
                  <>
                    <div className="dt-session-top">
                      <div className="dt-session-identity">
                        <div className="dt-session-avatar" title="StudyBridge AI">
                          <Bot size={18} />
                        </div>
                        <div>
                          <div className="dt-session-title">
                            {getDisplayRoomTitle(selectedAgent)}
                          </div>
                        </div>
                      </div>
                      <button
                        onClick={() => setShowDetailsModal(true)}
                        style={{
                          display: 'flex', alignItems: 'center', gap: '5px',
                          fontSize: '11px', padding: '5px 10px', borderRadius: '8px',
                          background: 'rgba(96,201,90,0.08)', border: '1px solid rgba(96,201,90,0.2)',
                          color: '#16a34a', fontWeight: '700', cursor: 'pointer'
                        }}
                      >
                        에이전트 상세
                      </button>
                    </div>

                    {/* 에이전트 칩 */}
                    {selectedAgent.agents && selectedAgent.agents.length > 0 && (
                      <div className="dt-agent-chips">
                        {selectedAgent.agents.map((ag, idx) => {
                          const c = getAvatarColor(idx);
                          return (
                            <div key={ag.id || idx} className="dt-agent-chip">
                              <div className="dt-chip-dot" style={{ backgroundColor: c.text }} />
                              <span>{ag.name}</span>
                              <span style={{ color: '#9ca3af', fontSize: 10 }}>({ag.role})</span>
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </>
                )}

                {/* 탭 전환 바 */}
                <div className="view-tab-bar">
                  <button
                    id="tab-chat"
                    className={`view-tab-btn ${viewTab === 'chat' ? 'active' : ''}`}
                    onClick={() => {
                      setViewTab('chat');
                      setIsLeftOpen(true);
                      setIsRightOpen(true);
                    }}
                  >
                    <MessageSquare size={13} /> 채팅
                  </button>
                  <button
                    id="tab-mindmap"
                    className={`view-tab-btn ${viewTab === 'mindmap' ? 'active mindmap' : ''}`}
                    onClick={() => {
                      setViewTab('mindmap');
                      setIsLeftOpen(false); // 마인드맵 진입 시 좌측 패널 자동 숨김
                      setIsRightOpen(false); // 마인드맵 진입 시 우측 패널 자동 숨김
                    }}
                  >
                    <Network size={13} /> 마인드맵 (크게 보기)
                  </button>
                </div>
              </div>

              {/* ── 채팅 뷰 ── */}
              {viewTab === 'chat' && (
                <div className="chat-history">
                  {chatHistory.length === 0 ? (
                    <div className="empty-state" style={{ marginTop: '40px' }}>
                      <MessageSquare size={36} color="#E5E7EB" style={{ marginBottom: 12 }} />
                      <p style={{ margin: 0, color: '#9ca3af', fontSize: 14 }}>질문을 입력해보세요.</p>
                    </div>
                  ) : (
                    chatHistory.map((msg, idx) => {
                      const isUser = msg.sender === 'USER';
                      const senderName = isUser ? '나' : (msg.senderName || msg.sender_name || selectedAgent.name);

                      let agentTheme = { bg: '#F3F4F6', icon: '🤖', tagBg: '#E5E7EB', accent: '#4B5563' };
                      let agentPersonality = '';
                      let agentRole = '';

                      if (!isUser && selectedAgent && selectedAgent.agents) {
                        const matchedAgent = selectedAgent.agents.find(
                          (ag) => ag.name === senderName || ag.name === msg.senderName || ag.name === msg.sender_name
                        );
                        if (matchedAgent) {
                          agentPersonality = getAgentPersonality(matchedAgent);
                          agentTheme = getAgentStyleTheme(agentPersonality);
                          agentRole = matchedAgent.role;
                        }
                      }

                      return (
                        <div key={msg.id || idx} className={`chat-bubble-container ${isUser ? 'user' : 'ai'}`}>
                          <div className="chat-bubble-sender" style={{ display: 'flex', alignItems: 'center', gap: '6px', color: isUser ? undefined : agentTheme.accent }}>
                            {!isUser && (
                              <span style={{ display: 'inline-flex', alignItems: 'center', justifyContent: 'center', width: '20px', height: '20px', borderRadius: '50%', backgroundColor: agentTheme.tagBg, fontSize: '11px' }}>
                                {agentTheme.icon}
                              </span>
                            )}
                            <span style={{ fontWeight: '700' }}>{senderName}</span>
                            {!isUser && msg.stage && STAGE_META[msg.stage] && (
                              <span style={{ fontSize: '10px', padding: '1px 7px', borderRadius: '999px', backgroundColor: `${STAGE_META[msg.stage].color}22`, color: STAGE_META[msg.stage].color, fontWeight: 'bold', whiteSpace: 'nowrap' }}>
                                {STAGE_META[msg.stage].badge}
                                {STAGE_META[msg.stage].hint ? ` · ${STAGE_META[msg.stage].hint}` : ''}
                              </span>
                            )}
                            {!isUser && msg.stage === 3 && msg.stageTo && (
                              <span style={{ fontSize: '10px', color: '#9ca3af' }}>→ {msg.stageTo}</span>
                            )}
                            {!isUser && agentRole && <span style={{ fontSize: '10px', color: '#9ca3af' }}>({agentRole})</span>}
                            {!isUser && agentPersonality && (
                              <span style={{ fontSize: '9px', padding: '1px 5px', borderRadius: '4px', backgroundColor: agentTheme.tagBg, color: agentTheme.accent, fontWeight: 'bold' }}>
                                {agentPersonality}
                              </span>
                            )}
                          </div>
                          <div className={`chat-bubble ${isUser ? 'user' : 'ai'}`} style={{ whiteSpace: 'pre-wrap', backgroundColor: isUser ? undefined : agentTheme.bg, border: 'none' }}>
                            {msg.content}
                          </div>
                          {/* 2차(검증) 말풍선엔 사용한 웹 근거 출처 칩을 단다 */}
                          {!isUser && msg.stage === 2 && Array.isArray(msg.sources) && msg.sources.length > 0 && (
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '4px', marginTop: '4px' }}>
                              <span style={{ fontSize: '10px', color: '#9ca3af', alignSelf: 'center' }}>근거:</span>
                              {msg.sources.slice(0, 6).map((s, si) => (
                                s.url ? (
                                  <a key={si} href={s.url} target="_blank" rel="noopener noreferrer"
                                    style={{ fontSize: '10px', padding: '1px 6px', borderRadius: '4px', backgroundColor: 'rgba(0,0,0,0.05)', color: 'var(--color-text-muted)', textDecoration: 'none' }}>
                                    {s.source}{s.title ? ` · ${String(s.title).slice(0, 24)}` : ''}
                                  </a>
                                ) : (
                                  <span key={si} style={{ fontSize: '10px', padding: '1px 6px', borderRadius: '4px', backgroundColor: 'rgba(0,0,0,0.05)', color: 'var(--color-text-muted)' }}>
                                    {s.source}{s.title ? ` · ${String(s.title).slice(0, 24)}` : ''}
                                  </span>
                                )
                              ))}
                            </div>
                          )}
                          {/* 3차(피드백) 말풍선엔 성격 검증 점수 배지 */}
                          {!isUser && msg.stage === 3 && msg.pv && typeof msg.pv.score === 'number' && (
                            <div style={{ marginTop: '4px', fontSize: '10px', color: msg.pv.passed ? '#16a34a' : '#dc2626' }}>
                              성격 검증 {msg.pv.score.toFixed(2)} {msg.pv.passed ? '통과' : '보완 필요'}
                            </div>
                          )}
                          {/* 단계 말풍선이 아닌(레거시/단일) 메시지에만 상세과정 아코디언 유지 */}
                          {!isUser && !msg.stage && <ProcessStepsAccordion processSteps={msg.processSteps} />}
                          <div className="chat-bubble-time">{formatTime(msg.createdAt)}</div>
                        </div>
                      );
                    })
                  )}
                  {typingRooms[getAgentId(selectedAgent)] && (
                    <div className="chat-bubble-container ai">
                      <div className="chat-bubble-sender"><StagedTypingLabel /></div>
                      <div className="chat-bubble ai" style={{ padding: '12px 16px', display: 'flex', alignItems: 'center', gap: 4 }}>
                        <span className="dot" /><span className="dot" /><span className="dot" />
                      </div>
                    </div>
                  )}
                  <div ref={chatEndRef} />
                </div>
              )}

              {/* ── 마인드맵 뷰 ── */}
              {viewTab === 'mindmap' && (
                <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
                  <AgentDiscussionThread
                    messages={chatHistory}
                    typingAgents={
                      typingRooms[getAgentId(selectedAgent)]
                        ? (selectedAgent.agents || [{ id: 'ai', name: selectedAgent.name || 'AI' }]).map((ag, i) => ({
                            id: ag.id || i,
                            name: ag.name,
                            color: ['#2563eb','#EA580C','#7C3AED'][i % 3],
                          }))
                        : []
                    }
                    agents={selectedAgent.agents || []}
                    bookmarkedIds={bookmarkedIds}
                    onBookmark={handleBookmark}
                    onRequestDetail={(disc, actionType = 'detail') => {
                      pendingDetailParentId.current = disc.id;
                      
                      // 사용자의 질문 노드에서 파생될 경우와 AI 노드에서 파생될 경우 문구 분리
                      const isUserNode = disc.sender === 'USER';
                      const senderName = disc.senderName || disc.sender_name || 'AI';
                      
                      // 내용을 25자 정도로 요약해서 프롬프트에 직접 포함하여 문맥 상실 방지
                      const contentExcerpt = disc.content 
                          ? (disc.content.length > 25 ? disc.content.substring(0, 25).replace(/\n/g, ' ') + '...' : disc.content.replace(/\n/g, ' '))
                          : '';

                      let promptText = '';
                      if (isUserNode) {
                        promptText = `@모두 여기에 덧붙여서 하나 더 궁금한 게 있는데, `;
                      } else {
                        if (actionType === 'criticize') {
                          promptText = `@모두 방금 ${senderName}가 말한 "${contentExcerpt}" 이 내용에 대해 각자의 관점에서 단점이나 문제점을 비판하고 반박해 줄래?`;
                        } else if (actionType === 'compare') {
                          promptText = `@모두 방금 ${senderName}가 말한 "${contentExcerpt}" 이 내용과 다른 개념을 대조하거나 각자의 의견과 어떻게 다른지 비교 분석해 줄래?`;
                        } else if (actionType === 'support') {
                          promptText = `@모두 방금 ${senderName}가 말한 "${contentExcerpt}" 이 내용에 전적으로 동의하며, 실무적인 추가 예시를 들어 보충 설명해 줄래?`;
                        } else {
                          promptText = `@모두 방금 ${senderName}가 말한 "${contentExcerpt}" 이 내용에 대해 각자의 특기나 관점에서 좀 더 자세히 설명해 줄래?`;
                        }
                      }
                        
                      setMessage(promptText);
                      setShowMentionPopup(true);
                      setMentionFilter(''); // 전체 목록 보여주기
                      
                      const activeId = getAgentId(selectedAgent);
                      if (activeId) setRoomDrafts((prev) => ({ ...prev, [activeId]: promptText }));

                      const inputEl = document.querySelector('.chat-input-premium input');
                      if (inputEl) inputEl.focus();

                      setToastMsg('💡 하단 입력창에 이어서 질문을 작성해주세요.');
                      setTimeout(() => setToastMsg(''), 2500);
                    }}
                  />
                </div>
              )}

              {/* ── 공통 입력창 ── */}
              <div style={{ position: 'relative', padding: '12px 20px 16px', backgroundColor: 'white', borderTop: '1px solid #f3f4f6', borderBottomLeftRadius: 16, borderBottomRightRadius: 16 }}>
                
                {/* 멘션 팝업 */}
                <AnimatePresence>
                  {showMentionPopup && selectedAgent && (
                    <motion.div 
                      initial={{ opacity: 0, y: 10, scale: 0.95 }}
                      animate={{ opacity: 1, y: 0, scale: 1 }}
                      exit={{ opacity: 0, y: 10, scale: 0.95 }}
                      transition={{ duration: 0.15 }}
                      style={{
                        position: 'absolute', bottom: '100%', left: '20px', marginBottom: '8px',
                        background: '#ffffff', border: '1px solid #e5e7eb', borderRadius: '12px',
                        boxShadow: '0 10px 25px rgba(0,0,0,0.1)', minWidth: '200px', overflow: 'hidden', zIndex: 100
                      }}
                    >
                      <ul style={{ listStyle: 'none', margin: 0, padding: '4px' }}>
                        {[{ name: '모두', color: '#60C95A' }, ...(selectedAgent.agents || [])]
                          .filter(ag => !mentionFilter || ag.name.toLowerCase().includes(mentionFilter.toLowerCase()))
                          .map((ag, idx) => (
                            <li 
                              key={idx}
                              style={{ 
                                padding: '10px 12px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '8px', 
                                fontSize: '13px', fontWeight: '600', color: '#374151', borderRadius: '8px', transition: 'background 0.2s'
                              }}
                              onMouseEnter={(e) => e.currentTarget.style.background = '#f3f4f6'}
                              onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}
                              onClick={() => {
                                const val = message;
                                const lastAtPos = val.lastIndexOf('@');
                                if (lastAtPos !== -1) {
                                  const beforeAt = val.slice(0, lastAtPos);
                                  const afterAtText = val.slice(lastAtPos);
                                  const spaceIndex = afterAtText.indexOf(' ');
                                  
                                  const afterMention = spaceIndex !== -1 ? afterAtText.slice(spaceIndex) : ' ';
                                  const newMsg = beforeAt + '@' + ag.name + afterMention;
                                  
                                  setMessage(newMsg);
                                  const activeId = getAgentId(selectedAgent);
                                  if (activeId) setRoomDrafts((prev) => ({ ...prev, [activeId]: newMsg }));
                                }
                                setShowMentionPopup(false);
                                const inputEl = document.querySelector('.chat-input-premium input');
                                if (inputEl) inputEl.focus();
                              }}
                            >
                              <div style={{ width: 24, height: 24, borderRadius: '50%', background: ag.color || '#e5e7eb', color: ag.color ? '#fff' : '#6b7280', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '12px' }}>
                                {ag.name === '모두' ? 'M' : <Bot size={13} />}
                              </div>
                              {ag.name}
                            </li>
                          ))
                        }
                      </ul>
                    </motion.div>
                  )}
                </AnimatePresence>

                <form onSubmit={sendMessage} className="chat-input-premium">
                  <input
                    type="text"
                    value={message}
                    onChange={(e) => {
                      const val = e.target.value;
                      setMessage(val);
                      
                      // 멘션 팝업 파싱 로직
                      const lastAtPos = val.lastIndexOf('@');
                      if (lastAtPos !== -1) {
                        const afterAt = val.slice(lastAtPos + 1);
                        if (!afterAt.includes(' ')) {
                          setShowMentionPopup(true);
                          setMentionFilter(afterAt);
                        } else {
                          setShowMentionPopup(false);
                        }
                      } else {
                        setShowMentionPopup(false);
                      }

                      const activeId = getAgentId(selectedAgent);
                      if (activeId) setRoomDrafts((prev) => ({ ...prev, [activeId]: val }));
                    }}
                    placeholder={viewTab === 'mindmap' ? '마인드맵으로 탐색할 질문을 입력하세요... (@를 입력해 에이전트 호출)' : '메시지를 입력해보세요... (@호출)'}
                    disabled={typingRooms[getAgentId(selectedAgent)]}
                  />
                  <button type="submit" disabled={typingRooms[getAgentId(selectedAgent)] || !message.trim()}>
                    <Send size={17} />
                  </button>
                </form>
              </div>
            </div>
          )}
        </div>

        {/* 우측 패널 토글 버튼 */}
        <button 
          onClick={() => setIsRightOpen(!isRightOpen)}
          style={{
            position: 'absolute', right: isRightOpen ? '320px' : '0', top: '50%', transform: 'translateY(-50%)', zIndex: 50,
            background: 'white', border: '1px solid #e5e7eb', borderRight: 'none', borderRadius: '12px 0 0 12px', padding: '10px 4px', cursor: 'pointer',
            boxShadow: '-4px 0 12px rgba(0,0,0,0.05)', transition: 'right 0.3s ease', display: 'flex', alignItems: 'center', justifyContent: 'center'
          }}
        >
          {isRightOpen ? <ChevronRight size={16} color="#9ca3af" /> : <ChevronLeft size={16} color="#9ca3af" />}
        </button>

        {/* ════ 3. 우측: 저장된 메모 (북마크) 패널 ════ */}
        {isRightOpen && (
          <div className="pane-right animate-fade-in" style={{ width: '320px', flexShrink: 0 }}>
            {!selectedAgent ? (
              <div className="dt-right-empty" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', color: '#9ca3af', textAlign: 'center', padding: '20px' }}>
                <Bookmark size={36} color="#e5e7eb" style={{ marginBottom: '12px' }} />
                <div style={{ fontSize: '14px', fontWeight: '600', color: '#6b7280' }}>세션을 선택하면<br/>저장된 메모가 표시됩니다</div>
              </div>
            ) : (
              <div className="dt-insight-panel" style={{ display: 'flex', flexDirection: 'column', height: '100%', padding: '20px' }}>
              
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '16px', paddingBottom: '16px', borderBottom: '1px solid rgba(0,0,0,0.05)' }}>
                <Bookmark size={20} color="#10b981" />
                <h3 style={{ 
                  margin: 0, fontSize: '15px', fontWeight: '800', color: '#334155'
                }}>저장된 메모 목록</h3>
                <span style={{ marginLeft: 'auto', background: '#ecfdf5', color: '#10b981', padding: '2px 8px', borderRadius: '12px', fontSize: '12px', fontWeight: 'bold' }}>
                  {bookmarkedIds.size}개
                </span>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', overflowY: 'auto', paddingRight: '4px', flex: 1 }}>
                {bookmarkedIds.size === 0 ? (
                  <div style={{ fontSize: '13px', color: '#9ca3af', width: '100%', textAlign: 'center', padding: '40px 0', lineHeight: '1.6' }}>
                    <Bookmark size={24} color="#f1f5f9" style={{ margin: '0 auto 12px' }} fill="#e2e8f0" />
                    유용한 답변에 <br/><strong style={{color: '#64748b'}}>📌 메모하기</strong>를 누르면<br/>이곳에 저장됩니다.
                  </div>
                ) : (
                  Array.from(bookmarkedIds).map((id) => {
                    const msg = chatHistory.find(m => m.id === id);
                    if (!msg) return null;
                    return (
                      <div 
                        key={id} 
                        onClick={() => handleScrollToNode(id)}
                        style={{ 
                          padding: '16px', 
                          background: '#ffffff', 
                          borderRadius: '12px', 
                          border: '1px solid #e2e8f0', 
                          cursor: 'pointer',
                          transition: 'all 0.2s ease',
                          boxShadow: '0 2px 4px rgba(0,0,0,0.02)'
                        }}
                        onMouseEnter={(e) => {
                          e.currentTarget.style.borderColor = '#34d399';
                          e.currentTarget.style.boxShadow = '0 4px 12px rgba(16,185,129,0.1)';
                        }}
                        onMouseLeave={(e) => {
                          e.currentTarget.style.borderColor = '#e2e8f0';
                          e.currentTarget.style.boxShadow = '0 2px 4px rgba(0,0,0,0.02)';
                        }}
                      >
                        <div style={{ fontSize: '12px', color: '#10b981', fontWeight: '700', marginBottom: '8px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                           <Bot size={14} /> {msg.senderName || msg.sender_name || 'AI'}
                        </div>
                        <div style={{ fontSize: '13px', color: '#334155', lineHeight: '1.5', display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                          "{msg.content}"
                        </div>
                      </div>
                    );
                  })
                )}
              </div>
            </div>
            )}
          </div>
        )}
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

                {/* 학습 진행 모드 선택 */}
                <div>
                  <label style={{ display: 'block', fontSize: '13px', fontWeight: '700', color: 'var(--color-text-main)', marginBottom: '6px' }}>
                    학습 진행 모드
                  </label>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    {[
                      { value: 'basic', title: '기본 채팅 모드', desc: '각 AI가 바로 답변합니다.' },
                      { value: 'socratic', title: '소크라테스 모드', desc: '정답을 바로 주기보다 질문으로 사고를 유도합니다.' },
                      { value: 'debate', title: '토론 모드', desc: 'AI들이 서로 다른 관점으로 답하고 피드백합니다.' },
                    ].map((opt) => (
                      <label
                        key={opt.value}
                        style={{
                          display: 'flex',
                          alignItems: 'flex-start',
                          gap: '10px',
                          padding: '10px 12px',
                          borderRadius: '10px',
                          border: `1px solid ${learningMode === opt.value ? 'var(--color-primary)' : 'var(--color-border)'}`,
                          backgroundColor: learningMode === opt.value ? 'var(--color-primary-soft, rgba(99,102,241,0.08))' : 'transparent',
                          cursor: 'pointer',
                        }}
                      >
                        <input
                          type="radio"
                          name="learningMode"
                          value={opt.value}
                          checked={learningMode === opt.value}
                          onChange={() => setLearningMode(opt.value)}
                          style={{ marginTop: '3px' }}
                        />
                        <div>
                          <div style={{ fontSize: '13px', fontWeight: '700', color: 'var(--color-text-main)' }}>{opt.title}</div>
                          <div style={{ fontSize: '12px', color: 'var(--color-text-muted)', marginTop: '2px' }}>{opt.desc}</div>
                        </div>
                      </label>
                    ))}
                  </div>
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
                  {getDisplayRoomTitle(selectedAgent)}
                </p>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                {(selectedAgent.agents && selectedAgent.agents.length > 0 ? selectedAgent.agents : [selectedAgent]).map((ag, idx) => {
                  const agPersonality = getAgentPersonality(ag);
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
                        </div>
                      </div>

                      {(() => {
                        const basePersona = ag.customInstruction || ag.custom_instruction || ag.persona || '';
                        const cleanedPersona = basePersona.replace('사용자의 학습을 돕는다', '').trim();
                        // 대괄호 태그들만 남고 알맹이가 없는 경우 노출하지 않음
                        const hasRealContent = ag.customInstruction || ag.custom_instruction || (cleanedPersona.replace(/\[지식수준:[^\]]+\]/, '').replace(/\[성격:[^\]]+\]/, '').trim().length > 0);
                        if (!hasRealContent) return null;

                        return (
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
                              {ag.customInstruction || ag.custom_instruction || cleanedPersona}
                            </div>
                          </div>
                        );
                      })()}
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
