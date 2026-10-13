import { useMemo } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import { makeStyles } from 'tss-react/mui';
import { alpha } from '@mui/material/styles';
import {
  IconButton,
  Tooltip,
  Avatar,
  ListItemAvatar,
  ListItemText,
  ListItemButton,
  Typography,
} from '@mui/material';
import BatteryFullIcon from '@mui/icons-material/BatteryFull';
import BatteryChargingFullIcon from '@mui/icons-material/BatteryChargingFull';
import Battery60Icon from '@mui/icons-material/Battery60';
import BatteryCharging60Icon from '@mui/icons-material/BatteryCharging60';
import Battery20Icon from '@mui/icons-material/Battery20';
import BatteryCharging20Icon from '@mui/icons-material/BatteryCharging20';
import ErrorIcon from '@mui/icons-material/Error';
import dayjs from 'dayjs';
import relativeTime from 'dayjs/plugin/relativeTime';
import { devicesActions } from '../store';
import VideocamIcon from '@mui/icons-material/Videocam';
import PlaceIcon from '@mui/icons-material/Place';
import SpeedIcon from '@mui/icons-material/Speed';
import {
  formatAlarm,
  formatBoolean,
  formatDistance,
  formatPercentage,
} from '../common/util/formatter';
import { useTranslation } from '../common/components/LocalizationProvider';
import { mapIconKey, mapIcons } from '../map/core/preloadImages';
import { useAdministrator } from '../common/util/permissions';
import EngineIcon from '../resources/images/data/engine.svg?react';
import { useAttributePreference } from '../common/util/preferences';
import GeofencesValue from '../common/components/GeofencesValue';
import DriverValue from '../common/components/DriverValue';
import MotionBar from './components/MotionBar';
import { slotReading } from '../common/util/fmc650Tacho';
import {
  drivingSpeed,
  getIgnition,
  getVehicleStatus,
  getStatusColor as getVehicleStatusColor,
} from '../common/util/vehicleStatus';

dayjs.extend(relativeTime);

