import React, { useState } from 'react';
import { FileText, File as FileIcon, Plus, X, Download, Send, CheckCircle2, Circle, Map, AlignLeft, HelpCircle, MessageSquare } from 'lucide-react';

export default function Archive() {
  const [activeTab, setActiveTab] = useState('journal');
  const [isRoadmapVisible, setIsRoadmapVisible] = useState(false);
  const [isJournalDetailVisible, setIsJournalDetailVisible] = useState(false);
  const [openedModalType, setOpenedModalType] = useState(null); // 'aiFeedback', 'pdfSummary', 'pdfQuiz', 'pdfChat', 'addMaterial'
  const [selectedItem, setSelectedItem] = useState(null);
  const [selectedJournal, setSelectedJournal] = useState(null);
  
  // 자료 추가 모달에서의 유형 상태 ('journal', 'syllabus', 'pdf')
  const [addMaterialType, setAddMaterialType] = useState('journal');
  
  // 채팅 입력창 (PDF Chat Modal용)
  const [chatInput, setChatInput] = useState('');

  // 표시할 카드 개수 관리 (더보기 기능)
  const [visibleCount, setVisibleCount] = useState(6);

  // ---------------- 더미 데이터 ----------------
  const journals = [
    { id: 1, title: '알고리즘 학습일지', date: '2026.03.28', tag: '학습일지', description: 'BFS/DFS 탐색 알고리즘 복습 및 백준 10문제 풀이. 다익스트라 구현에서 힙 자료구조 활용이 핵심임을 파악했다.', stats: { time: '2h 30m', solved: 10, score: '85%' }, keywords: ['BFS', 'DFS', '다익스트라', '힙 자료구조', '최단경로'], content: '기본적인 탐색에서부터 최단경로 알고리즘까지 전반적으로 복습했다. 특히 우선순위 큐를 활용한 다익스트라 구현이 아직 익숙하지 않아 집중적으로 훈련함.', nextPlan: '벨만-포드 알고리즘과 플로이드-워셜 알고리즘 정리' },
    { id: 2, title: '데이터베이스 정규화 복습', date: '2026.03.29', tag: '학습일지', description: '1NF~BCNF까지 정규화 단계별 조건 정리. 함수 종속성과 후보키 개념이 핵심임을 재확인했다.', stats: { time: '1h 45m', solved: 0, score: '90%' }, keywords: ['정규화', '1NF', 'BCNF', '함수 종속성', '후보키'], content: '데이터의 중복을 줄이고 무결성을 유지하기 위한 정규화 과정을 단계별로 정리함. 부분 함수 종속과 이행적 함수 종속의 차이를 명확히 구분할 수 있게 되었다.', nextPlan: '트랜잭션(Transaction) 특징과 격리 수준(Isolation Level) 정리' },
    { id: 3, title: 'React 상태관리 정리', date: '2026.03.30', tag: '학습일지', description: 'useState / useReducer / Context API 비교 정리. 전역 상태에는 Zustand가 가볍고 편리함을 학습했다.', stats: { time: '3h 10m', solved: 2, score: '80%' }, keywords: ['React', '상태관리', 'Context API', 'Zustand', 'useReducer'], content: '리액트의 기본적인 상태관리 훅들을 복습하고, Context API의 불필요한 렌더링 문제를 해결하기 위해 Zustand를 도입해보았다. 보일러플레이트가 적어 매우 편리했다.', nextPlan: 'Zustand와 React Query를 조합한 비동기 상태관리 학습' },
    { id: 4, title: '운영체제 프로세스와 스레드', date: '2026.04.01', tag: '학습일지', description: '프로세스 문맥 교환과 스레드의 메모리 공유 특성을 학습. 데드락 발생 조건 4가지 정리.', stats: { time: '2h 00m', solved: 5, score: '88%' }, keywords: ['OS', '프로세스', '스레드', '데드락', '문맥교환'], content: '멀티 프로세스와 멀티 스레드의 차이를 비교 분석함. 특히 공유 자원 접근 시 발생하는 데드락의 4가지 필요충분조건을 명확히 이해함.', nextPlan: '세마포어와 뮤텍스의 차이점 실습' },
    { id: 5, title: 'Spring Boot JPA 영속성 컨텍스트', date: '2026.04.03', tag: '학습일지', description: 'JPA의 1차 캐시, 동일성 보장, 트랜잭션을 지원하는 쓰기 지연, 변경 감지, 지연 로딩 개념 학습.', stats: { time: '4h 20m', solved: 0, score: '95%' }, keywords: ['Spring', 'JPA', '영속성 컨텍스트', '변경 감지', '지연 로딩'], content: '엔티티 매니저와 영속성 컨텍스트의 생명주기를 테스트 코드로 검증함. 쿼리가 날아가는 시점을 정확히 파악할 수 있게 됨.', nextPlan: 'JPQL과 QueryDSL 기본 문법 학습' },
    { id: 6, title: '네트워크 TCP/IP 4계층', date: '2026.04.05', tag: '학습일지', description: 'OSI 7계층과 TCP/IP 4계층 매핑. TCP 3-way handshake 과정 패킷 캡처로 확인.', stats: { time: '1h 50m', solved: 3, score: '82%' }, keywords: ['네트워크', 'TCP', 'IP', 'Handshake', 'OSI7'], content: 'Wireshark를 활용해 실제 웹 통신 시 발생하는 패킷을 분석함. SYN, ACK 플래그의 역할을 눈으로 확인하니 이해가 쉬움.', nextPlan: 'UDP의 특징과 사용 사례 정리' },
    { id: 7, title: '자바 디자인 패턴: 싱글톤 & 팩토리', date: '2026.04.08', tag: '학습일지', description: '멀티스레드 환경에서 안전한 싱글톤 패턴 구현 방법(Bill Pugh)과 팩토리 메서드 패턴의 장점 정리.', stats: { time: '2h 40m', solved: 2, score: '89%' }, keywords: ['Java', '디자인 패턴', '싱글톤', '팩토리', '객체지향'], content: '다양한 싱글톤 구현 방식을 비교하고, 왜 내부 정적 클래스 방식이 권장되는지 메모리 로드 시점을 통해 이해함.', nextPlan: '전략 패턴과 옵저버 패턴 학습' },
    { id: 8, title: 'AWS EC2 배포 실습', date: '2026.04.10', tag: '학습일지', description: 'EC2 인스턴스 생성, 탄력적 IP 연결, 보안 그룹 설정 및 터미널 접속 완료. 무중단 배포의 필요성 체감.', stats: { time: '3h 30m', solved: 0, score: '75%' }, keywords: ['AWS', 'EC2', '배포', '보안그룹', 'Linux'], content: '처음으로 클라우드 서버를 띄워봄. 권한 설정 문제로 SSH 접속에 애를 먹었으나 pem 키 권한 수정(chmod 400)으로 해결함.', nextPlan: 'Docker를 활용한 배포 컨테이너화' },
    { id: 9, title: '코딩테스트: 동적 계획법(DP) 기본', date: '2026.04.12', tag: '학습일지', description: '피보나치, 배낭 문제(Knapsack) 등 전형적인 DP 문제 5개 풀이. 점화식 도출 연습 집중.', stats: { time: '3h 15m', solved: 5, score: '92%' }, keywords: ['알고리즘', 'DP', '코딩테스트', '배낭문제', '점화식'], content: '상태를 어떻게 정의할 것인지, 기저 조건(Base case)은 무엇인지 파악하는 것이 DP의 핵심임을 깨달음.', nextPlan: '2차원 DP 및 LIS 문제 유형 풀이' },
    { id: 10, title: '프로젝트 리팩토링 및 성능 최적화', date: '2026.04.15', tag: '학습일지', description: 'React 컴포넌트 렌더링 최적화(React.memo, useMemo) 및 DB 인덱스 추가로 조회 속도 3배 향상.', stats: { time: '5h 00m', solved: 0, score: '98%' }, keywords: ['리팩토링', '최적화', '인덱스', 'useMemo', '성능향상'], content: 'N+1 문제를 fetch join으로 해결하고, 프론트엔드에서는 불필요한 렌더링 트리를 잘라내어 체감 속도를 크게 높임.', nextPlan: 'Lighthouse를 활용한 웹 성능 지표 분석' }
  ];

  const pdfs = [
    { id: 1, title: '대학 원격교육 실태 및 만족도 조사.pdf', date: '2026.04.01', tag: '강의계획서' },
    { id: 2, title: '데이터통신_1주차_강의자료.pdf', date: '2026.04.05', tag: '학습PDF' },
    { id: 3, title: 'Spring_Security_Architecture.pdf', date: '2026.04.10', tag: '학습PDF' },
    { id: 4, title: '2026년도_1학기_졸업프로젝트_운영계획안.pdf', date: '2026.04.11', tag: '강의계획서' },
    { id: 5, title: '운영체제_중간고사_요약본.pdf', date: '2026.04.14', tag: '학습PDF' },
    { id: 6, title: 'React_Hooks_Deep_Dive.pdf', date: '2026.04.16', tag: '학습PDF' },
    { id: 7, title: '소프트웨어공학_객체지향분석설계.pdf', date: '2026.04.18', tag: '강의계획서' },
    { id: 8, title: 'AWS_Certified_Solutions_Architect_Guide.pdf', date: '2026.04.20', tag: '학습PDF' },
    { id: 9, title: '인공지능_개론_3장_머신러닝기초.pdf', date: '2026.04.22', tag: '강의계획서' },
    { id: 10, title: '디자인패턴_GoF_요약.pdf', date: '2026.04.25', tag: '학습PDF' },
    { id: 11, title: '알고리즘_기출문제_해설집.pdf', date: '2026.04.28', tag: '학습PDF' }
  ];

  const roadmapData = [
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
  ];

  const getNodeColor = (week) => {
    if (week === 7) return '#F59E0B'; // Orange
    if ([3, 4, 8, 9].includes(week)) return '#06B6D4'; // Cyan
    return '#10B981'; // Green
  };

  // ---------------- 핸들러 ----------------
  const handleTabChange = (tab) => {
    setActiveTab(tab);
    setIsRoadmapVisible(false);
    setIsJournalDetailVisible(false);
    setVisibleCount(6); // 탭 변경 시 더보기 초기화
  };

  const handleOpenJournalDetail = (journal) => {
    setSelectedJournal(journal);
    setIsJournalDetailVisible(true);
    setTimeout(() => {
      document.getElementById('journal-detail-section')?.scrollIntoView({ behavior: 'smooth' });
    }, 100);
  };

  const openModal = (type, item) => {
    setSelectedItem(item);
    setOpenedModalType(type);
    if (type === 'addMaterial') {
      setAddMaterialType('journal');
    }
  };

  const closeModal = () => {
    setOpenedModalType(null);
    setSelectedItem(null);
  };

  const handleGenerateRoadmap = () => {
    setIsRoadmapVisible(true);
    // 스크롤 이동용으로 timeout 설정
    setTimeout(() => {
      document.getElementById('roadmap-section')?.scrollIntoView({ behavior: 'smooth' });
    }, 100);
  };

  return (
    <div className="container-main archive-page">
      {/* 1. 상단 헤더 구조 변경 (컨트롤 바) */}
      <div className="archive-control-bar">
        <div className="archive-tabs">
          <button 
            className={`archive-tab ${activeTab === 'journal' ? 'active' : ''}`}
            onClick={() => handleTabChange('journal')}
          >
            학습일지
          </button>
          <button 
            className={`archive-tab ${activeTab === 'pdf' ? 'active' : ''}`}
            onClick={() => handleTabChange('pdf')}
          >
            강의계획서 / 학습 PDF
          </button>
        </div>
        <button className="btn-primary btn-add-material" onClick={() => openModal('addMaterial', null)}>
          <Plus size={16} /> 자료 추가
        </button>
      </div>

      {/* 2. 카드 목록 영역 */}
      <div className="archive-grid">
        {activeTab === 'journal' && journals.slice(0, visibleCount).map((journal) => (
          <div key={journal.id} className="glass-panel archive-card animate-fade-in">
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
            <div className="card-actions">
              <button className="btn-outline" onClick={() => handleOpenJournalDetail(journal)}>자세히 보기</button>
              <button className="btn-primary" onClick={() => openModal('aiFeedback', journal)}>AI 피드백 받기</button>
            </div>
          </div>
        ))}

        {activeTab === 'pdf' && pdfs.slice(0, visibleCount).map((pdf) => (
          <div key={pdf.id} className="glass-panel archive-card animate-fade-in">
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
            {/* PDF 카드 버튼들 (2x2 그리드) */}
            <div className="card-actions pdf-actions-grid">
              <button className="btn-soft-primary" onClick={handleGenerateRoadmap}>
                <Map size={14} /> AI 로드맵
              </button>
              <button className="btn-soft-gray" onClick={() => openModal('pdfSummary', pdf)}>
                <AlignLeft size={14} /> 요약
              </button>
              <button className="btn-soft-gray" onClick={() => openModal('pdfQuiz', pdf)}>
                <HelpCircle size={14} /> 문제 생성
              </button>
              <button className="btn-primary" onClick={() => openModal('pdfChat', pdf)} style={{ border: 'none' }}>
                <MessageSquare size={14} /> AI 질문
              </button>
            </div>
          </div>
        ))}
      </div>

      {/* 3. 더보기(Load More) 버튼 */}
      {((activeTab === 'journal' && visibleCount < journals.length) || 
        (activeTab === 'pdf' && visibleCount < pdfs.length)) && (
        <div style={{ display: 'flex', justifyContent: 'center', marginTop: '40px' }}>
          <button 
            className="btn-outline" 
            style={{ width: 'max-content', flex: 'none', padding: '12px 32px', borderRadius: '30px', fontWeight: '600', backgroundColor: 'white', border: '1px solid var(--color-border)', boxShadow: '0 2px 4px rgba(0,0,0,0.05)' }}
            onClick={() => setVisibleCount(prev => prev + 6)}
          >
            + 더보기 ({(activeTab === 'journal' ? visibleCount : visibleCount)}/{(activeTab === 'journal' ? journals.length : pdfs.length)})
          </button>
        </div>
      )}

      {/* 4. 학습일지 상세/수정 영역 */}
      {activeTab === 'journal' && isJournalDetailVisible && selectedJournal && (
        <div id="journal-detail-section" className="roadmap-section animate-fade-in" style={{ marginBottom: '60px' }}>
          <div className="glass-panel" style={{ padding: '32px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '24px' }}>
              <div>
                <h2 style={{ margin: '0 0 8px', color: 'var(--color-text-main)' }}>학습일지 상세 및 수정</h2>
                <p style={{ margin: 0, color: 'var(--color-text-muted)', fontSize: '14px' }}>학습일지 내용을 확인하고 수정할 수 있습니다.</p>
              </div>
              <button className="btn-close" onClick={() => setIsJournalDetailVisible(false)}><X size={24} /></button>
            </div>
            
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '20px', marginBottom: '20px' }}>
              <div>
                <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>제목</label>
                <input type="text" className="input-field" defaultValue={selectedJournal.title} style={{ width: '100%', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
              </div>
              <div>
                <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>날짜</label>
                <input type="text" className="input-field" defaultValue={selectedJournal.date} style={{ width: '100%', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
              </div>
            </div>

            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>통계 (학습 시간 / 푼 문제 수 / 자기평가)</label>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px' }}>
                <input type="text" className="input-field" defaultValue={selectedJournal.stats.time} placeholder="학습 시간 (예: 2h 30m)" style={{ padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
                <input type="number" className="input-field" defaultValue={selectedJournal.stats.solved} placeholder="푼 문제 수" style={{ padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
                <input type="text" className="input-field" defaultValue={selectedJournal.stats.score} placeholder="자기평가 (예: 85%)" style={{ padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
              </div>
            </div>

            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>핵심 키워드 (쉼표로 구분)</label>
              <input type="text" className="input-field" defaultValue={selectedJournal.keywords.join(', ')} style={{ width: '100%', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
            </div>

            <div style={{ marginBottom: '20px' }}>
              <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>학습 내용</label>
              <textarea className="input-field" defaultValue={selectedJournal.content} style={{ width: '100%', minHeight: '120px', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', resize: 'vertical', backgroundColor: '#F9FAFB', fontFamily: 'inherit', lineHeight: '1.5' }} />
            </div>

            <div style={{ marginBottom: '24px' }}>
              <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>다음 학습 계획</label>
              <textarea className="input-field" defaultValue={selectedJournal.nextPlan} style={{ width: '100%', minHeight: '80px', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', resize: 'vertical', backgroundColor: '#F9FAFB', fontFamily: 'inherit', lineHeight: '1.5' }} />
            </div>

            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
              <button className="btn-outline" style={{ padding: '10px 24px' }} onClick={() => setIsJournalDetailVisible(false)}>취소</button>
              <button className="btn-primary" style={{ padding: '10px 24px' }} onClick={() => { alert('성공적으로 수정되었습니다.'); setIsJournalDetailVisible(false); }}>저장하기</button>
            </div>
          </div>
        </div>
      )}

      {/* 5. 로드맵 영역 */}
      {activeTab === 'pdf' && isRoadmapVisible && (
        <div id="roadmap-section" className="roadmap-section animate-fade-in">
          <div className="glass-panel" style={{ padding: '24px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
              <h2 style={{ margin: 0, color: 'var(--color-primary)' }}>AI 학습 로드맵</h2>
              <button className="btn-outline" style={{ display: 'inline-flex', width: 'max-content', flex: 'none', alignItems: 'center', gap: '6px', height: '32px', fontSize: '13px', padding: '0 12px' }}>
                <Download size={14} /> 다운로드
              </button>
            </div>
            <p style={{ color: 'var(--color-text-muted)', marginBottom: '24px' }}>
              업로드한 강의계획서를 기반으로 주차별 학습 계획을 생성했습니다.
            </p>

            <div className="roadmap-visual">
              <div className="roadmap-row">
                {roadmapData.slice(0, 6).map((item, idx) => (
                  <React.Fragment key={item.week}>
                    <div className="roadmap-visual-node">
                      <div className="node-circle" style={{ backgroundColor: getNodeColor(item.week) }}>{item.week}주</div>
                      <div className="node-title">{item.topic}</div>
                    </div>
                    {idx < 5 && <div className="node-arrow">&gt;</div>}
                  </React.Fragment>
                ))}
              </div>
              <div className="roadmap-row reverse">
                {roadmapData.slice(6, 12).reverse().map((item, idx) => (
                  <React.Fragment key={item.week}>
                    <div className="roadmap-visual-node">
                      <div className="node-circle" style={{ backgroundColor: getNodeColor(item.week) }}>{item.week}주</div>
                      <div className="node-title">{item.topic}</div>
                    </div>
                    {idx < 5 && <div className="node-arrow">&lt;</div>}
                  </React.Fragment>
                ))}
              </div>
            </div>

            <h3 className="timeline-title">주차별 세부 계획</h3>
            <div className="roadmap-timeline">
              {roadmapData.map((item, idx) => (
                <div key={item.week} className="timeline-item">
                  <div className="timeline-left">
                    <div className="timeline-circle" style={{ backgroundColor: getNodeColor(item.week) }}>{item.week}</div>
                    {idx < roadmapData.length - 1 && <div className="timeline-line"></div>}
                  </div>
                  <div className="timeline-card glass-panel" style={{ borderLeftColor: getNodeColor(item.week) }}>
                    <h4 className="timeline-card-title">{item.topic}</h4>
                    <div className="timeline-card-info">
                      <span className="info-label">학습 목표</span> <span>{item.goal}</span>
                    </div>
                    <div className="timeline-card-info">
                      <span className="info-label">학습 활동</span> <span>{item.act}</span>
                    </div>
                    <div className="timeline-card-check">
                       <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer', width: 'fit-content' }}>
                         <input type="checkbox" checked={item.done} readOnly /> 완료
                       </label>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* ---------------- 모달 영역 ---------------- */}

      {/* AI 피드백 모달 */}
      {openedModalType === 'aiFeedback' && (
        <div className="modal-overlay">
          <div className="glass-panel modal-content" style={{ maxWidth: '800px', padding: '32px' }}>
            <div className="modal-header" style={{ marginBottom: '24px' }}>
              <h3 style={{ margin: 0, fontSize: '22px' }}>AI 피드백</h3>
              <button className="btn-close" onClick={closeModal}><X size={24} /></button>
            </div>
            <div className="modal-body">
              <p style={{ color: 'var(--color-text-muted)', fontSize: '15px', marginBottom: '24px' }}>
                AI가 분석한 학습일지 피드백입니다.
              </p>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                <div style={{ display: 'flex', gap: '16px', alignItems: 'flex-start' }}>
                  <div style={{ width: '28px', height: '28px', borderRadius: '50%', backgroundColor: 'var(--color-primary)', color: 'white', display: 'flex', justifyContent: 'center', alignItems: 'center', fontSize: '14px', fontWeight: 'bold', flexShrink: 0 }}>1</div>
                  <p style={{ margin: 0, fontSize: '16px', lineHeight: '1.6' }}>BFS/DFS 알고리즘에 대한 이해가 잘 정리되어 있습니다.</p>
                </div>
                <div style={{ display: 'flex', gap: '16px', alignItems: 'flex-start' }}>
                  <div style={{ width: '28px', height: '28px', borderRadius: '50%', backgroundColor: 'var(--color-primary)', color: 'white', display: 'flex', justifyContent: 'center', alignItems: 'center', fontSize: '14px', fontWeight: 'bold', flexShrink: 0 }}>2</div>
                  <p style={{ margin: 0, fontSize: '16px', lineHeight: '1.6' }}>더 심화 학습하려면 플로이드-워셜, 벨만-포드 알고리즘도 함께 정리하면 좋습니다.</p>
                </div>
                <div style={{ display: 'flex', gap: '16px', alignItems: 'flex-start' }}>
                  <div style={{ width: '28px', height: '28px', borderRadius: '50%', backgroundColor: 'var(--color-primary)', color: 'white', display: 'flex', justifyContent: 'center', alignItems: 'center', fontSize: '14px', fontWeight: 'bold', flexShrink: 0 }}>3</div>
                  <p style={{ margin: 0, fontSize: '16px', lineHeight: '1.6' }}>백준 10문제 풀이는 충분한 실습량입니다. 다음 단계로 다이나믹 프로그래밍을 권장합니다.</p>
                </div>
              </div>
            </div>
            <div className="modal-footer" style={{ justifyContent: 'flex-end', display: 'flex', marginTop: '32px' }}>
              <button className="btn-primary" style={{ padding: '12px 32px', fontSize: '16px' }} onClick={closeModal}>확인</button>
            </div>
          </div>
        </div>
      )}

      {/* 요약 생성 모달 */}
      {openedModalType === 'pdfSummary' && (
        <div className="modal-overlay">
          <div className="glass-panel modal-content" style={{ maxWidth: '900px', padding: '32px' }}>
            <div className="modal-header" style={{ marginBottom: '24px' }}>
              <h3 style={{ margin: 0, fontSize: '22px' }}>요약 생성</h3>
              <button className="btn-close" onClick={closeModal}><X size={24} /></button>
            </div>
            <div className="modal-body">
              <p style={{ color: 'var(--color-text-muted)', fontSize: '15px', marginBottom: '24px' }}>
                업로드된 PDF의 핵심 내용 5줄 요약입니다.
              </p>
              <ul style={{ paddingLeft: '24px', margin: 0, display: 'flex', flexDirection: 'column', gap: '16px', fontSize: '16px', lineHeight: '1.6' }}>
                <li>원격교육은 시공간 제약 없이 다양한 학습자에게 교육 기회를 제공하는 방식이다.</li>
                <li>LMS는 강의 콘텐츠 관리, 학습 이력 추적, 평가 기능을 통합 제공한다.</li>
                <li>원격수업 만족도에는 콘텐츠 품질, 상호작용 수준, 기술적 안정성이 영향을 미친다.</li>
                <li>자기주도 학습 역량은 온라인 학습 성과와 강한 관계가 있다.</li>
                <li>향후 원격교육은 AI 기반 개인화 학습과 결합될 가능성이 높다.</li>
              </ul>
            </div>
            <div className="modal-footer" style={{ justifyContent: 'flex-end', display: 'flex', marginTop: '32px' }}>
              <button className="btn-primary" style={{ padding: '12px 32px', fontSize: '16px' }} onClick={closeModal}>확인</button>
            </div>
          </div>
        </div>
      )}

      {/* 퀴즈 풀기 모달 */}
      {openedModalType === 'pdfQuiz' && (
        <div className="modal-overlay">
          <div className="glass-panel modal-content" style={{ maxWidth: '1000px', maxHeight: '85vh', display: 'flex', flexDirection: 'column', padding: '32px' }}>
            <div className="modal-header" style={{ flexShrink: 0, marginBottom: '24px' }}>
              <h3 style={{ margin: 0, fontSize: '22px' }}>퀴즈 풀기</h3>
              <button className="btn-close" onClick={closeModal}><X size={24} /></button>
            </div>
            <div className="modal-body" style={{ overflowY: 'auto', paddingRight: '24px', marginRight: '-8px' }}>
              <div className="quiz-container" style={{ display: 'flex', flexDirection: 'column', gap: '40px' }}>
                <div>
                  <h4 style={{ margin: '0 0 16px', fontSize: '18px' }}>Q1. 원격교육에서 LMS의 핵심 기능이 아닌 것은?</h4>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    <button className="btn-outline" style={{ width: '100%', height: 'auto', display: 'flex', alignItems: 'center', textAlign: 'left', fontWeight: 'normal', justifyContent: 'flex-start', fontSize: '16px', padding: '16px' }}>1) 강의 콘텐츠 업로드 및 관리</button>
                    <button className="btn-outline" style={{ width: '100%', height: 'auto', display: 'flex', alignItems: 'center', textAlign: 'left', fontWeight: 'normal', justifyContent: 'flex-start', backgroundColor: '#FEE2E2', borderColor: '#FCA5A5', color: '#991B1B', fontSize: '16px', padding: '16px' }}>2) 오프라인 강의실 자동 배정 (오답)</button>
                    <button className="btn-outline" style={{ width: '100%', height: 'auto', display: 'flex', alignItems: 'center', textAlign: 'left', fontWeight: 'normal', justifyContent: 'flex-start', fontSize: '16px', padding: '16px' }}>3) 학습자 성적 및 이력 관리</button>
                    <button className="btn-outline" style={{ width: '100%', height: 'auto', display: 'flex', alignItems: 'center', textAlign: 'left', fontWeight: 'normal', justifyContent: 'flex-start', fontSize: '16px', padding: '16px' }}>4) 과제 제출 및 피드백 시스템</button>
                  </div>
                </div>
                <div>
                  <h4 style={{ margin: '0 0 16px', fontSize: '18px' }}>Q2. 원격수업 만족도에 가장 큰 영향을 미치는 요인은?</h4>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    <button className="btn-outline" style={{ width: '100%', height: 'auto', display: 'flex', alignItems: 'center', textAlign: 'left', fontWeight: 'normal', justifyContent: 'flex-start', fontSize: '16px', padding: '16px' }}>1) 수강료</button>
                    <button className="btn-outline" style={{ width: '100%', height: 'auto', display: 'flex', alignItems: 'center', textAlign: 'left', fontWeight: 'normal', justifyContent: 'flex-start', fontSize: '16px', padding: '16px' }}>2) 강의 시간대</button>
                    <button className="btn-outline" style={{ width: '100%', height: 'auto', display: 'flex', alignItems: 'center', textAlign: 'left', fontWeight: 'normal', justifyContent: 'flex-start', backgroundColor: '#DCFCE7', borderColor: '#86EFAC', color: '#166534', fontSize: '16px', padding: '16px' }}>3) 콘텐츠 품질과 상호작용 (정답)</button>
                    <button className="btn-outline" style={{ width: '100%', height: 'auto', display: 'flex', alignItems: 'center', textAlign: 'left', fontWeight: 'normal', justifyContent: 'flex-start', fontSize: '16px', padding: '16px' }}>4) 인터넷 속도</button>
                  </div>
                </div>
                <div>
                  <h4 style={{ margin: '0 0 16px', fontSize: '18px' }}>Q3. 자기주도 학습에서 가장 중요한 역량은?</h4>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    <button className="btn-outline" style={{ width: '100%', height: 'auto', display: 'flex', alignItems: 'center', textAlign: 'left', fontWeight: 'normal', justifyContent: 'flex-start', fontSize: '16px', padding: '16px' }}>1) 목표 설정 및 자기 조절 능력</button>
                    <button className="btn-outline" style={{ width: '100%', height: 'auto', display: 'flex', alignItems: 'center', textAlign: 'left', fontWeight: 'normal', justifyContent: 'flex-start', fontSize: '16px', padding: '16px' }}>2) 타이핑 속도</button>
                    <button className="btn-outline" style={{ width: '100%', height: 'auto', display: 'flex', alignItems: 'center', textAlign: 'left', fontWeight: 'normal', justifyContent: 'flex-start', fontSize: '16px', padding: '16px' }}>3) 교수자 의존도</button>
                    <button className="btn-outline" style={{ width: '100%', height: 'auto', display: 'flex', alignItems: 'center', textAlign: 'left', fontWeight: 'normal', justifyContent: 'flex-start', fontSize: '16px', padding: '16px' }}>4) 수강 과목 수</button>
                  </div>
                </div>
              </div>
            </div>
            <div className="modal-footer" style={{ flexShrink: 0, justifyContent: 'flex-end', display: 'flex', marginTop: '24px' }}>
              <button className="btn-primary" style={{ padding: '12px 32px', fontSize: '16px' }} onClick={closeModal}>확인</button>
            </div>
          </div>
        </div>
      )}

      {/* AI 질문하기 모달 (채팅형) */}
      {openedModalType === 'pdfChat' && (
        <div className="modal-overlay">
          <div className="glass-panel modal-content" style={{ maxWidth: '1000px', height: '80vh', padding: 0, overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            <div className="modal-header" style={{ padding: '24px 32px', borderBottom: '1px solid var(--color-border)' }}>
              <h3 style={{ margin: 0, fontSize: '22px' }}>AI 질문하기</h3>
              <button className="btn-close" onClick={closeModal}><X size={24} /></button>
            </div>
            <div className="modal-body" style={{ flex: 1, padding: '32px', backgroundColor: '#F9FAFB', overflowY: 'auto' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
                <div style={{ alignSelf: 'flex-start', backgroundColor: 'white', padding: '16px 24px', borderRadius: '20px', borderTopLeftRadius: '4px', maxWidth: '80%', boxShadow: '0 1px 4px rgba(0,0,0,0.05)', fontSize: '16px', lineHeight: '1.6' }}>
                  안녕하세요. 업로드한 자료에 대해 궁금한 점을 질문해주세요.
                </div>
                <div style={{ alignSelf: 'flex-end', backgroundColor: 'var(--color-primary)', color: 'white', padding: '16px 24px', borderRadius: '20px', borderTopRightRadius: '4px', maxWidth: '80%', boxShadow: '0 1px 4px rgba(0,0,0,0.05)', fontSize: '16px', lineHeight: '1.6' }}>
                  원격교육에서 LMS가 왜 중요한지 설명해줘.
                </div>
                <div style={{ alignSelf: 'flex-start', backgroundColor: 'white', padding: '16px 24px', borderRadius: '20px', borderTopLeftRadius: '4px', maxWidth: '80%', boxShadow: '0 1px 4px rgba(0,0,0,0.05)', fontSize: '16px', lineHeight: '1.6' }}>
                  LMS는 원격교육의 핵심 인프라입니다. 강의 콘텐츠 배포, 진도 추적, 성적 관리를 한 곳에서 처리해 교수자와 학습자 모두의 부담을 줄여줍니다.
                </div>
              </div>
            </div>
            <div style={{ padding: '24px 32px', backgroundColor: 'white', borderTop: '1px solid var(--color-border)' }}>
              <form onSubmit={(e) => e.preventDefault()} style={{ display: 'flex', gap: '16px' }}>
                <input 
                  type="text" 
                  className="input-field" 
                  style={{ margin: 0, borderRadius: '30px', backgroundColor: '#F3F4F6', border: 'none', padding: '16px 24px', fontSize: '16px' }}
                  placeholder="자료 내용에 대해 궁금한 점을 입력하세요."
                  value={chatInput}
                  onChange={(e) => setChatInput(e.target.value)}
                />
                <button type="submit" className="btn-primary" style={{ width: '54px', height: '54px', borderRadius: '50%', padding: 0, flexShrink: 0, display: 'flex', justifyContent: 'center', alignItems: 'center' }}>
                  <Send size={24} />
                </button>
              </form>
            </div>
          </div>
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
                      <input type="text" className="input-field" placeholder="학습일지 제목" style={{ width: '100%', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
                    </div>
                    <div>
                      <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>날짜</label>
                      <input type="date" className="input-field" style={{ width: '100%', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
                    </div>
                  </div>

                  <div>
                    <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>통계 (학습 시간 / 푼 문제 수 / 자기평가)</label>
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '16px' }}>
                      <input type="text" className="input-field" placeholder="학습 시간 (예: 2h 30m)" style={{ padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
                      <input type="number" className="input-field" placeholder="푼 문제 수" style={{ padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
                      <input type="text" className="input-field" placeholder="자기평가 (예: 85%)" style={{ padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
                    </div>
                  </div>

                  <div>
                    <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>핵심 키워드 (쉼표로 구분)</label>
                    <input type="text" className="input-field" placeholder="키워드 입력" style={{ width: '100%', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
                  </div>

                  <div>
                    <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>학습 내용</label>
                    <textarea className="input-field" placeholder="학습한 내용을 상세히 작성하세요." style={{ width: '100%', minHeight: '120px', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', resize: 'vertical', backgroundColor: '#F9FAFB', fontFamily: 'inherit', lineHeight: '1.5' }} />
                  </div>

                  <div>
                    <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>다음 학습 계획</label>
                    <textarea className="input-field" placeholder="다음에 학습할 내용을 작성하세요." style={{ width: '100%', minHeight: '80px', padding: '12px', borderRadius: '8px', border: '1px solid var(--color-border)', resize: 'vertical', backgroundColor: '#F9FAFB', fontFamily: 'inherit', lineHeight: '1.5' }} />
                  </div>
                </div>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', flex: 1 }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '16px', fontWeight: 'bold', marginBottom: '12px' }}>제목</label>
                    <input type="text" className="input-field" placeholder="자료의 제목을 입력하세요" style={{ width: '100%', fontSize: '16px', padding: '16px', borderRadius: '8px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }} />
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', flex: 1 }}>
                    <label style={{ display: 'block', fontSize: '16px', fontWeight: 'bold', marginBottom: '12px' }}>파일 업로드</label>
                    <div style={{ flex: 1, border: '2px dashed var(--color-border)', borderRadius: '12px', padding: '40px', display: 'flex', flexDirection: 'column', justifyContent: 'center', alignItems: 'center', textAlign: 'center', color: 'var(--color-text-muted)', backgroundColor: '#F9FAFB', cursor: 'pointer', transition: 'all 0.2s', minHeight: '200px' }}>
                      <FileIcon size={48} style={{ margin: '0 auto 16px', opacity: 0.5 }} />
                      <p style={{ margin: '0 0 12px', fontSize: '16px', fontWeight: 'bold' }}>클릭하거나 파일을 드래그하여 업로드하세요</p>
                      <p style={{ margin: 0, fontSize: '14px' }}>지원 형식: PDF, DOCX, TXT</p>
                    </div>
                  </div>
                </div>
              )}
            </div>
            <div className="modal-footer" style={{ justifyContent: 'flex-end', display: 'flex', gap: '12px', marginTop: 'auto', paddingTop: '32px', flexShrink: 0 }}>
              <button className="btn-outline" style={{ padding: '12px 32px', fontSize: '16px' }} onClick={closeModal}>취소</button>
              <button className="btn-primary" style={{ padding: '12px 32px', fontSize: '16px' }} onClick={() => { alert('등록되었습니다.'); closeModal(); }}>저장</button>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
