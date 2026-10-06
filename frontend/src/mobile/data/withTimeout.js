export class TimeoutError extends Error {
  constructor(milliseconds) {
    super(`request timed out after ${milliseconds}ms`);
    this.name = 'TimeoutError';
    this.code = 'ECONNABORTED';
    this.timeout = milliseconds;
  }
}

export function withTimeout(promise, milliseconds) {
  let timer;

  const timeout = new Promise((_resolve, reject) => {
    timer = setTimeout(() => reject(new TimeoutError(milliseconds)), milliseconds);
  });

  return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
}
