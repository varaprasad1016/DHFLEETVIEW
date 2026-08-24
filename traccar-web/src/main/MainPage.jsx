import { lazy, Suspense, useState, useCallback, useEffect } from 'react';
import {
  Box,
  Divider,
  Typography,
  IconButton,
} from '@mui/material';
import { makeStyles } from 'tss-react/mui';
import { alpha } from '@mui/material/styles';
import { useDispatch, useSelector } from 'react-redux';
import CloseIcon from '@mui/icons-material/Close';
import SearchIcon from '@mui/icons-material/Search';
import FilterListIcon from '@mui/icons-material/FilterList';
import AddIcon from '@mui/icons-material/Add';
import {
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  FormGroup,
  FormControlLabel,
  Checkbox,
  Badge,
  Popover,
  Tooltip,
  List,
  ListItemButton,
  ListItemText,
} from '@mui/material';
import DeviceList from './DeviceList';
import FleetDashboard from './FleetDashboard';
import StatusCard from '../common/components/StatusCard';
import { devicesActions } from '../store';
import usePersistedState from '../common/util/usePersistedState';
import EventsDrawer from './EventsDrawer';
import useFilter from './useFilter';
import MainToolbar from './MainToolbar';
import { useAttributePreference } from '../common/util/preferences';
import { useDeviceReadonly } from '../common/util/permissions';
import { useTranslation } from '../common/components/LocalizationProvider';

const MainMap = lazy(() => import('./MainMap'));

const SIDEBAR_WIDTH = 380;

const useStyles = makeStyles()((theme) => ({
  root: {
    height: '100%',
    display: 'flex',
    flexDirection: 'column',
  },
  content: {
    flex: 1,
    display: 'flex',
    overflow: 'hidden',
  },
  sidebar: {
    width: SIDEBAR_WIDTH,
    height: '100%',
    display: 'flex',
    flexDirection: 'column',
    borderRight: `1px solid ${theme.palette.divider}`,
    backgroundColor: theme.palette.background.default,
    flexShrink: 0,
    overflow: 'hidden',
    transition: 'width 0.25s ease, opacity 0.2s ease',
    [theme.breakpoints.down('sm')]: {
      position: 'fixed',
      left: 0,
      top: 56,
      bottom: 0,
      zIndex: 1100,
      width: '85%',
      maxWidth: 380,
      boxShadow: '4px 0 24px rgba(0,0,0,0.12)',
    },
  },
  sidebarHidden: {
    width: 0,
    opacity: 0,
    borderRight: 'none',
    [theme.breakpoints.down('sm')]: {
      width: 0,
    },
  },
  drawerHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: theme.spacing(1.5, 2),
    borderBottom: `1px solid ${theme.palette.divider}`,
    backgroundColor: theme.palette.background.paper,
    flexShrink: 0,
  },
  drawerTitle: {
    fontWeight: 700,
    fontSize: '1rem',
    letterSpacing: '-0.01em',
  },
  searchBox: {
    display: 'flex',
    alignItems: 'center',
    gap: theme.spacing(0.5),
    margin: theme.spacing(1.5, 2),
    padding: theme.spacing(0.75, 1.5),
    borderRadius: 10,
    backgroundColor: alpha(theme.palette.text.primary, 0.04),
    border: `1px solid ${theme.palette.divider}`,
    flexShrink: 0,
    transition: 'border-color 0.2s, box-shadow 0.2s',
    '&:focus-within': {
      borderColor: theme.palette.primary.main,
      boxShadow: `0 0 0 3px ${alpha(theme.palette.primary.main, 0.1)}`,
      backgroundColor: theme.palette.background.paper,
    },
  },
  searchInput: {
    flex: 1,
    fontSize: '0.875rem',
    padding: 0,
    border: 'none',
    outline: 'none',
    backgroundColor: 'transparent',
    color: theme.palette.text.primary,
    '&::placeholder': {
      color: theme.palette.text.secondary,
    },
  },
  sectionTitle: {
    fontWeight: 600,
    fontSize: '0.7rem',
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    color: theme.palette.text.secondary,
    padding: theme.spacing(1.5, 2, 0.5),
    flexShrink: 0,
  },
  deviceSection: {
    flex: 1,
    minHeight: 0,
    overflow: 'hidden',
  },
  mapContainer: {
    flex: 1,
    position: 'relative',
    minWidth: 0,
  },
  overlay: {
    [theme.breakpoints.down('sm')]: {
      position: 'fixed',
      inset: 0,
      top: 56,
      backgroundColor: 'rgba(0,0,0,0.3)',
      zIndex: 1099,
    },
  },
}));

