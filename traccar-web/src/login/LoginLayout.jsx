import { Paper } from '@mui/material';
import { makeStyles } from 'tss-react/mui';
import { alpha, useTheme } from '@mui/material/styles';
import { keyframes } from '@emotion/react';
import LogoImage from './LogoImage';

const drift = keyframes`
  0% { transform: translate(0, 0) scale(1); }
  50% { transform: translate(24px, -18px) scale(1.06); }
  100% { transform: translate(0, 0) scale(1); }
`;

const rise = keyframes`
  from { opacity: 0; transform: translateY(12px); }
  to { opacity: 1; transform: translateY(0); }
`;

const useStyles = makeStyles()((theme) => {
  const dark = theme.palette.mode === 'dark';
  const base = theme.palette.background.default;
  return {
    root: {
      position: 'relative',
      display: 'flex',
      height: '100%',
      alignItems: 'center',
      justifyContent: 'center',
      overflow: 'hidden',
      backgroundColor: base,
      // layered command-center backdrop: deep vignette + faint grid
      backgroundImage: [
        `radial-gradient(1200px 600px at 50% -10%, ${alpha(theme.palette.primary.main, dark ? 0.16 : 0.10)}, transparent 60%)`,
        `radial-gradient(900px 500px at 100% 110%, ${alpha(theme.palette.secondary.main, dark ? 0.12 : 0.08)}, transparent 60%)`,
        `linear-gradient(${alpha(theme.palette.text.primary, dark ? 0.035 : 0.02)} 1px, transparent 1px)`,
        `linear-gradient(90deg, ${alpha(theme.palette.text.primary, dark ? 0.035 : 0.02)} 1px, transparent 1px)`,
        `radial-gradient(120% 120% at 50% 40%, transparent 55%, ${alpha('#000000', dark ? 0.45 : 0.06)} 100%)`,
      ].join(','),
      backgroundSize: 'auto, auto, 44px 44px, 44px 44px, auto',
    },
    blob: {
      position: 'absolute',
      borderRadius: '50%',
      filter: 'blur(70px)',
      pointerEvents: 'none',
      willChange: 'transform',
    },
    blobPrimary: {
      width: 520,
      height: 520,
      top: -180,
      left: -140,
      background: `radial-gradient(circle at 35% 35%, ${alpha(theme.palette.primary.main, dark ? 0.42 : 0.22)}, transparent 70%)`,
      animation: `${drift} 20s ease-in-out infinite`,
    },
    blobSecondary: {
      width: 460,
      height: 460,
      bottom: -160,
      right: -120,
      background: `radial-gradient(circle at 65% 65%, ${alpha(theme.palette.info.main, dark ? 0.36 : 0.18)}, transparent 70%)`,
      animation: `${drift} 26s ease-in-out infinite reverse`,
    },
    blobAccent: {
      width: 380,
      height: 380,
      top: '28%',
      left: '58%',
      background: `radial-gradient(circle at 50% 50%, ${alpha(theme.palette.secondary.main, dark ? 0.24 : 0.12)}, transparent 70%)`,
      animation: `${drift} 32s ease-in-out infinite`,
    },
    card: {
      position: 'relative',
      width: '100%',
      maxWidth: 428,
      margin: theme.spacing(3),
      padding: theme.spacing(5, 5, 4.5),
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      borderRadius: 24,
      // glass panel with a lit rim + depth
      backgroundColor: alpha(theme.palette.background.paper, dark ? 0.72 : 0.86),
      backdropFilter: 'blur(22px) saturate(140%)',
      WebkitBackdropFilter: 'blur(22px) saturate(140%)',
      border: `1px solid ${alpha(theme.palette.text.primary, dark ? 0.10 : 0.06)}`,
      boxShadow: [
        `0 1px 0 ${alpha('#ffffff', dark ? 0.06 : 0.6)} inset`,
        `0 28px 70px ${alpha('#000000', dark ? 0.55 : 0.14)}`,
        `0 0 90px ${alpha(theme.palette.primary.main, dark ? 0.18 : 0.10)}`,
      ].join(','),
      animation: `${rise} 0.5s ease both`,
      '&::before': {
        // top hairline highlight
        content: '""',
        position: 'absolute',
        insetInline: 24,
        top: 0,
        height: 1,
        background: `linear-gradient(90deg, transparent, ${alpha(theme.palette.primary.light, 0.7)}, transparent)`,
      },
    },
    brand: {
      display: 'flex',
      flexDirection: 'column',
      alignItems: 'center',
      marginBottom: theme.spacing(3),
    },
    tagline: {
      marginTop: theme.spacing(1),
      fontSize: '0.68rem',
      fontWeight: 700,
      letterSpacing: '0.22em',
      textTransform: 'uppercase',
      color: theme.palette.text.secondary,
    },
    status: {
      display: 'inline-flex',
      alignItems: 'center',
      gap: 6,
      marginTop: theme.spacing(1.5),
      fontSize: '0.7rem',
      color: theme.palette.text.secondary,
    },
    dot: {
      width: 7,
      height: 7,
      borderRadius: '50%',
      backgroundColor: theme.palette.success.main,
      boxShadow: `0 0 0 3px ${alpha(theme.palette.success.main, 0.18)}`,
    },
    form: {
      width: '100%',
      display: 'flex',
      flexDirection: 'column',
      gap: theme.spacing(2),
    },
  };
});

const LoginLayout = ({ children }) => {
  const { classes } = useStyles();
  const theme = useTheme();

  return (
    <main className={classes.root}>
      <div className={`${classes.blob} ${classes.blobPrimary}`} />
      <div className={`${classes.blob} ${classes.blobSecondary}`} />
      <div className={`${classes.blob} ${classes.blobAccent}`} />
      <Paper className={classes.card} elevation={0}>
        <div className={classes.brand}>
          <LogoImage color={theme.palette.primary.main} />
          <span className={classes.tagline}>Fleet Command Center</span>
          <span className={classes.status}>
            <span className={classes.dot} />
            Secure connection
          </span>
        </div>
        <form className={classes.form} noValidate>
          {children}
        </form>
      </Paper>
    </main>
  );
};

export default LoginLayout;
