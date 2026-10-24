import { lazy, Suspense, useState, useCallback, useEffect } from 'react';
import { makeStyles } from 'tss-react/mui';
import { useTheme } from '@mui/material/styles';
import useMediaQuery from '@mui/material/useMediaQuery';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate, useLocation } from 'react-router-dom';
import DescriptionIcon from '@mui/icons-material/Description';
import AssignmentIcon from '@mui/icons-material/Assignment';
import SettingsIcon from '@mui/icons-material/Settings';
import PersonIcon from '@mui/icons-material/Person';
import Badge from '@mui/material/Badge';
import Typography from '@mui/material/Typography';
import Box from '@mui/material/Box';
import Chip from '@mui/material/Chip';
import ViewListIcon from '@mui/icons-material/ViewList';
import MapIconMui from '@mui/icons-material/Map';
import { selectOnlyStatus } from '../common/util/vehicleStatus';
import DeviceList from './DeviceList';
import StatusCard from '../common/components/StatusCard';
import { devicesActions, sessionActions } from '../store';
import { nativePostMessage } from '../common/components/NativeInterface';
import usePersistedState from '../common/util/usePersistedState';
import EventsDrawer from './EventsDrawer';
import useFilter from './useFilter';
import MainToolbar from './MainToolbar';
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
}));

// Named in the list heading so a narrowed view is never silent.
const STATUS_LABEL = { running: 'Running', idling: 'Idling', offline: 'Offline' };

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
  const isWebView = typeof window !== 'undefined'
    && (!!window.flutter_inappwebview || (typeof navigator !== 'undefined' && /wv|WebView/i.test(navigator.userAgent)));
  const isAppMobile = isMobile || isWebView;
  // Mobile/WebView has two mutually exclusive full-screen views: the fleet
  // dashboard and the live map. The old combined 'split'/'list' modes are gone
  // because a full-width sidebar left no room for the map on a phone.
  const [fleetView, setFleetView] = usePersistedState('fleetView', 'dashboard');

  const onEventsClick = useCallback(() => setEventsOpen(true), [setEventsOpen]);

  // Migrate any legacy persisted view to the surviving two.
  useEffect(() => {
    if (fleetView === 'split' || fleetView === 'list') {
      setFleetView('dashboard');
    }
  }, [fleetView, setFleetView]);

  // Selecting a vehicle used to jump straight to the full-screen map, from
  // when tapping a row was how you found it on the map. Tapping a row now
  // opens its cameras, and the map travels with them on the video page, so
  // the jump has nothing left to do - and it did harm: the selection
  // outlives the video page, so coming back from one landed on the map
  // instead of the list the vehicle was tapped from.

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
        // Straight to the report builder, which is the index of /reports, so
        // a report can be run from here rather than landing on one particular
        // report and having to go looking for the others.
        let id = selectedDeviceId;
        if (id == null) {
          const deviceIds = Object.keys(devices);
          if (deviceIds.length === 1) id = deviceIds[0];
        }
        navigate(id != null ? `/reports?deviceId=${id}` : '/reports');
        break;
      }
      case 'tachoreports':
        // The tachograph module is served outside this app, so a full
        // navigation rather than a route change.
        window.location.href = '/tacho/hours?tab=report';
        break;
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

  // No map entry: this menu opens from the map, so it only ever took you to
  // where you already were.
  const navItems = [
    !disableReports && { key: 'reports', label: 'Tracking reports', icon: <DescriptionIcon fontSize="small" /> },
    !disableReports && { key: 'tachoreports', label: 'Tacho reports', icon: <AssignmentIcon fontSize="small" /> },
    !readonly && { key: 'settings', label: t('settingsTitle'), icon: <SettingsIcon fontSize="small" /> },
    !readonly && { key: 'account', label: t('settingsUser'), icon: <PersonIcon fontSize="small" /> },
  ].filter(Boolean);

  const safeFilter = filter || { statuses: [], vehicleStatuses: [], groups: [], geofences: [] };
  // Only ever none or one, so the selection is simply the first entry.
  const selectedStatus = (safeFilter.vehicleStatuses || [])[0] || null;
  const toggleVehicleFilter = (key) => setFilter({
    ...safeFilter,
    vehicleStatuses: selectOnlyStatus(safeFilter.vehicleStatuses, key),
  });

  const clearVehicleFilters = () => setFilter({ ...safeFilter, vehicleStatuses: [] });

  // Mobile/WebView shows exactly one full-screen surface at a time.
  const showSidebar = isAppMobile ? fleetView === 'dashboard' : devicesOpen;
  const showMap = isAppMobile ? fleetView === 'map' : true;

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
        navItems={navItems}
        nav={nav}
        onNav={handleNav}
        onLogout={handleLogout}
      />
      {isAppMobile && (
        <div className={classes.viewToggle}>
          <button
            type="button"
            className={`${classes.viewToggleButton} ${fleetView === 'dashboard' ? classes.viewToggleActive : ''}`}
            onClick={() => setFleetView('dashboard')}
          >
            <ViewListIcon fontSize="small" /> Dashboard
          </button>
          <button
            type="button"
            className={`${classes.viewToggleButton} ${fleetView === 'map' ? classes.viewToggleActive : ''}`}
            onClick={() => setFleetView('map')}
          >
            <MapIconMui fontSize="small" /> Map
          </button>
        </div>
      )}
      <div className={classes.body}>
        {/* Sidebar – Fleet List (primary on APK/iOS) */}
        <div className={`${classes.sidebar} ${showSidebar ? '' : classes.sidebarClosed} ${!showSidebar && isAppMobile ? classes.sidebarMobileHidden : ''}`}>
          <div className={classes.sidebarInner}>
            {/*
              The list is the home screen. The stat cards and the chip row used
              to sit above it and pushed the registrations below the fold, which
              is the one thing somebody opening the app actually wants to see.
              The counts and the status filter are still there, behind the
              filter control in the toolbar, and the selected filter is named
              above the list so the view is never silently narrowed.
            */}
            <div className={classes.sectionTitle}>
              {selectedStatus
                ? `${STATUS_LABEL[selectedStatus]} (${filteredDevices.length} of ${Object.keys(devices).length})`
                : `Vehicles (${filteredDevices.length})`}
              {selectedStatus && (
                <Chip
                  label="Show all"
                  size="small"
                  variant="outlined"
                  onClick={clearVehicleFilters}
                  sx={{ ml: 1, height: 20, fontSize: '0.65rem' }}
                />
              )}
            </div>
            <div style={{ flex: 1, minHeight: 0 }}>
              <DeviceList devices={filteredDevices} />
            </div>

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
