import { Network } from '@capacitor/network';

export async function getNetworkStatus() {
  return Network.getStatus();
}

export function onNetworkStatusChange(listener) {
  const handle = Network.addListener('networkStatusChange', listener);

  return () => {
    handle.then((registered) => registered.remove());
  };
}
