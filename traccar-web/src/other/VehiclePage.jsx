import { useEffect, useMemo, useState } from 'react';
import { useSelector } from 'react-redux';
import {
  AppBar,
  Box,
  Button,
  Chip,
  CircularProgress,
  IconButton,
  Paper,
  Toolbar,
  Typography,
} from '@mui/material';
import { makeStyles } from 'tss-react/mui';
import { useNavigate, useSearchParams } from 'react-router-dom';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import VideocamIcon from '@mui/icons-material/Videocam';
import HistoryIcon from '@mui/icons-material/History';
import RouteIcon from '@mui/icons-material/Route';
import PlaceIcon from '@mui/icons-material/Place';
import SpeedIcon from '@mui/icons-material/Speed';
import BoltIcon from '@mui/icons-material/Bolt';
import SatelliteAltIcon from '@mui/icons-material/SatelliteAlt';
import DirectionsCarIcon from '@mui/icons-material/DirectionsCar';
import LocalParkingIcon from '@mui/icons-material/LocalParking';
import ScheduleIcon from '@mui/icons-material/Schedule';
import BackIcon from '../common/components/BackIcon';
import { useTranslation } from '../common/components/LocalizationProvider';
import { useAttributePreference } from '../common/util/preferences';
import { formatDistance, formatSpeed } from '../common/util/formatter';
import { distanceFromMeters } from '../common/util/converter';
import { getVehicleStatus, drivingSpeed } from '../common/util/vehicleStatus';
import fetchOrThrow from '../common/util/fetchOrThrow';
import { useCatch } from '../reactHelper';

dayjs.extend(relativeTime);

const duration = (value) => {
  const minutes = Math.round((value || 0) / 60000);
  const hours = Math.floor(minutes / 60);
  return hours ? `${hours} h ${minutes % 60} min` : `${minutes} min`;
};

const useStyles = makeStyles()((theme) => ({
  root: {
    height: '100%',
    display: 'flex',
    flexDirection: 'column',
  },
  content: {
    flexGrow: 1,
    overflow: 'auto',
    padding: theme.spacing(2),
    display: 'flex',
    flexDirection: 'column',
    gap: theme.spacing(2),
  },
  chips: {
    display: 'flex',
    gap: theme.spacing(1),
    flexWrap: 'wrap',
  },
  card: {
    padding: theme.spacing(1.5, 2),
  },
  cardTitle: {
    color: theme.palette.text.secondary,
    textTransform: 'uppercase',
    fontSize: '0.7rem',
    letterSpacing: '0.06em',
    marginBottom: theme.spacing(1),
  },
  odometer: {
    display: 'flex',
    gap: 4,
    justifyContent: 'center',
  },
  digit: {
    backgroundColor: theme.palette.mode === 'light' ? '#1f2937' : '#111827',
    color: '#fff',
    fontWeight: 700,
    fontSize: '1.6rem',
    lineHeight: 1,
    padding: theme.spacing(1, 0.75),
    borderRadius: 6,
    minWidth: 28,
    textAlign: 'center',
  },
  facts: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
    gap: theme.spacing(1),
  },
  fact: {
    display: 'flex',
    alignItems: 'center',
    gap: theme.spacing(0.75),
    border: `1px solid ${theme.palette.divider}`,
    borderRadius: 8,
    padding: theme.spacing(1, 1.25),
  },
  factLabel: {
    color: theme.palette.text.secondary,
    fontSize: '0.7rem',
  },
  actions: {
    display: 'flex',
    gap: theme.spacing(1),
    flexWrap: 'wrap',
  },
}));

