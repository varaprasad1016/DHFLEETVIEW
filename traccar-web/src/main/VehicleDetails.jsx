/*
 * Copyright (c) 2026 Infomac Solutions. All rights reserved.
 * Proprietary and confidential. No licence is granted by access to this file.
 * See LICENSE in the repository root.
 */
import { useEffect, useMemo, useState } from 'react';
import { useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import { makeStyles } from 'tss-react/mui';
import { alpha } from '@mui/material/styles';
import { Chip, IconButton, Link, Typography } from '@mui/material';
import ArrowBackIcon from '@mui/icons-material/ArrowBack';
import MyLocationIcon from '@mui/icons-material/MyLocation';
import RouteIcon from '@mui/icons-material/Route';
import VideocamIcon from '@mui/icons-material/Videocam';
import HistoryIcon from '@mui/icons-material/History';
import EditIcon from '@mui/icons-material/Edit';
import PersonIcon from '@mui/icons-material/Person';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import LocalGasStationIcon from '@mui/icons-material/LocalGasStation';
import dayjs from 'dayjs';
import { map } from '../map/core/MapView';
import { toMapCoordinates } from '../map/core/mapUtil';
import useTachoLive from '../common/util/useTachoLive';
import useComplianceAccess from '../common/util/useComplianceAccess';
import { ACTIVITY, asHours, cardEnding } from '../common/util/fmc650Tacho';
import { useTranslation } from '../common/components/LocalizationProvider';
import { useAttributePreference } from '../common/util/preferences';
import { formatSpeed } from '../common/util/formatter';

/*
 * One vehicle, in the bottom half of the phone's Map view.
 *
 * Tapping a vehicle in the list used to go straight to its cameras. This is
 * what it opens instead: the driver, the tachograph, the card holder's hours,
 * where it is and whether it is moving - the things the office reads first -
 * with the cameras one tap away in the action row rather than the whole
 * destination. The map stays above it with the vehicle in view.
 *
 * Everything here is already on the phone or one request away: the position
 * and driver from the live feed, the hours from the tachograph's own figures
 * (useTachoLive), the file dates from the tacho server, the calibration from
 * the maintenance schedule. Anything that does not answer is left out rather
 * than shown as an error - a vehicle with no tachograph still has a page.
 */

const useStyles = makeStyles()((theme) => ({
  root: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    minHeight: 0,
  },
  bar: {
    display: 'flex',
    alignItems: 'center',
    gap: theme.spacing(0.5),
    padding: theme.spacing(0.5, 1, 0.5, 0.5),
    borderBottom: `1px solid ${theme.palette.divider}`,
    flexShrink: 0,
  },
  barTitle: {
    flexGrow: 1,
    textAlign: 'center',
    fontWeight: 600,
    fontSize: '0.9rem',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    // Balanced against the back button so the title sits in the middle.
    paddingRight: 40,
  },
  body: {
    overflowY: 'auto',
    padding: theme.spacing(1.5, 2, 3),
    display: 'flex',
    flexDirection: 'column',
    gap: theme.spacing(1.5),
  },
  title: {
    fontSize: '1.2rem',
    fontWeight: 600,
    lineHeight: 1.2,
  },
  chips: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: theme.spacing(0.75),
    marginTop: theme.spacing(0.75),
  },
  actions: {
    display: 'grid',
    gridTemplateColumns: 'repeat(5, 1fr)',
    gap: theme.spacing(0.5),
    padding: theme.spacing(1, 0),
    borderTop: `1px solid ${theme.palette.divider}`,
    borderBottom: `1px solid ${theme.palette.divider}`,
  },
  action: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    gap: 2,
    padding: theme.spacing(0.75, 0),
    border: 0,
    borderRadius: 10,
    background: 'none',
    color: theme.palette.text.primary,
    fontSize: '0.7rem',
    cursor: 'pointer',
    '&:disabled': { color: theme.palette.text.disabled, cursor: 'default' },
    '&:not(:disabled):active': { backgroundColor: alpha(theme.palette.primary.main, 0.12) },
  },
  section: {
    display: 'flex',
    flexDirection: 'column',
    gap: theme.spacing(0.75),
  },
  sectionHead: {
    display: 'flex',
    alignItems: 'baseline',
    justifyContent: 'space-between',
    gap: theme.spacing(1),
  },
  sectionTitle: {
    fontWeight: 600,
    fontSize: '0.95rem',
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: theme.spacing(1.25, 1.5),
  },
  value: {
    fontSize: '0.9rem',
    fontWeight: 500,
    lineHeight: 1.3,
    overflowWrap: 'anywhere',
  },
  label: {
    fontSize: '0.72rem',
    color: theme.palette.text.secondary,
    lineHeight: 1.3,
  },
  muted: {
    fontSize: '0.85rem',
    color: theme.palette.text.secondary,
  },
  holder: {
    display: 'flex',
    alignItems: 'center',
    gap: theme.spacing(1.25),
  },
  avatar: {
    width: 40,
    height: 40,
    borderRadius: '50%',
    display: 'grid',
    placeItems: 'center',
    backgroundColor: alpha(theme.palette.text.primary, 0.08),
    color: theme.palette.text.secondary,
    flexShrink: 0,
  },
  alert: {
    display: 'flex',
    alignItems: 'center',
    gap: theme.spacing(0.75),
    padding: theme.spacing(0.75, 1),
    borderRadius: 8,
    fontSize: '0.8rem',
    fontWeight: 600,
  },
  bad: {
    backgroundColor: alpha(theme.palette.error.main, 0.14),
    color: theme.palette.error.main,
  },
  warn: {
    backgroundColor: alpha(theme.palette.warning.main, 0.16),
    color: theme.palette.warning.dark,
  },
  kv: {
    display: 'grid',
    gridTemplateColumns: '88px 1fr',
    gap: theme.spacing(0.75, 1.5),
    alignItems: 'start',
  },
  coords: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: theme.spacing(0.5),
    fontVariantNumeric: 'tabular-nums',
  },
  foot: {
    fontSize: '0.72rem',
    color: theme.palette.text.secondary,
  },
}));

