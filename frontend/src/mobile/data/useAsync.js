import { useCallback, useEffect, useRef, useState } from 'react';

const STATUS = {
  IDLE: 'idle',
  LOADING: 'loading',
  SUCCESS: 'success',
  ERROR: 'error',
};

export function describeApiError(error, overrides = {}) {
  if (!error) return '알 수 없는 오류가 발생했습니다.';

  const status = error.status || error.response?.status;

  if (overrides[status]) return overrides[status];

  if (error.networkError || (!error.response && error.message === 'Network Error')) {
    return '서버에 연결할 수 없습니다. 네트워크 상태를 확인해주세요.';
  }

  if (error.code === 'ECONNABORTED') {
    return '요청 시간이 초과되었습니다. 다시 시도해주세요.';
  }

  if (status === 401) return '로그인이 만료되었습니다. 다시 로그인해주세요.';
  if (status === 403) return '접근 권한이 없습니다.';
  if (status === 404) return '요청한 정보를 찾을 수 없습니다.';
  if (status === 409) return '이미 처리된 요청입니다.';
  if (status >= 500) return '서버에서 오류가 발생했습니다. 잠시 후 다시 시도해주세요.';

  return (
    error.response?.data?.message ||
    error.message ||
    '요청을 처리하지 못했습니다.'
  );
}

export function useAsync(loader, deps = [], { immediate = true } = {}) {
  const [status, setStatus] = useState(immediate ? STATUS.LOADING : STATUS.IDLE);
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const requestId = useRef(0);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const run = useCallback(async () => {
    const current = ++requestId.current;
    setStatus(STATUS.LOADING);
    setError(null);

    try {
      const result = await loader();
      if (!mounted.current || current !== requestId.current) return result;
      setData(result);
      setStatus(STATUS.SUCCESS);
      return result;
    } catch (caught) {
      if (!mounted.current || current !== requestId.current) throw caught;
      setError(caught);
      setStatus(STATUS.ERROR);
      throw caught;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  useEffect(() => {
    if (!immediate) return;
    run().catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run, immediate]);

  return {
    data,
    error,
    errorMessage: error ? describeApiError(error) : null,
    isLoading: status === STATUS.LOADING,
    isError: status === STATUS.ERROR,
    isSuccess: status === STATUS.SUCCESS,
    reload: run,
    setData,
  };
}

export function useSubmit(action, { errorMessages = {} } = {}) {
  const [isSubmitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const inFlight = useRef(false);

  const submit = useCallback(
    async (...args) => {
      if (inFlight.current) return undefined;

      inFlight.current = true;
      setSubmitting(true);
      setError(null);

      try {
        return await action(...args);
      } catch (caught) {
        setError(caught);
        throw caught;
      } finally {
        inFlight.current = false;
        setSubmitting(false);
      }
    },
    [action]
  );

  return {
    submit,
    isSubmitting,
    error,
    errorMessage: error ? describeApiError(error, errorMessages) : null,
    clearError: () => setError(null),
  };
}
