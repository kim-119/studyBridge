import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { FileText, File as FileIcon, Plus, X, AlignLeft, MessageSquare } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import { materialService } from '../services/api';

export default function Archive() {
  const { userId } = useAuth();
  const navigate = useNavigate();
  const [activeTab, setActiveTab] = useState('journal');
  const [openedModalType, setOpenedModalType] = useState(null); // 'addMaterial'
  const [addMaterialType, setAddMaterialType] = useState('journal');
  const [visibleCount, setVisibleCount] = useState(6);
  const [selectedJournal, setSelectedJournal] = useState(null);
  const [isJournalEditMode, setIsJournalEditMode] = useState(false);

  // 실시간 백엔드 데이터 상태
  const [journals, setJournals] = useState([]);
  const [pdfs, setPdfs] = useState([]);
  const [isLoading, setIsLoading] = useState(false);

  // AI 분석 실시간 상태
  const [journalSummary, setJournalSummary] = useState('');
  const [journalFeedback, setJournalFeedback] = useState([]);

  // "자료 추가" 폼 상태
  const [formTitle, setFormTitle] = useState('');
  const [formDate, setFormDate] = useState(new Date().toISOString().split('T')[0]);
  const [formKeywords, setFormKeywords] = useState('');
  const [formContent, setFormContent] = useState('');
  const [formNextPlan, setFormNextPlan] = useState('');
  const [formFile, setFormFile] = useState(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const addFileInputRef = useRef(null);

  // "학습일지 수정" 폼 상태
  const [editTitle, setEditTitle] = useState('');
  const [editDate, setEditDate] = useState('');
  const [editKeywords, setEditKeywords] = useState('');
  const [editContent, setEditContent] = useState('');
  const [editNextPlan, setEditNextPlan] = useState('');

  // ---------------- 인증 체크 핸들러 ----------------
  const checkAuth = () => {
    if (!userId) {
      alert('로그인이 필요한 기능입니다. 로그인 페이지로 이동합니다.');
      navigate('/login');
      return false;
    }
    return true;
  };

  // ---------------- 데이터 페칭 ----------------
  const fetchMaterials = async () => {
    if (!userId) return;
    try {
      setIsLoading(true);
      const data = await materialService.getMaterials();
      const list = Array.isArray(data) ? data : [];

      // 1. 학습일지 필터링 및 매핑
      const fetchedJournals = list
          .filter((item) => item.materialType === 'STUDY_LOG')
          .map((item) => ({
            id: item.materialId,
            title: item.title || '제목 없음',
            date: item.studyDate || (item.uploadedAt ? item.uploadedAt.split('T')[0] : ''),
            tag: '학습일지',
            description: item.learningContent
                ? item.learningContent.length > 100
                    ? item.learningContent.substring(0, 100) + '...'
                    : item.learningContent
                : '학습 내용이 비어 있습니다.',
            stats: { time: '-', solved: 0, score: '-' },
            keywords: item.keywords ? item.keywords.split(',').map((k) => k.trim()) : [],
            content: item.learningContent || '',
            nextPlan: item.nextPlan || '',
          }));

      // 2. PDF / Syllabus 필터링 및 매핑
      const fetchedPdfs = list
          .filter((item) => item.materialType === 'SYLLABUS' || item.materialType === 'PDF')
          .map((item) => ({
            id: item.materialId,
            title: item.title || item.originalFileName || '이름 없음',
            date: item.uploadedAt ? item.uploadedAt.split('T')[0] : '',
            tag: item.materialType === 'SYLLABUS' ? '강의계획서' : '학습PDF',
            extractionStatus: item.extractionStatus || 'SUCCESS',
          }));

      setJournals(fetchedJournals);
      setPdfs(fetchedPdfs);
    } catch (error) {
      console.error('자료 목록 조회 실패:', error);
    } finally {
      setIsLoading(false);
    }
  };

  // AI 요약 & 피드백 조회
  const fetchJournalAiData = async (materialId) => {
    try {
      setJournalSummary('AI가 학습일지를 분석 중입니다...');
      setJournalFeedback([]);

      const summaryRes = await materialService.getSummary(materialId);
      if (summaryRes && summaryRes.overview) {
        setJournalSummary(summaryRes.overview);
      } else {
        setJournalSummary('작성된 학습일지를 바탕으로 분석된 AI 요약이 아직 생성되지 않았습니다.');
      }

      const feedbackRes = await materialService.getFeedback(materialId);
      if (feedbackRes && feedbackRes.feedbackData) {
        try {
          const parsed = JSON.parse(feedbackRes.feedbackData);
          setJournalFeedback(Array.isArray(parsed) ? parsed : [feedbackRes.feedbackData]);
        } catch {
          setJournalFeedback(feedbackRes.feedbackData.split('\n').filter(Boolean));
        }
      } else {
        setJournalFeedback(['아직 등록된 AI 피드백이 없습니다. 잠시 후 다시 확인해주세요.']);
      }
    } catch (error) {
      console.error('AI 분석 정보 조회 실패:', error);
      setJournalSummary('AI 요약을 가져오는 도중 오류가 발생했습니다.');
      setJournalFeedback(['AI 피드백 정보를 불러오지 못했습니다.']);
    }
  };

  useEffect(() => {
    if (userId) {
      fetchMaterials();
    } else {
      setJournals([]);
      setPdfs([]);
    }
  }, [userId]);

  // ---------------- 핸들러 ----------------
  const handleTabChange = (tab) => {
    setActiveTab(tab);
    setVisibleCount(6);
  };

  const handleOpenDetail = (type, item) => {
    if (!checkAuth()) return;
    if (type === 'journal') {
      setSelectedJournal(item);
      setEditTitle(item.title);
      setEditDate(item.date);
      setEditKeywords(item.keywords.join(', '));
      setEditContent(item.content);
      setEditNextPlan(item.nextPlan);
      setIsJournalEditMode(false);
      fetchJournalAiData(item.id);
    } else {
      navigate(`/archive/${type}/${item.id}`, { state: { item } });
    }
  };

  const resetFormState = () => {
    setFormTitle('');
    setFormDate(new Date().toISOString().split('T')[0]);
    setFormKeywords('');
    setFormContent('');
    setFormNextPlan('');
    setFormFile(null);
  };

  const openModal = (type) => {
    if (!checkAuth()) return;
    setOpenedModalType(type);
    if (type === 'addMaterial') {
      setAddMaterialType('journal');
      resetFormState();
    }
  };

  const closeModal = () => {
    setOpenedModalType(null);
    resetFormState();
  };

  // 자료 추가 제출
  const handleSubmitMaterial = async () => {
    if (!checkAuth()) return;
    if (!formTitle.trim()) {
      alert('제목을 입력해주세요.');
      return;
    }

    try {
      setIsSubmitting(true);
      if (addMaterialType === 'journal') {
        const payload = {
          title: formTitle,
          keywords: formKeywords,
          studyDate: formDate || new Date().toISOString().split('T')[0],
          learningContent: formContent,
          nextPlan: formNextPlan,
        };
        await materialService.createStudyLog(payload);
        alert('학습일지가 등록되었습니다.');
      } else {
        if (!formFile) {
          alert('업로드할 파일을 선택해주세요.');
          return;
        }
        const materialType = addMaterialType === 'syllabus' ? 'SYLLABUS' : 'PDF';
        await materialService.uploadMaterial(formTitle, materialType, formKeywords, formFile);
        alert('자료 업로드가 시작되었습니다. AI가 문서를 분석하는 데 수 분이 걸릴 수 있습니다.');
      }
      closeModal();
      fetchMaterials();
    } catch (error) {
      console.error('자료 추가 실패:', error);
      alert(error.response?.data?.message || '자료 추가 중 오류가 발생했습니다.');
    } finally {
      setIsSubmitting(false);
    }
  };

  // 학습일지 삭제
  const handleDeleteJournal = async () => {
    if (!checkAuth()) return;
    if (window.confirm('정말로 이 학습일지를 삭제하시겠습니까? 삭제 후 복구할 수 없습니다.')) {
      try {
        await materialService.deleteMaterial(selectedJournal.id);
        alert('학습일지가 삭제되었습니다.');
        setSelectedJournal(null);
        fetchMaterials();
      } catch (error) {
        console.error('학습일지 삭제 실패:', error);
        alert('삭제 도중 오류가 발생했습니다.');
      }
    }
  };

  // 학습일지 수정
  const handleUpdateJournal = async () => {
    if (!checkAuth()) return;
    if (!editTitle.trim()) {
      alert('제목을 입력해주세요.');
      return;
    }
    try {
      await materialService.updateMaterial(selectedJournal.id, {
        title: editTitle,
        keywords: editKeywords,
        learningContent: editContent,
        nextPlan: editNextPlan,
      });
      alert('학습일지가 수정되었습니다.');
      setIsJournalEditMode(false);
      fetchMaterials();
      
      // Update local state and trigger AI data fetch to reload feedback/summary if content changed
      setSelectedJournal((prev) => ({
        ...prev,
        title: editTitle,
        keywords: editKeywords.split(',').map((k) => k.trim()),
        content: editContent,
        nextPlan: editNextPlan,
      }));
      
      // Re-fetch the AI data (feedback, summary) because they might have been regenerated
      fetchJournalAiData(selectedJournal.id);
    } catch (error) {
      console.error('학습일지 수정 실패:', error);
      alert('수정 도중 오류가 발생했습니다.');
    }
  };

  return (
      <div className="container-main archive-page">
        {/* 1. 상단 헤더 영역 */}
        <div className="archive-control-bar">
          <div className="archive-tabs">
            <button
                className={`archive-tab ${activeTab === 'journal' ? 'active' : ''}`}
                onClick={() => handleTabChange('journal')}
            >
              학습일지
            </button>
            <button
                className={`archive-tab ${activeTab === 'syllabus' ? 'active' : ''}`}
                onClick={() => handleTabChange('syllabus')}
            >
              강의계획서
            </button>
            <button
                className={`archive-tab ${activeTab === 'pdf' ? 'active' : ''}`}
                onClick={() => handleTabChange('pdf')}
            >
              학습 PDF
            </button>
          </div>
          <button className="btn-primary btn-add-material" onClick={() => openModal('addMaterial')}>
            <Plus size={16} /> 자료 추가
          </button>
        </div>

        {/* 2. 카드 목록 영역 */}
        <div className="archive-grid">
          {isLoading && (
              <div style={{ gridColumn: '1 / -1', textAlign: 'center', padding: '40px', color: 'var(--color-text-muted)' }}>
                자료를 불러오는 중입니다...
              </div>
          )}

          {!isLoading && activeTab === 'journal' && journals.length === 0 && (
              <div className="glass-panel" style={{ gridColumn: '1 / -1', padding: '60px 20px', textAlign: 'center', color: 'var(--color-text-muted)', borderRadius: '12px' }}>
                <FileText size={48} style={{ margin: '0 auto 16px', opacity: 0.3 }} />
                <h3 style={{ margin: '0 0 8px', color: 'var(--color-text-main)' }}>등록된 학습일지가 없습니다</h3>
                <p style={{ margin: 0 }}>새로운 학습일지를 등록하여 AI의 상세 분석과 요약을 확인해보세요.</p>
              </div>
          )}

          {!isLoading && activeTab === 'journal' && journals.slice(0, visibleCount).map((journal) => (
              <div
                  key={journal.id}
                  className="glass-panel archive-card animate-fade-in"
                  style={{ cursor: 'pointer' }}
                  onClick={() => handleOpenDetail('journal', journal)}
              >
                <div className="card-header">
                  <div className="icon-wrapper journal-icon">
                    <FileText size={22} color="rgba(255,255,255,0.8)" />
                  </div>
                  <span className="card-date">{journal.date}</span>
                </div>
                <h3 className="card-title">{journal.title}</h3>
                <div className="card-tags">
                  <span className="card-tag">#{journal.tag}</span>
                </div>
                <p className="card-desc">{journal.description}</p>
              </div>
          ))}

          {!isLoading && activeTab === 'syllabus' && pdfs.filter(p => p.tag === '강의계획서').length === 0 && (
              <div className="glass-panel" style={{ gridColumn: '1 / -1', padding: '60px 20px', textAlign: 'center', color: 'var(--color-text-muted)', borderRadius: '12px' }}>
                <FileIcon size={48} style={{ margin: '0 auto 16px', opacity: 0.3 }} />
                <h3 style={{ margin: '0 0 8px', color: 'var(--color-text-main)' }}>등록된 강의계획서가 없습니다</h3>
                <p style={{ margin: 0 }}>강의계획서를 업로드하여 AI 기반의 주차별 자동 학습 로드맵을 설계해보세요.</p>
              </div>
          )}

          {!isLoading && activeTab === 'syllabus' && pdfs.filter(p => p.tag === '강의계획서').slice(0, visibleCount).map((pdf) => (
              <div
                  key={pdf.id}
                  className="glass-panel archive-card animate-fade-in"
                  style={{ cursor: 'pointer' }}
                  onClick={() => handleOpenDetail('syllabus', pdf)}
              >
                <div className="card-header">
                  <div className="icon-wrapper pdf-icon">
                    <FileIcon size={22} color="rgba(255,255,255,0.8)" />
                  </div>
                  <span className="card-date">{pdf.date}</span>
                </div>
                <h3 className="card-title">{pdf.title}</h3>
                <div className="card-tags" style={{ marginBottom: 'auto' }}>
                  <span className="card-tag">#{pdf.tag}</span>
                </div>
              </div>
          ))}

          {!isLoading && activeTab === 'pdf' && pdfs.filter(p => p.tag === '학습PDF').length === 0 && (
              <div className="glass-panel" style={{ gridColumn: '1 / -1', padding: '60px 20px', textAlign: 'center', color: 'var(--color-text-muted)', borderRadius: '12px' }}>
                <FileIcon size={48} style={{ margin: '0 auto 16px', opacity: 0.3 }} />
                <h3 style={{ margin: '0 0 8px', color: 'var(--color-text-main)' }}>등록된 학습 PDF가 없습니다</h3>
                <p style={{ margin: 0 }}>학습용 PDF 파일을 업로드하면 AI 핵심 요약 및 맞춤 퀴즈 출제 기능을 이용할 수 있습니다.</p>
              </div>
          )}

          {!isLoading && activeTab === 'pdf' && pdfs.filter(p => p.tag === '학습PDF').slice(0, visibleCount).map((pdf) => (
              <div
                  key={pdf.id}
                  className="glass-panel archive-card animate-fade-in"
                  style={{ cursor: 'pointer' }}
                  onClick={() => handleOpenDetail('pdf', pdf)}
              >
                <div className="card-header">
                  <div className="icon-wrapper pdf-icon">
                    <FileIcon size={22} color="rgba(255,255,255,0.8)" />
                  </div>
                  <span className="card-date">{pdf.date}</span>
                </div>
                <h3 className="card-title">{pdf.title}</h3>
                <div className="card-tags" style={{ marginBottom: 'auto' }}>
                  <span className="card-tag">#{pdf.tag}</span>
                </div>
              </div>
          ))}
        </div>

        {/* 3. 더보기(Load More) 버튼 */}
        {((activeTab === 'journal' && visibleCount < journals.length) ||
            (activeTab === 'syllabus' && visibleCount < pdfs.filter(p => p.tag === '강의계획서').length) ||
            (activeTab === 'pdf' && visibleCount < pdfs.filter(p => p.tag === '학습PDF').length)) && (
            <div style={{ display: 'flex', justifyContent: 'center', marginTop: '40px' }}>
              <button
                  className="btn-outline"
                  style={{ width: 'max-content', flex: 'none', padding: '12px 32px', borderRadius: '30px', fontWeight: '600', backgroundColor: 'white', border: '1px solid var(--color-border)', boxShadow: '0 2px 4px rgba(0,0,0,0.05)' }}
                  onClick={() => setVisibleCount(prev => prev + 6)}
              >
                + 더보기 ({(activeTab === 'journal' ? visibleCount : visibleCount)}/{(activeTab === 'journal' ? journals.length : activeTab === 'syllabus' ? pdfs.filter(p => p.tag === '강의계획서').length : pdfs.filter(p => p.tag === '학습PDF').length)})
              </button>
            </div>
        )}

        {/* 자료 추가 모달 */}
        {openedModalType === 'addMaterial' && (
            <div className="modal-overlay">
              <div className="glass-panel modal-content" style={{ maxWidth: '800px', width: '100%', minHeight: '750px', maxHeight: '90vh', padding: '32px', overflowY: 'auto', display: 'flex', flexDirection: 'column' }}>
                <div className="modal-header" style={{ marginBottom: '24px', flexShrink: 0 }}>
                  <h3 style={{ margin: 0, fontSize: '22px' }}>자료 추가</h3>
                  <button className="btn-close" onClick={closeModal}><X size={24} /></button>
                </div>
                <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '24px', flex: 1 }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '16px', fontWeight: 'bold', marginBottom: '12px' }}>자료 유형</label>
                    <div style={{ display: 'flex', gap: '20px' }}>
                      <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '16px', cursor: 'pointer' }}>
                        <input type="radio" name="materialType" checked={addMaterialType === 'journal'} onChange={() => setAddMaterialType('journal')} style={{ transform: 'scale(1.2)' }} /> 학습일지
                      </label>
                      <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '16px', cursor: 'pointer' }}>
                        <input type="radio" name="materialType" checked={addMaterialType === 'syllabus'} onChange={() => setAddMaterialType('syllabus')} style={{ transform: 'scale(1.2)' }} /> 강의계획서
                      </label>
                      <label style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '16px', cursor: 'pointer' }}>
                        <input type="radio" name="materialType" checked={addMaterialType === 'pdf'} onChange={() => setAddMaterialType('pdf')} style={{ transform: 'scale(1.2)' }} /> 학습PDF
                      </label>
                    </div>
                  </div>

                  <hr style={{ border: 'none', borderTop: '1px solid var(--color-border)', margin: '0' }} />

                  {addMaterialType === 'journal' ? (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
                          <div>
                            <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>제목</label>
                            <input type="text" className="input-field" placeholder="학습일지 제목" value={formTitle} onChange={(e) => setFormTitle(e.target.value)} style={{ width: '100%', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
                          </div>
                          <div>
                            <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>날짜</label>
                            <input type="date" className="input-field" value={formDate} onChange={(e) => setFormDate(e.target.value)} style={{ width: '100%', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
                          </div>
                        </div>

                        <div>
                          <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>핵심 키워드 (쉼표로 구분)</label>
                          <input type="text" className="input-field" placeholder="키워드 입력 (예: React, 상태관리)" value={formKeywords} onChange={(e) => setFormKeywords(e.target.value)} style={{ width: '100%', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
                        </div>

                        <div>
                          <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>학습 내용</label>
                          <textarea className="input-field" placeholder="학습한 내용을 상세히 작성하세요." value={formContent} onChange={(e) => setFormContent(e.target.value)} style={{ width: '100%', minHeight: '120px', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', resize: 'vertical', backgroundColor: '#F9FAFB', fontFamily: 'inherit', lineHeight: '1.5' }} />
                        </div>

                        <div>
                          <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>다음 학습 계획</label>
                          <textarea className="input-field" placeholder="다음에 학습할 내용을 작성하세요." value={formNextPlan} onChange={(e) => setFormNextPlan(e.target.value)} style={{ width: '100%', minHeight: '80px', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', resize: 'vertical', backgroundColor: '#F9FAFB', fontFamily: 'inherit', lineHeight: '1.5' }} />
                        </div>
                      </div>
                  ) : (
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', flex: 1 }}>
                        <div>
                          <label style={{ display: 'block', fontSize: '16px', fontWeight: 'bold', marginBottom: '12px' }}>제목</label>
                          <input type="text" className="input-field" placeholder="자료의 제목을 입력하세요" value={formTitle} onChange={(e) => setFormTitle(e.target.value)} style={{ width: '100%', fontSize: '16px', padding: '16px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
                        </div>

                        <div>
                          <label style={{ display: 'block', fontSize: '16px', fontWeight: 'bold', marginBottom: '12px' }}>핵심 키워드 (쉼표로 구분)</label>
                          <input type="text" className="input-field" placeholder="키워드 입력" value={formKeywords} onChange={(e) => setFormKeywords(e.target.value)} style={{ width: '100%', fontSize: '16px', padding: '16px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
                        </div>

                        <div style={{ display: 'flex', flexDirection: 'column', flex: 1 }}>
                          <label style={{ display: 'block', fontSize: '16px', fontWeight: 'bold', marginBottom: '12px' }}>파일 업로드</label>
                          <input type="file" accept="application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain" ref={addFileInputRef} onChange={(e) => setFormFile(e.target.files[0])} style={{ display: 'none' }} />
                          <div
                              onClick={() => addFileInputRef.current?.click()}
                              style={{ flex: 1, border: '2px dashed var(--color-border)', borderRadius: '12px', padding: '40px', display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', textAlign: 'center', color: 'var(--color-text-muted)', backgroundColor: '#F9FAFB', cursor: 'pointer', transition: 'all 0.2s', minHeight: '200px' }}
                          >
                            <FileIcon size={48} style={{ margin: '0 auto 16px', opacity: 0.5 }} />
                            <p style={{ margin: '0 0 12px', fontSize: '16px', fontWeight: 'bold' }}>
                              {formFile ? `선택된 파일: ${formFile.name}` : '클릭하거나 파일을 드래그하여 업로드하세요'}
                            </p>
                            <p style={{ margin: 0, fontSize: '14px' }}>지원 형식: PDF, DOCX, TXT</p>
                          </div>
                        </div>
                      </div>
                  )}
                </div>
                <div className="modal-footer" style={{ justifyContent: 'flex-end', display: 'flex', gap: '12px', marginTop: 'auto', paddingTop: '32px', flexShrink: 0 }}>
                  <button className="btn-outline" style={{ padding: '12px 32px', fontSize: '16px' }} onClick={closeModal} disabled={isSubmitting}>취소</button>
                  <button className="btn-primary" style={{ padding: '12px 32px', fontSize: '16px' }} onClick={handleSubmitMaterial} disabled={isSubmitting}>
                    {isSubmitting ? '저장 중...' : '저장'}
                  </button>
                </div>
              </div>
            </div>
        )}

        {/* 학습일지 모달 */}
        {selectedJournal && (
            <div className="modal-overlay">
              <div className="glass-panel modal-content" style={{ maxWidth: '1100px', width: '90%', height: '85vh', padding: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
                <div className="modal-header" style={{ padding: '24px 32px', borderBottom: '1px solid var(--color-border)', margin: 0, flexShrink: 0 }}>
                  <h3 style={{ margin: 0, fontSize: '22px' }}>{selectedJournal.title}</h3>
                  <button className="btn-close" onClick={() => setSelectedJournal(null)}><X size={24} /></button>
                </div>

                <div className="modal-body" style={{ flex: 1, display: 'flex', overflow: 'hidden', padding: 0 }}>
                  {/* 왼쪽: 내용 / 수정폼 */}
                  <div style={{ flex: 1, padding: '32px', overflowY: 'auto', borderRight: '1px solid var(--color-border)' }}>
                    {isJournalEditMode ? (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', height: '100%' }}>
                          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px' }}>
                            <div>
                              <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>제목</label>
                              <input type="text" className="input-field" value={editTitle} onChange={(e) => setEditTitle(e.target.value)} style={{ width: '100%', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
                            </div>
                            <div>
                              <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>날짜</label>
                              <input type="text" className="input-field" value={editDate} disabled style={{ width: '100%', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F3F4F6', color: '#9CA3AF' }} />
                            </div>
                          </div>
                          <div>
                            <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>키워드</label>
                            <input type="text" className="input-field" value={editKeywords} onChange={(e) => setEditKeywords(e.target.value)} style={{ width: '100%', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
                          </div>
                          <div>
                            <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>학습 내용</label>
                            <textarea className="input-field" value={editContent} onChange={(e) => setEditContent(e.target.value)} style={{ width: '100%', minHeight: '120px', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', resize: 'vertical', backgroundColor: '#F9FAFB', color: 'var(--color-text-main)', fontFamily: 'inherit', lineHeight: '1.5' }} />
                          </div>
                          <div>
                            <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>다음 학습 계획</label>
                            <textarea className="input-field" value={editNextPlan} onChange={(e) => setEditNextPlan(e.target.value)} style={{ width: '100%', minHeight: '80px', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', resize: 'vertical', backgroundColor: '#F9FAFB', color: 'var(--color-text-main)', fontFamily: 'inherit', lineHeight: '1.5' }} />
                          </div>
                          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px', marginTop: 'auto', paddingTop: '12px' }}>
                            <button className="btn-outline" style={{ padding: '10px 24px', width: 'auto' }} onClick={() => setIsJournalEditMode(false)}>취소</button>
                            <button className="btn-primary" style={{ padding: '10px 24px', width: 'auto' }} onClick={handleUpdateJournal}>저장하기</button>
                          </div>
                        </div>
                    ) : (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px', height: '100%' }}>
                          <div>
                            <span style={{ color: 'var(--color-text-muted)', fontSize: '14px' }}>{selectedJournal.date} • {selectedJournal.tag}</span>
                          </div>
                          <div>
                            <h4 style={{ margin: '0 0 8px', fontSize: '15px', color: 'var(--color-text-muted)' }}>키워드</h4>
                            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px' }}>
                              {selectedJournal.keywords.map(kw => <span key={kw} className="tag">#{kw}</span>)}
                            </div>
                          </div>
                          <div>
                            <h4 style={{ margin: '0 0 8px', fontSize: '15px', color: 'var(--color-text-muted)' }}>학습 내용</h4>
                            <p style={{ margin: 0, lineHeight: 1.6, whiteSpace: 'pre-wrap', color: 'var(--color-text-main)' }}>{selectedJournal.content}</p>
                          </div>
                          <div>
                            <h4 style={{ margin: '0 0 8px', fontSize: '15px', color: 'var(--color-text-muted)' }}>다음 학습 계획</h4>
                            <p style={{ margin: 0, lineHeight: 1.6, whiteSpace: 'pre-wrap', color: 'var(--color-text-main)' }}>{selectedJournal.nextPlan}</p>
                          </div>
                          <div style={{ marginTop: 'auto', paddingTop: '16px', display: 'flex', gap: '12px' }}>
                            <button className="btn-outline" style={{ flex: 1, padding: '12px', fontWeight: 'bold', color: '#EF4444', borderColor: '#FCA5A5' }} onClick={handleDeleteJournal}>삭제하기</button>
                            <button className="btn-outline" style={{ flex: 1, padding: '12px', fontWeight: 'bold' }} onClick={() => setIsJournalEditMode(true)}>수정하기</button>
                          </div>
                        </div>
                    )}
                  </div>

                  {/* 오른쪽: 요약 & 피드백 */}
                  <div style={{ flex: 1, padding: '32px', overflowY: 'auto', backgroundColor: 'var(--color-bg-base)' }}>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                      <div className="glass-panel" style={{ padding: '24px' }}>
                        <h3 style={{ margin: '0 0 16px', fontSize: '18px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <AlignLeft size={18} color="var(--color-primary)" /> AI 요약
                        </h3>
                        <p style={{ margin: 0, fontSize: '15px', lineHeight: '1.6', color: 'var(--color-text-main)' }}>
                          {journalSummary}
                        </p>
                      </div>

                      <div className="glass-panel" style={{ padding: '24px' }}>
                        <h3 style={{ margin: '0 0 16px', fontSize: '18px', display: 'flex', alignItems: 'center', gap: '8px' }}>
                          <MessageSquare size={18} color="var(--color-primary)" /> AI 피드백
                        </h3>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                          {journalFeedback.map((fb, idx) => (
                              <div key={idx} style={{ display: 'flex', gap: '12px', alignItems: 'flex-start' }}>
                                <div style={{ width: '24px', height: '24px', borderRadius: '50%', backgroundColor: 'var(--color-primary)', color: 'white', display: 'flex', justifyContent: 'center', alignItems: 'center', fontSize: '12px', fontWeight: 'bold', flexShrink: 0 }}>
                                  {idx + 1}
                                </div>
                                <p style={{ margin: 0, fontSize: '14px', lineHeight: '1.5', color: 'var(--color-text-main)' }}>
                                  {fb}
                                </p>
                              </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
        )}
      </div>
  );
}