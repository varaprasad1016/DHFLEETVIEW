import { useCallback, useMemo, useState } from 'react';
import { useSelector } from 'react-redux';
import { makeStyles } from 'tss-react/mui';
import { alpha, useTheme } from '@mui/material/styles';
import {
  Button,
  CircularProgress,
  InputAdornment,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Typography,
} from '@mui/material';
import SearchIcon from '@mui/icons-material/Search';
import RouteIcon from '@mui/icons-material/Route';
import PauseCircleFilledIcon from '@mui/icons-material/PauseCircleFilled';
import SummarizeIcon from '@mui/icons-material/Summarize';
import NotificationsActiveIcon from '@mui/icons-material/NotificationsActive';
import PictureAsPdfIcon from '@mui/icons-material/PictureAsPdf';
import GridOnIcon from '@mui/icons-material/GridOn';
import dayjs from 'dayjs';
import utc from 'dayjs/plugin/utc';
import timezone from 'dayjs/plugin/timezone';
import PageLayout from '../common/components/PageLayout';
import ReportsMenu from './components/ReportsMenu';
import { useTranslation } from '../common/components/LocalizationProvider';
import { useCatch } from '../reactHelper';
import fetchOrThrow from '../common/util/fetchOrThrow';
import { APP_TIME_ZONE } from '../common/util/formatter';
import { downloadReportPdf } from '../common/util/reportPdf';
import exportExcel from '../common/util/exportExcel';

/*
 * One screen for the whole job: choose the vehicles, choose the report, choose
 * the period, read the answer. The classic report pages each do one of those
 * four things and make you find the others; this follows the order a transport
 * manager actually asks them in, and puts the totals above the rows because
 * that is what gets read.
 */

// Traccar speaks metres, knots and milliseconds. A UK yard does not.
dayjs.extend(utc);
dayjs.extend(timezone);

const miles = (metres) => (metres || 0) / 1609.344;
const mph = (knots) => (knots || 0) * 1.150779;
const hoursMinutes = (ms) => {
  const total = Math.round((ms || 0) / 1000);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  if (h && m) return `${h}h ${String(m).padStart(2, '0')}m`;
  if (h) return `${h}h`;
  return m ? `${m}m` : `${total}s`;
};
const clock = (iso) => (iso ? dayjs(iso).tz(APP_TIME_ZONE).format('DD MMM HH:mm:ss') : '—');
const where = (address, latitude, longitude) => {
  if (address) return address.replace(', England', '').replace(', United Kingdom', '');
  if (latitude == null || longitude == null) return '—';
  return `${latitude.toFixed(5)}, ${longitude.toFixed(5)}`;
};

const KINDS = [
  {
    id: 'trips',
    name: 'Trips',
    blurb: 'Every journey, with distance, time and where it started and finished',
    icon: RouteIcon,
  },
  {
    id: 'stops',
    name: 'Stops',
    blurb: 'Where the vehicle stood still, and for how long',
    icon: PauseCircleFilledIcon,
  },
  {
    id: 'summary',
    name: 'Summary',
    blurb: 'One line per vehicle: distance, speeds and odometer',
    icon: SummarizeIcon,
  },
  {
    id: 'events',
    name: 'Events',
    blurb: 'Alarms, ignition, geofences and the rest, in order',
    icon: NotificationsActiveIcon,
  },
];

