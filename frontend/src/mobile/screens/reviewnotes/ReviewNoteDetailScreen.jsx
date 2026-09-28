import React, { useState } from 'react';
import { Download, RotateCcw, Trash2 } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import Button from '../../components/Button';
import ScreenState from '../../components/ScreenState';
import SubTabs from '../../components/SubTabs';
import MobileScreen from '../../shell/MobileScreen';
import { reviewNoteService } from '../../../services/api';
import { useAsync, useSubmit } from '../../data/useAsync';
import { extractDownloadUrl } from '../../platform/downloadUrl';
import { openExternalUrl } from '../../platform/externalLink';
import ReviewNoteAiPanel from './ReviewNoteAiPanel';
import ReviewNoteReviewActions from './ReviewNoteReviewActions';
import ReviewNoteVariantPanel from './ReviewNoteVariantPanel';
import useVariantSession from './useVariantSession';
import {
  difficultyLabel,
  formatNoteDate,
  reviewDateBadges,
  reviewTargetCount,
} from './reviewNoteModel';
import './reviewNotes.css';

const DETAIL_TAB = {
  VARIANT: 'variant',
  AI: 'ai',
};

const DETAIL_TABS = [
  { key: DETAIL_TAB.VARIANT, label: '유사문제' },
  { key: DETAIL_TAB.AI, label: 'AI 해설' },
];

function ReviewNoteOverview({ note }) {
  const badges = reviewDateBadges(note);

  return (
    <section className="mobile-card mobile-section">
      <p className="mobile-card__meta">
        원본 자료: {note.sourceName || note.originalMaterialTitle || '-'}
      </p>
      <p className="mobile-review__counts">
        <span className="mobile-review__wrong">오답 {note.wrongCount ?? 0}개</span>
        {(note.unansweredCount ?? 0) > 0 && (
          <span className="mobile-review__unanswered">미응답 {note.unansweredCount}개</span>
        )}
        <span>복습 필요 {reviewTargetCount(note)}개</span>
      </p>

      {note.recommendedReviewDate && (
        <div className="mobile-review__date">
          <span>추천 복습일 {note.recommendedReviewDate}</span>
          {badges.map((badge) => (
            <span key={badge.key} className={`mobile-review__badge mobile-review__badge--${badge.tone}`}>
              {badge.label}
            </span>
          ))}
        </div>
      )}

      {note.reviewReason && <p className="mobile-paragraph">{note.reviewReason}</p>}

      <p className="mobile-card__meta mobile-review__footnote">
        난이도 {difficultyLabel(note.difficulty) || '-'} · 생성일 {formatNoteDate(note.createdAt)}
      </p>
    </section>
  );
}

export default function ReviewNoteDetailScreen() {
  const { reviewNoteId } = useParams();
  const navigate = useNavigate();
  const note = useAsync(() => reviewNoteService.getReviewNote(reviewNoteId), [reviewNoteId]);
  const [activeTab, setActiveTab] = useState(DETAIL_TAB.VARIANT);
  const variant = useVariantSession(reviewNoteId);
  const [isConfirmingDelete, setConfirmingDelete] = useState(false);

  const download = useSubmit(async () => {
    const response = await reviewNoteService.getDownloadUrl(reviewNoteId);
    const url = extractDownloadUrl(response) || note.data?.pdfUrl;
    if (!url) throw new Error('이 오답노트에는 아직 PDF가 없습니다.');
    await openExternalUrl(url);
  });

  const removeNote = useSubmit(async () => {
    await reviewNoteService.deleteReviewNote(reviewNoteId);
    variant.clear();
    navigate('/review-notes', { replace: true });
  });

  const data = note.data;
  const actionError = download.errorMessage || removeNote.errorMessage;

  return (
    <MobileScreen title={data?.title || '오답노트'} showBackButton>
      <ScreenState query={note} loadingLabel="오답노트를 불러오는 중입니다">
        {data && (
          <>
            <ReviewNoteOverview note={data} />

            <div className="mobile-actions mobile-section">
              <Button variant="action" onClick={() => navigate(`/review-notes/${reviewNoteId}/retry`)}>
                <RotateCcw size={16} />
                다시 풀기
              </Button>

              <Button
                variant="secondary"
                isLoading={download.isSubmitting}
                onClick={() => download.submit().catch(() => {})}
              >
                <Download size={16} />
                PDF 열기
              </Button>

              <Button variant="ghost" onClick={() => setConfirmingDelete(true)}>
                <Trash2 size={16} />
                삭제
              </Button>
            </div>

            {isConfirmingDelete && (
              <section className="mobile-card mobile-section">
                <p className="mobile-paragraph">이 오답노트를 삭제할까요? 되돌릴 수 없습니다.</p>
                <div className="mobile-card__actions">
                  <Button variant="secondary" onClick={() => setConfirmingDelete(false)}>
                    취소
                  </Button>
                  <Button
                    variant="danger"
                    isLoading={removeNote.isSubmitting}
                    onClick={() => removeNote.submit().catch(() => {})}
                  >
                    삭제
                  </Button>
                </div>
              </section>
            )}

            {actionError && <p className="mobile-auth__error">{actionError}</p>}

            <ReviewNoteReviewActions reviewNoteId={reviewNoteId} note={data} onChanged={note.reload} />

            <SubTabs tabs={DETAIL_TABS} activeKey={activeTab} onChange={setActiveTab} />

            {activeTab === DETAIL_TAB.VARIANT && <ReviewNoteVariantPanel note={data} variant={variant} />}
            {activeTab === DETAIL_TAB.AI && <ReviewNoteAiPanel reviewNoteId={reviewNoteId} note={data} />}
          </>
        )}
      </ScreenState>
    </MobileScreen>
  );
}
