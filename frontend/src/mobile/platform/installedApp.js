import { App } from '@capacitor/app';
import { Capacitor } from '@capacitor/core';
import { parseVersionCode } from '../update/releaseManifest';

export async function readInstalledApp() {
  if (!Capacitor.isNativePlatform()) return null;

  const info = await App.getInfo();
  const versionCode = parseVersionCode(info?.build);

  if (versionCode === null || !info?.id) {
    throw new Error(`installed app info is invalid: id=${info?.id} build=${info?.build}`);
  }

  return {
    packageName: info.id,
    versionName: info.version || String(versionCode),
    versionCode,
  };
}
