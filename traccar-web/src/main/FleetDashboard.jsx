import { useMemo } from 'react';
import { useSelector } from 'react-redux';
import { makeStyles } from 'tss-react/mui';
import { alpha } from '@mui/material/styles';
import DirectionsCarIcon from '@mui/icons-material/DirectionsCar';
import PauseCircleIcon from '@mui/icons-material/PauseCircle';
import LocalParkingIcon from '@mui/icons-material/LocalParking';
import StopCircleIcon from '@mui/icons-material/StopCircle';
import CloudOffIcon from '@mui/icons-material/CloudOff';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import { Typography, Box, Tooltip } from '@mui/material';
import { computeFleetStats } from '../common/util/vehicleStatus';

const useStyles = makeStyles()((theme) => ({
  root: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: theme.spacing(1.2),
    padding: theme.spacing(2),
  },
  card: {
    display: 'flex',
    alignItems: 'center',
    gap: theme.spacing(1.2),
    padding: theme.spacing(1.5),
    borderRadius: 12,
    border: `1px solid ${theme.palette.divider}`,
    backgroundColor: theme.palette.background.paper,
    transition: 'border-color 0.2s, box-shadow 0.2s, transform 0.15s',
    cursor: 'pointer',
    userSelect: 'none',
    '&:hover': {
      borderColor: alpha(theme.palette.primary.main, 0.3),
      boxShadow: `0 2px 8px ${alpha(theme.palette.primary.main, 0.08)}`,
      transform: 'translateY(-1px)',
    },
  },
  cardActive: {
    borderColor: alpha(theme.palette.primary.main, 0.5),
    backgroundColor: alpha(theme.palette.primary.main, 0.06),
    boxShadow: `0 4px 12px ${alpha(theme.palette.primary.main, 0.12)}`,
  },
  iconBox: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: 40,
    height: 40,
    borderRadius: 10,
    flexShrink: 0,
  },
  runningBg: {
    backgroundColor: alpha(theme.palette.success.main, 0.14),
  },
  idlingBg: {
    backgroundColor: alpha(theme.palette.warning.main, 0.14),
  },
  parkedBg: {
    backgroundColor: alpha(theme.palette.neutral.main, 0.14),
  },
  stoppedBg: {
    backgroundColor: alpha(theme.palette.neutral.main, 0.12),
  },
  offlineBg: {
    backgroundColor: alpha(theme.palette.error.main, 0.1),
  },
  alarmBg: {
    backgroundColor: alpha(theme.palette.error.main, 0.14),
  },
  info: {
    display: 'flex',
    flexDirection: 'column',
    minWidth: 0,
  },
  count: {
    fontWeight: 700,
    fontSize: '1.25rem',
    lineHeight: 1.2,
    letterSpacing: '-0.02em',
  },
  label: {
    fontSize: '0.7rem',
    fontWeight: 500,
    color: theme.palette.text.secondary,
    textTransform: 'uppercase',
    letterSpacing: '0.04em',
  },
}));

/**
 * FleetDashboard – ignition-based stats.
 * - DVR/CNMS unchanged: uses standard `ignition` attribute.
 * - Teltonika: resolves ignition via io239 / fallback keys + per-device override (see vehicleStatus.js).
 * Cards are clickable filters (running / idling / parked / stopped / offline).
 */
const FleetDashboard = ({ filter, setFilter }) => {
  const { classes } = useStyles();
  const devices = useSelector((state) => state.devices.items);
  const positions = useSelector((state) => state.session.positions);

  const stats = useMemo(() => {
    const base = computeFleetStats(devices, positions);
    // alarms: independent of ignition status
    let alarms = 0;
    Object.values(devices).forEach((device) => {
      const position = positions[device.id];
      if (position?.attributes?.alarm) alarms += 1;
    });
    return { ...base, alarms };
  }, [devices, positions]);

  const isActive = (key) => {
    const v = filter?.vehicleStatuses || filter?.statuses || [];
    // parked & stopped are aliases – highlight both if either active
    if (key === 'parked' || key === 'stopped') return v.includes('parked') || v.includes('stopped');
    return v.includes(key);
  };

  const toggleStatus = (key) => {
    if (!setFilter || !filter) return;
    // Support both new filter.vehicleStatuses and legacy filter.statuses
    const current = filter.vehicleStatuses ?? filter.statuses ?? [];
    const alias = key === 'parked' ? ['parked', 'stopped'] : [key];
    const has = alias.some((k) => current.includes(k));
    let next;
    if (has) {
      next = current.filter((s) => !alias.includes(s));
    } else {
      next = [...current, key];
      // keep parked/stopped in sync – store as parked
      if (key === 'stopped') next = next.filter((s) => s !== 'stopped').concat('parked');
    }
    // Prefer new field vehicleStatuses; keep statuses for device online/offline if needed
    if (filter.vehicleStatuses !== undefined) {
      setFilter({ ...filter, vehicleStatuses: next });
    } else {
      // Migrate to vehicleStatuses
      setFilter({ ...filter, vehicleStatuses: next });
    }
  };

  const Card = ({ statusKey, label, count, icon, bgClass, color }) => (
    <Tooltip title={`Filter: ${label}`} arrow>
      <div
        className={`${classes.card} ${isActive(statusKey) ? classes.cardActive : ''}`}
        onClick={() => toggleStatus(statusKey)}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === 'Enter') toggleStatus(statusKey); }}
      >
        <div className={`${classes.iconBox} ${classes[bgClass]}`}>
          <Box sx={{ color: `${color}.main`, fontSize: 22, display: 'flex' }}>{icon}</Box>
        </div>
        <div className={classes.info}>
          <Typography className={classes.count} color={`${color}.main`}>{count}</Typography>
          <Typography className={classes.label}>{label}</Typography>
        </div>
      </div>
    </Tooltip>
  );

  return (
    <div className={classes.root}>
      <Card statusKey="running" label="Running" count={stats.running} icon={<DirectionsCarIcon fontSize="inherit" />} bgClass="runningBg" color="success" />
      <Card statusKey="idling" label="Idling" count={stats.idling} icon={<PauseCircleIcon fontSize="inherit" />} bgClass="idlingBg" color="warning" />
      <Card statusKey="parked" label="Parked" count={stats.parked} icon={<LocalParkingIcon fontSize="inherit" />} bgClass="parkedBg" color="neutral" />
      <Card statusKey="stopped" label="Stopped" count={stats.stopped} icon={<StopCircleIcon fontSize="inherit" />} bgClass="stoppedBg" color="neutral" />
      <Card statusKey="offline" label="Offline" count={stats.offline} icon={<CloudOffIcon fontSize="inherit" />} bgClass="offlineBg" color="error" />
      {stats.alarms > 0 && (
        <Box sx={{ gridColumn: '1 / -1' }}>
          <div className={classes.card} style={{ borderColor: alpha('#dc2626', 0.3), cursor: 'default' }}>
            <div className={`${classes.iconBox} ${classes.alarmBg}`}>
              <WarningAmberIcon sx={{ color: 'error.main', fontSize: 22 }} />
            </div>
            <div className={classes.info}>
              <Typography className={classes.count} color="error.main">{stats.alarms}</Typography>
              <Typography className={classes.label}>Active Alarms</Typography>
            </div>
          </div>
        </Box>
      )}
    </div>
  );
};

export default FleetDashboard;
