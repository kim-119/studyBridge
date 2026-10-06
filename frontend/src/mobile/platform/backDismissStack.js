const dismissHandlers = [];

export function pushBackDismiss(onDismiss) {
  const entry = { onDismiss };
  dismissHandlers.push(entry);

  return () => {
    const index = dismissHandlers.indexOf(entry);
    if (index >= 0) dismissHandlers.splice(index, 1);
  };
}

export function dismissTopLayer() {
  const top = dismissHandlers[dismissHandlers.length - 1];
  if (!top) return false;

  top.onDismiss();
  return true;
}

export function pendingDismissCount() {
  return dismissHandlers.length;
}
