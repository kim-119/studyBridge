import { clearSessionOnDevice, persistSessionToDevice, restoreSessionFromDevice } from '../platform/tokenStore';

const AUTH_CHANGE_EVENT = 'auth-change';

export async function restoreSession() {
  await restoreSessionFromDevice();
}

export function hasStoredCredentials() {
  return Boolean(localStorage.getItem('token') || localStorage.getItem('userId'));
}

export function watchSessionChanges() {
  const syncToDevice = () => {
    if (hasStoredCredentials()) {
      persistSessionToDevice().catch(() => {});
    } else {
      clearSessionOnDevice().catch(() => {});
    }
  };

  window.addEventListener(AUTH_CHANGE_EVENT, syncToDevice);

  return () => window.removeEventListener(AUTH_CHANGE_EVENT, syncToDevice);
}
