import React from 'react';
import { MoreVertical } from 'lucide-react';
import { commentIdOf, formatPostTime, isOwnedBy } from './knowledgeModel';

function CommentItem({ comment, isMine, onMore }) {
  return (
    <li className="knowledge-comment">
      <div className="knowledge-comment__body">
        <p className="knowledge-comment__meta">
          <strong>{comment.authorNickname || '알 수 없음'}</strong>
          <span>{formatPostTime(comment.createdAt)}</span>
        </p>
        <p className="knowledge-comment__text">{comment.content}</p>
      </div>
      <button
        type="button"
        className="mobile-row__more"
        aria-label={isMine ? '내 댓글 관리' : '댓글 신고'}
        onClick={() => onMore({ kind: 'comment', id: commentIdOf(comment), isMine })}
      >
        <MoreVertical size={18} />
      </button>
    </li>
  );
}

export default function KnowledgeComments({ comments, userId, onMore }) {
  if (comments.length === 0) {
    return <p className="knowledge-comments__empty">첫 댓글을 남겨보세요.</p>;
  }

  return (
    <ul className="knowledge-comments">
      {comments.map((comment) => (
        <CommentItem
          key={commentIdOf(comment)}
          comment={comment}
          isMine={isOwnedBy(comment, userId)}
          onMore={onMore}
        />
      ))}
    </ul>
  );
}
