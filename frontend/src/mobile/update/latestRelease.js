const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || '';
const LATEST_RELEASE_PATH = '/api/app/version';
const NO_RELEASE_CODE = 'NO_RELEASE';
const REQUEST_TIMEOUT_MS = 10000;

export const RELEASE_STATUS = {
  AVAILABLE: 'available',
  NO_RELEASE: 'no-release',
};

async function readJsonOrNull(response) {
  try {
    return await response.json();
  } catch {
    return null;
  }
}

export async function fetchLatestRelease({ fetchImpl = fetch, timeoutMs = REQUEST_TIMEOUT_MS } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetchImpl(`${API_BASE_URL}${LATEST_RELEASE_PATH}`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      cache: 'no-store',
      credentials: 'omit',
      signal: controller.signal,
    });
    const body = await readJsonOrNull(response);

    if (response.status === 404 && body?.code === NO_RELEASE_CODE) {
      return { status: RELEASE_STATUS.NO_RELEASE, body: null };
    }

    if (!response.ok) {
      throw new Error(`latest release request failed with HTTP ${response.status}`);
    }

    return { status: RELEASE_STATUS.AVAILABLE, body };
  } finally {
    clearTimeout(timer);
  }
}
