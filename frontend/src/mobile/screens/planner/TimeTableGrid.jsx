import React from 'react';
import {
  SLOTS_PER_HOUR,
  TIMETABLE_END_HOUR,
  TIMETABLE_START_HOUR,
  isSlotChecked,
} from './plannerAdapter';

const SLOT_LABELS = ['00', '10', '20', '30', '40', '50'];

export default function TimeTableGrid({ timeTable, onToggle }) {
  const hours = [];
  for (let hour = TIMETABLE_START_HOUR; hour <= TIMETABLE_END_HOUR; hour += 1) hours.push(hour);

  return (
    <div className="mobile-timetable">
      <div className="mobile-timetable__head">
        <span />
        {SLOT_LABELS.map((label) => (
          <span key={label}>{label}</span>
        ))}
      </div>

      {hours.map((hour) => (
        <div className="mobile-timetable__row" key={hour}>
          <span className="mobile-timetable__hour">{String(hour).padStart(2, '0')}</span>

          {Array.from({ length: SLOTS_PER_HOUR }, (_, slot) => {
            const checked = isSlotChecked(timeTable, hour, slot);

            return (
              <button
                key={slot}
                type="button"
                className={checked ? 'mobile-timetable__slot is-on' : 'mobile-timetable__slot'}
                aria-label={`${hour}시 ${SLOT_LABELS[slot]}분 ${checked ? '해제' : '선택'}`}
                aria-pressed={checked}
                disabled={!onToggle}
                onClick={() => onToggle?.(hour, slot)}
              />
            );
          })}
        </div>
      ))}
    </div>
  );
}
