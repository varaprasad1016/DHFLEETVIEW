import { useEffect, useReducer, useState } from 'react';
import { useDispatch } from 'react-redux';
import { makeStyles } from 'tss-react/mui';
import { List } from 'react-window';
import { devicesActions } from '../store';
import { useAsyncTask } from '../reactHelper';
import DeviceRow from './DeviceRow';
import fetchOrThrow from '../common/util/fetchOrThrow';

const useStyles = makeStyles()((theme) => ({
  list: {
    height: '100%',
    direction: theme.direction,
  },
  listInner: {
    position: 'relative',
    margin: theme.spacing(1.5, 0),
  },
}));

const DeviceList = ({ devices }) => {
  const { classes } = useStyles();
  const dispatch = useDispatch();

  const [, forceUpdate] = useReducer((x) => x + 1, 0);

  useEffect(() => {
    const interval = setInterval(forceUpdate, 60000);
    return () => {
      clearInterval(interval);
    };
  }, []);

  useAsyncTask(
    async ({ signal }) => {
      const response = await fetchOrThrow('/api/devices', { signal });
      dispatch(devicesActions.refresh(await response.json()));
    },
    [dispatch],
  );

  /*
   * Who is driving each vehicle, for the name beside the registration.
   *
   * One request for the whole list rather than one per row: the driver comes
   * from tachograph values the unit sends only when they change, so the server
   * merges each vehicle's recent records and returns the last known state. The
   * list works perfectly well without it, so a failure here is quiet.
   */
  const [tacho, setTacho] = useState({});
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const response = await fetch('/api/tachograph/live');
        if (!response.ok) return;
        const data = await response.json();
        if (!cancelled) setTacho(data || {});
      } catch {
        // the registrations matter more than the names beside them
      }
    };
    load();
    const timer = setInterval(load, 60000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  /*
   * What each vehicle is driving towards: closures and roadworks ahead of it on
   * the strategic network. One request for the whole list, refreshed on the
   * same rhythm as the feed behind it, and silent when it fails - a roadworks
   * service being down must never cost anyone their vehicle list.
   */
  const [ahead, setAhead] = useState({});
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const response = await fetch('/api/disruptions/ahead');
        if (!response.ok) return;
        const data = await response.json();
        if (cancelled) return;
        const byDevice = {};
        (data.items || []).forEach((item) => {
          byDevice[item.deviceId] = item;
        });
        setAhead(byDevice);
      } catch {
        // the vehicles matter more than the roadworks
      }
    };
    load();
    const timer = setInterval(load, 120000);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, []);

  return (
    <List
      className={classes.list}
      rowComponent={DeviceRow}
      rowCount={devices.length}
      rowHeight={96}
      rowProps={{ devices, tacho, ahead }}
      overscanCount={5}
    />
  );
};

export default DeviceList;
