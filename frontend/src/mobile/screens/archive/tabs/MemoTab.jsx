import React, { useEffect, useState } from 'react';
import Button from '../../../components/Button';
import ScreenState from '../../../components/ScreenState';
import TextField from '../../../components/TextField';
import { materialService } from '../../../../services/api';
import { useAsync, useSubmit } from '../../../data/useAsync';

export default function MemoTab({ materialId }) {
  const memo = useAsync(() => materialService.getMemo(materialId), [materialId]);
  const [content, setContent] = useState('');
  const [isSaved, setSaved] = useState(false);

  useEffect(() => {
    if (memo.data) setContent(memo.data.content || '');
  }, [memo.data]);

  const saveMemo = useSubmit(async () => {
    await materialService.saveMemo(materialId, content);
    setSaved(true);
  });

  return (
    <ScreenState query={memo} loadingLabel="메모를 불러오는 중입니다">
      <section>
        <TextField
          as="textarea"
          label="메모"
          value={content}
          placeholder="이 자료에 대한 메모를 남겨보세요"
          error={saveMemo.errorMessage}
          onChange={(event) => {
            setContent(event.target.value);
            setSaved(false);
          }}
        />

        <Button fullWidth isLoading={saveMemo.isSubmitting} onClick={() => saveMemo.submit().catch(() => {})}>
          {isSaved ? '저장됨' : '메모 저장'}
        </Button>
      </section>
    </ScreenState>
  );
}
