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
import Chip from '@mui/material/Chip';
import Stack from '@mui/material/Stack';
import ViewListIcon from '@mui/icons-material/ViewList';
import MapIconMui from '@mui/icons-material/Map';
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
    width: `min(${SIDEBAR_WIDTH}px, 100vw)`,
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
    width: `min(${SIDEBAR_WIDTH}px, 100vw)`,
    minWidth: `min(${SIDEBAR_WIDTH}px, 100vw)`,
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
  filterChips: {
    display: 'flex',
    gap: theme.spacing(0.75),
    padding: theme.spacing(1, 1.5),
    overflowX: 'auto',
    flexShrink: 0,
    scrollbarWidth: 'none',
    '&::-webkit-scrollbar': { display: 'none' },
  },
  viewToggle: {
    display: 'flex',
    gap: theme.spacing(0.5),
    padding: theme.spacing(0.75, 1.5),
    borderBottom: `1px solid ${theme.palette.divider}`,
    flexShrink: 0,
  },
  viewToggleButton: {
    flex: 1,
    textTransform: 'none',
    fontWeight: 600,
    fontSize: '0.8rem',
    borderRadius: 10,
    padding: theme.spacing(0.6, 1),
    border: `1px solid ${theme.palette.divider}`,
    background: 'none',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: theme.spacing(0.75),
    color: theme.palette.text.secondary,
    transition: 'all 0.15s',
  },
  viewToggleActive: {
    backgroundColor: theme.palette.primary.main,
    color: theme.palette.common.white,
    borderColor: theme.palette.primary.main,
  },
  fleetContainer: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    minHeight: 0,
    overflow: 'hidden',
  },
  mapHiddenMobile: {
    display: 'none',
    [theme.breakpoints.up('md')]: {
      display: 'block',
    },
  },
  sidebarMobileHidden: {
    [theme.breakpoints.down('md')]: {
      display: 'none',
    },
  },
  navSection: {
    flexShrink: 0,
    borderTop: `1px solid ${theme.palette.divider}`,
    padding: theme.spacing(0.5, 0),
  },
  navSectionCompact: {
    flexShrink: 0,
    borderTop: `1px solid ${theme.palette.divider}`,
    display: 'flex',
    flexDirection: 'row',
    justifyContent: 'space-around',
    flexWrap: 'wrap',
    gap: theme.spacing(0.5),
    padding: theme.spacing(0.5),
  },
  navItemCompact: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: 44,
    height: 40,
    borderRadius: 10,
    cursor: 'pointer',
    color: theme.palette.text.secondary,
    border: 'none',
    background: 'none',
    '&:hover': {
      backgroundColor: alpha(theme.palette.primary.main, 0.06),
      color: theme.palette.text.primary,
    },
  },
  navItemCompactActive: {
    backgroundColor: alpha(theme.palette.primary.main, 0.08),
    color: theme.palette.primary.main,
  },
  navItemCompactDanger: {
    color: theme.palette.error.main,
    '&:hover': {
      backgroundColor: alpha(theme.palette.error.main, 0.06),
    },
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
  const compactNav = useMediaQuery(theme.breakpoints.down('sm'))
    || useMediaQuery('(max-height: 600px)');

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
    vehicleStatuses: [],
    groups: [],
    geofences: [],
  });
  const [filterSort, setFilterSort] = usePersistedState('filterSort', '');
  const [filterMap, setFilterMap] = usePersistedState('filterMap', false);

  // Migrate old persisted filter without vehicleStatuses
  useEffect(() => {
    if (filter && !Array.isArray(filter.vehicleStatuses)) {
      setFilter({ ...filter, vehicleStatuses: [] });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const [devicesOpen, setDevicesOpen] = useState(desktop);
  const [eventsOpen, setEventsOpen] = useState(false);
  const isMobile = useMediaQuery(theme.breakpoints.down('md'));
  const [fleetView, setFleetView] = usePersistedState('fleetView', isMobile ? 'list' : 'split');

  const onEventsClick = useCallback(() => setEventsOpen(true), [setEventsOpen]);

  useEffect(() => {
    if (!desktop && mapOnSelect && selectedDeviceId && fleetView !== 'list') {
      setDevicesOpen(false);
    }
  }, [desktop, mapOnSelect, selectedDeviceId, fleetView]);

  // APK/iOS default: show fleet LIST on login, not map. On mobile initial load, enforce list view.
  useEffect(() => {
    if (isMobile && fleetView === 'split' && !window.localStorage.getItem('fleetView')) {
      setFleetView('list');
    }
  }, [isMobile, fleetView, setFleetView]);

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

  const vehicleFilterActive = (key) => (filter.vehicleStatuses || []).includes(key) || (key === 'parked' && (filter.vehicleStatuses || []).includes('stopped')) || (key === 'stopped' && (filter.vehicleStatuses || []).includes('parked'));
  const toggleVehicleFilter = (key) => {
    const current = filter.vehicleStatuses || [];
    const aliases = key === 'parked' || key === 'stopped' ? ['parked', 'stopped'] : [key];
    const has = aliases.some((k) => current.includes(k));
    const next = has ? current.filter((s) => !aliases.includes(s)) : [...current, key === 'stopped' ? 'parked' : key];
    setFilter({ ...filter, vehicleStatuses: next });
  };

  const clearVehicleFilters = () => setFilter({ ...filter, vehicleStatuses: [] });

  // On APK/iOS (mobile) we surface fleet list as primary view
  const showSidebar = isMobile ? fleetView !== 'map' : devicesOpen;
  const showMap = isMobile ? fleetView !== 'list' : true;

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
      {isMobile && (
        <div className={classes.viewToggle}>
          <button
            type="button"
            className={`${classes.viewToggleButton} ${fleetView === 'list' ? classes.viewToggleActive : ''}`}
            onClick={() => setFleetView('list')}
          >
            <ViewListIcon fontSize="small" /> Fleet List
          </button>
          <button
            type="button"
            className={`${classes.viewToggleButton} ${fleetView === 'map' ? classes.viewToggleActive : ''}`}
            onClick={() => setFleetView('map')}
          >
            <MapIconMui fontSize="small" /> Map
          </button>
          <button
            type="button"
            className={`${classes.viewToggleButton} ${fleetView === 'split' ? classes.viewToggleActive : ''}`}
            onClick={() => setFleetView('split')}
          >
            <ViewListIcon fontSize="small" /> + <MapIconMui fontSize="small" />
          </button>
        </div>
      )}
      <div className={classes.body}>
        {/* Sidebar – Fleet List (primary on APK/iOS) */}
        <div className={`${classes.sidebar} ${showSidebar ? '' : classes.sidebarClosed} ${!showSidebar && isMobile ? classes.sidebarMobileHidden : ''}`}>
          <div className={classes.sidebarInner}>
            {/* Fleet Dashboard – ignition-based stats, clickable */}
            <FleetDashboard filter={filter} setFilter={setFilter} />

            <Divider />

            {/* Quick filter chips – running / stopped / idling / parked (ignition) */}
            <Stack direction="row" className={classes.filterChips} sx={{ flexWrap: 'wrap' }}>
              <Chip label={`All (${Object.keys(devices).length})`} size="small" variant={(filter.vehicleStatuses || []).length === 0 ? 'filled' : 'outlined'} color={(filter.vehicleStatuses || []).length === 0 ? 'primary' : 'default'} onClick={clearVehicleFilters} />
              <Chip label="Running" size="small" color="success" variant={vehicleFilterActive('running') ? 'filled' : 'outlined'} onClick={() => toggleVehicleFilter('running')} />
              <Chip label="Idling" size="small" color="warning" variant={vehicleFilterActive('idling') ? 'filled' : 'outlined'} onClick={() => toggleVehicleFilter('idling')} />
              <Chip label="Parked" size="small" variant={vehicleFilterActive('parked') ? 'filled' : 'outlined'} onClick={() => toggleVehicleFilter('parked')} />
              <Chip label="Stopped" size="small" variant={vehicleFilterActive('stopped') ? 'filled' : 'outlined'} onClick={() => toggleVehicleFilter('stopped')} />
              <Chip label="Offline" size="small" color="error" variant={vehicleFilterActive('offline') ? 'filled' : 'outlined'} onClick={() => toggleVehicleFilter('offline')} />
            </Stack>
            <Typography variant="caption" color="textSecondary" sx={{ px: 1.5, pb: 0.5 }}>
              Filter by ignition status – DVR/CNMS unchanged, Teltonika via ignition parameter (io239 fallback).
            </Typography>

            {/* Vehicle List – uses ignition-colored icons (gray=off, green=running) */}
            <div className={classes.sectionTitle}>
              Vehicles ({filteredDevices.length} / {Object.keys(devices).length})
            </div>
            <div style={{ flex: 1, minHeight: 0 }}>
              <DeviceList devices={filteredDevices} />
            </div>

            {/* Navigation */}
            {compactNav ? (
              <div className={classes.navSectionCompact}>
                {navItems.map((item) => (
                  <button
                    key={item.key}
                    type="button"
                    title={item.label}
                    className={`${classes.navItemCompact} ${nav === item.key ? classes.navItemCompactActive : ''}`}
                    onClick={() => handleNav(item.key)}
                  >
                    {item.icon}
                  </button>
                ))}
                <button
                  type="button"
                  title={t('loginLogout')}
                  className={`${classes.navItemCompact} ${classes.navItemCompactDanger}`}
                  onClick={handleLogout}
                >
                  <LogoutIcon fontSize="small" />
                </button>
              </div>
            ) : (
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
            )}
          </div>
        </div>

        {/* Map – hidden on mobile when fleet list is primary (APK/iOS shows list on login) */}
        {showMap && (
          <div className={`${classes.mapArea} ${!showMap ? classes.mapHiddenMobile : ''}`}>
            <Suspense fallback={null}>
              <MainMap
                filteredPositions={filteredPositions}
                selectedPosition={selectedPosition}
                onEventsClick={onEventsClick}
              />
            </Suspense>
          </div>
        )}
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
