import React, { useState, useEffect, useRef } from 'react';
import { useLocation, useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, AlignLeft, HelpCircle, Map, MessageSquare, Edit3, Image, Download, Send, CheckCircle2, Circle, Settings, ChevronRight, X, Trash2 } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import { materialService } from '../services/api';

export default function ArchiveDetail() {
  const { type, id } = useParams();
  const location = useLocation();
  const navigate = useNavigate();
  const { userId } = useAuth();

  // 기본 상태 정보
  const [material, setMaterial] = useState(location.state?.item || null);
  const [isLoadingDetail, setIsLoadingDetail] = useState(!location.state?.item);
  const [activePdfTool, setActivePdfTool] = useState('summary');

  // 각 탭별 실 API 데이터 상태
  const [summaryData, setSummaryData] = useState(null);
  const [quizzes, setQuizzes] = useState([]);
  const [selectedQuizId, setSelectedQuizId] = useState(null);
  const [roadmapSteps, setRoadmapSteps] = useState([]);
  const [memoText, setMemoText] = useState('');
  const [chatMessages, setChatMessages] = useState([
    { sender: 'ai', text: '이 AI는 자료보관함에 업로드된 PDF 기반 채팅만 가능합니다.\n현재 선택한 자료의 내용 안에서만 질문에 답변합니다.\n자료에 없는 내용은 임의로 생성하지 않습니다.\n일반적인 학습 질문이나 자료와 무관한 질문은 학습메이트 기능을 이용해주세요.' }
  ]);
  const [chatInput, setChatInput] = useState('');

  // UI 상호작용 상태
  const [isQuizSettingsOpen, setIsQuizSettingsOpen] = useState(false);
  const [quizSettings, setQuizSettings] = useState({ difficulty: '보통', count: 5, range: '전체' });
  const [isGeneratingQuiz, setIsGeneratingQuiz] = useState(false);
  const [isSavingMemo, setIsSavingMemo] = useState(false);
  const [userAnswers, setUserAnswers] = useState({});

  const chatEndRef = useRef(null);

  // ✅ 패널 너비 조절 관련 상태
  const [leftWidth, setLeftWidth] = useState(50); // 기본값 50%

  // ---------------- 인증 체크 ----------------
  useEffect(() => {
    if (!userId) {
      alert('로그인이 필요한 기능입니다. 로그인 페이지로 이동합니다.');
      navigate('/login');
    }
  }, [userId, navigate]);

  // ---------------- 데이터 로딩 ----------------
  const loadMaterialDetail = async () => {
    try {
      setIsLoadingDetail(true);
      const detail = await materialService.getMaterialDetail(id);
      setMaterial(detail);
      if (detail.extractionStatus === 'SUCCESS') {
        loadTabData(detail.materialId);
      }
    } catch (e) {
      console.error('자료 상세 정보 로드 실패:', e);
    } finally {
      setIsLoadingDetail(false);
    }
  };

  const loadTabData = async (materialId) => {
    // 1. 요약 정보 로드
    try {
      const summary = await materialService.getSummary(materialId);
      setSummaryData(summary);
    } catch (e) {
      console.warn('AI 요약 정보가 아직 없습니다:', e);
    }

    // 2. 퀴즈 정보 로드
    try {
      const quizList = await materialService.getQuizzes(materialId);
      setQuizzes(Array.isArray(quizList) ? quizList : []);
    } catch (e) {
      console.warn('AI 퀴즈 정보 로드 실패:', e);
    }

    // 3. 로드맵 정보 로드
    try {
      const roadmap = await materialService.getRoadmap(materialId);
      setRoadmapSteps(roadmap?.steps || []);
    } catch (e) {
      console.warn('AI 로드맵 정보 로드 실패:', e);
    }

    // 4. 메모 정보 로드
    try {
      const memo = await materialService.getMemo(materialId);
      setMemoText(memo?.content || '');
    } catch (e) {
      console.warn('메모 정보 로드 실패:', e);
    }
  };

  useEffect(() => {
    if (userId && id) {
      loadMaterialDetail();
    }
  }, [userId, id]);

  // ---------------- PENDING / PROCESSING 폴링 ----------------
  useEffect(() => {
    let pollInterval;
    if (material && (material.extractionStatus === 'PENDING' || material.extractionStatus === 'PROCESSING')) {
      pollInterval = setInterval(async () => {
        try {
          const freshDetail = await materialService.getMaterialDetail(id);
          if (freshDetail.extractionStatus !== 'PENDING' && freshDetail.extractionStatus !== 'PROCESSING') {
            setMaterial(freshDetail);
            loadTabData(freshDetail.materialId);
          }
        } catch (e) {
          console.error("폴링 오류:", e);
        }
      }, 5000);
    }
    return () => {
      if (pollInterval) clearInterval(pollInterval);
    };
  }, [material, id]);

  // 채팅 메시지 끝으로 자동 스크롤
  useEffect(() => {
    chatEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [chatMessages]);

  // ---------------- 핸들러 ----------------

  // 퀴즈 옵션 선택
  const handleSelectOption = (questionIdx, optionIdx) => {
    setUserAnswers(prev => ({
      ...prev,
      [questionIdx]: optionIdx
    }));
  };

  // 퀴즈 생성 신청
  const handleGenerateQuiz = async () => {
    try {
      setIsGeneratingQuiz(true);
      const req = {
        difficulty: quizSettings.difficulty,
        questionCount: quizSettings.count,
        pageRange: quizSettings.range
      };
      const newQuiz = await materialService.generateQuiz(id, req);
      setQuizzes(prev => [newQuiz, ...prev]);
      setSelectedQuizId(newQuiz.quizId);
      setUserAnswers({});
      setIsQuizSettingsOpen(false);
      alert('새로운 AI 맞춤형 퀴즈가 출제되었습니다!');
    } catch (e) {
      console.error('퀴즈 생성 실패:', e);
      alert('퀴즈 생성에 실패했습니다. AI 분석 완료 여부를 확인해보세요.');
    } finally {
      setIsGeneratingQuiz(false);
    }
  };

  // 로드맵 주차별 태스크 토글
  const handleToggleTask = async (taskId) => {
    try {
      // Optimistic update
      setRoadmapSteps(prevSteps => {
        return prevSteps.map(step => ({
          ...step,
          tasks: step.tasks.map(task => {
            if (task.taskId === taskId) {
              return { ...task, isCompleted: !task.isCompleted };
            }
            return task;
          })
        }));
      });
      // Call API
      await materialService.toggleRoadmapTask(id, taskId);
    } catch (e) {
      console.error('상태 변경 실패:', e);
      // Revert optimistic update
      setRoadmapSteps(prevSteps => {
        return prevSteps.map(step => ({
          ...step,
          tasks: step.tasks.map(task => {
            if (task.taskId === taskId) {
              return { ...task, isCompleted: !task.isCompleted };
            }
            return task;
          })
        }));
      });
      alert('상태 변경 도중 오류가 발생했습니다.');
    }
  };

  // 메모 저장
  const handleSaveMemo = async () => {
    try {
      setIsSavingMemo(true);
      await materialService.saveMemo(id, memoText);
      alert('메모가 저장되었습니다.');
    } catch (e) {
      console.error('메모 저장 실패:', e);
      alert('메모 저장 도중 오류가 발생했습니다.');
    } finally {
      setIsSavingMemo(false);
    }
  };

  // 자료 삭제
  const handleDeleteMaterial = async () => {
    if (window.confirm('정말로 이 자료를 삭제하시겠습니까? 삭제 후에는 복구할 수 없습니다.')) {
      try {
        await materialService.deleteMaterial(id);
        alert('자료가 삭제되었습니다.');
        navigate('/archive');
      } catch (e) {
        console.error('자료 삭제 실패:', e);
        alert('자료 삭제 중 오류가 발생했습니다.');
      }
    }
  };

  // AI 챗봇 메시지 전송
  const handleSendChat = async (e) => {
    if (e) e.preventDefault();
    if (!chatInput.trim()) return;

    const userMsg = chatInput.trim();
    setChatInput('');
    setChatMessages(prev => [...prev, { sender: 'user', text: userMsg }]);

    try {
      setChatMessages(prev => [...prev, { sender: 'ai', text: 'AI 분석기가 답변을 작성하는 중입니다...', isThinking: true }]);
      const res = await materialService.askQuestion(id, { userQuestion: userMsg });
      setChatMessages(prev => {
        const filtered = prev.filter(m => !m.isThinking);
        return [...filtered, { sender: 'ai', text: res.aiAnswer }];
      });
    } catch (e) {
      console.error('AI 질문 실패:', e);
      setChatMessages(prev => {
        const filtered = prev.filter(m => !m.isThinking);
        return [...filtered, { sender: 'ai', text: '죄송합니다. 답변을 받아오지 못했습니다. 잠시 후 다시 시도해 주세요.' }];
      });
    }
  };

  // ---------------- 로드맵 노드 색상 설정 ----------------
  const getNodeColor = (week) => {
    if (week === 7) return '#F59E0B';
    if ([3, 4, 8, 9].includes(week)) return '#06B6D4';
    return '#10B981';
  };

  // ---------------- 퀴즈 파서 ----------------
  const parseQuizQuestions = (rawQuizData) => {
    try {
      const parsed = JSON.parse(rawQuizData);
      return parsed.map((item, idx) => ({
        q: item.question || item.q || `Q${idx + 1}. 문제`,
        options: item.options || item.choices || item.answers || [],
        answer: typeof item.answer === 'number' ? item.answer : 0
      }));
    } catch (e) {
      console.error("Quiz JSON 파싱 실패:", e);
      return [];
    }
  };

  // ---------------- 렌더링 도우미 ----------------
  const renderPdfRightPanel = () => {
    switch (activePdfTool) {
      case 'summary': {
        const parsedCoreContents = [];
        if (summaryData?.coreContents) {
          try {
            const parsed = JSON.parse(summaryData.coreContents);
            if (Array.isArray(parsed)) {
              parsedCoreContents.push(...parsed);
            } else if (typeof parsed === 'object') {
              Object.entries(parsed).forEach(([k, v]) => {
                parsedCoreContents.push({ title: k, description: typeof v === 'string' ? v : JSON.stringify(v) });
              });
            }
          } catch (e) {
            summaryData.coreContents.split('\n').filter(Boolean).forEach((line, idx) => {
              parsedCoreContents.push({ title: `${idx + 1}. 핵심 요약`, description: line.replace(/^[-\d.\s*]+/, '').trim() });
            });
          }
        }

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
                    {summaryData?.overview || '요약 개요 정보를 불러오는 중이거나 작성된 요약이 없습니다.'}
                  </p>
                </div>

                <div>
                  <h4 style={{ margin: '0 0 12px', fontSize: '16px', color: 'var(--color-text-main)' }}>🔑 핵심 키워드</h4>
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                    {material?.keywords ? (
                        material.keywords.split(',').map((kw) => (
                            <span key={kw} className="tag" style={{ backgroundColor: '#F3F4F6', color: 'var(--color-text-main)' }}>#{kw.trim()}</span>
                        ))
                    ) : (
                        <span style={{ color: 'var(--color-text-muted)', fontSize: '14px' }}>등록된 키워드가 없습니다.</span>
                    )}
                  </div>
                </div>

                <div>
                  <h4 style={{ margin: '0 0 16px', fontSize: '16px', color: 'var(--color-text-main)' }}>📑 세부 핵심 내용</h4>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                    {parsedCoreContents.length > 0 ? (
                        parsedCoreContents.map((content, idx) => (
                            <div key={idx} style={{ backgroundColor: '#F9FAFB', padding: '16px', borderRadius: '8px', border: '1px solid var(--color-border)' }}>
                              <h5 style={{ margin: '0 0 8px', fontSize: '15px' }}>{content.title || `${idx + 1}. 핵심 포인트`}</h5>
                              <p style={{ margin: 0, fontSize: '14px', lineHeight: '1.5', color: 'var(--color-text-muted)' }}>{content.description || content}</p>
                            </div>
                        ))
                    ) : (
                        <p style={{ color: 'var(--color-text-muted)', fontSize: '14px' }}>세부 요약 내용이 존재하지 않습니다.</p>
                    )}
                  </div>
                </div>
              </div>
            </div>
        );
      }
      case 'quiz': {
        const activeQuiz = quizzes.find(q => q.quizId === selectedQuizId);
        const parsedQuestions = activeQuiz ? parseQuizQuestions(activeQuiz.quizData) : [];

        return (
            <div className="animate-fade-in" style={{ paddingBottom: '24px', display: 'flex', flexDirection: 'column', height: '100%' }}>
              {/* 상단 액션 영역 */}
              <div className="glass-panel" style={{ padding: '24px', marginBottom: '24px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
                <div style={{ flex: '1 1 auto', minWidth: '200px' }}>
                  <h3 style={{ margin: '0 0 8px', fontSize: '20px', color: 'var(--color-text-main)' }}>퀴즈 생성</h3>
                  <p style={{ margin: 0, color: 'var(--color-text-muted)', fontSize: '14px', wordBreak: 'keep-all' }}>원하는 문제 유형, 난이도 등으로 퀴즈 세트를 만들어보세요.</p>
                </div>
                <div style={{ display: 'flex', gap: '12px', alignItems: 'center', flex: '0 0 auto' }}>
                  <button
                      className="btn-outline"
                      style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 20px', borderRadius: '30px', whiteSpace: 'nowrap', flexShrink: 0, width: 'auto' }}
                      onClick={() => setIsQuizSettingsOpen(true)}
                      disabled={isGeneratingQuiz}
                  >
                    설정
                  </button>
                  <button
                      className="btn-primary"
                      style={{ padding: '10px 24px', borderRadius: '30px', fontWeight: 'bold', whiteSpace: 'nowrap', flexShrink: 0, width: 'auto' }}
                      onClick={handleGenerateQuiz}
                      disabled={isGeneratingQuiz}
                  >
                    {isGeneratingQuiz ? '생성 중...' : '생성'}
                  </button>
                </div>
              </div>

              {/* 퀴즈 내용 영역 */}
              {selectedQuizId === null ? (
                  <div className="animate-fade-in" style={{ flex: 1 }}>
                    <h4 style={{ margin: '0 0 16px', fontSize: '16px', color: 'var(--color-text-main)' }}>내 퀴즈</h4>
                    {quizzes.length === 0 ? (
                        <p style={{ color: 'var(--color-text-muted)', fontSize: '14px' }}>출제된 퀴즈가 없습니다. 우측 상단의 생성 버튼을 눌러보세요!</p>
                    ) : (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                          {quizzes.map(quiz => (
                              <div
                                  key={quiz.quizId}
                                  className="glass-panel hover-scale"
                                  style={{ padding: '20px', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', alignItems: 'center', transition: 'all 0.2s', border: '1px solid transparent' }}
                                  onMouseEnter={(e) => e.currentTarget.style.border = '1px solid var(--color-primary)'}
                                  onMouseLeave={(e) => e.currentTarget.style.border = '1px solid transparent'}
                                  onClick={() => {
                                    setSelectedQuizId(quiz.quizId);
                                    setUserAnswers({});
                                  }}
                              >
                                <div>
                                  <h5 style={{ margin: '0 0 8px', fontSize: '16px', color: 'var(--color-text-main)' }}>
                                    {quiz.createdAt ? quiz.createdAt.split('T')[0] + ' ' + quiz.createdAt.split('T')[1].substring(0, 5) : '작성일 없음'}
                                  </h5>
                                  <p style={{ margin: 0, fontSize: '14px', color: 'var(--color-text-muted)' }}>문항: {quiz.questionCount}개 • 난이도: {quiz.difficulty} • 범위: {quiz.pageRange || '전체'}</p>
                                </div>
                                <ChevronRight size={20} color="var(--color-text-muted)" />
                              </div>
                          ))}
                        </div>
                    )}
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
                    {parsedQuestions.length === 0 ? (
                        <p style={{ color: 'var(--color-text-muted)', fontSize: '14px' }}>파싱된 질문이 없습니다.</p>
                    ) : (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>
                          {parsedQuestions.map((q, idx) => (
                              <div key={idx} className="glass-panel" style={{ padding: '24px', borderLeft: '4px solid var(--color-primary)' }}>
                                <h5 style={{ margin: '0 0 20px', fontSize: '16px', color: 'var(--color-text-main)', lineHeight: '1.5' }}>{q.q}</h5>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                                  {q.options.map((opt, optIdx) => {
                                    const isSelected = userAnswers[idx] === optIdx;
                                    const isCorrectAnswer = optIdx === q.answer;
                                    const hasAnswered = userAnswers[idx] !== undefined;

                                    let optionBgColor = 'white';
                                    let optionTextColor = 'var(--color-text-main)';
                                    let optionBorderColor = 'var(--color-border)';

                                    if (isSelected) {
                                      if (isCorrectAnswer) {
                                        optionBgColor = '#DCFCE7';
                                        optionBorderColor = '#86EFAC';
                                        optionTextColor = '#166534';
                                      } else {
                                        optionBgColor = '#FEE2E2';
                                        optionBorderColor = '#FCA5A5';
                                        optionTextColor = '#991B1B';
                                      }
                                    } else if (hasAnswered && isCorrectAnswer) {
                                      optionBgColor = '#DCFCE7';
                                      optionBorderColor = '#86EFAC';
                                      optionTextColor = '#166534';
                                    }

                                    return (
                                        <button
                                            key={optIdx}
                                            onClick={() => handleSelectOption(idx, optIdx)}
                                            className="btn-outline"
                                            style={{
                                              width: '100%', height: 'auto', display: 'flex', alignItems: 'center',
                                              textAlign: 'left', fontWeight: 'normal', justifyContent: 'flex-start',
                                              fontSize: '15px', padding: '16px', borderRadius: '12px',
                                              backgroundColor: optionBgColor,
                                              borderColor: optionBorderColor,
                                              color: optionTextColor,
                                              transition: 'all 0.2s'
                                            }}
                                        >
                                          {opt}
                                        </button>
                                    );
                                  })}
                                </div>
                              </div>
                          ))}
                        </div>
                    )}
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
      }
      case 'memo':
        return (
            <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', height: '100%', paddingBottom: '24px' }}>
              <h3 style={{ margin: '0 0 16px', fontSize: '20px' }}>나의 학습 메모</h3>
              <p style={{ color: 'var(--color-text-muted)', fontSize: '14px', marginBottom: '16px' }}>문서와 관련된 아이디어나 핵심 정리 사항을 메모로 기록해보세요.</p>
              <textarea
                  style={{
                    flex: 1,
                    padding: '24px',
                    borderRadius: '16px',
                    border: '1px solid var(--color-border)',
                    backgroundColor: '#FFFDF5',
                    color: 'var(--color-text-main)',
                    fontSize: '16px',
                    lineHeight: '1.7',
                    fontFamily: 'inherit',
                    resize: 'none',
                    boxShadow: 'inset 0 2px 8px rgba(0,0,0,0.03)',
                    minHeight: '300px'
                  }}
                  placeholder="이 자료를 보며 중요하게 기억할 부분을 자유롭게 입력하세요."
                  value={memoText}
                  onChange={(e) => setMemoText(e.target.value)}
              />
              <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '20px' }}>
                <button
                    className="btn-primary"
                    style={{ width: 'auto', padding: '12px 32px', borderRadius: '30px', fontWeight: 'bold' }}
                    onClick={handleSaveMemo}
                    disabled={isSavingMemo}
                >
                  {isSavingMemo ? '저장 중...' : '메모 저장'}
                </button>
              </div>
            </div>
        );

      case 'chat':
        return (
            <div className="animate-fade-in" style={{ display: 'flex', flexDirection: 'column', height: '100%', minHeight: '450px' }}>
              <h3 style={{ margin: '0 0 16px', fontSize: '20px' }}>AI 질문</h3>
              <div style={{ flex: 1, backgroundColor: '#F9FAFB', borderRadius: '12px', padding: '24px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '20px', border: '1px solid var(--color-border)', maxHeight: '350px' }}>
                {chatMessages.map((msg, idx) => (
                    <div
                        key={idx}
                        style={{
                          alignSelf: msg.sender === 'user' ? 'flex-end' : 'flex-start',
                          backgroundColor: msg.sender === 'user' ? 'var(--color-primary)' : 'white',
                          color: msg.sender === 'user' ? 'white' : 'var(--color-text-main)',
                          padding: '16px 20px',
                          borderRadius: '20px',
                          borderTopLeftRadius: msg.sender === 'ai' ? '4px' : '20px',
                          borderTopRightRadius: msg.sender === 'user' ? '4px' : '20px',
                          maxWidth: '85%',
                          boxShadow: '0 1px 4px rgba(0,0,0,0.05)',
                          fontSize: '15px',
                          lineHeight: '1.6',
                          whiteSpace: 'pre-wrap'
                        }}
                    >
                      {msg.text}
                    </div>
                ))}
                <div ref={chatEndRef} />
              </div>
              <div style={{ marginTop: '16px' }}>
                <form onSubmit={handleSendChat} style={{ display: 'flex', gap: '12px', width: '100%' }}>
                  <input
                      type="text"
                      className="input-field"
                      style={{ flex: 1, minWidth: 0, margin: 0, borderRadius: '30px', backgroundColor: '#F3F4F6', border: 'none', padding: '16px 24px', fontSize: '15px', height: '50px' }}
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

  if (isLoadingDetail) {
    return (
        <div className="container-main" style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '50vh', color: 'var(--color-primary)', fontWeight: 'bold' }}>
          상세 분석 자료를 불러오는 중입니다...
        </div>
    );
  }

  if (!material) {
    return (
        <div className="container-main" style={{ textAlign: 'center', marginTop: '100px' }}>
          <h2>자료를 찾을 수 없습니다.</h2>
          <button className="btn-primary" style={{ width: 'auto', padding: '0 24px', margin: '20px auto' }} onClick={() => navigate('/archive')}>목록으로 돌아가기</button>
        </div>
    );
  }

  // AI 분석 대기/추출 상태 뷰
  if (material.extractionStatus === 'PENDING' || material.extractionStatus === 'PROCESSING') {
    return (
        <div className="container-main animate-fade-in" style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', minHeight: '60vh', textAlign: 'center' }}>
          <div className="glass-panel" style={{ padding: '60px 40px', maxWidth: '600px', borderRadius: '16px' }}>
            <div className="animate-spin-custom" style={{ width: '48px', height: '48px', border: '4px solid #E5E7EB', borderTopColor: 'var(--color-primary)', borderRadius: '50%', margin: '0 auto 24px' }}></div>
            <h2 style={{ margin: '0 0 16px', color: 'var(--color-text-main)' }}>AI가 문서를 열심히 분석하고 있습니다 🧠</h2>
            <p style={{ color: 'var(--color-text-muted)', lineHeight: '1.6', marginBottom: '24px' }}>
              문서에서 핵심 정보를 읽고 주차별 로드맵, 핵심 요약, 메모 및 AI 퀴즈 데이터베이스를 조율하는 과정입니다. 분석이 완료되면 자동으로 화면이 전환됩니다. 잠시만 기다려주세요!
            </p>
            <button className="btn-outline" style={{ width: 'auto', padding: '8px 24px' }} onClick={() => navigate('/archive')}>목록으로 돌아가기</button>
          </div>
          <style dangerouslySetInnerHTML={{__html: `
          @keyframes spin {
            to { transform: rotate(360deg); }
          }
          .animate-spin-custom {
            animation: spin 1.2s linear infinite;
          }
        `}} />
        </div>
    );
  }

  return (
      <div className="archive-detail-container animate-fade-in">
        <style dangerouslySetInnerHTML={{__html: `
        .archive-detail-container, .archive-detail-container * {
          box-sizing: border-box;
        }
      `}} />
        {type === 'pdf' && (
            <div className="archive-action-bar" style={{ padding: '16px 24px', borderBottom: '1px solid var(--color-border)', backgroundColor: 'white', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flex: 1, minWidth: 0 }}>
                <button className="btn-outline" style={{ width: 'auto', padding: '8px 16px', border: 'none', flexShrink: 0 }} onClick={() => navigate('/archive')}>
                  <ArrowLeft size={18} /> 목록
                </button>
                <span style={{ fontWeight: '600', fontSize: '18px', color: 'var(--color-text-main)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flex: 1 }} title={material.title || material.originalFileName}>
                  {material.title || material.originalFileName}
                </span>
              </div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '16px', flexShrink: 0 }}>
                {/* 뷰어 너비 */}
                <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                  <span style={{ fontSize: '12px', color: 'var(--color-text-muted)', marginRight: '4px' }}>뷰어 너비:</span>
                  {[30, 50, 70].map(pct => (
                      <button
                          key={pct}
                          onClick={() => setLeftWidth(pct)}
                          style={{
                            padding: '4px 8px',
                            fontSize: '11px',
                            borderRadius: '4px',
                            border: '1px solid var(--color-border)',
                            backgroundColor: leftWidth === pct ? 'var(--color-primary)' : 'white',
                            color: leftWidth === pct ? 'white' : 'var(--color-text-main)',
                            cursor: 'pointer',
                            fontWeight: leftWidth === pct ? 'bold' : 'normal',
                            transition: 'all 0.15s'
                          }}
                      >
                        {pct}%
                      </button>
                  ))}
                </div>
                {/* 기존 AI 버튼들 */}
                <div style={{ display: 'flex', gap: '8px' }}>
                  <button className={`archive-action-btn ${activePdfTool === 'summary' ? 'active' : ''}`} onClick={() => setActivePdfTool('summary')}><AlignLeft size={16} /> 요약</button>
                  <button className={`archive-action-btn ${activePdfTool === 'quiz' ? 'active' : ''}`} onClick={() => setActivePdfTool('quiz')}><HelpCircle size={16} /> 퀴즈/문제 생성</button>
                  <button className={`archive-action-btn ${activePdfTool === 'memo' ? 'active' : ''}`} onClick={() => setActivePdfTool('memo')}><Edit3 size={16} /> 메모</button>
                  <button className={`archive-action-btn ${activePdfTool === 'chat' ? 'active' : ''}`} onClick={() => setActivePdfTool('chat')}><MessageSquare size={16} /> AI 질문</button>
                </div>
                {/* 삭제 버튼 */}
                <button className="btn-outline" style={{ width: 'auto', padding: '8px 16px', border: 'none', color: '#EF4444' }} onClick={handleDeleteMaterial}>
                  <Trash2 size={18} /> 삭제
                </button>
              </div>
            </div>
        )}

        {type === 'journal' && (
            <div style={{ padding: '16px 24px', backgroundColor: 'white', borderBottom: '1px solid var(--color-border)', display: 'flex', alignItems: 'center', gap: '16px' }}>
              <button className="btn-outline" style={{ width: 'auto', padding: '8px 16px', border: 'none' }} onClick={() => navigate('/archive')}>
                <ArrowLeft size={18} /> 목록
              </button>
              <button className="btn-outline" style={{ width: 'auto', padding: '8px 16px', border: 'none', color: '#EF4444' }} onClick={handleDeleteMaterial}>
                <Trash2 size={18} /> 삭제
              </button>
              <div style={{ display: 'flex', flexDirection: 'column' }}>
                <h2 style={{ margin: 0, fontSize: '18px' }}>{material.title}</h2>
                <span style={{ fontSize: '13px', color: 'var(--color-text-muted)' }}>
                  {material.studyDate || (material.uploadedAt ? material.uploadedAt.split('T')[0] : '')} • 학습일지
                </span>
              </div>
            </div>
        )}

        <div className="archive-split-view">
          <div className="archive-left-panel" style={{ width: type === 'pdf' ? `${leftWidth}%` : '50%', flex: 'none', overflowY: 'auto' }}>
            {type === 'pdf' ? (
                <div style={{ width: '100%', height: '100%', backgroundColor: 'white', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
                  {material.s3PresignedUrl ? (
                      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', height: '100%' }}>

                        <div style={{ flex: 1, position: 'relative' }}>
                          <iframe src={material.s3PresignedUrl} style={{ width: '100%', height: '100%', border: 'none' }} title="Document Viewer" />
                        </div>
                      </div>
                  ) : (
                      <div style={{ width: '100%', height: '100%', display: 'flex', justifyContent: 'center', alignItems: 'center', flexDirection: 'column', padding: '40px' }}>
                        <div style={{ padding: '40px', backgroundColor: '#F3F4F6', borderRadius: '8px', marginBottom: '24px' }}>
                          <span style={{ fontSize: '48px', color: '#9CA3AF' }}>PDF</span>
                        </div>
                        <h3 style={{ margin: '0 0 8px', color: 'var(--color-text-main)' }}>{material.title}</h3>
                        <p style={{ color: 'var(--color-text-muted)', margin: 0, textAlign: 'center' }}>문서 미리보기 영역 (S3 파일이 준비되지 않았습니다)</p>
                      </div>
                  )}
                </div>
            ) : (
                <div className="glass-panel" style={{ padding: '32px' }}>
                  <div>
                    <h2 style={{ margin: '0 0 8px', color: 'var(--color-text-main)' }}>학습일지 상세</h2>
                    <p style={{ margin: 0, color: 'var(--color-text-muted)', fontSize: '14px' }}>학습일지 내용을 확인합니다.</p>
                  </div>

                  <hr style={{ border: 'none', borderTop: '1px solid var(--color-border)', margin: '24px 0' }} />

                  <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                    <div>
                      <h4 style={{ margin: '0 0 8px', fontSize: '15px', color: 'var(--color-text-muted)', fontWeight: '600' }}>제목</h4>
                      <p style={{ margin: 0, fontSize: '16px', color: 'var(--color-text-main)', fontWeight: 'bold' }}>{material.title}</p>
                    </div>

                    <div>
                      <h4 style={{ margin: '0 0 8px', fontSize: '15px', color: 'var(--color-text-muted)', fontWeight: '600' }}>날짜</h4>
                      <p style={{ margin: 0, fontSize: '15px', color: 'var(--color-text-main)' }}>{material.studyDate || (material.uploadedAt ? material.uploadedAt.split('T')[0] : '')}</p>
                    </div>

                    <div>
                      <h4 style={{ margin: '0 0 8px', fontSize: '15px', color: 'var(--color-text-muted)', fontWeight: '600' }}>핵심 키워드</h4>
                      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                        {material.keywords ? (
                            material.keywords.split(',').map((kw) => (
                                <span key={kw} className="tag" style={{ backgroundColor: '#F3F4F6', color: 'var(--color-text-main)' }}>#{kw.trim()}</span>
                            ))
                        ) : (
                            <span style={{ color: 'var(--color-text-muted)', fontSize: '14px' }}>등록된 키워드가 없습니다.</span>
                        )}
                      </div>
                    </div>

                    <div>
                      <h4 style={{ margin: '0 0 8px', fontSize: '15px', color: 'var(--color-text-muted)', fontWeight: '600' }}>학습 내용</h4>
                      <p style={{ margin: 0, lineHeight: '1.6', whiteSpace: 'pre-wrap', color: 'var(--color-text-main)' }}>{material.learningContent || '작성된 내용이 없습니다.'}</p>
                    </div>

                    <div>
                      <h4 style={{ margin: '0 0 8px', fontSize: '15px', color: 'var(--color-text-muted)', fontWeight: '600' }}>다음 학습 계획</h4>
                      <p style={{ margin: 0, lineHeight: '1.6', whiteSpace: 'pre-wrap', color: 'var(--color-text-main)' }}>{material.nextPlan || '작성된 계획이 없습니다.'}</p>
                    </div>
                  </div>
                </div>
            )}
          </div>
          {type === 'pdf' && (
              <div
                  style={{
                    width: '1px',
                    backgroundColor: 'var(--color-border)',
                    zIndex: 10,
                  }}
              />
          )}
          <div className="archive-right-panel" style={{ width: type === 'pdf' ? `${100 - leftWidth}%` : '50%', flex: 'none', overflowY: 'auto', overflowX: 'hidden', boxSizing: 'border-box', backgroundColor: type === 'journal' ? 'var(--color-bg-base)' : 'white', borderLeft: type === 'pdf' ? 'none' : '1px solid var(--color-border)' }}>
            {type === 'pdf' ? (
                renderPdfRightPanel()
            ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                  <div className="glass-panel animate-fade-in" style={{ padding: '24px' }}>
                    <h3 style={{ margin: '0 0 16px', fontSize: '18px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <AlignLeft size={18} color="var(--color-primary)" /> AI 요약
                    </h3>
                    <p style={{ margin: 0, fontSize: '15px', lineHeight: '1.6', color: 'var(--color-text-main)' }}>
                      {summaryData?.overview || '학습일지의 AI 요약을 생성하는 중이거나 내용이 부족합니다.'}
                    </p>
                  </div>

                  <div className="glass-panel animate-fade-in" style={{ padding: '24px' }}>
                    <h3 style={{ margin: '0 0 16px', fontSize: '18px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                      <MessageSquare size={18} color="var(--color-primary)" /> AI 피드백
                    </h3>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                      {summaryData?.overview ? (
                          <div style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
                            <div style={{ width: '24px', height: '24px', borderRadius: '50%', backgroundColor: 'var(--color-primary)', color: 'white', display: 'flex', justifyContent: 'center', alignItems: 'center', fontSize: '12px', fontWeight: 'bold', flexShrink: 0 }}>1</div>
                            <p style={{ margin: 0, fontSize: '14px', lineHeight: '1.5', color: 'var(--color-text-main)' }}>
                              학습일지 분석 결과, 주제에 맞게 핵심 지식을 정확히 성찰하였습니다.
                            </p>
                          </div>
                      ) : (
                          <p style={{ color: 'var(--color-text-muted)', fontSize: '14px', margin: 0 }}>AI 피드백이 생성되지 않았습니다.</p>
                      )}
                    </div>
                  </div>
                </div>
            )}
          </div>
        </div>
      </div>
  );
}
