import { lazy, Suspense, useState, useCallback, useEffect } from 'react';
import { Paper } from '@mui/material';
import { makeStyles } from 'tss-react/mui';
import { alpha, useTheme } from '@mui/material/styles';
import useMediaQuery from '@mui/material/useMediaQuery';
import { useDispatch, useSelector } from 'react-redux';
import DeviceList from './DeviceList';
import BottomMenu from '../common/components/BottomMenu';
import StatusCard from '../common/components/StatusCard';
import FleetDashboard from './FleetDashboard';
import { devicesActions } from '../store';
import usePersistedState from '../common/util/usePersistedState';
import EventsDrawer from './EventsDrawer';
import useFilter from './useFilter';
import MainToolbar from './MainToolbar';
import { useAttributePreference } from '../common/util/preferences';

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
  sidebarScroll: {
    flex: 1,
    overflow: 'auto',
    minHeight: 0,
  },
  mapArea: {
    flex: 1,
    position: 'relative',
    minWidth: 0,
  },
  dashboardWrap: {
    flexShrink: 0,
  },
  searchWrap: {
    flexShrink: 0,
    padding: theme.spacing(0, 2, 1),
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
  deviceWrap: {
    flex: 1,
    minHeight: 0,
  },
  footer: {
    pointerEvents: 'auto',
    zIndex: 5,
  },
}));

const MainPage = () => {
  const { classes } = useStyles();
  const dispatch = useDispatch();
  const theme = useTheme();

  const desktop = useMediaQuery(theme.breakpoints.up('md'));

  const mapOnSelect = useAttributePreference('mapOnSelect', true);

  const selectedDeviceId = useSelector((state) => state.devices.selectedId);
  const positions = useSelector((state) => state.session.positions);
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

  const onEventsClick = useCallback(() => setEventsOpen(true), [setEventsOpen]);

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
            <div className={classes.dashboardWrap}>
              <FleetDashboard />
            </div>
            <div className={classes.searchWrap}>
              {/* Search is handled in MainToolbar now — placeholder for filter row */}
            </div>
            <div className={classes.sectionTitle}>
              Vehicles ({filteredDevices.length})
            </div>
            <div className={classes.deviceWrap}>
              <DeviceList devices={filteredDevices} />
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
      {!desktop && (
        <div className={classes.footer}>
          <BottomMenu />
        </div>
      )}
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
