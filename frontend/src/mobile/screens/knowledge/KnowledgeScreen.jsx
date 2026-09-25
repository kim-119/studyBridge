import React, { useMemo, useState } from 'react';
import { Heart, MessageCircle } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import Fab from '../../components/Fab';
import ScreenState, { EmptyState } from '../../components/ScreenState';
import MobileScreen from '../../shell/MobileScreen';
import { knowledgeService } from '../../../services/api';
import { useAsync } from '../../data/useAsync';

function summarize(content) {
  if (!content) return '';
  const plain = content.replace(/\s+/g, ' ').trim();
  return plain.length > 90 ? `${plain.slice(0, 90)}…` : plain;
}

export default function KnowledgeScreen() {
  const navigate = useNavigate();
  const [keyword, setKeyword] = useState('');
  const posts = useAsync(() => knowledgeService.getPosts(), []);

  const visiblePosts = useMemo(() => {
    const list = Array.isArray(posts.data) ? posts.data : posts.data?.content || [];
    if (!keyword) return list;

    return list.filter((post) =>
      `${post.title || ''} ${post.content || ''}`.toLowerCase().includes(keyword.toLowerCase())
    );
  }, [posts.data, keyword]);

  return (
    <MobileScreen title="지식공유" showBackButton>
      <div className="mobile-toolbar">
        <input
          className="mobile-search"
          type="search"
          value={keyword}
          placeholder="게시글 검색"
          onChange={(event) => setKeyword(event.target.value)}
        />
      </div>

      <ScreenState query={posts} loadingLabel="게시글을 불러오는 중입니다">
        {visiblePosts.length === 0 ? (
          <EmptyState message={keyword ? '검색 결과가 없습니다.' : '아직 등록된 게시글이 없습니다.'} />
        ) : (
          <ul className="mobile-list">
            {visiblePosts.map((post) => (
              <li key={post.blogId}>
                <button
                  type="button"
                  className="mobile-post"
                  onClick={() => navigate(`/knowledge/${post.blogId}`)}
                >
                  {post.imagePresignedUrl && (
                    <img className="mobile-post__thumbnail" src={post.imagePresignedUrl} alt="" />
                  )}

                  <span className="mobile-post__body">
                    <strong>{post.title}</strong>
                    <span className="mobile-post__summary">{summarize(post.content)}</span>

                    <span className="mobile-post__meta">
                      <span>{post.authorNickname}</span>
                      <span>
                        <Heart size={14} /> {post.likeCount ?? 0}
                      </span>
                      <span>
                        <MessageCircle size={14} /> {post.comments?.length ?? 0}
                      </span>
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </ScreenState>

      <Fab label="게시글 작성" onClick={() => navigate('/knowledge/new')} />
    </MobileScreen>
  );
}
