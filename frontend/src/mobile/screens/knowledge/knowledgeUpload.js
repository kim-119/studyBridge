import api, { MATERIAL_UPLOAD_TIMEOUT_MS } from '../../../services/api';

export function buildPostFormData({ title, content, imageFile, pdfFile }) {
  const formData = new FormData();
  formData.append('title', title);
  formData.append('content', content);
  if (imageFile) formData.append('image', imageFile, imageFile.name);
  if (pdfFile) formData.append('pdf', pdfFile, pdfFile.name);
  return formData;
}

export async function createKnowledgePost(fields) {
  const response = await api.post('/api/blogs', buildPostFormData(fields), {
    timeout: MATERIAL_UPLOAD_TIMEOUT_MS,
    headers: { 'Content-Type': 'multipart/form-data' },
  });
  return response.data;
}
