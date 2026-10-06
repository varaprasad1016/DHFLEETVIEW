import { formatShortSpeed } from './formatter';

/**
 * Vehicle status derived strictly from ignition parameter.
 * - DVR / CNMS: standard `ignition` attribute (existing, unchanged)
 * - Teltonika FMC650: `ignition` (io239) + fallback keys (io239, io1, di1, acc, ign …)
 *   Device-specific override: device.attributes.ignitionKey or device.attributes.teltonikaIgnitionKey
 *
 * Statuses:
 *   running - ignition ON + moving (speed >= threshold)
 *   idling  - ignition ON + stationary
 *   parked  - ignition OFF (also exposed as "stopped" for UI)
 *   stopped - alias of parked
 *   nofix   - still reporting, but with no satellite fix: the coordinate is the
 *             last one it managed and the speed is unknown rather than zero
 *   offline - device offline/unknown or no position
 */

export const SPEED_THRESHOLD_KTS = 3; // ~5.5 km/h, matches existing FleetDashboard threshold

const IGNITION_FALLBACK_KEYS = [
  'ignition',
  'ign',
  'io239',
  'io1',
  'di1',
  'din1',
  'acc',
  'engineIgnition',
  'power',
];

const normalizeBoolean = (value) => {
  if (value === true || value === 1 || value === '1') return true;
  if (value === false || value === 0 || value === '0') return false;
  if (typeof value === 'string') {
    const v = value.trim().toLowerCase();
    if (['true', 'yes', 'on', '1'].includes(v)) return true;
    if (['false', 'no', 'off', '0'].includes(v)) return false;
  }
  if (typeof value === 'number') return value !== 0;
  return null;
};

/**
 * Resolve ignition boolean from position attributes.
 * @param {object} position - traccar position with attributes
 * @param {object} device - optional device for per-device override key
 * @returns {boolean|null} true/false or null if unknown
 */
export const getIgnition = (position, device = null) => {
  if (!position?.attributes) return null;

  const attrs = position.attributes;

  // Per-device override: allow custom ignition attribute key (e.g. Teltonika specific IO)
  // device.attributes.ignitionKey / teltonikaIgnitionKey / ignitionAttribute
  const customKey =
    device?.attributes?.ignitionKey ||
    device?.attributes?.teltonikaIgnitionKey ||
    device?.attributes?.ignitionAttribute ||
    device?.attributes?.ignitionSource;
  if (customKey && attrs.hasOwnProperty(customKey)) {
    const v = normalizeBoolean(attrs[customKey]);
    if (v !== null) return v;
  }

  // Standard ordered fallback – first matching key wins
  for (const key of IGNITION_FALLBACK_KEYS) {
    if (attrs.hasOwnProperty(key)) {
      const v = normalizeBoolean(attrs[key]);
      if (v !== null) return v;
    }
  }

  // Also support raw Teltonika IO prefix with string number (e.g. "239")
  // Some configs expose IO as "io239" already covered; also check numeric IO keys like "239"
  if (attrs.hasOwnProperty('239')) {
    const v = normalizeBoolean(attrs['239']);
    if (v !== null) return v;
  }

  return null;
};

export const isIgnitionOn = (position, device) => getIgnition(position, device) === true;
export const isIgnitionOff = (position, device) => getIgnition(position, device) === false;

/**
 * Whether the position is an actual satellite fix.
 *
 * A tracker with no fix still reports: it sends its last known coordinate with
 * speed zero and the fix flagged invalid. Believing that is how a lorry doing
 * 50 on the motorway shows as sitting still — the coordinate is real, it is
 * just hours old, and the zero speed means "not known" rather than "stopped".
 */
export const hasFix = (position) => position?.valid !== false;

/**
 * Derive vehicle status from ignition, speed and whether the fix is real.
 * DVR behaviour is preserved: it already reports ignition, so same path.
 * @returns {'running'|'idling'|'parked'|'nofix'|'offline'}
 */
