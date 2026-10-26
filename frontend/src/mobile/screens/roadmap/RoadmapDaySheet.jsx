import React from 'react';
import { CheckCircle2, Circle } from 'lucide-react';
import BottomSheet from '../../components/BottomSheet';
import Button from '../../components/Button';

function DetailList({ label, items }) {
  if (items.length === 0) return null;

  return (
    <section className="mobile-roadmap-detail">
      <h4 className="mobile-roadmap-detail__label">{label}</h4>
      <ul className="mobile-bullets">
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

function DetailText({ label, text }) {
  if (!text) return null;

  return (
    <section className="mobile-roadmap-detail">
      <h4 className="mobile-roadmap-detail__label">{label}</h4>
      <p className="mobile-paragraph">{text}</p>
    </section>
  );
}

export default function RoadmapDaySheet({ weekNumber, day, isToggling, onToggle, onClose }) {
  const isOpen = Boolean(day);

  return (
    <BottomSheet
      title={day ? `${weekNumber}주차 ${day.dayLabel}` : ''}
      isOpen={isOpen}
      onClose={onClose}
    >
      {day && (
        <>
          <h3 className="mobile-section__title">{day.title}</h3>

          <DetailText label="오늘 목표" text={day.objective} />

          {day.coreConcepts.length > 0 && (
            <section className="mobile-roadmap-detail">
              <h4 className="mobile-roadmap-detail__label">핵심 개념</h4>
              <ul className="mobile-chips">
                {day.coreConcepts.map((concept) => (
                  <li key={concept}>{concept}</li>
                ))}
              </ul>
            </section>
          )}

          <DetailList label="할 일" items={day.tasks} />
          <DetailList label="복습 질문" items={day.reviewQuestions} />
          <DetailText label="체크포인트" text={day.checkpoint} />
          <DetailText label="산출물" text={day.deliverable} />

          <Button
            fullWidth
            variant={day.completed ? 'secondary' : 'primary'}
            isLoading={isToggling}
            onClick={onToggle}
          >
            {day.completed ? <CheckCircle2 size={16} /> : <Circle size={16} />}
            {day.completed ? '완료 취소' : '학습 완료'}
          </Button>
        </>
      )}
    </BottomSheet>
  );
}
