import { Preferences } from '@capacitor/preferences';

const MIRRORED_KEYS = ['token', 'refreshToken', 'user', 'userId', 'userEmail'];

export async function restoreSessionFromDevice() {
  const entries = await Promise.all(
    MIRRORED_KEYS.map(async (key) => [key, (await Preferences.get({ key })).value])
  );

  entries.forEach(([key, value]) => {
    if (value === null) {
      localStorage.removeItem(key);
    } else {
      localStorage.setItem(key, value);
    }
  });
}

export async function persistSessionToDevice() {
  await Promise.all(
    MIRRORED_KEYS.map((key) => {
      const value = localStorage.getItem(key);
      return value === null
        ? Preferences.remove({ key })
        : Preferences.set({ key, value });
    })
  );
}

export async function clearSessionOnDevice() {
  await Promise.all(MIRRORED_KEYS.map((key) => Preferences.remove({ key })));
}
