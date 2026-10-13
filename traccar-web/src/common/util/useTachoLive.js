import { useEffect, useMemo, useRef, useState } from 'react';
import { hasTachoData, slotReading, vehicleReading, figures, warningFor } from './fmc650Tacho';

/*
 * The vehicle's current tachograph state, built up from its positions.
 *
 * The tachograph sends a value when it changes, so a single position almost
 * never carries the whole picture: a record while the driver is halfway
 * through a shift may hold nothing but the working state. Readings are
 * therefore merged into a running state per vehicle, the same way the tacho
 * server does it on the ingest side.
 *
 * That state is also kept in localStorage, because the merge starts empty on
 * every page load and the next change might be an hour away - without it, the
 * panel would sit nearly blank until the driver did something. Anything older
 * than FRESH is thrown away rather than shown as current.
 */

const FRESH_MS = 24 * 60 * 60 * 1000; // older than this is not "live" at all
const STALE_MS = 10 * 60 * 1000; // no record this long: say so, don't hide it
const TICK_MS = 30000; // what redraws "since" and the stale mark

const storageKey = (deviceId) => `dhfv-tacho-${deviceId}`;

const read = (deviceId) => {
  try {
    const raw = window.localStorage.getItem(storageKey(deviceId));
    if (!raw) return null;
    const saved = JSON.parse(raw);
    if (!saved?.recordedAt || Date.now() - new Date(saved.recordedAt).getTime() > FRESH_MS)
      return null;
    return saved;
  } catch {
    return null; // private window, cleared site data, or something we did not write
  }
};

const write = (deviceId, state) => {
  try {
    window.localStorage.setItem(storageKey(deviceId), JSON.stringify(state));
  } catch {
    // a panel that cannot remember is still a working panel
  }
};

const positionTime = (position) =>
  position?.deviceTime || position?.fixTime || position?.serverTime;

const emptyState = { slots: {}, vehicle: {}, recordedAt: null };

/*
 * Merge one position's readings into the running state. A slot keeps its own
 * values; `since` moves only when the activity itself changes, and is backdated
 * by the tachograph's own "duration of the current activity" where that is
 * believable, so a panel opened mid-shift still says how long they have been at it.
 */
const merge = (state, position) => {
  const attributes = position?.attributes;
  if (!attributes || !hasTachoData(attributes)) return state;
  const at = positionTime(position) || new Date().toISOString();
  const next = {
    slots: { ...state.slots },
    vehicle: { ...state.vehicle, ...vehicleReading(attributes) },
    recordedAt: at,
  };

  [1, 2].forEach((slot) => {
    const reading = slotReading(attributes, slot);
    if (!Object.keys(reading).length) return;
    const previous = state.slots[slot] || {};
    const values = { ...previous, ...reading };

    const activityChanged =
      'workingState' in reading && reading.workingState !== previous.workingState;
    const cardChanged = 'cardNumber' in reading && reading.cardNumber !== previous.cardNumber;
    if (activityChanged || cardChanged || !previous.since) {
      const duration = reading.activityDuration;
      const backdate =
        duration !== null && duration !== undefined && duration < 24 * 60 ? duration : 0;
      values.since = new Date(new Date(at).getTime() - backdate * 60000).toISOString();
    } else {
      values.since = previous.since;
    }
    // A card that has been pulled takes the holder's name with it.
    if (values.cardPresent === false) {
      values.cardNumber = null;
      values.cardHolder = null;
    }
    values.recordedAt = at;
    next.slots[slot] = values;
  });
  return next;
};