const FilterPopover = ({
  anchorEl,
  onClose,
  filter,
  setFilter,
  filterSort,
  setFilterSort,
  filterMap,
  setFilterMap,
  groups,
  geofences,
  deviceStatusCount,
  t,
}) => (
  <Popover
    open={Boolean(anchorEl)}
    anchorEl={anchorEl}
    onClose={onClose}
    anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
    marginThreshold={0}
  >
    <Box sx={{ p: 2, display: 'flex', flexDirection: 'column', gap: 2, width: 280 }}>
      <FormControl size="small">
        <InputLabel>{t('deviceStatus')}</InputLabel>
        <Select
          label={t('deviceStatus')}
          value={filter.statuses}
          onChange={(e) => setFilter({ ...filter, statuses: e.target.value })}
          multiple
        >
          <MenuItem value="online">{`${t('deviceStatusOnline')} (${deviceStatusCount('online')})`}</MenuItem>
          <MenuItem value="offline">{`${t('deviceStatusOffline')} (${deviceStatusCount('offline')})`}</MenuItem>
          <MenuItem value="unknown">{`${t('deviceStatusUnknown')} (${deviceStatusCount('unknown')})`}</MenuItem>
        </Select>
      </FormControl>
      <FormControl size="small">
        <InputLabel>{t('settingsGroups')}</InputLabel>
        <Select
          label={t('settingsGroups')}
          value={filter.groups}
          onChange={(e) => setFilter({ ...filter, groups: e.target.value })}
          multiple
        >
          {Object.values(groups)
            .sort((a, b) => a.name.localeCompare(b.name))
            .map((group) => (
              <MenuItem key={group.id} value={group.id}>{group.name}</MenuItem>
            ))}
        </Select>
      </FormControl>
      <FormControl size="small">
        <InputLabel>{t('sharedGeofences')}</InputLabel>
        <Select
          label={t('sharedGeofences')}
          value={filter.geofences}
          onChange={(e) => setFilter({ ...filter, geofences: e.target.value })}
          multiple
        >
          {Object.values(geofences)
            .sort((a, b) => a.name.localeCompare(b.name))
            .map((geofence) => (
              <MenuItem key={geofence.id} value={geofence.id}>{geofence.name}</MenuItem>
            ))}
        </Select>
      </FormControl>
      <FormControl size="small">
        <InputLabel>{t('sharedSortBy')}</InputLabel>
        <Select
          label={t('sharedSortBy')}
          value={filterSort}
          onChange={(e) => setFilterSort(e.target.value)}
        >
          <MenuItem value="">&nbsp;</MenuItem>
          <MenuItem value="name">{t('sharedName')}</MenuItem>
          <MenuItem value="lastUpdate">{t('deviceLastUpdate')}</MenuItem>
        </Select>
      </FormControl>
      <FormGroup>
        <FormControlLabel
          control={
            <Checkbox checked={filterMap} onChange={(e) => setFilterMap(e.target.checked)} size="small" />
          }
          label={t('sharedFilterMap')}
        />
      </FormGroup>
    </Box>
  </Popover>
);