const useStyles = makeStyles()((theme) => ({
  icon: {
    width: '22px',
    height: '22px',
    filter: 'brightness(0) invert(1)',
  },
  avatar: {
    borderRadius: 10,
  },
  // The registration drawn as the plate on the front of the lorry: the same
  // yellow, the blue band, and a condensed face standing in for Charles
  // Wright. A fleet is recognised by its plates, so the list reads the way the
  // yard does. Fixed colours on purpose - a number plate is yellow and black in
  // either theme.
  primaryRow: {
    display: 'flex',
    alignItems: 'center',
    gap: theme.spacing(1),
    minWidth: 0,
  },
  plate: {
    display: 'inline-flex',
    alignItems: 'stretch',
    flexShrink: 0,
    borderRadius: 4,
    overflow: 'hidden',
    border: '1px solid #0f1115',
    backgroundColor: '#f5cd2f',
    boxShadow: '0 1px 2px rgba(0, 0, 0, 0.3)',
    lineHeight: 1,
  },
  plateBand: {
    display: 'flex',
    alignItems: 'flex-end',
    justifyContent: 'center',
    backgroundColor: '#15489f',
    color: '#ffffff',
    fontSize: '0.5rem',
    fontWeight: 700,
    letterSpacing: '0.02em',
    padding: '3px 3px 2px',
    minWidth: 15,
  },
  plateText: {
    color: '#0f1115',
    fontWeight: 700,
    fontSize: '0.95rem',
    letterSpacing: '0.09em',
    padding: '3px 7px 2px',
    whiteSpace: 'nowrap',
    fontFamily: "'Arial Narrow', 'Helvetica Neue', Arial, sans-serif",
  },
  plainName: {
    fontWeight: 600,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  driverName: {
    fontSize: '0.78rem',
    fontWeight: 600,
    color: theme.palette.text.secondary,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    minWidth: 0,
  },
  avatarRunning: {
    backgroundColor: theme.palette.success.main,
  },
  avatarIdling: {
    backgroundColor: theme.palette.warning.main,
  },
  avatarParked: {
    backgroundColor: theme.palette.neutral.main,
  },
  avatarStopped: {
    backgroundColor: theme.palette.neutral.main,
  },
  avatarOffline: {
    backgroundColor: alpha(theme.palette.neutral.main, 0.7),
  },
  avatarDefault: {
    backgroundColor: theme.palette.mode === 'light' ? theme.palette.primary.main : '#4338ca',
  },
  batteryText: {
    fontSize: '0.75rem',
    fontWeight: 'normal',
    lineHeight: '0.875rem',
  },
  success: {
    color: theme.palette.success.main,
  },
  warning: {
    color: theme.palette.warning.main,
  },
  error: {
    color: theme.palette.error.main,
  },
  neutral: {
    color: theme.palette.neutral.main,
  },
  railRunning: {
    borderLeft: `4px solid ${theme.palette.success.main}`,
  },
  railIdling: {
    borderLeft: `4px solid ${theme.palette.warning.main}`,
  },
  railParked: {
    borderLeft: `4px solid ${theme.palette.neutral.main}`,
  },
  railOffline: {
    borderLeft: `4px solid ${theme.palette.error.main}`,
  },
  railDefault: {
    borderLeft: '4px solid transparent',
  },
  inlineIcon: {
    fontSize: '0.85rem',
    verticalAlign: '-2px',
    marginLeft: 3,
    marginRight: 2,
  },
  details: {
    display: 'block',
    fontSize: '0.72rem',
    color: theme.palette.text.secondary,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  detail: {
    whiteSpace: 'nowrap',
  },
  place: {
    whiteSpace: 'nowrap',
  },
  selected: {
    backgroundColor: alpha(theme.palette.primary.main, 0.08),
    '&:hover': {
      backgroundColor: alpha(theme.palette.primary.main, 0.12),
    },
  },
}));

/*
 * A name that is a vehicle registration, rather than a label somebody typed.
 * Plate styling belongs on the former and would look wrong on the latter -
 * "To Be Installed" is not a number plate.
 */
const looksLikeReg = (value) => {
  const text = (value || '').replace(/\s+/g, '');
  return /^[A-Z0-9]{5,8}$/.test(text) && /[A-Z]/.test(text) && /[0-9]/.test(text);
};

const DeviceRow = ({ devices, index, style, tacho }) => {
  const { classes } = useStyles();
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const t = useTranslation();

  const admin = useAdministrator();
  const selectedDeviceId = useSelector((state) => state.devices.selectedId);

  const item = devices[index];
  const position = useSelector((state) => state.session.positions[item.id]);

  const devicePrimary = useAttributePreference('devicePrimary', 'name');
  const deviceSecondary = useAttributePreference('deviceSecondary', '');
  const speedUnit = useAttributePreference('speedUnit', 'mph');
  const distanceUnit = useAttributePreference('distanceUnit', 'mi');

  const resolveFieldValue = (field) => {
    if (field === 'geofenceIds') {
      const geofenceIds = position?.geofenceIds;
      return geofenceIds?.length ? <GeofencesValue geofenceIds={geofenceIds} /> : null;
    }
    if (field === 'driverUniqueId') {
      const driverUniqueId = position?.attributes?.driverUniqueId;
      return driverUniqueId ? <DriverValue driverUniqueId={driverUniqueId} /> : null;
    }
    if (field === 'motion') {
      return <MotionBar deviceId={item.id} />;
    }
    return item[field];
  };

  const primaryValue = resolveFieldValue(devicePrimary);
  const secondaryValue = resolveFieldValue(deviceSecondary);

  // Ignition-based vehicle status (DVR unchanged, Teltonika via fallback)
  const ignition = getIgnition(position, item);
  const vehicleStatus = getVehicleStatus(item, position);
  const avatarClass = (() => {
    if (vehicleStatus === 'running') return classes.avatarRunning;
    if (vehicleStatus === 'idling') return classes.avatarIdling;
    if (vehicleStatus === 'parked') return classes.avatarParked;
    if (vehicleStatus === 'offline') return classes.avatarOffline;
    return classes.avatarDefault;
  })();
  const railClass = (() => {
    if (vehicleStatus === 'running') return classes.railRunning;
    if (vehicleStatus === 'idling') return classes.railIdling;
    if (vehicleStatus === 'parked' || vehicleStatus === 'stopped') return classes.railParked;
    if (vehicleStatus === 'offline') return classes.railOffline;
    return classes.railDefault;
  })();
  // Icon library: selectable category icons (mapIcons) are shown in avatar; color by ignition
  // Gray when ignition off (parked/stopped/offline), green when running (spec)
  const vehicleStatusLabel = vehicleStatus.charAt(0).toUpperCase() + vehicleStatus.slice(1);
  // Live speed, shown only while the vehicle is actually driving.
  const speed = drivingSpeed(item, position, speedUnit, t);
  // Where it is and how far it has been: the two things a transport manager
  // looks for next to the status. The DVR supplies its own address string when
  // the server-side geocoder hasn't filled one in.
  const odometer = position?.attributes?.totalDistance;
  const place = position?.address || position?.attributes?.cnmsAddress;
  const driverUniqueId = position?.attributes?.driverUniqueId;
  const hasCamera = Boolean(item.attributes?.cmsv9DeviceId);
  const lastUpdate = item.lastUpdate ? dayjs(item.lastUpdate).fromNow() : null;

  // Who is in the driver's seat, from the vehicle's own tachograph. The list
  // fetches this for every vehicle at once (see DeviceList); a vehicle without
  // a tachograph simply has nothing here.
  const driverName = useMemo(() => {
    const attributes = tacho?.[item.id]?.attributes;
    if (!attributes) return null;
    const reading = slotReading(attributes, 1);
    return reading.cardHolder || null;
  }, [tacho, item.id]);

  const secondaryText = () => {
    // Single source of truth for status: the operational vehicle status. The
    // separate connection Online/Offline was removed because the two could
    // disagree (e.g. "Online • OFFLINE") and flicker on first load.
    return (
      <>
        {secondaryValue && (
          <>
            {secondaryValue}
            {' • '}
          </>
        )}
        <Tooltip
          title={`Ignition: ${ignition === true ? 'ON' : ignition === false ? 'OFF' : 'unknown'} – ${vehicleStatusLabel}`}
        >
          <span
            className={classes[getVehicleStatusColor(vehicleStatus)]}
            style={{ fontWeight: 600, fontSize: '0.7rem', textTransform: 'uppercase' }}
          >
            {vehicleStatusLabel}
          </span>
        </Tooltip>
        {speed && (
          <span className={classes.success} style={{ fontWeight: 600 }}>
            {' • '}
            {speed}
          </span>
        )}
        {lastUpdate && (
          <span className={classes.neutral}>
            {' • '}
            {lastUpdate}
          </span>
        )}
        {driverUniqueId && (
          <>
            {' • '}
            <DriverValue driverUniqueId={driverUniqueId} />
          </>
        )}
        {hasCamera && <VideocamIcon className={classes.inlineIcon} />}
      </>
    );
  };

  // Second line: odometer and the address, which is what the vehicle list is
  // actually used for day to day.
  const detailText = () => (
    <span className={classes.details}>
      {odometer > 0 && (
        <span className={classes.detail}>
          <SpeedIcon className={classes.inlineIcon} />
          {formatDistance(odometer, distanceUnit, t)}
        </span>
      )}
      {place && (
        <span className={`${classes.detail} ${classes.place}`}>
          <PlaceIcon className={classes.inlineIcon} />
          {place}
        </span>
      )}
    </span>
  );

  /**
   * One tap from the list to the cameras. The video page carries the map
   * beside the channels, so the position comes with it and nothing is lost by
   * not going to the map first.
   *
   * A vehicle with no camera has nowhere to go, so it falls back to selecting
   * it, which is what every row used to do. The device is selected either way,
   * so coming back from the video leaves the right vehicle highlighted.
   */
  const openVehicle = () => {
    dispatch(devicesActions.selectId(item.id));
    if (hasCamera) {
      navigate(`/cmsv9-video?deviceId=${item.id}`);
    }
  };

  return (
    <div style={style}>
      <ListItemButton
        key={item.id}
        onClick={openVehicle}
        disabled={!admin && item.disabled}
        selected={selectedDeviceId === item.id}
        className={`${railClass} ${selectedDeviceId === item.id ? classes.selected : ''}`}
      >
        <ListItemAvatar>
          <Tooltip
            title={`${vehicleStatusLabel} — ${item.category || 'default'} icon (${ignition === true ? 'ignition ON' : ignition === false ? 'ignition OFF' : 'ignition unknown'}${vehicleStatus === 'offline' ? ', when last heard from' : ''})`}
          >
            <Avatar className={`${classes.avatar} ${avatarClass}`}>
              <img className={classes.icon} src={mapIcons[mapIconKey(item.category)]} alt="" />
            </Avatar>
          </Tooltip>
        </ListItemAvatar>
        <ListItemText
          primary={(
            <span className={classes.primaryRow}>
              {looksLikeReg(primaryValue) ? (
                <span className={classes.plate} title={primaryValue}>
                  <span className={classes.plateBand}>UK</span>
                  <span className={classes.plateText}>{primaryValue}</span>
                </span>
              ) : (
                <span className={classes.plainName}>{primaryValue}</span>
              )}
              {driverName && <span className={classes.driverName}>{driverName}</span>}
            </span>
          )}
          secondary={
            <>
              {secondaryText()}
              {detailText()}
            </>
          }
          slots={{
            primary: Typography,
            secondary: Typography,
          }}
          slotProps={{
            primary: { noWrap: true },
            secondary: { noWrap: true, component: 'span' },
          }}
        />
        {position && (
          <>
            {position.attributes.hasOwnProperty('alarm') && (
              <Tooltip title={`${t('eventAlarm')}: ${formatAlarm(position.attributes.alarm, t)}`}>
                <IconButton size="small">
                  <ErrorIcon fontSize="small" className={classes.error} />
                </IconButton>
              </Tooltip>
            )}
            {/* Ignition is the last thing the vehicle told us, not a live reading:
                it stays as it was when the unit stopped reporting. A vehicle that
                went quiet with the engine running kept a green engine here next to
                the word OFFLINE, which reads as a contradiction. Offline, it is
                shown grey and the tooltip says the state is the last known one. */}
            {ignition !== null && (
              <Tooltip
                title={
                  vehicleStatus === 'offline'
                    ? `${t('positionIgnition')}: ${formatBoolean(ignition, t)} when last heard from (${vehicleStatusLabel})`
                    : `${t('positionIgnition')}: ${formatBoolean(ignition, t)} (${vehicleStatusLabel})`
                }
              >
                <IconButton size="small">
                  <EngineIcon
                    width={20}
                    height={20}
                    className={
                      ignition && vehicleStatus !== 'offline' ? classes.success : classes.neutral
                    }
                  />
                </IconButton>
              </Tooltip>
            )}
            {position.attributes.hasOwnProperty('batteryLevel') && (
              <Tooltip
                title={`${t('positionBatteryLevel')}: ${formatPercentage(position.attributes.batteryLevel)}`}
              >
                <IconButton size="small">
                  {(position.attributes.batteryLevel > 70 &&
                    (position.attributes.charge ? (
                      <BatteryChargingFullIcon fontSize="small" className={classes.success} />
                    ) : (
                      <BatteryFullIcon fontSize="small" className={classes.success} />
                    ))) ||
                    (position.attributes.batteryLevel > 30 &&
                      (position.attributes.charge ? (
                        <BatteryCharging60Icon fontSize="small" className={classes.warning} />
                      ) : (
                        <Battery60Icon fontSize="small" className={classes.warning} />
                      ))) ||
                    (position.attributes.charge ? (
                      <BatteryCharging20Icon fontSize="small" className={classes.error} />
                    ) : (
                      <Battery20Icon fontSize="small" className={classes.error} />
                    ))}
                </IconButton>
              </Tooltip>
            )}
          </>
        )}
      </ListItemButton>
    </div>
  );
};

export default DeviceRow;
