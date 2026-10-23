import React, { useRef, useState } from 'react';
import { FileText, ImagePlus, Paperclip, X } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import Button from '../../components/Button';
import TextField from '../../components/TextField';
import MobileScreen from '../../shell/MobileScreen';
import { useSubmit } from '../../data/useAsync';
import { IMAGE_ACCEPT, PDF_ACCEPT, attachmentError, totalUploadError } from './knowledgeModel';
import { createKnowledgePost } from './knowledgeUpload';
import './knowledge.css';

function SelectedAttachment({ icon, file, label, onRemove }) {
  if (!file) return null;

  return (
    <li className="knowledge-attachment">
      {icon}
      <span className="knowledge-attachment__name">{file.name}</span>
      <button type="button" className="mobile-row__more" aria-label={`${label} 첨부 취소`} onClick={onRemove}>
        <X size={16} />
      </button>
    </li>
  );
}

function useAttachment(kind) {
  const inputRef = useRef(null);
  const [file, setFile] = useState(null);
  const [error, setError] = useState(null);

  const select = (event) => {
    const selected = event.target.files?.[0] || null;
    event.target.value = '';
    if (!selected) return;

    const problem = attachmentError(selected, kind);
    setError(problem);
    if (!problem) setFile(selected);
  };

  return {
    inputRef,
    file,
    error,
    select,
    open: () => inputRef.current?.click(),
    clear: () => {
      setFile(null);
      setError(null);
    },
  };
}

export default function KnowledgeCreateScreen() {
  const navigate = useNavigate();
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const image = useAttachment('image');
  const pdf = useAttachment('pdf');
  const sizeError = totalUploadError([image.file, pdf.file]);

  const createPost = useSubmit(async () => {
    const created = await createKnowledgePost({
      title: title.trim(),
      content: content.trim(),
      imageFile: image.file,
      pdfFile: pdf.file,
    });
    navigate(created?.blogId ? `/knowledge/${created.blogId}` : '/knowledge', { replace: true });
  });

  const handleSubmit = (event) => {
    event.preventDefault();
    createPost.submit().catch(() => {});
  };

  const attachmentMessage = image.error || pdf.error || sizeError;

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
          <Button variant="secondary" onClick={image.open}>
            <ImagePlus size={16} />
            {image.file ? '이미지 변경' : '이미지 첨부'}
          </Button>

          <Button variant="secondary" onClick={pdf.open}>
            <Paperclip size={16} />
            {pdf.file ? 'PDF 변경' : 'PDF 첨부'}
          </Button>
        </div>

        <ul className="knowledge-attachments">
          <SelectedAttachment icon={<ImagePlus size={16} />} file={image.file} label="이미지" onRemove={image.clear} />
          <SelectedAttachment icon={<FileText size={16} />} file={pdf.file} label="PDF" onRemove={pdf.clear} />
        </ul>

        {attachmentMessage && <p className="mobile-field__error">{attachmentMessage}</p>}

        <input ref={image.inputRef} type="file" accept={IMAGE_ACCEPT} hidden onChange={image.select} />
        <input ref={pdf.inputRef} type="file" accept={PDF_ACCEPT} hidden onChange={pdf.select} />

        <Button
          type="submit"
          fullWidth
          isLoading={createPost.isSubmitting}
          disabled={!title.trim() || !content.trim() || Boolean(sizeError)}
        >
          게시하기
        </Button>
      </form>
    </MobileScreen>
  );
}
