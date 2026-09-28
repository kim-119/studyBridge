import React, { useRef } from 'react';
import FullCalendar from '@fullcalendar/react';
import dayGridPlugin from '@fullcalendar/daygrid';
import interactionPlugin from '@fullcalendar/interaction';
import { ChevronLeft, ChevronRight } from 'lucide-react';
import SubTabs from '../../components/SubTabs';
import { addDaysToIsoDate, toLocalIsoDate } from './scheduleEvents';

export const MONTH_VIEW = 'dayGridMonth';
export const WEEK_VIEW = 'dayGridWeek';

const VIEW_TABS = [
  { key: MONTH_VIEW, label: '월' },
  { key: WEEK_VIEW, label: '주' },
];

const CALENDAR_PLUGINS = [dayGridPlugin, interactionPlugin];

const VIEW_OPTIONS = {
  [MONTH_VIEW]: { dayMaxEvents: 2 },
  [WEEK_VIEW]: { dayMaxEvents: false },
};

function describeVisibleRange(view) {
  const firstDate = toLocalIsoDate(view.currentStart);
  const lastDate = addDaysToIsoDate(toLocalIsoDate(view.currentEnd), -1);
  return { type: view.type, title: view.title, firstDate, lastDate };
}

function renderEventContent(arg) {
  const className = arg.event.extendedProps.completed
    ? 'mobile-calendar__event is-completed'
    : 'mobile-calendar__event';

  return <span className={className}>{arg.event.title}</span>;
}

export default function ScheduleCalendar({
  events,
  selectedDate,
  visibleRange,
  onSelectDate,
  onSelectEvent,
  onVisibleRangeChange,
}) {
  const calendarRef = useRef(null);
  const activeView = visibleRange?.type || MONTH_VIEW;

  const calendarApi = () => calendarRef.current?.getApi();

  const showToday = () => {
    calendarApi()?.today();
    onSelectDate(toLocalIsoDate(new Date()));
  };

  const handleMoreLinkClick = (arg) => {
    onSelectDate(toLocalIsoDate(arg.date));
    return WEEK_VIEW;
  };

  const highlightSelectedDate = (arg) =>
    toLocalIsoDate(arg.date) === selectedDate ? ['is-selected'] : [];

  return (
    <section className="mobile-card mobile-section mobile-calendar">
      <div className="mobile-calendar__toolbar">
        <button type="button" aria-label="이전" onClick={() => calendarApi()?.prev()}>
          <ChevronLeft size={18} />
        </button>
        <span className="mobile-calendar__title">{visibleRange?.title || ''}</span>
        <button type="button" aria-label="다음" onClick={() => calendarApi()?.next()}>
          <ChevronRight size={18} />
        </button>
        <button type="button" className="mobile-calendar__today" onClick={showToday}>
          오늘
        </button>
      </div>

      <SubTabs
        tabs={VIEW_TABS}
        activeKey={activeView}
        onChange={(viewType) => calendarApi()?.changeView(viewType)}
      />

      <FullCalendar
        ref={calendarRef}
        plugins={CALENDAR_PLUGINS}
        initialView={MONTH_VIEW}
        headerToolbar={false}
        locale="ko"
        height="auto"
        fixedWeekCount={false}
        views={VIEW_OPTIONS}
        events={events}
        eventContent={renderEventContent}
        dayCellClassNames={highlightSelectedDate}
        dateClick={(arg) => onSelectDate(arg.dateStr)}
        eventClick={(arg) => onSelectEvent(arg.event.id)}
        moreLinkClick={handleMoreLinkClick}
        datesSet={(arg) => onVisibleRangeChange(describeVisibleRange(arg.view))}
      />
    </section>
  );
}
