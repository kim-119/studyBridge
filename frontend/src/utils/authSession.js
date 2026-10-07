// Network cancellation (including closing another tab) does not invalidate credentials.
export const isRejectedSession = error => [401, 403].includes(error?.response?.status);
