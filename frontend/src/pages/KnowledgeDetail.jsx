import React, { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ArrowLeft, Heart, MessageSquare, Share2, FileText, Download, User } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import { knowledgeService } from '../services/api';

export default function KnowledgeDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  
  const [post, setPost] = useState(null);
  const [newComment, setNewComment] = useState('');

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

  return (
    <div style={{ backgroundColor: '#F9FAFB', minHeight: '100vh', paddingBottom: '80px', fontFamily: '"Malgun Gothic", "맑은 고딕", sans-serif' }}>
      
      {/* 썸네일 헤더 영역 */}
      <div style={{ width: '100%', height: '400px', position: 'relative', overflow: 'hidden' }}>
        <img src={getThumbnail()} alt={post.title} style={{ width: '100%', height: '100%', objectFit: 'cover', filter: 'brightness(0.6)' }} />
        <div style={{ position: 'absolute', top: '40px', left: '0', right: '0', maxWidth: '800px', margin: '0 auto', padding: '0 20px', zIndex: 10 }}>
          <button 
            onClick={() => navigate('/knowledge')}
            style={{ display: 'flex', alignItems: 'center', gap: '8px', background: 'rgba(255,255,255,0.2)', backdropFilter: 'blur(4px)', color: 'white', border: '1px solid rgba(255,255,255,0.3)', padding: '10px 16px', borderRadius: '12px', cursor: 'pointer', fontWeight: '600', transition: '0.2s' }}
            onMouseEnter={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.3)'}
            onMouseLeave={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.2)'}
          >
            <ArrowLeft size={18} />
            목록으로
          </button>
        </div>
        <div style={{ position: 'absolute', bottom: '40px', left: '0', right: '0', maxWidth: '800px', margin: '0 auto', padding: '0 20px', color: 'white', zIndex: 10 }}>
          <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '16px' }}>
            {hashtags.map(tag => (
              <span key={tag} style={{ backgroundColor: '#60C95A', padding: '4px 12px', borderRadius: '16px', fontSize: '14px', fontWeight: 'bold' }}>{tag}</span>
            ))}
          </div>
          <h1 style={{ fontSize: '36px', fontWeight: 'bold', margin: '0 0 16px', lineHeight: '1.3' }}>{post.title}</h1>
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px', fontSize: '15px', color: 'rgba(255,255,255,0.9)' }}>
            <span style={{ fontWeight: '700' }}>{post.authorNickname}</span>
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
              <div style={{ width: '40px', height: '40px', borderRadius: '50%', backgroundColor: '#E5E7EB', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <User size={20} color="#9CA3AF" />
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
            {post.comments?.map(comment => (
              <div key={comment.commentId} style={{ display: 'flex', gap: '16px' }}>
                <div style={{ width: '40px', height: '40px', borderRadius: '50%', backgroundColor: '#111827', color: 'white', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: '700', fontSize: '14px' }}>
                  {comment.authorNickname ? comment.authorNickname.charAt(0) : 'U'}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '8px' }}>
                    <span style={{ fontWeight: '700', color: '#111827', fontSize: '15px' }}>{comment.authorNickname}</span>
                    <span style={{ fontSize: '13px', color: '#9CA3AF' }}>{formatCommentDate(comment.createdAt)}</span>
                  </div>
                  <div style={{ color: '#4B5563', fontSize: '15px', lineHeight: '1.6' }}>
                    {comment.content}
                  </div>
                </div>
              </div>
            ))}
          </div>

        </div>
      </div>
    </div>
  );
}
