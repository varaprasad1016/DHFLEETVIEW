import { createContext, use, useCallback, useEffect, useMemo, useState } from 'react';
import { useSelector } from 'react-redux';
import { ThemeProvider, useMediaQuery } from '@mui/material';
import { CacheProvider } from '@emotion/react';
import createCache from '@emotion/cache';
import { prefixer } from 'stylis';
import rtlPlugin from 'stylis-plugin-rtl';
import theme from './common/theme';
import { useLocalization } from './common/components/LocalizationProvider';

const cache = {
  ltr: createCache({
    key: 'muiltr',
    stylisPlugins: [prefixer],
  }),
  rtl: createCache({
    key: 'muirtl',
    stylisPlugins: [prefixer, rtlPlugin],
  }),
};

// Shared with the /tacho compliance pages (same origin), so switching the theme
// in either place switches both.
const THEME_KEY = 'dhfv-theme';

const readStoredTheme = () => {
  try {
    const value = window.localStorage.getItem(THEME_KEY);
    return value === 'dark' || value === 'light' ? value : null;
  } catch {
    return null;
  }
};

const ThemeModeContext = createContext({ darkMode: false, toggleDarkMode: () => {} });

export const useThemeMode = () => use(ThemeModeContext);

const AppThemeProvider = ({ children }) => {
  const server = useSelector((state) => state.session.server);
  const { direction } = useLocalization();

  const [storedTheme, setStoredTheme] = useState(readStoredTheme);
  const serverDarkMode = server?.attributes?.darkMode;
  const preferDarkMode = useMediaQuery('(prefers-color-scheme: dark)');
  // The user's own choice wins, then the server default, then the device setting.
  let darkMode = serverDarkMode !== undefined ? serverDarkMode : preferDarkMode;
  if (storedTheme) {
    darkMode = storedTheme === 'dark';
  }

  useEffect(() => {
    const onStorage = (event) => {
      if (event.key === THEME_KEY) {
        setStoredTheme(readStoredTheme());
      }
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', darkMode ? 'dark' : 'light');
    document.documentElement.style.colorScheme = darkMode ? 'dark' : 'light';
  }, [darkMode]);

  const toggleDarkMode = useCallback(() => {
    const next = darkMode ? 'light' : 'dark';
    try {
      window.localStorage.setItem(THEME_KEY, next);
    } catch {
      // storage unavailable (private mode): still switch for this session
    }
    setStoredTheme(next);
  }, [darkMode]);

  const themeMode = useMemo(() => ({ darkMode, toggleDarkMode }), [darkMode, toggleDarkMode]);
  const themeInstance = theme(server, darkMode, direction);

  return (
    <CacheProvider value={cache[direction]}>
      <ThemeModeContext value={themeMode}>
        <ThemeProvider theme={themeInstance}>{children}</ThemeProvider>
      </ThemeModeContext>
    </CacheProvider>
  );
};

export default AppThemeProvider;
