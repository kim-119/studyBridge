import React, { useCallback, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import Button from '../../components/Button';
import ImageViewer from '../../components/ImageViewer';
import ScreenState from '../../components/ScreenState';
import TextField from '../../components/TextField';
import MobileScreen from '../../shell/MobileScreen';
import { knowledgeService } from '../../../services/api';
import { useAuth } from '../../../hooks/useAuth';
import { useAsync, useSubmit } from '../../data/useAsync';
import KnowledgeActionSheet from './KnowledgeActionSheet';
import KnowledgeComments from './KnowledgeComments';
import KnowledgePdfAttachment from './KnowledgePdfAttachment';
import { KnowledgePostActions, KnowledgePostHeader, KnowledgePostImage } from './KnowledgePostParts';
import { isOwnedBy, updatePostIn } from './knowledgeModel';
import { useLikeToggle } from './useLikeToggle';
import { useReloadWhenVisible } from './useReloadWhenVisible';
import './knowledge.css';

const REPORT_RECEIVED_NOTICE = '신고가 접수되었습니다. 운영진이 확인 후 조치합니다.';

function useTargetActions(blogId, { reload, onPostDeleted, onReported }) {
  const deleteTarget = async (target) => {
    if (target.kind === 'post') {
      await knowledgeService.deletePost(target.id);
      onPostDeleted();
      return;
    }
    await knowledgeService.deleteComment(blogId, target.id);
    await reload();
  };

  const reportTarget = async (target, payload) => {
    if (target.kind === 'post') await knowledgeService.reportPost(target.id, payload);
    else await knowledgeService.reportComment(target.id, payload);
    onReported();
  };

  return { deleteTarget, reportTarget };
}

export default function KnowledgeDetailScreen() {
  const { blogId } = useParams();
  const navigate = useNavigate();
  const { userId } = useAuth();
  const post = useAsync(() => knowledgeService.getPostDetail(blogId), [blogId]);
  const { setData, reload } = post;
  const commentsSection = useRef(null);
  const [comment, setComment] = useState('');
  const [viewerImage, setViewerImage] = useState(null);
  const [sheetTarget, setSheetTarget] = useState(null);
  const [notice, setNotice] = useState(null);

  useReloadWhenVisible(reload);

  const updatePost = useCallback((id, updater) => setData((current) => updatePostIn(current, id, updater)), [setData]);
  const like = useLikeToggle(updatePost);
  const closeSheet = () => setSheetTarget(null);

  const { deleteTarget, reportTarget } = useTargetActions(blogId, {
    reload: async () => {
      closeSheet();
      await reload();
    },
    onPostDeleted: () => navigate('/knowledge', { replace: true }),
    onReported: () => {
      closeSheet();
      setNotice(REPORT_RECEIVED_NOTICE);
    },
  });

  const addComment = useSubmit(async () => {
    await knowledgeService.addComment(blogId, comment.trim());
    setComment('');
    await reload();
  });

  const openSheet = (target) => {
    setNotice(null);
    setSheetTarget(target);
  };

  const data = post.data;

  return (
    <MobileScreen title="지식공유" showBackButton>
      <ScreenState query={post} loadingLabel="게시글을 불러오는 중입니다">
        {data && (
          <>
            <article className="knowledge-post">
              <KnowledgePostHeader
                post={data}
                onMore={() => openSheet({ kind: 'post', id: data.blogId, isMine: isOwnedBy(data, userId) })}
              />
              <KnowledgePostImage post={data} onOpenImage={setViewerImage} />
              <KnowledgePostActions
                post={data}
                isLikePending={like.isPending(data.blogId)}
                onToggleLike={like.toggleLike}
                onComment={() => commentsSection.current?.scrollIntoView?.({ behavior: 'smooth' })}
              />
              {like.errorMessage && <p className="mobile-auth__error">{like.errorMessage}</p>}
              <div className="knowledge-post__content">
                <h2 className="knowledge-post__title">{data.title}</h2>
                <p className="knowledge-post__text">{data.content}</p>
              </div>
              <KnowledgePdfAttachment
                url={data.pdfPresignedUrl}
                title={data.title}
                onRefreshUrl={async () => (await reload())?.pdfPresignedUrl}
              />
            </article>

            {notice && (
              <p className="mobile-notice mobile-section" role="status">
                {notice}
              </p>
            )}

            <section ref={commentsSection} className="mobile-section" aria-label="댓글">
              <h3 className="mobile-section__title">댓글 {data.comments?.length ?? 0}</h3>
              <KnowledgeComments comments={data.comments || []} userId={userId} onMore={openSheet} />
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
        )}
      </ScreenState>

      <KnowledgeActionSheet
        target={sheetTarget}
        onClose={closeSheet}
        onDelete={deleteTarget}
        onReport={reportTarget}
      />
      <ImageViewer src={viewerImage} alt={data?.title || ''} onClose={() => setViewerImage(null)} />
    </MobileScreen>
  );
}
