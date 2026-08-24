import { useMemo } from 'react';
import { createTheme } from '@mui/material/styles';
import palette from './palette';
import dimensions from './dimensions';
import components from './components';

const softShadow = (index) => {
  const y = Math.min(index * 0.5, 16);
  const blur = 2 + index * 1.4;
  const alpha = 0.03 + index * 0.0045;
  return `0px ${y}px ${blur}px rgba(16, 24, 40, ${Math.min(alpha, 0.28).toFixed(3)})`;
};

const shadows = Array.from({ length: 25 }, (_, index) =>
  index === 0 ? 'none' : softShadow(index),
);

export default (server, darkMode, direction) =>
  useMemo(
    () =>
      createTheme({
        shape: {
          borderRadius: 10,
        },
        typography: {
          fontFamily:
            "'Inter Variable', 'Inter', Roboto, 'Segoe UI', 'Helvetica Neue', Arial, sans-serif",
          h4: {
            fontWeight: 700,
            letterSpacing: '-0.02em',
          },
          h5: {
            fontWeight: 700,
            letterSpacing: '-0.02em',
          },
          h6: {
            fontWeight: 650,
            letterSpacing: '-0.01em',
          },
          subtitle1: {
            fontWeight: 600,
          },
          subtitle2: {
            fontWeight: 600,
          },
          button: {
            fontWeight: 600,
          },
        },
        palette: palette(server, darkMode),
        direction,
        dimensions,
        components,
        shadows,
      }),
    [server, darkMode, direction],
  );
