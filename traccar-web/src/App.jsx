import { Outlet, useNavigate, useLocation } from 'react-router-dom';
import { useDispatch, useSelector } from 'react-redux';
import { useMediaQuery, useTheme } from '@mui/material';
import { alpha } from '@mui/material/styles';
import HomeRoundedIcon from '@mui/icons-material/HomeRounded';
import { makeStyles } from 'tss-react/mui';
import SocketController from './SocketController';
import CachingController from './CachingController';
import { useCatch, useAsyncTask } from './reactHelper';
import { sessionActions } from './store';
import UpdateController from './UpdateController';
import MotionController from './main/MotionController';
import TermsDialog from './common/components/TermsDialog';
import Loader from './common/components/Loader';
import fetchOrThrow from './common/util/fetchOrThrow';
import ErrorBoundary from './ErrorBoundary';

const useStyles = makeStyles()((theme) => {
  const dark = theme.palette.mode === 'dark';
  return {
    page: {
      flexGrow: 1,
      overflow: 'auto',
    },
    menu: {
      zIndex: 4,
      '@media print': {
        display: 'none',
      },
    },
    homeButton: {
      position: 'fixed',
      right: theme.spacing(2),
      // stacked just above the add-FAB (which lives bottom-right on list pages)
      bottom: `calc(${theme.spacing(2)} + 64px)`,
      [theme.breakpoints.down('md')]: {
        bottom: `calc(${theme.dimensions.bottomBarHeight}px + ${theme.spacing(2)} + 64px)`,
      },
      zIndex: 1100,
      width: 48,
      height: 48,
      display: 'inline-flex',
      alignItems: 'center',
      justifyContent: 'center',
      borderRadius: '50%',
      border: `1px solid ${alpha(theme.palette.text.primary, dark ? 0.12 : 0.08)}`,
      backgroundColor: alpha(theme.palette.background.paper, dark ? 0.8 : 0.92),
      backdropFilter: 'blur(14px) saturate(140%)',
      WebkitBackdropFilter: 'blur(14px) saturate(140%)',
      color: theme.palette.text.primary,
      cursor: 'pointer',
      boxShadow: `0 8px 24px ${alpha('#000000', dark ? 0.5 : 0.16)}`,
      transition: 'transform 0.15s ease, box-shadow 0.15s ease, border-color 0.15s ease',
      '&:hover': {
        transform: 'translateY(-1px)',
        boxShadow: `0 12px 30px ${alpha(theme.palette.primary.main, 0.28)}`,
        borderColor: alpha(theme.palette.primary.main, 0.5),
        color: theme.palette.primary.main,
      },
      '@media print': {
        display: 'none',
      },
    },
  };
});

const App = () => {
  const { classes } = useStyles();
  const theme = useTheme();
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const location = useLocation();

  const desktop = useMediaQuery(theme.breakpoints.up('md'));

  const newServer = useSelector((state) => state.session.server.newServer);
  const termsUrl = useSelector((state) => state.session.server.attributes.termsUrl);
  const user = useSelector((state) => state.session.user);

  const acceptTerms = useCatch(async () => {
    const response = await fetchOrThrow(`/api/users/${user.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...user, attributes: { ...user.attributes, termsAccepted: true } }),
    });
    dispatch(sessionActions.updateUser(await response.json()));
  });

  useAsyncTask(
    async ({ signal }) => {
      if (!user) {
        const response = await fetch('/api/session', { signal });
        if (response.ok) {
          dispatch(sessionActions.updateUser(await response.json()));
        } else {
          window.sessionStorage.setItem(
            'postLogin',
            window.location.pathname + window.location.search,
          );
          navigate(newServer ? '/register' : '/login', { replace: true });
        }
      }
      return null;
    },
    [user, dispatch, navigate, newServer],
  );

  if (user == null) {
    return <Loader />;
  }
  if (termsUrl && !user.attributes.termsAccepted) {
    return <TermsDialog open onCancel={() => navigate('/login')} onAccept={() => acceptTerms()} />;
  }
  return (
    <>
      <SocketController />
      <CachingController />
      <UpdateController />
      <MotionController />
      <div className={classes.page}>
        <ErrorBoundary key={location.pathname}>
          <Outlet />
        </ErrorBoundary>
      </div>
      {location.pathname !== '/' && (
        <button
          type="button"
          className={classes.homeButton}
          onClick={() => navigate('/')}
          title="Back to dashboard"
          aria-label="Home"
        >
          <HomeRoundedIcon fontSize="small" />
        </button>
      )}
    </>
  );
};

export default App;
