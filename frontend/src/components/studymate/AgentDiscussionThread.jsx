import React, { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Bot, User, Sparkles, Network, ThumbsUp, RefreshCw,
  ChevronDown, ChevronUp, Brain, CheckCircle2, Zap
} from 'lucide-react';
import './studymate-premium.css';

/**
 * AgentDiscussionThread
 *
 * Props:
 *  - messages: { id, content, sender, senderName, createdAt, agentId, actionType? }[]
 *  - typingAgents: { id, name, color, action? }[]
 *  - agents: 에이전트 목록 (색상 매핑용)
 *  - learnedIds: Set<messageId>  — 학습 완료된 메시지 ID 집합
 *  - onHelpful:      (message) => void  — "도움됨" 클릭 → 학습 완료 처리
 *  - onRequestDetail:(message) => void  — "더 자세히" 클릭 → 재질문 자동 전송
 */
export default function AgentDiscussionThread({
  messages = [],
  typingAgents = [],
  agents = [],
  learnedIds = new Set(),
  onHelpful,
  onRequestDetail,
}) {
  const containerRef = useRef(null);
  const [collapsed, setCollapsed] = useState({});

  // ─── 캔버스 Pan & Zoom 상태 ──────────────────────────────────────────────
  const [transform, setTransform] = useState({ x: 0, y: 0, scale: 1 });
  const isDragging = useRef(false);
  const dragStart = useRef({ x: 0, y: 0 });

  // 메시지가 추가되면 뷰포트 위치 최적화
  useEffect(() => {
    if (messages.length > 0 || typingAgents.length > 0) {
      // 가로형 마인드맵이므로 트리가 우측으로 자람. 따라서 루트를 약간 좌측(x: 200)에 배치.
      setTransform(prev => ({ ...prev, y: 0, x: 200, scale: 1 }));
    }
  }, [messages.length, typingAgents.length]);

  const handleWheel = (e) => {
    if (e.ctrlKey || e.metaKey) {
      // 줌 인/아웃
      e.preventDefault();
      const zoomFactor = 0.05;
      const delta = e.deltaY < 0 ? zoomFactor : -zoomFactor;
      setTransform((prev) => ({
        ...prev,
        scale: Math.min(Math.max(0.3, prev.scale + delta), 3)
      }));
    } else {
      // 상하 스크롤 (이동)
      setTransform((prev) => ({
        ...prev,
        y: prev.y - e.deltaY,
        x: prev.x - e.deltaX
      }));
    }
  };

  const handleMouseDown = (e) => {
    // 버튼, 아이콘 등 클릭 시 드래그 방지
    if (e.target.closest('button') || e.target.closest('.dt-create-btn')) return;
    
    isDragging.current = true;
    dragStart.current = { x: e.clientX - transform.x, y: e.clientY - transform.y };
    if (containerRef.current) containerRef.current.style.cursor = 'grabbing';
  };

  const handleMouseMove = (e) => {
    if (!isDragging.current) return;
    e.preventDefault();
    setTransform((prev) => ({
      ...prev,
      x: e.clientX - dragStart.current.x,
      y: e.clientY - dragStart.current.y
    }));
  };

  const handleMouseUpOrLeave = () => {
    isDragging.current = false;
    if (containerRef.current) containerRef.current.style.cursor = 'grab';
  };

  // ─── 에이전트 색상 팔레트 ────────────────────────────────────────────────
  const AGENT_COLORS = [
    { accent: '#2563eb', bg: 'rgba(37,99,235,0.08)',  badgeBg: '#DBEAFE' },
    { accent: '#EA580C', bg: 'rgba(234,88,12,0.08)',  badgeBg: '#FFEDD5' },
    { accent: '#7C3AED', bg: 'rgba(124,58,237,0.08)', badgeBg: '#EDE9FE' },
    { accent: '#059669', bg: 'rgba(5,150,105,0.08)',  badgeBg: '#D1FAE5' },
    { accent: '#E11D48', bg: 'rgba(225,29,72,0.08)',  badgeBg: '#FFE4E6' },
  ];

  const getAgentColor = (senderName) => {
    const idx = agents.findIndex((ag) => ag.name === senderName);
    return AGENT_COLORS[(idx >= 0 ? idx : 0) % AGENT_COLORS.length];
  };

  // ─── 마인드맵 트리 빌드 (재귀) ────────────────────────────────────────
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
            // 해당 에이전트의 직전 응답을 찾음
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

        // 2. 멘션을 못 찾았거나, @모두 이거나, '자세히' 등 맥락이 이어지는 꼬리질문일 경우
        // 이전 유저 노드의 자식으로 이어가서 대화의 흐름(Chain)을 만듦
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
        
        // 어떤 경우든 마지막 유저 노드를 갱신해야 다음 AI 응답이 이 노드 아래로 붙음
        lastUserNode = node;
      } else {
        // AI 응답인데 부모가 없는 경우
        if (lastUserNode) {
          lastUserNode.children.push(node);
        } else {
          roots.push(node);
        }
      }
    }
  });

  // 타이핑 중인 에이전트가 있다면 가상 노드로 추가하여 멀티플레이어 느낌 강화
  if (typingAgents.length > 0) {
    typingAgents.forEach((agent, idx) => {
      const typingNode = {
        id: `typing-${agent.name}-${idx}`,
        type: 'AI',
        sender: 'AI',
        senderName: agent.name,
        content: '타이핑 중...',
        isTyping: true,
        children: []
      };
      if (lastUserNode) {
        lastUserNode.children.push(typingNode);
      } else {
        roots.push(typingNode);
      }
    });
  }

  const learnedCount = messages.filter((m) => learnedIds.has(m.id)).length;
  const totalAI = messages.filter((m) => m.sender !== 'USER').length;

  const toggleCollapse = (idx) =>
    setCollapsed((prev) => ({ ...prev, [idx]: !prev[idx] }));

  // 재귀적 노드 렌더링 컴포넌트
  const renderTreeNode = (node, isRoot = false) => {
    const isUser = node.sender === 'USER';
    const color = isUser 
      ? { accent: '#059669', bg: '#ecfdf5' } 
      : getAgentColor(node.senderName || node.sender_name);
    const isLearned = learnedIds.has(node.id);

    return (
      <div className="tree-level-wrapper" key={node.id} style={{ display: 'flex', flexDirection: 'row', alignItems: 'center', gap: '60px', position: 'relative' }}>
        
        {/* 현재 노드 */}
        <motion.div
          className={`tree-branch-node ${isRoot ? 'tree-root-node' : ''} ${isLearned ? 'learned' : ''}`}
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ type: 'spring', stiffness: 120 }}
          style={{ position: 'relative' }}
        >
          {/* 부모와 연결되는 선 (루트가 아닐 때만 좌측 선) */}
          {!isRoot && <div className="connection-line-left" />}
          {/* 자식이 있을 때 우측으로 나가는 선 */}
          {node.children && node.children.length > 0 && <div className="connection-line-right" />}

          {/* 학습 뱃지 */}
          {isLearned && !isUser && (
            <div className="learned-badge">
              <CheckCircle2 size={11} /> 학습 완료
            </div>
          )}

          {/* 헤더 */}
          <div className="branch-header" style={{ color: isRoot ? '' : color.accent, borderBottom: isRoot ? '1px solid rgba(255,255,255,0.1)' : '1px solid rgba(0,0,0,0.04)', paddingBottom: '8px', marginBottom: '10px' }}>
            <div style={{
              width: 24, height: 24, borderRadius: '50%', 
              background: isRoot ? 'rgba(255,255,255,0.2)' : color.bg, 
              color: isRoot ? '#fff' : color.accent, 
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              fontSize: '12px', fontWeight: '800', border: isRoot ? '1px solid rgba(255,255,255,0.4)' : `1px solid ${color.accent}50`
            }}>
              {isUser ? '나' : (node.senderName || node.sender_name || 'AI').charAt(0)}
            </div>
            <span style={{ fontWeight: 700, fontSize: isRoot ? '15px' : '14px' }}>
              {isUser ? (isRoot ? '디지털 트윈 — 핵심 질문' : '나 (추가 질문)') : (node.senderName || node.sender_name || 'AI')}
            </span>
            {!isUser && (
              <span className="branch-badge" style={{ color: color.accent, background: color.bg, border: `1px solid ${color.accent}30`, fontSize: '10px', padding: '2px 8px', borderRadius: '10px' }}>
                {node.actionType || '의견'}
              </span>
            )}
          </div>

          {/* 콘텐츠 */}
          <div className={isRoot ? "tree-root-content" : "branch-content"} style={{ fontWeight: isUser ? '600' : '400', color: isRoot ? '' : (isUser ? '#111827' : '#1f2937'), whiteSpace: 'pre-wrap', lineHeight: '1.6', fontSize: '13px' }}>
            {node.isTyping ? (
              <div style={{ display: 'flex', gap: '4px', padding: '4px 0' }}>
                <span className="dot" style={{ animation: 'pulseDot 1.4s infinite ease-in-out both', animationDelay: '-0.32s', width: 6, height: 6, background: color.accent, borderRadius: '50%' }} />
                <span className="dot" style={{ animation: 'pulseDot 1.4s infinite ease-in-out both', animationDelay: '-0.16s', width: 6, height: 6, background: color.accent, borderRadius: '50%' }} />
                <span className="dot" style={{ animation: 'pulseDot 1.4s infinite ease-in-out both', width: 6, height: 6, background: color.accent, borderRadius: '50%' }} />
              </div>
            ) : (
              node.content
            )}
          </div>

          {/* 액션 버튼 */}
          {!node.isTyping && (
            <div className="branch-feedback-row" style={{ display: 'flex', gap: '6px', marginTop: '12px', paddingTop: '10px', borderTop: isUser ? '1px solid rgba(0,0,0,0.05)' : '1px solid #f3f4f6', justifyContent: isUser ? 'flex-end' : 'flex-start' }}>
              {!isUser && (
                <button className={`feedback-btn ${isLearned ? 'active' : ''}`} onClick={() => onHelpful?.(node)}>
                  <ThumbsUp size={11} />
                  {isLearned ? '학습 완료 ✓' : '도움됨'}
                </button>
              )}
              <button className="feedback-btn detail" onClick={() => onRequestDetail?.(node)}>
                <RefreshCw size={11} />
                {isUser ? '추가 질문 연결' : '더 자세히'}
              </button>
            </div>
          )}
        </motion.div>

        {/* 자식 노드들 (재귀 렌더링) */}
        {node.children && node.children.length > 0 && (
          <div className="tree-children-container" style={{ display: 'flex', flexDirection: 'column', gap: '32px', position: 'relative' }}>
            {/* 여러 자식들을 묶어주는 수직 연결선 (Spine) - 자식이 2개 이상일 때만 의미있지만 일단 일괄 적용 */}
            {node.children.length > 1 && (
              <div style={{ position: 'absolute', left: '-30px', top: '30px', bottom: '30px', width: '3px', background: '#cbd5e1', borderRadius: '2px' }} />
            )}
            
            {node.children.map(child => renderTreeNode(child, false))}
          </div>
        )}
      </div>
    );
  };

  // ─── 렌더 ────────────────────────────────────────────────────────────────
  return (
    <div 
      className="discussion-container-light" 
      ref={containerRef}
      onWheel={handleWheel}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={handleMouseUpOrLeave}
      onMouseLeave={handleMouseUpOrLeave}
      style={{ 
        cursor: 'grab', 
        overflow: 'hidden', /* 스크롤바 숨기고 커스텀 이동 */
        position: 'relative',
        width: '100%',
        height: '100%'
      }}
    >
      <div 
        className="mindmap-canvas"
        style={{
          transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.scale})`,
          transformOrigin: '50% 50%',
          transition: isDragging.current ? 'none' : 'transform 0.1s ease-out',
          width: '6000px',
          height: '6000px',
          position: 'absolute',
          left: '50%',
          top: '50%',
          marginLeft: '-3000px',
          marginTop: '-3000px',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          backgroundImage: 'radial-gradient(circle, #cbd5e1 1.5px, transparent 1.5px)',
          backgroundSize: '32px 32px'
        }}
      >

      {/* ── 학습 상태 헤더 (디지털 트윈 지식 그래프 요약) ── */}
      {totalAI > 0 && (
        <motion.div
          className="dt-knowledge-bar"
          initial={{ opacity: 0, y: -8 }}
          animate={{ opacity: 1, y: 0 }}
        >
          <div className="dk-stat">
            <Brain size={14} color="#7C3AED" />
            <span>AI 응답</span>
            <strong>{totalAI}개</strong>
          </div>
          <div className="dk-divider" />
          <div className="dk-stat">
            <CheckCircle2 size={14} color="#16a34a" />
            <span>학습 완료</span>
            <strong style={{ color: '#16a34a' }}>{learnedCount}개</strong>
          </div>
          <div className="dk-divider" />
          <div className="dk-stat">
            <Zap size={14} color="#f59e0b" />
            <span>학습률</span>
            <strong style={{ color: '#f59e0b' }}>
              {totalAI > 0 ? Math.round((learnedCount / totalAI) * 100) : 0}%
            </strong>
          </div>
          {/* 진행 바 */}
          <div className="dk-progress-wrap">
            <div
              className="dk-progress-bar"
              style={{ width: `${totalAI > 0 ? (learnedCount / totalAI) * 100 : 0}%` }}
            />
          </div>
        </motion.div>
      )}

      <AnimatePresence>
        {/* 빈 상태 */}
        {roots.length === 0 && typingAgents.length === 0 && (
          <motion.div
            key="empty"
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="mindmap-empty"
          >
            <div className="mindmap-empty-icon">
              <Network size={32} color="#60C95A" />
            </div>
            <div style={{ fontWeight: 700, fontSize: 15, color: '#374151', marginBottom: 6 }}>
              마인드맵 학습을 시작하세요
            </div>
            <div style={{ fontSize: 13, color: '#9ca3af', lineHeight: 1.7, maxWidth: 300, textAlign: 'center' }}>
              질문을 입력하면 AI가 마인드맵 트리로 답변합니다.<br />
              <span style={{ color: '#16a34a', fontWeight: 600 }}>👍 도움됨</span>을 누르면 학습 완료로 기록되고,<br />
              <span style={{ color: '#2563eb', fontWeight: 600 }}>↺ 더 자세히</span>를 누르면 AI가 즉시 재설명합니다.
            </div>
          </motion.div>
        )}

        {/* 세션 트리 목록 (여러 개의 루트 노드) */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '100px', alignItems: 'flex-start' }}>
          {roots.map((rootNode, idx) => (
            <motion.div
              key={rootNode.id || idx}
              initial={{ opacity: 0, y: 24 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, delay: 0.05 * idx }}
            >
              {renderTreeNode(rootNode, true)}
            </motion.div>
          ))}
          
          {/* 타이핑 스켈레톤 (새로운 질문 처리 중일 때) */}
          {typingAgents.length > 0 && roots.length > 0 && (
            <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} style={{ marginLeft: '440px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
               {typingAgents.map((agent, tIdx) => {
                 const color = AGENT_COLORS[tIdx % AGENT_COLORS.length];
                 return (
                    <div key={tIdx} className="tree-branch-node" style={{ width: '380px' }}>
                      <div className="branch-header" style={{ color: color.accent }}>
                        <Bot size={14} /> <span style={{fontWeight: 700}}>{agent.name}</span>
                        <span style={{ fontSize: 11, color: '#9ca3af', fontWeight: 400, marginLeft: '8px' }}>응답 생성 중...</span>
                      </div>
                      <div className="dt-typing-dots" style={{ marginBottom: 12 }}>
                        <span /><span /><span />
                      </div>
                      <div className="skeleton-light" style={{ width: '85%' }} />
                      <div className="skeleton-light" style={{ width: '65%' }} />
                    </div>
                 );
               })}
            </motion.div>
          )}
        </div>



          {/* 초기 타이핑 상태 */}
          {roots.length === 0 && typingAgents.length > 0 && (
            <motion.div key="init-typing" className="session-tree" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
              <div className="tree-branches-container">
                {typingAgents.map((agent, tIdx) => {
                  const color = AGENT_COLORS[tIdx % AGENT_COLORS.length];
                  return (
                    <motion.div key={`init-${tIdx}`} className={`tree-branch-node ${tIdx % 2 === 0 ? 'left' : 'right'}`} initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
                      <div className="branch-header" style={{ color: color.accent }}>
                        <Bot size={13} /> {agent.name}
                      </div>
                      <div className="dt-typing-dots"><span /><span /><span /></div>
                    </motion.div>
                  );
                })}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div> {/* end mindmap-canvas */}
      
      {/* 줌 컨트롤 미니 툴바 */}
      <div style={{ position: 'absolute', bottom: '20px', right: '20px', display: 'flex', gap: '8px', zIndex: 100, background: 'white', padding: '6px', borderRadius: '12px', boxShadow: '0 4px 12px rgba(0,0,0,0.1)', border: '1px solid #f3f4f6' }}>
        <button onClick={() => setTransform(p => ({ ...p, scale: Math.max(0.3, p.scale - 0.2) }))} style={{ background: '#f8fafc', border: 'none', borderRadius: '8px', width: '32px', height: '32px', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>-</button>
        <div style={{ fontSize: '13px', fontWeight: 'bold', display: 'flex', alignItems: 'center', justifyContent: 'center', minWidth: '40px' }}>{Math.round(transform.scale * 100)}%</div>
        <button onClick={() => setTransform(p => ({ ...p, scale: Math.min(3, p.scale + 0.2) }))} style={{ background: '#f8fafc', border: 'none', borderRadius: '8px', width: '32px', height: '32px', cursor: 'pointer', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>+</button>
        <button onClick={() => setTransform({ x: 0, y: 0, scale: 1 })} style={{ background: '#e0f2fe', color: '#0369a1', border: 'none', borderRadius: '8px', padding: '0 12px', cursor: 'pointer', fontWeight: 'bold', fontSize: '12px' }}>원래대로</button>
      </div>

    </div>
  );
}
