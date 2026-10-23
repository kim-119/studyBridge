export const PROFILE_KEYS = ['user', 'userId', 'userEmail'];
export const LEGACY_PLAINTEXT_TOKEN_KEYS = ['token', 'refreshToken'];

export function planSessionRestore({ localRefreshToken, vaultRefreshToken, localProfile, deviceProfile }) {
  if (localRefreshToken) {
    return { refreshTokenToRestore: null, profileToRestore: {} };
  }

  if (!vaultRefreshToken) {
    return { refreshTokenToRestore: null, profileToRestore: {} };
  }

  const profileToRestore = {};
  PROFILE_KEYS.forEach((key) => {
    if (!localProfile[key] && deviceProfile[key]) {
      profileToRestore[key] = deviceProfile[key];
    }
  });

  return { refreshTokenToRestore: vaultRefreshToken, profileToRestore };
}

export function isSessionOrphaned({ userId, token, refreshToken }) {
  return Boolean(userId) && !token && !refreshToken;
}

const TOKEN_FIELDS = ['accessToken', 'refreshToken', 'token'];

export function stripTokensFromProfile(key, value) {
  if (key !== 'user' || value === null) return value;

  try {
    const profile = JSON.parse(value);
    TOKEN_FIELDS.forEach((field) => delete profile[field]);
    return JSON.stringify(profile);
  } catch {
    return null;
  }
}
