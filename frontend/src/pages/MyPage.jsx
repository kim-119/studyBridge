import React, { useState, useEffect } from 'react';
import { useAuth } from '../hooks/useAuth';
import { authService, adminService } from '../services/api';
import { ShieldAlert, MessageCircle, X, CheckCircle, AlertTriangle, Ban } from 'lucide-react';

export default function MyPage() {
  const { userId, userEmail, user, updateUser } = useAuth();
  const isAdmin = user?.role === 'ADMIN' || userEmail === 'admin@studybridge.com';
  
  const [name, setName] = useState('');
  const [major, setMajor] = useState('');
  const [email, setEmail] = useState('');
  const [isEditing, setIsEditing] = useState(false);

  useEffect(() => {
    if (!userId) return;
    const fetchProfile = async () => {
      try {
        const res = await authService.getProfile(userId);
        setName(res.displayName || res.display_name || res.name || '');
        setMajor(res.major || '');
        setEmail(res.email || userEmail || '');
      } catch (err) {
        console.warn('서버에서 프로필을 불러오지 못했습니다. 로컬 데이터를 사용합니다.');
        setName(user?.displayName || '');
        setMajor(user?.major || '');
        setEmail(user?.email || userEmail || '');
      }
    };
    fetchProfile();
  }, [userId, userEmail]);

  // 관리자 메뉴 (문의/신고) 더미 데이터 및 상태
  const [inquiries, setInquiries] = useState([]);

  const [reports, setReports] = useState([]);
  const [loadingReports, setLoadingReports] = useState(false);
  const [suspensionDetails, setSuspensionDetails] = useState(null);

  const fetchReports = async () => {
    if (!isAdmin) return;
    const stored = localStorage.getItem('reports');
    if (stored) {
      setReports(JSON.parse(stored));
      return;
    }
    setLoadingReports(true);
    try {
      const data = await adminService.getGroupReports();
      const fetched = (data || []).map(r => ({
        id: r.id,
        groupStudyId: r.groupStudyId,
        reporter: r.reporterName || '익명',
        reportedUser: r.reportedUserName || '알 수 없음',
        reportedUserId: r.reportedUserId,
        reason: r.reason || '신고',
        content: `스터디그룹 ID: ${r.groupStudyId}에 대한 회원 신고가 접수되었습니다.`,
        date: r.createdAt ? r.createdAt.split('T')[0] : new Date().toISOString().split('T')[0],
        status: '대기중',
        adminNote: ''
      }));
      setReports(fetched);
      localStorage.setItem('reports', JSON.stringify(fetched));
    } catch (err) {
      console.error('신고 내역 로드 실패:', err);
    } finally {
      setLoadingReports(false);
    }
  };

  useEffect(() => {
    if (isAdmin) {
      fetchReports();
    }
  }, [userEmail, user]);

  const [activeAdminTab, setActiveAdminTab] = useState('inquiries');

  // 문의 목록 실시간 로드 (관리자 전용)
  useEffect(() => {
    if (isAdmin) {
      adminService.getInquiries()
        .then(setInquiries)
        .catch(err => console.error('문의 조회 실패', err));
    }
  }, [isAdmin]);

  // 모달 상태
  const [selectedInquiry, setSelectedInquiry] = useState(null);
  const [replyContent, setReplyContent] = useState('');

  const [selectedReport, setSelectedReport] = useState(null);
  const [suspendReason, setSuspendReason] = useState('바람직하지 않은 활동 (광고, 도배, 욕설, 비방 등)');
  const [suspendReasonOther, setSuspendReasonOther] = useState('');
  const [suspendDuration, setSuspendDuration] = useState('7일');
  const [adminNote, setAdminNote] = useState('');

  const handleReplyInquiry = () => {
    if (!replyContent.trim()) {
      alert('답변 내용을 입력해주세요.');
      return;
    }
    setInquiries(inquiries.map(inq => 
      inq.id === selectedInquiry.id ? { ...inq, status: '답변완료', reply: replyContent } : inq
    ));
    setSelectedInquiry(null);
    setReplyContent('');
    alert('답변이 등록되었습니다.');
  };

  const handleSuspendUser = async () => {
    const finalReason = suspendReason === '기타' ? (suspendReasonOther || '기타') : suspendReason;
    
    try {
      if (selectedReport && selectedReport.reportedUserId) {
        if (suspendDuration === '영구 정지') {
          await adminService.banUser(selectedReport.reportedUserId, {
            reason: finalReason,
            memo: adminNote || '영구 정지 조치'
          });
          alert(`${selectedReport.reportedUser} 회원이 영구 정지되었습니다.`);
        } else {
          let days = 7;
          if (suspendDuration === '1일') days = 1;
          if (suspendDuration === '30일') days = 30;

          await adminService.suspendUser(selectedReport.reportedUserId, {
            days: days,
            reason: finalReason,
            memo: adminNote || `${days}일 활동 정지 조치`
          });
          alert(`${selectedReport.reportedUser} 회원이 ${days}일 동안 활동 정지되었습니다.`);
        }
      }
      
      const updated = reports.map(rep => 
        rep.id === selectedReport.id ? { ...rep, status: '처리완료', adminNote: `[${suspendDuration} 정지] ${finalReason}` } : rep
      );
      setReports(updated);
      localStorage.setItem('reports', JSON.stringify(updated));
    } catch (err) {
      console.error('제재 처리 실패:', err);
      alert(err.response?.data?.message || err.message || '제재 처리에 실패했습니다.');
    } finally {
      setSelectedReport(null);
      setSuspendDuration('7일');
      setSuspendReason('바람직하지 않은 활동 (광고, 도배, 욕설, 비방 등)');
      setSuspendReasonOther('');
      setAdminNote('');
    }
  };

  const handleCrushGroup = async (groupId, reportId) => {
    if (!groupId) {
      alert('그룹 ID가 존재하지 않습니다.');
      return;
    }
    if (!window.confirm(`스터디 그룹(ID: ${groupId})을 강제 폐쇄하시겠습니까?`)) return;
    try {
      await adminService.deleteGroup(groupId);
      alert('스터디 그룹이 강제 폐쇄되었습니다.');
      const updated = reports.map(rep => 
        rep.id === reportId ? { ...rep, status: '처리완료', adminNote: '[그룹 강제 폐쇄 완료]' } : rep
      );
      setReports(updated);
      localStorage.setItem('reports', JSON.stringify(updated));
    } catch (err) {
      console.error('그룹 폐쇄 실패:', err);
      alert(err.response?.data?.message || err.message || '그룹 폐쇄에 실패했습니다.');
    }
  };

  // 비밀번호 변경 관련 상태
  const [verifyEmail, setVerifyEmail] = useState('');
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [passwordError, setPasswordError] = useState('');
  const [passwordSuccess, setPasswordSuccess] = useState('');
  const [isVerified, setIsVerified] = useState(false);

  const handleSave = async () => {
    const finalName = name.trim() || email.split('@')[0] || '';
    const finalMajor = major.trim() || '전공 미설정';

    try {
      if (userId) {
        await authService.updateProfile(userId, { displayName: finalName, major: finalMajor });
        
        let refreshed = { displayName: finalName, major: finalMajor, email: email };
        try {
          refreshed = await authService.getProfile(userId);
        } catch (e) {
          console.warn('저장 후 프로필 재조회 실패:', e);
        }

        updateUser(refreshed);

        setName(refreshed.displayName || refreshed.display_name || refreshed.name || finalName);
        setMajor(refreshed.major || finalMajor);
        setEmail(refreshed.email || email);
      }
      
      setIsEditing(false);
      alert('프로필이 성공적으로 업데이트되었습니다.');
    } catch (error) {
      alert(error.message || '프로필 업데이트에 실패했습니다.');
    }
  };

  const handleCancel = () => {
    setName(user?.displayName || '');
    setMajor(user?.major || '');
    setIsEditing(false);
  };

  const handleVerifyPassword = async () => {
    setPasswordError('');
    setPasswordSuccess('');

    if (!verifyEmail || !currentPassword) {
      setPasswordError('이메일과 현재 비밀번호를 입력해주세요.');
      return;
    }

    try {
      const res = await authService.verifyPassword({ 
        email: verifyEmail, 
        password: currentPassword 
      });
      
      if (res.verified) {
        setIsVerified(true);
        setPasswordSuccess('본인 확인이 완료되었습니다. 새 비밀번호를 입력해주세요.');
      }
    } catch (error) {
      setPasswordError('이메일 또는 현재 비밀번호가 일치하지 않습니다.');
    }
  };

  const handleCancelPasswordChange = () => {
    setIsVerified(false);
    setVerifyEmail('');
    setCurrentPassword('');
    setNewPassword('');
    setConfirmPassword('');
    setPasswordError('');
    setPasswordSuccess('');
  };

  const handleFinalPasswordChange = async () => {
    setPasswordError('');
    setPasswordSuccess('');

    if (!newPassword || !confirmPassword) {
      setPasswordError('새 비밀번호를 입력해주세요.');
      return;
    }

    if (newPassword !== confirmPassword) {
      setPasswordError('새 비밀번호가 일치하지 않습니다.');
      return;
    }

    try {
      await authService.updatePassword({ 
        email: verifyEmail,
        currentPassword: currentPassword, 
        newPassword: newPassword,
        newPasswordConfirm: confirmPassword
      });
      alert('비밀번호가 성공적으로 변경되었습니다.');
      handleCancelPasswordChange();
    } catch (error) {
      setPasswordError(error.message || '비밀번호 변경에 실패했습니다.');
    }
  };

  return (
    <div className="mypage-page">
      <div className="glass-panel animate-fade-in" style={{ padding: '30px' }}>
        <div className="profile-header">
          <div className="profile-avatar">
            {name ? name.charAt(0).toUpperCase() : '?'}
          </div>
          <div>
            <h3 style={{ margin: 0 }}>{name || '이름 없음'}</h3>
            <p style={{ margin: '6px 0 0', color: 'var(--color-text-muted)' }}>
              {major || '전공 미설정'}
            </p>
          </div>
        </div>

        <div className="form-grid">
          <div className="form-group">
            <label>이름</label>
            <input
              className="input-field"
              value={name}
              onChange={(e) => setName(e.target.value)}
              disabled={!isEditing}
              placeholder="이름을 입력하세요"
            />
          </div>

          <div className="form-group">
            <label>전공</label>
            <input
              className="input-field"
              value={major}
              onChange={(e) => setMajor(e.target.value)}
              disabled={!isEditing}
              placeholder="전공을 입력하세요"
            />
          </div>

          <div className="form-group">
            <label>이메일</label>
            <input className="input-field" value={email} disabled />
          </div>
        </div>

        <div className="btn-group">
          {isEditing ? (
            <>
              <button className="btn-primary" onClick={handleSave}>
                저장
              </button>
              <button className="btn-outline" onClick={handleCancel}>
                취소
              </button>
            </>
          ) : (
            <button className="btn-primary" onClick={() => setIsEditing(true)}>
              프로필 수정
            </button>
          )}
        </div>
      </div>

      <div className="glass-panel animate-fade-in" style={{ padding: '30px', marginTop: '24px' }}>
        <h3 style={{ margin: '0 0 20px 0', color: 'var(--color-primary)' }}>비밀번호 변경</h3>
        
        {!isVerified ? (
          <div style={{ display: 'grid', gap: '18px' }}>
            <div>
              <label style={{ display: 'block', marginBottom: '8px', fontWeight: 600 }}>이메일</label>
              <input
                type="email"
                className="input-field"
                value={verifyEmail}
                onChange={(e) => setVerifyEmail(e.target.value)}
                placeholder="가입 시 사용한 이메일"
              />
            </div>
            <div>
              <label style={{ display: 'block', marginBottom: '8px', fontWeight: 600 }}>현재 비밀번호</label>
              <input
                type="password"
                className="input-field"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                placeholder="현재 비밀번호를 입력하세요"
              />
            </div>
            {passwordError && <div style={{ color: 'red', marginTop: '10px' }}>{passwordError}</div>}
            <div style={{ display: 'flex', gap: '10px', marginTop: '24px' }}>
              <button className="btn-primary" onClick={handleVerifyPassword} style={{ width: 'auto', minWidth: '120px' }}>
                본인 확인
              </button>
            </div>
          </div>
        ) : (
          <div className="form-grid">
            <div className="form-group">
              <label>새 비밀번호</label>
              <input
                type="password"
                className="input-field"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                placeholder="새 비밀번호 입력"
              />
            </div>
            <div className="form-group">
              <label>새 비밀번호 확인</label>
              <input
                type="password"
                className="input-field"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                placeholder="새 비밀번호 다시 입력"
              />
            </div>
            {passwordError && <div style={{ color: 'red', marginTop: '10px' }}>{passwordError}</div>}
            {passwordSuccess && <div style={{ color: 'green', marginTop: '10px' }}>{passwordSuccess}</div>}
            <div className="btn-group">
              <button className="btn-primary" onClick={handleFinalPasswordChange} style={{ width: 'auto', minWidth: '120px' }}>
                비밀번호 변경
              </button>
              <button className="btn-outline" onClick={handleCancelPasswordChange} style={{ width: 'auto', minWidth: '80px' }}>
                취소
              </button>
            </div>
          </div>
        )}
      </div>

      {/* 관리자 메뉴 (하단 추가) */}
      {isAdmin && (
        <div className="glass-panel animate-fade-in" style={{ padding: '30px', marginTop: '24px' }}>
          <h3 style={{ margin: '0 0 20px 0', color: 'var(--color-primary)', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <ShieldAlert size={20} /> 관리자 메뉴 (문의 및 신고 관리)
          </h3>

        <div className="archive-tabs" style={{ marginBottom: '20px' }}>
          <button 
            className={`archive-tab ${activeAdminTab === 'inquiries' ? 'active' : ''}`}
            onClick={() => setActiveAdminTab('inquiries')}
          >
            문의 내역
          </button>
          <button 
            className={`archive-tab ${activeAdminTab === 'reports' ? 'active' : ''}`}
            onClick={() => setActiveAdminTab('reports')}
          >
            신고 내역
          </button>
        </div>

        {activeAdminTab === 'inquiries' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {inquiries.map(inq => (
              <div key={inq.id} style={{ padding: '16px', borderRadius: '12px', border: '1px solid var(--color-border)', backgroundColor: '#F9FAFB' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                  <div style={{ fontWeight: 'bold', fontSize: '16px' }}>{inq.title}</div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <span style={{ fontSize: '13px', color: 'var(--color-text-muted)' }}>{inq.date} • {inq.author}</span>
                    <span style={{ 
                      padding: '4px 10px', borderRadius: '20px', fontSize: '12px', fontWeight: 'bold',
                      backgroundColor: inq.status === '대기중' ? '#FEF08A' : '#BBF7D0',
                      color: inq.status === '대기중' ? '#854D0E' : '#166534'
                    }}>
                      {inq.status}
                    </span>
                  </div>
                </div>
                <p style={{ margin: '0 0 12px 0', fontSize: '14px', color: 'var(--color-text-main)' }}>{inq.content}</p>
                {inq.reply && (
                  <div style={{ padding: '12px', backgroundColor: 'white', borderRadius: '8px', border: '1px solid #E5E7EB', marginTop: '12px', fontSize: '14px' }}>
                    <strong><MessageCircle size={14} style={{ display: 'inline', verticalAlign: 'middle', marginRight: '4px' }} /> 관리자 답변:</strong> {inq.reply}
                  </div>
                )}
                {inq.status === '대기중' && (
                  <button className="btn-outline" style={{ marginTop: '12px', padding: '8px 16px', width: 'auto' }} onClick={() => setSelectedInquiry(inq)}>
                    답변하기
                  </button>
                )}
              </div>
            ))}
          </div>
        )}

        {activeAdminTab === 'reports' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            {reports.map(rep => (
              <div key={rep.id} style={{ padding: '16px', borderRadius: '12px', border: '1px solid var(--color-border)', backgroundColor: '#FEF2F2' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
                  <div style={{ fontWeight: 'bold', fontSize: '16px', color: '#991B1B' }}>
                    <AlertTriangle size={16} style={{ display: 'inline', verticalAlign: 'middle', marginRight: '6px' }}/>
                    [{rep.reason}] {rep.reportedUser} 신고
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <span style={{ fontSize: '13px', color: 'var(--color-text-muted)' }}>{rep.date} • 신고자: {rep.reporter}</span>
                    <span style={{ 
                      padding: '4px 10px', borderRadius: '20px', fontSize: '12px', fontWeight: 'bold',
                      backgroundColor: rep.status === '대기중' ? '#FCA5A5' : '#E5E7EB',
                      color: rep.status === '대기중' ? '#7F1D1D' : '#4B5563'
                    }}>
                      {rep.status}
                    </span>
                  </div>
                </div>
                <p style={{ margin: '0 0 12px 0', fontSize: '14px', color: 'var(--color-text-main)' }}>{rep.content}</p>
                {rep.adminNote && (
                  <div style={{ padding: '12px', backgroundColor: 'white', borderRadius: '8px', border: '1px solid #E5E7EB', marginTop: '12px', fontSize: '14px', color: '#374151' }}>
                    <strong><CheckCircle size={14} style={{ display: 'inline', verticalAlign: 'middle', marginRight: '4px' }} /> 처리내역:</strong> {rep.adminNote}
                  </div>
                )}
                {rep.status === '대기중' && (
                  <div style={{ display: 'flex', gap: '10px', marginTop: '12px' }}>
                    <button className="btn-primary" style={{ padding: '8px 16px', width: 'auto', backgroundColor: '#EF4444' }} onClick={() => setSelectedReport(rep)}>
                      제재하기
                    </button>
                    {rep.groupStudyId && (
                      <button className="btn-outline" style={{ padding: '8px 16px', width: 'auto', color: '#DC2626', borderColor: '#DC2626', backgroundColor: '#FFF5F5' }} onClick={() => handleCrushGroup(rep.groupStudyId, rep.id)}>
                        그룹 강제 폐쇄
                      </button>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}

        <div style={{ marginTop: '24px', textAlign: 'center', borderTop: '1px solid var(--color-border)', paddingTop: '24px' }}>
          {/* Removed suspension preview button */}
        </div>
        </div>
      )}

      {/* 문의 답변 모달 */}
      {selectedInquiry && (
        <div className="modal-overlay" style={{ zIndex: 1000 }}>
          <div className="glass-panel modal-content animate-fade-in" style={{ width: '500px', padding: '32px', borderRadius: '24px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
              <h3 style={{ margin: 0, fontSize: '20px' }}>문의 답변하기</h3>
              <button className="btn-close" onClick={() => setSelectedInquiry(null)}><X size={24} /></button>
            </div>
            <div style={{ marginBottom: '20px', padding: '16px', backgroundColor: '#F3F4F6', borderRadius: '8px' }}>
              <strong>Q. {selectedInquiry.title}</strong>
              <p style={{ margin: '8px 0 0 0', fontSize: '14px' }}>{selectedInquiry.content}</p>
            </div>
            <textarea 
              className="input-field" 
              placeholder="답변 내용을 입력하세요"
              value={replyContent}
              onChange={(e) => setReplyContent(e.target.value)}
              style={{ minHeight: '120px', resize: 'vertical', padding: '16px', marginBottom: '24px' }}
            />
            <div style={{ display: 'flex', gap: '12px' }}>
              <button className="btn-outline" style={{ flex: 1, padding: '12px' }} onClick={() => setSelectedInquiry(null)}>취소</button>
              <button className="btn-primary" style={{ flex: 1, padding: '12px' }} onClick={handleReplyInquiry}>답변 등록</button>
            </div>
          </div>
        </div>
      )}

      {/* 유저 제재 모달 (네이버 스타일 구조) */}
      {selectedReport && (
        <div className="modal-overlay" style={{ zIndex: 1000 }}>
          <div className="glass-panel modal-content animate-fade-in" style={{ width: '550px', padding: '32px', borderRadius: '24px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '24px' }}>
              <h3 style={{ margin: 0, fontSize: '20px', color: '#DC2626' }}>활동 정지 대상 멤버 1</h3>
              <button className="btn-close" onClick={() => setSelectedReport(null)}><X size={24} /></button>
            </div>
            
            <div style={{ padding: '16px', backgroundColor: '#F9FAFB', borderRadius: '8px', border: '1px solid var(--color-border)', display: 'flex', flexDirection: 'column', gap: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <div style={{ width: '40px', height: '40px', borderRadius: '50%', backgroundColor: '#E5E7EB', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 'bold', color: '#9CA3AF' }}>
                  {selectedReport.reportedUser.charAt(0)}
                </div>
                <div style={{ flex: 1, fontSize: '15px', fontWeight: 'bold' }}>{selectedReport.reportedUser}</div>
                <div style={{ color: '#EF4444', fontWeight: 'bold', fontSize: '14px' }}>정지 1회</div>
              </div>
              
              <div style={{ borderTop: '1px dashed var(--color-border)', paddingTop: '12px' }}>
                <div style={{ fontSize: '13px', fontWeight: 'bold', color: 'var(--color-text-muted)', marginBottom: '8px' }}>과거 제재 기록</div>
                <ul style={{ margin: 0, paddingLeft: '20px', fontSize: '13px', color: 'var(--color-text-main)', lineHeight: '1.6' }}>
                  <li><strong>[2026-04-15]</strong> 욕설/비방 (글쓰기 7일 제한)</li>
                </ul>
              </div>
            </div>
            
            <p style={{ fontSize: '13px', color: 'var(--color-text-muted)', marginTop: '8px', marginBottom: '24px' }}>
              <AlertTriangle size={14} style={{ display: 'inline', verticalAlign: 'text-bottom', marginRight: '4px' }}/>
              스탭과 이미 활동 정지 상태인 멤버는 제외되었습니다.
            </p>

            <div style={{ marginBottom: '24px', border: '2px solid #EF4444', padding: '16px', borderRadius: '8px' }}>
              <label style={{ display: 'block', marginBottom: '16px', fontWeight: 'bold', fontSize: '16px' }}>활동 정지 사유</label>
              
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {[
                  '성인/도박 등 불법광고 및 스팸 활동',
                  '바람직하지 않은 활동 (광고, 도배, 욕설, 비방 등)',
                  '우리 카페 내 자체 운영 원칙에 위배되는 활동',
                  '기타'
                ].map(reason => (
                  <label key={reason} style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '14px' }}>
                    <input 
                      type="radio" 
                      name="suspendReason"
                      value={reason}
                      checked={suspendReason === reason}
                      onChange={() => setSuspendReason(reason)}
                      style={{ accentColor: '#EF4444', width: '16px', height: '16px' }}
                    />
                    {reason === '기타' ? '기타 - 한글 25자 이내로 작성해 주세요.' : reason}
                  </label>
                ))}
                
                {suspendReason === '기타' && (
                  <input 
                    type="text"
                    className="input-field"
                    style={{ marginLeft: '24px', width: 'calc(100% - 24px)', height: '36px' }}
                    value={suspendReasonOther}
                    onChange={(e) => setSuspendReasonOther(e.target.value)}
                    placeholder="사유를 입력해주세요"
                    maxLength={25}
                  />
                )}
              </div>
            </div>

            <div style={{ marginBottom: '32px' }}>
              <label style={{ display: 'block', marginBottom: '12px', fontWeight: 'bold', fontSize: '15px' }}>활동 정지 기간</label>
              <select 
                className="input-field"
                value={suspendDuration}
                onChange={(e) => setSuspendDuration(e.target.value)}
                style={{ cursor: 'pointer' }}
              >
                <option value="1일">1일</option>
                <option value="7일">7일</option>
                <option value="30일">30일</option>
                <option value="영구 정지">영구 정지</option>
              </select>
            </div>

            <div style={{ marginBottom: '24px', textAlign: 'center', fontWeight: 'bold', fontSize: '15px' }}>
              대상 멤버를 활동 정지 하시겠습니까?
            </div>

            <div style={{ display: 'flex', justifyContent: 'center', gap: '12px' }}>
              <button className="btn-primary" style={{ width: '120px', padding: '12px', backgroundColor: '#EF4444' }} onClick={handleSuspendUser}>활동정지</button>
              <button className="btn-outline" style={{ width: '120px', padding: '12px' }} onClick={() => setSelectedReport(null)}>취소</button>
            </div>
          </div>
        </div>
      )}
      )}
    </div>
  );
}