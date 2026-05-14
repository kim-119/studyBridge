import React, { useEffect, useState } from 'react';
import FullCalendar from '@fullcalendar/react';
import dayGridPlugin from '@fullcalendar/daygrid';
import interactionPlugin from '@fullcalendar/interaction';

import StudyTimer from '../components/StudyTimer';
import StudyStatistics from '../components/StudyStatistics';
import { todoService } from '../services/api';

export default function Dashboard() {
  const userEmail = localStorage.getItem('userEmail') || 'guest';
  const userId = localStorage.getItem('userId');
  const userName = userEmail.includes('@') ? userEmail.split('@')[0] : userEmail;

  const [todayStudySeconds, setTodayStudySeconds] = useState(0);
  const [selectedDate, setSelectedDate] = useState('');
  const [todoText, setTodoText] = useState('');
  const [todos, setTodos] = useState([]);
  const [selectedEndDate, setSelectedEndDate] = useState('');

  const [selectedEvent, setSelectedEvent] = useState(null);
  const [isEventModalOpen, setIsEventModalOpen] = useState(false);

  const fetchTodos = async () => {
    const savedUserId = localStorage.getItem('userId');

    if (!savedUserId) {
      setTodos([]);
      setSelectedDate('');
      setTodoText('');
      return;
    }

    try {
      const data = await todoService.getTodos(savedUserId);
      setTodos(Array.isArray(data) ? data : []);
    } catch (err) {
      console.error('Todo 조회 실패:', err);
      setTodos([]);
    }
  };

  useEffect(() => {
    const savedUserId = localStorage.getItem('userId');

    if (!savedUserId) {
      setTodos([]);
      setSelectedDate('');
      setTodoText('');
      return;
    }

    fetchTodos();
  }, [userId]);

  const formatStudyTime = (seconds) => {
    const totalSeconds = Math.max(0, Math.round(seconds || 0));
    const h = Math.floor(totalSeconds / 3600);
    const m = Math.floor((totalSeconds % 3600) / 60);
    const s = totalSeconds % 60;
    const parts = [];

    if (h) parts.push(`${h}시간`);
    if (m) parts.push(`${m}분`);
    if (s || parts.length === 0) parts.push(`${s}초`);

    return parts.join(' ');
  };

  const handleDateClick = (arg) => {
    setSelectedEndDate(arg.dateStr);
    setSelectedDate(arg.dateStr);
    setTodoText('');
  };

  const handleAddTodo = async () => {
    const savedUserId = localStorage.getItem('userId');

    if (!savedUserId) {
      alert('로그인이 필요합니다.');
      setTodos([]);
      setSelectedDate('');
      setTodoText('');
      return;
    }

    if (!selectedDate) {
      alert('날짜를 먼저 선택하세요.');
      return;
    }

    if (!todoText.trim()) {
      alert('할 일을 입력하세요.');
      return;
    }

    try {
      const endDate = selectedEndDate || selectedDate;
      await todoService.createTodo(savedUserId, {
        text: todoText.trim(),
        startDate: `${selectedDate}T00:00:00`,
        endDate: `${endDate}T23:59:59`,
        viewType: 'MONTH',
        completed: false,
      });

      setTodoText('');
      setSelectedEndDate('');
      await fetchTodos();
    } catch (err) {
      console.error('Todo 생성 실패:', err);
      setTodoText('');
      alert(err.message || 'Todo 생성에 실패했습니다.');
    }
  };

  const handleDeleteTodo = async (todoId) => {
    try {
      await todoService.deleteTodo(todoId);
      await fetchTodos();
    } catch (err) {
      console.error('Todo 삭제 실패:', err);
      alert(err.message || 'Todo 삭제에 실패했습니다.');
    }
  };

  const handleToggleTodo = async (todoId) => {
    try {
      await todoService.toggleTodo(todoId);
      await fetchTodos();
    } catch (err) {
      console.error('Todo 상태 변경 실패:', err);
      alert(err.message || 'Todo 상태 변경에 실패했습니다.');
    }
  };

  const eventColors = [
    "#DDF5E3",
    "#D9F0FF",
    "#FDF0D5",
    "#EEE3FF",
    "#E6FFF4"
  ];

  const calendarEvents = userId && Array.isArray(todos)
    ? todos.map((todo) => {
        // endDate가 있으면 사용, 없으면 startDate 기준으로 하루
        const startDate = todo.startDate ? todo.startDate.split('T')[0] : '';
        const endDate = todo.endDate 
          ? new Date(todo.endDate.split('T')[0])
          : startDate ? new Date(startDate) : new Date();
        // FullCalendar는 end 날짜의 다음날까지 표시하므로, endDate에 1일 추가
        const adjustedEndDate = new Date(endDate);
        adjustedEndDate.setDate(adjustedEndDate.getDate() + 1);
        
        return {
          id: String(todo.id),
          title: todo.text,
          start: startDate,
          end: adjustedEndDate.toISOString().split('T')[0],
          backgroundColor: eventColors[(todo.id || 0) % eventColors.length],
          borderColor: 'rgba(0,0,0,0.05)',
          textColor: '#1F2937',
          extendedProps: {
            completed: todo.completed,
          },
        };
      }).filter(e => e.start)
    : [];

  const isDateInTodoRange = (selectedDate, todo) => {
    if (!selectedDate || !todo.startDate) return false;
    const selected = new Date(selectedDate);
    const start = new Date(todo.startDate.split('T')[0]);
    const end = new Date((todo.endDate || todo.startDate).split('T')[0]);

    selected.setHours(0, 0, 0, 0);
    start.setHours(0, 0, 0, 0);
    end.setHours(0, 0, 0, 0);

    return selected >= start && selected <= end;
  };

  const filteredTodos = Array.isArray(todos) ? todos.filter((todo) =>
    isDateInTodoRange(selectedDate, todo)
  ) : [];

  const summaryCards = [
    {
      title: '오늘의 학습 시간',
      value: formatStudyTime(todayStudySeconds),
      desc: '종료된 개인 학습 시간 기준',
    },
    {
      title: '진행 중인 스터디',
      value: '0개',
      desc: '참여 중인 그룹 스터디',
    },
    {
      title: '등록된 Todo',
      value: `${Array.isArray(todos) ? todos.length : 0}개`,
      desc: '캘린더에 등록된 전체 할 일',
    },
  ];

  return (
    <div className="container-main dashboard-page">

      <StudyTimer onTimeUpdate={setTodayStudySeconds} />

      <div className="summary-grid">
        {summaryCards.map((card, index) => (
          <div
            key={index}
            className="glass-panel summary-card animate-fade-in"
          >
            <p>{card.title}</p>
            <h3>{card.value}</h3>
            <p>{card.desc}</p>
          </div>
        ))}
      </div>

      <div className="main-grid">
        <div className="glass-panel calendar-container animate-fade-in">

          <FullCalendar
            key={userId || 'guest'}
            plugins={[dayGridPlugin, interactionPlugin]}
            initialView="dayGridMonth"
            events={userId ? calendarEvents : []}
            dateClick={handleDateClick}
            eventClick={(info) => {
              setSelectedEvent(info.event);
              setIsEventModalOpen(true);
            }}
            eventContent={(arg) => {
              const isCompleted = arg.event.extendedProps.completed;
              return (
                <div style={{
                  width: '100%',
                  textDecoration: isCompleted ? 'line-through' : 'none',
                  color: isCompleted ? '#9CA3AF' : 'inherit',
                  overflow: 'hidden',
                  whiteSpace: 'nowrap',
                  textOverflow: 'ellipsis',
                  display: 'block'
                }}>
                  {arg.event.title}
                </div>
              );
            }}
            headerToolbar={{
              left: 'prev,next today',
              center: 'title',
              right: 'dayGridMonth,dayGridWeek',
            }}
            contentHeight="auto"
            views={{
              dayGridMonth: { dayMaxEvents: 3 },
              dayGridWeek: { dayMaxEvents: false }
            }}
          />
        </div>

        <div className="glass-panel todo-section animate-fade-in">
          <h3 style={{ marginBottom: '12px' }}>날짜별 Todo</h3>

          <p style={{ color: 'var(--color-text-muted)', marginTop: 0 }}>
            {selectedDate ? `시작 날짜: ${selectedDate}` : '캘린더에서 날짜를 선택하세요.'}
          </p>

          {selectedDate && (
            <div style={{ marginBottom: '12px', paddingBottom: '12px', borderBottom: '1px solid var(--color-border)' }}>
              <label style={{ fontSize: '13px', color: 'var(--color-text-muted)', display: 'block', marginBottom: '4px' }}>
                종료 날짜:
              </label>
              <input
                type="date"
                value={selectedEndDate}
                onChange={(e) => setSelectedEndDate(e.target.value)}
                min={selectedDate}
                className="input-field"
                style={{ marginBottom: 0 }}
              />
            </div>
          )}

          <div style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
            <input
              className="input-field"
              value={todoText}
              onChange={(e) => setTodoText(e.target.value)}
              placeholder="할 일을 입력하세요"
              disabled={!selectedDate || !userId}
            />
            <button
              className="btn-primary"
              onClick={handleAddTodo}
              style={{ width: '80px', flexShrink: 0 }}
              disabled={!selectedDate || !userId}
            >
              추가
            </button>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {userId && selectedDate && filteredTodos.length > 0 ? (
              filteredTodos.map((todo) => (
                <div
                  key={todo.id}
                  className={`todo-item ${todo.completed ? 'completed' : ''}`}
                >
                  <input
                    type="checkbox"
                    checked={todo.completed}
                    onChange={() => handleToggleTodo(todo.id)}
                  />
                  <span className="todo-text">
                    {todo.text}
                  </span>
                  <button
                    className="btn-outline"
                    onClick={() => handleDeleteTodo(todo.id)}
                    style={{ width: '50px', height: '30px', fontSize: '12px' }}
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

      {isEventModalOpen && selectedEvent && (
        <div style={{
          position: 'fixed', top: 0, left: 0, width: '100%', height: '100%', 
          backgroundColor: 'rgba(0,0,0,0.5)', display: 'flex', justifyContent: 'center', alignItems: 'center', zIndex: 1000
        }} onClick={() => setIsEventModalOpen(false)}>
          <div className="glass-panel animate-fade-in" style={{ width: '90%', maxWidth: '400px', padding: '30px' }} onClick={(e) => e.stopPropagation()}>
            <h3 style={{ margin: '0 0 16px 0', color: 'var(--color-primary)', borderBottom: '1px solid var(--color-border)', paddingBottom: '12px' }}>
              Todo 상세
            </h3>
            <div style={{ display: 'grid', gap: '12px', fontSize: '0.95rem', color: 'var(--color-text-main)' }}>
              <div>
                <span style={{ fontWeight: 600, color: 'var(--color-text-muted)', display: 'inline-block', width: '80px', verticalAlign: 'top' }}>할 일:</span>
                <span style={{ display: 'inline-block', width: 'calc(100% - 85px)', wordBreak: 'break-word', whiteSpace: 'pre-wrap' }}>{selectedEvent.title}</span>
              </div>
              <div>
                <span style={{ fontWeight: 600, color: 'var(--color-text-muted)', display: 'inline-block', width: '80px' }}>시작 날짜:</span>
                <span>{selectedEvent.startStr.split('T')[0]}</span>
              </div>
              <div>
                <span style={{ fontWeight: 600, color: 'var(--color-text-muted)', display: 'inline-block', width: '80px' }}>종료 날짜:</span>
                <span>
                  {(() => {
                    const endDate = new Date(selectedEvent.endStr || selectedEvent.startStr);
                    if (selectedEvent.endStr) {
                      endDate.setDate(endDate.getDate() - 1);
                    }
                    return endDate.toISOString().split('T')[0];
                  })()}
                </span>
              </div>
              <div>
                <span style={{ fontWeight: 600, color: 'var(--color-text-muted)', display: 'inline-block', width: '80px' }}>상태:</span>
                <span style={{ color: selectedEvent.extendedProps.completed ? 'var(--color-text-muted)' : 'var(--color-primary)', fontWeight: 600 }}>
                  {selectedEvent.extendedProps.completed ? '완료' : '미완료'}
                </span>
              </div>
            </div>
            <div style={{ marginTop: '24px', textAlign: 'right' }}>
              <button className="btn-primary" style={{ width: 'auto', padding: '8px 24px' }} onClick={() => setIsEventModalOpen(false)}>닫기</button>
            </div>
          </div>
        </div>
      )}

      <StudyStatistics todayStudySeconds={todayStudySeconds} />
    </div>
  );
}