import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import Fab from '../../components/Fab';
import ImageViewer from '../../components/ImageViewer';
import ScreenState, { EmptyState } from '../../components/ScreenState';
import MobileScreen from '../../shell/MobileScreen';
import { knowledgeService } from '../../../services/api';
import { useAsync } from '../../data/useAsync';
import {
  KnowledgePdfBadge,
  KnowledgePostActions,
  KnowledgePostHeader,
  KnowledgePostImage,
} from './KnowledgePostParts';
import { postsFromResponse, updatePostIn } from './knowledgeModel';
import { useLikeToggle } from './useLikeToggle';
import { useReloadWhenVisible } from './useReloadWhenVisible';
import './knowledge.css';

const SEARCH_DEBOUNCE_MS = 350;

function FeedPost({ post, isLikePending, onToggleLike, onOpenImage, onOpenPost }) {
  return (
    <article className="knowledge-post">
      <KnowledgePostHeader post={post} />
      <KnowledgePostImage post={post} onOpenImage={onOpenImage} />
      <KnowledgePostActions
        post={post}
        isLikePending={isLikePending}
        onToggleLike={onToggleLike}
        onComment={onOpenPost}
      />
      <button type="button" className="knowledge-post__content knowledge-post__open" onClick={onOpenPost}>
        <strong className="knowledge-post__title">{post.title}</strong>
        <span className="knowledge-post__text knowledge-post__text--clamped">{post.content}</span>
      </button>
      <KnowledgePdfBadge post={post} />
    </article>
  );
}

export default function KnowledgeScreen() {
  const navigate = useNavigate();
  const [keyword, setKeyword] = useState('');
  const [appliedKeyword, setAppliedKeyword] = useState('');
  const [viewerImage, setViewerImage] = useState(null);

  useEffect(() => {
    const timer = setTimeout(() => setAppliedKeyword(keyword.trim()), SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [keyword]);

  const posts = useAsync(
    () => (appliedKeyword ? knowledgeService.searchPosts(appliedKeyword) : knowledgeService.getPosts()),
    [appliedKeyword]
  );
  const { setData, reload } = posts;

  useReloadWhenVisible(reload);

  const updatePost = useCallback((id, updater) => setData((current) => updatePostIn(current, id, updater)), [setData]);
  const like = useLikeToggle(updatePost);
  const visiblePosts = useMemo(() => postsFromResponse(posts.data), [posts.data]);

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

      {like.errorMessage && <p className="mobile-auth__error">{like.errorMessage}</p>}

      <ScreenState query={posts} loadingLabel="게시글을 불러오는 중입니다">
        {visiblePosts.length === 0 ? (
          <EmptyState message={appliedKeyword ? '검색 결과가 없습니다.' : '아직 등록된 게시글이 없습니다.'} />
        ) : (
          <ul className="knowledge-feed">
            {visiblePosts.map((post) => (
              <li key={post.blogId}>
                <FeedPost
                  post={post}
                  isLikePending={like.isPending(post.blogId)}
                  onToggleLike={like.toggleLike}
                  onOpenImage={setViewerImage}
                  onOpenPost={() => navigate(`/knowledge/${post.blogId}`)}
                />
              </li>
            ))}
          </ul>
        )}
      </ScreenState>

      <Fab label="게시글 작성" onClick={() => navigate('/knowledge/new')} />
      <ImageViewer src={viewerImage} onClose={() => setViewerImage(null)} />
    </MobileScreen>
  );
}
