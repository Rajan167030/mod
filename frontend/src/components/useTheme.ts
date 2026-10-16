import { useCallback, useEffect, useState } from 'react';

export type Theme = 'dark' | 'light';
const STORAGE_KEY = 'airops_theme';

const systemTheme = (): Theme =>
  window.matchMedia?.('(prefers-color-scheme: light)').matches ? 'light' : 'dark';

export const readStoredTheme = (): Theme | null => {
  try {
    const v = localStorage.getItem(STORAGE_KEY);
    return v === 'light' || v === 'dark' ? v : null;
  } catch {
    return null;
  }
};

export const useTheme = () => {
  const [theme, setTheme] = useState<Theme>(() => readStoredTheme() ?? systemTheme());

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  const toggle = useCallback(() => {
    setTheme((t) => {
      const next = t === 'dark' ? 'light' : 'dark';
      try {
        localStorage.setItem(STORAGE_KEY, next);
      } catch {
        /* storage unavailable; theme still applies for this session */
      }
      return next;
    });
  }, []);

  return { theme, toggle };
};

/** Current theme for components that cannot use CSS classes (e.g. map tiles). */
export const useActiveTheme = (): Theme => {
  const read = () => (document.documentElement.dataset.theme === 'light' ? 'light' : 'dark') as Theme;
  const [theme, setTheme] = useState<Theme>(read);
  useEffect(() => {
    const obs = new MutationObserver(() => setTheme(read()));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    return () => obs.disconnect();
  }, []);
  return theme;
};