// Everything about one vehicle on a single screen: where it is, what it has done
// today, its last journey and how far it has travelled in total.
const VehiclePage = () => {
  const { classes } = useStyles();
  const navigate = useNavigate();
  const t = useTranslation();

  const [searchParams] = useSearchParams();
  const deviceId = searchParams.get('deviceId');
  const device = useSelector((state) => state.devices.items[deviceId]);
  const position = useSelector((state) => state.session.positions[deviceId]);

  const speedUnit = useAttributePreference('speedUnit', 'mph');
  const distanceUnit = useAttributePreference('distanceUnit', 'mi');

  const [today, setToday] = useState(null);
  const [loading, setLoading] = useState(false);

  const load = useCatch(async () => {
    if (!deviceId) return;
    setLoading(true);
    try {
      const query = new URLSearchParams({
        deviceId,
        from: dayjs().startOf('day').toISOString(),
        to: dayjs().endOf('day').toISOString(),
      });
      const [trips, stops] = await Promise.all(
        ['trips', 'stops'].map(async (kind) => {
          const response = await fetchOrThrow(`/api/reports/${kind}?${query.toString()}`, {
            headers: { Accept: 'application/json' },
          });
          return response.json();
        }),
      );
      setToday({ trips, stops });
    } finally {
      setLoading(false);
    }
  });

  useEffect(() => {
    load();
  }, [deviceId]);

  const summary = useMemo(() => {
    const trips = today?.trips || [];
    const stops = today?.stops || [];
    return {
      driving: trips.reduce((sum, trip) => sum + (trip.duration || 0), 0),
      distance: trips.reduce((sum, trip) => sum + (trip.distance || 0), 0),
      parked: stops.reduce((sum, stop) => sum + (stop.duration || 0), 0),
      journeys: trips.length,
      lastTrip: trips.length ? trips[trips.length - 1] : null,
    };
  }, [today]);

  const status = getVehicleStatus(device, position);
  const speed = drivingSpeed(device, position, speedUnit, t);
  const odometer = position?.attributes?.totalDistance;
  const place = position?.address || position?.attributes?.cnmsAddress;
  const voltage = position?.attributes?.power;
  const satellites = position?.attributes?.sat;
  const hasCamera = Boolean(device?.attributes?.cmsv9DeviceId);

  const odometerDigits =
    odometer > 0
      ? String(Math.round(distanceFromMeters(odometer, distanceUnit)))
          .padStart(6, '0')
          .split('')
      : null;

  return (
    <div className={classes.root}>
      <AppBar
        position="static"
        color="transparent"
        elevation={0}
        sx={{ borderBottom: 1, borderColor: 'divider' }}
      >
        <Toolbar>
          <IconButton edge="start" sx={{ mr: 2 }} onClick={() => navigate(-1)}>
            <BackIcon />
          </IconButton>
          <Typography variant="h6" noWrap sx={{ flexGrow: 1 }}>
            {device?.name || t('sharedDevice')}
          </Typography>
          {device?.lastUpdate && (
            <Typography variant="caption" color="text.secondary">
              {dayjs(device.lastUpdate).fromNow()}
            </Typography>
          )}
        </Toolbar>
      </AppBar>

      <div className={classes.content}>
        <div className={classes.chips}>
          <Chip
            size="small"
            color={status === 'running' ? 'success' : status === 'idling' ? 'warning' : 'default'}
            label={status.charAt(0).toUpperCase() + status.slice(1)}
          />
          {speed && <Chip size="small" icon={<SpeedIcon />} label={speed} />}
          {voltage !== undefined && (
            <Chip size="small" icon={<BoltIcon />} label={`${voltage} V`} />
          )}
          {satellites !== undefined && (
            <Chip size="small" icon={<SatelliteAltIcon />} label={`${satellites} sats`} />
          )}
        </div>

        {place && (
          <Typography variant="body2" color="text.secondary" sx={{ display: 'flex', gap: 0.5 }}>
            <PlaceIcon fontSize="small" color="error" />
            {place}
          </Typography>
        )}

        {odometerDigits && (
          <Paper variant="outlined" className={classes.card}>
            <Typography className={classes.cardTitle}>{`Odometer — ${distanceUnit}`}</Typography>
            <div className={classes.odometer}>
              {odometerDigits.map((digit, index) => (
                <span key={`${digit}-${index}`} className={classes.digit}>
                  {digit}
                </span>
              ))}
            </div>
          </Paper>
        )}

        <Paper variant="outlined" className={classes.card}>
          <Typography className={classes.cardTitle}>Today</Typography>
          {loading && <CircularProgress size={22} />}
          {!loading && (
            <div className={classes.facts}>
              <div className={classes.fact}>
                <DirectionsCarIcon fontSize="small" color="success" />
                <Box>
                  <Typography variant="body2">{duration(summary.driving)}</Typography>
                  <Typography className={classes.factLabel}>Driving</Typography>
                </Box>
              </div>
              <div className={classes.fact}>
                <RouteIcon fontSize="small" color="warning" />
                <Box>
                  <Typography variant="body2">
                    {formatDistance(summary.distance, distanceUnit, t)}
                  </Typography>
                  <Typography className={classes.factLabel}>Distance</Typography>
                </Box>
              </div>
              <div className={classes.fact}>
                <LocalParkingIcon fontSize="small" color="primary" />
                <Box>
                  <Typography variant="body2">{duration(summary.parked)}</Typography>
                  <Typography className={classes.factLabel}>Parked</Typography>
                </Box>
              </div>
              <div className={classes.fact}>
                <ScheduleIcon fontSize="small" color="action" />
                <Box>
                  <Typography variant="body2">{summary.journeys}</Typography>
                  <Typography className={classes.factLabel}>Journeys</Typography>
                </Box>
              </div>
            </div>
          )}
        </Paper>

        {summary.lastTrip && (
          <Paper variant="outlined" className={classes.card}>
            <Typography className={classes.cardTitle}>
              {`Last journey — ${dayjs(summary.lastTrip.startTime).format('D MMM')}`}
            </Typography>
            <Typography variant="body2" sx={{ mb: 0.5 }}>
              {`${dayjs(summary.lastTrip.startTime).format('HH:mm:ss')} – ${dayjs(summary.lastTrip.endTime).format('HH:mm:ss')}`}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {`Max ${formatSpeed(summary.lastTrip.maxSpeed, speedUnit, t)} · Avg ${formatSpeed(summary.lastTrip.averageSpeed, speedUnit, t)}`}
            </Typography>
            <Typography variant="body2" color="text.secondary">
              {`${duration(summary.lastTrip.duration)} · ${formatDistance(summary.lastTrip.distance, distanceUnit, t)}`}
            </Typography>
          </Paper>
        )}

        <div className={classes.actions}>
          {hasCamera && (
            <Button
              variant="contained"
              startIcon={<VideocamIcon />}
              onClick={() => navigate(`/cmsv9-video?deviceId=${deviceId}`)}
            >
              {t('linkLiveVideo')}
            </Button>
          )}
          <Button
            variant="outlined"
            startIcon={<HistoryIcon />}
            onClick={() => navigate(`/journeys?deviceId=${deviceId}`)}
          >
            Journeys
          </Button>
          <Button
            variant="outlined"
            startIcon={<RouteIcon />}
            onClick={() => navigate(`/replay?deviceId=${deviceId}`)}
          >
            {t('reportReplay')}
          </Button>
        </div>
      </div>
    </div>
  );
};

export default VehiclePage;