const PERIODS = [
  {
    id: 'today',
    name: 'Today',
    range: () => [dayjs().tz(APP_TIME_ZONE).startOf('day'), dayjs().tz(APP_TIME_ZONE).endOf('day')],
  },
  {
    id: 'yesterday',
    name: 'Yesterday',
    range: () => [
      dayjs().tz(APP_TIME_ZONE).subtract(1, 'day').startOf('day'),
      dayjs().tz(APP_TIME_ZONE).subtract(1, 'day').endOf('day'),
    ],
  },
  {
    id: 'week',
    name: 'This week',
    range: () => [
      dayjs().tz(APP_TIME_ZONE).startOf('week'),
      dayjs().tz(APP_TIME_ZONE).endOf('day'),
    ],
  },
  {
    id: 'seven',
    name: 'Last 7 days',
    range: () => [
      dayjs().tz(APP_TIME_ZONE).subtract(7, 'day').startOf('day'),
      dayjs().tz(APP_TIME_ZONE).endOf('day'),
    ],
  },
  {
    id: 'month',
    name: 'This month',
    range: () => [
      dayjs().tz(APP_TIME_ZONE).startOf('month'),
      dayjs().tz(APP_TIME_ZONE).endOf('day'),
    ],
  },
  { id: 'custom', name: 'Custom range', custom: true },
];

const COLUMNS = {
  trips: [
    ['Start', (r) => clock(r.startTime)],
    ['From', (r) => where(r.startAddress, r.startLat, r.startLon)],
    ['End', (r) => clock(r.endTime)],
    ['To', (r) => where(r.endAddress, r.endLat, r.endLon)],
    ['Distance', (r) => `${miles(r.distance).toFixed(1)} mi`, 'number'],
    ['Driving', (r) => hoursMinutes(r.duration), 'number'],
    ['Max', (r) => `${mph(r.maxSpeed).toFixed(0)} mph`, 'number'],
    ['Average', (r) => `${mph(r.averageSpeed).toFixed(0)} mph`, 'number'],
  ],
  stops: [
    ['Arrived', (r) => clock(r.startTime)],
    ['Left', (r) => clock(r.endTime)],
    ['Stopped for', (r) => hoursMinutes(r.duration), 'number'],
    ['Where', (r) => where(r.address, r.latitude, r.longitude)],
  ],
  summary: [
    ['Vehicle', (r) => r.deviceName],
    ['Distance', (r) => `${miles(r.distance).toFixed(1)} mi`, 'number'],
    ['Max speed', (r) => `${mph(r.maxSpeed).toFixed(0)} mph`, 'number'],
    ['Average speed', (r) => `${mph(r.averageSpeed).toFixed(0)} mph`, 'number'],
    ['Odometer start', (r) => `${miles(r.startOdometer).toFixed(0)} mi`, 'number'],
    ['Odometer end', (r) => `${miles(r.endOdometer).toFixed(0)} mi`, 'number'],
  ],
  events: [
    ['When', (r) => clock(r.eventTime || r.serverTime)],
    ['Vehicle', (r) => r.deviceName],
    [
      'Event',
      (r) =>
        String(r.type || '')
          .replace(/([A-Z])/g, ' $1')
          .trim(),
    ],
    ['Where', (r) => where(r.address, r.latitude, r.longitude)],
  ],
};

// Where each kind of row keeps its place, matching the server.
const PLACE_FIELDS = {
  trips: [
    ['startAddress', 'startLat', 'startLon'],
    ['endAddress', 'endLat', 'endLon'],
  ],
  stops: [['address', 'latitude', 'longitude']],
  events: [['address', 'latitude', 'longitude']],
  summary: [],
};

/*
 * Fill in the places the positions never got a name for.
 *
 * The same service the PDF uses, so the screen and the printed page never
 * disagree, and whichever is asked for second costs nothing.
 */
const nameThePlaces = async (kind, rows) => {
  const fields = PLACE_FIELDS[kind] || [];
  if (!fields.length) return rows;

  // Every spot that still needs a name, and where it came from. The server
  // answers in the order it is asked, so nothing has to be matched up by
  // stringifying a coordinate - which is what went wrong before: JavaScript
  // writes 51.5000 where Python writes 51.5.
  const asked = [];
  rows.forEach((row, index) =>
    fields.forEach(([address, latKey, lonKey]) => {
      if (row[address]) return;
      const latitude = row[latKey];
      const longitude = row[lonKey];
      if (latitude == null || longitude == null) return;
      asked.push({ index, address, latitude, longitude });
    }),
  );
  if (!asked.length) return rows;

  let answers;
  try {
    const response = await fetch('/tacho/api/reports/places', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(asked.map(({ latitude, longitude }) => ({ latitude, longitude }))),
    });
    if (!response.ok) return rows;
    answers = await response.json();
  } catch {
    return rows; // a coordinate is still a usable answer
  }
  if (!Array.isArray(answers)) return rows;

  const filled = rows.map((row) => ({ ...row }));
  asked.forEach(({ index, address }, position) => {
    const place = answers[position];
    if (place) filled[index][address] = place;
  });
  return filled;
};