/* "(4d)" - how old a reading is, the way the reference app marks every value. */
const age = (iso) => {
  if (!iso) return '';
  const minutes = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 60000));
  if (minutes < 1) return '(now)';
  if (minutes < 60) return `(${minutes}m)`;
  if (minutes < 60 * 48) return `(${Math.round(minutes / 60)}h)`;
  return `(${Math.round(minutes / 1440)}d)`;
};

const cardKey = (value) => String(value || '').toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 14);

const fetchJson = async (url, signal) => {
  const response = await fetch(url, { signal, headers: { Accept: 'application/json' } });
  if (!response.ok) throw new Error(String(response.status));
  return response.json();
};

const Field = ({ label, value, when, classes }) => (
  <div>
    <Typography className={classes.value}>{value ?? '—'}</Typography>
    <Typography className={classes.label}>
      {label}
      {when ? ` ${age(when)}` : ''}
    </Typography>
  </div>
);

const VehicleDetails = ({ deviceId, position, onBack }) => {
  const { classes } = useStyles();
  const navigate = useNavigate();
  const t = useTranslation();
  const speedUnit = useAttributePreference('speedUnit');

  const device = useSelector((state) => state.devices.items[deviceId]);
  const drivers = useSelector((state) => state.drivers.items);
  const complianceAccess = useComplianceAccess();
  const live = useTachoLive(deviceId, position);

  const reg = (device?.attributes?.registration || device?.name || '').toUpperCase().replace(/\s+/g, '');
  const driverUniqueId = position?.attributes?.driverUniqueId;
  const driverName = driverUniqueId ? drivers[driverUniqueId]?.name || driverUniqueId : null;
  const online = device?.status === 'online';
  const hasCamera = Boolean(device?.attributes?.cmsv9DeviceId);
  const fuel = position?.attributes?.fuel;
  const fuelPct = typeof fuel === 'number' && fuel >= 0 && fuel <= 100 ? Math.round(fuel) : null;
  const moving = Boolean(position?.attributes?.motion);

  // The tacho server's side of the story: the last vehicle-unit file, the card
  // files, and the calibration schedule. Three small requests, each optional.
  const [files, setFiles] = useState({ vu: null, cards: [] });
  const [calibration, setCalibration] = useState(null);
  useEffect(() => {
    if (!complianceAccess || !deviceId) return undefined;
    const controller = new AbortController();
    (async () => {
      try {
        const [vu, cards] = await Promise.all([
          reg
            ? fetchJson(`/tacho/api/tacho/downloads?vehicle_ref=${encodeURIComponent(reg)}&kind=vehicle_unit&limit=1`, controller.signal)
            : { files: [] },
          fetchJson('/tacho/api/tacho/downloads?kind=driver_card&limit=200', controller.signal),
        ]);
        setFiles({ vu: vu.files?.[0] || null, cards: cards.files || [] });
      } catch {
        // no tachograph archive for this vehicle; the section says so
      }
      try {
        const detail = await fetchJson(`/tacho/api/maintenance/vehicles/${deviceId}`, controller.signal);
        const schedule = (detail.schedules || []).find((s) => s.kind === 'tacho_calibration' && s.active);
        setCalibration(schedule || null);
      } catch {
        // no maintenance schedule held
      }
    })();
    return () => controller.abort();
  }, [complianceAccess, deviceId, reg]);

  // "Stopped since 16:16" - from the server's stops report, which works the
  // stops out from the positions themselves. (Moving/stopped events are not
  // recorded for these units, so they cannot be the source.) The last stop is
  // still going if it runs up to the vehicle's latest position; otherwise the
  // vehicle has been moving since that stop ended.
  const [motion, setMotion] = useState(null);
  const fixTime = position?.fixTime;
  useEffect(() => {
    if (!deviceId) return undefined;
    const controller = new AbortController();
    (async () => {
      try {
        const to = new Date(Math.max(Date.now(), fixTime ? new Date(fixTime).getTime() : 0) + 60000);
        const from = new Date(to.getTime() - 3 * 24 * 3600 * 1000);
        const query = new URLSearchParams({ deviceId, from: from.toISOString(), to: to.toISOString() });
        const stops = await fetchJson(`/api/reports/stops?${query}`, controller.signal);
        const last = stops[stops.length - 1];
        if (!last) {
          setMotion(null);
          return;
        }
        const latest = fixTime ? new Date(fixTime).getTime() : Date.now();
        const ongoing = new Date(last.endTime).getTime() >= latest - 120000;
        setMotion(ongoing ? { state: 'Stopped', since: last.startTime } : { state: 'Moving', since: last.endTime });
      } catch {
        setMotion(null);
      }
    })();
    return () => controller.abort();
  }, [deviceId, moving, fixTime]);

  // The address. Positions arrive without one (the server does not geocode
  // every record for every vehicle), so it is asked for here, for this one
  // position, and remembered until the vehicle has moved.
  const [address, setAddress] = useState(null);
  const lat = position ? position.latitude.toFixed(4) : null;
  const lon = position ? position.longitude.toFixed(4) : null;
  useEffect(() => {
    setAddress(null);
    if (!position || position.address || !lat) return undefined;
    const controller = new AbortController();
    (async () => {
      try {
        const response = await fetch(
          `/api/server/geocode?latitude=${position.latitude}&longitude=${position.longitude}`,
          { signal: controller.signal },
        );
        if (response.ok && response.status !== 204) setAddress((await response.text()) || null);
      } catch {
        // no geocoder, or no answer; the coordinates below still say where it is
      }
    })();
    return () => controller.abort();
    // lat/lon rounded to ~10 m: a parked vehicle's jitter must not re-ask
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deviceId, lat, lon]);

  const locate = () => {
    if (!position) return;
    map.easeTo({
      center: toMapCoordinates(position.longitude, position.latitude),
      zoom: Math.max(map.getZoom(), 15),
    });
  };

  const copyCoords = async () => {
    if (!position) return;
    try {
      await navigator.clipboard.writeText(`${position.latitude.toFixed(6)}, ${position.longitude.toFixed(6)}`);
    } catch {
      // clipboard refused (insecure context, or permission); nothing else to do
    }
  };

  // The tachograph's own view of the vehicle: what it is recording right now.
  const slots = live.slots || [];
  const first = slots[0] || null;
  const activityLabel = useMemo(() => {
    if (!live.hasData) return null;
    if (live.stale) return 'Tachograph asleep';
    const active = slots.find((s) => s.activity);
    return active ? ACTIVITY[active.activity]?.label || active.activity : 'Tachograph awake';
  }, [live.hasData, live.stale, slots]);

  const cardFileFor = (slot) => {
    if (!slot) return null;
    const key = cardKey(slot.cardNumber);
    return (
      files.cards.find((f) => key && cardKey(f.card_number) === key)
      || files.cards.find((f) => slot.cardHolder && f.driver && f.driver.toUpperCase() === slot.cardHolder.toUpperCase())
      || null
    );
  };

  const downloadType = files.vu
    ? (files.vu.source === 'listener' ? 'Remote download (TachoSync)' : 'Manual upload')
    : null;

  if (!device) return null;

  const action = (label, icon, onClick, disabled = false) => (
    <button type="button" className={classes.action} onClick={onClick} disabled={disabled}>
      {icon}
      <span>{label}</span>
    </button>
  );

  return (
    <div className={classes.root}>
      <div className={classes.bar}>
        <IconButton size="small" onClick={onBack} aria-label="Back to the list">
          <ArrowBackIcon fontSize="small" />
        </IconButton>
        <Typography className={classes.barTitle}>{`${device.name} · Details`}</Typography>
      </div>
      <div className={classes.body}>
        <div>
          <Typography className={classes.title}>{device.name}</Typography>
          <div className={classes.chips}>
            <Chip size="small" label={online ? (moving ? 'Moving' : 'Stopped') : 'Offline'} color={online ? (moving ? 'success' : 'default') : 'error'} variant="outlined" />
            {device.category && <Chip size="small" label={device.category} variant="outlined" />}
            {hasCamera && <Chip size="small" label={`${device.attributes?.cmsv9Channels || 4} cameras`} variant="outlined" />}
            {fuelPct !== null && <Chip size="small" icon={<LocalGasStationIcon />} label={`${fuelPct}%`} variant="outlined" />}
          </div>
        </div>

        <div className={classes.actions}>
          {action('Locate', <MyLocationIcon fontSize="small" />, locate, !position)}
          {action('Trip', <RouteIcon fontSize="small" />, () => navigate(`/replay?deviceId=${deviceId}`), !position)}
          {action('Video', <VideocamIcon fontSize="small" color={hasCamera && online ? 'primary' : 'inherit'} />, () => navigate(`/cmsv9-video?deviceId=${deviceId}`), !hasCamera)}
          {action('Journeys', <HistoryIcon fontSize="small" />, () => navigate(`/journeys?deviceId=${deviceId}`))}
          {action(t('sharedEdit'), <EditIcon fontSize="small" />, () => navigate(`/settings/device/${deviceId}`))}
        </div>

        <div className={classes.section}>
          <div className={classes.sectionHead}>
            <Typography className={classes.sectionTitle}>Driver</Typography>
            <Link component="button" variant="body2" onClick={() => navigate(`/settings/device/${deviceId}/connections`)}>
              Assign driver
            </Link>
          </div>
          <Typography className={driverName ? classes.value : classes.muted}>
            {driverName || 'No driver assigned'}
          </Typography>
        </div>

        <div className={classes.section}>
          <Typography className={classes.sectionTitle}>Tachograph</Typography>
          {live.noCardDriving && (
            <div className={`${classes.alert} ${classes.bad}`}>
              <WarningAmberIcon sx={{ fontSize: 16 }} />
              <span>Being driven without a driver card</span>
            </div>
          )}
          {!live.hasData && !files.vu && !calibration ? (
            <Typography className={classes.muted}>
              {complianceAccess
                ? 'No tachograph data from this vehicle yet.'
                : 'Tachograph data is part of the compliance module.'}
            </Typography>
          ) : (
            <div className={classes.grid}>
              <Field classes={classes} label="Tachograph activity" value={activityLabel} when={live.recordedAt} />
              <Field classes={classes} label="Download type" value={downloadType} when={files.vu?.created_at} />
              <Field
                classes={classes}
                label="Latest file record"
                value={files.vu ? dayjs(files.vu.created_at).format('YYYY/MM/DD') : null}
                when={files.vu?.created_at}
              />
              <Field
                classes={classes}
                label="Tachograph next calibration"
                value={calibration?.next_due ? dayjs(calibration.next_due).format('YYYY/MM/DD') : null}
              />
              {live.vehicle?.vin && <Field classes={classes} label="VIN" value={live.vehicle.vin} />}
              {live.vehicle?.tachoSpeed !== undefined && live.vehicle?.tachoSpeed !== null && (
                <Field classes={classes} label="Tachograph speed" value={`${live.vehicle.tachoSpeed} km/h`} when={live.recordedAt} />
              )}
            </div>
          )}
        </div>

        {slots.filter((s) => s.cardHolder || s.cardNumber || s.cardPresent).map((slot) => {
          const f = slot.figures;
          const activity = slot.activity ? ACTIVITY[slot.activity] : null;
          const file = cardFileFor(slot);
          return (
            <div className={classes.section} key={slot.slot}>
              <div className={classes.holder}>
                <div className={classes.avatar}><PersonIcon /></div>
                <div style={{ minWidth: 0 }}>
                  <Typography className={classes.value} style={{ fontWeight: 600, fontSize: '1rem' }}>
                    {slot.cardHolder || (slot.cardNumber ? `Card ${cardEnding(slot.cardNumber)}` : `Driver ${slot.slot} card`)}
                  </Typography>
                  <Typography className={classes.label}>
                    {live.recordedAt ? `Updated on ${dayjs(live.recordedAt).format('YYYY/MM/DD HH:mm')}` : 'Not reported yet'}
                    {slots.length > 1 ? ` · slot ${slot.slot}` : ''}
                  </Typography>
                </div>
              </div>
              {activity && (
                <Chip
                  size="small"
                  label={slot.minutesInActivity !== null ? `${activity.label} for ${asHours(slot.minutesInActivity)}` : activity.label}
                  sx={{ alignSelf: 'flex-start', color: '#fff', backgroundColor: activity.color, fontWeight: 600 }}
                />
              )}
              {slot.warning && (
                <div className={`${classes.alert} ${slot.warning.level === 'bad' ? classes.bad : classes.warn}`}>
                  <WarningAmberIcon sx={{ fontSize: 16 }} />
                  <span>{slot.warning.label}</span>
                </div>
              )}
              {f ? (
                <div className={classes.grid}>
                  <Field classes={classes} label="Continuous driving time" value={asHours(f.continuousDriving)} when={live.recordedAt} />
                  <Field classes={classes} label="Pending break time" value={asHours(f.nextBreakDuration ?? f.remainingCurrentBreak)} when={live.recordedAt} />
                  <Field classes={classes} label="Working day driving" value={asHours(f.dailyDriving)} when={live.recordedAt} />
                  <Field classes={classes} label="Weekly driving time" value={asHours(f.weeklyDriving)} when={live.recordedAt} />
                  <Field classes={classes} label="Driving until break" value={asHours(f.drivingUntilBreak)} />
                  <Field classes={classes} label="Driving left today" value={asHours(f.drivingLeftToday)} />
                  <Field classes={classes} label="Driving left this week" value={asHours(f.drivingLeftWeek)} />
                  <Field classes={classes} label="Two-week driving" value={asHours(f.twoWeekDriving)} />
                  <Field classes={classes} label="Until daily rest" value={asHours(f.untilDailyRest)} />
                  <Field
                    classes={classes}
                    label="Driver latest file record"
                    value={file ? dayjs(file.created_at).format('YYYY/MM/DD') : null}
                    when={file?.created_at}
                  />
                </div>
              ) : (
                <Typography className={classes.muted}>No driving-time figures reported for this card yet.</Typography>
              )}
            </div>
          );
        })}

        <div className={classes.section}>
          <div className={classes.kv}>
            <Typography className={classes.label} style={{ paddingTop: 2 }}>Location</Typography>
            <div>
              <Typography className={classes.value}>
                {position?.address || address || (position ? 'Looking up the address…' : 'No position yet')}
              </Typography>
              {position && (
                <Typography className={`${classes.muted} ${classes.coords}`}>
                  {`${position.latitude.toFixed(6)}, ${position.longitude.toFixed(6)}`}
                  <IconButton size="small" onClick={copyCoords} aria-label="Copy coordinates">
                    <ContentCopyIcon sx={{ fontSize: 14 }} />
                  </IconButton>
                </Typography>
              )}
            </div>
            <Typography className={classes.label} style={{ paddingTop: 2 }}>Status</Typography>
            <Typography className={classes.value}>
              {!online && `Offline${device.lastUpdate ? ` since ${dayjs(device.lastUpdate).format('DD/MM/YY HH:mm:ss')}` : ''}`}
              {online && motion && `${motion.state} since ${dayjs(motion.since).format('DD/MM/YY HH:mm:ss')}`}
              {online && !motion && (moving ? 'Moving' : 'Stopped')}
              {online && moving && position?.speed > 0 ? ` · ${formatSpeed(position.speed, speedUnit, t)}` : ''}
            </Typography>
          </div>
        </div>

        {position?.fixTime && (
          <Typography className={classes.foot}>
            {`Position reported ${dayjs(position.fixTime).format('DD/MM/YY HH:mm:ss')}`}
          </Typography>
        )}
      </div>
    </div>
  );
};

export default VehicleDetails;
