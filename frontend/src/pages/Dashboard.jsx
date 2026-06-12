import React, { useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';
import { AlertTriangle } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import StudyReport from '../components/StudyReport';
import WeeklySchedule from '../components/WeeklySchedule';
import PlannerWorkspace from '../components/PlannerWorkspace';
import { todoService } from '../services/api';

const tabs = [
  { id: 'report', label: '학습리포트' },
  { id: 'schedule', label: '주간일정' },
  { id: 'planner', label: '플래너' },
];

export default function Dashboard() {
  const { user } = useAuth();
  const userEmail = localStorage.getItem('userEmail') || 'guest';
  const userId = localStorage.getItem('userId');
  const userName = userEmail.includes('@') ? userEmail.split('@')[0] : userEmail;
  const [activeTab, setActiveTab] = useState('report');
  const [todayStudySeconds, setTodayStudySeconds] = useState(0);
  const [todoCount, setTodoCount] = useState(0);
  const [showWarning, setShowWarning] = useState(false);

  useEffect(() => {
    if (user?.status === 'WARNING' && !sessionStorage.getItem('warningShown')) {
      setShowWarning(true);
      sessionStorage.setItem('warningShown', 'true');
    }
  }, [user]);

  useEffect(() => {
    if (!userId) {
      setTodoCount(0);
      return;
    }

    const loadTodoCount = async () => {
      try {
        const data = await todoService.getTodos(userId);
        setTodoCount(Array.isArray(data) ? data.length : 0);
      } catch (err) {
        console.error('Todo 개수 조회 실패:', err);
        setTodoCount(0);
      }
    };

    loadTodoCount();
  }, [userId]);

  if (user?.role === 'ADMIN' || user?.displayName === '시스템 관리자' || userName === 'admin') {
    return <Navigate to="/admin" replace />;
  }

  return (
    <div className="container-main dashboard-page">
      <div className="dashboard-tabs">
        {tabs.map((tab) => (
          <button key={tab.id} type="button" className={`dashboard-tab ${activeTab === tab.id ? 'active' : ''}`} onClick={() => setActiveTab(tab.id)}>
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === 'report' && (
        <StudyReport todayStudySeconds={todayStudySeconds} todoCount={todoCount} onTimeUpdate={setTodayStudySeconds} />
      )}
      {activeTab === 'schedule' && <WeeklySchedule userId={userId} onTodoCountChange={setTodoCount} />}
      {activeTab === 'planner' && <PlannerWorkspace />}

      {showWarning && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.5)', zIndex: 10000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
          <div className="animate-fade-in" style={{ backgroundColor: 'white', borderRadius: '16px', width: '90%', maxWidth: '400px', overflow: 'hidden', boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1)' }}>
            <div style={{ padding: '24px', textAlign: 'center' }}>
              <div style={{ width: '64px', height: '64px', borderRadius: '50%', backgroundColor: '#FEF3C7', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 16px', color: '#D97706' }}>
                <AlertTriangle size={32} />
              </div>
              <h3 style={{ margin: '0 0 12px 0', fontSize: '20px', fontWeight: 'bold', color: '#111827' }}>경고 안내</h3>
              <p style={{ margin: '0 0 16px 0', fontSize: '14px', color: '#4B5563', lineHeight: '1.5' }}>
                운영 정책 위반으로 인해 경고 조치되었습니다.<br />
                사유: <strong>{user?.suspensionReason || '운영 정책 위반'}</strong>
              </p>
              <button onClick={() => setShowWarning(false)} style={{ width: '100%', padding: '12px', backgroundColor: '#F59E0B', color: 'white', border: 'none', borderRadius: '8px', fontWeight: 'bold', cursor: 'pointer', fontSize: '15px' }}>
                확인
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
