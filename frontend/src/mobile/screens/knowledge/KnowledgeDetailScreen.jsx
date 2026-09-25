import React, { useState } from 'react';
import { FileText, Heart } from 'lucide-react';
import { useParams } from 'react-router-dom';
import Button from '../../components/Button';
import ScreenState from '../../components/ScreenState';
import TextField from '../../components/TextField';
import MobileScreen from '../../shell/MobileScreen';
import { knowledgeService } from '../../../services/api';
import { useAsync, useSubmit } from '../../data/useAsync';
import { openExternalUrl } from '../../platform/externalLink';

export default function KnowledgeDetailScreen() {
  const { blogId } = useParams();
  const post = useAsync(() => knowledgeService.getPostDetail(blogId), [blogId]);
  const [comment, setComment] = useState('');

  const toggleLike = useSubmit(async () => {
    await knowledgeService.toggleLike(blogId);
    await post.reload();
  });

  const addComment = useSubmit(async () => {
    await knowledgeService.addComment(blogId, comment.trim());
    setComment('');
    await post.reload();
  });

  const data = post.data;

  return (
    <MobileScreen title={data?.title || '지식공유'} showBackButton>
      <ScreenState query={post} loadingLabel="게시글을 불러오는 중입니다">
        <>
          <section className="mobile-card mobile-section">
            <p className="mobile-card__meta">
              {[data?.authorNickname, String(data?.createdAt || '').slice(0, 10)]
                .filter(Boolean)
                .join(' · ')}
            </p>

            {data?.imagePresignedUrl && (
              <img className="mobile-post__image" src={data.imagePresignedUrl} alt="" />
            )}

            <p className="mobile-paragraph">{data?.content}</p>

            {data?.pdfPresignedUrl && (
              <Button variant="secondary" onClick={() => openExternalUrl(data.pdfPresignedUrl)}>
                <FileText size={16} />
                첨부 자료 열기
              </Button>
            )}

            <div className="mobile-card__actions">
              <Button
                variant={data?.likedByCurrentUser ? 'primary' : 'secondary'}
                isLoading={toggleLike.isSubmitting}
                onClick={() => toggleLike.submit().catch(() => {})}
              >
                <Heart size={16} />
                {data?.likeCount ?? 0}
              </Button>
            </div>
          </section>

          <section className="mobile-section">
            <h3 className="mobile-section__title">댓글 {data?.comments?.length ?? 0}</h3>

            <ul className="mobile-list">
              {(data?.comments || []).map((entry) => (
                <li key={entry.commentId ?? entry.id} className="mobile-card">
                  <p className="mobile-card__meta">{entry.authorNickname}</p>
                  <p className="mobile-paragraph">{entry.content}</p>
                </li>
              ))}
            </ul>
          </section>

          <TextField
            as="textarea"
            label="댓글 작성"
            value={comment}
            placeholder="의견을 남겨보세요"
            error={addComment.errorMessage}
            onChange={(event) => setComment(event.target.value)}
          />

          <Button
            fullWidth
            isLoading={addComment.isSubmitting}
            disabled={!comment.trim()}
            onClick={() => addComment.submit().catch(() => {})}
          >
            댓글 등록
          </Button>
        </>
      </ScreenState>
    </MobileScreen>
  );
}
