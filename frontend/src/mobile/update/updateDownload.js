import { openExternalUrl } from '../platform/externalLink';
import { isHttpsUrl } from './releaseManifest';

export async function openUpdateDownload(downloadUrl, openUrl = openExternalUrl) {
  if (!isHttpsUrl(downloadUrl)) {
    console.error('[app-update] https 가 아닌 다운로드 주소는 열지 않습니다.', downloadUrl);
    return false;
  }

  try {
    await openUrl(downloadUrl);
    return true;
  } catch (error) {
    console.warn('[app-update] 다운로드 주소를 열지 못했습니다.', error);
    return false;
  }
}
