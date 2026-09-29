import { useEffect, useState } from 'react';

const POLL_INTERVAL_MS = 5000;
const IN_PROGRESS_STATUSES = new Set(['PENDING', 'PROCESSING']);

export function isExtractionInProgress(material) {
  return IN_PROGRESS_STATUSES.has(material?.extractionStatus);
}

export function isExtractionFailed(material) {
  return material?.extractionStatus === 'FAILED';
}

export function useExtractionPolling(material, refreshMaterial) {
  const [pollError, setPollError] = useState(null);
  const isInProgress = isExtractionInProgress(material);

  useEffect(() => {
    if (!isInProgress) return undefined;

    const timer = window.setInterval(() => {
      refreshMaterial()
        .then(() => setPollError(null))
        .catch((error) => setPollError(error));
    }, POLL_INTERVAL_MS);

    return () => window.clearInterval(timer);
  }, [isInProgress, refreshMaterial]);

  return pollError;
}
