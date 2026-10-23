export const TASK_STATUS = {
  IDLE: 'idle',
  GENERATING: 'generating',
  READY: 'ready',
  FAILED: 'failed',
};

const IDLE_TASK = Object.freeze({
  status: TASK_STATUS.IDLE,
  result: null,
  error: null,
  startedAt: null,
  context: null,
});

export function createBackgroundTaskStore() {
  const tasks = new Map();
  const listeners = new Set();

  const notify = () => listeners.forEach((listener) => listener());

  const save = (key, task) => {
    tasks.set(key, Object.freeze(task));
    notify();
  };

  const get = (key) => tasks.get(key) || IDLE_TASK;

  const isGenerating = (key) => get(key).status === TASK_STATUS.GENERATING;

  const run = (key, work, { now = Date.now(), context = null } = {}) => {
    const current = tasks.get(key);
    if (current?.status === TASK_STATUS.GENERATING) return current.promise;

    const settle = (fields) => save(key, { result: null, error: null, startedAt: now, context, ...fields });

    const promise = Promise.resolve()
      .then(work)
      .then(
        (result) => {
          settle({ status: TASK_STATUS.READY, result });
          return result;
        },
        (error) => {
          settle({ status: TASK_STATUS.FAILED, error });
          throw error;
        }
      );

    settle({ status: TASK_STATUS.GENERATING, promise });
    return promise;
  };

  const reset = (key) => {
    if (!tasks.has(key) || isGenerating(key)) return;
    tasks.delete(key);
    notify();
  };

  const subscribe = (listener) => {
    listeners.add(listener);
    return () => listeners.delete(listener);
  };

  return { get, isGenerating, run, reset, subscribe };
}

export const backgroundTasks = createBackgroundTaskStore();
