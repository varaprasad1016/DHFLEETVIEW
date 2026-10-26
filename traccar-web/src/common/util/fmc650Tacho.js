/*
 * Copyright (c) 2026 Infomac Solutions. All rights reserved.
 * Proprietary and confidential. No licence is granted by access to this file.
 * See LICENSE in the repository root.
 */
/*
 * Tachograph data an FMC650 sends alongside its positions.
 *
 * The server stores IO elements it has no name for as position attributes
 * called io<AVL ID>, so tachograph values arrive as io184, io10507 and so on.
 * The IDs and encodings are Teltonika's: "FMC650 Teltonika Data Sending
 * Parameters ID" (tachograph data elements) and "How to read Driver ID".
 *
 * This is the same mapping the tacho server ingests with
 * (tachograph-server app/services/fmc650.py). The AVL IDs in the two must
 * agree - change them together.
 *
 * The tachograph sends a value when it changes, not on every record, so one
 * position carries only what moved. Readings are merged into the last known
 * state by useTachoLive; nothing here keeps state.
 */

// Driver 1 / 2 working state (AVL 184 / 185). 6 is error, 7 not available.
export const WORKING_STATES = { 0: 'rest', 1: 'available', 2: 'work', 3: 'drive' };

export const ACTIVITY = {
  drive: { label: 'Driving', color: '#16a34a' },
  work: { label: 'Other work', color: '#f59e0b' },
  available: { label: 'Available', color: '#0ea5e9' },
  rest: { label: 'Rest', color: '#64748b' },
};

// Driver 1 / 2 time related states (AVL 189 / 190): what the tachograph is
// warning the driver about. Even codes are a limit already reached.
export const TIME_STATES = {
  1: { label: '15 min before 4h30 driving', level: 'warn' },
  2: { label: '4h30 driving reached — break due', level: 'bad' },
  3: { label: '15 min before 9h daily driving', level: 'warn' },
  4: { label: '9h daily driving reached', level: 'bad' },
  5: { label: '15 min before 16h', level: 'warn' },
  6: { label: '16h reached', level: 'bad' },
  7: { label: 'Weekly driving time pre-warning', level: 'warn' },
  8: { label: 'Weekly driving limit reached', level: 'bad' },
  9: { label: 'Two-week driving time pre-warning', level: 'warn' },
  10: { label: 'Two-week driving limit reached', level: 'bad' },
  11: { label: 'Driver card expiry warning', level: 'warn' },
  12: { label: 'Driver card download due', level: 'warn' },
};

// field -> [driver 1 AVL ID, driver 2 AVL ID]; null where Teltonika has no
// driver 2 element. Minutes throughout; 0xFFFF means "not available".
const MINUTES = {
  continuousDriving: [56, 57],
  cumulativeBreak: [58, 59],
  activityDuration: [60, 61],
  twoWeekDriving: [69, 77],
  dailyDriving: [10507, 10514],
  weeklyDriving: [10508, 10515],
  untilDailyRest: [10509, 10516],
  untilWeeklyRest: [10522, 10523],
  minDailyRest: [10524, 10525],
  minWeeklyRest: [10526, 10527],
  nextBreakDuration: [10528, 10529],
  untilBreak: [10530, 10531],
  remainingCurrentDriving: [10532, null],
  remainingShiftDriving: [10533, null],
  remainingWeekDriving: [10534, null],
  remainingCurrentBreak: [10539, null],
  untilNextDriving: [10540, null],
  nextDrivingDuration: [10541, null],
};
const COUNTS = { dailyExtensionsUsed: [10510, 10517] };
const TIMESTAMPS = {
  endLastDailyRest: [10504, 10511],
  endLastWeeklyRest: [10505, 10512],
};
const SLOT_IDS = {
  workingState: [184, 185],
  cardPresent: [187, 188],
  timeState: [189, 190],
  idMsb: [195, 197],
  idLsb: [196, 198],
  firstName: [10518, 10520],
  surname: [10519, 10521],
};
// Vehicle-side elements: the tachograph's view of the vehicle, not of a driver.
const VEHICLE_IDS = {
  noCardDriving: 52,
  overspeed: 186,
  tachoSpeed: 80,
  direction: 122,
  performance: 123,
  handlingInfo: 124,
  systemEvent: 125,
  vin: 528,
};

export const DIRECTIONS = { 0: 'Forward', 1: 'Reverse', 2: 'Error', 3: null };
export const PERFORMANCE = { 0: 'Normal', 1: 'Performance analysis', 2: 'Error', 3: null };
export const PRESENCE = { 0: 'No', 1: 'Yes', 2: 'Error', 3: null };

