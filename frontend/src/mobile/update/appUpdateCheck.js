import { readInstalledApp } from '../platform/installedApp';
import { RELEASE_STATUS, fetchLatestRelease } from './latestRelease';
import { UPDATE_KIND, decideUpdate, parseReleaseManifest } from './releaseManifest';

const NO_UPDATE = { kind: UPDATE_KIND.NONE, problem: null };
const LOG_PREFIX = '[app-update]';

export async function checkForAppUpdate({
  readApp = readInstalledApp,
  fetchRelease = fetchLatestRelease,
} = {}) {
  try {
    const installedApp = await readApp();
    if (!installedApp) return NO_UPDATE;

    const release = await fetchRelease();
    if (release.status === RELEASE_STATUS.NO_RELEASE) return NO_UPDATE;

    const { manifest, problem } = parseReleaseManifest(release.body);
    if (!manifest) {
      console.warn(`${LOG_PREFIX} 배포 정보를 무시합니다: ${problem}`);
      return NO_UPDATE;
    }

    const decision = decideUpdate(installedApp, manifest);
    if (decision.problem) console.error(`${LOG_PREFIX} 배포 정보를 거부합니다: ${decision.problem}`);
    return decision;
  } catch (error) {
    console.warn(`${LOG_PREFIX} 업데이트 확인을 건너뜁니다.`, error);
    return NO_UPDATE;
  }
}

export function createUpdateSession(check = checkForAppUpdate) {
  let pendingCheck = null;
  const dismissedVersionCodes = new Set();

  return {
    check() {
      if (!pendingCheck) pendingCheck = check();
      return pendingCheck;
    },
    dismiss(versionCode) {
      dismissedVersionCodes.add(versionCode);
    },
    isDismissed(versionCode) {
      return dismissedVersionCodes.has(versionCode);
    },
  };
}

export const appUpdateSession = createUpdateSession();