// The same figures the PDF puts at the top, worked out from the same rows.
const figuresFor = (kind, rows) => {
  if (kind === 'trips') {
    const lengths = rows.map((r) => miles(r.distance));
    const sound = lengths.filter((d) => d >= 0);
    return [
      ['Trips', `${rows.length}`],
      ['Distance', `${sound.reduce((a, b) => a + b, 0).toFixed(1)} mi`],
      ['Driving time', hoursMinutes(rows.reduce((a, r) => a + (r.duration || 0), 0))],
      ['Longest trip', `${Math.max(0, ...sound).toFixed(1)} mi`],
      ['Fastest', `${Math.max(0, ...rows.map((r) => mph(r.maxSpeed))).toFixed(0)} mph`],
    ];
  }
  if (kind === 'stops') {
    return [
      ['Stops', `${rows.length}`],
      ['Stopped for', hoursMinutes(rows.reduce((a, r) => a + (r.duration || 0), 0))],
      ['Longest stop', hoursMinutes(Math.max(0, ...rows.map((r) => r.duration || 0)))],
    ];
  }
  if (kind === 'summary') {
    return [
      ['Vehicles', `${rows.length}`],
      ['Distance', `${rows.reduce((a, r) => a + miles(r.distance), 0).toFixed(1)} mi`],
    ];
  }
  return [
    ['Events', `${rows.length}`],
    ['Kinds', `${new Set(rows.map((r) => r.type)).size}`],
  ];
};

