import React, { useState } from 'react';
import { CalendarPlus, Lightbulb } from 'lucide-react';
import Button from '../../components/Button';
import { learningLoopService, reviewNoteService } from '../../../services/api';
import { useSubmit } from '../../data/useAsync';
import {
  cleanText,
  describeScheduleResult,
  registeredScheduleMessage,
  reviewScheduleTitle,
} from './reviewNoteModel';

const REVIEW_NEEDED_FAILURE = '복습 필요 분석을 생성하지 못했습니다. 잠시 후 다시 시도해 주세요.';

function ReviewNeededAnalysis({ reviewNoteId, savedText }) {
  const [generatedText, setGeneratedText] = useState('');
  const [isOpen, setOpen] = useState(false);
  const analysisText = generatedText || savedText || '';

  const analyze = useSubmit(async () => {
    const response = await reviewNoteService.reviewNeeded(reviewNoteId);
    const text = response?.reviewNeededText || '';
    if (!text) throw new Error(REVIEW_NEEDED_FAILURE);
    setGeneratedText(text);
  });

  const handlePress = () => {
    if (analysisText) {
      setOpen((previous) => !previous);
      return;
    }
    setOpen(true);
    analyze.submit().catch(() => {});
  };

  return (
    <>
      <Button variant="action" fullWidth isLoading={analyze.isSubmitting} onClick={handlePress}>
        <Lightbulb size={16} />
        복습 필요 분석
      </Button>

      {isOpen && !analyze.isSubmitting && (
        <div className="mobile-review__callout">
          <strong>복습 필요 분석</strong>
          {analyze.errorMessage ? (
            <p className="mobile-field__error">{analyze.errorMessage}</p>
          ) : (
            <p className="mobile-paragraph">{cleanText(analysisText)}</p>
          )}
        </div>
      )}
    </>
  );
}

function ReviewScheduleRegistration({ reviewNoteId, note, onRegistered }) {
  const [resultMessage, setResultMessage] = useState('');

  const register = useSubmit(async () => {
    setResultMessage('');
    const response = await learningLoopService.registerReviewSchedule({
      wrongNoteId: Number(reviewNoteId),
      title: reviewScheduleTitle(note),
    });
    setResultMessage(describeScheduleResult(response));
    onRegistered().catch(() => {});
  });

  const message = resultMessage || registeredScheduleMessage(note);

  return (
    <>
      <Button
        variant="secondary"
        fullWidth
        isLoading={register.isSubmitting}
        onClick={() => register.submit().catch(() => {})}
      >
        <CalendarPlus size={16} />
        복습 일정 등록
      </Button>

      {register.errorMessage ? (
        <p className="mobile-auth__error">
          복습 일정 등록에 실패했습니다. ({register.errorMessage}) 잠시 후 다시 시도해 주세요.
        </p>
      ) : (
        message && <p className="mobile-review__success">{message}</p>
      )}
    </>
  );
}

export default function ReviewNoteReviewActions({ reviewNoteId, note, onChanged }) {
  return (
    <section className="mobile-card mobile-section mobile-review__actions">
      <ReviewNeededAnalysis reviewNoteId={reviewNoteId} savedText={note.reviewNeededText} />
      <ReviewScheduleRegistration reviewNoteId={reviewNoteId} note={note} onRegistered={onChanged} />
    </section>
  );
}
