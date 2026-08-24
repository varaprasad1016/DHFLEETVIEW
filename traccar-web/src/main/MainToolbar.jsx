import { useSelector } from 'react-redux';
import { makeStyles } from 'tss-react/mui';
import { alpha } from '@mui/material/styles';
import {
  AppBar,
  Toolbar,
  IconButton,
  Typography,
  Badge,
  Tooltip,
} from '@mui/material';
import MenuIcon from '@mui/icons-material/Menu';
import NotificationsNoneIcon from '@mui/icons-material/NotificationsNone';
import { useTranslation } from '../common/components/LocalizationProvider';

const useStyles = makeStyles()((theme) => ({
  appBar: {
    position: 'fixed',
    top: 0,
    left: 0,
    right: 0,
    zIndex: 1200,
    backgroundColor: theme.palette.background.paper,
    borderBottom: `1px solid ${theme.palette.divider}`,
    boxShadow: 'none',
    height: 56,
    display: 'flex',
    justifyContent: 'center',
  },
  toolbar: {
    width: '100%',
    maxWidth: '100%',
    minHeight: 56,
    padding: theme.spacing(0, 2),
  },
  brand: {
    display: 'flex',
    alignItems: 'center',
    gap: theme.spacing(1),
    flex: 1,
    minWidth: 0,
  },
  brandIcon: {
    width: 32,
    height: 32,
    borderRadius: 8,
    background: 'linear-gradient(135deg, #4f46e5, #7c3aed)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },
  brandPin: {
    width: 16,
    height: 16,
    filter: 'brightness(0) invert(1)',
  },
  brandText: {
    fontWeight: 700,
    fontSize: '1.05rem',
    letterSpacing: '-0.02em',
    color: theme.palette.text.primary,
    lineHeight: 1.1,
  },
  brandSub: {
    fontSize: '0.65rem',
    fontWeight: 500,
    color: theme.palette.text.secondary,
    letterSpacing: '0.02em',
  },
  hamburger: {
    color: theme.palette.text.secondary,
    marginRight: theme.spacing(0.5),
    '&:hover': {
      backgroundColor: alpha(theme.palette.primary.main, 0.08),
      color: theme.palette.primary.main,
    },
  },
  iconBtn: {
    color: theme.palette.text.secondary,
    '&:hover': {
      backgroundColor: alpha(theme.palette.text.primary, 0.06),
      color: theme.palette.text.primary,
    },
  },
}));

const MainToolbar = ({ sidebarOpen, onToggleSidebar }) => {
  const { classes } = useStyles();
  const t = useTranslation();
  const socket = useSelector((state) => state.session.socket);
  const events = useSelector((state) => state.events.items);

  return (
    <AppBar elevation={0} className={classes.appBar}>
      <Toolbar className={classes.toolbar}>
        <IconButton
          edge="start"
          className={classes.hamburger}
          onClick={onToggleSidebar}
          size="medium"
        >
          <MenuIcon />
        </IconButton>
        <div className={classes.brand}>
          <div className={classes.brandIcon}>
            <svg className={classes.brandPin} viewBox="0 0 24 24" fill="currentColor">
              <path d="M12 2C8.13 2 5 5.13 5 9c0 5.25 7 13 7 13s7-7.75 7-13c0-3.87-3.13-7-7-7zm0 9.5c-1.38 0-2.5-1.12-2.5-2.5s1.12-2.5 2.5-2.5 2.5 1.12 2.5 2.5-1.12 2.5-2.5 2.5z"/>
            </svg>
          </div>
          <div>
            <Typography className={classes.brandText}>DH FleetView</Typography>
            <Typography className={classes.brandSub}>Tracking &amp; Live View</Typography>
          </div>
        </div>
        <Tooltip title={t('reportEvents')}>
          <IconButton className={classes.iconBtn} size="medium">
            <Badge color="error" variant="dot" invisible={events.length === 0}>
              <NotificationsNoneIcon />
            </Badge>
          </IconButton>
        </Tooltip>
      </Toolbar>
    </AppBar>
  );
};

export default MainToolbar;