const useTachoLive = (deviceId, position) => {
  const [state, setState] = useState(emptyState);
  const lastPosition = useRef(null);
  const [tick, setTick] = useState(0);

  // Hydrate when the vehicle changes, so the panel opens with what is known.
  useEffect(() => {
    lastPosition.current = null;
    setState(deviceId ? read(deviceId) || emptyState : emptyState);
  }, [deviceId]);

  /*
   * Seed from the server's merge of the vehicle's recent records.
   *
   * Without this the panel can only show what arrives while it is open, and a
   * stopped vehicle sends records with no tachograph values in them at all -
   * so a driver's hours would read as blank precisely when someone is most
   * likely to be looking them up. The server walks back through the records
   * and returns the last value reported for each element, which is the state
   * the tachograph is still in.
   */
  useEffect(() => {
    if (!deviceId) return undefined;
    const controller = new AbortController();
    (async () => {
      try {
        const response = await fetch(`/api/tachograph/live/${deviceId}`, {
          signal: controller.signal,
        });
        if (!response.ok) return;
        const data = await response.json();
        if (!data?.attributes || !Object.keys(data.attributes).length) return;
        setState((current) => {
          // Live records already merged in are newer than anything the server
          // read, so the seed goes underneath rather than over the top.
          const seeded = merge(emptyState, {
            attributes: data.attributes,
            deviceTime: data.recordedAt || new Date().toISOString(),
          });
          const slots = { ...seeded.slots };
          Object.entries(current.slots || {}).forEach(([slot, values]) => {
            // Value by value, not slot by slot: a live record may carry only
            // the working state, and that must not wipe the figures with it.
            slots[slot] = { ...(seeded.slots[slot] || {}), ...values };
          });
          const next = current.recordedAt
            ? {
                slots,
                vehicle: { ...seeded.vehicle, ...current.vehicle },
                recordedAt: current.recordedAt,
              }
            : seeded;
          write(deviceId, next);
          return next;
        });
      } catch {
        // No seed is survivable: the panel fills in as records arrive.
      }
    })();
    return () => controller.abort();
  }, [deviceId]);

  useEffect(() => {
    if (!deviceId || !position?.attributes) return;
    const id = position.id ?? positionTime(position);
    if (id === lastPosition.current) return; // the same record re-delivered
    lastPosition.current = id;
    setState((current) => {
      const next = merge(current, position);
      if (next !== current) write(deviceId, next);
      return next;
    });
  }, [deviceId, position]);

  // "Driving for 2h 10m" and the stale mark are both clocks, not data.
  useEffect(() => {
    const timer = setInterval(() => setTick((n) => n + 1), TICK_MS);
    return () => clearInterval(timer);
  }, []);

  return useMemo(() => {
    const now = Date.now();
    const recordedAt = state.recordedAt;
    const slots = [1, 2]
      .map((slot) => {
        const values = state.slots[slot];
        if (!values) return null;
        const known =
          values.cardPresent !== undefined ||
          values.workingState !== undefined ||
          values.cardNumber ||
          values.cardHolder;
        if (!known) return null;
        return {
          slot,
          cardNumber: values.cardNumber || null,
          cardHolder: values.cardHolder || null,
          cardPresent: values.cardPresent ?? null,
          activity: values.workingState ?? null,
          since: values.since || null,
          minutesInActivity: values.since
            ? Math.max(0, Math.round((now - new Date(values.since).getTime()) / 60000))
            : null,
          warning: warningFor(values.timeState),
          // Driving-time figures belong to whoever's card is in the slot: with
          // the slot empty they are the last driver's, which is worse than
          // showing nothing. A card the tachograph reports as inserted counts
          // even when it does not name the holder.
          figures:
            values.cardPresent === true || values.cardNumber || values.cardHolder
              ? figures(values)
              : null,
        };
      })
      .filter(Boolean);

    const driving = slots.some((s) => s.activity === 'drive');
    return {
      slots,
      vehicle: state.vehicle || {},
      recordedAt,
      stale: Boolean(recordedAt) && now - new Date(recordedAt).getTime() > STALE_MS,
      hasData: Boolean(recordedAt),
      // The tachograph reports driving with no card in slot 1 both as its own
      // signal (AVL 52) and, less directly, as driving with the slot empty.
      noCardDriving:
        Boolean(state.vehicle?.noCardSignal && driving) ||
        slots.some((s) => s.activity === 'drive' && s.cardPresent === false),
    };
    // `tick` is a dependency on purpose: how long they have been driving and
    // whether the last record counts as stale both move with the clock, not
    // with the data.
  }, [state, tick]);
};

export default useTachoLive;
