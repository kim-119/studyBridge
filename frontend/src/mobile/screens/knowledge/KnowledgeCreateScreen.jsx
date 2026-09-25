import React, { useRef, useState } from 'react';
import { ImagePlus, Paperclip } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import Button from '../../components/Button';
import TextField from '../../components/TextField';
import MobileScreen from '../../shell/MobileScreen';
import { knowledgeService } from '../../../services/api';
import { useSubmit } from '../../data/useAsync';

export default function KnowledgeCreateScreen() {
  const navigate = useNavigate();
  const imageInput = useRef(null);
  const pdfInput = useRef(null);
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [imageFile, setImageFile] = useState(null);
  const [pdfFile, setPdfFile] = useState(null);

  const createPost = useSubmit(async () => {
    const created = await knowledgeService.createPost(title.trim(), content.trim(), imageFile, pdfFile);
    navigate(created?.blogId ? `/knowledge/${created.blogId}` : '/knowledge', { replace: true });
  });

  const handleSubmit = (event) => {
    event.preventDefault();
    createPost.submit().catch(() => {});
  };

  return (
    <MobileScreen title="새 게시글" showBackButton>
      <form onSubmit={handleSubmit}>
        <TextField label="제목" value={title} onChange={(event) => setTitle(event.target.value)} />

        <TextField
          as="textarea"
          label="본문"
          value={content}
          placeholder="공유하고 싶은 학습 내용을 적어주세요"
          error={createPost.errorMessage}
          onChange={(event) => setContent(event.target.value)}
        />

        <div className="mobile-actions mobile-section">
          <Button variant="secondary" onClick={() => imageInput.current?.click()}>
            <ImagePlus size={16} />
            {imageFile ? '이미지 변경' : '이미지 첨부'}
          </Button>

          <Button variant="secondary" onClick={() => pdfInput.current?.click()}>
            <Paperclip size={16} />
            {pdfFile ? 'PDF 변경' : 'PDF 첨부'}
          </Button>
        </div>

        {(imageFile || pdfFile) && (
          <p className="mobile-field__hint">
            {[imageFile?.name, pdfFile?.name].filter(Boolean).join(' · ')}
          </p>
        )}

        <input
          ref={imageInput}
          type="file"
          accept="image/*"
          hidden
          onChange={(event) => setImageFile(event.target.files?.[0] || null)}
        />
        <input
          ref={pdfInput}
          type="file"
          accept="application/pdf"
          hidden
          onChange={(event) => setPdfFile(event.target.files?.[0] || null)}
        />

        <Button
          type="submit"
          fullWidth
          isLoading={createPost.isSubmitting}
          disabled={!title.trim() || !content.trim()}
        >
          게시하기
        </Button>
      </form>
    </MobileScreen>
  );
}