const ALL_IDS = [
  ...Object.values(MINUTES),
  ...Object.values(COUNTS),
  ...Object.values(TIMESTAMPS),
  ...Object.values(SLOT_IDS),
]
  .flat()
  .filter((id) => id !== null)
  .concat(Object.values(VEHICLE_IDS));

const attr = (attributes, id) =>
  id === null || id === undefined ? undefined : attributes[`io${id}`];

const asInt = (value) => {
  const number = Number(value);
  return Number.isFinite(number) ? Math.trunc(number) : null;
};

export const hasTachoData = (attributes) =>
  Boolean(attributes) && ALL_IDS.some((id) => `io${id}` in attributes);

/*
 * One half of a driver card number: eight bytes of ASCII, sent mirrored.
 *
 * The catch is that the element arrives as a 64-bit integer and JSON has no
 * such thing - above 2^53 the low bytes, which are the first characters of the
 * name once reversed, come back altered. Rather than show a card number that
 * is subtly wrong, anything that cannot be represented exactly is dropped: the
 * card still reads as present and the holder's name (10518/10519, which arrive
 * as text) is the part an operator actually recognises.
 */
const mirroredAscii = (value) => {
  const number = Number(value);
  if (!Number.isFinite(number) || !Number.isSafeInteger(number)) return null;
  let rest = BigInt(number) & 0xffffffffffffffffn;
  const chars = [];
  for (let i = 0; i < 8; i += 1) {
    chars.push(String.fromCharCode(Number(rest & 0xffn))); // low byte first = mirrored
    rest >>= 8n;
  }
  return chars.join('');
};

export const driverId = (msb, lsb) => {
  const first = mirroredAscii(msb);
  const second = mirroredAscii(lsb);
  if (first === null || second === null) return null;
  const text = (first + second).replace(/\0/g, '').trim();
  if (!text || !/^[\x21-\x7e]+$/.test(text) || /^0+$/.test(text)) return null;
  return text;
};

// Driver name elements: hex, where the first byte is the ISO/IEC 8859 code page.
export const cardText = (value) => {
  if (typeof value !== 'string' || value.length < 4) return null;
  const hex = value.replace(/[^0-9a-fA-F]/g, '');
  if (hex.length < 4) return null;
  let text = '';
  for (let i = 2; i + 1 < hex.length; i += 2) {
    text += String.fromCharCode(parseInt(hex.slice(i, i + 2), 16));
  }
  text = text.replace(/\0/g, '').trim();
  return text || null;
};

const timestamp = (value) => {
  const seconds = asInt(value);
  if (!seconds || seconds >= 0xffffffff) return null;
  return new Date(seconds * 1000).toISOString();
};

/* Only the values this record carries, decoded, for driver slot 1 or 2. */
export const slotReading = (attributes, slot) => {
  const i = slot - 1;
  const out = {};
  const state = asInt(attr(attributes, SLOT_IDS.workingState[i]));
  if (state !== null) out.workingState = WORKING_STATES[state] ?? null; // null = error / not available
  const present = asInt(attr(attributes, SLOT_IDS.cardPresent[i]));
  if (present !== null) out.cardPresent = { 0: false, 1: true }[present] ?? null;
  const time = asInt(attr(attributes, SLOT_IDS.timeState[i]));
  if (time !== null) out.timeState = time;

  const msb = attr(attributes, SLOT_IDS.idMsb[i]);
  const lsb = attr(attributes, SLOT_IDS.idLsb[i]);
  if (msb !== undefined || lsb !== undefined) out.cardNumber = driverId(msb, lsb);
  // Slot 1 only: the server decodes the same pair into driverUniqueId when it
  // knows the model, which keeps working if the elements ever stop arriving raw.
  if (slot === 1 && !out.cardNumber && attributes.driverUniqueId) {
    out.cardNumber = String(attributes.driverUniqueId).trim() || null;
  }

  const first = cardText(attr(attributes, SLOT_IDS.firstName[i]));
  const last = cardText(attr(attributes, SLOT_IDS.surname[i]));
  if (first || last) out.cardHolder = [last, first].filter(Boolean).join(' ');

  Object.entries(MINUTES).forEach(([name, ids]) => {
    const value = asInt(attr(attributes, ids[i]));
    if (value !== null) out[name] = value >= 0xffff ? null : value;
  });
  Object.entries(COUNTS).forEach(([name, ids]) => {
    const value = asInt(attr(attributes, ids[i]));
    if (value !== null) out[name] = value >= 0xff ? null : value;
  });
  Object.entries(TIMESTAMPS).forEach(([name, ids]) => {
    const value = attr(attributes, ids[i]);
    if (value !== undefined) out[name] = timestamp(value);
  });
  return out;
};

