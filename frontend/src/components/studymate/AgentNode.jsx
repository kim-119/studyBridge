import React from 'react';
import { motion } from 'framer-motion';
import { Bot, CheckCircle2 } from 'lucide-react';
import './studymate-premium.css';

export default function AgentNode({ 
  agent, 
  status = 'idle', // 'idle' | 'analyzing' | 'reviewing' | 'done'
  isActive = false,
  index = 0
}) {
  const getStatusText = () => {
    switch(status) {
      case 'analyzing': return '분석 중...';
      case 'reviewing': return '검토 중...';
      case 'done': return '작업 완료';
      default: return '대기 중';
    }
  };

  const isWorking = status === 'analyzing' || status === 'reviewing';

  return (
    <motion.div 
      className={`agent-node-light ${isActive ? 'active' : ''} ${status}`}
      initial={{ opacity: 0, x: -20 }}
      animate={{ opacity: 1, x: 0 }}
      transition={{ duration: 0.4, delay: index * 0.1 }}
    >
      <div style={{ position: 'relative' }}>
        <div className="pulse-ring-light"></div>
        <div className={`avatar-light ${isActive ? 'active' : ''}`} style={{ color: agent.color || 'var(--color-primary)' }}>
          <Bot size={24} />
        </div>
      </div>
      
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: '15px', fontWeight: '700', color: 'var(--color-text-main)', marginBottom: '4px' }}>
          {agent.name || 'AI 에이전트'}
        </div>
        <div style={{ fontSize: '12px', color: 'var(--color-text-muted)' }}>
          {agent.role || '학습 도우미'}
        </div>
      </div>

      <div>
        {status === 'done' ? (
          <CheckCircle2 size={18} color="var(--color-primary)" />
        ) : (
          <span style={{ 
            fontSize: '11px', 
            fontWeight: '600', 
            padding: '4px 8px', 
            borderRadius: '20px',
            backgroundColor: isWorking ? 'rgba(96, 201, 90, 0.1)' : '#F3F4F6',
            color: isWorking ? 'var(--color-primary)' : 'var(--color-text-muted)'
          }}>
            {getStatusText()}
          </span>
        )}
      </div>
    </motion.div>
  );
}
