import { useEffect, useMemo, useRef, useState } from 'react';
import { useSelector } from 'react-redux';
import { AppBar, Box, CircularProgress, IconButton, Toolbar, Typography } from '@mui/material';
import { makeStyles } from 'tss-react/mui';
import { useNavigate, useSearchParams } from 'react-router-dom';
import dayjs from 'dayjs';
import DirectionsCarIcon from '@mui/icons-material/DirectionsCar';
import LocalParkingIcon from '@mui/icons-material/LocalParking';
import ScheduleIcon from '@mui/icons-material/Schedule';
import RouteIcon from '@mui/icons-material/Route';
import SpeedIcon from '@mui/icons-material/Speed';
import BackIcon from '../common/components/BackIcon';
import { useTranslation } from '../common/components/LocalizationProvider';
import { useAttributePreference } from '../common/util/preferences';
import { formatDistance, formatSpeed } from '../common/util/formatter';
import fetchOrThrow from '../common/util/fetchOrThrow';
import { useCatch } from '../reactHelper';

const DAYS = 7;

// "19 min" / "2 h 4 min" reads better on a timeline than "0 h 19 m".
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
  days: {
    display: 'flex',
    gap: theme.spacing(1),
    padding: theme.spacing(1.5, 2),
    overflowX: 'auto',
    scrollbarWidth: 'none',
    '&::-webkit-scrollbar': { display: 'none' },
  },
  day: {
    width: 56,
    minHeight: 68,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 2,
    padding: theme.spacing(0.75, 0),
    borderRadius: 12,
    border: `1px solid ${theme.palette.divider}`,
    cursor: 'pointer',
    flex: '0 0 auto',
  },
  dayName: {
    fontSize: '0.7rem',
    lineHeight: 1.2,
  },
  dayNumber: {
    fontSize: '1rem',
    fontWeight: 700,
    lineHeight: 1.2,
  },
  daySelected: {
    backgroundColor: theme.palette.success.main,
    borderColor: theme.palette.success.main,
    color: theme.palette.success.contrastText,
  },
  totals: {
    display: 'flex',
    justifyContent: 'space-around',
    gap: theme.spacing(1),
    padding: theme.spacing(1, 2, 2),
    borderBottom: `1px solid ${theme.palette.divider}`,
    flexWrap: 'wrap',
  },
  total: {
    display: 'flex',
    alignItems: 'center',
    gap: theme.spacing(0.75),
  },
  list: {
    flexGrow: 1,
    overflow: 'auto',
    padding: theme.spacing(1, 2, 3),
  },
  row: {
    display: 'flex',
    gap: theme.spacing(1.5),
    alignItems: 'flex-start',
  },
  time: {
    width: 46,
    paddingTop: 10,
    flex: '0 0 auto',
    color: theme.palette.text.secondary,
  },
  rail: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    alignSelf: 'stretch',
    flex: '0 0 auto',
  },
  dot: {
    width: 30,
    height: 30,
    borderRadius: '50%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    border: '2px solid',
    marginTop: 6,
  },
  dotDrive: {
    borderColor: theme.palette.success.main,
    color: theme.palette.success.main,
  },
  dotStop: {
    borderColor: theme.palette.info?.main || theme.palette.primary.main,
    color: theme.palette.info?.main || theme.palette.primary.main,
  },
  line: {
    flexGrow: 1,
    width: 2,
    backgroundColor: theme.palette.divider,
  },
  card: {
    flexGrow: 1,
    border: `1px solid ${theme.palette.divider}`,
    borderRadius: 10,
    padding: theme.spacing(1, 1.25),
    margin: theme.spacing(0.5, 0, 1),
    minWidth: 0,
  },
  cardDrive: {
    cursor: 'pointer',
  },
  facts: {
    display: 'flex',
    gap: theme.spacing(1.5),
    flexWrap: 'wrap',
    alignItems: 'center',
    marginBottom: theme.spacing(0.5),
  },
  fact: {
    display: 'flex',
    alignItems: 'center',
    gap: 3,
    fontSize: '0.82rem',
    whiteSpace: 'nowrap',
  },
  replay: {
    marginLeft: 'auto',
    fontSize: '0.75rem',
    fontWeight: 600,
    color: theme.palette.primary.main,
    whiteSpace: 'nowrap',
  },
  address: {
    marginTop: 4,
  },
  empty: {
    padding: theme.spacing(6, 2),
    textAlign: 'center',
  },
}));

