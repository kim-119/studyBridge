import React from 'react';
import { CheckCircle2, Circle } from 'lucide-react';

function LegacyTask({ task, isToggling, onToggle }) {
  return (
    <li>
      <button
        type="button"
        className="mobile-roadmap__step"
        disabled={!task.hasServerId || isToggling}
        onClick={onToggle}
      >
        {task.isCompleted ? (
          <CheckCircle2 size={20} className="mobile-roadmap__check is-done" />
        ) : (
          <Circle size={20} className="mobile-roadmap__check" />
        )}
        <span>{task.content}</span>
      </button>
    </li>
  );
}

export default function RoadmapLegacyWeeks({ weeks, togglingTaskId, onToggleTask }) {
  return (
    <>
      <p className="mobile-notice mobile-section">
        이 로드맵은 이전 형식입니다. 84일(12주 × 7일) 구조로 다시 생성하려면 로드맵을 재생성해주세요.
      </p>

      <ul className="mobile-list">
        {weeks.map((week) => (
          <li key={week.weekNumber} className="mobile-card">
            <h3 className="mobile-section__title">
              {week.weekNumber}주차 · {week.title}
            </h3>
            {week.description && <p className="mobile-card__meta">{week.description}</p>}

            <ul className="mobile-list">
              {week.tasks.map((task) => (
                <LegacyTask
                  key={task.taskId}
                  task={task}
                  isToggling={togglingTaskId === task.taskId}
                  onToggle={() => onToggleTask(task.taskId)}
                />
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </>
  );
}
