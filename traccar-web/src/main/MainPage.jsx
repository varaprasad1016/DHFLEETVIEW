import { lazy, Suspense, useState, useCallback, useEffect } from 'react';
import { makeStyles } from 'tss-react/mui';
import { alpha, useTheme } from '@mui/material/styles';
import useMediaQuery from '@mui/material/useMediaQuery';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate, useLocation } from 'react-router-dom';
import MapIcon from '@mui/icons-material/Map';
import DescriptionIcon from '@mui/icons-material/Description';
import SettingsIcon from '@mui/icons-material/Settings';
import PersonIcon from '@mui/icons-material/Person';
import LogoutIcon from '@mui/icons-material/Logout';
import Badge from '@mui/material/Badge';
import Divider from '@mui/material/Divider';
import Typography from '@mui/material/Typography';
import Box from '@mui/material/Box';
import DeviceList from './DeviceList';
import StatusCard from '../common/components/StatusCard';
import FleetDashboard from './FleetDashboard';
import { devicesActions, sessionActions } from '../store';
import { nativePostMessage } from '../common/components/NativeInterface';
import usePersistedState from '../common/util/usePersistedState';
import EventsDrawer from './EventsDrawer';
import useFilter from './useFilter';
import MainToolbar from './MainToolbar';
import { useAttributePreference } from '../common/util/preferences';
import { useTranslation } from '../common/components/LocalizationProvider';
import { useRestriction } from '../common/util/permissions';

const MainMap = lazy(() => import('./MainMap'));

const SIDEBAR_WIDTH = 380;

const useStyles = makeStyles()((theme) => ({
  root: {
    height: '100%',
    width: '100%',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  },
  body: {
    flex: 1,
    display: 'flex',
    minHeight: 0,
    position: 'relative',
  },
  sidebar: {
    width: SIDEBAR_WIDTH,
    height: '100%',
    display: 'flex',
    flexDirection: 'column',
    flexShrink: 0,
    borderRight: `1px solid ${theme.palette.divider}`,
    backgroundColor: theme.palette.background.default,
    overflow: 'hidden',
    transition: 'width 0.25s ease, min-width 0.25s ease',
  },
  sidebarClosed: {
    width: 0,
    minWidth: 0,
    borderRight: 'none',
  },
  sidebarInner: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    width: SIDEBAR_WIDTH,
    minWidth: SIDEBAR_WIDTH,
    overflow: 'hidden',
  },
  mapArea: {
    flex: 1,
    position: 'relative',
    minWidth: 0,
  },
  sectionTitle: {
    fontWeight: 600,
    fontSize: '0.7rem',
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    color: theme.palette.text.secondary,
    padding: theme.spacing(1, 2, 0.5),
    flexShrink: 0,
  },
  navSection: {
    flexShrink: 0,
    borderTop: `1px solid ${theme.palette.divider}`,
    padding: theme.spacing(0.5, 0),
  },
  navItem: {
    display: 'flex',
    alignItems: 'center',
    gap: theme.spacing(1.5),
    padding: theme.spacing(1, 2),
    cursor: 'pointer',
    color: theme.palette.text.secondary,
    fontSize: '0.875rem',
    fontWeight: 500,
    transition: 'background 0.15s, color 0.15s',
    border: 'none',
    background: 'none',
    width: '100%',
    textAlign: 'left',
    '&:hover': {
      backgroundColor: alpha(theme.palette.primary.main, 0.06),
      color: theme.palette.text.primary,
    },
  },
  navItemActive: {
    backgroundColor: alpha(theme.palette.primary.main, 0.08),
    color: theme.palette.primary.main,
    fontWeight: 600,
  },
  navItemDanger: {
    color: theme.palette.error.main,
    '&:hover': {
      backgroundColor: alpha(theme.palette.error.main, 0.06),
    },
  },
}));

