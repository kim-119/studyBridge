/**
 * 다운로드 URL 응답 형태가 엔드포인트마다 다르다.
 *   planners/{id}/download-url        → { downloadUrl }
 *   groups/materials/{id}/download    → { downloadUrl }
 *   review-notes/{id}/download        → { url, fileName }
 * 한 곳에서 모든 키를 해석해 화면별 누락을 막는다.
 */
export function extractDownloadUrl(response) {
  if (!response) return null;
  if (typeof response === 'string') return response;

  return (
    response.downloadUrl ||
    response.presignedUrl ||
    response.pdfUrl ||
    response.url ||
    null
  );
}