const useStyles = makeStyles()((theme) => ({
  page: {
    display: 'grid',
    gridTemplateColumns: 'minmax(300px, 360px) 1fr',
    gap: theme.spacing(2),
    padding: theme.spacing(2),
    height: '100%',
    overflow: 'auto',
    [theme.breakpoints.down('md')]: { gridTemplateColumns: '1fr' },
  },
  panel: { display: 'flex', flexDirection: 'column', gap: theme.spacing(2), minWidth: 0 },
  card: {
    background: theme.palette.background.paper,
    border: `1px solid ${theme.palette.divider}`,
    borderRadius: 14,
    padding: theme.spacing(2),
  },
  step: {
    fontSize: '0.68rem',
    letterSpacing: '0.09em',
    textTransform: 'uppercase',
    color: theme.palette.text.secondary,
    fontWeight: 700,
    marginBottom: theme.spacing(1.25),
    display: 'block',
  },
  vehicles: { maxHeight: 260, overflow: 'auto', marginTop: theme.spacing(1) },
  vehicle: {
    display: 'flex',
    alignItems: 'center',
    gap: theme.spacing(1),
    padding: theme.spacing(0.75, 1),
    borderRadius: 9,
    cursor: 'pointer',
    '&:hover': { background: alpha(theme.palette.primary.main, 0.06) },
  },
  vehicleOn: { background: alpha(theme.palette.primary.main, 0.12) },
  plate: {
    display: 'inline-flex',
    borderRadius: 4,
    overflow: 'hidden',
    border: '1px solid #0f1115',
    flexShrink: 0,
  },
  plateBand: {
    background: '#15489f',
    color: '#fff',
    fontSize: '0.45rem',
    fontWeight: 700,
    padding: '3px 3px 2px',
    display: 'flex',
    alignItems: 'flex-end',
  },
  plateText: {
    background: '#f5cd2f',
    color: '#0f1115',
    fontWeight: 700,
    fontSize: '0.8rem',
    letterSpacing: '0.07em',
    padding: '3px 6px 2px',
    whiteSpace: 'nowrap',
  },
  kinds: { display: 'grid', gap: theme.spacing(1) },
  kind: {
    display: 'flex',
    gap: theme.spacing(1.5),
    alignItems: 'flex-start',
    padding: theme.spacing(1.25),
    borderRadius: 11,
    border: `1px solid ${theme.palette.divider}`,
    cursor: 'pointer',
    '&:hover': { borderColor: theme.palette.primary.main },
  },
  kindOn: {
    borderColor: theme.palette.primary.main,
    background: alpha(theme.palette.primary.main, 0.08),
  },
  chips: { display: 'flex', flexWrap: 'wrap', gap: theme.spacing(0.75) },
  chip: {
    padding: theme.spacing(0.6, 1.5),
    borderRadius: 999,
    border: `1px solid ${theme.palette.divider}`,
    cursor: 'pointer',
    fontSize: '0.8rem',
    color: theme.palette.text.secondary,
  },
  chipOn: {
    background: theme.palette.primary.main,
    borderColor: theme.palette.primary.main,
    color: theme.palette.primary.contrastText,
    fontWeight: 600,
  },
  custom: {
    display: 'grid',
    gridTemplateColumns: '1fr 1fr',
    gap: theme.spacing(1),
    marginTop: theme.spacing(1.5),
  },
  results: { display: 'flex', flexDirection: 'column', gap: theme.spacing(2), minWidth: 0 },
  figures: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
    gap: 1,
    background: theme.palette.divider,
    borderRadius: 14,
    overflow: 'hidden',
    border: `1px solid ${theme.palette.divider}`,
  },
  figure: { background: theme.palette.background.paper, padding: theme.spacing(1.5, 2) },
  figureLabel: {
    display: 'block',
    fontSize: '0.64rem',
    letterSpacing: '0.08em',
    textTransform: 'uppercase',
    color: theme.palette.text.secondary,
  },
  figureValue: {
    display: 'block',
    marginTop: 2,
    fontSize: '1.4rem',
    fontWeight: 700,
    fontVariantNumeric: 'tabular-nums',
  },
  actions: { display: 'flex', gap: theme.spacing(1), flexWrap: 'wrap', alignItems: 'center' },
  tableWrap: {
    overflow: 'auto',
    border: `1px solid ${theme.palette.divider}`,
    borderRadius: 14,
    background: theme.palette.background.paper,
  },
  number: { textAlign: 'right', fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap' },
  empty: { padding: theme.spacing(5), textAlign: 'center', color: theme.palette.text.secondary },
}));

