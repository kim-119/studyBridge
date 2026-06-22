import React, { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Bot, User, Network, Bookmark, RefreshCw,
  Brain, CheckCircle2, Zap, MessageSquare,
  ChevronDown, ChevronUp, ChevronLeft, ChevronRight, ZoomIn, ZoomOut
} from 'lucide-react';
import RichText from './RichText';
import './studymate-premium.css';

// ── 토론 노드 전용 상수 ─────────────────────────────────────────────────────────
// 색상 규칙: PRO=초록 / CON=주황 / NEUTRAL·JUDGE=보라 / TOPIC=파랑
const DEBATE_COLOR = {
  PRO:     { accent: '#059669', bg: '#ecfdf5', badgeBg: '#D1FAE5' },
  CON:     { accent: '#ea580c', bg: '#fff7ed', badgeBg: '#FFEDD5' },
  NEUTRAL: { accent: '#7c3aed', bg: '#f5f3ff', badgeBg: '#EDE9FE' },
  JUDGE:   { accent: '#7c3aed', bg: '#f5f3ff', badgeBg: '#EDE9FE' },
  TOPIC:   { accent: '#2563eb', bg: '#eff6ff', badgeBg: '#DBEAFE' },
};
const debateColor = (side) => DEBATE_COLOR[side] || DEBATE_COLOR.TOPIC;

// 연결선 라벨 규칙 (토론 모드에서는 "피드백" 금지)
const DEBATE_EDGE_LABEL = {
  TOPIC: '논제',
  OPENING_STATEMENT: '입론',
  NEUTRAL_ANALYSIS: '쟁점 정리',
  REBUTTAL: '반박',
  CROSS_REBUTTAL: '재반박',
  NEUTRAL_CHECK: '검토',
  CLOSING_STATEMENT: '최종 변론',
  JUDGEMENT: '판정',
};

// stageType+side별 맞춤 액션 버튼
const DEBATE_ACTIONS = {
  TOPIC: [
    { label: '찬성 근거 만들기', actionType: 'pro_argument' },
    { label: '반대 근거 만들기', actionType: 'con_argument' },
    { label: '쟁점 정리', actionType: 'issue_summary' },
    { label: '판정 요청', actionType: 'judge' },
  ],
  OPENING_STATEMENT_PRO: [
    { label: '반대측 반박 요청', actionType: 'con_rebut' },
    { label: '근거 보강', actionType: 'strengthen_pro' },
    { label: '예외 조건 찾기', actionType: 'find_exception' },
  ],
  OPENING_STATEMENT_CON: [
    { label: '찬성측 반박 요청', actionType: 'pro_rebut' },
    { label: '근거 보강', actionType: 'strengthen_con' },
    { label: '반례 찾기', actionType: 'find_counterexample' },
  ],
  REBUTTAL_PRO: [
    { label: '반대측 재반박', actionType: 'con_cross_rebut' },
    { label: '논리 허점 검사', actionType: 'check_logic_gap' },
    { label: '근거 추가', actionType: 'add_evidence' },
  ],
  REBUTTAL_CON: [
    { label: '찬성측 재반박', actionType: 'pro_cross_rebut' },
    { label: '논리 허점 검사', actionType: 'check_logic_gap' },
    { label: '근거 추가', actionType: 'add_evidence' },
  ],
  CROSS_REBUTTAL_PRO: [
    { label: '심사위원 판정', actionType: 'judge' },
    { label: '논리 허점 검사', actionType: 'check_logic_gap' },
    { label: '근거 추가', actionType: 'add_evidence' },
  ],
  CROSS_REBUTTAL_CON: [
    { label: '심사위원 판정', actionType: 'judge' },
    { label: '논리 허점 검사', actionType: 'check_logic_gap' },
    { label: '근거 추가', actionType: 'add_evidence' },
  ],
  CLOSING_STATEMENT: [
    { label: '심사위원 판정', actionType: 'judge' },
    { label: '설득력 강화', actionType: 'improve_persuasion' },
    { label: '핵심 요약', actionType: 'summarize_claim' },
  ],
  NEUTRAL_ANALYSIS: [
    { label: '판정 요청', actionType: 'judge' },
    { label: '쟁점 정리', actionType: 'issue_summary' },
    { label: '학습 요약', actionType: 'learning_summary' },
  ],
  NEUTRAL_CHECK: [
    { label: '심사위원 판정', actionType: 'judge' },
    { label: '논리 허점 검사', actionType: 'check_logic_gap' },
    { label: '학습 요약', actionType: 'learning_summary' },
  ],
  JUDGEMENT: [
    { label: '판정 근거 자세히', actionType: 'explain_judgement' },
    { label: '반대 판정 가능성', actionType: 'alternative_judgement' },
    { label: '학습 요약', actionType: 'learning_summary' },
  ],
};

const getDebateActions = (node) => {
  const st = node.stageType;
  const side = node.side;
  if (st === 'TOPIC') return DEBATE_ACTIONS.TOPIC;
  if (st === 'JUDGEMENT') return DEBATE_ACTIONS.JUDGEMENT;
  if (st === 'NEUTRAL_ANALYSIS') return DEBATE_ACTIONS.NEUTRAL_ANALYSIS;
  if (st === 'NEUTRAL_CHECK') return DEBATE_ACTIONS.NEUTRAL_CHECK;
  if (st === 'CLOSING_STATEMENT') return DEBATE_ACTIONS.CLOSING_STATEMENT;
  return DEBATE_ACTIONS[`${st}_${side}`] || [];
};

// ── 소크라테스 노드 전용 상수 ────────────────────────────────────────────────────
// 색상: 진단/핵심개념=파랑, 오개념/반례=주황, 힌트=노랑, 적용=초록, 자기설명=청록, 정리=보라
const SOCRATIC_COLOR = {
  SESSION:            { accent: '#0ea5e9', bg: '#f0f9ff', badgeBg: '#e0f2fe' },
  DIAGNOSIS:          { accent: '#2563eb', bg: '#eff6ff', badgeBg: '#DBEAFE' },
  CORE_CONCEPT:       { accent: '#2563eb', bg: '#eff6ff', badgeBg: '#DBEAFE' },
  MISCONCEPTION_CHECK:{ accent: '#ea580c', bg: '#fff7ed', badgeBg: '#FFEDD5' },
  COUNTEREXAMPLE:     { accent: '#ea580c', bg: '#fff7ed', badgeBg: '#FFEDD5' },
  HINT:               { accent: '#ca8a04', bg: '#fefce8', badgeBg: '#FEF9C3' },
  APPLICATION:        { accent: '#059669', bg: '#ecfdf5', badgeBg: '#D1FAE5' },
  SELF_EXPLANATION:   { accent: '#0d9488', bg: '#f0fdfa', badgeBg: '#CCFBF1' },
  SUMMARY:            { accent: '#7c3aed', bg: '#f5f3ff', badgeBg: '#EDE9FE' },
  NEXT_STUDY_PLAN:    { accent: '#7c3aed', bg: '#f5f3ff', badgeBg: '#EDE9FE' },
};
const socraticColor = (stageType) => SOCRATIC_COLOR[stageType] || SOCRATIC_COLOR.SESSION;