/* The tachograph's view of the vehicle, from whatever this record carries. */
export const vehicleReading = (attributes) => {
  const out = {};
  const noCard = asInt(attr(attributes, VEHICLE_IDS.noCardDriving));
  if (noCard !== null) out.noCardSignal = noCard === 1;
  const overspeed = asInt(attr(attributes, VEHICLE_IDS.overspeed));
  if (overspeed !== null) out.overspeed = overspeed === 1;
  const speed = asInt(attr(attributes, VEHICLE_IDS.tachoSpeed));
  if (speed !== null) out.tachoSpeed = speed;
  const direction = asInt(attr(attributes, VEHICLE_IDS.direction));
  if (direction !== null) out.direction = DIRECTIONS[direction] ?? null;
  const performance = asInt(attr(attributes, VEHICLE_IDS.performance));
  if (performance !== null) out.performance = PERFORMANCE[performance] ?? null;
  const handling = asInt(attr(attributes, VEHICLE_IDS.handlingInfo));
  if (handling !== null) out.handlingInfo = PRESENCE[handling] ?? null;
  const event = asInt(attr(attributes, VEHICLE_IDS.systemEvent));
  if (event !== null) out.systemEvent = PRESENCE[event] ?? null;
  const vin = attr(attributes, VEHICLE_IDS.vin);
  if (vin !== undefined) {
    const text =
      typeof vin === 'string' && /^[0-9a-fA-F]+$/.test(vin) && vin.length > 17
        ? cardText(`00${vin}`)
        : String(vin);
    if (text && text.trim()) out.vin = text.trim();
  }
  return out;
};

/*
 * Driver-facing limits. The tachograph's own "remaining" figures are used where
 * it sends them; where a model does not, they are worked out from the elapsed
 * figures it does send, against the EU limits (4h30 continuous, 9h daily - 10h
 * twice a week, 56h weekly, 90h fortnightly).
 */
export const figures = (values) => {
  const pick = (key, fallback) =>
    values[key] === null || values[key] === undefined ? fallback : values[key];
  const cont = values.continuousDriving;
  const daily = values.dailyDriving;
  const weekly = values.weeklyDriving;
  const fortnight = values.twoWeekDriving;
  const extensions = values.dailyExtensionsUsed;
  const dailyLimit = extensions !== null && extensions !== undefined && extensions < 2 ? 600 : 540;
  const left = (limit, used) =>
    used === null || used === undefined ? null : Math.max(0, limit - used);
  return {
    drivingUntilBreak: pick('untilBreak', pick('remainingCurrentDriving', left(270, cont))),
    drivingLeftToday: pick('remainingShiftDriving', left(dailyLimit, daily)),
    drivingLeftWeek: pick('remainingWeekDriving', left(3360, weekly)),
    drivingLeftFortnight: left(5400, fortnight),
    continuousDriving: cont ?? null,
    breakTaken: values.cumulativeBreak ?? null,
    dailyDriving: daily ?? null,
    weeklyDriving: weekly ?? null,
    twoWeekDriving: fortnight ?? null,
    nextBreakDuration: values.nextBreakDuration ?? null,
    untilDailyRest: values.untilDailyRest ?? null,
    untilWeeklyRest: values.untilWeeklyRest ?? null,
    minDailyRest: values.minDailyRest ?? null,
    minWeeklyRest: values.minWeeklyRest ?? null,
    remainingCurrentBreak: values.remainingCurrentBreak ?? null,
    dailyExtensionsUsed: extensions ?? null,
    endLastDailyRest: values.endLastDailyRest ?? null,
    endLastWeeklyRest: values.endLastWeeklyRest ?? null,
  };
};

export const warningFor = (timeState) =>
  TIME_STATES[timeState] ? { code: timeState, ...TIME_STATES[timeState] } : null;

/* Minutes as the hours and minutes a driver thinks in. */
export const asHours = (minutes) => {
  if (minutes === null || minutes === undefined) return '—';
  const whole = Math.max(0, Math.round(minutes));
  const h = Math.floor(whole / 60);
  const m = whole % 60;
  return h ? `${h}h ${String(m).padStart(2, '0')}m` : `${m}m`;
};

/* A driver card number is 16 characters of which only the tail is recognisable. */
export const cardEnding = (number) =>
  number && number.length > 4 ? `…${number.slice(-4)}` : number || null;
