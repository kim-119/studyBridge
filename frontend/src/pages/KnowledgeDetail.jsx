import React, { useState, useEffect, useRef } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Heart, MessageSquare, Share2, FileText, Download, User, Flag, X, Pencil, Image as ImageIcon, Check } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import { knowledgeService } from '../services/api';

const REPORT_REASONS = [
  { value: 'SPAM', label: '스팸/광고' },
  { value: 'ABUSE', label: '욕설/비방' },
  { value: 'INAPPROPRIATE_CONTENT', label: '부적절한 콘텐츠' },
  { value: 'OTHER', label: '기타' },
];

export default function KnowledgeDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user, userId, userEmail } = useAuth();

  const [post, setPost] = useState(null);
  const [newComment, setNewComment] = useState('');

  // 글 수정 관련 상태
  const [showEditModal, setShowEditModal] = useState(false);
  const [editPost, setEditPost] = useState({ title: '', summary: '', tags: '' });
  const [editImageFile, setEditImageFile] = useState(null);
  const [editPdfFile, setEditPdfFile] = useState(null);
  const [editClearImage, setEditClearImage] = useState(false);
  const [editClearPdf, setEditClearPdf] = useState(false);
  const [editSubmitting, setEditSubmitting] = useState(false);
  const editImageRef = useRef(null);
  const editPdfRef = useRef(null);

  // 공유하기 상태
  const [shareCopied, setShareCopied] = useState(false);

  // 신고 관련 상태
  const [showReportModal, setShowReportModal] = useState(false);
  const [reportType, setReportType] = useState('post'); // 'post' | 'comment'
  const [reportTargetId, setReportTargetId] = useState(null);
  const [reportReason, setReportReason] = useState('SPAM');
  const [reportDetails, setReportDetails] = useState('');
  const [reportSubmitting, setReportSubmitting] = useState(false);

  const openReportModal = (type, targetId) => {
    if (!userId) {
      alert('로그인 후 이용해주세요.');
      return;
    }
    setReportType(type);
    setReportTargetId(targetId);
    setReportReason('SPAM');
    setReportDetails('');
    setShowReportModal(true);
  };

  const handleReportSubmit = async (e) => {
    e.preventDefault();
    if (reportSubmitting) return;
    setReportSubmitting(true);
    try {
      const payload = { reason: reportReason, details: reportDetails };
      if (reportType === 'post') {
        await knowledgeService.reportPost(reportTargetId, payload);
      } else {
        await knowledgeService.reportComment(reportTargetId, payload);
      }
      alert('신고가 정상적으로 접수되었습니다. 관리자 검토 후 조치 예정입니다.');
      setShowReportModal(false);
    } catch (error) {
      console.error('Failed to submit report:', error);
      alert(error.response?.data?.message || '신고 처리에 실패했습니다. 이미 신고했거나 본인의 글/댓글이 아닌지 확인해주세요.');
    } finally {
      setReportSubmitting(false);
    }
  };

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
        await knowledgeService.deleteComment(id, commentId);
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
        await knowledgeService.deletePost(id);
        alert("게시글이 삭제되었습니다.");
        navigate('/knowledge');
      } catch (error) {
        console.error("Failed to delete post:", error);
        alert("게시글 삭제에 실패했습니다.");
      }
    }
  };

  const openEditModal = () => {
    if (!post) return;
    const tags = (post.content?.match(/#\S+/g) || []).map(t => t.replace(/^#/, '')).join(', ');
    const summary = post.content?.replace(/#\S+/g, '').trim() || '';
    setEditPost({ title: post.title || '', summary, tags });
    setEditImageFile(null);
    setEditPdfFile(null);
    setEditClearImage(false);
    setEditClearPdf(false);
    setShowEditModal(true);
  };

  const handleEditSubmit = async () => {
    if (!editPost.title.trim() || !editPost.summary.trim()) {
      alert("제목과 내용을 입력해주세요.");
      return;
    }
    if (editSubmitting) return;
    setEditSubmitting(true);

    const tagsArray = editPost.tags.split(',')
      .map(tag => tag.trim())
      .filter(t => t)
      .map(t => t.startsWith('#') ? t : `#${t}`);

    const finalContent = tagsArray.length
      ? `${editPost.summary}\n\n${tagsArray.join(' ')}`
      : editPost.summary;

    try {
      const updated = await knowledgeService.updatePost(
        id,
        editPost.title,
        finalContent,
        editImageFile,
        editPdfFile,
        editClearImage,
        editClearPdf
      );
      setPost(updated);
      setShowEditModal(false);
    } catch (error) {
      console.error("Failed to update post:", error);
      alert(error.response?.data?.message || "글 수정에 실패했습니다.");
    } finally {
      setEditSubmitting(false);
    }
  };

  const handleShare = async () => {
    const url = window.location.href;
    try {
      if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(url);
      } else {
        const textarea = document.createElement('textarea');
        textarea.value = url;
        textarea.style.position = 'fixed';
        textarea.style.opacity = '0';
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();
        document.execCommand('copy');
        document.body.removeChild(textarea);
      }
      setShareCopied(true);
      setTimeout(() => setShareCopied(false), 2000);
    } catch (error) {
      console.error("Failed to copy share link:", error);
      window.prompt("아래 링크를 복사하세요:", url);
    }
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
  // 운영 관리 권한: 지정 관리 이메일 또는 ADMIN role (백엔드 BlogService.canManagePost와 정책 일치)
  const BLOG_MANAGER_EMAILS = ['dohy910@gmail.com'];
  const isModerator = (
    (userEmail && BLOG_MANAGER_EMAILS.includes(String(userEmail).trim().toLowerCase())) ||
    user?.role === 'ADMIN' || user?.role === 'ROLE_ADMIN'
  );
  const canManagePost = isMyPost || isModerator;

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
          
          {canManagePost && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              {isModerator && !isMyPost && (
                <span style={{ display: 'flex', alignItems: 'center', background: 'rgba(96,201,90,0.25)', backdropFilter: 'blur(4px)', color: '#bbf7d0', border: '1px solid rgba(96,201,90,0.4)', padding: '6px 12px', borderRadius: '12px', fontSize: '12px', fontWeight: '700' }}>
                  관리자 권한
                </span>
              )}
              <button
                onClick={openEditModal}
                style={{ display: 'flex', alignItems: 'center', gap: '8px', background: 'rgba(255,255,255,0.2)', backdropFilter: 'blur(4px)', color: 'white', border: '1px solid rgba(255,255,255,0.3)', padding: '10px 16px', borderRadius: '12px', cursor: 'pointer', fontWeight: '600', transition: '0.2s' }}
                onMouseEnter={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.3)'}
                onMouseLeave={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.2)'}
              >
                <Pencil size={16} />
                수정하기
              </button>
              <button
                onClick={handleDeletePost}
                style={{ display: 'flex', alignItems: 'center', gap: '8px', background: 'rgba(239,68,68,0.2)', backdropFilter: 'blur(4px)', color: '#F87171', border: '1px solid rgba(239,68,68,0.3)', padding: '10px 16px', borderRadius: '12px', cursor: 'pointer', fontWeight: '600', transition: '0.2s' }}
                onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(239,68,68,0.4)'; e.currentTarget.style.color = 'white'; }}
                onMouseLeave={(e) => { e.currentTarget.style.background = 'rgba(239,68,68,0.2)'; e.currentTarget.style.color = '#F87171'; }}
              >
                삭제하기
              </button>
            </div>
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
            <button
              onClick={handleShare}
              style={{ padding: '12px 32px', display: 'flex', alignItems: 'center', gap: '8px', backgroundColor: shareCopied ? '#ECFDF5' : 'white', border: shareCopied ? '2px solid #60C95A' : '2px solid #E5E7EB', color: shareCopied ? '#387235' : '#4B5563', borderRadius: '40px', fontSize: '16px', fontWeight: '700', cursor: 'pointer', transition: 'all 0.2s' }}
            >
              {shareCopied ? <Check size={20} /> : <Share2 size={20} />}
              {shareCopied ? '링크 복사됨' : '공유하기'}
            </button>
            {!isMyPost && userId && (
              <button
                onClick={() => openReportModal('post', post.blogId)}
                style={{ padding: '12px 32px', display: 'flex', alignItems: 'center', gap: '8px', backgroundColor: 'white', border: '2px solid #FCA5A5', color: '#EF4444', borderRadius: '40px', fontSize: '16px', fontWeight: '700', cursor: 'pointer', transition: 'all 0.2s' }}
              >
                <Flag size={20} />
                신고하기
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
                  onMouseEnter={(e) => { if(newComment.trim()) e.currentTarget.style.backgroundColor = '#387235' }}
                  onMouseLeave={(e) => { if(newComment.trim()) e.currentTarget.style.backgroundColor = '#60C95A' }}
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
                  </div>
                  <div style={{ color: '#4B5563', fontSize: '15px', lineHeight: '1.6' }}>
                    {comment.content}
                  </div>
                  {isMyComment ? (
                    <button
                      onClick={() => handleDeleteComment(comment.commentId)}
                      style={{ position: 'absolute', right: '0', top: '0', background: 'none', border: 'none', color: '#EF4444', fontSize: '13px', cursor: 'pointer', padding: '4px', fontWeight: 'bold' }}
                    >
                      삭제
                    </button>
                  ) : (
                    userId && (
                      <button
                        onClick={() => openReportModal('comment', comment.commentId)}
                        style={{ position: 'absolute', right: '0', top: '0', display: 'flex', alignItems: 'center', gap: '4px', background: 'none', border: 'none', color: '#9CA3AF', fontSize: '13px', cursor: 'pointer', padding: '4px', fontWeight: 'bold' }}
                      >
                        <Flag size={13} /> 신고
                      </button>
                    )
                  )}
                </div>
              </div>
            )})}
          </div>

        </div>
      </div>

      {/* 글 수정 모달 */}
      {showEditModal && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100000, padding: '20px' }} onClick={() => setShowEditModal(false)}>
          <div style={{ backgroundColor: '#FFFFFF', borderRadius: '12px', width: '100%', maxWidth: '800px', maxHeight: '90vh', overflowY: 'auto', display: 'flex', flexDirection: 'column' }} onClick={(e) => e.stopPropagation()}>
            <div style={{ padding: '32px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #E5E7EB', paddingBottom: '16px' }}>
                <h2 style={{ fontSize: '20px', fontWeight: 'bold', color: '#111827', margin: 0 }}>지식 글 수정</h2>
                <button onClick={() => setShowEditModal(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6B7280' }}><X size={24} /></button>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '14px', fontWeight: 'bold', color: '#111827', marginBottom: '8px' }}>제목</label>
                  <input
                    type="text"
                    placeholder="글 제목을 입력하세요."
                    value={editPost.title}
                    onChange={(e) => setEditPost({ ...editPost, title: e.target.value })}
                    style={{ width: '100%', height: '40px', boxSizing: 'border-box', padding: '0 16px', borderRadius: '8px', border: '1px solid #D1D5DB', fontSize: '14px', outline: 'none' }}
                    onFocus={(e) => e.target.style.border = '1px solid #60C95A'}
                    onBlur={(e) => e.target.style.border = '1px solid #D1D5DB'}
                  />
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: '14px', fontWeight: 'bold', color: '#111827', marginBottom: '8px' }}>해시태그</label>
                  <input
                    type="text"
                    placeholder="쉼표(,)로 구분하여 해시태그를 입력하세요. 예: 로드맵, 코딩테스트"
                    value={editPost.tags}
                    onChange={(e) => setEditPost({ ...editPost, tags: e.target.value })}
                    style={{ width: '100%', height: '40px', boxSizing: 'border-box', padding: '0 16px', borderRadius: '8px', border: '1px solid #D1D5DB', fontSize: '14px', outline: 'none' }}
                    onFocus={(e) => e.target.style.border = '1px solid #60C95A'}
                    onBlur={(e) => e.target.style.border = '1px solid #D1D5DB'}
                  />
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: '14px', fontWeight: 'bold', color: '#111827', marginBottom: '8px' }}>내용</label>
                  <textarea
                    placeholder="나만의 로드맵, 노하우, 공부 자료를 상세히 공유해주세요."
                    value={editPost.summary}
                    onChange={(e) => setEditPost({ ...editPost, summary: e.target.value })}
                    style={{ width: '100%', boxSizing: 'border-box', padding: '16px', borderRadius: '8px', border: '1px solid #D1D5DB', fontSize: '14px', outline: 'none', minHeight: '200px', resize: 'vertical', lineHeight: '1.6' }}
                    onFocus={(e) => e.target.style.border = '1px solid #60C95A'}
                    onBlur={(e) => e.target.style.border = '1px solid #D1D5DB'}
                  />
                </div>

                {/* 첨부 파일 섹션 */}
                <div>
                  <label style={{ display: 'block', fontSize: '14px', fontWeight: 'bold', color: '#111827', marginBottom: '8px' }}>자료 첨부 (PDF, 이미지)</label>
                  <div style={{ display: 'flex', gap: '16px' }}>
                    <input type="file" ref={editPdfRef} accept="application/pdf" style={{ display: 'none' }} onChange={(e) => { setEditPdfFile(e.target.files[0]); setEditClearPdf(false); }} />
                    <input type="file" ref={editImageRef} accept="image/*" style={{ display: 'none' }} onChange={(e) => { setEditImageFile(e.target.files[0]); setEditClearImage(false); }} />
                    <button onClick={() => editPdfRef.current.click()} style={{ flex: 1, padding: '24px', backgroundColor: '#F3F4F6', border: '1px dashed #D1D5DB', borderRadius: '8px', cursor: 'pointer', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px', color: '#6B7280', transition: '0.2s' }} onMouseEnter={(e) => e.currentTarget.style.borderColor = '#60C95A'} onMouseLeave={(e) => e.currentTarget.style.borderColor = '#D1D5DB'}>
                      <FileText size={28} color={editPdfFile || (post.pdfPresignedUrl && !editClearPdf) ? "#60C95A" : "#6B7280"} />
                      <span style={{ fontSize: '12px', fontWeight: 'bold', color: editPdfFile || (post.pdfPresignedUrl && !editClearPdf) ? "#111827" : "#6B7280" }}>{editPdfFile ? editPdfFile.name : (post.pdfPresignedUrl && !editClearPdf ? '기존 PDF 첨부됨' : 'PDF 업로드')}</span>
                    </button>
                    <button onClick={() => editImageRef.current.click()} style={{ flex: 1, padding: '24px', backgroundColor: '#F3F4F6', border: '1px dashed #D1D5DB', borderRadius: '8px', cursor: 'pointer', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px', color: '#6B7280', transition: '0.2s' }} onMouseEnter={(e) => e.currentTarget.style.borderColor = '#60C95A'} onMouseLeave={(e) => e.currentTarget.style.borderColor = '#D1D5DB'}>
                      <ImageIcon size={28} color={editImageFile || (post.imagePresignedUrl && !editClearImage) ? "#60C95A" : "#6B7280"} />
                      <span style={{ fontSize: '12px', fontWeight: 'bold', color: editImageFile || (post.imagePresignedUrl && !editClearImage) ? "#111827" : "#6B7280" }}>{editImageFile ? editImageFile.name : (post.imagePresignedUrl && !editClearImage ? '기존 사진 첨부됨' : '사진 업로드')}</span>
                    </button>
                  </div>
                  {/* 기존 첨부 제거 옵션 */}
                  <div style={{ display: 'flex', gap: '20px', marginTop: '12px' }}>
                    {post.pdfPresignedUrl && !editPdfFile && (
                      <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', color: '#6B7280', cursor: 'pointer' }}>
                        <input type="checkbox" checked={editClearPdf} onChange={(e) => setEditClearPdf(e.target.checked)} />
                        기존 PDF 삭제
                      </label>
                    )}
                    {post.imagePresignedUrl && !editImageFile && (
                      <label style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '13px', color: '#6B7280', cursor: 'pointer' }}>
                        <input type="checkbox" checked={editClearImage} onChange={(e) => setEditClearImage(e.target.checked)} />
                        기존 사진 삭제
                      </label>
                    )}
                  </div>
                </div>
              </div>

              {/* 하단 버튼 */}
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px', marginTop: '16px', paddingTop: '16px', borderTop: '1px solid #E5E7EB' }}>
                <button
                  onClick={() => setShowEditModal(false)}
                  style={{ width: '80px', height: '40px', backgroundColor: '#FFFFFF', color: '#111827', border: '1px solid #E5E7EB', borderRadius: '8px', fontSize: '14px', cursor: 'pointer' }}
                >
                  취소
                </button>
                <button
                  onClick={handleEditSubmit}
                  disabled={editSubmitting}
                  style={{ minWidth: '80px', height: '40px', padding: '0 16px', backgroundColor: editSubmitting ? '#9CA3AF' : '#60C95A', color: 'white', border: 'none', borderRadius: '8px', fontSize: '14px', cursor: editSubmitting ? 'not-allowed' : 'pointer' }}
                  onMouseEnter={(e) => { if (!editSubmitting) e.currentTarget.style.backgroundColor = '#387235'; }}
                  onMouseLeave={(e) => { if (!editSubmitting) e.currentTarget.style.backgroundColor = '#60C95A'; }}
                >
                  {editSubmitting ? '저장 중...' : '수정 완료'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* 신고 모달 */}
      {showReportModal && (
        <div
          style={{ position: 'fixed', inset: 0, backgroundColor: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000, padding: '20px' }}
          onClick={() => setShowReportModal(false)}
        >
          <div
            style={{ backgroundColor: 'white', borderRadius: '16px', width: '100%', maxWidth: '480px', overflow: 'hidden' }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '20px 24px', borderBottom: '1px solid #E5E7EB' }}>
              <h3 style={{ fontSize: '18px', fontWeight: 'bold', margin: 0 }}>{reportType === 'post' ? '게시글 신고' : '댓글 신고'}</h3>
              <button onClick={() => setShowReportModal(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6B7280' }}>
                <X size={20} />
              </button>
            </div>
            <form onSubmit={handleReportSubmit} style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
              <div style={{ padding: '12px 16px', backgroundColor: '#FEF2F2', borderRadius: '8px', fontSize: '13px', color: '#991B1B', lineHeight: '1.5' }}>
                신고된 내용은 관리자 검토를 통해 확인하며, 허위 신고 시 서비스 이용에 제한을 받을 수 있습니다.
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '14px', fontWeight: 'bold', color: '#374151', marginBottom: '8px' }}>신고 사유 선택</label>
                <select
                  value={reportReason}
                  onChange={(e) => setReportReason(e.target.value)}
                  style={{ width: '100%', boxSizing: 'border-box', padding: '12px', borderRadius: '8px', border: '1px solid #D1D5DB', fontSize: '15px', outline: 'none', backgroundColor: 'white' }}
                >
                  {REPORT_REASONS.map((r) => (
                    <option key={r.value} value={r.value}>{r.label}</option>
                  ))}
                </select>
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '14px', fontWeight: 'bold', color: '#374151', marginBottom: '8px' }}>상세 사유 (선택)</label>
                <textarea
                  value={reportDetails}
                  onChange={(e) => setReportDetails(e.target.value)}
                  placeholder="신고 사유를 상세하게 작성해주세요."
                  style={{ width: '100%', boxSizing: 'border-box', padding: '12px', borderRadius: '8px', border: '1px solid #D1D5DB', fontSize: '15px', outline: 'none', resize: 'vertical', minHeight: '90px' }}
                />
              </div>
              <button
                type="submit"
                disabled={reportSubmitting}
                style={{ padding: '14px', backgroundColor: reportSubmitting ? '#9CA3AF' : '#EF4444', color: 'white', border: 'none', borderRadius: '8px', fontSize: '16px', fontWeight: 'bold', cursor: reportSubmitting ? 'not-allowed' : 'pointer' }}
              >
                신고 접수
              </button>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}
