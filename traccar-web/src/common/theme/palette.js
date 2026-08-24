const validatedColor = (color) => (/^#([0-9A-Fa-f]{3}){1,2}$/.test(color) ? color : null);

export default (server, darkMode) => {
  const mode = darkMode ? 'dark' : 'light';
  const light = mode === 'light';

  return {
    mode,
    background: {
      default: light ? '#f4f6fb' : '#0b0e14',
      paper: light ? '#ffffff' : '#141a24',
    },
    text: {
      primary: light ? '#101828' : '#e6eaf2',
      secondary: light ? '#667085' : '#9aa4b5',
    },
    divider: light ? 'rgba(16, 24, 40, 0.08)' : 'rgba(230, 234, 242, 0.09)',
    primary: {
      main:
        validatedColor(server?.attributes?.colorPrimary) || (light ? '#4f46e5' : '#818cf8'),
      light: light ? '#6366f1' : '#a5b4fc',
      dark: light ? '#4338ca' : '#6366f1',
      contrastText: '#ffffff',
    },
    secondary: {
      main:
        validatedColor(server?.attributes?.colorSecondary) || (light ? '#0d9488' : '#5eead4'),
      light: light ? '#14b8a6' : '#99f6e4',
      dark: light ? '#0f766e' : '#2dd4bf',
      contrastText: '#ffffff',
    },
    success: {
      main: light ? '#16a34a' : '#4ade80',
      light: light ? '#4ade80' : '#86efac',
      dark: light ? '#15803d' : '#22c55e',
      contrastText: '#ffffff',
    },
    warning: {
      main: light ? '#d97706' : '#fbbf24',
      light: light ? '#fbbf24' : '#fcd34d',
      dark: light ? '#b45309' : '#f59e0b',
      contrastText: '#ffffff',
    },
    error: {
      main: light ? '#dc2626' : '#f87171',
      light: light ? '#f87171' : '#fca5a5',
      dark: light ? '#b91c1c' : '#ef4444',
      contrastText: '#ffffff',
    },
    info: {
      main: light ? '#0284c7' : '#38bdf8',
      light: light ? '#38bdf8' : '#7dd3fc',
      dark: light ? '#0369a1' : '#0ea5e9',
      contrastText: '#ffffff',
    },
    neutral: {
      main: light ? '#98a2b3' : '#667085',
    },
    geometry: {
      main: '#3bb2d0',
    },
    alwaysDark: {
      main: '#0f172a',
    },
  };
};
