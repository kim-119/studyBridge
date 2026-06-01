import React, { useEffect, useRef } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Bot, User, Sparkles, Network } from 'lucide-react';
import './studymate-premium.css';

export default function AgentDiscussionThread({ 
  messages = [], 
  typingAgents = [] // array of agentIds currently typing/reviewing
}) {
  const containerRef = useRef(null);

  useEffect(() => {
    if (containerRef.current) {
      containerRef.current.scrollTop = containerRef.current.scrollHeight;
    }
  }, [messages, typingAgents]);

  // Group messages by user question to form a "Session"
  const sessions = [];
  let currentSession = null;

  messages.forEach(msg => {
    if (msg.sender === 'USER') {
      if (currentSession) sessions.push(currentSession);
      currentSession = { userQuery: msg, discussions: [], finalAnswer: null };
    } else {
      if (currentSession) {
        if (msg.actionType && msg.actionType.includes('완료') && !msg.actionType.includes('분석')) {
          currentSession.finalAnswer = msg;
        } else {
          currentSession.discussions.push(msg);
        }
      }
    }
  });
  if (currentSession) sessions.push(currentSession);

  return (
    <div className="discussion-container-light" ref={containerRef} style={{ overflowY: 'auto', maxHeight: '65vh', paddingRight: '10px' }}>
      <AnimatePresence>
        {sessions.length === 0 && (
          <motion.div 
            initial={{ opacity: 0 }} 
            animate={{ opacity: 1 }} 
            style={{ width: '100%', textAlign: 'center', color: 'var(--color-text-muted)', padding: '60px', background: '#FFFFFF', borderRadius: '16px', border: '1px solid var(--color-border)' }}
          >
            <Network size={40} color="#E5E7EB" style={{ marginBottom: '16px' }} />
            <div>디지털 트윈을 중심으로 AI 그룹이 어떻게 마인드맵 회의를 펼치는지 질문을 던져보세요.</div>
          </motion.div>
        )}
        
        {sessions.map((session, idx) => (
          <motion.div 
            key={session.userQuery?.id || idx}
            className="session-tree"
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.5 }}
          >
            {/* The Trunk Line connecting the tree */}
            <div className="tree-trunk"></div>

            {/* 1. Root Node (User Query - Digital Twin) */}
            <div className="tree-root-node">
              <div className="tree-root-header">
                <User size={18} /> 디지털 트윈 (나의 핵심 질문)
              </div>
              <div className="tree-root-content">
                {session.userQuery?.content}
              </div>
            </div>

            {/* 2. Branches (AI Discussion) */}
            {(session.discussions.length > 0 || (idx === sessions.length - 1 && typingAgents.length > 0)) && (
              <div className="tree-branches-container">
                {session.discussions.map((disc, dIdx) => {
                  const position = dIdx % 2 === 0 ? 'left' : 'right';
                  return (
                    <motion.div 
                      key={disc.id || dIdx} 
                      className={`tree-branch-node ${position}`}
                      initial={{ opacity: 0, x: position === 'left' ? -20 : 20 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ type: 'spring', stiffness: 100 }}
                    >
                      <div className="branch-header" style={{ color: disc.agentColor || 'var(--color-text-main)' }}>
                        <Bot size={16} /> {disc.senderName || 'AI'}
                        <span className="branch-badge" style={{ color: disc.agentColor, background: `${disc.agentColor}1A` }}>
                          {disc.actionType || '의견 제안'}
                        </span>
                      </div>
                      <div className="branch-content">
                        {disc.content}
                      </div>
                    </motion.div>
                  );
                })}

                {/* Typing Skeletons for current active session */}
                {idx === sessions.length - 1 && typingAgents.map((agent, tIdx) => {
                  const position = (session.discussions.length + tIdx) % 2 === 0 ? 'left' : 'right';
                  return (
                    <motion.div 
                      key={`typing-${agent.id}-${tIdx}`} 
                      className={`tree-branch-node ${position}`}
                      initial={{ opacity: 0, scale: 0.9 }}
                      animate={{ opacity: 1, scale: 1 }}
                      exit={{ opacity: 0 }}
                    >
                      <div className="branch-header" style={{ color: agent.color || 'var(--color-text-muted)' }}>
                        <Bot size={16} /> {agent.name}
                        <span style={{ fontSize: '12px', color: 'var(--color-text-muted)' }}>{agent.action || '마인드맵 가지 뻗는 중...'}</span>
                      </div>
                      <div className="skeleton-light" style={{ width: '80%' }}></div>
                      <div className="skeleton-light" style={{ width: '60%' }}></div>
                      <div className="skeleton-light" style={{ width: '40%' }}></div>
                    </motion.div>
                  );
                })}
              </div>
            )}

            {/* 3. Convergence Node (Final Collaborative Answer) */}
            {session.finalAnswer && (
              <motion.div 
                className="tree-convergence-node"
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: 0.3, type: 'spring', stiffness: 120 }}
              >
                <div className="convergence-header">
                  <Sparkles size={20} /> AI 조별 회의 최종 결론
                </div>
                <div className="convergence-content">
                  {session.finalAnswer.content}
                </div>
              </motion.div>
            )}
          </motion.div>
        ))}
      </AnimatePresence>
    </div>
  );
}
