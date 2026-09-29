import React from 'react';
import { FileText, Heart, MessageCircle, MoreVertical } from 'lucide-react';
import { formatPostTime } from './knowledgeModel';

function AuthorAvatar({ post }) {
  if (post.authorPhotoUrl) {
    return <img className="knowledge-post__avatar" src={post.authorPhotoUrl} alt="" />;
  }

  return (
    <span className="knowledge-post__avatar" aria-hidden="true">
      {String(post.authorNickname || '?').slice(0, 1)}
    </span>
  );
}

export function KnowledgePostHeader({ post, onMore }) {
  return (
    <header className="knowledge-post__header">
      <AuthorAvatar post={post} />
      <span className="knowledge-post__author">
        <strong>{post.authorNickname || '알 수 없음'}</strong>
        <span>{formatPostTime(post.createdAt)}</span>
      </span>
      {onMore && (
        <button type="button" className="mobile-row__more" aria-label="게시글 더보기" onClick={onMore}>
          <MoreVertical size={18} />
        </button>
      )}
    </header>
  );
}

export function KnowledgePostImage({ post, onOpenImage }) {
  if (!post.imagePresignedUrl) return null;

  return (
    <button
      type="button"
      className="knowledge-post__media"
      aria-label="이미지 크게 보기"
      onClick={() => onOpenImage(post.imagePresignedUrl)}
    >
      <img src={post.imagePresignedUrl} alt={`${post.title || '게시글'} 첨부 이미지`} loading="lazy" />
    </button>
  );
}

export function KnowledgePdfBadge({ post }) {
  if (!post.pdfPresignedUrl) return null;

  return (
    <p className="knowledge-post__pdf-badge">
      <FileText size={14} />
      PDF 첨부
    </p>
  );
}

export function KnowledgePostActions({ post, isLikePending, onToggleLike, onComment }) {
  const isLiked = Boolean(post.likedByCurrentUser);
  const commentCount = post.comments?.length ?? 0;

  return (
    <div className="knowledge-post__actions">
      <button
        type="button"
        className={isLiked ? 'knowledge-action is-liked' : 'knowledge-action'}
        aria-pressed={isLiked}
        aria-busy={isLikePending || undefined}
        aria-label={isLiked ? `좋아요 취소, 좋아요 ${post.likeCount ?? 0}개` : `좋아요, 좋아요 ${post.likeCount ?? 0}개`}
        onClick={() => onToggleLike(post)}
      >
        <Heart size={20} fill={isLiked ? 'currentColor' : 'none'} />
        <span>{post.likeCount ?? 0}</span>
      </button>

      <button
        type="button"
        className="knowledge-action"
        aria-label={`댓글 ${commentCount}개`}
        onClick={onComment}
      >
        <MessageCircle size={20} />
        <span>{commentCount}</span>
      </button>
    </div>
  );
}