const SOCRATIC_EDGE_LABEL = {
  SESSION: '세션',
  DIAGNOSIS: '진단', CORE_CONCEPT: '핵심 개념', MISCONCEPTION_CHECK: '오개념',
  HINT: '힌트', APPLICATION: '적용', COUNTEREXAMPLE: '반례',
  SELF_EXPLANATION: '자기 설명', SUMMARY: '정리', NEXT_STUDY_PLAN: '다음 학습',
};

const SOCRATIC_ACTIONS = {
  DIAGNOSIS: [
    { label: '더 쉬운 질문', actionType: 'easier_question' },
    { label: '더 어려운 질문', actionType: 'harder_question' },
    { label: '예시로 질문', actionType: 'example_question' },
  ],
  CORE_CONCEPT: [
    { label: '더 쉬운 질문', actionType: 'easier_question' },
    { label: '힌트 요청', actionType: 'request_hint' },
    { label: '반례 질문', actionType: 'counterexample_question' },
  ],
  MISCONCEPTION_CHECK: [
    { label: '힌트 요청', actionType: 'request_hint' },
    { label: '반례 질문', actionType: 'counterexample_question' },
    { label: '다시 설명 유도', actionType: 're_explain' },
  ],
  HINT: [
    { label: '다음 힌트', actionType: 'next_hint' },
    { label: '예시 힌트', actionType: 'example_hint' },
    { label: '정답 일부 보기', actionType: 'reveal_partial' },
  ],
  APPLICATION: [
    { label: '코드 예제로 적용', actionType: 'apply_code' },
    { label: '실무 사례로 적용', actionType: 'apply_practical' },
    { label: '시험 문제로 바꾸기', actionType: 'to_exam' },
  ],
  COUNTEREXAMPLE: [
    { label: '힌트 요청', actionType: 'request_hint' },
    { label: '다시 설명 유도', actionType: 're_explain' },
    { label: '적용 질문', actionType: 'apply_practical' },
  ],
  SELF_EXPLANATION: [
    { label: '내 답변 평가', actionType: 'evaluate_answer' },
    { label: '부족한 개념 찾기', actionType: 'find_weakness' },
    { label: '다음 질문 만들기', actionType: 'next_question' },
  ],
  SUMMARY: [
    { label: '학습 계획 만들기', actionType: 'make_study_plan' },
    { label: '퀴즈 생성', actionType: 'make_quiz' },
    { label: '복습 질문 만들기', actionType: 'make_review' },
  ],
  SESSION: [
    { label: '더 쉬운 질문', actionType: 'easier_question' },
    { label: '학습 계획 만들기', actionType: 'make_study_plan' },
  ],
};
const getSocraticActions = (node) => SOCRATIC_ACTIONS[node.stageType] || SOCRATIC_ACTIONS.SESSION;

const SIMULATION_COLOR = {
  SESSION: { accent: '#1d4ed8', bg: '#eff6ff', badgeBg: '#dbeafe' },
  SCENARIO_SETUP: { accent: '#1d4ed8', bg: '#eff6ff', badgeBg: '#dbeafe' },
  USER_ROLE: { accent: '#7c3aed', bg: '#f5f3ff', badgeBg: '#ede9fe' },
  SITUATION_CONTEXT: { accent: '#0d9488', bg: '#f0fdfa', badgeBg: '#ccfbf1' },
  CHOICES: { accent: '#059669', bg: '#ecfdf5', badgeBg: '#d1fae5' },
  CHOICE: { accent: '#059669', bg: '#ecfdf5', badgeBg: '#d1fae5' },
  SELECTED_CHOICE: { accent: '#059669', bg: '#ecfdf5', badgeBg: '#d1fae5' },
  CONSEQUENCE: { accent: '#ea580c', bg: '#fff7ed', badgeBg: '#ffedd5' },
  CONSEQUENCE_PREVIEW: { accent: '#ea580c', bg: '#fff7ed', badgeBg: '#ffedd5' },
  CONCEPT_MAPPING: { accent: '#2563eb', bg: '#eff6ff', badgeBg: '#dbeafe' },
  CONCEPT_EXPLANATION: { accent: '#2563eb', bg: '#eff6ff', badgeBg: '#dbeafe' },
  MISCONCEPTION_TRAP: { accent: '#dc2626', bg: '#fef2f2', badgeBg: '#fee2e2' },
  RISK_OR_LIMITATION: { accent: '#dc2626', bg: '#fef2f2', badgeBg: '#fee2e2' },
  REFLECTION_QUESTION: { accent: '#ca8a04', bg: '#fefce8', badgeBg: '#fef9c3' },
  NEXT_SCENARIO: { accent: '#4c1d95', bg: '#faf5ff', badgeBg: '#ede9fe' },
  NEXT_BRANCH: { accent: '#4c1d95', bg: '#faf5ff', badgeBg: '#ede9fe' },
};
const simulationColor = (stageType) => SIMULATION_COLOR[stageType] || SIMULATION_COLOR.SESSION;

const SIMULATION_EDGE_LABEL = {
  SESSION: '세션', SCENARIO_SETUP: '상황 설정', USER_ROLE: '나의 역할', SITUATION_CONTEXT: '문제 상황',
  CHOICES: '선택지', CHOICE: '선택', SELECTED_CHOICE: '선택한 행동', CONSEQUENCE: '선택 결과',
  CONSEQUENCE_PREVIEW: '결과 변화', CONCEPT_MAPPING: '개념 연결', CONCEPT_EXPLANATION: '개념 설명',
  MISCONCEPTION_TRAP: '오개념 함정', RISK_OR_LIMITATION: '위험과 한계', REFLECTION_QUESTION: '성찰 질문',
  NEXT_SCENARIO: '다음 분기', NEXT_BRANCH: '다음 사건',
};

