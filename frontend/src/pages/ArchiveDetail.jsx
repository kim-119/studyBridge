import React, { useState } from 'react';
import { useLocation, useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, AlignLeft, HelpCircle, Map, MessageSquare, Edit3, Image, Download, Send, CheckCircle2, Circle, Settings, ChevronRight, X } from 'lucide-react';

export default function ArchiveDetail() {
  const { type, id } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const item = location.state?.item;

  const [activePdfTool, setActivePdfTool] = useState('summary');
  const [chatInput, setChatInput] = useState('');

  // 퀴즈 상태
  const [isQuizSettingsOpen, setIsQuizSettingsOpen] = useState(false);
  const [quizSettings, setQuizSettings] = useState({ difficulty: '보통', count: 5, range: '전체' });
  const [selectedQuizId, setSelectedQuizId] = useState(null);
  const [quizzes, setQuizzes] = useState([
    {
      id: 1,
      date: '2026년 5월 21일 오후 08:28',
      count: 5,
      type: '객관식',
      difficulty: '보통',
      questions: [
        {
          q: 'Q1. 원격교육에서 LMS의 핵심 기능이 아닌 것은?',
          options: [
            '1) 강의 콘텐츠 업로드 및 관리',
            '2) 오프라인 강의실 자동 배정 (오답)',
            '3) 학습자 성적 및 이력 관리',
            '4) 과제 제출 및 피드백 시스템'
          ],
          answer: 1,
          selected: null
        },
        {
          q: 'Q2. 원격수업 만족도에 가장 큰 영향을 미치는 요인은?',
          options: [
            '1) 수강료',
            '2) 강의 시간대',
            '3) 콘텐츠 품질과 상호작용 (정답)',
            '4) 인터넷 속도'
          ],
          answer: 2,
          selected: null
        }
      ]
    }
  ]);

  if (!item) {
    return (
      <div className="container-main" style={{ textAlign: 'center', marginTop: '100px' }}>
        <h2>자료를 찾을 수 없습니다.</h2>
        <button className="btn-primary" style={{ width: 'auto', padding: '0 24px', margin: '20px auto' }} onClick={() => navigate('/archive')}>목록으로 돌아가기</button>
      </div>
    );
  }

  // ---------------- 더미 데이터 ----------------
  const [roadmapData, setRoadmapData] = useState([
    { week: 1, topic: '원격교육의 이해와 기본 개념', goal: '원격교육의 정의와 특징 이해', act: '강의 수강 및 개념 요약', done: true },
    { week: 2, topic: '원격수업 유형과 운영 방식', goal: '동기/비동기 수업의 차이점 이해', act: '사례 분석', done: true },
    { week: 3, topic: '학습관리시스템 LMS의 역할', goal: 'LMS의 주요 기능 파악', act: '주요 LMS 플랫폼 비교', done: false },
    { week: 4, topic: '온라인 학습 참여 전략', goal: '자기주도적 참여 방법 학습', act: '토론 게시판 활동', done: false },
    { week: 5, topic: '원격수업 만족도 요인 분석', goal: '만족도에 영향을 미치는 핵심 요인 파악', act: '관련 논문 리뷰', done: false },
    { week: 6, topic: '자기주도 학습 방법', goal: '스스로 학습 계획 수립 및 실천', act: '학습 플래너 작성', done: false },
    { week: 7, topic: '중간 점검 및 핵심 개념 복습', goal: '1~6주차 내용 총정리', act: '요약 노트 작성', done: false },
    { week: 8, topic: '학습 데이터 기반 피드백', goal: '학습 분석학의 기초 이해', act: '데이터 활용 사례 조사', done: false },
    { week: 9, topic: '협업 도구와 온라인 토론', goal: '온라인 협업 역량 강화', act: '조별 과제 수행', done: false },
    { week: 10, topic: '학습 성과 평가 방식', goal: '온라인 평가의 특징과 방법 이해', act: '평가 루브릭 제작', done: false },
    { week: 11, topic: '학습 계획 보완', goal: '개인별 취약점 파악 및 보완', act: '피드백 반영', done: false },
    { week: 12, topic: '최종 정리 및 시험 대비', goal: '전체 내용 종합적 이해', act: '모의 퀴즈 풀이', done: false },
  ]);

  const toggleRoadmapDone = (index) => {
    const newData = [...roadmapData];
    newData[index].done = !newData[index].done;
    setRoadmapData(newData);
  };

  const getNodeColor = (week) => {
    if (week === 7) return '#F59E0B';
    if ([3, 4, 8, 9].includes(week)) return '#06B6D4';
    return '#10B981';
  };

  // ---------------- 렌더링 영역 ----------------
  const renderPdfRightPanel = () => {
    switch (activePdfTool) {
      case 'summary':
        return (
          <div className="animate-fade-in" style={{ paddingBottom: '32px' }}>
            <h3 style={{ margin: '0 0 24px', fontSize: '20px' }}>AI 핵심 요약 노트</h3>
            <p style={{ color: 'var(--color-text-muted)', fontSize: '15px', marginBottom: '24px' }}>
              문서 전체 맥락을 분석하여 도출된 종합 핵심 요약입니다.
            </p>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
              <div className="glass-panel" style={{ padding: '20px', borderLeft: '4px solid var(--color-primary)' }}>
                <h4 style={{ margin: '0 0 12px', fontSize: '16px', color: 'var(--color-text-main)' }}>📌 문서 개요</h4>
                <p style={{ margin: 0, fontSize: '15px', lineHeight: '1.6', color: 'var(--color-text-muted)' }}>
                  본 문서는 현대 원격교육 시스템의 구조적 특징과 학습관리시스템(LMS)의 발전 방향을 다루고 있습니다.
                  비대면 학습 환경에서 학습자 만족도에 영향을 미치는 주요 요인을 분석하고, 성공적인 온라인 학습을 위한 자기주도적 참여 전략을 제시합니다.
                </p>
              </div>

              <div>
                <h4 style={{ margin: '0 0 12px', fontSize: '16px', color: 'var(--color-text-main)' }}>🔑 핵심 키워드</h4>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                  {['원격교육', 'LMS 인프라', '상호작용', '자기주도 학습', '만족도 지표'].map(kw => (
                    <span key={kw} className="tag" style={{ backgroundColor: '#F3F4F6', color: 'var(--color-text-main)' }}>#{kw}</span>
                  ))}
                </div>
              </div>

              <div>
                <h4 style={{ margin: '0 0 16px', fontSize: '16px', color: 'var(--color-text-main)' }}>📑 세부 핵심 내용</h4>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                  <div style={{ backgroundColor: '#F9FAFB', padding: '16px', borderRadius: '8px', border: '1px solid var(--color-border)' }}>
                    <h5 style={{ margin: '0 0 8px', fontSize: '15px' }}>1. 원격교육 플랫폼의 기술적 진화</h5>
                    <p style={{ margin: 0, fontSize: '14px', lineHeight: '1.5', color: 'var(--color-text-muted)' }}>
                      초기 단방향 콘텐츠 제공 위주에서 벗어나, 현재의 LMS는 학습 이력 추적(Tracking), 실시간 평가, 그리고 피어(Peer) 간의 동기/비동기 상호작용을 통합적으로 지원하는 복합 인프라로 발전했습니다.
                    </p>
                  </div>
                  <div style={{ backgroundColor: '#F9FAFB', padding: '16px', borderRadius: '8px', border: '1px solid var(--color-border)' }}>
                    <h5 style={{ margin: '0 0 8px', fontSize: '15px' }}>2. 학습 성과를 결정짓는 핵심 변수</h5>
                    <p style={{ margin: 0, fontSize: '14px', lineHeight: '1.5', color: 'var(--color-text-muted)' }}>
                      기술적 안정성(네트워크, 서버 등)은 기본 전제이며, 최종적인 학습 만족도와 성취도는 '콘텐츠의 질적 수준'과 '교수자-학습자 간 피드백 빈도'에 의해 가장 크게 좌우되는 것으로 나타났습니다.
                    </p>
                  </div>
                  <div style={{ backgroundColor: '#F9FAFB', padding: '16px', borderRadius: '8px', border: '1px solid var(--color-border)' }}>
                    <h5 style={{ margin: '0 0 8px', fontSize: '15px' }}>3. 미래 방향성: AI 결합</h5>
                    <p style={{ margin: 0, fontSize: '14px', lineHeight: '1.5', color: 'var(--color-text-muted)' }}>
                      향후 시스템은 개별 학습자의 성취도 데이터와 학습 패턴을 분석하여 맞춤형 콘텐츠와 퀴즈를 실시간으로 생성해주는 AI 기반 적응형 학습(Adaptive Learning) 모델로 전환될 전망입니다.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        );
      case 'quiz':
        return (
          <div className="animate-fade-in" style={{ paddingBottom: '24px', display: 'flex', flexDirection: 'column', height: '100%' }}>
            {/* 상단 액션 영역 */}
            <div className="glass-panel" style={{ padding: '24px', marginBottom: '24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <h3 style={{ margin: '0 0 8px', fontSize: '20px', color: 'var(--color-text-main)' }}>퀴즈 생성</h3>
                <p style={{ margin: 0, color: 'var(--color-text-muted)', fontSize: '14px' }}>원하는 문제 유형, 난이도 등으로 퀴즈 세트를 만들어보세요.</p>
              </div>
              <div style={{ display: 'flex', gap: '12px', alignItems: 'center' }}>
                <button
                  className="btn-outline"
                  style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 20px', borderRadius: '30px', whiteSpace: 'nowrap', flexShrink: 0, width: 'auto' }}
                  onClick={() => setIsQuizSettingsOpen(true)}
                >
                  설정
                </button>
                <button className="btn-primary" style={{ padding: '10px 24px', borderRadius: '30px', fontWeight: 'bold', whiteSpace: 'nowrap', flexShrink: 0, width: 'auto' }}>
                  생성
                </button>
              </div>
            </div>

            {/* 퀴즈 내용 영역 */}
            {selectedQuizId === null ? (
              <div className="animate-fade-in" style={{ flex: 1 }}>
                <h4 style={{ margin: '0 0 16px', fontSize: '16px', color: 'var(--color-text-main)' }}>내 퀴즈</h4>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                  {quizzes.map(quiz => (
                    <div
                      key={quiz.id}
                      className="glass-panel hover-scale"
                      style={{ padding: '20px', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center', transition: 'all 0.2s', border: '1px solid transparent' }}
                      onMouseEnter={(e) => e.currentTarget.style.border = '1px solid var(--color-primary)'}
                      onMouseLeave={(e) => e.currentTarget.style.border = '1px solid transparent'}
                      onClick={() => setSelectedQuizId(quiz.id)}
                    >
                      <div>
                        <h5 style={{ margin: '0 0 8px', fontSize: '16px', color: 'var(--color-text-main)' }}>{quiz.date}</h5>
                        <p style={{ margin: 0, fontSize: '14px', color: 'var(--color-text-muted)' }}>문항: {quiz.count} • 유형: {quiz.type} • 난이도: {quiz.difficulty}</p>
                      </div>
                      <ChevronRight size={20} color="var(--color-text-muted)" />
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="animate-fade-in" style={{ flex: 1 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '24px' }}>
                  <button
                    className="btn-outline"
                    style={{ width: '40px', height: '40px', padding: 0, display: 'flex', justifyContent: 'center', alignItems: 'center', borderRadius: '50%' }}
                    onClick={() => setSelectedQuizId(null)}
                  >
                    <ArrowLeft size={20} />
                  </button>
                  <h4 style={{ margin: 0, fontSize: '18px', color: 'var(--color-text-main)' }}>퀴즈 풀이</h4>
                </div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>
                  {quizzes.find(q => q.id === selectedQuizId)?.questions.map((q, idx) => (
                    <div key={idx} className="glass-panel" style={{ padding: '24px', borderLeft: '4px solid var(--color-primary)' }}>
                      <h5 style={{ margin: '0 0 20px', fontSize: '16px', color: 'var(--color-text-main)', lineHeight: '1.5' }}>{q.q}</h5>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                        {q.options.map((opt, optIdx) => (
                          <button
                            key={optIdx}
                            className={`btn-outline ${q.selected === optIdx ? 'selected' : ''}`}
                            style={{
                              width: '100%', height: 'auto', display: 'flex', alignItems: 'center',
                              textAlign: 'left', fontWeight: 'normal', justifyContent: 'flex-start',
                              fontSize: '15px', padding: '16px', borderRadius: '12px',
                              backgroundColor: optIdx === q.answer ? '#DCFCE7' : 'white',
                              borderColor: optIdx === q.answer ? '#86EFAC' : 'var(--color-border)',
                              color: optIdx === q.answer ? '#166534' : 'var(--color-text-main)',
                              transition: 'all 0.2s'
                            }}
                          >
                            {opt}
                          </button>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* 설정 모달 */}
            {isQuizSettingsOpen && (
              <div className="modal-overlay" style={{ zIndex: 1000 }}>
                <div className="glass-panel modal-content animate-fade-in" style={{ width: '420px', padding: '32px', borderRadius: '24px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '32px' }}>
                    <h3 style={{ margin: 0, fontSize: '20px', color: 'var(--color-text-main)' }}>퀴즈 설정</h3>
                    <button className="btn-close" onClick={() => setIsQuizSettingsOpen(false)}><X size={24} /></button>
                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: '28px' }}>
                    <div>
                      <label style={{ display: 'block', marginBottom: '12px', fontWeight: '600', fontSize: '15px', color: 'var(--color-text-main)' }}>난이도</label>
                      <div style={{ display: 'flex', gap: '8px' }}>
                        {['쉬움', '보통', '어려움'].map(level => (
                          <button
                            key={level}
                            className="btn-outline"
                            style={{
                              flex: 1, padding: '12px', borderRadius: '12px', transition: 'all 0.2s',
                              backgroundColor: quizSettings.difficulty === level ? 'var(--color-primary)' : 'white',
                              color: quizSettings.difficulty === level ? 'white' : 'var(--color-text-main)',
                              borderColor: quizSettings.difficulty === level ? 'var(--color-primary)' : 'var(--color-border)',
                              fontWeight: quizSettings.difficulty === level ? 'bold' : 'normal',
                            }}
                            onClick={() => setQuizSettings({ ...quizSettings, difficulty: level })}
                          >
                            {level}
                          </button>
                        ))}
                      </div>
                    </div>

                    <div>
                      <label style={{ display: 'block', marginBottom: '12px', fontWeight: '600', fontSize: '15px', color: 'var(--color-text-main)' }}>문항 수</label>
                      <input
                        type="number"
                        className="input-field"
                        value={quizSettings.count}
                        onChange={(e) => setQuizSettings({ ...quizSettings, count: parseInt(e.target.value) || 5 })}
                        style={{ width: '100%', padding: '16px', borderRadius: '12px', backgroundColor: '#F9FAFB', border: '1px solid var(--color-border)' }}
                      />
                    </div>

                    <div>
                      <label style={{ display: 'block', marginBottom: '12px', fontWeight: '600', fontSize: '15px', color: 'var(--color-text-main)' }}>페이지 범위</label>
                      <input
                        type="text"
                        className="input-field"
                        placeholder="예: 1-10 또는 전체"
                        value={quizSettings.range}
                        onChange={(e) => setQuizSettings({ ...quizSettings, range: e.target.value })}
                        style={{ width: '100%', padding: '16px', borderRadius: '12px', backgroundColor: '#F9FAFB', border: '1px solid var(--color-border)' }}
                      />
                    </div>
                  </div>

                  <div style={{ display: 'flex', gap: '12px', marginTop: '40px' }}>
                    <button className="btn-outline" style={{ flex: 1, padding: '16px', borderRadius: '12px', fontWeight: 'bold' }} onClick={() => setIsQuizSettingsOpen(false)}>취소</button>
                    <button className="btn-primary" style={{ flex: 1, padding: '16px', borderRadius: '12px', fontWeight: 'bold' }} onClick={() => setIsQuizSettingsOpen(false)}>확인</button>
                  </div>
                </div>
              </div>
            )}
          </div>
        );
      case 'memo':
        return (
          <div className="empty-state animate-fade-in" style={{ height: '100%' }}>
            <Image size={48} style={{ opacity: 0.3, marginBottom: '16px' }} />
            <h3>준비 중입니다</h3>
            <p style={{ color: 'var(--color-text-muted)' }}>이 기능은 현재 개발 중입니다.</p>
          </div>
        );
      case 'roadmap': {
        const doneCount = roadmapData.filter(item => item.done).length;
        const progressPercent = Math.round((doneCount / roadmapData.length) * 100);

        return (
          <div className="animate-fade-in">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
              <h2 style={{ margin: 0, color: 'var(--color-text-main)' }}>주차별 학습 로드맵</h2>
              <button className="btn-outline" style={{ display: 'inline-flex', width: 'max-content', flex: 'none', alignItems: 'center', gap: '6px', height: '32px', fontSize: '13px', padding: '0 12px' }}>
                <Download size={14} /> 12주차
              </button>
            </div>
            <p style={{ color: 'var(--color-text-muted)', marginBottom: '24px' }}>
              업로드한 강의계획서를 기반으로 주차별 학습 계획을 생성했습니다.
            </p>

            <div className="glass-panel" style={{ padding: '20px', marginBottom: '32px', borderLeft: '4px solid var(--color-primary)' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <span style={{ fontWeight: 'bold', fontSize: '15px', color: 'var(--color-text-main)' }}>전체 학습 진행률</span>
                <span style={{ fontWeight: 'bold', fontSize: '18px', color: 'var(--color-primary)' }}>{progressPercent}% <span style={{ fontSize: '13px', color: 'var(--color-text-muted)', fontWeight: 'normal' }}>({doneCount}/{roadmapData.length})</span></span>
              </div>
              <div style={{ width: '100%', height: '10px', backgroundColor: '#E5E7EB', borderRadius: '5px', overflow: 'hidden' }}>
                <div style={{ width: `${progressPercent}%`, height: '100%', backgroundColor: 'var(--color-primary)', transition: 'width 0.6s cubic-bezier(0.4, 0, 0.2, 1)' }}></div>
              </div>
            </div>

            <div className="roadmap-timeline">
              {roadmapData.map((item, idx) => (
                <div key={item.week} className="timeline-item" style={{ opacity: item.done ? 0.6 : 1, transition: 'opacity 0.3s' }}>
                  <div className="timeline-left">
                    <div className="timeline-circle" style={{ backgroundColor: item.done ? '#9CA3AF' : getNodeColor(item.week) }}>{item.week}</div>
                    {idx < roadmapData.length - 1 && <div className="timeline-line"></div>}
                  </div>
                  <div className="timeline-card glass-panel" style={{ borderLeftColor: item.done ? '#9CA3AF' : getNodeColor(item.week), padding: '16px', backgroundColor: item.done ? '#F3F4F6' : 'white', transition: 'all 0.3s' }}>
                    <h4 style={{ margin: '0 0 12px', fontSize: '15px', textDecoration: item.done ? 'line-through' : 'none', color: item.done ? 'var(--color-text-muted)' : 'var(--color-text-main)' }}>{item.topic}</h4>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '13px' }}>
                      <div><span style={{ fontWeight: 'bold', color: 'var(--color-text-muted)', marginRight: '8px' }}>학습 목표</span> <span style={{ textDecoration: item.done ? 'line-through' : 'none' }}>{item.goal}</span></div>
                      <div><span style={{ fontWeight: 'bold', color: 'var(--color-text-muted)', marginRight: '8px' }}>학습 활동</span> <span style={{ textDecoration: item.done ? 'line-through' : 'none' }}>{item.act}</span></div>
                    </div>
                    <div style={{ marginTop: '16px' }}>
                      <button
                        onClick={() => toggleRoadmapDone(idx)}
                        style={{
                          display: 'flex', alignItems: 'center', gap: '8px',
                          padding: '8px 16px', borderRadius: '20px', border: item.done ? 'none' : '1px solid var(--color-border)',
                          backgroundColor: item.done ? 'var(--color-primary)' : 'white',
                          color: item.done ? 'white' : 'var(--color-text-main)',
                          fontWeight: '600', cursor: 'pointer', transition: 'all 0.2s',
                          fontSize: '13px', boxShadow: item.done ? '0 2px 8px rgba(16, 185, 129, 0.3)' : '0 1px 2px rgba(0,0,0,0.05)'
                        }}
                      >
                        {item.done ? <CheckCircle2 size={16} /> : <Circle size={16} color="var(--color-text-muted)" />}
                        {item.done ? '학습 완료' : '완료 표시하기'}
                      </button>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        );
      }
      case 'chat':
        return (
          <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
            <h3 style={{ margin: '0 0 16px', fontSize: '20px' }}>AI 질문</h3>
            <div style={{ flex: 1, backgroundColor: '#F9FAFB', borderRadius: '12px', padding: '24px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '20px', border: '1px solid var(--color-border)' }}>
              <div style={{ alignSelf: 'flex-start', backgroundColor: 'white', padding: '16px 20px', borderRadius: '20px', borderTopLeftRadius: '4px', maxWidth: '85%', boxShadow: '0 1px 4px rgba(0,0,0,0.05)', fontSize: '15px', lineHeight: '1.6' }}>
                안녕하세요. 업로드한 자료에 대해 궁금한 점을 질문해주세요.
              </div>
              <div style={{ alignSelf: 'flex-end', backgroundColor: 'var(--color-primary)', color: 'white', padding: '16px 20px', borderRadius: '20px', borderTopRightRadius: '4px', maxWidth: '85%', boxShadow: '0 1px 4px rgba(0,0,0,0.05)', fontSize: '15px', lineHeight: '1.6' }}>
                원격교육에서 LMS가 왜 중요한지 설명해줘.
              </div>
              <div style={{ alignSelf: 'flex-start', backgroundColor: 'white', padding: '16px 20px', borderRadius: '20px', borderTopLeftRadius: '4px', maxWidth: '85%', boxShadow: '0 1px 4px rgba(0,0,0,0.05)', fontSize: '15px', lineHeight: '1.6' }}>
                LMS는 원격교육의 핵심 인프라입니다. 강의 콘텐츠 배포, 진도 추적, 성적 관리를 한 곳에서 처리해 교수자와 학습자 모두의 부담을 줄여줍니다.
              </div>
            </div>
            <div style={{ marginTop: '16px' }}>
              <form onSubmit={(e) => e.preventDefault()} style={{ display: 'flex', gap: '12px' }}>
                <input
                  type="text"
                  className="input-field"
                  style={{ margin: 0, borderRadius: '30px', backgroundColor: '#F3F4F6', border: 'none', padding: '16px 24px', fontSize: '15px', height: '50px' }}
                  placeholder="자료 내용에 대해 궁금한 점을 입력하세요."
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                />
                <button type="submit" className="btn-primary" style={{ width: '50px', height: '50px', borderRadius: '50%', padding: 0, flexShrink: 0, display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
                  <Send size={20} />
                </button>
              </form>
            </div>
          </div>
        );
      default:
        return null;
    }
  };

  return (
    <div className="archive-detail-container animate-fade-in">
      {(type === 'pdf' || type === 'syllabus') && (
        <div className="archive-action-bar" style={{ padding: '16px 0', borderBottom: '1px solid var(--color-border)', backgroundColor: 'white' }}>
          <div style={{ flex: 1, padding: '0 24px', display: 'flex', alignItems: 'center' }}>
            <button className="btn-outline" style={{ width: 'auto', padding: '8px 16px', border: 'none' }} onClick={() => navigate('/archive')}>
              <ArrowLeft size={18} /> 목록
            </button>
          </div>
          <div style={{ flex: 1, padding: '0 24px', display: 'flex', flexWrap: 'wrap', gap: '12px' }}>
            <button className={`archive-action-btn ${activePdfTool === 'summary' ? 'active' : ''}`} onClick={() => setActivePdfTool('summary')}>
              <AlignLeft size={16} /> 요약
            </button>
            <button className={`archive-action-btn ${activePdfTool === 'quiz' ? 'active' : ''}`} onClick={() => setActivePdfTool('quiz')}>
              <HelpCircle size={16} /> 퀴즈/문제 생성
            </button>
            <button className={`archive-action-btn ${activePdfTool === 'roadmap' ? 'active' : ''}`} onClick={() => setActivePdfTool('roadmap')}>
              <Map size={16} /> 주차별 로드맵 생성
            </button>
            <button className={`archive-action-btn ${activePdfTool === 'memo' ? 'active' : ''}`} onClick={() => setActivePdfTool('memo')}>
              <Edit3 size={16} /> 메모
            </button>
            <button className={`archive-action-btn ${activePdfTool === 'chat' ? 'active' : ''}`} onClick={() => setActivePdfTool('chat')}>
              <MessageSquare size={16} /> AI 질문
            </button>
          </div>
        </div>
      )}

      {type === 'journal' && (
        <div style={{ padding: '16px 24px', backgroundColor: 'white', borderBottom: '1px solid var(--color-border)', display: 'flex', alignItems: 'center', gap: '16px' }}>
          <button className="btn-outline" style={{ width: 'auto', padding: '8px 16px', border: 'none' }} onClick={() => navigate('/archive')}>
            <ArrowLeft size={18} /> 목록
          </button>
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <h2 style={{ margin: 0, fontSize: '18px' }}>{item.title}</h2>
            <span style={{ fontSize: '13px', color: 'var(--color-text-muted)' }}>{item.date} • {item.tag}</span>
          </div>
        </div>
      )}

      <div className="archive-split-view">
        <div className="archive-left-panel">
          {(type === 'pdf' || type === 'syllabus') ? (
            <div style={{ width: '100%', height: '100%', backgroundColor: 'white', borderRadius: '12px', border: '1px solid var(--color-border)', display: 'flex', justifyContent: 'center', alignItems: 'center', flexDirection: 'column' }}>
              <div style={{ padding: '40px', backgroundColor: '#F3F4F6', borderRadius: '8px', marginBottom: '24px' }}>
                <span style={{ fontSize: '48px', color: '#9CA3AF' }}>PDF</span>
              </div>
              <h3 style={{ margin: '0 0 8px', color: 'var(--color-text-main)' }}>{item.title}</h3>
              <p style={{ color: 'var(--color-text-muted)', margin: 0 }}>문서 미리보기 영역</p>
            </div>
          ) : (
            <div className="glass-panel" style={{ padding: '32px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '24px' }}>
                <div>
                  <h2 style={{ margin: '0 0 8px', color: 'var(--color-text-main)' }}>학습일지 상세 및 수정</h2>
                  <p style={{ margin: 0, color: 'var(--color-text-muted)', fontSize: '14px' }}>학습일지 내용을 확인하고 수정할 수 있습니다.</p>
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', marginBottom: '20px' }}>
                <div>
                  <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>제목</label>
                  <input type="text" className="input-field" defaultValue={item.title} style={{ width: '100%', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
                </div>
                <div>
                  <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>날짜</label>
                  <input type="text" className="input-field" defaultValue={item.date} style={{ width: '100%', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
                </div>
              </div>

              <div style={{ marginBottom: '20px' }}>
                <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>통계 (학습 시간 / 푼 문제 수 / 자기평가)</label>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px' }}>
                  <input type="text" className="input-field" defaultValue={item.stats.time} placeholder="학습 시간 (예: 2h 30m)" style={{ padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
                  <input type="number" className="input-field" defaultValue={item.stats.solved} placeholder="푼 문제 수" style={{ padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
                  <input type="text" className="input-field" defaultValue={item.stats.score} placeholder="자기평가 (예: 85%)" style={{ padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
                </div>
              </div>

              <div style={{ marginBottom: '20px' }}>
                <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>핵심 키워드 (쉼표로 구분)</label>
                <input type="text" className="input-field" defaultValue={item.keywords.join(', ')} style={{ width: '100%', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
              </div>

              <div style={{ marginBottom: '20px' }}>
                <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>학습 내용</label>
                <textarea className="input-field" defaultValue={item.content} style={{ width: '100%', minHeight: '120px', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', resize: 'vertical', backgroundColor: '#F9FAFB', fontFamily: 'inherit', lineHeight: '1.5' }} />
              </div>

              <div style={{ marginBottom: '24px' }}>
                <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>다음 학습 계획</label>
                <textarea className="input-field" defaultValue={item.nextPlan} style={{ width: '100%', minHeight: '80px', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', resize: 'vertical', backgroundColor: '#F9FAFB', fontFamily: 'inherit', lineHeight: '1.5' }} />
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
                <button className="btn-primary" style={{ padding: '10px 24px', width: 'auto' }} onClick={() => { alert('성공적으로 수정되었습니다.'); }}>저장하기</button>
              </div>
            </div>
          )}
        </div>
        <div className="archive-right-panel" style={{ backgroundColor: type === 'journal' ? 'var(--color-bg-base)' : 'white', borderLeft: (type === 'pdf' || type === 'syllabus') ? 'none' : '1px solid var(--color-border)' }}>
          {(type === 'pdf' || type === 'syllabus') ? (
            renderPdfRightPanel()
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
              <div className="glass-panel animate-fade-in" style={{ padding: '24px' }}>
                <h3 style={{ margin: '0 0 16px', fontSize: '18px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <AlignLeft size={18} color="var(--color-primary)" /> AI 요약
                </h3>
                <p style={{ margin: 0, fontSize: '15px', lineHeight: '1.6', color: 'var(--color-text-main)' }}>
                  {item.description}
                </p>
              </div>

              <div className="glass-panel animate-fade-in" style={{ padding: '24px' }}>
                <h3 style={{ margin: '0 0 16px', fontSize: '18px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <MessageSquare size={18} color="var(--color-primary)" /> AI 피드백
                </h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                  <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
                    <div style={{ width: '24px', height: '24px', borderRadius: '50%', backgroundColor: 'var(--color-primary)', color: 'white', display: 'flex', justifyContent: 'center', alignItems: 'center', fontSize: '12px', fontWeight: 'bold', flexShrink: 0 }}>1</div>
                    <p style={{ margin: 0, fontSize: '14px', lineHeight: '1.5', color: 'var(--color-text-main)' }}>
                      학습 목표에 맞게 핵심 개념을 잘 파악했습니다. {item.keywords[0]}, {item.keywords[1]}에 대한 이해가 잘 정리되어 있습니다.
                    </p>
                  </div>
                  <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
                    <div style={{ width: '24px', height: '24px', borderRadius: '50%', backgroundColor: 'var(--color-primary)', color: 'white', display: 'flex', justifyContent: 'center', alignItems: 'center', fontSize: '12px', fontWeight: 'bold', flexShrink: 0 }}>2</div>
                    <p style={{ margin: 0, fontSize: '14px', lineHeight: '1.5', color: 'var(--color-text-main)' }}>
                      더 심화 학습하려면 연관된 추가 개념도 함께 정리하면 좋습니다. 다음 학습 계획이 구체적으로 잘 수립되었습니다.
                    </p>
                  </div>
                  <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
                    <div style={{ width: '24px', height: '24px', borderRadius: '50%', backgroundColor: 'var(--color-primary)', color: 'white', display: 'flex', justifyContent: 'center', alignItems: 'center', fontSize: '12px', fontWeight: 'bold', flexShrink: 0 }}>3</div>
                    <p style={{ margin: 0, fontSize: '14px', lineHeight: '1.5', color: 'var(--color-text-main)' }}>
                      {item.stats.solved > 0 ? `현재 ${item.stats.solved}문제를 풀이하셨습니다. 충분한 실습량입니다.` : '실습 및 문제 풀이 경험을 추가하면 학습 효과를 더 높일 수 있습니다.'} 다음 단계 학습을 권장합니다.
                    </p>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
