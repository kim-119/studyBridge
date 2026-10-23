import React from 'react';
import { Bookmark, Bot } from 'lucide-react';

/**
 * 우측 사이드 패널 — 저장된 메모 중심.
 * - 픽셀 교실 이미지/구름 말풍선은 중앙 "교수님들과 대화" 탭으로 이동했다.
 * - 여기서는 저장된 메모(북마크) 목록을 메인으로 두고, 하단에 "교수님들과 대화" 탭 안내
 *   작은 도움말 카드를 둔다.
 *
 * 주의: 채팅 스트리밍/에이전트 호출/답변 카드 로직은 건드리지 않는다.
 *       메모 저장/스크롤 핸들러(onScrollToMemo)는 상위(StudyMate)에서 그대로 내려받는다.
 */
const ProfessorLearningPanel = ({ memos = [], onScrollToMemo }) => {
  return (
    <div className="prof-learn-panel">
      {/* 헤더 */}
      <div className="prof-learn-header">
        <span className="prof-learn-header-icon"><Bookmark size={18} /></span>
        <h3>저장된 메모</h3>
      </div>

      {/* 저장된 메모(북마크) — 기존 메모하기 흐름 유지 */}
      <div className="prof-learn-memos">
        <div className="prof-learn-memos-head">
          <Bookmark size={15} color="#10b981" />
          <span>메모 목록</span>
          <span className="prof-learn-memos-count">{memos.length}개</span>
        </div>

        {memos.length === 0 ? (
          <div className="prof-learn-memos-empty">
            <Bookmark size={22} color="#e2e8f0" fill="#e2e8f0" />
            <div>
              유용한 답변에 <strong>📌 메모하기</strong>를 누르면<br />이곳에 저장됩니다.
            </div>
          </div>
        ) : (
          <div className="prof-learn-memos-list">
            {memos.map((msg) => (
              <button
                type="button"
                key={msg.id}
                className="prof-learn-memo-card"
                onClick={() => onScrollToMemo?.(msg.id)}
              >
                <div className="prof-learn-memo-card-name">
                  <Bot size={13} /> {msg.senderName || msg.sender_name || 'AI'}
                </div>
                <div className="prof-learn-memo-card-body">"{msg.content}"</div>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default ProfessorLearningPanel;