const SIMULATION_ACTIONS = {
  SCENARIO_SETUP: [
    { label: '배경 더 자세히', actionType: 'expand_background' },
    { label: '더 쉬운 상황으로', actionType: 'easier_scenario' },
    { label: '더 어려운 상황으로', actionType: 'harder_scenario' },
  ],
  USER_ROLE: [
    { label: '내 역할 바꾸기', actionType: 'change_role' },
    { label: '관찰자 시점으로 보기', actionType: 'observer_view' },
    { label: '의사결정자 시점으로 보기', actionType: 'decision_view' },
  ],
  CHOICES: [
    { label: '다음 분기 진행', actionType: 'next_branch' },
    { label: '난이도 올리기', actionType: 'raise_difficulty' },
    { label: '다른 분야로 바꾸기', actionType: 'change_domain' },
  ],
  CHOICE: [
    { label: '이 선택하기', actionType: 'choose' },
    { label: '결과 미리보기', actionType: 'preview' },
    { label: '위험 분석', actionType: 'risk' },
  ],
  CONSEQUENCE: [
    { label: '왜 이런 결과인지', actionType: 'why_result' },
    { label: '다른 선택과 비교', actionType: 'compare_choices' },
    { label: '개념으로 연결', actionType: 'connect_concept' },
  ],
  CONCEPT_MAPPING: [
    { label: '핵심 개념 정리', actionType: 'summarize_concept' },
    { label: '다른 사례로 확장', actionType: 'expand_case' },
    { label: '전공 맥락으로 연결', actionType: 'major_context' },
  ],
  MISCONCEPTION_TRAP: [
    { label: '오개념 더 파기', actionType: 'dig_trap' },
    { label: '반례 보기', actionType: 'counterexample' },
    { label: '안전한 판단 기준', actionType: 'safe_rule' },
  ],
  REFLECTION_QUESTION: [
    { label: '힌트 받기', actionType: 'hint' },
    { label: '내 답변 평가', actionType: 'evaluate_reflection' },
    { label: '다음 질문 생성', actionType: 'next_question' },
  ],
  NEXT_SCENARIO: [
    { label: '다음 분기 진행', actionType: 'next_branch' },
    { label: '난이도 올리기', actionType: 'raise_difficulty' },
    { label: '다른 분야로 바꾸기', actionType: 'change_domain' },
  ],
  NEXT_BRANCH: [
    { label: '다음 분기 진행', actionType: 'next_branch' },
    { label: '난이도 올리기', actionType: 'raise_difficulty' },
    { label: '다른 분야로 바꾸기', actionType: 'change_domain' },
  ],
  SESSION: [
    { label: '배경 더 자세히', actionType: 'expand_background' },
    { label: '다음 분기 진행', actionType: 'next_branch' },
  ],
};
const getSimulationActions = (node) => SIMULATION_ACTIONS[node.stageType] || SIMULATION_ACTIONS.SESSION;

/**
 * AgentDiscussionThread
 *
 * Top-Down Flowchart (Mindmap) Thread UI
 * Features: True parallel horizontal branching, Y-axis scrolling, accordion expansion.
 */