const MainPage = () => {
  const { classes } = useStyles();
  const dispatch = useDispatch();
  const theme = useTheme();
  const navigate = useNavigate();
  const location = useLocation();
  const t = useTranslation();

  const desktop = useMediaQuery(theme.breakpoints.up('md'));

  const readonly = useRestriction('readonly');
  const disableReports = useRestriction('disableReports');

  const mapOnSelect = useAttributePreference('mapOnSelect', true);

  const selectedDeviceId = useSelector((state) => state.devices.selectedId);
  const positions = useSelector((state) => state.session.positions);
  const user = useSelector((state) => state.session.user);
  const devices = useSelector((state) => state.devices.items);
  const [filteredPositions, setFilteredPositions] = useState([]);
  const selectedPosition = filteredPositions.find(
    (position) => selectedDeviceId && position.deviceId === selectedDeviceId,
  );

  const [filteredDevices, setFilteredDevices] = useState([]);

  const [keyword, setKeyword] = useState('');
  const [filter, setFilter] = usePersistedState('deviceFilter', {
    statuses: [],
    groups: [],
    geofences: [],
  });
  const [filterSort, setFilterSort] = usePersistedState('filterSort', '');
  const [filterMap, setFilterMap] = usePersistedState('filterMap', false);

  const [devicesOpen, setDevicesOpen] = useState(desktop);
  const [eventsOpen, setEventsOpen] = useState(false);

  const onEventsClick = useCallback(() => setEventsOpen(true), [setEventsClick]);

  useEffect(() => {
    if (!desktop && mapOnSelect && selectedDeviceId) {
      setDevicesOpen(false);
    }
  }, [desktop, mapOnSelect, selectedDeviceId]);

  useFilter(
    keyword,
    filter,
    filterSort,
    filterMap,
    positions,
    setFilteredDevices,
    setFilteredPositions,
  );

  const currentNav = () => {
    if (location.pathname === '/') return 'map';
    if (location.pathname.startsWith('/reports')) return 'reports';
    if (location.pathname.startsWith('/settings/user/')) return 'account';
    if (location.pathname.startsWith('/settings')) return 'settings';
    return null;
  };

  const handleNav = (value) => {
    switch (value) {
      case 'map':
        navigate('/');
        break;
      case 'reports': {
        let id = selectedDeviceId;
        if (id == null) {
          const deviceIds = Object.keys(devices);
          if (deviceIds.length === 1) id = deviceIds[0];
        }
        navigate(id != null ? `/reports/combined?deviceId=${id}` : '/reports/combined');
        break;
      }
      case 'settings':
        navigate('/settings/preferences?menu=true');
        break;
      case 'account':
        navigate(`/settings/user/${user.id}`);
        break;
      case 'logout':
        handleLogout();
        break;
      default:
        break;
    }
  };

  const handleLogout = async () => {
    const notificationToken = window.localStorage.getItem('notificationToken');
    if (notificationToken && !user.readonly) {
      window.localStorage.removeItem('notificationToken');
      const tokens = user.attributes.notificationTokens?.split(',') || [];
      if (tokens.includes(notificationToken)) {
        const updatedUser = {
          ...user,
          attributes: {
            ...user.attributes,
            notificationTokens:
              tokens.length > 1
                ? tokens.filter((it) => it !== notificationToken).join(',')
                : undefined,
          },
        };
        await fetch(`/api/users/${user.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(updatedUser),
        });
      }
    }
    await fetch('/api/session', { method: 'DELETE' });
    nativePostMessage('logout');
    navigate('/login');
    dispatch(sessionActions.updateUser(null));
  };

  const nav = currentNav();

  const navItems = [
    { key: 'map', label: t('mapTitle'), icon: <MapIcon fontSize="small" /> },
    !disableReports && { key: 'reports', label: t('reportTitle'), icon: <DescriptionIcon fontSize="small" /> },
    !readonly && { key: 'settings', label: t('settingsTitle'), icon: <SettingsIcon fontSize="small" /> },
    !readonly && { key: 'account', label: t('settingsUser'), icon: <PersonIcon fontSize="small" /> },
  ].filter(Boolean);

  return (
    <div className={classes.root}>
      <MainToolbar
        filteredDevices={filteredDevices}
        devicesOpen={devicesOpen}
        setDevicesOpen={setDevicesOpen}
        keyword={keyword}
        setKeyword={setKeyword}
        filter={filter}
        setFilter={setFilter}
        filterSort={filterSort}
        setFilterSort={setFilterSort}
        filterMap={filterMap}
        setFilterMap={setFilterMap}
      />
      <div className={classes.body}>
        {/* Sidebar */}
        <div className={`${classes.sidebar} ${devicesOpen ? '' : classes.sidebarClosed}`}>
          <div className={classes.sidebarInner}>
            {/* Fleet Dashboard */}
            <FleetDashboard />

            <Divider />

            {/* Vehicle List */}
            <div className={classes.sectionTitle}>
              Vehicles ({filteredDevices.length})
            </div>
            <div style={{ flex: 1, minHeight: 0 }}>
              <DeviceList devices={filteredDevices} />
            </div>

            {/* Navigation */}
            <div className={classes.navSection}>
              {navItems.map((item) => (
                <button
                  key={item.key}
                  className={`${classes.navItem} ${nav === item.key ? classes.navItemActive : ''}`}
                  onClick={() => handleNav(item.key)}
                >
                  {item.icon}
                  {item.label}
                </button>
              ))}
              <button
                className={`${classes.navItem} ${classes.navItemDanger}`}
                onClick={handleLogout}
              >
                <LogoutIcon fontSize="small" />
                {t('loginLogout')}
              </button>
            </div>
          </div>
        </div>

        {/* Map */}
        <div className={classes.mapArea}>
          <Suspense fallback={null}>
            <MainMap
              filteredPositions={filteredPositions}
              selectedPosition={selectedPosition}
              onEventsClick={onEventsClick}
            />
          </Suspense>
        </div>
      </div>
      <EventsDrawer open={eventsOpen} onClose={() => setEventsOpen(false)} />
      {selectedDeviceId && (
        <StatusCard
          deviceId={selectedDeviceId}
          position={selectedPosition}
          onClose={() => dispatch(devicesActions.selectId(null))}
          desktopPadding={devicesOpen ? SIDEBAR_WIDTH : 0}
        />
      )}
    </div>
  );
};

export default MainPage;
