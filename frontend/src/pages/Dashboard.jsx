import React, { useEffect, useState } from 'react';
import FullCalendar from '@fullcalendar/react';
import dayGridPlugin from '@fullcalendar/daygrid';
import interactionPlugin from '@fullcalendar/interaction';

import StudyTimer from '../components/StudyTimer';

export default function Dashboard() {
  const userEmail = localStorage.getItem('userEmail') || '게스트';
  const userName = userEmail.includes('@') ? userEmail.split('@')[0] : userEmail;

  const [todayStudySeconds, setTodayStudySeconds] = useState(0);
  const [selectedDate, setSelectedDate] = useState('');
  const [todoText, setTodoText] = useState('');
  const [todos, setTodos] = useState({});

  useEffect(() => {
    const savedTodos = JSON.parse(localStorage.getItem('calendarTodos')) || {};
    setTodos(savedTodos);
  }, []);

  const formatStudyTime = (seconds) => {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);

    if (h > 0) return `${h}시간 ${m}분`;
    return `${m}분`;
  };

  const handleDateClick = (arg) => {
    setSelectedDate(arg.dateStr);
    setTodoText('');
  };

  const handleAddTodo = () => {
    if (!selectedDate) {
      alert('날짜를 먼저 선택하세요.');
      return;
    }

    if (!todoText.trim()) {
      alert('할 일을 입력하세요.');
      return;
    }

    const nextTodos = {
      ...todos,
      [selectedDate]: [
        ...(todos[selectedDate] || []),
        {
          id: Date.now(),
          text: todoText.trim(),
          done: false,
        },
      ],
    };

    setTodos(nextTodos);
    localStorage.setItem('calendarTodos', JSON.stringify(nextTodos));
    setTodoText('');
  };

  const handleDeleteTodo = (date, todoId) => {
    const updatedList = todos[date].filter((todo) => todo.id !== todoId);

    const nextTodos = {
      ...todos,
      [date]: updatedList,
    };

    if (updatedList.length === 0) {
      delete nextTodos[date];
    }

    setTodos(nextTodos);
    localStorage.setItem('calendarTodos', JSON.stringify(nextTodos));
  };

  const handleToggleTodo = (date, todoId) => {
    const updatedList = todos[date].map((todo) =>
      todo.id === todoId ? { ...todo, done: !todo.done } : todo
    );

    const nextTodos = {
      ...todos,
      [date]: updatedList,
    };

    setTodos(nextTodos);
    localStorage.setItem('calendarTodos', JSON.stringify(nextTodos));
  };

  const calendarEvents = Object.entries(todos).flatMap(([date, todoList]) =>
    todoList.map((todo) => ({
      id: String(todo.id),
      title: todo.done ? `완료: ${todo.text}` : todo.text,
      date,
    }))
  );

  const summaryCards = [
    {
      title: '오늘의 학습 시간',
      value: formatStudyTime(todayStudySeconds),
      desc: '종료된 개인 학습 시간 기준',
    },
    {
      title: '진행 중인 스터디',
      value: '3개',
      desc: '참여 중인 그룹 스터디',
    },
    {
      title: '등록된 Todo',
      value: `${Object.values(todos).flat().length}개`,
      desc: '캘린더에 등록된 전체 할 일',
    },
  ];

  return (
    <div
      style={{
        width: '100%',
        maxWidth: '1280px',
        margin: '0 auto',
        padding: '24px',
        boxSizing: 'border-box',
      }}
    >
      <div
        className="glass-panel animate-fade-in"
        style={{ padding: '30px', marginBottom: '24px' }}
      >
        <h2 style={{ margin: 0, color: 'var(--color-primary)' }}>
          환영합니다, {userName}님!
        </h2>
        <p style={{ color: 'var(--color-text-muted)', marginTop: '8px' }}>
          오늘의 학습 현황을 확인하고 스터디 일정을 관리해 보세요.
        </p>
      </div>

      <StudyTimer onTimeUpdate={setTodayStudySeconds} />

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(3, 1fr)',
          gap: '16px',
          marginTop: '24px',
          marginBottom: '24px',
        }}
      >
        {summaryCards.map((card, index) => (
          <div
            key={index}
            className="glass-panel animate-fade-in"
            style={{ padding: '22px' }}
          >
            <p style={{ margin: 0, fontSize: '14px', color: 'var(--color-text-muted)' }}>
              {card.title}
            </p>
            <h3
              style={{
                margin: '10px 0 6px',
                fontSize: '26px',
                color: 'var(--color-primary)',
              }}
            >
              {card.value}
            </h3>
            <p style={{ margin: 0, fontSize: '13px', color: 'var(--color-text-muted)' }}>
              {card.desc}
            </p>
          </div>
        ))}
      </div>

      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          gap: '24px',
        }}
      >
        <div className="glass-panel animate-fade-in" style={{ padding: '20px' }}>
          <style>
            {`
              .fc-theme-standard .fc-scrollgrid { border-color: var(--color-border); }
              .fc-theme-standard td, .fc-theme-standard th { border-color: var(--color-border); }
              .fc-col-header-cell-cushion { color: var(--color-text-main); font-weight: 600; padding: 12px 0 !important; }
              .fc-daygrid-day-number { color: var(--color-text-main); font-weight: 500; }
              .fc .fc-button-primary { background-color: var(--color-primary); border-color: var(--color-primary); }
              .fc .fc-button-primary:hover { background-color: var(--color-primary-hover); border-color: var(--color-primary-hover); }
              .fc .fc-button-primary:not(:disabled):active,
              .fc .fc-button-primary:not(:disabled).fc-button-active {
                background-color: var(--color-primary-hover);
                border-color: var(--color-primary-hover);
              }
              .fc-event {
                background-color: rgba(96, 201, 90, 0.15);
                border: 1px solid var(--color-primary);
                color: var(--color-text-main);
                border-radius: 4px;
                padding: 2px 4px;
              }
              .fc-day-today { background-color: rgba(96, 201, 90, 0.05) !important; }
            `}
          </style>

          <FullCalendar
            plugins={[dayGridPlugin, interactionPlugin]}
            initialView="dayGridMonth"
            events={calendarEvents}
            dateClick={handleDateClick}
            headerToolbar={{
              left: 'prev,next today',
              center: 'title',
              right: 'dayGridMonth,dayGridWeek',
            }}
            height={600}
          />
        </div>

        <div className="glass-panel animate-fade-in" style={{ padding: '20px' }}>
          <h3 style={{ marginBottom: '12px' }}>날짜별 Todo</h3>

          <p style={{ color: 'var(--color-text-muted)', marginTop: 0 }}>
            {selectedDate ? `선택 날짜: ${selectedDate}` : '캘린더에서 날짜를 선택하세요.'}
          </p>

          <div style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
            <input
              className="input-field"
              value={todoText}
              onChange={(e) => setTodoText(e.target.value)}
              placeholder="할 일을 입력하세요"
              disabled={!selectedDate}
            />
            <button
              className="btn-primary"
              onClick={handleAddTodo}
              style={{ width: '80px', flexShrink: 0 }}
              disabled={!selectedDate}
            >
              추가
            </button>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {selectedDate && todos[selectedDate]?.length > 0 ? (
              todos[selectedDate].map((todo) => (
                <div
                  key={todo.id}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    padding: '10px',
                    border: '1px solid var(--color-border)',
                    borderRadius: '8px',
                    backgroundColor: 'var(--color-bg-card)',
                  }}
                >
                  <input
                    type="checkbox"
                    checked={todo.done}
                    onChange={() => handleToggleTodo(selectedDate, todo.id)}
                  />
                  <span
                    style={{
                      flex: 1,
                      color: todo.done
                        ? 'var(--color-text-muted)'
                        : 'var(--color-text-main)',
                      textDecoration: todo.done ? 'line-through' : 'none',
                    }}
                  >
                    {todo.text}
                  </span>
                  <button
                    className="btn-outline"
                    onClick={() => handleDeleteTodo(selectedDate, todo.id)}
                    style={{
                      width: '50px',
                      height: '30px',
                      fontSize: '12px',
                    }}
                  >
                    삭제
                  </button>
                </div>
              ))
            ) : (
              <p style={{ color: 'var(--color-text-muted)', fontSize: '14px' }}>
                등록된 Todo가 없습니다.
              </p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}