import React, { useEffect, useRef, useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Bot, User, Network, Bookmark, RefreshCw,
  Brain, CheckCircle2, Zap, MessageSquare,
  ChevronDown, ChevronUp, ZoomIn, ZoomOut
} from 'lucide-react';
import './studymate-premium.css';

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
}) {
  const containerRef = useRef(null);
  
  // 아코디언 상태 관리 (Set of expanded node IDs)
  const [expandedNodes, setExpandedNodes] = useState(new Set());
  
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
    const color = isUser 
      ? { accent: '#10b981', bg: '#ecfdf5' } 
      : getAgentColor(node.senderName || node.sender_name);
    const isBookmarked = bookmarkedIds.has(node.id);
    const isExpanded = expandedNodes.has(node.id) || node.isTyping;
    const isRoot = depth === 0;

    return (
        <div id={`node-${node.id}`} key={node.id} style={{ display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
            
            {/* 1) 현재 노드 카드 */}
            <motion.div
              layout
              onClick={() => toggleExpand(node.id)}
              style={{
                width: isRoot ? '400px' : '340px',
                backgroundColor: isUser ? (isRoot ? '#f0fdf4' : '#f8fafc') : '#ffffff',
                border: isUser 
                  ? (isRoot ? '2px solid rgba(16,185,129,0.4)' : '1px solid rgba(16,185,129,0.3)') 
                  : '1px solid #e2e8f0',
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
                    {isUser ? <User size={14} /> : (node.senderName || node.sender_name || 'AI').charAt(0)}
                 </div>
                 
                 <span style={{ fontWeight: '800', fontSize: '14px', color: '#0f172a', letterSpacing: '-0.3px', flexShrink: 0 }}>
                    {isUser ? (isRoot ? '나의 질문' : '나 (추가 질문)') : (node.senderName || node.sender_name || 'AI')}
                 </span>

                 {!isUser && (
                    <span style={{ color: color.accent, background: 'rgba(255,255,255,0.7)', border: `1px solid ${color.accent}30`, fontSize: '10px', padding: '2px 6px', borderRadius: '99px', fontWeight: '700', flexShrink: 0 }}>
                      {node.actionType || '의견'}
                    </span>
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
                   display: '-webkit-box',
                   WebkitLineClamp: isExpanded ? 'unset' : 2,
                   WebkitBoxOrient: 'vertical',
                   overflow: 'hidden'
                 }}>
                   {node.isTyping ? (
                      <div style={{ display: 'flex', gap: '4px', padding: '4px 0' }}>
                        <span style={{ animation: 'pulseDot 1.4s infinite ease-in-out both', animationDelay: '-0.32s', width: '6px', height: '6px', background: color.accent, borderRadius: '50%' }} />
                        <span style={{ animation: 'pulseDot 1.4s infinite ease-in-out both', animationDelay: '-0.16s', width: '6px', height: '6px', background: color.accent, borderRadius: '50%' }} />
                        <span style={{ animation: 'pulseDot 1.4s infinite ease-in-out both', width: '6px', height: '6px', background: color.accent, borderRadius: '50%' }} />
                      </div>
                   ) : (
                      node.content
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
                         <div style={{ display: 'flex', gap: '8px', marginTop: '12px', paddingTop: '12px', borderTop: isUser ? '1px dashed rgba(16,185,129,0.3)' : '1px solid #f1f5f9' }}>
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

                            {!isUser && (
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

                                {/* 자식으로 내려가는 수직 연결선 */}
                                <div style={{ width: '2px', height: '40px', background: '#cbd5e1', zIndex: 0, display: 'flex', justifyContent: 'center', alignItems: 'center', position: 'relative' }}>
                                   {(child.sender !== 'USER' && node.sender !== 'USER') && (
                                       <div style={{
                                           position: 'absolute',
                                           background: '#ffffff',
                                           border: '1px solid #e2e8f0',
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
                                           <Zap size={10} color="#3b82f6" fill="#3b82f6" />
                                           피드백
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

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%', overflow: 'hidden' }}>
      
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
                대화 스레드를 시작하세요
              </div>
              <div style={{ fontSize: 15, color: '#475569', lineHeight: 1.8, maxWidth: 400, textAlign: 'center' }}>
                질문을 입력하면 AI가 실시간으로 답변합니다.<br />
                모든 대화 흐름은 <strong>위에서 아래로 분기되는 조직도</strong> 형태로 구성되며,<br />
                궁금한 노드를 클릭해 상세 내용을 확인하고 <span style={{ color: '#059669', fontWeight: 'bold' }}>추가 질문</span>을 이어갈 수 있습니다.
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
                      {agent.name.charAt(0)}
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
