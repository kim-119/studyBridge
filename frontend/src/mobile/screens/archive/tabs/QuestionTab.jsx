import React, { useState } from 'react';
import Button from '../../../components/Button';
import TextField from '../../../components/TextField';
import { materialService } from '../../../../services/api';
import { useSubmit } from '../../../data/useAsync';

export default function QuestionTab({ materialId }) {
  const [question, setQuestion] = useState('');
  const [history, setHistory] = useState([]);

  const askQuestion = useSubmit(async () => {
    const asked = question.trim();
    const response = await materialService.askQuestion(materialId, { userQuestion: asked });

    setHistory((previous) => [
      ...previous,
      { question: asked, answer: response?.aiAnswer || response?.message || '답변을 받지 못했습니다.' },
    ]);
    setQuestion('');
  });

  return (
    <section>
      {history.map((entry) => (
        <article key={entry.question} className="mobile-card mobile-section">
          <p className="mobile-qa__question">{entry.question}</p>
          <p className="mobile-paragraph">{entry.answer}</p>
        </article>
      ))}

      <TextField
        as="textarea"
        label="AI에게 질문하기"
        value={question}
        placeholder="이 자료에 대해 궁금한 점을 물어보세요"
        error={askQuestion.errorMessage}
        onChange={(event) => setQuestion(event.target.value)}
      />

      <Button
        fullWidth
        isLoading={askQuestion.isSubmitting}
        disabled={!question.trim()}
        onClick={() => askQuestion.submit().catch(() => {})}
      >
        질문 보내기
      </Button>
    </section>
  );
}
