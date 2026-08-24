import { Paper } from '@mui/material';
import { makeStyles } from 'tss-react/mui';
import { alpha, useTheme } from '@mui/material/styles';
import LogoImage from './LogoImage';

const useStyles = makeStyles()((theme) => ({
  root: {
    position: 'relative',
    display: 'flex',
    height: '100%',
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
    backgroundColor: theme.palette.background.default,
  },
  blob: {
    position: 'absolute',
    borderRadius: '50%',
    filter: 'blur(60px)',
    pointerEvents: 'none',
  },
  blobPrimary: {
    width: 480,
    height: 480,
    top: -160,
    left: -120,
    background: `radial-gradient(circle at 35% 35%, ${alpha(theme.palette.primary.main, 0.2)}, transparent 70%)`,
  },
  blobSecondary: {
    width: 420,
    height: 420,
    bottom: -140,
    right: -100,
    background: `radial-gradient(circle at 65% 65%, ${alpha(theme.palette.secondary.main, 0.18)}, transparent 70%)`,
  },
  blobAccent: {
    width: 360,
    height: 360,
    top: '30%',
    left: '55%',
    background: `radial-gradient(circle at 50% 50%, ${alpha(theme.palette.primary.light, 0.12)}, transparent 70%)`,
  },
  card: {
    position: 'relative',
    width: '100%',
    maxWidth: 440,
    margin: theme.spacing(3),
    padding: theme.spacing(5, 5, 4),
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    borderRadius: 20,
    backgroundColor: theme.palette.background.paper,
    boxShadow: '0 24px 60px rgba(16, 24, 40, 0.12), 0 2px 8px rgba(16, 24, 40, 0.06)',
    border: `1px solid ${theme.palette.divider}`,
  },
  logo: {
    marginBottom: theme.spacing(3),
  },
  form: {
    width: '100%',
    display: 'flex',
    flexDirection: 'column',
    gap: theme.spacing(2),
  },
}));

const LoginLayout = ({ children }) => {
  const { classes } = useStyles();
  const theme = useTheme();

  return (
    <main className={classes.root}>
      <div className={`${classes.blob} ${classes.blobPrimary}`} />
      <div className={`${classes.blob} ${classes.blobSecondary}`} />
      <div className={`${classes.blob} ${classes.blobAccent}`} />
      <Paper className={classes.card} elevation={0}>
        <div className={classes.logo}>
          <LogoImage color={theme.palette.primary.main} />
        </div>
        <form className={classes.form} noValidate>
          {children}
        </form>
      </Paper>
    </main>
  );
};

export default LoginLayout;
