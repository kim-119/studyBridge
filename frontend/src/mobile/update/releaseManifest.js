export const ANDROID_PLATFORM = 'android';

export const UPDATE_KIND = {
  NONE: 'none',
  OPTIONAL: 'optional',
  FORCED: 'forced',
};

const BYTES_PER_MEGABYTE = 1024 * 1024;

function isPositiveInteger(value) {
  return Number.isInteger(value) && value > 0;
}

function isNonEmptyString(value) {
  return typeof value === 'string' && value.trim().length > 0;
}

export function parseVersionCode(value) {
  if (isPositiveInteger(value)) return value;
  if (typeof value !== 'string' || !/^\d+$/.test(value.trim())) return null;

  const parsed = Number.parseInt(value.trim(), 10);
  return isPositiveInteger(parsed) ? parsed : null;
}

export function isHttpsUrl(value) {
  if (!isNonEmptyString(value)) return false;

  try {
    return new URL(value).protocol === 'https:';
  } catch {
    return false;
  }
}

function readReleaseNotes(value) {
  if (!Array.isArray(value)) return [];
  return value.filter(isNonEmptyString).map((note) => note.trim());
}

function readFileSize(value) {
  return isPositiveInteger(value) ? value : null;
}

export function parseReleaseManifest(body) {
  if (!body || typeof body !== 'object' || Array.isArray(body)) {
    return { manifest: null, problem: 'response is not a JSON object' };
  }

  if (body.platform !== ANDROID_PLATFORM) {
    return { manifest: null, problem: `unsupported platform "${body.platform}"` };
  }

  if (!isNonEmptyString(body.packageName)) {
    return { manifest: null, problem: 'packageName is missing' };
  }

  if (!isPositiveInteger(body.versionCode)) {
    return { manifest: null, problem: `versionCode is not a positive integer: ${JSON.stringify(body.versionCode)}` };
  }

  if (!isNonEmptyString(body.versionName)) {
    return { manifest: null, problem: 'versionName is missing' };
  }

  if (!isHttpsUrl(body.downloadUrl)) {
    return { manifest: null, problem: 'downloadUrl is not an https URL' };
  }

  return {
    manifest: {
      packageName: body.packageName,
      versionCode: body.versionCode,
      versionName: body.versionName.trim(),
      downloadUrl: body.downloadUrl,
      releaseNotes: readReleaseNotes(body.releaseNotes),
      forceUpdate: body.forceUpdate === true,
      minimumSupportedVersionCode: isPositiveInteger(body.minimumSupportedVersionCode)
        ? body.minimumSupportedVersionCode
        : null,
      fileSize: readFileSize(body.fileSize),
    },
    problem: null,
  };
}

function isBelowMinimumSupported(installedApp, manifest) {
  return (
    manifest.minimumSupportedVersionCode !== null &&
    installedApp.versionCode < manifest.minimumSupportedVersionCode
  );
}

export function decideUpdate(installedApp, manifest) {
  if (manifest.packageName !== installedApp.packageName) {
    return {
      kind: UPDATE_KIND.NONE,
      problem: `packageName mismatch: server=${manifest.packageName} installed=${installedApp.packageName}`,
    };
  }

  if (manifest.versionCode <= installedApp.versionCode) {
    return { kind: UPDATE_KIND.NONE, problem: null };
  }

  const isForced = manifest.forceUpdate || isBelowMinimumSupported(installedApp, manifest);

  return {
    kind: isForced ? UPDATE_KIND.FORCED : UPDATE_KIND.OPTIONAL,
    problem: null,
    currentVersionName: installedApp.versionName,
    latestVersionName: manifest.versionName,
    versionCode: manifest.versionCode,
    releaseNotes: manifest.releaseNotes,
    downloadUrl: manifest.downloadUrl,
    fileSize: manifest.fileSize,
  };
}

export function formatFileSize(bytes) {
  if (!isPositiveInteger(bytes)) return null;
  return `${(bytes / BYTES_PER_MEGABYTE).toFixed(1)} MB`;
}
