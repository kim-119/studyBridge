import React, { useMemo, useState } from 'react';
import { Printer } from 'lucide-react';

const defaultRows = [
  { day: '월', focus: '', tasks: '', review: '' },
  { day: '화', focus: '', tasks: '', review: '' },
  { day: '수', focus: '', tasks: '', review: '' },
  { day: '목', focus: '', tasks: '', review: '' },
  { day: '금', focus: '', tasks: '', review: '' },
  { day: '토', focus: '', tasks: '', review: '' },
  { day: '일', focus: '', tasks: '', review: '' },
];

export default function PlannerWorkspace() {
  const [title, setTitle] = useState('이번 주 학습 플래너');
  const [goal, setGoal] = useState('');
  const [rows, setRows] = useState(defaultRows);

  const filledCount = useMemo(
    () => rows.filter((row) => row.focus.trim() || row.tasks.trim() || row.review.trim()).length,
    [rows],
  );

  const updateRow = (index, key, value) => {
    setRows((prev) => prev.map((row, rowIndex) => (
      rowIndex === index ? { ...row, [key]: value } : row
    )));
  };

  return (
    <div className="planner-workspace">
      <div className="glass-panel planner-toolbar">
        <div>
          <h3>플래너</h3>
          <p>{filledCount}/7일 계획 작성됨</p>
        </div>
        <button className="btn-primary" style={{ width: 'auto', padding: '0 16px' }} onClick={() => window.print()}>
          <Printer size={16} />
          인쇄/PDF
        </button>
      </div>

      <div className="glass-panel planner-sheet">
        <div className="planner-sheet-header">
          <input className="planner-title-input" value={title} onChange={(e) => setTitle(e.target.value)} aria-label="플래너 제목" />
          <textarea className="planner-goal-input" value={goal} onChange={(e) => setGoal(e.target.value)} placeholder="이번 주 목표" />
        </div>

        <div className="planner-table">
          <div className="planner-row planner-head">
            <span>요일</span>
            <span>핵심 주제</span>
            <span>할 일</span>
            <span>회고</span>
          </div>
          {rows.map((row, index) => (
            <div className="planner-row" key={row.day}>
              <strong>{row.day}</strong>
              <input value={row.focus} onChange={(e) => updateRow(index, 'focus', e.target.value)} placeholder="학습 주제" />
              <textarea value={row.tasks} onChange={(e) => updateRow(index, 'tasks', e.target.value)} placeholder="Todo" />
              <textarea value={row.review} onChange={(e) => updateRow(index, 'review', e.target.value)} placeholder="완료 후 메모" />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
