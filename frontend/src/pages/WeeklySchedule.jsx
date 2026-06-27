import React, { useEffect, useState } from 'react';
import FullCalendar from '@fullcalendar/react';
import dayGridPlugin from '@fullcalendar/daygrid';
import interactionPlugin from '@fullcalendar/interaction';
import { useAuth } from '../hooks/useAuth';
import { todoService } from '../services/api';

/**
 * 주간 일정 탭.
 *  - 기존 Todo API(/api/todos: getTodos/createTodo/toggleTodo/deleteTodo)와 FullCalendar 를 재사용한다.
 *  - 새 Todo 테이블/엔드포인트를 만들지 않고, 기존 날짜범위(startDate/endDate) 구조를 그대로 사용한다.
 *  - 월/주 보기 토글 + 우측 날짜별 Todo 패널 UI 만 정리/개선.
 */
const eventColors = ['#DDF5E3', '#D9F0FF', '#FDF0D5', '#EEE3FF', '#E6FFF4'];

// 플래너에서 추가된 Todo 는 text 가 '[플래너]' 로 시작한다(Todo 모델에 별도 출처 필드가 없어 접두어로 구분).
const PLANNER_PREFIX = '[플래너]';
const isPlannerTodo = (t) => typeof t?.text === 'string' && t.text.startsWith(PLANNER_PREFIX);
const displayTodoText = (text) =>
  (typeof text === 'string' && text.startsWith(PLANNER_PREFIX)) ? text.slice(PLANNER_PREFIX.length).trim() : text;

function toDateStr(d) {
  const tz = new Date(d.getTime() - d.getTimezoneOffset() * 60000);
  return tz.toISOString().split('T')[0];
}

