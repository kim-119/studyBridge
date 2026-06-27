import React, { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';
import { Search, Plus, Heart, MessageSquare, Image as ImageIcon, FileText, X, ChevronLeft, ChevronRight } from 'lucide-react';
import { useAuth } from '../hooks/useAuth';
import { knowledgeService } from '../services/api';

export default function Knowledge() {
  const { user } = useAuth();
  
  const [posts, setPosts] = useState([]);
  const [searchQuery, setSearchQuery] = useState('');
  const [activeFilter, setActiveFilter] = useState('전체');
  const [currentPage, setCurrentPage] = useState(1);
  const PAGE_SIZE = 15;
  
  const [showWriteModal, setShowWriteModal] = useState(false);
  const [newPost, setNewPost] = useState({ title: '', summary: '', tags: '' });
  const [imageFile, setImageFile] = useState(null);
  const [pdfFile, setPdfFile] = useState(null);
  
  const imageRef = useRef(null);
  const pdfRef = useRef(null);

  const filters = ['전체', '#로드맵', '#코딩테스트', '#토익', '#자료', '#취업', '#디자인'];

  useEffect(() => {
    fetchPosts();
  }, []);

  const fetchPosts = async () => {
    try {
      const data = await knowledgeService.getPosts();
      setPosts(data);
    } catch (error) {
      console.error("Failed to fetch posts:", error);
    }
  };

  const handleSearch = async (e) => {
    if (e.key === 'Enter') {
      if (!searchQuery.trim()) {
        fetchPosts();
        return;
      }
      try {
        const result = await knowledgeService.searchPosts(searchQuery);
        setPosts(result);
      } catch (error) {
        console.error("Failed to search posts:", error);
      }
    }
  };

  const handleWriteSubmit = async () => {
    if (!newPost.title.trim() || !newPost.summary.trim()) return;
    
    const tagsArray = newPost.tags.split(',')
      .map(tag => tag.trim())
      .filter(t => t)
      .map(t => t.startsWith('#') ? t : `#${t}`);
    
    const finalContent = `${newPost.summary}\n\n${tagsArray.join(' ')}`;
    
    try {
      await knowledgeService.createPost(newPost.title, finalContent, imageFile, pdfFile);
      setShowWriteModal(false);
      setNewPost({ title: '', summary: '', tags: '' });
      setImageFile(null);
      setPdfFile(null);
      fetchPosts();
    } catch (error) {
      console.error("Failed to create post:", error);
      alert("글 작성에 실패했습니다.");
    }
  };

  const getThumbnail = (post) => {
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

  const extractTags = (content) => {
    return content?.match(/#\S+/g) || [];
  };

  const stripTags = (content) => {
    return content?.replace(/#\S+/g, '').trim() || '';
  };

  const filteredPosts = posts.filter(post => {
    if (activeFilter === '전체') return true;
    const tags = extractTags(post.content);
    return tags.includes(activeFilter);
  });

  // 필터/검색 결과가 바뀌면 1페이지로 리셋
  useEffect(() => {
    setCurrentPage(1);
  }, [activeFilter, posts]);

  const totalPages = Math.max(1, Math.ceil(filteredPosts.length / PAGE_SIZE));
  const safePage = Math.min(currentPage, totalPages);
  const pagedPosts = filteredPosts.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  const goToPage = (page) => {
    if (page < 1 || page > totalPages) return;
    setCurrentPage(page);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  return (
    <div style={{ width: '100%', boxSizing: 'border-box', padding: 'clamp(16px, 4vw, 40px)', fontFamily: '"Malgun Gothic", "맑은 고딕", sans-serif', backgroundColor: '#F9FAFB', minHeight: 'calc(100vh - 80px)' }}>
      
      {/* 중앙 집중형 검색 및 생성 헤더 */}
      <div style={{ maxWidth: '800px', margin: '0 auto 48px', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
        
        <div className="kn-searchbar" style={{ width: '100%', position: 'relative', display: 'flex', alignItems: 'center', backgroundColor: '#FFFFFF', borderRadius: '24px', boxShadow: '0 8px 30px rgba(0,0,0,0.06)', padding: '8px 8px 8px 24px', border: '1px solid #E5E7EB', transition: 'all 0.3s' }}
             onFocus={(e) => { e.currentTarget.style.boxShadow = '0 12px 40px rgba(96, 201, 90, 0.15)'; e.currentTarget.style.borderColor = '#60C95A' }}
             onBlur={(e) => { e.currentTarget.style.boxShadow = '0 8px 30px rgba(0,0,0,0.06)'; e.currentTarget.style.borderColor = '#E5E7EB' }}
        >
          <Search size={24} color="#9CA3AF" />
          <input
            type="text"
            className="kn-search-input"
            placeholder="궁금한 로드맵이나 자료를 RAG AI로 검색해보세요 (입력 후 Enter)"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            onKeyDown={handleSearch}
            style={{ flex: 1, minWidth: 0, height: '48px', border: 'none', backgroundColor: 'transparent', fontSize: '16px', color: '#111827', outline: 'none', marginLeft: '12px' }}
          />
          <button
            onClick={() => setShowWriteModal(true)}
            className="kn-create-btn"
            style={{ height: '48px', padding: '0 24px', backgroundColor: '#60C95A', color: 'white', borderRadius: '16px', border: 'none', fontWeight: 'bold', fontSize: '15px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '8px', transition: 'background-color 0.2s', boxShadow: '0 4px 12px rgba(96, 201, 90, 0.3)', whiteSpace: 'nowrap' }}
            onMouseEnter={(e) => e.currentTarget.style.backgroundColor = '#387235'}
            onMouseLeave={(e) => e.currentTarget.style.backgroundColor = '#60C95A'}
          >
            <Plus size={20} />
            새 지식 작성
          </button>
        </div>

        {/* Filter Tags */}
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', justifyContent: 'center', marginTop: '24px' }}>
          {filters.map(filter => (
            <button
              key={filter}
              onClick={() => setActiveFilter(filter)}
              style={{ padding: '8px 16px', borderRadius: '20px', border: activeFilter === filter ? '1px solid #60C95A' : '1px solid #E5E7EB', backgroundColor: activeFilter === filter ? '#60C95A' : '#FFFFFF', color: activeFilter === filter ? 'white' : '#6B7280', fontSize: '14px', fontWeight: 'bold', cursor: 'pointer', transition: 'all 0.2s', boxShadow: activeFilter === filter ? '0 4px 12px rgba(96, 201, 90, 0.2)' : 'none' }}
              onMouseEnter={(e) => { if(activeFilter !== filter) e.currentTarget.style.borderColor = '#60C95A' }}
              onMouseLeave={(e) => { if(activeFilter !== filter) e.currentTarget.style.borderColor = '#E5E7EB' }}
            >
              {filter}
            </button>
          ))}
        </div>
      </div>

      {/* Main Content: Post Grid (Full Width) */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(min(320px, 100%), 1fr))', gap: '24px' }}>
        {/* Featured Post (First post) spanning full width */}
        {pagedPosts.length > 0 && (
          <div style={{ gridColumn: '1 / -1', marginBottom: '16px' }}>
             <Link to={`/knowledge/${pagedPosts[0].blogId}`} style={{ textDecoration: 'none', display: 'block' }}>
              <div style={{ position: 'relative', width: '100%', height: '400px', borderRadius: '24px', overflow: 'hidden', boxShadow: '0 12px 32px rgba(0,0,0,0.1)', cursor: 'pointer' }}>
                <img src={getThumbnail(pagedPosts[0])} alt={pagedPosts[0].title} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
                <div style={{ position: 'absolute', bottom: 0, left: 0, right: 0, padding: '60px 40px 40px', background: 'linear-gradient(to top, rgba(0,0,0,0.9), transparent)', color: 'white' }}>
                  <div style={{ display: 'flex', gap: '8px', marginBottom: '16px' }}>
                    {extractTags(pagedPosts[0].content).map(tag => <span key={tag} style={{ backgroundColor: '#60C95A', padding: '6px 12px', borderRadius: '8px', fontSize: '13px', fontWeight: 'bold' }}>{tag}</span>)}
                  </div>
                  <h2 style={{ fontSize: '32px', fontWeight: 'bold', margin: '0 0 16px' }}>{pagedPosts[0].title}</h2>
                  <p style={{ fontSize: '16px', color: 'rgba(255,255,255,0.8)', margin: '0 0 20px', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden', maxWidth: '800px' }}>{stripTags(pagedPosts[0].content)}</p>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '16px', fontSize: '15px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                      {pagedPosts[0].authorPhotoUrl ? (
                        <img src={pagedPosts[0].authorPhotoUrl} alt="author" style={{ width: '24px', height: '24px', borderRadius: '50%', objectFit: 'cover' }} />
                      ) : (
                        <div style={{ width: '24px', height: '24px', borderRadius: '50%', backgroundColor: '#60C95A', color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '12px', fontWeight: 'bold' }}>
                          {pagedPosts[0].authorNickname ? pagedPosts[0].authorNickname.charAt(0) : 'U'}
                        </div>
                      )}
                      <span style={{ fontWeight: 'bold' }}>{pagedPosts[0].authorNickname}</span>
                    </div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><Heart size={16} /> {pagedPosts[0].likeCount}</div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}><MessageSquare size={16} /> {pagedPosts[0].comments?.length || 0}</div>
                  </div>
                </div>
              </div>
            </Link>
          </div>
        )}

        {/* Rest of the posts Grid */}
        {pagedPosts.slice(1).map(post => (
          <Link to={`/knowledge/${post.blogId}`} key={post.blogId} style={{ textDecoration: 'none', color: 'inherit' }}>
            <div style={{ backgroundColor: 'white', borderRadius: '16px', overflow: 'hidden', boxShadow: '0 4px 16px rgba(0,0,0,0.04)', transition: 'transform 0.2s, boxShadow 0.2s', display: 'flex', flexDirection: 'column', height: '100%', border: '1px solid #E5E7EB' }} onMouseEnter={(e) => { e.currentTarget.style.transform = 'translateY(-6px)'; e.currentTarget.style.boxShadow = '0 12px 24px rgba(0,0,0,0.08)' }} onMouseLeave={(e) => { e.currentTarget.style.transform = 'translateY(0)'; e.currentTarget.style.boxShadow = '0 4px 16px rgba(0,0,0,0.04)' }}>
              <div style={{ width: '100%', height: '200px', backgroundColor: '#F3F4F6' }}>
                <img src={getThumbnail(post)} alt={post.title} style={{ width: '100%', height: '100%', objectFit: 'cover' }} />
              </div>
              <div style={{ padding: '24px', flex: 1, display: 'flex', flexDirection: 'column' }}>
                <div style={{ display: 'flex', gap: '6px', flexWrap: 'wrap', marginBottom: '12px' }}>
                  {extractTags(post.content).map(tag => <span key={tag} style={{ color: '#60C95A', fontSize: '13px', fontWeight: 'bold', backgroundColor: 'rgba(96, 201, 90, 0.1)', padding: '4px 8px', borderRadius: '6px' }}>{tag}</span>)}
                </div>
                <h3 style={{ fontSize: '18px', fontWeight: 'bold', color: '#111827', margin: '0 0 12px', lineHeight: '1.4', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>{post.title}</h3>
                <p style={{ fontSize: '15px', color: '#6B7280', margin: '0 0 20px', lineHeight: '1.5', display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden', flex: 1 }}>{stripTags(post.content)}</p>
                
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: '16px', borderTop: '1px solid #E5E7EB' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                    {post.authorPhotoUrl ? (
                      <img src={post.authorPhotoUrl} alt="author" style={{ width: '24px', height: '24px', borderRadius: '50%', objectFit: 'cover' }} />
                    ) : (
                      <div style={{ width: '24px', height: '24px', borderRadius: '50%', backgroundColor: '#60C95A', color: 'white', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '12px', fontWeight: 'bold' }}>
                        {post.authorNickname ? post.authorNickname.charAt(0) : 'U'}
                      </div>
                    )}
                    <span style={{ fontSize: '14px', fontWeight: 'bold', color: '#111827' }}>{post.authorNickname}</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '12px', color: '#6B7280', fontSize: '14px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><Heart size={16} /> {post.likeCount}</div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><MessageSquare size={16} /> {post.comments?.length || 0}</div>
                  </div>
                </div>
              </div>
            </div>
          </Link>
        ))}
      </div>

      {/* 페이지네이션 */}
      {totalPages > 1 && (
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '8px', marginTop: '48px' }}>
          <button
            onClick={() => goToPage(safePage - 1)}
            disabled={safePage === 1}
            style={{ width: '40px', height: '40px', display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: '10px', border: '1px solid #E5E7EB', backgroundColor: '#FFFFFF', color: safePage === 1 ? '#D1D5DB' : '#374151', cursor: safePage === 1 ? 'not-allowed' : 'pointer', fontWeight: 'bold' }}
          >
            <ChevronLeft size={18} />
          </button>

          {Array.from({ length: totalPages }, (_, i) => i + 1).map(page => (
            <button
              key={page}
              onClick={() => goToPage(page)}
              style={{ minWidth: '40px', height: '40px', padding: '0 8px', borderRadius: '10px', border: page === safePage ? '1px solid #60C95A' : '1px solid #E5E7EB', backgroundColor: page === safePage ? '#60C95A' : '#FFFFFF', color: page === safePage ? 'white' : '#374151', fontSize: '14px', fontWeight: 'bold', cursor: 'pointer', boxShadow: page === safePage ? '0 4px 12px rgba(96, 201, 90, 0.25)' : 'none', transition: 'all 0.2s' }}
              onMouseEnter={(e) => { if (page !== safePage) e.currentTarget.style.borderColor = '#60C95A'; }}
              onMouseLeave={(e) => { if (page !== safePage) e.currentTarget.style.borderColor = '#E5E7EB'; }}
            >
              {page}
            </button>
          ))}

          <button
            onClick={() => goToPage(safePage + 1)}
            disabled={safePage === totalPages}
            style={{ width: '40px', height: '40px', display: 'flex', alignItems: 'center', justifyContent: 'center', borderRadius: '10px', border: '1px solid #E5E7EB', backgroundColor: '#FFFFFF', color: safePage === totalPages ? '#D1D5DB' : '#374151', cursor: safePage === totalPages ? 'not-allowed' : 'pointer', fontWeight: 'bold' }}
          >
            <ChevronRight size={18} />
          </button>
        </div>
      )}

      {/* 글 작성 모달 (디자인 정책 적용) */}
      {showWriteModal && (
        <div style={{ position: 'fixed', top: 0, left: 0, right: 0, bottom: 0, backgroundColor: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100000, padding: '20px' }} onClick={() => setShowWriteModal(false)}>
          <div style={{ backgroundColor: '#FFFFFF', borderRadius: '12px', width: '100%', maxWidth: '800px', maxHeight: '90vh', overflowY: 'auto', display: 'flex', flexDirection: 'column', animation: 'slideUp 0.3s ease-out' }} onClick={(e) => e.stopPropagation()}>
            <div style={{ padding: '32px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid #E5E7EB', paddingBottom: '16px' }}>
                <h2 style={{ fontSize: '20px', fontWeight: 'bold', color: '#111827', margin: 0 }}>지식 공유하기</h2>
                <button onClick={() => setShowWriteModal(false)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: '#6B7280' }}><X size={24} /></button>
              </div>

              {/* 입력 폼 */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '14px', fontWeight: 'bold', color: '#111827', marginBottom: '8px' }}>제목</label>
                  <input 
                    type="text" 
                    placeholder="글 제목을 입력하세요." 
                    value={newPost.title}
                    onChange={(e) => setNewPost({...newPost, title: e.target.value})}
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
                    value={newPost.tags}
                    onChange={(e) => setNewPost({...newPost, tags: e.target.value})}
                    style={{ width: '100%', height: '40px', boxSizing: 'border-box', padding: '0 16px', borderRadius: '8px', border: '1px solid #D1D5DB', fontSize: '14px', outline: 'none' }}
                    onFocus={(e) => e.target.style.border = '1px solid #60C95A'}
                    onBlur={(e) => e.target.style.border = '1px solid #D1D5DB'}
                  />
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: '14px', fontWeight: 'bold', color: '#111827', marginBottom: '8px' }}>내용</label>
                  <textarea 
                    placeholder="나만의 로드맵, 노하우, 공부 자료를 상세히 공유해주세요. 다른 사람들에게 큰 도움이 됩니다!" 
                    value={newPost.summary}
                    onChange={(e) => setNewPost({...newPost, summary: e.target.value})}
                    style={{ width: '100%', boxSizing: 'border-box', padding: '16px', borderRadius: '8px', border: '1px solid #D1D5DB', fontSize: '14px', outline: 'none', minHeight: '200px', resize: 'vertical', lineHeight: '1.6' }}
                    onFocus={(e) => e.target.style.border = '1px solid #60C95A'}
                    onBlur={(e) => e.target.style.border = '1px solid #D1D5DB'}
                  />
                </div>

                {/* 첨부 파일 섹션 */}
                <div>
                  <label style={{ display: 'block', fontSize: '14px', fontWeight: 'bold', color: '#111827', marginBottom: '8px' }}>자료 첨부 (PDF, 이미지)</label>
                  <div style={{ display: 'flex', gap: '16px' }}>
                    <input type="file" ref={pdfRef} accept="application/pdf" style={{ display: 'none' }} onChange={(e) => setPdfFile(e.target.files[0])} />
                    <input type="file" ref={imageRef} accept="image/*" style={{ display: 'none' }} onChange={(e) => setImageFile(e.target.files[0])} />
                    <button onClick={() => pdfRef.current.click()} style={{ flex: 1, padding: '24px', backgroundColor: '#F3F4F6', border: '1px dashed #D1D5DB', borderRadius: '8px', cursor: 'pointer', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px', color: '#6B7280', transition: '0.2s' }} onMouseEnter={(e) => e.currentTarget.style.borderColor = '#60C95A'} onMouseLeave={(e) => e.currentTarget.style.borderColor = '#D1D5DB'}>
                      <FileText size={28} color={pdfFile ? "#60C95A" : "#6B7280"} />
                      <span style={{ fontSize: '12px', fontWeight: 'bold', color: pdfFile ? "#111827" : "#6B7280" }}>{pdfFile ? pdfFile.name : 'PDF 업로드'}</span>
                    </button>
                    <button onClick={() => imageRef.current.click()} style={{ flex: 1, padding: '24px', backgroundColor: '#F3F4F6', border: '1px dashed #D1D5DB', borderRadius: '8px', cursor: 'pointer', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px', color: '#6B7280', transition: '0.2s' }} onMouseEnter={(e) => e.currentTarget.style.borderColor = '#60C95A'} onMouseLeave={(e) => e.currentTarget.style.borderColor = '#D1D5DB'}>
                      <ImageIcon size={28} color={imageFile ? "#60C95A" : "#6B7280"} />
                      <span style={{ fontSize: '12px', fontWeight: 'bold', color: imageFile ? "#111827" : "#6B7280" }}>{imageFile ? imageFile.name : '사진 업로드'}</span>
                    </button>
                  </div>
                </div>
              </div>

              {/* 하단 버튼 */}
              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '12px', marginTop: '16px', paddingTop: '16px', borderTop: '1px solid #E5E7EB' }}>
                <button 
                  onClick={() => setShowWriteModal(false)}
                  style={{ width: '80px', height: '40px', backgroundColor: '#FFFFFF', color: '#111827', border: '1px solid #E5E7EB', borderRadius: '8px', fontSize: '14px', cursor: 'pointer' }}
                >
                  취소
                </button>
                <button 
                  onClick={handleWriteSubmit}
                  style={{ width: '80px', height: '40px', backgroundColor: '#60C95A', color: 'white', border: 'none', borderRadius: '8px', fontSize: '14px', cursor: 'pointer' }}
                  onMouseEnter={(e) => e.currentTarget.style.backgroundColor = '#387235'}
                  onMouseLeave={(e) => e.currentTarget.style.backgroundColor = '#60C95A'}
                >
                  등록
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

    </div>
  );
}
