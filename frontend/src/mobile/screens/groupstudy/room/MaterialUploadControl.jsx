import React from 'react';
import { FileUp } from 'lucide-react';
import Button from '../../../components/Button';
import { MATERIAL_UPLOAD_ACCEPT } from '../materialUploadModel';
import './groupRoom.css';

function uploadButtonClassName(isUploading) {
  return ['mobile-button mobile-button--secondary mobile-button--block', isUploading ? 'is-disabled' : '']
    .filter(Boolean)
    .join(' ');
}

function UploadOutcome({ outcome, onOpenViewer }) {
  if (!outcome) return null;

  if (!outcome.isSuccess) {
    return (
      <p className="mobile-auth__error" role="alert" data-material-upload="failure">
        {outcome.message}
      </p>
    );
  }

  return (
    <div className="mobile-room-upload__result" role="status" data-material-upload="success">
      <p className="mobile-room-quiz-result">{outcome.message}</p>
      {outcome.materialId != null && (
        <Button variant="ghost" onClick={() => onOpenViewer(outcome.materialId)}>
          자료 열기
        </Button>
      )}
    </div>
  );
}

export default function MaterialUploadControl({ upload, quizOptions, onOpenViewer }) {
  const selectFile = (event) => {
    const [file] = event.target.files || [];
    event.target.value = '';
    if (file) upload.start(file, quizOptions);
  };

  return (
    <section className="mobile-room-upload">
      <label className={uploadButtonClassName(upload.isUploading)} aria-disabled={upload.isUploading}>
        {upload.isUploading ? <span className="mobile-button__spinner" /> : <FileUp size={16} />}
        {upload.isUploading ? 'PDF 올리는 중' : 'PDF 자료 올리기'}
        <input
          type="file"
          accept={MATERIAL_UPLOAD_ACCEPT}
          hidden
          disabled={upload.isUploading}
          data-material-upload-input=""
          onChange={selectFile}
        />
      </label>
      <p className="mobile-field__hint">
        {upload.isUploading
          ? `${upload.uploadingFileName || 'PDF'} 자료를 올리고 퀴즈를 만드는 중입니다. 패널을 닫아도 계속됩니다.`
          : 'PDF · 최대 30MB · 올리면 위 설정으로 퀴즈도 함께 만들어집니다.'}
      </p>
      {upload.fileError && (
        <p className="mobile-field__error" role="alert">
          {upload.fileError}
        </p>
      )}
      <UploadOutcome outcome={upload.outcome} onOpenViewer={onOpenViewer} />
    </section>
  );
}
