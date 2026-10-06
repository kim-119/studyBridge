import { Capacitor, CapacitorHttp } from '@capacitor/core';

const DOWNLOAD_TIMEOUT_MS = 60000;

export class PdfDownloadError extends Error {
  constructor(message, status = null) {
    super(message);
    this.name = 'PdfDownloadError';
    this.status = status;
  }
}

export function canDownloadPdfNatively() {
  return Capacitor.isNativePlatform();
}

function base64ToBytes(base64) {
  const binary = window.atob(String(base64).replace(/\s/g, ''));
  const bytes = new Uint8Array(binary.length);
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index);
  }
  return bytes;
}

function isSuccessStatus(status) {
  return status >= 200 && status < 300;
}

export async function downloadPdfBytes(url) {
  let response;
  try {
    response = await CapacitorHttp.get({
      url,
      responseType: 'arraybuffer',
      connectTimeout: DOWNLOAD_TIMEOUT_MS,
      readTimeout: DOWNLOAD_TIMEOUT_MS,
    });
  } catch (error) {
    throw new PdfDownloadError(error?.message || 'PDF download failed');
  }

  if (!isSuccessStatus(response.status)) {
    throw new PdfDownloadError(`PDF download failed with status ${response.status}`, response.status);
  }

  if (typeof response.data !== 'string' || response.data.length === 0) {
    throw new PdfDownloadError('PDF download returned no data', response.status);
  }

  return base64ToBytes(response.data);
}
