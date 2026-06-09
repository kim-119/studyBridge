import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Heart, MessageSquare, Share2, FileText, Download, User, AlertTriangle, ShieldAlert, X } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import { knowledgeService, adminService } from '../services/api';

export default function KnowledgeDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user, userId } = useAuth();

  const [post, setPost] = useState(null);
  const [newComment, setNewComment] = useState('');

  // 어드민 계정 여부 확인
  const isAdmin = user?.role === 'ADMIN' ||
    user?.displayName === '시스템 관리자' ||
    (user?.email && user.email.split('@')[0] === 'admin');

  // 신고 관련 상태
  const [isReportModalOpen, setIsReportModalOpen] = useState(false);
  const [reportType, setReportType] = useState('post'); // 'post' 또는 'comment'
  const [targetId, setTargetId] = useState(null);
  const [reportReason, setReportReason] = useState('부적절한 홍보 및 스팸');
  const [customReason, setCustomReason] = useState('');

  useEffect(() => {
    fetchPostDetail();
  }, [id]);

  const fetchPostDetail = async () => {
    try {
      const data = await knowledgeService.getPostDetail(id);
      setPost(data);
    } catch (error) {
      console.error("Failed to fetch post detail:", error);
      alert("게시글을 불러올 수 없습니다.");
      navigate('/knowledge');
    }
  };

  const handleLike = async () => {
    try {
      const updatedPost = await knowledgeService.toggleLike(id);
      setPost(updatedPost);
    } catch (error) {
      console.error("Failed to toggle like:", error);
      alert("좋아요 처리에 실패했습니다. 로그인 상태를 확인해주세요.");
    }
  };

  const handleAddComment = async (e) => {
    e.preventDefault();
    if (!newComment.trim()) return;
    try {
      await knowledgeService.addComment(id, newComment);
      setNewComment('');
      fetchPostDetail();
    } catch (error) {
      console.error("Failed to add comment:", error);
      alert("댓글 작성에 실패했습니다.");
    }
  };

  const handleDeleteComment = async (commentId) => {
    if (window.confirm("정말로 이 댓글을 삭제하시겠습니까?")) {
      try {
        if (isAdmin) {
          await adminService.deleteComment(commentId);
        } else {
          await knowledgeService.deleteComment(id, commentId);
        }
        fetchPostDetail();
      } catch (error) {
        console.error("Failed to delete comment:", error);
        alert("댓글 삭제에 실패했습니다.");
      }
    }
  };

  const handleDeletePost = async () => {
    if (window.confirm("정말로 이 게시글을 삭제하시겠습니까?")) {
      try {
        if (isAdmin) {
          await adminService.deletePost(id);
        } else {
          await knowledgeService.deletePost(id);
        }
        alert("게시글이 삭제되었습니다.");
        navigate('/knowledge');
      } catch (error) {
        console.error("Failed to delete post:", error);
        alert("게시글 삭제에 실패했습니다.");
      }
    }
  };

  const handleOpenReportModal = (type, targetId) => {
    if (!userId) {
      alert("로그인 후 이용 가능합니다.");
      navigate('/login');
      return;
    }
    setReportType(type);
    setTargetId(targetId);
    setReportReason('부적절한 홍보 및 스팸');
    setCustomReason('');
    setIsReportModalOpen(true);
  };

  const handleReportSubmit = (e) => {
    e.preventDefault();
    const finalReason = reportReason === '기타' ? customReason : reportReason;
    if (reportReason === '기타' && !customReason.trim()) {
      alert('신고 사유를 입력해주세요.');
      return;
    }

    console.log(`[DUMMY REPORT] Type: ${reportType}, Target ID: ${targetId}, Reason: ${finalReason}`);
    alert('신고가 정상적으로 접수되었습니다. 관리자 검토 후 조치 예정입니다.');
    setIsReportModalOpen(false);
  };


  if (!post) {
    return <div style={{ padding: '40px', textAlign: 'center', fontFamily: '"Malgun Gothic", sans-serif' }}>로딩 중...</div>;
  }

  const extractTags = (content) => {
    return content?.match(/#\S+/g) || [];
  };

  const stripTags = (content) => {
    return content?.replace(/#\S+/g, '').trim() || '';
  };

  const getThumbnail = () => {
    if (post.imagePresignedUrl) return post.imagePresignedUrl;
    const unsplashUrls = [
      'https://images.unsplash.com/photo-1517694712202-14dd9538aa97?ixlib=rb-4.0.3&auto=format&fit=crop&w=1200&q=80',
      'https://images.unsplash.com/photo-1526379095098-d400fd0bfce8?ixlib=rb-4.0.3&auto=format&fit=crop&w=600&q=80',
      'https://images.unsplash.com/photo-1434030216411-0b793f4b4173?ixlib=rb-4.0.3&auto=format&fit=crop&w=600&q=80',
      'https://images.unsplash.com/photo-1561070791-2526d30994b5?ixlib=rb-4.0.3&auto=format&fit=crop&w=600&q=80',
      'https://images.unsplash.com/photo-1456324504439-367cee3b3c32?ixlib=rb-4.0.3&auto=format&fit=crop&w=600&q=80'
    ];
    return unsplashUrls[(post.blogId || 0) % unsplashUrls.length];
  };

  const hashtags = extractTags(post.content);
  const cleanContent = stripTags(post.content);

  const formatDate = (dateString) => {
    if (!dateString) return '';
    return new Date(dateString).toLocaleDateString();
  };

  const formatCommentDate = (dateString) => {
    if (!dateString) return '';
    const date = new Date(dateString);
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')} ${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
  };

  const isLiked = post.likedByCurrentUser;
  const isMyPost = post && userId && (String(post.authorId) === String(userId));

  return (
    <div style={{ backgroundColor: '#F9FAFB', minHeight: '100vh', paddingBottom: '80px', fontFamily: '"Malgun Gothic", "맑은 고딕", sans-serif' }}>

      {/* 썸네일 헤더 영역 */}
      <div style={{ width: '100%', height: '400px', position: 'relative', overflow: 'hidden' }}>
        <img src={getThumbnail()} alt={post.title} style={{ width: '100%', height: '100%', objectFit: 'cover', filter: 'brightness(0.6)' }} />
        <div style={{ position: 'absolute', top: '40px', left: '0', right: '0', maxWidth: '800px', margin: '0 auto', padding: '0 20px', zIndex: 10, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <button
            onClick={() => navigate('/knowledge')}
            style={{ display: 'flex', alignItems: 'center', gap: '8px', background: 'rgba(255,255,255,0.2)', backdropFilter: 'blur(4px)', color: 'white', border: '1px solid rgba(255,255,255,0.3)', padding: '10px 16px', borderRadius: '12px', cursor: 'pointer', fontWeight: '600', transition: '0.2s' }}
            onMouseEnter={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.3)'}
            onMouseLeave={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.2)'}
          >
            <ArrowLeft size={18} />
            목록으로
          </button>

          {(isMyPost || isAdmin) && (
            <button
              onClick={handleDeletePost}
              style={{ display: 'flex', alignItems: 'center', gap: '8px', background: 'rgba(239,68,68,0.2)', backdropFilter: 'blur(4px)', color: '#F87171', border: '1px solid rgba(239,68,68,0.3)', padding: '10px 16px', borderRadius: '12px', cursor: 'pointer', fontWeight: '600', transition: '0.2s' }}
              onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(239,68,68,0.4)'; e.currentTarget.style.color = 'white'; }}
              onMouseLeave={(e) => { e.currentTarget.style.background = 'rgba(239,68,68,0.2)'; e.currentTarget.style.color = '#F87171'; }}
            >
              삭제하기
            </button>
          )}
        </div>
        <div style={{ position: 'absolute', bottom: '40px', left: '0', right: '0', maxWidth: '800px', margin: '0 auto', padding: '0 20px', color: 'white', zIndex: 10 }}>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '16px' }}>
            {hashtags.map(tag => (
              <span key={tag} style={{ backgroundColor: '#60C95A', padding: '4px 12px', borderRadius: '16px', fontSize: '14px', fontWeight: 'bold' }}>{tag}</span>
            ))}
          </div>
          <h1 style={{ fontSize: '36px', fontWeight: 'bold', margin: '0 0 16px', lineHeight: '1.3' }}>{post.title}</h1>
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px', fontSize: '15px', color: 'rgba(255,255,255,0.9)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              {post.authorPhotoUrl ? (
                <img src={post.authorPhotoUrl} alt="author" style={{ width: '28px', height: '28px', borderRadius: '50%', objectFit: 'cover' }} />
              ) : (
                <div style={{ width: '28px', height: '28px', borderRadius: '50%', backgroundColor: '#60C95A', color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '12px', fontWeight: 'bold' }}>
                  {post.authorNickname ? post.authorNickname.charAt(0) : 'U'}
                </div>
              )}
              <span style={{ fontWeight: '700' }}>{post.authorNickname}</span>
            </div>
            <span>•</span>
            <span>{formatDate(post.createdAt)}</span>
            <span>•</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><Heart size={16} fill={isLiked ? "white" : "none"} /> {post.likeCount}</div>
          </div>
        </div>
      </div>

      <div style={{ maxWidth: '800px', margin: '0 auto', padding: '40px 20px' }}>

        {/* 본문 콘텐츠 */}
        <div style={{ backgroundColor: 'white', borderRadius: '24px', padding: '40px', boxShadow: '0 4px 20px rgba(0,0,0,0.03)', marginBottom: '32px' }}>
          <div style={{ fontSize: '17px', color: '#374151', lineHeight: '1.8', whiteSpace: 'pre-wrap' }}>
            {cleanContent}
          </div>

          {/* Attached S3 Image Rendering */}
          {post.imagePresignedUrl && (
            <div style={{ marginTop: '32px', textAlign: 'center' }}>
              <img
                src={post.imagePresignedUrl}
                alt="Attached Resource"
                style={{
                  maxWidth: '100%',
                  maxHeight: '500px',
                  borderRadius: '12px',
                  boxShadow: '0 4px 20px rgba(0,0,0,0.08)'
                }}
              />
            </div>
          )}

          {/* 첨부파일 영역 */}
          {post.pdfPresignedUrl && (
            <div style={{ marginTop: '40px', paddingTop: '32px', borderTop: '1px solid #E5E7EB' }}>
              <h3 style={{ fontSize: '18px', fontWeight: '700', color: '#111827', margin: '0 0 16px' }}>첨부 자료</h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 20px', backgroundColor: '#F3F4F6', borderRadius: '12px', border: '1px solid #E5E7EB' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                    <div style={{ padding: '10px', backgroundColor: '#EF4444', color: 'white', borderRadius: '8px' }}>
                      <FileText size={20} />
                    </div>
                    <div>
                      <div style={{ fontSize: '15px', fontWeight: '600', color: '#111827', marginBottom: '4px' }}>PDF 첨부파일</div>
                    </div>
                  </div>
                  <a href={post.pdfPresignedUrl} target="_blank" rel="noreferrer" style={{ textDecoration: 'none' }}>
                    <button style={{ padding: '8px 16px', display: 'flex', alignItems: 'center', gap: '6px', backgroundColor: 'white', border: '1px solid #D1D5DB', borderRadius: '8px', cursor: 'pointer', fontWeight: '600', color: '#4B5563', transition: '0.2s' }} onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = '#F9FAFB'; e.currentTarget.style.borderColor = '#9CA3AF' }} onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'white'; e.currentTarget.style.borderColor = '#D1D5DB' }}>
                      <Download size={16} /> 다운로드
                    </button>
                  </a>
                </div>
              </div>
            </div>
          )}

          {/* 액션 버튼 */}
          <div style={{ display: 'flex', justifyContent: 'center', gap: '16px', marginTop: '48px' }}>
            <button
              onClick={handleLike}
              style={{ padding: '12px 32px', display: 'flex', alignItems: 'center', gap: '8px', backgroundColor: isLiked ? '#FEE2E2' : 'white', border: isLiked ? '2px solid #EF4444' : '2px solid #E5E7EB', color: isLiked ? '#EF4444' : '#4B5563', borderRadius: '40px', fontSize: '16px', fontWeight: '700', cursor: 'pointer', transition: 'all 0.2s' }}
            >
              <Heart size={20} fill={isLiked ? "#EF4444" : "none"} />
              도움이 되었어요 {post.likeCount}
            </button>
            <button style={{ padding: '12px 32px', display: 'flex', alignItems: 'center', gap: '8px', backgroundColor: 'white', border: '2px solid #E5E7EB', color: '#4B5563', borderRadius: '40px', fontSize: '16px', fontWeight: '700', cursor: 'pointer', transition: 'all 0.2s' }}>
              <Share2 size={20} />
              공유하기
            </button>
            {!isMyPost && !isAdmin && (
              <button
                onClick={() => handleOpenReportModal('post', post.blogId)}
                style={{ padding: '12px 32px', display: 'flex', alignItems: 'center', gap: '8px', backgroundColor: 'white', border: '2px solid #E5E7EB', color: '#EF4444', borderRadius: '40px', fontSize: '16px', fontWeight: '700', cursor: 'pointer', transition: 'all 0.2s' }}
                onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = '#FEF2F2'; e.currentTarget.style.borderColor = '#FCA5A5'; }}
                onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'white'; e.currentTarget.style.borderColor = '#E5E7EB'; }}
              >
                <AlertTriangle size={20} />
                신고
              </button>
            )}
          </div>
        </div>

        {/* 댓글 섹션 */}
        <div style={{ backgroundColor: 'white', borderRadius: '24px', padding: '40px', boxShadow: '0 4px 20px rgba(0,0,0,0.03)' }}>
          <h3 style={{ fontSize: '20px', fontWeight: 'bold', color: '#111827', margin: '0 0 24px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            댓글 <span style={{ color: '#60C95A' }}>{post.comments?.length || 0}</span>
          </h3>

          {/* 댓글 입력 폼 */}
          <form onSubmit={handleAddComment} style={{ marginBottom: '40px' }}>
            <div style={{ display: 'flex', gap: '16px', alignItems: 'flex-start' }}>
              <div style={{ width: '40px', height: '40px', borderRadius: '50%', backgroundColor: '#E5E7EB', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }}>
                {user?.photoUrl ? (
                  <img src={user.photoUrl} alt="my avatar" style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                ) : (
                  <User size={20} color="#9CA3AF" />
                )}
              </div>
              <div style={{ flex: 1, position: 'relative' }}>
                <textarea
                  placeholder="댓글을 남겨보세요..."
                  value={newComment}
                  onChange={(e) => setNewComment(e.target.value)}
                  style={{ width: '100%', boxSizing: 'border-box', padding: '16px', borderRadius: '12px', border: '1px solid #D1D5DB', fontSize: '15px', outline: 'none', resize: 'vertical', minHeight: '100px', backgroundColor: '#F9FAFB' }}
                />
                <button
                  type="submit"
                  disabled={!newComment.trim()}
                  style={{ position: 'absolute', right: '16px', bottom: '16px', padding: '8px 20px', backgroundColor: newComment.trim() ? '#60C95A' : '#9CA3AF', color: 'white', borderRadius: '8px', border: 'none', fontWeight: 'bold', cursor: newComment.trim() ? 'pointer' : 'not-allowed', transition: '0.2s' }}
                  onMouseEnter={(e) => { if (newComment.trim()) e.currentTarget.style.backgroundColor = '#387235' }}
                  onMouseLeave={(e) => { if (newComment.trim()) e.currentTarget.style.backgroundColor = '#60C95A' }}
                >
                  등록
                </button>
              </div>
            </div>
          </form>

          {/* 댓글 리스트 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
            {post.comments?.map(comment => {
              const isMyComment = user && (comment.authorNickname === user.displayName || comment.authorNickname === user.nickname);
              return (
                <div key={comment.commentId} style={{ display: 'flex', gap: '16px' }}>
                  {comment.authorPhotoUrl ? (
                    <img src={comment.authorPhotoUrl} alt="author" style={{ width: '40px', height: '40px', borderRadius: '50%', objectFit: 'cover', flexShrink: 0 }} />
                  ) : (
                    <div style={{ width: '40px', height: '40px', borderRadius: '50%', backgroundColor: '#111827', color: 'white', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: '700', fontSize: '14px' }}>
                      {comment.authorNickname ? comment.authorNickname.charAt(0) : 'U'}
                    </div>
                  )}
                  <div style={{ flex: 1, position: 'relative' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '8px' }}>
                      <span style={{ fontWeight: '700', color: '#111827', fontSize: '15px' }}>{comment.authorNickname}</span>
                      <span style={{ fontSize: '13px', color: '#9CA3AF' }}>{formatCommentDate(comment.createdAt)}</span>
                      {!isMyComment && !isAdmin && (
                        <button
                          onClick={() => handleOpenReportModal('comment', comment.commentId)}
                          style={{ background: 'none', border: 'none', color: '#9CA3AF', fontSize: '12px', cursor: 'pointer', padding: '0 4px', fontWeight: '600', transition: 'color 0.2s', display: 'flex', alignItems: 'center', gap: '2px' }}
                          onMouseEnter={(e) => e.currentTarget.style.color = '#EF4444'}
                          onMouseLeave={(e) => e.currentTarget.style.color = '#9CA3AF'}
                        >
                          <AlertTriangle size={12} />
                          신고
                        </button>
                      )}
                    </div>
                    <div style={{ color: '#4B5563', fontSize: '15px', lineHeight: '1.6' }}>
                      {comment.content}
                    </div>
                    {(isMyComment || isAdmin) && (
                      <button
                        onClick={() => handleDeleteComment(comment.commentId)}
                        style={{ position: 'absolute', right: '0', top: '0', background: 'none', border: 'none', color: '#EF4444', fontSize: '13px', cursor: 'pointer', padding: '4px', fontWeight: 'bold' }}
                      >
                        삭제
                      </button>
                    )}
                  </div>
                </div>
              )
            })}
          </div>

        </div>
      </div>

      {/* 신고 모달 */}
      {isReportModalOpen && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100000, padding: '20px' }} onClick={() => setIsReportModalOpen(false)}>
          <div style={{ backgroundColor: '#FFFFFF', borderRadius: '16px', width: '100%', maxWidth: '480px', overflow: 'hidden', boxShadow: '0 20px 25px -5px rgba(0,0,0,0.1), 0 10px 10px -5px rgba(0,0,0,0.04)', animation: 'slideUp 0.2s ease-out' }} onClick={(e) => e.stopPropagation()}>

            {/* 헤더 */}
            <div style={{ padding: '20px 24px', borderBottom: '1px solid #F3F4F6', display: 'flex', justifyContent: 'space-between', alignItems: 'center', backgroundColor: '#FEF2F2' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: '#DC2626' }}>
                <ShieldAlert size={20} />
                <h3 style={{ fontSize: '18px', fontWeight: 'bold', margin: 0 }}>{reportType === 'post' ? '게시글 신고' : '댓글 신고'}</h3>
              </div>
              <button onClick={() => setIsReportModalOpen(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#9CA3AF', transition: 'color 0.2s' }} onMouseEnter={(e) => e.currentTarget.style.color = '#4B5563'} onMouseLeave={(e) => e.currentTarget.style.color = '#9CA3AF'}>
                <X size={20} />
              </button>
            </div>

            {/* 본문 */}
            <form onSubmit={handleReportSubmit} style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
              <div style={{ backgroundColor: '#FFFBEB', border: '1px solid #FEF3C7', borderRadius: '8px', padding: '12px 16px', fontSize: '13px', color: '#B45309', display: 'flex', alignItems: 'flex-start', gap: '8px', lineHeight: '1.5' }}>
                <AlertTriangle size={16} style={{ flexShrink: 0, marginTop: '2px' }} />
                <span>
                  신고된 내용은 관리자 검토를 통해 확인하며, 허위 신고 시 서비스 이용에 제한을 받을 수 있습니다.
                </span>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '14px', fontWeight: 'bold', color: '#374151', marginBottom: '8px' }}>신고 사유 선택</label>
                <select
                  value={reportReason}
                  onChange={(e) => setReportReason(e.target.value)}
                  style={{ width: '100%', height: '42px', padding: '0 12px', borderRadius: '8px', border: '1px solid #D1D5DB', fontSize: '14px', outline: 'none', backgroundColor: 'white' }}
                >
                  <option value="부적절한 홍보 및 스팸">부적절한 홍보 및 스팸</option>
                  <option value="욕설, 비방 및 면학분위기 저해">욕설, 비방 및 면학분위기 저해</option>
                  <option value="음란성 또는 유해한 콘텐츠">음란성 또는 유해한 콘텐츠</option>
                  <option value="도배 및 광고성 댓글">도배 및 광고성 댓글</option>
                  <option value="기타">기타 (직접 입력)</option>
                </select>
              </div>

              {reportReason === '기타' && (
                <div>
                  <label style={{ display: 'block', fontSize: '14px', fontWeight: 'bold', color: '#374151', marginBottom: '8px' }}>상세 사유 입력</label>
                  <textarea
                    placeholder="신고 사유를 상세하게 작성해주세요."
                    value={customReason}
                    onChange={(e) => setCustomReason(e.target.value)}
                    style={{ width: '100%', boxSizing: 'border-box', padding: '12px', borderRadius: '8px', border: '1px solid #D1D5DB', fontSize: '14px', outline: 'none', resize: 'vertical', minHeight: '80px' }}
                    required
                  />
                </div>
              )}

              {/* 푸터 버튼 */}
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px', marginTop: '12px' }}>
                <button type="button" onClick={() => setIsReportModalOpen(false)} style={{ padding: '10px 18px', backgroundColor: '#FFFFFF', color: '#4B5563', border: '1px solid #D1D5DB', borderRadius: '8px', fontSize: '14px', fontWeight: 'bold', cursor: 'pointer', transition: 'background-color 0.2s' }} onMouseEnter={(e) => e.currentTarget.style.backgroundColor = '#F9FAFB'} onMouseLeave={(e) => e.currentTarget.style.backgroundColor = '#FFFFFF'}>
                  취소
                </button>
                <button type="submit" style={{ padding: '10px 18px', backgroundColor: '#EF4444', color: 'white', border: 'none', borderRadius: '8px', fontSize: '14px', fontWeight: 'bold', cursor: 'pointer', transition: 'background-color 0.2s' }} onMouseEnter={(e) => e.currentTarget.style.backgroundColor = '#DC2626'} onMouseLeave={(e) => e.currentTarget.style.backgroundColor = '#EF4444'}>
                  신고 접수
                </button>
              </div>
            </form>

          </div>
        </div>
      )}
    </div>
  );
}