const ReportWorkspacePage = () => {
  const { classes, cx } = useStyles();
  const t = useTranslation();
  const theme = useTheme();
  const devices = useSelector((state) => state.devices.items);

  const [search, setSearch] = useState('');
  const [chosen, setChosen] = useState([]);
  const [kind, setKind] = useState('trips');
  const [period, setPeriod] = useState('today');
  const [customFrom, setCustomFrom] = useState(
    dayjs().tz(APP_TIME_ZONE).subtract(7, 'day').startOf('day').format('YYYY-MM-DDTHH:mm'),
  );
  const [customTo, setCustomTo] = useState(
    dayjs().tz(APP_TIME_ZONE).endOf('day').format('YYYY-MM-DDTHH:mm'),
  );
  const [rows, setRows] = useState(null);
  const [loading, setLoading] = useState(false);
  const [exporting, setExporting] = useState(false);

  const fleet = useMemo(() => {
    const all = Object.values(devices);
    const needle = search.trim().toLowerCase();
    const matching = needle ? all.filter((d) => d.name.toLowerCase().includes(needle)) : all;
    return matching.sort((a, b) => a.name.localeCompare(b.name));
  }, [devices, search]);

  const range = useCallback(() => {
    if (period === 'custom') {
      // Typed in UK time, which is what the yard means by "the 14th".
      return {
        from: dayjs.tz(customFrom, 'YYYY-MM-DDTHH:mm', APP_TIME_ZONE).toISOString(),
        to: dayjs.tz(customTo, 'YYYY-MM-DDTHH:mm', APP_TIME_ZONE).toISOString(),
      };
    }
    const [from, to] = PERIODS.find((p) => p.id === period).range();
    return { from: from.toISOString(), to: to.toISOString() };
  }, [period, customFrom, customTo]);

  const run = useCatch(async () => {
    if (!chosen.length) return;
    setLoading(true);
    setRows(null);
    try {
      const { from, to } = range();
      const query = new URLSearchParams({ from, to });
      chosen.forEach((id) => query.append('deviceId', id));
      const response = await fetchOrThrow(`/api/reports/${kind}?${query.toString()}`, {
        headers: { Accept: 'application/json' },
      });
      const loaded = await response.json();
      setRows(loaded);
      // The names arrive a moment later; the table fills in as they do.
      setRows(await nameThePlaces(kind, loaded));
    } finally {
      setLoading(false);
    }
  });

  const exportPdf = useCatch(async () => {
    setExporting(true);
    try {
      await downloadReportPdf(kind, { deviceIds: chosen, ...range() });
    } finally {
      setExporting(false);
    }
  });

  const exportSheet = useCatch(async () => {
    const columns = COLUMNS[kind];
    const sheet = rows.map((row) => {
      const out = {};
      columns.forEach(([label, value]) => {
        out[label] = value(row);
      });
      return out;
    });
    await exportExcel(`${kind} report`, `${kind}.xlsx`, new Map([['Report', sheet]]), theme);
  });

  const toggle = (id) =>
    setChosen((current) =>
      current.includes(id) ? current.filter((x) => x !== id) : [...current, id],
    );

  const columns = COLUMNS[kind];
  const figures = rows ? figuresFor(kind, rows) : [];

  return (
    <PageLayout menu={<ReportsMenu />} breadcrumbs={['reportTitle']}>
      <div className={classes.page}>
        <div className={classes.panel}>
          <div className={classes.card}>
            <span className={classes.step}>1 · Vehicles</span>
            <TextField
              size="small"
              fullWidth
              placeholder="Search registration"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              slotProps={{
                input: {
                  startAdornment: (
                    <InputAdornment position="start">
                      <SearchIcon fontSize="small" />
                    </InputAdornment>
                  ),
                },
              }}
            />
            <div className={classes.vehicles}>
              {fleet.map((device) => (
                <div
                  key={device.id}
                  role="button"
                  tabIndex={0}
                  className={cx(classes.vehicle, chosen.includes(device.id) && classes.vehicleOn)}
                  onClick={() => toggle(device.id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') toggle(device.id);
                  }}
                >
                  <span className={classes.plate}>
                    <span className={classes.plateBand}>UK</span>
                    <span className={classes.plateText}>{device.name}</span>
                  </span>
                </div>
              ))}
              {!fleet.length && (
                <Typography variant="body2" color="textSecondary">
                  No vehicle matches that.
                </Typography>
              )}
            </div>
            <Typography variant="caption" color="textSecondary">
              {chosen.length ? `${chosen.length} selected` : 'Choose at least one vehicle'}
            </Typography>
          </div>

          <div className={classes.card}>
            <span className={classes.step}>2 · Report</span>
            <div className={classes.kinds}>
              {KINDS.map((option) => {
                const Icon = option.icon;
                return (
                  <div
                    key={option.id}
                    role="button"
                    tabIndex={0}
                    className={cx(classes.kind, kind === option.id && classes.kindOn)}
                    onClick={() => {
                      setKind(option.id);
                      setRows(null);
                    }}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') setKind(option.id);
                    }}
                  >
                    <Icon fontSize="small" color={kind === option.id ? 'primary' : 'disabled'} />
                    <span>
                      <Typography variant="body2" fontWeight={600}>
                        {option.name}
                      </Typography>
                      <Typography variant="caption" color="textSecondary">
                        {option.blurb}
                      </Typography>
                    </span>
                  </div>
                );
              })}
            </div>
          </div>

          <div className={classes.card}>
            <span className={classes.step}>3 · Period</span>
            <div className={classes.chips}>
              {PERIODS.map((option) => (
                <span
                  key={option.id}
                  role="button"
                  tabIndex={0}
                  className={cx(classes.chip, period === option.id && classes.chipOn)}
                  onClick={() => {
                    setPeriod(option.id);
                    setRows(null);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') setPeriod(option.id);
                  }}
                >
                  {option.name}
                </span>
              ))}
            </div>
            {period === 'custom' && (
              <div className={classes.custom}>
                <TextField
                  size="small"
                  type="datetime-local"
                  label="From"
                  value={customFrom}
                  onChange={(e) => {
                    setCustomFrom(e.target.value);
                    setRows(null);
                  }}
                  slotProps={{ inputLabel: { shrink: true } }}
                />
                <TextField
                  size="small"
                  type="datetime-local"
                  label="To"
                  value={customTo}
                  onChange={(e) => {
                    setCustomTo(e.target.value);
                    setRows(null);
                  }}
                  slotProps={{ inputLabel: { shrink: true } }}
                />
              </div>
            )}
          </div>

          <Button
            variant="contained"
            size="large"
            disabled={!chosen.length || loading}
            onClick={run}
            startIcon={loading ? <CircularProgress size={16} color="inherit" /> : null}
          >
            {loading ? 'Working…' : 'Run report'}
          </Button>
        </div>

        <div className={classes.results}>
          {rows && rows.length > 0 && (
            <>
              <div className={classes.figures}>
                {figures.map(([label, value]) => (
                  <div key={label} className={classes.figure}>
                    <span className={classes.figureLabel}>{label}</span>
                    <span className={classes.figureValue}>{value}</span>
                  </div>
                ))}
              </div>
              <div className={classes.actions}>
                <Button
                  variant="contained"
                  startIcon={<PictureAsPdfIcon />}
                  onClick={exportPdf}
                  disabled={exporting}
                >
                  {exporting ? 'Preparing…' : 'Download PDF'}
                </Button>
                <Button variant="outlined" startIcon={<GridOnIcon />} onClick={exportSheet}>
                  Spreadsheet
                </Button>
                <Typography variant="caption" color="textSecondary">
                  {`${rows.length} row${rows.length === 1 ? '' : 's'}`}
                </Typography>
              </div>
              <div className={classes.tableWrap}>
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      {columns.map(([label, , align]) => (
                        <TableCell
                          key={label}
                          className={align === 'number' ? classes.number : undefined}
                        >
                          {label}
                        </TableCell>
                      ))}
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {rows.map((row, index) => (
                      // Report rows carry no id of their own; their order is the key.
                      <TableRow key={index} hover>
                        {columns.map(([label, value, align]) => (
                          <TableCell
                            key={label}
                            className={align === 'number' ? classes.number : undefined}
                          >
                            {value(row)}
                          </TableCell>
                        ))}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </>
          )}
          {rows && rows.length === 0 && (
            <div className={cx(classes.card, classes.empty)}>
              Nothing was recorded for that vehicle in that period.
            </div>
          )}
          {!rows && !loading && (
            <div className={cx(classes.card, classes.empty)}>
              Choose vehicles, a report and a period, then run it.
              <br />
              {t('reportTitle')}
              {
                ' are built from the vehicle’s own positions — its tracker where one is fitted, otherwise its camera.'
              }
            </div>
          )}
        </div>
      </div>
    </PageLayout>
  );
};

export default ReportWorkspacePage;