export default function AgentDiscussionThread({
  messages = [],
  typingAgents = [],
  agents = [],
  bookmarkedIds = new Set(),
  onBookmark,
  onRequestDetail,
  focusAgentName = null,
}) {
  const containerRef = useRef(null);
  
  // 아코디언 상태 관리 (Set of expanded node IDs)
  const [expandedNodes, setExpandedNodes] = useState(new Set());
  // 논제/토론 액션 패널을 넓게 펼친 노드 집합(노드별 토글). 기본은 컴팩트(가로 스크롤).
  const [wideActionNodes, setWideActionNodes] = useState(new Set());
  const toggleWideActions = (nodeId) => {
    setWideActionNodes((prev) => {
      const next = new Set(prev);
      if (next.has(nodeId)) next.delete(nodeId); else next.add(nodeId);
      return next;
    });
  };

  // 확대/축소 상태 관리
  const [zoom, setZoom] = useState(1);

  // 새 메시지가 오면 자동으로 확장
  useEffect(() => {
    if (messages.length > 0) {
      const lastMsg = messages[messages.length - 1];
      setExpandedNodes(prev => {
        const next = new Set(prev);
        next.add(lastMsg.id);
        return next;
      });
    }
  }, [messages]);

  // 타이핑 중인 에이전트도 자동으로 확장
  useEffect(() => {
    if (typingAgents.length > 0) {
      setExpandedNodes(prev => {
        const next = new Set(prev);
        typingAgents.forEach((ag, idx) => next.add(`typing-${ag.name}-${idx}`));
        return next;
      });
    }
  }, [typingAgents]);

  const toggleExpand = (id) => {
    setExpandedNodes(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const AGENT_COLORS = [
    { accent: '#2563eb', bg: 'rgba(37,99,235,0.08)',  badgeBg: '#DBEAFE' },
    { accent: '#ea580c', bg: 'rgba(234,88,12,0.08)',  badgeBg: '#FFEDD5' },
    { accent: '#7c3aed', bg: 'rgba(124,58,237,0.08)', badgeBg: '#EDE9FE' },
    { accent: '#059669', bg: 'rgba(5,150,105,0.08)',  badgeBg: '#D1FAE5' },
    { accent: '#e11d48', bg: 'rgba(225,29,72,0.08)',  badgeBg: '#FFE4E6' },
  ];

  const getAgentColor = (senderName) => {
    const idx = agents.findIndex((ag) => ag.name === senderName);
    return AGENT_COLORS[(idx >= 0 ? idx : 0) % AGENT_COLORS.length];
  };

  const roots = [];
  const nodeMap = new Map();
  let lastUserNode = null;

  messages.forEach((msg) => {
    const node = { ...msg, children: [] };
    nodeMap.set(node.id, node);

    if (node.parentId && nodeMap.has(node.parentId)) {
      nodeMap.get(node.parentId).children.push(node);
    } else {
      if (node.sender === 'USER') {
        let parent = null;
        const isMention = node.content.includes('@');
        const isEveryone = node.content.includes('@모두');
        const isDetail = node.content.includes('자세히');

        if (isMention && !isEveryone) {
          const names = Array.from(new Set(messages.filter(m => m.sender !== 'USER').map(m => m.senderName || m.sender_name).filter(Boolean)));
          let mentionedAgent = null;
          for (let name of names) {
            if (node.content.includes(`@${name}`)) {
              mentionedAgent = name;
              break;
            }
          }
          if (mentionedAgent) {
            for (let i = messages.indexOf(msg) - 1; i >= 0; i--) {
              const prevMsg = messages[i];
              const senderName = prevMsg.senderName || prevMsg.sender_name;
              if (prevMsg.sender !== 'USER' && senderName === mentionedAgent) {
                parent = nodeMap.get(prevMsg.id);
                break;
              }
            }
          }
        }

        if (!parent && (isMention || isEveryone || isDetail)) {
          if (lastUserNode) {
            parent = nodeMap.get(lastUserNode.id);
          }
        }

        if (parent) {
          parent.children.push(node);
        } else {
          roots.push(node);
        }
        lastUserNode = node;
      } else {
        // AI 메시지 처리
        let aiParent = null;
        
        // 역순으로 탐색하여 이전 에이전트의 이름을 언급했는지(피드백인지) 확인
        for (let i = messages.indexOf(msg) - 1; i >= 0; i--) {
            const prevMsg = messages[i];
            if (prevMsg.sender === 'USER') break; // 사용자 메시지를 만나면 탐색 중단 (같은 분기 내에서만 확인)
            
            const prevName = prevMsg.senderName || prevMsg.sender_name;
            if (prevName && (node.content.includes(prevName) || (prevName.length > 2 && node.content.includes(prevName.substring(1))))) {
                aiParent = nodeMap.get(prevMsg.id);
                break;
            }
        }
        
        if (aiParent) {
            aiParent.children.push(node); // 피드백 대상의 '자식'으로 추가하여 수직 구조 형성
        } else if (lastUserNode) {
            lastUserNode.children.push(node);
        } else {
            roots.push(node);
        }
      }
    }
  });

  // 타이핑 중인 에이전트를 마인드맵 노드에 직접 추가하지 않음 (대신 좌측 하단 플로팅 UI로 표시)

  // 메시지가 추가되면 하단/우측으로 스크롤 여유를 줌
  useEffect(() => {
    if (containerRef.current) {
      setTimeout(() => {
        const el = containerRef.current;
        el.scrollTo({
          top: el.scrollHeight,
          behavior: 'smooth'
        });
      }, 100);
    }
  }, [messages.length, typingAgents.length]);



  const formatTime = (isoString) => {
    if (!isoString) return '';
    const d = new Date(isoString);
    return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  };

  /**
   * 재귀적으로 조직도(Flowchart) 트리를 그리는 함수
   */
  const renderFlowchartNode = (node, depth = 0) => {
    const isUser = node.sender === 'USER';
    const isDebate = node.nodeType === 'debate';
    const isSocratic = node.nodeType === 'socratic';
    const isSimulation = node.nodeType === 'simulation';
    const color = isUser
      ? { accent: '#10b981', bg: '#ecfdf5' }
      : isDebate
        ? debateColor(node.side)
        : isSocratic
          ? socraticColor(node.stageType)
          : isSimulation
            ? simulationColor(node.stageType)
            : getAgentColor(node.senderName || node.sender_name);
    const isBookmarked = bookmarkedIds.has(node.id);
    const isExpanded = expandedNodes.has(node.id) || node.isTyping;
    const isRoot = depth === 0;

    // 교수님들과 대화 대상 강조/흐림: 에이전트(일반) 답변 노드에만 적용한다.
    const nodeSenderName = node.senderName || node.sender_name;
    const isAgentAnswerNode = !isUser && !isDebate && !isSocratic && !isSimulation && !!nodeSenderName;
    const focusClass = (focusAgentName && isAgentAnswerNode)
      ? (nodeSenderName === focusAgentName ? 'professor-thread-node is-focused' : 'professor-thread-node is-dimmed')
      : '';

    return (
        <div id={`node-${node.id}`} key={node.id} className={focusClass} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            
            {/* 1) 현재 노드 카드 */}
            <motion.div
              layout
              onClick={() => toggleExpand(node.id)}
              style={{
                width: isRoot ? '400px' : '340px',
                backgroundColor: isUser ? (isRoot ? '#f0fdf4' : '#f8fafc') : ((isDebate || isSocratic || isSimulation) ? color.bg : '#ffffff'),
                border: isUser
                  ? (isRoot ? '2px solid rgba(16,185,129,0.4)' : '1px solid rgba(16,185,129,0.3)')
                  : (isDebate || isSocratic || isSimulation) ? `1.5px solid ${color.accent}55` : '1px solid #e2e8f0',
                borderRadius: '16px',
                padding: '16px',
                boxShadow: isExpanded 
                   ? (isRoot ? '0 12px 36px rgba(16,185,129,0.12)' : '0 8px 24px rgba(0,0,0,0.06)')
                   : '0 2px 8px rgba(0,0,0,0.03)',
                cursor: 'pointer',
                position: 'relative',
                zIndex: 2,
                flexShrink: 0
              }}
              onMouseEnter={(e) => {
                e.currentTarget.style.boxShadow = isRoot 
                  ? '0 16px 40px rgba(16,185,129,0.15)'
                  : '0 12px 32px rgba(0,0,0,0.08)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.boxShadow = isExpanded 
                   ? (isRoot ? '0 12px 36px rgba(16,185,129,0.12)' : '0 8px 24px rgba(0,0,0,0.06)')
                   : '0 2px 8px rgba(0,0,0,0.03)';
              }}
            >
              {/* 헤더 영역 (항상 노출) */}
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '8px' }}>
                 <div style={{
                    width: '28px', height: '28px', borderRadius: '8px', flexShrink: 0,
                    background: isUser ? 'linear-gradient(135deg, #10b981, #059669)' : `linear-gradient(135deg, ${color.accent}15, ${color.accent}30)`, 
                    color: isUser ? '#fff' : color.accent, 
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    fontSize: '13px', fontWeight: '800',
                    border: isUser ? 'none' : `1px solid ${color.accent}40`
                 }}>
                    {isUser ? <User size={14} /> : <Bot size={14} />}
                 </div>
                 
                 {(isDebate || isSocratic || isSimulation) ? (
                   <>
                     {/* 토론/소크라테스/상황극 노드: senderName보다 stageTitle을 강조한다 */}
                     <span style={{ fontWeight: '800', fontSize: '14px', color: color.accent, letterSpacing: '-0.3px', flexShrink: 0 }}>
                        {node.stageTitle}
                     </span>
                     {node.agentName && node.stageType !== 'TOPIC' && node.stageType !== 'SESSION' && (
                        <span style={{ color: color.accent, background: color.badgeBg, border: `1px solid ${color.accent}30`, fontSize: '10px', padding: '2px 7px', borderRadius: '99px', fontWeight: '700', flexShrink: 0 }}>
                          · {node.agentName}
                        </span>
                     )}
                   </>
                 ) : (
                   <>
                     <span style={{ fontWeight: '800', fontSize: '14px', color: '#0f172a', letterSpacing: '-0.3px', flexShrink: 0 }}>
                        {isUser ? (isRoot ? '나의 질문' : '나 (추가 질문)') : (node.senderName || node.sender_name || 'AI')}
                     </span>

                     {!isUser && (
                        <span style={{ color: color.accent, background: 'rgba(255,255,255,0.7)', border: `1px solid ${color.accent}30`, fontSize: '10px', padding: '2px 6px', borderRadius: '99px', fontWeight: '700', flexShrink: 0 }}>
                          {node.actionType || '의견'}
                        </span>
                     )}
                   </>
                 )}

                 {isBookmarked && !isUser && (
                    <div style={{ marginLeft: '4px', background: '#f0fdf4', color: '#16a34a', padding: '2px 6px', borderRadius: '8px', fontSize: '10px', display: 'flex', alignItems: 'center', gap: '4px', fontWeight: '800', flexShrink: 0, border: '1px solid #16a34a' }}>
                      <Bookmark size={10} fill="#16a34a" /> 메모됨
                    </div>
                 )}

                 <div style={{ marginLeft: 'auto', color: '#94a3b8', display: 'flex', alignItems: 'center' }}>
                    {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                 </div>
              </div>

              {/* 콘텐츠 영역 (컴팩트일 땐 2줄 요약, 확장 시 전체 노출) */}
              <motion.div layout="position">
                 <div style={{
                   fontSize: '13.5px',
                   color: isUser ? '#166534' : '#334155',
                   lineHeight: '1.6',
                   whiteSpace: 'pre-wrap',
                   overflowWrap: 'anywhere',
                   // 확장 시 전체 노출(잘림 없음), 컴팩트일 때만 2줄 미리보기
                   ...(isExpanded
                     ? { height: 'auto', maxHeight: 'none', overflow: 'visible' }
                     : { display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' })
                 }}>
                   {node.isTyping ? (
                      <div style={{ display: 'flex', gap: '4px', padding: '4px 0' }}>
                        <span style={{ animation: 'pulseDot 1.4s infinite ease-in-out both', animationDelay: '-0.32s', width: '6px', height: '6px', background: color.accent, borderRadius: '50%' }} />
                        <span style={{ animation: 'pulseDot 1.4s infinite ease-in-out both', animationDelay: '-0.16s', width: '6px', height: '6px', background: color.accent, borderRadius: '50%' }} />
                        <span style={{ animation: 'pulseDot 1.4s infinite ease-in-out both', width: '6px', height: '6px', background: color.accent, borderRadius: '50%' }} />
                      </div>
                   ) : (
                      <RichText text={node.content} />
                   )}
                 </div>
              </motion.div>

              {/* 액션 버튼 (확장 시에만 노출) */}
              <AnimatePresence>
                 {isExpanded && !node.isTyping && (
                     <motion.div 
                        initial={{ height: 0, opacity: 0 }} 
                        animate={{ height: 'auto', opacity: 1 }} 
                        exit={{ height: 0, opacity: 0 }} 
                        transition={{ duration: 0.2 }}
                        style={{ overflow: 'hidden' }}
                     >
                         <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', marginTop: '12px', paddingTop: '12px', borderTop: isUser ? '1px dashed rgba(16,185,129,0.3)' : '1px solid #f1f5f9' }}>
                            {!isUser && (
                              <button
                                onClick={(e) => { e.stopPropagation(); onBookmark?.(node); }}
                                style={{ 
                                  display: 'flex', alignItems: 'center', gap: '4px', padding: '6px 12px', borderRadius: '8px', fontSize: '12px', fontWeight: '700', 
                                  border: isBookmarked ? '1px solid #16a34a' : '1px solid #e2e8f0', 
                                  background: isBookmarked ? '#f0fdf4' : '#ffffff', 
                                  color: isBookmarked ? '#16a34a' : '#64748b', 
                                  cursor: 'pointer', transition: 'all 0.2s ease',
                                  boxShadow: isBookmarked ? '0 2px 8px rgba(22,163,74,0.1)' : '0 1px 2px rgba(0,0,0,0.02)'
                                }}
                              >
                                <Bookmark size={13} fill={isBookmarked ? "#16a34a" : "none"} />
                                {isBookmarked ? '메모됨' : '메모하기'}
                              </button>
                            )}
                            {!isDebate && !isSocratic && !isSimulation && (
                              <button
                                onClick={(e) => { e.stopPropagation(); onRequestDetail?.(node, isUser ? 'question' : 'detail'); }}
                                style={{
                                  display: 'flex', alignItems: 'center', gap: '4px', padding: '6px 12px', borderRadius: '8px', fontSize: '12px', fontWeight: '700',
                                  border: isUser ? '1px solid #34d399' : '1px solid #e2e8f0',
                                  background: isUser ? '#ecfdf5' : '#ffffff',
                                  color: isUser ? '#059669' : '#64748b',
                                  cursor: 'pointer', transition: 'all 0.2s ease',
                                  boxShadow: '0 1px 2px rgba(0,0,0,0.02)'
                                }}
                              >
                                {isUser ? <MessageSquare size={13} /> : <RefreshCw size={13} />}
                                {isUser ? '추가 질문 연결' : '더 자세히'}
                              </button>
                            )}

                            {!isUser && !isDebate && !isSocratic && !isSimulation && (
                              <>
                                <button
                                  onClick={(e) => { e.stopPropagation(); onRequestDetail?.(node, 'criticize'); }}
                                  style={{ display: 'flex', alignItems: 'center', gap: '4px', padding: '6px 10px', borderRadius: '8px', fontSize: '12px', fontWeight: '700', border: '1px solid #fecdd3', background: '#fff1f2', color: '#e11d48', cursor: 'pointer', boxShadow: '0 1px 2px rgba(0,0,0,0.02)' }}
                                >
                                  ⚔️ 반박
                                </button>
                                <button
                                  onClick={(e) => { e.stopPropagation(); onRequestDetail?.(node, 'compare'); }}
                                  style={{ display: 'flex', alignItems: 'center', gap: '4px', padding: '6px 10px', borderRadius: '8px', fontSize: '12px', fontWeight: '700', border: '1px solid #ddd6fe', background: '#f5f3ff', color: '#7c3aed', cursor: 'pointer', boxShadow: '0 1px 2px rgba(0,0,0,0.02)' }}
                                >
                                  ⚖️ 비교
                                </button>
                                <button
                                  onClick={(e) => { e.stopPropagation(); onRequestDetail?.(node, 'support'); }}
                                  style={{ display: 'flex', alignItems: 'center', gap: '4px', padding: '6px 10px', borderRadius: '8px', fontSize: '12px', fontWeight: '700', border: '1px solid #fef08a', background: '#fefce8', color: '#ca8a04', cursor: 'pointer', boxShadow: '0 1px 2px rgba(0,0,0,0.02)' }}
                                >
                                  💡 예시
                                </button>
                              </>
                            )}
                            <span style={{ marginLeft: 'auto', alignSelf: 'center', fontSize: '11px', color: '#9ca3af', fontWeight: '500' }}>
                              {formatTime(node.createdAt)}
                            </span>
                         </div>

                         {/* 논제/토론 액션 패널: 토론 모드 카드와 시각적으로 분리(중립 슬레이트 토큰)하고
                             좁은 화면에서 버튼이 잘리지 않게 펼치기(<>)로 wrap 전환한다. (문제3) */}
                         {(isDebate || isSocratic || isSimulation) && (() => {
                            const acts = isDebate ? getDebateActions(node)
                              : isSocratic ? getSocraticActions(node)
                                : getSimulationActions(node);
                            if (!acts || acts.length === 0) return null;
                            const wide = wideActionNodes.has(node.id);
                            const panelId = `action-panel-${node.id}`;
                            return (
                              <div style={{ width: '100%', marginTop: '8px', background: '#f8fafc', border: '1px dashed #cbd5e1', borderRadius: '10px', padding: '8px 10px' }}>
                                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '6px' }}>
                                  <span style={{ fontSize: '11px', fontWeight: '800', color: '#475569', letterSpacing: '-0.2px' }}>논제 액션</span>
                                  <button
                                    type="button"
                                    aria-expanded={wide}
                                    aria-controls={panelId}
                                    onClick={(e) => { e.stopPropagation(); toggleWideActions(node.id); }}
                                    title={wide ? '액션 접기' : '액션 펼치기'}
                                    style={{ display: 'flex', alignItems: 'center', gap: '3px', padding: '2px 8px', borderRadius: '7px', fontSize: '11px', fontWeight: '700', border: '1px solid #cbd5e1', background: '#ffffff', color: '#475569', cursor: 'pointer' }}
                                  >
                                    {wide ? <><ChevronLeft size={12} /> 접기</> : <>펼치기 <ChevronRight size={12} /></>}
                                  </button>
                                </div>
                                <div
                                  id={panelId}
                                  style={{ display: 'flex', gap: '8px', flexWrap: wide ? 'wrap' : 'nowrap', overflowX: wide ? 'visible' : 'auto', paddingBottom: wide ? 0 : '4px' }}
                                >
                                  {acts.map((act) => (
                                    <button
                                      key={act.actionType}
                                      onClick={(e) => { e.stopPropagation(); onRequestDetail?.(node, act.actionType); }}
                                      style={{ display: 'flex', alignItems: 'center', gap: '4px', padding: '6px 11px', borderRadius: '8px', fontSize: '12px', fontWeight: '700', border: `1px solid ${color.accent}40`, background: color.badgeBg, color: color.accent, cursor: 'pointer', boxShadow: '0 1px 2px rgba(0,0,0,0.02)', whiteSpace: 'nowrap', flexShrink: 0 }}
                                    >
                                      {act.label}
                                    </button>
                                  ))}
                                </div>
                              </div>
                            );
                         })()}
                     </motion.div>
                 )}
              </AnimatePresence>
            </motion.div>

            {/* 2) 자식 노드 계층 (가로 분기 - 조직도 형태) */}
            {node.children && node.children.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                    
                    {/* 부모에서 내려오는 수직 연결선 */}
                    <div style={{ width: '2px', height: '28px', background: '#cbd5e1' }} />
                    
                    {/* 자식들 수평 나열 (가로 분기) */}
                    <div style={{ display: 'flex', flexDirection: 'row', alignItems: 'flex-start', justifyContent: 'center' }}>
                        {node.children.map((child, idx) => {
                           const isFirst = idx === 0;
                           const isLast = idx === node.children.length - 1;
                           const isOnly = node.children.length === 1;

                           return (
                             <div key={child.id} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', padding: '0 40px', position: 'relative' }}>
                                
                                {/* 형제들을 묶는 상단 수평 연결선 */}
                                {!isOnly && (
                                   <div style={{
                                      position: 'absolute',
                                      top: 0,
                                      left: isFirst ? '50%' : 0,
                                      right: isLast ? '50%' : 0,
                                      height: '2px',
                                      background: '#cbd5e1',
                                      zIndex: 0
                                   }} />
                                )}

                                {/* 자식으로 내려가는 수직 연결선 (기본 모드는 중립 회색 — 파란 줄/글로우 제거) */}
                                <div style={{
                                    width: (child.nodeType === 'debate' && (child.stageType === 'REBUTTAL' || child.stageType === 'CROSS_REBUTTAL')) ? '3px' : '2px',
                                    height: '40px',
                                    background: (child.nodeType === 'debate' && (child.stageType === 'REBUTTAL' || child.stageType === 'CROSS_REBUTTAL')) ? 'linear-gradient(to bottom, #fca5a5, #ef4444)' : '#cbd5e1',
                                    zIndex: 0,
                                    display: 'flex',
                                    justifyContent: 'center',
                                    alignItems: 'center',
                                    position: 'relative',
                                    boxShadow: (child.nodeType === 'debate' && (child.stageType === 'REBUTTAL' || child.stageType === 'CROSS_REBUTTAL')) ? '0 0 8px rgba(239, 68, 68, 0.4)' : 'none'
                                }}>
                                   {/* 토론 노드: stageType 기반 라벨(입론/반박/재반박/최종 변론/판정/논제). "피드백" 금지 */}
                                   {child.nodeType === 'debate' ? (
                                       DEBATE_EDGE_LABEL[child.stageType] && (
                                         (child.stageType === 'REBUTTAL' || child.stageType === 'CROSS_REBUTTAL') ? (
                                            <motion.div
                                                initial={{ scale: 0.8, opacity: 0 }}
                                                animate={{ scale: 1, opacity: 1, boxShadow: ['0 0 0px rgba(239,68,68,0)', '0 0 12px rgba(239,68,68,0.6)', '0 0 0px rgba(239,68,68,0)'] }}
                                                transition={{ duration: 1.2, repeat: Infinity, repeatType: 'reverse' }}
                                                style={{
                                                    position: 'absolute',
                                                    background: 'linear-gradient(135deg, #fef2f2, #fee2e2)',
                                                    border: '1px solid #ef4444',
                                                    padding: '4px 10px',
                                                    borderRadius: '12px',
                                                    fontSize: '11px',
                                                    fontWeight: '900',
                                                    color: '#b91c1c',
                                                    display: 'flex',
                                                    alignItems: 'center',
                                                    gap: '4px',
                                                    zIndex: 2,
                                                    whiteSpace: 'nowrap'
                                                }}>
                                                <Zap size={12} color="#dc2626" fill="#ef4444" />
                                                {DEBATE_EDGE_LABEL[child.stageType]}
                                            </motion.div>
                                         ) : (
                                            <div style={{
                                                position: 'absolute',
                                                background: '#ffffff',
                                                border: `1px solid ${debateColor(child.side).accent}40`,
                                                padding: '2px 8px',
                                                borderRadius: '12px',
                                                fontSize: '10px',
                                                fontWeight: '800',
                                                color: debateColor(child.side).accent,
                                                display: 'flex',
                                                alignItems: 'center',
                                                gap: '4px',
                                                boxShadow: '0 2px 6px rgba(0,0,0,0.05)',
                                                zIndex: 2,
                                                whiteSpace: 'nowrap'
                                            }}>
                                                {DEBATE_EDGE_LABEL[child.stageType]}
                                            </div>
                                         )
                                       )
                                   ) : child.nodeType === 'simulation' ? (
                                       SIMULATION_EDGE_LABEL[child.stageType] && (
                                         <div style={{
                                             position: 'absolute', background: '#ffffff', border: `1px solid ${simulationColor(child.stageType).accent}40`,
                                             padding: '2px 8px', borderRadius: '12px', fontSize: '10px', fontWeight: '800',
                                             color: simulationColor(child.stageType).accent, display: 'flex', alignItems: 'center', gap: '4px',
                                             boxShadow: '0 2px 6px rgba(0,0,0,0.05)', zIndex: 2, whiteSpace: 'nowrap'
                                         }}>
                                             {SIMULATION_EDGE_LABEL[child.stageType]}
                                         </div>
                                       )
                                   ) : child.nodeType === 'socratic' ? (
                                       SOCRATIC_EDGE_LABEL[child.stageType] && (
                                         <div style={{
                                             position: 'absolute',
                                             background: '#ffffff',
                                             border: `1px solid ${socraticColor(child.stageType).accent}40`,
                                             padding: '2px 8px',
                                             borderRadius: '12px',
                                             fontSize: '10px',
                                             fontWeight: '800',
                                             color: socraticColor(child.stageType).accent,
                                             display: 'flex',
                                             alignItems: 'center',
                                             gap: '4px',
                                             boxShadow: '0 2px 6px rgba(0,0,0,0.05)',
                                             zIndex: 2,
                                             whiteSpace: 'nowrap'
                                         }}>
                                             {SOCRATIC_EDGE_LABEL[child.stageType]}
                                         </div>
                                       )
                                   ) : (child.sender !== 'USER' && node.sender !== 'USER') && (
                                       <div
                                           style={{
                                               position: 'absolute',
                                               background: '#ffffff',
                                               border: '1px solid #cbd5e1',
                                               padding: '2px 8px',
                                               borderRadius: '12px',
                                               fontSize: '10px',
                                               fontWeight: '800',
                                               color: '#475569',
                                               display: 'flex',
                                               alignItems: 'center',
                                               gap: '4px',
                                               boxShadow: '0 2px 6px rgba(0,0,0,0.05)',
                                               zIndex: 2,
                                               whiteSpace: 'nowrap'
                                           }}>
                                           <Zap size={12} color="#64748b" />
                                           반박
                                       </div>
                                   )}
                                </div>

                                {/* 자식 노드 재귀 렌더링 */}
                                {renderFlowchartNode(child, depth + 1)}
                             </div>
                           )
                        })}
                    </div>
                </div>
            )}
        </div>
    );
  };

  const hasDebate = messages.some((m) => m.nodeType === 'debate');
  const hasSocratic = messages.some((m) => m.nodeType === 'socratic');

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%', overflow: 'hidden' }}>

      {/* 소크라테스 노드가 있을 때만 표시되는 색상 범례 */}
      {hasSocratic && (
        <div style={{
          position: 'absolute', top: '16px', right: '16px', zIndex: 50,
          background: 'rgba(255,255,255,0.9)', backdropFilter: 'blur(12px)',
          border: '1px solid rgba(226,232,240,0.9)', borderRadius: '14px',
          padding: '10px 14px', boxShadow: '0 8px 24px rgba(0,0,0,0.07)',
          display: 'flex', flexDirection: 'column', gap: '6px',
        }}>
          <div style={{ fontSize: '11px', fontWeight: 800, color: '#475569', marginBottom: '2px' }}>소크라테스 범례</div>
          {[
            { c: SOCRATIC_COLOR.DIAGNOSIS.accent, t: '진단/핵심 개념' },
            { c: SOCRATIC_COLOR.MISCONCEPTION_CHECK.accent, t: '오개념/반례' },
            { c: SOCRATIC_COLOR.HINT.accent, t: '힌트' },
            { c: SOCRATIC_COLOR.APPLICATION.accent, t: '적용' },
            { c: SOCRATIC_COLOR.SELF_EXPLANATION.accent, t: '자기 설명' },
            { c: SOCRATIC_COLOR.SUMMARY.accent, t: '정리/다음 학습' },
          ].map((row) => (
            <div key={row.t} style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '11px', fontWeight: 700, color: '#334155' }}>
              <span style={{ width: '10px', height: '10px', borderRadius: '3px', background: row.c, flexShrink: 0 }} />
              {row.t}
            </div>
          ))}
        </div>
      )}

      {/* 토론 노드가 있을 때만 표시되는 색상 범례 */}
      {hasDebate && (
        <div style={{
          position: 'absolute', top: '16px', right: '16px', zIndex: 50,
          background: 'rgba(255,255,255,0.9)', backdropFilter: 'blur(12px)',
          border: '1px solid rgba(226,232,240,0.9)', borderRadius: '14px',
          padding: '10px 14px', boxShadow: '0 8px 24px rgba(0,0,0,0.07)',
          display: 'flex', flexDirection: 'column', gap: '6px',
        }}>
          <div style={{ fontSize: '11px', fontWeight: 800, color: '#475569', marginBottom: '2px' }}>토론 범례</div>
          {[
            { c: DEBATE_COLOR.PRO.accent, t: '찬성측' },
            { c: DEBATE_COLOR.CON.accent, t: '반대측' },
            { c: DEBATE_COLOR.NEUTRAL.accent, t: '중립/심사위원' },
            { c: DEBATE_COLOR.TOPIC.accent, t: '논제' },
          ].map((row) => (
            <div key={row.t} style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '11px', fontWeight: 700, color: '#334155' }}>
              <span style={{ width: '10px', height: '10px', borderRadius: '3px', background: row.c, flexShrink: 0 }} />
              {row.t}
            </div>
          ))}
        </div>
      )}

      {/* 확대/축소 컨트롤 패널 (항상 화면 우측 하단 고정) */}
      <div style={{
        position: 'absolute',
        bottom: '24px',
        right: '24px',
        display: 'flex',
        alignItems: 'center',
        background: 'rgba(255, 255, 255, 0.85)',
        backdropFilter: 'blur(12px)',
        border: '1px solid rgba(226, 232, 240, 0.8)',
        borderRadius: '99px',
        padding: '6px',
        boxShadow: '0 8px 32px rgba(0,0,0,0.08)',
        zIndex: 50,
        gap: '4px'
      }}>
        <button
          onClick={() => setZoom(prev => Math.max(prev - 0.1, 0.4))}
          style={{ width: '36px', height: '36px', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'transparent', border: 'none', borderRadius: '50%', cursor: 'pointer', color: '#64748b', transition: 'all 0.2s' }}
          onMouseEnter={e => { e.currentTarget.style.background = '#f1f5f9'; e.currentTarget.style.color = '#334155'; }}
          onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = '#64748b'; }}
          title="축소"
        >
          <ZoomOut size={20} strokeWidth={2.5} />
        </button>
        
        <div 
          onClick={() => setZoom(1)}
          style={{ width: '48px', textAlign: 'center', fontSize: '13.5px', fontWeight: '800', color: '#334155', userSelect: 'none', cursor: 'pointer' }}
          title="100%로 초기화"
        >
          {Math.round(zoom * 100)}%
        </div>

        <button
          onClick={() => setZoom(prev => Math.min(prev + 0.1, 1.5))}
          style={{ width: '36px', height: '36px', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'transparent', border: 'none', borderRadius: '50%', cursor: 'pointer', color: '#64748b', transition: 'all 0.2s' }}
          onMouseEnter={e => { e.currentTarget.style.background = '#f1f5f9'; e.currentTarget.style.color = '#334155'; }}
          onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = '#64748b'; }}
          title="확대"
        >
          <ZoomIn size={20} strokeWidth={2.5} />
        </button>
      </div>

      <div 
        className="discussion-container-y-scroll" 
        ref={containerRef}
        style={{ 
          overflowY: 'auto', 
          overflowX: 'auto', // 가로 확장을 위해 X축 스크롤 허용
          width: '100%',
          height: '100%',
          background: 'transparent',
        }}
      >

      {/* 
         자식 요소가 넓어질 때 좌측이 잘리는 flex 오류를 방지하기 위해 
         inline-flex와 minWidth: 100%를 결합한 절대적인 중앙 정렬 컨테이너 
      */}
      <div style={{ 
        display: 'inline-flex', 
        flexDirection: 'column', 
        alignItems: 'center',
        minWidth: '100%',
        padding: '40px 60px 100px 60px',
        gap: '60px',
        transform: `scale(${zoom})`,
        transformOrigin: 'top center',
        transition: 'transform 0.25s cubic-bezier(0.4, 0, 0.2, 1)'
      }}>
        
        {/* ── 학습 상태 요약 바 ── */}
        <AnimatePresence>
          {/* 빈 상태 */}
          {roots.length === 0 && (
            <motion.div
              key="empty"
              initial={{ opacity: 0, scale: 0.95 }}
              animate={{ opacity: 1, scale: 1 }}
              style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', marginTop: '10vh', background: 'rgba(255,255,255,0.7)', backdropFilter: 'blur(16px)', padding: '60px 40px', borderRadius: '32px', boxShadow: '0 12px 40px rgba(0,0,0,0.03)', border: '1px solid rgba(255,255,255,0.6)' }}
            >
              <div style={{ width: 88, height: 88, borderRadius: '28px', background: 'linear-gradient(135deg, #f0fdf4, #e0f2fe)', display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: 24, border: '1px solid rgba(16,185,129,0.15)', boxShadow: '0 8px 24px rgba(16,185,129,0.1)' }}>
                <Network size={44} color="#059669" />
              </div>
              <div style={{ fontWeight: 800, fontSize: 22, color: '#0f172a', marginBottom: 12, letterSpacing: '-0.5px' }}>
                교수님들과 학습할 질문을 입력하세요
              </div>
              <div style={{ fontSize: 15, color: '#475569', lineHeight: 1.8, maxWidth: 400, textAlign: 'center' }}>
                질문을 입력하면 교수님들이 실시간으로 답변합니다.<br />
                모든 대화는 <strong>위(전체 의견) → 아래(교수 의견)</strong>로 갈라지는 트리로 정리되며,<br />
                궁금한 <span style={{ color: '#059669', fontWeight: 'bold' }}>대화 카드</span>를 눌러 더 자세히 묻거나 이어갈 수 있습니다.
              </div>
            </motion.div>
          )}

          {/* 최상위 루트 노드(들)부터 조직도 렌더링 */}
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '80px', width: '100%' }}>
             {roots.map((rootNode, idx) => (
               <motion.div
                 key={rootNode.id || idx}
                 initial={{ opacity: 0, y: 30 }}
                 animate={{ opacity: 1, y: 0 }}
                 transition={{ duration: 0.5, delay: 0.05 * idx, type: 'spring', stiffness: 100 }}
               >
                 {renderFlowchartNode(rootNode, 0)}
               </motion.div>
             ))}
          </div>
        </AnimatePresence>
      </div>

      {/* 🚀 응답 대기 중 (타이핑) 플로팅 UI (마인드맵 구조를 해치지 않게 좌측 하단 고정) */}
      <AnimatePresence>
        {typingAgents.length > 0 && (
          <motion.div
            initial={{ opacity: 0, y: 20, scale: 0.9 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 20, scale: 0.9 }}
            transition={{ duration: 0.3 }}
            style={{
              position: 'absolute',
              left: '24px',
              bottom: '24px',
              background: 'rgba(255, 255, 255, 0.9)',
              backdropFilter: 'blur(12px)',
              border: '1px solid rgba(226, 232, 240, 0.8)',
              borderRadius: '20px',
              padding: '16px 24px',
              display: 'flex',
              flexDirection: 'column',
              gap: '12px',
              boxShadow: '0 10px 40px rgba(0,0,0,0.1)',
              zIndex: 100,
              minWidth: '240px'
            }}
          >
            <div style={{ fontSize: '13px', fontWeight: '800', color: '#475569', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', width: '24px', height: '24px', background: '#eff6ff', borderRadius: '50%', color: '#3b82f6' }}>
                <Bot size={14} />
              </div>
              에이전트 응답 생성 중...
            </div>
            
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {typingAgents.map((agent, idx) => {
                const colorInfo = getAgentColor(agent.name);
                return (
                  <div key={idx} style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <div style={{ width: '24px', height: '24px', borderRadius: '50%', background: colorInfo.bg, display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '11px', fontWeight: '800', color: colorInfo.accent }}>
                      <Bot size={13} />
                    </div>
                    <span style={{ fontSize: '14px', fontWeight: '700', color: '#1e293b' }}>{agent.name}</span>
                    
                    <div style={{ display: 'flex', gap: '4px', marginLeft: 'auto', alignItems: 'center', paddingRight: '8px' }}>
                      <span style={{ animation: 'pulseDot 1.4s infinite ease-in-out both', animationDelay: '-0.32s', width: '5px', height: '5px', background: colorInfo.accent, borderRadius: '50%' }} />
                      <span style={{ animation: 'pulseDot 1.4s infinite ease-in-out both', animationDelay: '-0.16s', width: '5px', height: '5px', background: colorInfo.accent, borderRadius: '50%' }} />
                      <span style={{ animation: 'pulseDot 1.4s infinite ease-in-out both', width: '5px', height: '5px', background: colorInfo.accent, borderRadius: '50%' }} />
                    </div>
                  </div>
                );
              })}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  </div>
  );
}
