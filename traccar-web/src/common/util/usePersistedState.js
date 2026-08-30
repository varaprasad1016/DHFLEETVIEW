import { useEffect, useRef, useState } from 'react';

const listeners = new Map();

const broadcast = (key, value) => {
  listeners.get(key)?.forEach((listener) => listener(value));
};

export const savePersistedState = (key, value) => {
  window.localStorage.setItem(key, JSON.stringify(value));
  broadcast(key, value);
};

export default (key, defaultValue) => {
  const defaultRef = useRef(defaultValue);

  const [value, setValue] = useState(() => {
    try {
      const stickyValue = window.localStorage.getItem(key);
      if (!stickyValue) return defaultRef.current;
      const parsed = JSON.parse(stickyValue);
      // Guard against null / corrupted persisted state (e.g. "null")
      if (parsed === null || parsed === undefined) return defaultRef.current;
      return parsed;
    } catch (e) {
      return defaultRef.current;
    }
  });

  useEffect(() => {
    if (!listeners.has(key)) {
      listeners.set(key, new Set());
    }
    listeners.get(key).add(setValue);
    return () => listeners.get(key).delete(setValue);
  }, [key]);

  useEffect(() => {
    if (value !== defaultRef.current) {
      window.localStorage.setItem(key, JSON.stringify(value));
    } else {
      window.localStorage.removeItem(key);
    }
    broadcast(key, value);
  }, [key, value]);

  return [value, setValue];
};
