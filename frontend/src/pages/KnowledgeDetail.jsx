import React, { useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { ArrowLeft, Heart, MessageSquare, Share2, FileText, Download, User } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';

export default function KnowledgeDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useAuth();
  
  // 더미 데이터 (실제로는 id로 fetch 해와야 함)
  const [post, setPost] = useState({
    id: Number(id),
    title: '비전공자를 위한 백엔드 개발자 로드맵 (PDF 첨부)',
    content: `제가 1년 동안 공부했던 내용과 단계별로 추천하는 강의, 책, 프로젝트 주제들을 정리했습니다. 방향을 못 잡고 계신 분들께 도움이 되길 바랍니다.

1단계: CS 기초 및 언어 선택
- 네트워크, 운영체제 기본기 (추천 도서: ...)
- Java or Python? 장단점 비교

2단계: 프레임워크 학습
- Spring Boot / Django / FastAPI 중 선택 기준
- 제가 추천하는 인강 리스트

3단계: 사이드 프로젝트 가이드
- 팀빌딩은 어디서 하나요?
- ERD 설계부터 배포까지의 사이클

자세한 내용은 첨부한 PDF 파일을 참고해주세요. 질문은 댓글로 남겨주시면 확인하는 대로 답변 드리겠습니다!`,
    author: '잠재용',
    date: '2023-11-01',
    likes: 124,
    commentsCount: 32,
    hashtags: ['#백엔드', '#로드맵', '#비전공자'],
    thumbnail: 'https://images.unsplash.com/photo-1517694712202-14dd9538aa97?ixlib=rb-4.0.3&auto=format&fit=crop&w=1200&q=80',
    attachments: [
      { id: 1, type: 'pdf', name: '비전공자_백엔드_로드맵_v1.0.pdf', size: '2.4MB' }
    ]
  });

  const [comments, setComments] = useState([
    { id: 1, author: '개발자지망생', text: '와 정말 감사합니다! 헤매고 있었는데 등대 같은 자료네요.', date: '2023-11-01 14:30' },
    { id: 2, author: '스프링러버', text: 'PDF 자료 정리 엄청 깔끔하게 잘 하셨네요. 스크랩해갑니다.', date: '2023-11-02 09:15' },
  ]);

  const [newComment, setNewComment] = useState('');
  const [isLiked, setIsLiked] = useState(false);

  const handleLike = () => {
    setIsLiked(!isLiked);
    setPost(prev => ({ ...prev, likes: isLiked ? prev.likes - 1 : prev.likes + 1 }));
  };

  const handleAddComment = (e) => {
    e.preventDefault();
    if (!newComment.trim()) return;
    const comment = {
      id: Date.now(),
      author: user?.displayName || user?.name || '익명사용자',
      text: newComment,
      date: new Date().toISOString().replace('T', ' ').substring(0, 16)
    };
    setComments([...comments, comment]);
    setPost(prev => ({ ...prev, commentsCount: prev.commentsCount + 1 }));
    setNewComment('');
  };

  return (
    <div style={{ backgroundColor: '#F9FAFB', minHeight: '100vh', paddingBottom: '80px' }}>
      
      {/* 썸네일 헤더 영역 */}
      <div style={{ width: '100%', height: '400px', position: 'relative', overflow: 'hidden' }}>
        <img src={post.thumbnail} alt={post.title} style={{ width: '100%', height: '100%', objectFit: 'cover', filter: 'brightness(0.6)' }} />
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
            {post.hashtags.map(tag => (
              <span key={tag} style={{ backgroundColor: '#60C95A', padding: '4px 12px', borderRadius: '16px', fontSize: '14px', fontWeight: 'bold' }}>{tag}</span>
            ))}
          </div>
          <h1 style={{ fontSize: '36px', fontWeight: 'bold', margin: '0 0 16px', lineHeight: '1.3' }}>{post.title}</h1>
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px', fontSize: '15px', color: 'rgba(255,255,255,0.9)' }}>
            <span style={{ fontWeight: '700' }}>{post.author}</span>
            <span>•</span>
            <span>{post.date}</span>
            <span>•</span>
            <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><Heart size={16} fill={isLiked ? "white" : "none"} /> {post.likes}</div>
          </div>
        </div>
      </div>

      <div style={{ maxWidth: '800px', margin: '0 auto', padding: '40px 20px' }}>
        
        {/* 본문 콘텐츠 */}
        <div style={{ backgroundColor: 'white', borderRadius: '24px', padding: '40px', boxShadow: '0 4px 20px rgba(0,0,0,0.03)', marginBottom: '32px' }}>
          <div style={{ fontSize: '17px', color: '#374151', lineHeight: '1.8', whiteSpace: 'pre-wrap', fontFamily: '"Inter", "Pretendard", sans-serif' }}>
            {post.content}
          </div>

          {/* 첨부파일 영역 */}
          {post.attachments && post.attachments.length > 0 && (
            <div style={{ marginTop: '40px', paddingTop: '32px', borderTop: '1px solid #E5E7EB' }}>
              <h3 style={{ fontSize: '18px', fontWeight: '700', color: '#111827', margin: '0 0 16px' }}>첨부 자료</h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                {post.attachments.map(file => (
                  <div key={file.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '16px 20px', backgroundColor: '#F3F4F6', borderRadius: '12px', border: '1px solid #E5E7EB' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                      <div style={{ padding: '10px', backgroundColor: '#EF4444', color: 'white', borderRadius: '8px' }}>
                        <FileText size={20} />
                      </div>
                      <div>
                        <div style={{ fontSize: '15px', fontWeight: '600', color: '#111827', marginBottom: '4px' }}>{file.name}</div>
                        <div style={{ fontSize: '13px', color: '#6B7280' }}>{file.size}</div>
                      </div>
                    </div>
                    <button style={{ padding: '8px 16px', display: 'flex', alignItems: 'center', gap: '6px', backgroundColor: 'white', border: '1px solid #D1D5DB', borderRadius: '8px', cursor: 'pointer', fontWeight: '600', color: '#4B5563', transition: '0.2s' }} onMouseEnter={(e) => { e.currentTarget.style.backgroundColor = '#F9FAFB'; e.currentTarget.style.borderColor = '#9CA3AF' }} onMouseLeave={(e) => { e.currentTarget.style.backgroundColor = 'white'; e.currentTarget.style.borderColor = '#D1D5DB' }}>
                      <Download size={16} /> 다운로드
                    </button>
                  </div>
                ))}
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
              도움이 되었어요 {post.likes}
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
            댓글 <span style={{ color: '#60C95A' }}>{post.commentsCount}</span>
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
            {comments.map(comment => (
              <div key={comment.id} style={{ display: 'flex', gap: '16px' }}>
                <div style={{ width: '40px', height: '40px', borderRadius: '50%', backgroundColor: '#111827', color: 'white', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: '700', fontSize: '14px' }}>
                  {comment.author.charAt(0)}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '8px' }}>
                    <span style={{ fontWeight: '700', color: '#111827', fontSize: '15px' }}>{comment.author}</span>
                    <span style={{ fontSize: '13px', color: '#9CA3AF' }}>{comment.date}</span>
                  </div>
                  <div style={{ color: '#4B5563', fontSize: '15px', lineHeight: '1.6' }}>
                    {comment.text}
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
