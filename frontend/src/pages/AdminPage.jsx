import React, { useState } from 'react';
import { ShieldAlert, MessageCircle, X, CheckCircle, AlertTriangle, Ban, LogOut, Users, FileText, Trash2 } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import { useNavigate } from 'react-router-dom';
import { adminService, groupService, knowledgeService } from '../services/api';

export default function AdminPage() {
  const { logout } = useAuth();
  const navigate = useNavigate();
  const [inquiries, setInquiries] = useState([]);
  const [groups, setGroups] = useState([]);
  const [posts, setPosts] = useState([]);

  const [reports, setReports] = useState([]);
  const [generalReports, setGeneralReports] = useState([]);
  const [reportSubTab, setReportSubTab] = useState('general');

  React.useEffect(() => {
    fetchInquiries();
    fetchGroups();
    fetchPosts();
    fetchReports();
  }, []);

  const fetchReports = async () => {
    try {
      const res = await adminService.getGroupReports();
      setReports(res || []);
      const resGen = await adminService.getGeneralReports();
      setGeneralReports(resGen || []);
    } catch (err) {
      console.error('신고 목록을 불러오는데 실패했습니다.', err);
    }
  };

  const fetchGroups = async () => {
    try {
      const res = await groupService.getGroups();
      setGroups(res || []);
    } catch (err) {
      console.error('그룹 목록을 불러오는데 실패했습니다.', err);
    }
  };

  const fetchPosts = async () => {
    try {
      const res = await knowledgeService.getPosts();
      setPosts(res || []);
    } catch (err) {
      console.error('게시글 목록을 불러오는데 실패했습니다.', err);
    }
  };

  const fetchInquiries = async () => {
    try {
      const res = await adminService.getInquiries();
      setInquiries(res || []);
    } catch (err) {
      console.error('문의 목록을 불러오는데 실패했습니다.', err);
    }
  };

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

  const handleReplyInquiry = async (id) => {
    if (!replyContent.trim()) {
      alert('답변 내용을 입력해주세요.');
      return;
    }
    try {
      await adminService.replyInquiry(id, { reply: replyContent });
      alert('답변이 등록되었습니다.');
      setExpandedInquiryId(null);
      setReplyContent('');
      fetchInquiries();
    } catch (err) {
      console.error('답변 등록에 실패했습니다.', err);
      alert('답변 등록에 실패했습니다.');
    }
  };

  const handleSuspendUser = async (userId) => {
    const finalReason = suspendReason === '기타' ? (suspendReasonOther || '기타') : suspendReason;
    try {
      if (suspendDuration === '영구 정지') {
        await adminService.banUser(userId, { reason: finalReason });
        alert('해당 멤버를 영구 정지했습니다.');
      } else {
        await adminService.suspendUser(userId, { reason: finalReason, days: suspendDuration === '경고' ? 0 : parseInt(suspendDuration) });
        const actionText = suspendDuration === '경고' ? '경고 처리' : '활동 정지';
        alert(`해당 멤버를 ${actionText}했습니다.`);
      }

      setReports(prevReports => prevReports.map(report => 
        report.id === expandedReportId ? { ...report, status: '처리 완료' } : report
      ));

      setExpandedReportId(null);
      setSuspendDuration('7일');
      setSuspendReason('바람직하지 않은 활동 (광고, 도배, 욕설, 비방 등)');
      setSuspendReasonOther('');
      setAdminNote('');
      // 백엔드에서 신고 상태 업데이트 API가 없으므로 프론트엔드에서 상태만 변경 (fetchReports() 주석 처리)
      // fetchReports();
    } catch (err) {
      console.error('제재 처리 실패', err);
      alert('제재 처리에 실패했습니다.');
    }
  };

  const handleDeleteGroup = async (id) => {
    if (!window.confirm('정말 이 그룹 스터디를 삭제하시겠습니까?')) return;
    try {
      await adminService.deleteGroup(id);
      alert('그룹 스터디가 삭제되었습니다.');
      fetchGroups();
    } catch (err) {
      console.error('그룹 스터디 삭제 실패:', err);
      alert('삭제에 실패했습니다.');
    }
  };

  const handleDeletePost = async (id) => {
    if (!window.confirm('정말 이 지식공유 게시글을 삭제하시겠습니까?')) return;
    try {
      await adminService.deletePost(id);
      alert('게시글이 삭제되었습니다.');
      fetchPosts();
    } catch (err) {
      console.error('게시글 삭제 실패:', err);
      alert('삭제에 실패했습니다.');
    }
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
          <button 
            style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 16px', borderRadius: '8px', cursor: 'pointer', border: 'none', backgroundColor: activeAdminTab === 'groups' ? '#1F2937' : 'transparent', color: activeAdminTab === 'groups' ? '#3B82F6' : '#9CA3AF', fontWeight: activeAdminTab === 'groups' ? 'bold' : 'normal', transition: 'all 0.2s', fontSize: '15px' }}
            onClick={() => setActiveAdminTab('groups')}
          >
            <Users size={18} /> 그룹스터디 관리
          </button>
          <button 
            style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 16px', borderRadius: '8px', cursor: 'pointer', border: 'none', backgroundColor: activeAdminTab === 'posts' ? '#1F2937' : 'transparent', color: activeAdminTab === 'posts' ? '#8B5CF6' : '#9CA3AF', fontWeight: activeAdminTab === 'posts' ? 'bold' : 'normal', transition: 'all 0.2s', fontSize: '15px' }}
            onClick={() => setActiveAdminTab('posts')}
          >
            <FileText size={18} /> 지식공유 관리
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
            {/* 신고 관리 서브 탭 */}
            <div style={{ display: 'flex', gap: '12px', marginBottom: '24px', borderBottom: '1px solid #E5E7EB', paddingBottom: '12px' }}>
              <button 
                style={{ padding: '8px 16px', borderRadius: '6px', cursor: 'pointer', border: 'none', backgroundColor: reportSubTab === 'general' ? '#1F2937' : 'transparent', color: reportSubTab === 'general' ? 'white' : '#4B5563', fontWeight: 'bold' }}
                onClick={() => { setReportSubTab('general'); setExpandedReportId(null); }}
              >
                지식공유 / 댓글 신고
              </button>
              <button 
                style={{ padding: '8px 16px', borderRadius: '6px', cursor: 'pointer', border: 'none', backgroundColor: reportSubTab === 'group' ? '#1F2937' : 'transparent', color: reportSubTab === 'group' ? 'white' : '#4B5563', fontWeight: 'bold' }}
                onClick={() => { setReportSubTab('group'); setExpandedReportId(null); }}
              >
                그룹스터디 신고
              </button>
            </div>

            {reportSubTab === 'general' && (
              generalReports.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '40px', color: '#6B7280' }}>등록된 지식공유/댓글 신고가 없습니다.</div>
              ) : (
                <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                  <thead>
                    <tr style={{ borderBottom: '2px solid #E5E7EB', color: '#6B7280', fontSize: '14px' }}>
                      <th style={{ padding: '16px 8px', width: '60px', textAlign: 'center' }}>No.</th>
                      <th style={{ padding: '16px 8px', width: '100px' }}>유형</th>
                      <th style={{ padding: '16px 8px', width: '150px' }}>신고 사유</th>
                      <th style={{ padding: '16px 8px' }}>대상자 / 제목</th>
                      <th style={{ padding: '16px 8px', width: '100px' }}>신고자</th>
                      <th style={{ padding: '16px 8px', width: '120px' }}>신고일</th>
                      <th style={{ padding: '16px 8px', width: '100px', textAlign: 'center' }}>상태</th>
                    </tr>
                  </thead>
                  <tbody>
                    {generalReports.map(rep => (
                      <React.Fragment key={rep.reportId}>
                        <tr 
                          style={{ borderBottom: expandedReportId === rep.reportId ? 'none' : '1px solid #E5E7EB', cursor: 'pointer', transition: 'background-color 0.2s', backgroundColor: expandedReportId === rep.reportId ? '#FEF2F2' : 'transparent' }}
                          onMouseEnter={(e) => e.currentTarget.style.backgroundColor = '#FEF2F2'}
                          onMouseLeave={(e) => e.currentTarget.style.backgroundColor = expandedReportId === rep.reportId ? '#FEF2F2' : 'transparent'}
                          onClick={() => {
                            setExpandedReportId(expandedReportId === rep.reportId ? null : rep.reportId);
                          }}
                        >
                          <td style={{ padding: '16px 8px', textAlign: 'center', color: '#6B7280' }}>{rep.reportId}</td>
                          <td style={{ padding: '16px 8px' }}>
                            <span style={{ padding: '4px 8px', borderRadius: '6px', fontSize: '12px', fontWeight: 'bold', backgroundColor: rep.reportType === 'POST' ? '#E0E7FF' : rep.reportType === 'COMMENT' ? '#FEE2E2' : '#FEF3C7', color: rep.reportType === 'POST' ? '#4338CA' : rep.reportType === 'COMMENT' ? '#EF4444' : '#D97706' }}>
                              {rep.reportType === 'POST' ? '게시글' : rep.reportType === 'COMMENT' ? '댓글' : '유저'}
                            </span>
                          </td>
                          <td style={{ padding: '16px 8px', fontWeight: 'bold', color: '#991B1B' }}>[{rep.reason || '기타'}]</td>
                          <td style={{ padding: '16px 8px', fontWeight: 'bold', color: '#111827' }}>
                            {rep.targetTitleOrName || '알 수 없음'} <span style={{ color: '#9CA3AF', fontWeight: 'normal', fontSize: '12px' }}>(ID: {rep.targetId})</span>
                          </td>
                          <td style={{ padding: '16px 8px', color: '#4B5563' }}>{rep.reporterNickname || '알 수 없음'}</td>
                          <td style={{ padding: '16px 8px', color: '#4B5563' }}>{(rep.createdAt || '').split('T')[0]}</td>
                          <td style={{ padding: '16px 8px', textAlign: 'center' }}>
                            <span style={{ 
                              padding: '6px 12px', borderRadius: '20px', fontSize: '12px', fontWeight: 'bold',
                              backgroundColor: rep.status === 'RESOLVED' ? '#BBF7D0' : rep.status === 'REJECTED' ? '#F3F4F6' : '#FEF08A',
                              color: rep.status === 'RESOLVED' ? '#166534' : rep.status === 'REJECTED' ? '#4B5563' : '#854D0E'
                            }}>
                              {rep.status === 'PENDING' ? '대기중' : rep.status === 'RESOLVED' ? '처리 완료' : '반려됨'}
                            </span>
                          </td>
                        </tr>
                        {expandedReportId === rep.reportId && (
                          <tr style={{ borderBottom: '1px solid #E5E7EB', backgroundColor: '#FEF2F2' }}>
                            <td colSpan={7} style={{ padding: '0 24px 24px 24px' }}>
                              <div style={{ padding: '20px', backgroundColor: 'white', borderRadius: '12px', border: '1px solid #FCA5A5', display: 'flex', flexDirection: 'column', gap: '16px' }}>
                                <div style={{ padding: '16px', backgroundColor: '#F9FAFB', borderRadius: '8px', border: '1px solid #E5E7EB' }}>
                                  <div style={{ fontSize: '13px', fontWeight: 'bold', color: '#6B7280', marginBottom: '8px' }}>신고 상세 사유</div>
                                  <p style={{ margin: 0, fontSize: '14px', color: '#4B5563', lineHeight: '1.6' }}>{rep.details || '상세 사유가 없습니다.'}</p>
                                </div>
                                
                                {rep.status === 'PENDING' && (
                                  <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px' }}>
                                    <button 
                                      style={{ padding: '10px 20px', backgroundColor: '#E5E7EB', color: '#4B5563', border: 'none', borderRadius: '8px', fontWeight: 'bold', fontSize: '14px', cursor: 'pointer' }}
                                      onClick={async () => {
                                        if (window.confirm('이 신고를 반려(무시) 처리하시겠습니까?')) {
                                          try {
                                            await adminService.resolveReport(rep.reportId, 'REJECTED');
                                            alert('신고를 반려 처리했습니다.');
                                            fetchReports();
                                          } catch (err) {
                                            console.error(err);
                                            alert('처리에 실패했습니다.');
                                          }
                                        }
                                      }}
                                    >
                                      신고 반려 (무시)
                                    </button>
                                    <button 
                                      style={{ padding: '10px 20px', backgroundColor: '#DC2626', color: 'white', border: 'none', borderRadius: '8px', fontWeight: 'bold', fontSize: '14px', cursor: 'pointer' }}
                                      onClick={async () => {
                                        if (window.confirm('이 신고를 승인(처리 완료) 처리하시겠습니까?')) {
                                          try {
                                            await adminService.resolveReport(rep.reportId, 'RESOLVED');
                                            alert('신고를 승인(처리 완료) 처리했습니다.');
                                            fetchReports();
                                          } catch (err) {
                                            console.error(err);
                                            alert('처리에 실패했습니다.');
                                          }
                                        }
                                      }}
                                    >
                                      신고 승인 (처리 완료)
                                    </button>
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
              )
            )}

            {reportSubTab === 'group' && (
              reports.length === 0 ? (
                <div style={{ textAlign: 'center', padding: '40px', color: 'var(--color-text-muted)' }}>등록된 신고가 없습니다.</div>
              ) : (
                <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                  <thead>
                    <tr style={{ borderBottom: '2px solid #E5E7EB', color: '#6B7280', fontSize: '14px' }}>
                      <th style={{ padding: '16px 8px', width: '60px', textAlign: 'center' }}>No.</th>
                      <th style={{ padding: '16px 8px', width: '150px' }}>신고 사유</th>
                      <th style={{ padding: '16px 8px', width: '150px' }}>대상자</th>
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
                          <td style={{ padding: '16px 8px', fontWeight: 'bold', color: '#991B1B' }}>[{rep.reason || '기타'}]</td>
                          <td style={{ padding: '16px 8px', fontWeight: 'bold', color: '#111827' }}>{rep.reportedUserName || '알 수 없음'}</td>
                          <td style={{ padding: '16px 8px', color: '#4B5563' }}>{rep.reporterName || '알 수 없음'}</td>
                          <td style={{ padding: '16px 8px', color: '#4B5563' }}>{(rep.createdAt || '').split('T')[0]}</td>
                          <td style={{ padding: '16px 8px', textAlign: 'center' }}>
                            <span style={{ 
                              padding: '6px 12px', borderRadius: '20px', fontSize: '12px', fontWeight: 'bold',
                              backgroundColor: (rep.reportedUserStatus === 'SUSPENDED' || rep.reportedUserStatus === 'BANNED' || rep.status === '처리 완료') ? '#BBF7D0' : '#FEF08A',
                              color: (rep.reportedUserStatus === 'SUSPENDED' || rep.reportedUserStatus === 'BANNED' || rep.status === '처리 완료') ? '#166534' : '#854D0E'
                            }}>
                              {(rep.reportedUserStatus === 'SUSPENDED' || rep.reportedUserStatus === 'BANNED' || rep.status === '처리 완료') ? '처리 완료' : '대기중'}
                            </span>
                          </td>
                        </tr>
                        {expandedReportId === rep.id && (
                          <tr style={{ borderBottom: '1px solid #E5E7EB', backgroundColor: '#FEF2F2' }}>
                            <td colSpan={6} style={{ padding: '0 24px 24px 24px' }}>
                              <div style={{ padding: '20px', backgroundColor: 'white', borderRadius: '12px', border: '1px solid #FCA5A5', display: 'flex', flexDirection: 'column', gap: '16px' }}>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
                                  <div style={{ flex: 1, padding: '16px', backgroundColor: '#F9FAFB', borderRadius: '8px', border: '1px solid #E5E7EB' }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                                      <div style={{ fontSize: '13px', fontWeight: 'bold', color: '#6B7280' }}>신고 내용 요약</div>
                                    </div>
                                    <p style={{ margin: 0, fontSize: '14px', color: '#4B5563', lineHeight: '1.6' }}><strong>[{rep.reason || '기타'}]</strong> 신고가 접수되었습니다.</p>
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
                                      <option value="영구 정지">영구 정지</option>
                                    </select>
                                  </div>
                                  <div style={{ display: 'flex', alignItems: 'flex-end' }}>
                                    <button className="btn-primary" style={{ padding: '10px 20px', backgroundColor: '#DC2626', borderRadius: '8px', fontWeight: 'bold', fontSize: '14px' }} onClick={() => handleSuspendUser(rep.reportedUserId)}>
                                      제재 처분 확정
                                    </button>
                                  </div>
                                </div>
                              </div>
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    ))}
                  </tbody>
                </table>
              )
            )}
          </div>
        )}

        {activeAdminTab === 'groups' && (
          <div>
            {groups.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '40px', color: 'var(--color-text-muted)' }}>등록된 그룹 스터디가 없습니다.</div>
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                <thead>
                  <tr style={{ borderBottom: '2px solid #E5E7EB', color: '#6B7280', fontSize: '14px' }}>
                    <th style={{ padding: '16px 8px', width: '60px', textAlign: 'center' }}>ID</th>
                    <th style={{ padding: '16px 8px' }}>그룹명</th>
                    <th style={{ padding: '16px 8px', width: '120px' }}>작성자</th>
                    <th style={{ padding: '16px 8px', width: '80px', textAlign: 'center' }}>관리</th>
                  </tr>
                </thead>
                <tbody>
                  {groups.map(group => (
                    <tr key={group.id} style={{ borderBottom: '1px solid #E5E7EB' }}>
                      <td style={{ padding: '16px 8px', textAlign: 'center', color: '#6B7280' }}>{group.id}</td>
                      <td style={{ padding: '16px 8px', fontWeight: 'bold', color: '#111827' }}>
                        <a href={`/groupstudy?openModal=${group.id}`} style={{ textDecoration: 'none', color: '#111827', textDecorationLine: 'underline' }} target="_blank" rel="noopener noreferrer">
                          {group.name || group.title}
                        </a>
                      </td>
                      <td style={{ padding: '16px 8px', color: '#4B5563' }}>{group.leaderName || group.owner?.displayName || '알 수 없음'}</td>
                      <td style={{ padding: '16px 8px', textAlign: 'center' }}>
                        <button onClick={() => handleDeleteGroup(group.id)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#EF4444', padding: '4px' }} title="삭제">
                          <Trash2 size={18} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}

        {activeAdminTab === 'posts' && (
          <div>
            {posts.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '40px', color: 'var(--color-text-muted)' }}>등록된 지식공유 게시글이 없습니다.</div>
            ) : (
              <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
                <thead>
                  <tr style={{ borderBottom: '2px solid #E5E7EB', color: '#6B7280', fontSize: '14px' }}>
                    <th style={{ padding: '16px 8px', width: '60px', textAlign: 'center' }}>ID</th>
                    <th style={{ padding: '16px 8px' }}>제목</th>
                    <th style={{ padding: '16px 8px', width: '120px' }}>작성자</th>
                    <th style={{ padding: '16px 8px', width: '120px' }}>작성일</th>
                    <th style={{ padding: '16px 8px', width: '80px', textAlign: 'center' }}>관리</th>
                  </tr>
                </thead>
                <tbody>
                  {posts.map(post => (
                    <tr key={post.id || post.blogId} style={{ borderBottom: '1px solid #E5E7EB' }}>
                      <td style={{ padding: '16px 8px', textAlign: 'center', color: '#6B7280' }}>{post.id || post.blogId}</td>
                      <td style={{ padding: '16px 8px', fontWeight: 'bold', color: '#111827' }}>
                        <a href={`/knowledge/${post.id || post.blogId}`} style={{ textDecoration: 'none', color: '#111827' }} target="_blank" rel="noopener noreferrer">
                          {post.title}
                        </a>
                      </td>
                      <td style={{ padding: '16px 8px', color: '#4B5563' }}>{post.authorNickname || post.authorName || post.user?.displayName || '알 수 없음'}</td>
                      <td style={{ padding: '16px 8px', color: '#4B5563' }}>{(post.createdAt || post.date || '').split('T')[0]}</td>
                      <td style={{ padding: '16px 8px', textAlign: 'center' }}>
                        <button onClick={() => handleDeletePost(post.id || post.blogId)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#EF4444', padding: '4px' }} title="삭제">
                          <Trash2 size={18} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
        </div>
      </div>
    </div>

    </div>
  );
}