export default function WeeklySchedule() {
  const { userId } = useAuth();
  const [todos, setTodos] = useState([]);
  const [selectedDate, setSelectedDate] = useState(toDateStr(new Date()));
  const [selectedEndDate, setSelectedEndDate] = useState('');
  const [todoText, setTodoText] = useState('');

  const fetchTodos = async () => {
    const savedUserId = localStorage.getItem('userId');
    if (!savedUserId) { setTodos([]); return; }
    try {
      const data = await todoService.getTodos(savedUserId);
      setTodos(Array.isArray(data) ? data : []);
    } catch (err) {
      console.error('Todo 조회 실패:', err);
      setTodos([]);
    }
  };

  useEffect(() => { fetchTodos(); }, []);

  const handleDateClick = (arg) => setSelectedDate(arg.dateStr);

  const handleAddTodo = async () => {
    const savedUserId = localStorage.getItem('userId');
    if (!savedUserId) { alert('로그인이 필요합니다.'); return; }
    if (!selectedDate) { alert('날짜를 먼저 선택하세요.'); return; }
    if (!todoText.trim()) { alert('할 일을 입력하세요.'); return; }
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
      alert(err.message || 'Todo 생성에 실패했습니다.');
    }
  };

  const handleDeleteTodo = async (todoId) => {
    try { await todoService.deleteTodo(todoId); await fetchTodos(); }
    catch (err) { alert(err.message || 'Todo 삭제에 실패했습니다.'); }
  };

  const handleToggleTodo = async (todoId) => {
    try { await todoService.toggleTodo(todoId); await fetchTodos(); }
    catch (err) { alert(err.message || 'Todo 상태 변경에 실패했습니다.'); }
  };

  const calendarEvents = userId && Array.isArray(todos)
    ? todos.map((todo) => {
        const startDate = todo.startDate ? todo.startDate.split('T')[0] : '';
        const endDate = todo.endDate ? new Date(todo.endDate.split('T')[0]) : (startDate ? new Date(startDate) : new Date());
        const adjustedEndDate = new Date(endDate);
        adjustedEndDate.setDate(adjustedEndDate.getDate() + 1);
        const planner = isPlannerTodo(todo);
        return {
          id: String(todo.id),
          title: displayTodoText(todo.text),
          start: startDate,
          end: adjustedEndDate.toISOString().split('T')[0],
          backgroundColor: planner ? '#DCFCE7' : eventColors[(todo.id || 0) % eventColors.length],
          borderColor: planner ? '#86EFAC' : 'rgba(0,0,0,0.05)',
          textColor: '#1F2937',
          extendedProps: { completed: todo.completed, source: planner ? 'planner' : 'todo' },
        };
      }).filter((e) => e.start)
    : [];

  const isDateInTodoRange = (date, todo) => {
    if (!date || !todo.startDate) return false;
    const selected = new Date(date);
    const start = new Date(todo.startDate.split('T')[0]);
    const end = new Date((todo.endDate || todo.startDate).split('T')[0]);
    selected.setHours(0, 0, 0, 0); start.setHours(0, 0, 0, 0); end.setHours(0, 0, 0, 0);
    return selected >= start && selected <= end;
  };

  const filteredTodos = Array.isArray(todos) ? todos.filter((t) => isDateInTodoRange(selectedDate, t)) : [];
  const completedCount = filteredTodos.filter((t) => t.completed).length;

  return (
    <div className="container-main dashboard-page" style={{ maxWidth: '1200px', margin: '0 auto', padding: 'clamp(12px, 4vw, 24px)' }}>
      <div style={{ marginBottom: '20px' }}>
        <h1 style={{ fontSize: '24px', fontWeight: 900, color: '#15803D', margin: '0 0 6px 0' }}>주간 일정</h1>
        <p style={{ color: '#6B7280', margin: 0, fontSize: '14px' }}>월/주 보기로 일정을 확인하고, 날짜를 선택해 할 일을 관리하세요.</p>
      </div>

      <div className="main-grid">
        {/* 좌측 캘린더 (월/주 토글 + today + 이전/다음) */}
        <div className="glass-panel calendar-container animate-fade-in">
          <FullCalendar
            key={userId || 'guest'}
            plugins={[dayGridPlugin, interactionPlugin]}
            initialView="dayGridMonth"
            events={userId ? calendarEvents : []}
            dateClick={handleDateClick}
            headerToolbar={{ left: 'prev,next today', center: 'title', right: 'dayGridMonth,dayGridWeek' }}
            buttonText={{ today: '오늘', month: '월', week: '주' }}
            locale="ko"
            height="650px"
            views={{ dayGridMonth: { dayMaxEvents: 3 }, dayGridWeek: { dayMaxEvents: false } }}
            eventContent={(arg) => {
              const isCompleted = arg.event.extendedProps.completed;
              return (
                <div style={{ width: '100%', textDecoration: isCompleted ? 'line-through' : 'none', color: isCompleted ? '#9CA3AF' : 'inherit', overflow: 'hidden', whiteSpace: 'nowrap', textOverflow: 'ellipsis' }}>
                  {arg.event.title}
                </div>
              );
            }}
            dayCellDidMount={(info) => {
              if (info.dateStr === selectedDate) {
                info.el.style.backgroundColor = '#ECFDF3';
                info.el.style.boxShadow = 'inset 0 0 0 2px #BBF7D0';
              } else {
                info.el.style.backgroundColor = '';
                info.el.style.boxShadow = '';
              }
            }}
          />
        </div>

        {/* 우측 날짜별 Todo 패널 */}
        <div className="glass-panel todo-section animate-fade-in">
          {/* 등록된 Todo 개수 카드 */}
          <div style={{ display: 'flex', gap: '10px', marginBottom: '16px' }}>
            <div style={{ flex: 1, backgroundColor: '#ECFDF3', border: '1px solid #BBF7D0', borderRadius: '12px', padding: '12px' }}>
              <div style={{ fontSize: '12px', color: '#15803D', fontWeight: 700 }}>이 날짜 할 일</div>
              <div style={{ fontSize: '22px', fontWeight: 900, color: '#15803D' }}>{filteredTodos.length}<span style={{ fontSize: '13px', fontWeight: 600 }}> 개</span></div>
            </div>
            <div style={{ flex: 1, backgroundColor: '#F0FDF4', border: '1px solid #BBF7D0', borderRadius: '12px', padding: '12px' }}>
              <div style={{ fontSize: '12px', color: '#16A34A', fontWeight: 700 }}>완료</div>
              <div style={{ fontSize: '22px', fontWeight: 900, color: '#16A34A' }}>{completedCount}<span style={{ fontSize: '13px', fontWeight: 600 }}> / {filteredTodos.length}</span></div>
            </div>
          </div>

          <div style={{ backgroundColor: '#fff', border: '1px solid var(--color-border)', borderRadius: '10px', padding: '10px 12px', marginBottom: '12px' }}>
            <div style={{ fontSize: '12px', color: 'var(--color-text-muted)' }}>선택한 날짜</div>
            <div style={{ fontSize: '15px', fontWeight: 800, color: '#111827' }}>{selectedDate || '캘린더에서 날짜를 선택하세요.'}</div>
          </div>

          {selectedDate && (
            <div style={{ marginBottom: '12px' }}>
              <label style={{ fontSize: '13px', color: 'var(--color-text-muted)', display: 'block', marginBottom: '4px' }}>종료 날짜(선택)</label>
              <input type="date" value={selectedEndDate} onChange={(e) => setSelectedEndDate(e.target.value)} min={selectedDate} className="input-field" style={{ marginBottom: 0 }} />
            </div>
          )}

          <div style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
            <input className="input-field" value={todoText} onChange={(e) => setTodoText(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') handleAddTodo(); }}
              placeholder="할 일을 입력하세요" disabled={!selectedDate || !userId} />
            <button className="btn-primary" onClick={handleAddTodo} style={{ width: '80px', flexShrink: 0 }} disabled={!selectedDate || !userId}>추가</button>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '420px', overflowY: 'auto' }}>
            {userId && selectedDate && filteredTodos.length > 0 ? (
              filteredTodos.map((todo) => (
                <div key={todo.id} className={`todo-item ${todo.completed ? 'completed' : ''}`}>
                  <input type="checkbox" checked={todo.completed} onChange={() => handleToggleTodo(todo.id)} />
                  <span className="todo-text">
                    {isPlannerTodo(todo) && (
                      <span style={{ display: 'inline-block', marginRight: '6px', padding: '1px 7px', borderRadius: '999px', backgroundColor: '#DCFCE7', color: '#15803D', fontSize: '11px', fontWeight: 700, verticalAlign: 'middle' }}>플래너</span>
                    )}
                    {displayTodoText(todo.text)}
                  </span>
                  <button className="btn-outline" onClick={() => handleDeleteTodo(todo.id)} style={{ width: '50px', height: '30px', fontSize: '12px' }}>삭제</button>
                </div>
              ))
            ) : (
              <p style={{ color: 'var(--color-text-muted)', fontSize: '14px' }}>등록된 Todo가 없습니다.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
