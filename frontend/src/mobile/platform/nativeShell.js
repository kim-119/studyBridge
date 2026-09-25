import { App } from '@capacitor/app';
import { Capacitor } from '@capacitor/core';
import { SplashScreen } from '@capacitor/splash-screen';
import { StatusBar, Style } from '@capacitor/status-bar';

export function isNativePlatform() {
  return Capacitor.isNativePlatform();
}

export async function applyNativeChrome() {
  if (!isNativePlatform()) return;

  await StatusBar.setStyle({ style: Style.Light });
  await StatusBar.setBackgroundColor({ color: '#FFFFFF' });
}

export async function hideSplashScreen() {
  if (!isNativePlatform()) return;
  await SplashScreen.hide();
}

export function registerHardwareBackButton(onBack) {
  if (!isNativePlatform()) return () => {};

  const handle = App.addListener('backButton', ({ canGoBack }) => {
    const handled = onBack({ canGoBack });
    if (!handled) App.exitApp();
  });

  return () => {
    handle.then((listener) => listener.remove());
  };
}

export function registerAppStateChange(onStateChange) {
  if (!isNativePlatform()) return () => {};

  const handle = App.addListener('appStateChange', onStateChange);

  return () => {
    handle.then((listener) => listener.remove());
  };
}
