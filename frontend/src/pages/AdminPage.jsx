import React, { useState } from 'react';
import { ShieldAlert, MessageCircle, X, CheckCircle, AlertTriangle, Ban, LogOut } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import { useNavigate } from 'react-router-dom';

export default function AdminPage() {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const [inquiries, setInquiries] = useState([
    { id: 1, author: '김철수', type: '버그 및 오류신고', title: '강의계획서 업로드 오류', content: 'PDF 파일을 올리는데 계속 실패합니다. 확인 부탁드려요.', date: '2026-05-20', status: '대기중', reply: '' },
    { id: 2, author: '이영희', type: '이용문의', title: '비밀번호 초기화 메일 안옴', content: '비밀번호 재설정 메일이 오지 않습니다.', date: '2026-05-21', status: '답변완료', reply: '스팸 메일함을 확인해주세요. 그래도 없으면 고객센터로 전화주세요.' },
  ]);

  const [reports, setReports] = useState([
    { id: 1, reporter: '홍길동', reportedUser: '악플러123', reason: '욕설/비방', content: '게시판에서 계속 욕설을 합니다.', date: '2026-05-21', status: '대기중', adminNote: '', pastReports: [{ date: '2026-04-10', reason: '도배', result: '경고 조치' }, { date: '2026-05-01', reason: '욕설/비방', result: '3일 정지' }] },
    { id: 2, reporter: '김철수', reportedUser: '광고봇99', reason: '스팸/도배', content: '불법 광고 링크를 계속 올립니다.', date: '2026-05-22', status: '대기중', adminNote: '', pastReports: [] },
    { id: 3, reporter: '이영희', reportedUser: '어그로꾼', reason: '욕설/비방', content: '채팅방 분위기를 계속 흐립니다.', date: '2026-05-23', status: '대기중', adminNote: '', pastReports: [{ date: '2025-12-01', reason: '운영원칙 위배', result: '30일 정지' }, { date: '2026-02-15', reason: '광고', result: '7일 정지' }] },
  ]);

  const [activeAdminTab, setActiveAdminTab] = useState('inquiries');

  // 아코디언 상태
  const [expandedInquiryId, setExpandedInquiryId] = useState(null);
  const [replyContent, setReplyContent] = useState('');

  const [expandedReportId, setExpandedReportId] = useState(null);
  const [suspendReason, setSuspendReason] = useState('바람직하지 않은 활동 (광고, 도배, 욕설, 비방 등)');
  const [suspendReasonOther, setSuspendReasonOther] = useState('');
  const [suspendDuration, setSuspendDuration] = useState('7일');
  const [adminNote, setAdminNote] = useState('');
  const [showSuspensionMockup, setShowSuspensionMockup] = useState(false);

  const handleReplyInquiry = (id) => {
    if (!replyContent.trim()) {
      alert('답변 내용을 입력해주세요.');
      return;
    }
    setInquiries(inquiries.map(inq => 
      inq.id === id ? { ...inq, status: '답변완료', reply: replyContent } : inq
    ));
    setExpandedInquiryId(null);
    setReplyContent('');
    alert('답변이 등록되었습니다.');
  };

  const handleSuspendUser = (id) => {
    const finalReason = suspendReason === '기타' ? (suspendReasonOther || '기타') : suspendReason;
    const notePrefix = suspendDuration === '경고' ? '[경고 조치]' : `[${suspendDuration} 정지]`;
    setReports(reports.map(rep => 
      rep.id === id ? { ...rep, status: '처리완료', adminNote: `${notePrefix} ${finalReason}` } : rep
    ));
    setExpandedReportId(null);
    setSuspendDuration('7일');
    setSuspendReason('바람직하지 않은 활동 (광고, 도배, 욕설, 비방 등)');
    setSuspendReasonOther('');
    setAdminNote('');
    const actionText = suspendDuration === '경고' ? '경고 처리' : '활동 정지';
    alert(`해당 멤버를 ${actionText}했습니다.`);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', width: '100%', height: '100vh', backgroundColor: '#F3F4F6' }} className="animate-fade-in">
      {/* Topbar */}
      <div style={{ width: '100%', height: '70px', backgroundColor: '#111827', color: 'white', display: 'flex', alignItems: 'center', padding: '0 32px', flexShrink: 0, boxShadow: '0 4px 10px rgba(0,0,0,0.1)', zIndex: 10, boxSizing: 'border-box' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginRight: '60px' }}>
          <ShieldAlert size={28} color="#10B981" />
          <div style={{ display: 'flex', flexDirection: 'column' }}>
            <h2 style={{ margin: 0, color: 'white', fontSize: '20px', lineHeight: '1.2' }}>StudyBridge</h2>
            <span style={{ color: '#9CA3AF', fontSize: '11px', fontWeight: 'bold', letterSpacing: '1px' }}>ADMIN PORTAL</span>
          </div>
        </div>

        <nav style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 1 }}>
          <button 
            style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 16px', borderRadius: '8px', cursor: 'pointer', border: 'none', backgroundColor: activeAdminTab === 'inquiries' ? '#1F2937' : 'transparent', color: activeAdminTab === 'inquiries' ? '#10B981' : '#9CA3AF', fontWeight: activeAdminTab === 'inquiries' ? 'bold' : 'normal', transition: 'all 0.2s', fontSize: '15px' }}
            onClick={() => setActiveAdminTab('inquiries')}
          >
            <MessageCircle size={18} /> 1:1 문의 관리
          </button>
          <button 
            style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 16px', borderRadius: '8px', cursor: 'pointer', border: 'none', backgroundColor: activeAdminTab === 'reports' ? '#1F2937' : 'transparent', color: activeAdminTab === 'reports' ? '#EF4444' : '#9CA3AF', fontWeight: activeAdminTab === 'reports' ? 'bold' : 'normal', transition: 'all 0.2s', fontSize: '15px' }}
            onClick={() => setActiveAdminTab('reports')}
          >
            <AlertTriangle size={18} /> 신고 내역 관리
          </button>
        </nav>

        <div>
          <button 
            style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 16px', borderRadius: '8px', cursor: 'pointer', border: 'none', backgroundColor: '#10B981', color: 'white', transition: 'all 0.2s', fontWeight: 'bold', fontSize: '14px' }}
            onClick={() => {
              logout();
              navigate('/');
            }}
          >
            <LogOut size={16} /> 로그아웃
          </button>
        </div>
      </div>

      {/* Main Content Area */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '40px', boxSizing: 'border-box' }}>
        <div style={{ width: '100%', margin: '0 auto' }}>

          <div style={{ padding: '30px', backgroundColor: 'white', border: '1px solid #E5E7EB', borderRadius: '16px', boxShadow: '0 4px 6px -1px rgba(0, 0, 0, 0.05)' }}>
            {activeAdminTab === 'inquiries' && (
          <div>
            {inquiries.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '40px', color: 'var(--color-text-muted)' }}>등록된 문의가 없습니다.</div>
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                <thead>
                  <tr style={{ borderBottom: '2px solid #E5E7EB', color: '#6B7280', fontSize: '14px' }}>
                    <th style={{ padding: '16px 8px', width: '60px', textAlign: 'center' }}>No.</th>
                    <th style={{ padding: '16px 8px', width: '150px' }}>유형</th>
                    <th style={{ padding: '16px 8px' }}>제목</th>
                    <th style={{ padding: '16px 8px', width: '120px' }}>작성자</th>
                    <th style={{ padding: '16px 8px', width: '120px' }}>작성일</th>
                    <th style={{ padding: '16px 8px', width: '100px', textAlign: 'center' }}>상태</th>
                  </tr>
                </thead>
                <tbody>
                  {inquiries.map(inq => (
                    <React.Fragment key={inq.id}>
                      <tr 
                        style={{ borderBottom: expandedInquiryId === inq.id ? 'none' : '1px solid #E5E7EB', cursor: 'pointer', transition: 'background-color 0.2s', backgroundColor: expandedInquiryId === inq.id ? '#F9FAFB' : 'transparent' }}
                        onMouseEnter={(e) => e.currentTarget.style.backgroundColor = '#F9FAFB'}
                        onMouseLeave={(e) => e.currentTarget.style.backgroundColor = expandedInquiryId === inq.id ? '#F9FAFB' : 'transparent'}
                        onClick={() => {
                          if (expandedInquiryId !== inq.id) {
                            setReplyContent('');
                          }
                          setExpandedInquiryId(expandedInquiryId === inq.id ? null : inq.id);
                        }}
                      >
                        <td style={{ padding: '16px 8px', textAlign: 'center', color: '#6B7280' }}>{inq.id}</td>
                        <td style={{ padding: '16px 8px' }}>
                          <span style={{ padding: '4px 8px', borderRadius: '6px', fontSize: '12px', fontWeight: 'bold', backgroundColor: '#E0E7FF', color: '#4338CA' }}>
                            {inq.type || '기타'}
                          </span>
                        </td>
                        <td style={{ padding: '16px 8px', fontWeight: 'bold', color: '#111827' }}>{inq.title}</td>
                        <td style={{ padding: '16px 8px', color: '#4B5563' }}>{inq.author}</td>
                        <td style={{ padding: '16px 8px', color: '#4B5563' }}>{inq.date}</td>
                        <td style={{ padding: '16px 8px', textAlign: 'center' }}>
                          <span style={{ 
                            padding: '6px 12px', borderRadius: '20px', fontSize: '12px', fontWeight: 'bold',
                            backgroundColor: inq.status === '대기중' ? '#FEF08A' : '#BBF7D0',
                            color: inq.status === '대기중' ? '#854D0E' : '#166534'
                          }}>
                            {inq.status}
                          </span>
                        </td>
                      </tr>
                      {expandedInquiryId === inq.id && (
                        <tr style={{ borderBottom: '1px solid #E5E7EB', backgroundColor: '#F9FAFB' }}>
                          <td colSpan={6} style={{ padding: '0 24px 24px 24px' }}>
                            <div style={{ padding: '20px', backgroundColor: 'white', borderRadius: '12px', border: '1px solid #E5E7EB', display: 'flex', flexDirection: 'column', gap: '16px' }}>
                              <div style={{ padding: '16px', backgroundColor: '#F3F4F6', borderRadius: '8px', borderLeft: '4px solid #10B981' }}>
                                <strong style={{ fontSize: '16px', color: '#111827', display: 'block', marginBottom: '8px' }}>Q. {inq.title}</strong>
                                <p style={{ margin: 0, fontSize: '14px', color: '#4B5563', lineHeight: '1.6' }}>{inq.content}</p>
                              </div>
                              
                              {inq.status === '대기중' ? (
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                                  <label style={{ fontWeight: 'bold', fontSize: '14px', color: '#374151' }}>관리자 답변 작성</label>
                                  <textarea 
                                    className="input-field" 
                                    placeholder="사용자에게 전달할 답변 내용을 상세히 입력하세요."
                                    value={replyContent}
                                    onChange={(e) => setReplyContent(e.target.value)}
                                    style={{ minHeight: '100px', resize: 'vertical', padding: '12px', fontSize: '14px', borderRadius: '8px' }}
                                  />
                                  <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                                    <button style={{ backgroundColor: '#111827', color: 'white', border: 'none', cursor: 'pointer', padding: '10px 20px', borderRadius: '8px', fontWeight: 'bold', fontSize: '14px' }} onClick={() => handleReplyInquiry(inq.id)}>
                                      답변 등록 완료
                                    </button>
                                  </div>
                                </div>
                              ) : (
                                <div style={{ padding: '16px', backgroundColor: '#ECFDF5', borderRadius: '8px', border: '1px solid #D1FAE5', color: '#065F46' }}>
                                  <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px', fontWeight: 'bold', fontSize: '14px' }}>
                                    <MessageCircle size={16} /> 관리자 답변
                                  </div>
                                  <p style={{ margin: 0, fontSize: '14px', lineHeight: '1.5' }}>{inq.reply}</p>
                                </div>
                              )}
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {activeAdminTab === 'reports' && (
          <div>
            {reports.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '40px', color: 'var(--color-text-muted)' }}>등록된 신고가 없습니다.</div>
            ) : (
              <>
                <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: '16px' }}>
                  <button className="btn-outline" onClick={() => setShowSuspensionMockup(true)} style={{ width: 'auto', display: 'inline-flex', alignItems: 'center', gap: '8px', padding: '8px 16px', borderRadius: '8px', fontWeight: 'bold', fontSize: '14px' }}>
                    <Ban size={16} /> 제재(정지) 화면 클라이언트 미리보기
                  </button>
                </div>
                <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                  <thead>
                    <tr style={{ borderBottom: '2px solid #E5E7EB', color: '#6B7280', fontSize: '14px' }}>
                      <th style={{ padding: '16px 8px', width: '60px', textAlign: 'center' }}>No.</th>
                      <th style={{ padding: '16px 8px', width: '150px' }}>신고 사유</th>
                      <th style={{ padding: '16px 8px', width: '150px' }}>대상자</th>
                      <th style={{ padding: '16px 8px' }}>내용 요약</th>
                      <th style={{ padding: '16px 8px', width: '100px' }}>신고자</th>
                      <th style={{ padding: '16px 8px', width: '120px' }}>신고일</th>
                      <th style={{ padding: '16px 8px', width: '100px', textAlign: 'center' }}>상태</th>
                    </tr>
                  </thead>
                  <tbody>
                    {reports.map(rep => (
                      <React.Fragment key={rep.id}>
                        <tr 
                          style={{ borderBottom: expandedReportId === rep.id ? 'none' : '1px solid #E5E7EB', cursor: 'pointer', transition: 'background-color 0.2s', backgroundColor: expandedReportId === rep.id ? '#FEF2F2' : 'transparent' }}
                          onMouseEnter={(e) => e.currentTarget.style.backgroundColor = '#FEF2F2'}
                          onMouseLeave={(e) => e.currentTarget.style.backgroundColor = expandedReportId === rep.id ? '#FEF2F2' : 'transparent'}
                          onClick={() => {
                            if (expandedReportId !== rep.id) {
                              setSuspendDuration('7일');
                              setSuspendReason('바람직하지 않은 활동 (광고, 도배, 욕설, 비방 등)');
                              setSuspendReasonOther('');
                            }
                            setExpandedReportId(expandedReportId === rep.id ? null : rep.id);
                          }}
                        >
                          <td style={{ padding: '16px 8px', textAlign: 'center', color: '#6B7280' }}>{rep.id}</td>
                          <td style={{ padding: '16px 8px', fontWeight: 'bold', color: '#991B1B' }}>[{rep.reason}]</td>
                          <td style={{ padding: '16px 8px', fontWeight: 'bold', color: '#111827' }}>{rep.reportedUser}</td>
                          <td style={{ padding: '16px 8px', color: '#4B5563', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: '200px' }}>{rep.content}</td>
                          <td style={{ padding: '16px 8px', color: '#4B5563' }}>{rep.reporter}</td>
                          <td style={{ padding: '16px 8px', color: '#4B5563' }}>{rep.date}</td>
                          <td style={{ padding: '16px 8px', textAlign: 'center' }}>
                            <span style={{ 
                              padding: '6px 12px', borderRadius: '20px', fontSize: '12px', fontWeight: 'bold',
                              backgroundColor: rep.status === '대기중' ? '#FCA5A5' : '#E5E7EB',
                              color: rep.status === '대기중' ? '#7F1D1D' : '#4B5563'
                            }}>
                              {rep.status}
                            </span>
                          </td>
                        </tr>
                        {expandedReportId === rep.id && (
                          <tr style={{ borderBottom: '1px solid #E5E7EB', backgroundColor: '#FEF2F2' }}>
                            <td colSpan={7} style={{ padding: '0 24px 24px 24px' }}>
                              <div style={{ padding: '20px', backgroundColor: 'white', borderRadius: '12px', border: '1px solid #FCA5A5', display: 'flex', flexDirection: 'column', gap: '16px' }}>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                                  <div style={{ flex: 1, padding: '16px', backgroundColor: '#F9FAFB', borderRadius: '8px', border: '1px solid #E5E7EB' }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                                      <div style={{ fontSize: '13px', fontWeight: 'bold', color: '#6B7280' }}>신고 내용 요약</div>
                                    </div>
                                    <p style={{ margin: 0, fontSize: '14px', color: '#4B5563', lineHeight: '1.6' }}><strong>[{rep.reason}]</strong> {rep.content}</p>
                                  </div>
                                  
                                  <div style={{ flex: 1, padding: '16px', backgroundColor: '#FEF2F2', borderRadius: '8px', border: '1px solid #FCA5A5' }}>
                                    <div style={{ fontSize: '13px', fontWeight: 'bold', color: '#991B1B', marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                                      <ShieldAlert size={14} /> 이전 제재/신고 기록
                                    </div>
                                    {rep.pastReports && rep.pastReports.length > 0 ? (
                                      <ul style={{ margin: 0, paddingLeft: '20px', fontSize: '13px', color: '#7F1D1D', lineHeight: '1.6' }}>
                                        {rep.pastReports.map((pr, idx) => (
                                          <li key={idx} style={{ marginBottom: '4px' }}>[{pr.date}] {pr.reason} - <strong>{pr.result}</strong></li>
                                        ))}
                                      </ul>
                                    ) : (
                                      <div style={{ fontSize: '13px', color: '#B91C1C', textAlign: 'center', padding: '10px 0' }}>
                                        이전 제재 기록이 없는 유저입니다.
                                      </div>
                                    )}
                                  </div>
                                </div>
                                
                                {rep.status === '대기중' ? (
                                  <div style={{ display: 'flex', gap: '20px' }}>
                                    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: '8px' }}>
                                      <label style={{ fontWeight: 'bold', fontSize: '14px', color: '#991B1B' }}>활동 정지 사유 선택</label>
                                      <select className="input-field" value={suspendReason} onChange={(e) => setSuspendReason(e.target.value)} style={{ padding: '10px', borderRadius: '8px', fontSize: '14px', border: '1px solid #FCA5A5' }}>
                                        <option value="성인/도박 등 불법광고 및 스팸 활동">성인/도박 등 불법광고 및 스팸 활동</option>
                                        <option value="바람직하지 않은 활동 (광고, 도배, 욕설, 비방 등)">바람직하지 않은 활동 (광고, 도배, 욕설, 비방 등)</option>
                                        <option value="플랫폼 내 자체 운영 원칙에 위배되는 활동">플랫폼 내 자체 운영 원칙에 위배되는 활동</option>
                                        <option value="기타">기타 (직접 입력)</option>
                                      </select>
                                      {suspendReason === '기타' && (
                                        <input type="text" className="input-field" placeholder="상세 사유 입력" value={suspendReasonOther} onChange={(e) => setSuspendReasonOther(e.target.value)} style={{ padding: '10px', borderRadius: '8px', fontSize: '14px', border: '1px solid #FCA5A5' }} />
                                      )}
                                    </div>
                                    <div style={{ width: '200px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                                      <label style={{ fontWeight: 'bold', fontSize: '14px', color: '#374151' }}>제재 수위</label>
                                      <select className="input-field" value={suspendDuration} onChange={(e) => setSuspendDuration(e.target.value)} style={{ padding: '10px', borderRadius: '8px', fontSize: '14px' }}>
                                        <option value="경고">경고</option>
                                        <option value="1일">1일 정지</option>
                                        <option value="7일">7일 정지</option>
                                        <option value="30일">30일 정지</option>
                                        <option value="영구 정지">영구 계정 정지</option>
                                      </select>
                                    </div>
                                    <div style={{ display: 'flex', alignItems: 'flex-end' }}>
                                      <button className="btn-primary" style={{ padding: '10px 20px', backgroundColor: '#DC2626', borderRadius: '8px', fontWeight: 'bold', fontSize: '14px' }} onClick={() => handleSuspendUser(rep.id)}>
                                        제재 처분 확정
                                      </button>
                                    </div>
                                  </div>
                                ) : (
                                  <div style={{ padding: '16px', backgroundColor: '#F9FAFB', borderRadius: '8px', border: '1px solid #E5E7EB', color: '#374151' }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '8px', fontWeight: 'bold', fontSize: '14px' }}>
                                      <CheckCircle size={16} color="#10B981" /> 처리 내역
                                    </div>
                                    <p style={{ margin: 0, fontSize: '14px', lineHeight: '1.5' }}>{rep.adminNote}</p>
                                  </div>
                                )}
                              </div>
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </div>
        )}
        </div>
      </div>
    </div>



      {/* 정지 화면 미리보기 모달 */}
      {showSuspensionMockup && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(17, 24, 39, 0.7)', backdropFilter: 'blur(8px)', zIndex: 9999, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center' }} className="animate-fade-in">
          <div className="glass-panel" style={{ width: '550px', padding: '50px', textAlign: 'center', backgroundColor: 'white', borderRadius: '24px', boxShadow: '0 25px 50px -12px rgba(0, 0, 0, 0.5)' }}>
            <div style={{ width: '90px', height: '90px', borderRadius: '50%', backgroundColor: '#FEF2F2', display: 'flex', alignItems: 'center', justifyContent: 'center', margin: '0 auto 30px auto' }}>
              <Ban size={48} color="#DC2626" />
            </div>
            
            <h2 style={{ margin: '0 0 20px 0', fontSize: '28px', color: '#111827', fontWeight: 'bold' }}>서비스 이용이 제한되었습니다</h2>
            <p style={{ margin: '0 0 40px 0', fontSize: '16px', color: '#4B5563', lineHeight: '1.6' }}>
              고객님의 계정은 운영 정책 위반으로 인해 일시적으로 서비스 이용이 정지되었습니다.<br/>
              정지 기간 동안은 모든 기능의 사용이 제한됩니다.
            </p>

            <div style={{ backgroundColor: '#F9FAFB', borderRadius: '16px', padding: '24px', textAlign: 'left', marginBottom: '40px', border: '1px solid #E5E7EB' }}>
              <div style={{ display: 'flex', marginBottom: '16px' }}>
                <div style={{ width: '120px', fontWeight: 'bold', color: '#374151', fontSize: '15px' }}>제재 사유</div>
                <div style={{ flex: 1, color: '#DC2626', fontWeight: 'bold', fontSize: '15px' }}>바람직하지 않은 활동 (욕설/비방 등)</div>
              </div>
              <div style={{ display: 'flex', marginBottom: '16px' }}>
                <div style={{ width: '120px', fontWeight: 'bold', color: '#374151', fontSize: '15px' }}>정지 기간</div>
                <div style={{ flex: 1, color: '#111827', fontSize: '15px', fontWeight: 'bold' }}>2026.05.22 ~ 2026.05.29 (7일)</div>
              </div>
              <div style={{ display: 'flex' }}>
                <div style={{ width: '120px', fontWeight: 'bold', color: '#374151', fontSize: '15px' }}>관리자 메모</div>
                <div style={{ flex: 1, color: '#6B7280', fontSize: '15px', lineHeight: '1.5' }}>게시판에서 반복적인 타인 비방 행위가 다수 신고되어 운영 정책에 따라 조치되었습니다.</div>
              </div>
            </div>

            <p style={{ margin: '0 0 30px 0', fontSize: '14px', color: '#9CA3AF' }}>
              이의 제기 및 관련 문의는 고객센터(kimdo0910@gmail.com)를 이용해 주세요.
            </p>

            <button 
              className="btn-primary" 
              onClick={() => setShowSuspensionMockup(false)}
              style={{ width: '100%', padding: '16px', fontSize: '18px', borderRadius: '12px', fontWeight: 'bold' }}
            >
              미리보기 종료 (로그아웃 연출)
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
