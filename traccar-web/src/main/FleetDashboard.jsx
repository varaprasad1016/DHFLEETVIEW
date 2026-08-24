import { useMemo } from 'react';
import { useSelector } from 'react-redux';
import { makeStyles } from 'tss-react/mui';
import { alpha } from '@mui/material/styles';
import DirectionsCarIcon from '@mui/icons-material/DirectionsCar';
import PauseCircleIcon from '@mui/icons-material/PauseCircle';
import ParkingIcon from '@mui/icons-material/LocalParking';
import CloudOffIcon from '@mui/icons-material/CloudOff';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import { Typography, Box } from '@mui/material';

const SPEED_THRESHOLD = 3;

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
    transition: 'border-color 0.2s, box-shadow 0.2s',
    cursor: 'default',
    '&:hover': {
      borderColor: alpha(theme.palette.primary.main, 0.3),
      boxShadow: `0 2px 8px ${alpha(theme.palette.primary.main, 0.08)}`,
    },
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
    backgroundColor: alpha(theme.palette.success.main, 0.1),
  },
  idlingBg: {
    backgroundColor: alpha(theme.palette.warning.main, 0.1),
  },
  parkedBg: {
    backgroundColor: alpha(theme.palette.info.main, 0.1),
  },
  offlineBg: {
    backgroundColor: alpha(theme.palette.neutral.main, 0.1),
  },
  alarmBg: {
    backgroundColor: alpha(theme.palette.error.main, 0.1),
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

const FleetDashboard = () => {
  const { classes } = useStyles();
  const devices = useSelector((state) => state.devices.items);
  const positions = useSelector((state) => state.session.positions);

  const stats = useMemo(() => {
    let running = 0;
    let idling = 0;
    let parked = 0;
    let offline = 0;
    let alarms = 0;

    Object.values(devices).forEach((device) => {
      const position = positions[device.id];
      if (device.status === 'offline' || device.status === 'unknown' || !position) {
        offline++;
        return;
      }
      const speed = position.speed || 0;
      const ignition = position.attributes?.ignition;

      if (position.attributes?.alarm) {
        alarms++;
      }

      if (speed >= SPEED_THRESHOLD) {
        running++;
      } else if (ignition === true) {
        idling++;
      } else {
        parked++;
      }
    });

    return { running, idling, parked, offline, alarms, total: Object.keys(devices).length };
  }, [devices, positions]);

  return (
    <div className={classes.root}>
      <div className={classes.card}>
        <div className={`${classes.iconBox} ${classes.runningBg}`}>
          <DirectionsCarIcon sx={{ color: 'success.main', fontSize: 22 }} />
        </div>
        <div className={classes.info}>
          <Typography className={classes.count} color="success.main">{stats.running}</Typography>
          <Typography className={classes.label}>Running</Typography>
        </div>
      </div>
      <div className={classes.card}>
        <div className={`${classes.iconBox} ${classes.idlingBg}`}>
          <PauseCircleIcon sx={{ color: 'warning.main', fontSize: 22 }} />
        </div>
        <div className={classes.info}>
          <Typography className={classes.count} color="warning.main">{stats.idling}</Typography>
          <Typography className={classes.label}>Idling</Typography>
        </div>
      </div>
      <div className={classes.card}>
        <div className={`${classes.iconBox} ${classes.parkedBg}`}>
          <ParkingIcon sx={{ color: 'info.main', fontSize: 22 }} />
        </div>
        <div className={classes.info}>
          <Typography className={classes.count} color="info.main">{stats.parked}</Typography>
          <Typography className={classes.label}>Parked</Typography>
        </div>
      </div>
      <div className={classes.card}>
        <div className={`${classes.iconBox} ${classes.offlineBg}`}>
          <CloudOffIcon sx={{ color: 'neutral.main', fontSize: 22 }} />
        </div>
        <div className={classes.info}>
          <Typography className={classes.count} color="neutral.main">{stats.offline}</Typography>
          <Typography className={classes.label}>Offline</Typography>
        </div>
      </div>
      {stats.alarms > 0 && (
        <Box sx={{ gridColumn: '1 / -1' }}>
          <div className={classes.card} style={{ borderColor: alpha('#dc2626', 0.3) }}>
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