// A vehicle's day: every journey and every stop, in order, the way a driver or
// transport manager reads a day - not a spreadsheet of report rows.
const JourneysPage = () => {
  const { classes } = useStyles();
  const navigate = useNavigate();
  const t = useTranslation();

  const [searchParams] = useSearchParams();
  const deviceId = searchParams.get('deviceId');
  const device = useSelector((state) => state.devices.items[deviceId]);

  const distanceUnit = useAttributePreference('distanceUnit', 'mi');
  const speedUnit = useAttributePreference('speedUnit', 'mph');

  const [day, setDay] = useState(() => dayjs().startOf('day'));
  // The strip starts on today, at its right-hand end.
  const daysRef = useRef(null);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);

  const days = useMemo(
    () =>
      Array.from({ length: DAYS }, (_, i) =>
        dayjs()
          .startOf('day')
          .subtract(DAYS - 1 - i, 'day'),
      ),
    [],
  );

  const load = useCatch(async () => {
    if (!deviceId) return;
    setLoading(true);
    try {
      const query = new URLSearchParams({
        deviceId,
        from: day.toISOString(),
        to: day.endOf('day').toISOString(),
      });
      const [trips, stops] = await Promise.all(
        ['trips', 'stops'].map(async (kind) => {
          const response = await fetchOrThrow(`/api/reports/${kind}?${query.toString()}`, {
            headers: { Accept: 'application/json' },
          });
          return response.json();
        }),
      );
      const merged = [
        ...trips.map((trip) => ({ ...trip, kind: 'trip', time: trip.startTime })),
        ...stops.map((stop) => ({ ...stop, kind: 'stop', time: stop.startTime })),
      ].sort((a, b) => dayjs(a.time).valueOf() - dayjs(b.time).valueOf());
      setItems(merged);
    } finally {
      setLoading(false);
    }
  });

  useEffect(() => {
    load();
  }, [deviceId, day]);

  useEffect(() => {
    if (daysRef.current) {
      daysRef.current.scrollLeft = daysRef.current.scrollWidth;
    }
  }, []);

  const totals = useMemo(() => {
    const trips = items.filter((item) => item.kind === 'trip');
    const stops = items.filter((item) => item.kind === 'stop');
    return {
      driving: trips.reduce((sum, trip) => sum + (trip.duration || 0), 0),
      distance: trips.reduce((sum, trip) => sum + (trip.distance || 0), 0),
      parked: stops.reduce((sum, stop) => sum + (stop.duration || 0), 0),
    };
  }, [items]);

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
          <Typography variant="h6" noWrap>
            {device?.name || t('reportTrips')}
          </Typography>
        </Toolbar>
      </AppBar>

      <div className={classes.days} ref={daysRef}>
        {days.map((item) => (
          <div
            key={item.valueOf()}
            className={`${classes.day}${item.isSame(day, 'day') ? ` ${classes.daySelected}` : ''}`}
            onClick={() => setDay(item)}
          >
            <span className={classes.dayName}>{item.format('ddd')}</span>
            <span className={classes.dayNumber}>{item.format('D')}</span>
            <span className={classes.dayName}>{item.format('MMM')}</span>
          </div>
        ))}
      </div>

      <div className={classes.totals}>
        <div className={classes.total}>
          <DirectionsCarIcon fontSize="small" color="success" />
          <Typography variant="body2">{duration(totals.driving)}</Typography>
        </div>
        <div className={classes.total}>
          <RouteIcon fontSize="small" color="warning" />
          <Typography variant="body2">
            {formatDistance(totals.distance, distanceUnit, t)}
          </Typography>
        </div>
        <div className={classes.total}>
          <LocalParkingIcon fontSize="small" color="primary" />
          <Typography variant="body2">{duration(totals.parked)}</Typography>
        </div>
      </div>

      <div className={classes.list}>
        {loading && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress size={28} />
          </Box>
        )}
        {!loading && !items.length && (
          <Typography className={classes.empty} color="text.secondary">
            {`Nothing recorded on ${day.format('ddd D MMM')}`}
          </Typography>
        )}
        {!loading &&
          items.map((item, index) => {
            const drive = item.kind === 'trip';
            return (
              <div className={classes.row} key={`${item.kind}-${item.time}-${index}`}>
                <Typography variant="body2" className={classes.time}>
                  {dayjs(item.time).format('HH:mm')}
                </Typography>
                <div className={classes.rail}>
                  <div className={`${classes.dot} ${drive ? classes.dotDrive : classes.dotStop}`}>
                    {drive ? (
                      <DirectionsCarIcon fontSize="small" />
                    ) : (
                      <LocalParkingIcon fontSize="small" />
                    )}
                  </div>
                  {index < items.length - 1 && <div className={classes.line} />}
                </div>
                <div
                  className={`${classes.card}${drive ? ` ${classes.cardDrive}` : ''}`}
                  onClick={() =>
                    drive &&
                    navigate(
                      `/replay?deviceId=${deviceId}&from=${encodeURIComponent(item.startTime)}&to=${encodeURIComponent(item.endTime)}`,
                    )
                  }
                >
                  <div className={classes.facts}>
                    <span className={classes.fact}>
                      <ScheduleIcon fontSize="inherit" color="action" />
                      {duration(item.duration)}
                    </span>
                    {drive && (
                      <>
                        <span className={classes.fact}>
                          <RouteIcon fontSize="inherit" color="warning" />
                          {formatDistance(item.distance, distanceUnit, t)}
                        </span>
                        <span className={classes.fact}>
                          <SpeedIcon fontSize="inherit" color="error" />
                          {formatSpeed(item.maxSpeed, speedUnit, t)}
                        </span>
                      </>
                    )}
                    {drive && <span className={classes.replay}>Replay ›</span>}
                  </div>
                  {(drive ? item.startAddress : item.address) && (
                    <Typography variant="body2" color="text.secondary" className={classes.address}>
                      {drive ? item.startAddress : item.address}
                    </Typography>
                  )}
                </div>
              </div>
            );
          })}
      </div>
    </div>
  );
};

export default JourneysPage;
