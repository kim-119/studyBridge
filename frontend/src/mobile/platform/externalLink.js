import { Browser } from '@capacitor/browser';
import { Capacitor } from '@capacitor/core';

export async function openExternalUrl(url) {
  if (!url) return;

  if (!Capacitor.isNativePlatform()) {
    window.open(url, '_blank', 'noopener');
    return;
  }

  await Browser.open({ url, presentationStyle: 'popover' });
}
