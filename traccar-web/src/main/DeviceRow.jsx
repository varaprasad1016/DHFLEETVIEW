import { useDispatch, useSelector } from 'react-redux';
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
import {
  formatAlarm,
  formatBoolean,
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
import { getIgnition, getVehicleStatus, getStatusColor as getVehicleStatusColor } from '../common/util/vehicleStatus';

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
  selected: {
    backgroundColor: alpha(theme.palette.primary.main, 0.08),
    '&:hover': {
      backgroundColor: alpha(theme.palette.primary.main, 0.12),
    },
  },
}));

const DeviceRow = ({ devices, index, style }) => {
  const { classes } = useStyles();
  const dispatch = useDispatch();
  const t = useTranslation();

  const admin = useAdministrator();
  const selectedDeviceId = useSelector((state) => state.devices.selectedId);

  const item = devices[index];
  const position = useSelector((state) => state.session.positions[item.id]);

  const devicePrimary = useAttributePreference('devicePrimary', 'name');
  const deviceSecondary = useAttributePreference('deviceSecondary', '');

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

  const secondaryText = () => {
    // Single source of truth for status: the operational vehicle status. The
    // separate connection Online/Offline was removed because the two could
    // disagree (e.g. "Online • OFFLINE") and flicker on first load.
    const lastSeen = item.lastUpdate ? dayjs(item.lastUpdate).fromNow() : null;
    return (
      <>
        {secondaryValue && (
          <>
            {secondaryValue}
            {' • '}
          </>
        )}
        <Tooltip title={`Ignition: ${ignition === true ? 'ON' : ignition === false ? 'OFF' : 'unknown'} – ${vehicleStatusLabel}`}>
          <span className={classes[getVehicleStatusColor(vehicleStatus)]} style={{ fontWeight: 600, fontSize: '0.7rem', textTransform: 'uppercase' }}>
            {vehicleStatusLabel}
          </span>
        </Tooltip>
        {vehicleStatus === 'offline' && lastSeen && (
          <span className={classes.neutral}>
            {' • '}
            {lastSeen}
          </span>
        )}
      </>
    );
  };

  return (
    <div style={style}>
      <ListItemButton
        key={item.id}
        onClick={() => dispatch(devicesActions.selectId(item.id))}
        disabled={!admin && item.disabled}
        selected={selectedDeviceId === item.id}
        className={`${railClass} ${selectedDeviceId === item.id ? classes.selected : ''}`}
      >
        <ListItemAvatar>
          <Tooltip title={`${vehicleStatusLabel} — ${item.category || 'default'} icon (${ignition === true ? 'ignition ON → green' : ignition === false ? 'ignition OFF → gray' : 'unknown'})`}>
            <Avatar className={`${classes.avatar} ${avatarClass}`}>
              <img className={classes.icon} src={mapIcons[mapIconKey(item.category)]} alt="" />
            </Avatar>
          </Tooltip>
        </ListItemAvatar>
        <ListItemText
          primary={primaryValue}
          secondary={secondaryText()}
          slots={{
            primary: Typography,
            secondary: Typography,
          }}
          slotProps={{
            primary: { noWrap: true },
            secondary: { noWrap: true },
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
            {(ignition !== null) && (
              <Tooltip
                title={`${t('positionIgnition')}: ${formatBoolean(ignition, t)} (${vehicleStatusLabel})`}
              >
                <IconButton size="small">
                  {ignition ? (
                    <EngineIcon width={20} height={20} className={classes.success} />
                  ) : (
                    <EngineIcon width={20} height={20} className={classes.neutral} />
                  )}
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