const MainPage = () => {
  const { classes } = useStyles();
  const dispatch = useDispatch();
  const t = useTranslation();
  const deviceReadonly = useDeviceReadonly();

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

  const [sidebarOpen, setSidebarOpen] = useState(true);
  const [eventsOpen, setEventsOpen] = useState(false);
  const [filterAnchorEl, setFilterAnchorEl] = useState(null);

  const onEventsClick = useCallback(() => setEventsOpen(true), [setEventsOpen]);

  const groups = useSelector((state) => state.groups.items);
  const devices = useSelector((state) => state.devices.items);
  const geofences = useSelector((state) => state.geofences.items);

  const deviceStatusCount = (status) =>
    Object.values(devices).filter((d) => d.status === status).length;

  useEffect(() => {
    if (mapOnSelect && selectedDeviceId) {
      setSidebarOpen(false);
    }
  }, [mapOnSelect, selectedDeviceId]);

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
      <MainToolbar sidebarOpen={sidebarOpen} onToggleSidebar={() => setSidebarOpen(!sidebarOpen)} />
      <div className={classes.content}>
        {/* Sidebar */}
        <div className={`${classes.sidebar} ${sidebarOpen ? '' : classes.sidebarHidden}`}>
          <div className={classes.drawerHeader}>
            <Typography className={classes.drawerTitle}>Fleet Overview</Typography>
            <IconButton size="small" onClick={() => setSidebarOpen(false)}>
              <CloseIcon fontSize="small" />
            </IconButton>
          </div>

          <div style={{ overflow: 'auto', flex: 1, minHeight: 0 }}>
            {/* Dashboard Stats */}
            <FleetDashboard />
            <Divider />

            {/* Search + Filter */}
            <div className={classes.searchBox}>
              <SearchIcon fontSize="small" sx={{ color: 'text.secondary' }} />
              <input
                className={classes.searchInput}
                placeholder={t('sharedSearchDevices')}
                value={keyword}
                onChange={(e) => setKeyword(e.target.value)}
              />
              <IconButton size="small" onClick={(e) => setFilterAnchorEl(e.currentTarget)}>
                <Badge
                  color="info"
                  variant="dot"
                  invisible={!filter.statuses.length && !filter.groups.length && !filter.geofences.length}
                >
                  <FilterListIcon fontSize="small" sx={{ color: 'text.secondary' }} />
                </Badge>
              </IconButton>
            </div>

            {/* Device List */}
            <div className={classes.sectionTitle}>
              Vehicles ({filteredDevices.length})
            </div>
            <div className={classes.deviceSection}>
              <DeviceList devices={filteredDevices} />
            </div>
          </div>

          {/* Add device button */}
          {!deviceReadonly && (
            <Box sx={{ p: 1.5, borderTop: 1, borderColor: 'divider', flexShrink: 0 }}>
              <Tooltip title={t('deviceRegisterFirst')}>
                <IconButton
                  fullWidth
                  size="small"
                  sx={{
                    borderRadius: 2,
                    backgroundColor: alpha('#4f46e5', 0.06),
                    color: 'primary.main',
                    '&:hover': { backgroundColor: alpha('#4f46e5', 0.12) },
                  }}
                  onClick={() => { window.location.href = '/settings/device'; }}
                >
                  <AddIcon fontSize="small" />
                </IconButton>
              </Tooltip>
            </Box>
          )}
        </div>

        {/* Mobile overlay when sidebar is open */}
        {sidebarOpen && (
          <div className={classes.overlay} onClick={() => setSidebarOpen(false)} />
        )}

        {/* Map — full area */}
        <div className={classes.mapContainer}>
          <Suspense fallback={null}>
            <MainMap
              filteredPositions={filteredPositions}
              selectedPosition={selectedPosition}
              onEventsClick={onEventsClick}
            />
          </Suspense>
        </div>
      </div>

      <FilterPopover
        anchorEl={filterAnchorEl}
        onClose={() => setFilterAnchorEl(null)}
        filter={filter}
        setFilter={setFilter}
        filterSort={filterSort}
        setFilterSort={setFilterSort}
        filterMap={filterMap}
        setFilterMap={setFilterMap}
        groups={groups}
        geofences={geofences}
        deviceStatusCount={deviceStatusCount}
        t={t}
      />

      <EventsDrawer open={eventsOpen} onClose={() => setEventsOpen(false)} />
      {selectedDeviceId && (
        <StatusCard
          deviceId={selectedDeviceId}
          position={selectedPosition}
          onClose={() => dispatch(devicesActions.selectId(null))}
          desktopPadding={sidebarOpen ? SIDEBAR_WIDTH : 0}
        />
      )}
    </div>
  );
};

export default MainPage;
