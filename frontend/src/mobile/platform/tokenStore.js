import { Capacitor, registerPlugin } from '@capacitor/core';
import { Preferences } from '@capacitor/preferences';
import {
  LEGACY_PLAINTEXT_TOKEN_KEYS,
  PROFILE_KEYS,
  planSessionRestore,
  stripTokensFromProfile,
} from '../auth/sessionRecovery';

const SecureSession = registerPlugin('StudyBridgeSecureSession');

function readLocalProfile() {
  return Object.fromEntries(PROFILE_KEYS.map((key) => [key, localStorage.getItem(key)]));
}

async function readDeviceProfile() {
  const entries = await Promise.all(
    PROFILE_KEYS.map(async (key) => [key, (await Preferences.get({ key })).value])
  );
  return Object.fromEntries(entries);
}

async function readVaultRefreshToken() {
  const { refreshToken } = await SecureSession.readRefreshToken();
  return refreshToken || null;
}

async function removeLegacyPlaintextTokens() {
  await Promise.all(LEGACY_PLAINTEXT_TOKEN_KEYS.map((key) => Preferences.remove({ key })));
}

export async function restoreSessionFromDevice() {
  if (!Capacitor.isNativePlatform()) return;

  await removeLegacyPlaintextTokens();

  const plan = planSessionRestore({
    localRefreshToken: localStorage.getItem('refreshToken'),
    vaultRefreshToken: await readVaultRefreshToken(),
    localProfile: readLocalProfile(),
    deviceProfile: await readDeviceProfile(),
  });

  if (plan.refreshTokenToRestore) {
    localStorage.setItem('refreshToken', plan.refreshTokenToRestore);
  }

  Object.entries(plan.profileToRestore).forEach(([key, value]) => {
    localStorage.setItem(key, value);
  });
}

export async function persistSessionToDevice() {
  if (!Capacitor.isNativePlatform()) return;

  const refreshToken = localStorage.getItem('refreshToken');

  if (refreshToken) {
    await SecureSession.writeRefreshToken({ refreshToken });
  } else {
    await SecureSession.clear();
  }

  await Promise.all(
    PROFILE_KEYS.map((key) => {
      const value = stripTokensFromProfile(key, localStorage.getItem(key));
      return value === null ? Preferences.remove({ key }) : Preferences.set({ key, value });
    })
  );
}

export async function clearSessionOnDevice() {
  if (!Capacitor.isNativePlatform()) return;

  await SecureSession.clear();
  await Promise.all(
    [...PROFILE_KEYS, ...LEGACY_PLAINTEXT_TOKEN_KEYS].map((key) => Preferences.remove({ key }))
  );
}
