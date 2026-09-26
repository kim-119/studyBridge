import React, { useEffect, useState } from 'react';
import { CalendarPlus, Download, Sparkles } from 'lucide-react';
import { useParams } from 'react-router-dom';
import Button from '../../components/Button';
import ScreenState from '../../components/ScreenState';
import TextField from '../../components/TextField';
import MobileScreen from '../../shell/MobileScreen';
import { reviewNoteService } from '../../../services/api';
import { useAsync, useSubmit } from '../../data/useAsync';
import { extractDownloadUrl } from '../../platform/downloadUrl';
import { openExternalUrl } from '../../platform/externalLink';

export default function ReviewNoteDetailScreen() {
  const { reviewNoteId } = useParams();
  const note = useAsync(() => reviewNoteService.getReviewNote(reviewNoteId), [reviewNoteId]);
  const [memo, setMemo] = useState('');

  useEffect(() => {
    if (note.data) setMemo(note.data.memo || '');
  }, [note.data]);

  const saveMemo = useSubmit(async () => {
    await reviewNoteService.updateMemo(reviewNoteId, memo);
    await note.reload();
  });

  const download = useSubmit(async () => {
    const response = await reviewNoteService.getDownloadUrl(reviewNoteId);
    await openExternalUrl(extractDownloadUrl(response));
  });

  const requestVariant = useSubmit(async () => {
    await reviewNoteService.variantQuestion(reviewNoteId, { count: 3 });
    await note.reload();
  });

  const scheduleReview = useSubmit(async () => {
    await reviewNoteService.reviewNeeded(reviewNoteId);
    await note.reload();
  });

  const data = note.data;

  return (
    <MobileScreen title={data?.title || '오답노트'} showBackButton>
      <ScreenState query={note} loadingLabel="오답노트를 불러오는 중입니다">
        <>
          <section className="mobile-card mobile-section">
            <p className="mobile-card__meta">
              {[
                data?.sourceName,
                `오답 ${data?.wrongCount ?? 0}`,
                `미응답 ${data?.unansweredCount ?? 0}`,
              ]
                .filter(Boolean)
                .join(' · ')}
            </p>

            {data?.reviewReason && <p className="mobile-paragraph">{data.reviewReason}</p>}

            {data?.recommendedReviewDate && (
              <p className="mobile-card__meta">추천 복습일 {data.recommendedReviewDate}</p>
            )}
          </section>

          <div className="mobile-actions mobile-section">
            <Button
              variant="secondary"
              isLoading={download.isSubmitting}
              onClick={() => download.submit().catch(() => {})}
            >
              <Download size={16} />
              PDF 열기
            </Button>

            <Button
              variant="secondary"
              isLoading={requestVariant.isSubmitting}
              onClick={() => requestVariant.submit().catch(() => {})}
            >
              <Sparkles size={16} />
              유사 문제
            </Button>

            <Button
              variant="secondary"
              isLoading={scheduleReview.isSubmitting}
              disabled={data?.reviewScheduled}
              onClick={() => scheduleReview.submit().catch(() => {})}
            >
              <CalendarPlus size={16} />
              {data?.reviewScheduled ? '일정 등록됨' : '복습 일정'}
            </Button>
          </div>

          {data?.reviewNeededText && (
            <section className="mobile-card mobile-section">
              <p className="mobile-paragraph">{data.reviewNeededText}</p>
            </section>
          )}

          <TextField
            as="textarea"
            label="메모"
            value={memo}
            placeholder="복습하며 느낀 점을 남겨보세요"
            error={saveMemo.errorMessage}
            onChange={(event) => setMemo(event.target.value)}
          />

          <Button fullWidth isLoading={saveMemo.isSubmitting} onClick={() => saveMemo.submit().catch(() => {})}>
            메모 저장
          </Button>
        </>
      </ScreenState>
    </MobileScreen>
  );
}
