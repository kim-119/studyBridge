import { useState } from 'react';
import { groupService } from '../../../../services/api';
import { describeApiError } from '../../../data/useAsync';
import { useBackgroundTask } from '../../../data/useBackgroundTask';
import {
  describeUploadFailure,
  describeUploadListRefreshFailure,
  describeUploadOutcome,
  groupMaterialUploadTaskKey,
  materialTitleFromFileName,
  quizIdsOf,
  validateMaterialFile,
  withUploadedMaterial,
} from '../materialUploadModel';
import { serverReasonOf } from '../quizGenerationModel';

const UPLOAD_ERROR_OVERRIDES = {
  413: 'PDF 파일이 서버 허용 용량보다 큽니다.',
};

async function uploadGroupMaterial({ groupId, file, options, materials, quizzes }) {
  const title = materialTitleFromFileName(file.name);
  const quizIdsBefore = quizIdsOf(quizzes.data);
  const material = await groupService.uploadQuizMaterial(groupId, title, file, options);

  if (material?.id != null) materials.setData((list) => withUploadedMaterial(list, material));

  try {
    const [, refreshedQuizzes] = await Promise.all([materials.reload(), quizzes.reload()]);
    return describeUploadOutcome({ material, title, quizIdsBefore, refreshedQuizzes });
  } catch (error) {
    return describeUploadListRefreshFailure({ material, title, reason: describeApiError(error) });
  }
}

function describeUploadError(error) {
  return describeUploadFailure(serverReasonOf(error) || describeApiError(error, UPLOAD_ERROR_OVERRIDES));
}

function outcomeOf(upload) {
  if (upload.isReady) return upload.result;
  if (upload.isFailed) return { isSuccess: false, materialId: null, message: describeUploadError(upload.error) };
  return null;
}

export function useMaterialUpload(groupId, { materials, quizzes }) {
  const upload = useBackgroundTask(groupMaterialUploadTaskKey(groupId));
  const [fileError, setFileError] = useState(null);

  const start = (file, options) => {
    const validationError = validateMaterialFile(file);
    setFileError(validationError);
    if (validationError) return;

    upload
      .run(() => uploadGroupMaterial({ groupId, file, options, materials, quizzes }), {
        context: { fileName: file.name },
      })
      .catch((error) => console.warn('그룹 학습자료 업로드에 실패했습니다.', error));
  };

  return {
    isUploading: upload.isGenerating,
    uploadingFileName: upload.isGenerating ? upload.context?.fileName ?? null : null,
    fileError,
    outcome: fileError ? null : outcomeOf(upload),
    start,
  };
}