export const getVehicleStatus = (device, position) => {
  if (!device) return 'offline';
  // offline if no position or device marked offline
  if (!position) return 'offline';
  if (device.status === 'offline' || device.status === 'unknown') {
    // Still treat as offline regardless of last ignition – matches existing offline card logic
    return 'offline';
  }

  const ignition = getIgnition(position, device);
  const speed = typeof position.speed === 'number' ? position.speed : 0;

  // Without a fix the speed is unknown, not zero, so neither "running" nor
  // "idling" can be claimed. Say what is actually true instead.
  if (!hasFix(position)) return 'nofix';

  if (ignition === true) {
    return speed >= SPEED_THRESHOLD_KTS ? 'running' : 'idling';
  }
  if (ignition === false) {
    return 'parked'; // stopped alias
  }
  // ignition unknown – fallback to motion
  return speed >= SPEED_THRESHOLD_KTS ? 'running' : 'parked';
};

/**
 * The vehicle's current speed while it is driving, e.g. "42 mph"; null when it
 * isn't (idling, parked, offline). Shared by the map labels and the vehicle list
 * so both show the same thing.
 */
export const drivingSpeed = (device, position, speedUnit, t) =>
  getVehicleStatus(device, position) === 'running'
    ? formatShortSpeed(position?.speed, speedUnit, t)
    : null;

/**
 * Normalize parked/stopped alias for filtering.
 */
export const normalizeStatus = (status) => {
  if (status === 'stopped') return 'parked';
  return status;
};

export const getStatusColor = (vehicleStatus) => {
  switch (normalizeStatus(vehicleStatus)) {
    case 'running':
      return 'success'; // green
    case 'idling':
      return 'warning'; // amber
    case 'parked':
      return 'neutral'; // gray
    case 'nofix':
      return 'warning'; // reporting, but its position cannot be trusted
    case 'offline':
      return 'error';
    default:
      return 'neutral';
  }
};

/**
 * Avatar / map icon color based on ignition (spec: gray when off, green when running).
 * @returns {'success'|'neutral'|'warning'|'error'}
 */
export const getIgnitionColor = (position, device) => {
  const ignition = getIgnition(position, device);
  if (ignition === true) return 'success';
  if (ignition === false) return 'neutral';
  // unknown – fallback to speed
  const speed = position?.speed || 0;
  return speed >= SPEED_THRESHOLD_KTS ? 'success' : 'neutral';
};

export const getIgnitionAvatarStyle = (position, device, theme) => {
  const color = getIgnitionColor(position, device);
  // green when running, gray when off – spec
  if (color === 'success') return theme.palette.success.main;
  if (color === 'warning') return theme.palette.warning.main;
  if (color === 'error') return theme.palette.error.main;
  return theme.palette.neutral.main; // gray
};

// Fleet counts helper
export const computeFleetStats = (devices, positions) => {
  const stats = { running: 0, idling: 0, parked: 0, stopped: 0, offline: 0, nofix: 0, total: 0 };
  Object.values(devices).forEach((device) => {
    const position = positions[device.id];
    const status = getVehicleStatus(device, position);
    stats.total += 1;
    if (status === 'running') stats.running += 1;
    else if (status === 'idling') stats.idling += 1;
    else if (status === 'parked') {
      stats.parked += 1;
      stats.stopped += 1;
    } else if (status === 'nofix') stats.nofix += 1;
    else if (status === 'offline') stats.offline += 1;
  });
  return stats;
};

// Filter helper for useFilter / UI
export const matchesVehicleStatusFilter = (device, position, statuses) => {
  if (!statuses || statuses.length === 0) return true;
  const normalized = statuses.map((s) => normalizeStatus(s));
  const status = getVehicleStatus(device, position);
  // stopped filter should match parked devices
  if (normalized.includes(status) || (status === 'parked' && normalized.includes('stopped')))
    return true;
  // also allow offline filter
  if (normalized.includes('offline') && status === 'offline') return true;
  // unknown status filter -> parked
  return false;
};
