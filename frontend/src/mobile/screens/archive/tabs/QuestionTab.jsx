import React, { useEffect, useState } from 'react';
import Button from '../../../components/Button';
import TextField from '../../../components/TextField';
import { materialService } from '../../../../services/api';
import { describeApiError, useSubmit } from '../../../data/useAsync';
import {
  aiExceptionMessage,
  aiFailureMessage,
  isAiFailure,
  isTextMissing,
  textStatusMessage,
} from '../aiResponseModel';
import {
  SENDER,
  answerTextOf,
  createMessage,
  loadHistory,
  messageKey,
  saveHistory,
} from '../questionHistory';

function answerMessageFor(response, materialId) {
  if (isAiFailure(response)) {
    return createMessage(SENDER.AI, aiFailureMessage(response), materialId, { isError: true });
  }

  return createMessage(SENDER.AI, answerTextOf(response), materialId, {
    routeAction: response?.routeAction || null,
  });
}

function failureMessageFor(error, materialId) {
  const text = aiExceptionMessage(error) || describeApiError(error);
  return createMessage(SENDER.AI, text, materialId, { isError: true });
}

function ChatMessage({ message }) {
  if (message.sender === SENDER.USER) {
    return (
      <li className="mobile-card">
        <p className="mobile-qa__question">{message.text}</p>
      </li>
    );
  }

  return (
    <li className="mobile-card">
      <p className={message.isError ? 'mobile-auth__error' : 'mobile-paragraph'}>{message.text}</p>
    </li>
  );
}

export default function QuestionTab({ materialId, textStatus }) {
  const [question, setQuestion] = useState('');
  const [messages, setMessages] = useState(() => loadHistory(materialId));
  const [latestTextStatus, setLatestTextStatus] = useState(textStatus || null);
  const [isHistorySaved, setHistorySaved] = useState(true);

  useEffect(() => {
    setHistorySaved(saveHistory(materialId, messages));
  }, [materialId, messages]);

  useEffect(() => {
    setLatestTextStatus(textStatus || null);
  }, [textStatus]);

  const askQuestion = useSubmit(async () => {
    const asked = question.trim();
    setQuestion('');
    setMessages((previous) => [...previous, createMessage(SENDER.USER, asked, materialId)]);

    try {
      const response = await materialService.askQuestion(materialId, { userQuestion: asked });
      if (response?.textStatus) setLatestTextStatus(response.textStatus);
      setMessages((previous) => [...previous, answerMessageFor(response, materialId)]);
    } catch (error) {
      setMessages((previous) => [...previous, failureMessageFor(error, materialId)]);
    }
  });

  const isTextUnavailable = isTextMissing(latestTextStatus);

  return (
    <section>
      <ul className="mobile-list mobile-section" aria-live="polite">
        {messages.map((message, index) => (
          <ChatMessage key={messageKey(message, index)} message={message} />
        ))}
      </ul>

      {!isHistorySaved && (
        <p className="mobile-notice mobile-section">이 기기에 질문 기록을 저장하지 못했습니다. 화면을 나가면 기록이 사라집니다.</p>
      )}

      {isTextUnavailable && <p className="mobile-auth__error">{textStatusMessage(latestTextStatus)}</p>}

      <TextField
        as="textarea"
        label="AI에게 질문하기"
        value={question}
        disabled={isTextUnavailable || askQuestion.isSubmitting}
        placeholder="이 자료에 대해 궁금한 점을 물어보세요"
        onChange={(event) => setQuestion(event.target.value)}
      />

      <Button
        fullWidth
        isLoading={askQuestion.isSubmitting}
        disabled={!question.trim() || isTextUnavailable}
        onClick={() => askQuestion.submit().catch(() => {})}
      >
        질문 보내기
      </Button>
    </section>
  );
}
