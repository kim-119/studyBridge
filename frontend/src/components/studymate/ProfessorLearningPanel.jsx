import React from 'react';
import { GraduationCap, Bookmark, Bot } from 'lucide-react';

/**
 * 교수님들과 학습하기 패널 (우측)
 * - 기존 "마인드맵 (크게 보기)" 영역을 대체한다.
 * - 픽셀 교실 이미지 위에 구름형 말풍선을 얹어 "교수님들이 함께 도와주는" 느낌을 준다.
 * - 저장된 메모(북마크) 목록은 기존 흐름을 그대로 유지해 하단에 렌더한다.
 *
 * 주의: 채팅 스트리밍/에이전트 호출/답변 카드 로직은 건드리지 않는다.
 *       메모 저장/스크롤 핸들러(onScrollToMemo)는 상위(StudyMate)에서 그대로 내려받는다.
 */
const ProfessorLearningPanel = ({ memos = [], onScrollToMemo }) => {
  return (
    <div className="prof-learn-panel">
      {/* 헤더 */}
      <div className="prof-learn-header">
        <span className="prof-learn-header-icon"><GraduationCap size={18} /></span>
        <h3>교수님들과 학습하기</h3>
      </div>

      {/* 픽셀 교실 + 구름 말풍선 */}
      <div className="prof-learn-stage">
        <div className="prof-cloud prof-cloud--main">
          궁금한 내용을 질문하면<br />교수님들이 함께 도와드려요!
        </div>

        <img
          src="/studymate-professor-classroom.png"
          alt="교수님들과 함께하는 픽셀 교실"
          className="prof-learn-img"
          loading="lazy"
        />

        {/* 교수별 미니 구름 말풍선 (반박 · 비교 · 예시) */}
        <span className="prof-cloud prof-cloud--mini prof-cloud--rebut">반박</span>
        <span className="prof-cloud prof-cloud--mini prof-cloud--compare">비교</span>
        <span className="prof-cloud prof-cloud--mini prof-cloud--example">예시</span>
      </div>

      {/* 저장된 메모(북마크) — 기존 메모하기 흐름 유지 */}
      <div className="prof-learn-memos">
        <div className="prof-learn-memos-head">
          <Bookmark size={15} color="#10b981" />
          <span>저장된 메모</span>
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
