import { useCallback, useSyncExternalStore } from 'react';
import { TASK_STATUS, backgroundTasks } from './backgroundTasks';

export function useBackgroundTask(taskKey, store = backgroundTasks) {
  const task = useSyncExternalStore(store.subscribe, () => store.get(taskKey));

  const run = useCallback((work, options) => store.run(taskKey, work, options), [store, taskKey]);
  const reset = useCallback(() => store.reset(taskKey), [store, taskKey]);

  return {
    ...task,
    isGenerating: task.status === TASK_STATUS.GENERATING,
    isReady: task.status === TASK_STATUS.READY,
    isFailed: task.status === TASK_STATUS.FAILED,
    run,
    reset,
  };
}
