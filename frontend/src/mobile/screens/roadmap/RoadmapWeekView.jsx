import React from 'react';
import { CheckCircle2, ChevronRight, Circle } from 'lucide-react';
import { isWeekCompleted } from './roadmapModel';

function WeekChips({ weeks, selectedWeekNumber, onSelect }) {
  return (
    <div className="mobile-roadmap-weeks" role="tablist" aria-label="주차 선택">
      {weeks.map((week) => {
        const classNames = ['mobile-roadmap-weeks__chip'];
        if (week.weekNumber === selectedWeekNumber) classNames.push('is-active');
        if (isWeekCompleted(week)) classNames.push('is-done');

        return (
          <button
            key={week.weekNumber}
            type="button"
            role="tab"
            aria-selected={week.weekNumber === selectedWeekNumber}
            className={classNames.join(' ')}
            onClick={() => onSelect(week.weekNumber)}
          >
            {week.weekNumber}주차
          </button>
        );
      })}
    </div>
  );
}

function DayRow({ day, isToggling, onToggle, onOpen }) {
  return (
    <li className={day.completed ? 'mobile-roadmap-day is-done' : 'mobile-roadmap-day'}>
      <button
        type="button"
        className="mobile-roadmap-day__toggle"
        aria-label={day.completed ? `${day.dayLabel} 완료 취소` : `${day.dayLabel} 완료`}
        aria-pressed={day.completed}
        disabled={isToggling}
        onClick={onToggle}
      >
        {day.completed ? (
          <CheckCircle2 size={22} className="mobile-roadmap__check is-done" />
        ) : (
          <Circle size={22} className="mobile-roadmap__check" />
        )}
      </button>

      <button type="button" className="mobile-roadmap-day__body" onClick={onOpen}>
        <span className="mobile-roadmap-day__label">{day.dayLabel}</span>
        <span className="mobile-roadmap-day__title">{day.title}</span>
      </button>

      <ChevronRight size={18} className="mobile-row__chevron" />
    </li>
  );
}

export default function RoadmapWeekView({
  weeks,
  selectedWeekNumber,
  onSelectWeek,
  togglingDayKey,
  onToggleDay,
  onOpenDay,
}) {
  const week = weeks.find((candidate) => candidate.weekNumber === selectedWeekNumber) || weeks[0];

  return (
    <section className="mobile-section">
      <WeekChips weeks={weeks} selectedWeekNumber={week.weekNumber} onSelect={onSelectWeek} />

      <div className="mobile-card">
        <h3 className="mobile-section__title">
          {week.weekNumber}주차 · {week.title}
        </h3>
        {week.description && (
          <p className="mobile-card__meta">
            <span>주차 목표: {week.description}</span>
          </p>
        )}
        {week.weekSummary && <p className="mobile-card__meta">{week.weekSummary}</p>}

        <ul className="mobile-list">
          {week.days.map((day) => (
            <DayRow
              key={`${week.weekNumber}-${day.dayIndex}`}
              day={day}
              isToggling={togglingDayKey === `${week.weekNumber}-${day.dayIndex}`}
              onToggle={() => onToggleDay(week.weekNumber, day.dayIndex)}
              onOpen={() => onOpenDay(week.weekNumber, day.dayIndex)}
            />
          ))}
        </ul>
      </div>
    </section>
  );
}
