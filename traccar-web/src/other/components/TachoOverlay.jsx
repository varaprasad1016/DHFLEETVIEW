import { useCallback, useEffect, useRef, useState } from 'react';
import { Box, Chip, IconButton, Paper, Tooltip, Typography } from '@mui/material';
import { alpha } from '@mui/material/styles';
import { makeStyles } from 'tss-react/mui';
import dayjs from 'dayjs';
import CloseIcon from '@mui/icons-material/Close';
import DragIndicatorIcon from '@mui/icons-material/DragIndicator';
import ExpandLessIcon from '@mui/icons-material/ExpandLess';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import WarningAmberIcon from '@mui/icons-material/WarningAmber';
import DownloadIcon from '@mui/icons-material/Download';
import { ACTIVITY, asHours, cardEnding } from '../../common/util/fmc650Tacho';

/*
 * The vehicle's tachograph, over the live map.
 *
 * It sits on the map rather than beside it because the map and the cameras
 * already have the screen between them, and hours are read at a glance next to
 * the picture - not in a panel that takes width away from both. It can be
 * dragged anywhere inside the map and closed; where it was put and whether it
 * was closed are remembered per browser.
 */

const PANEL_WIDTH = 304;
const EDGE = 12;
const STORE_KEY = 'dhfv-tacho-panel';

const useStyles = makeStyles()((theme) => ({
  panel: {
    position: 'absolute',
    zIndex: 6, // above MapScale and the location button
    width: PANEL_WIDTH,
    maxWidth: `calc(100% - ${EDGE * 2}px)`,
    // Capped as well as bounded by the map: on a phone the map is only a few
    // hundred pixels tall, and a panel free to use all of it leaves nothing of
    // the map to look at. Past the cap the panel scrolls inside itself.
    maxHeight: `min(calc(100% - ${EDGE * 2}px), 340px)`,
    display: 'flex',
    flexDirection: 'column',
    borderRadius: 12,
    border: `1px solid ${theme.palette.divider}`,
    backgroundColor: alpha(theme.palette.background.paper, 0.94),
    backdropFilter: 'blur(6px)',
    boxShadow: theme.shadows[6],
    overflow: 'hidden',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: theme.spacing(0.5),
    padding: theme.spacing(0.75, 0.5, 0.75, 0.75),
    borderBottom: `1px solid ${theme.palette.divider}`,
    cursor: 'grab',
    touchAction: 'none', // the drag is ours, not the map's pan
    userSelect: 'none',
  },
  dragging: {
    cursor: 'grabbing',
  },
  headerTitle: {
    flexGrow: 1,
    fontWeight: 600,
    fontSize: '0.78rem',
    letterSpacing: '0.04em',
    textTransform: 'uppercase',
    color: theme.palette.text.secondary,
  },
  body: {
    overflowY: 'auto',
    padding: theme.spacing(1, 1.25, 1.25),
    display: 'flex',
    flexDirection: 'column',
    gap: theme.spacing(1),
  },
  slot: {
    display: 'flex',
    flexDirection: 'column',
    gap: theme.spacing(0.5),
  },
  slotHead: {
    display: 'flex',
    alignItems: 'baseline',
    gap: theme.spacing(0.75),
  },
  slotLabel: {
    fontSize: '0.65rem',
    fontWeight: 600,
    letterSpacing: '0.06em',
    textTransform: 'uppercase',
    color: theme.palette.text.secondary,
  },
  name: {
    fontWeight: 600,
    fontSize: '0.9rem',
    lineHeight: 1.25,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  figures: {
    display: 'grid',
    gridTemplateColumns: 'auto 1fr',
    columnGap: theme.spacing(1),
    rowGap: 2,
    alignItems: 'baseline',
  },
  figureLabel: {
    fontSize: '0.75rem',
    color: theme.palette.text.secondary,
  },
  figureValue: {
    fontSize: '0.8rem',
    fontWeight: 600,
    fontVariantNumeric: 'tabular-nums',
    textAlign: 'right',
  },
  divider: {
    height: 1,
    backgroundColor: theme.palette.divider,
  },
  alert: {
    display: 'flex',
    alignItems: 'center',
    gap: theme.spacing(0.75),
    padding: theme.spacing(0.5, 0.75),
    borderRadius: 8,
    fontSize: '0.75rem',
    fontWeight: 600,
    lineHeight: 1.3,
  },
  bad: {
    backgroundColor: alpha(theme.palette.error.main, 0.14),
    color: theme.palette.error.main,
  },
  warn: {
    backgroundColor: alpha(theme.palette.warning.main, 0.16),
    color: theme.palette.warning.dark,
  },
  foot: {
    fontSize: '0.7rem',
    color: theme.palette.text.secondary,
    fontVariantNumeric: 'tabular-nums',
  },
  more: {
    alignSelf: 'flex-start',
    fontSize: '0.7rem',
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.04em',
    color: theme.palette.primary.main,
    background: 'none',
    border: 0,
    padding: 0,
    cursor: 'pointer',
  },
  downloads: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: theme.spacing(0.5),
    alignSelf: 'flex-start',
    fontSize: '0.72rem',
    fontWeight: 700,
    textTransform: 'uppercase',
    letterSpacing: '0.04em',
    color: theme.palette.primary.main,
    textDecoration: 'none',
  },
  empty: {
    fontSize: '0.78rem',
    color: theme.palette.text.secondary,
    lineHeight: 1.45,
  },
}));

const readStore = () => {
  try {
    return JSON.parse(window.localStorage.getItem(STORE_KEY)) || {};
  } catch {
    return {};
  }
};

const writeStore = (value) => {
  try {
    window.localStorage.setItem(STORE_KEY, JSON.stringify(value));
  } catch {
    // position not remembered; the panel still works
  }
};

const Figure = ({ label, value, classes }) => (
  <>
    <Typography className={classes.figureLabel}>{label}</Typography>
    <Typography className={classes.figureValue}>{value}</Typography>
  </>
);

const DriverSlot = ({ data, classes, expanded }) => {
  const activity = data.activity ? ACTIVITY[data.activity] : null;
  const f = data.figures;
  return (
    <div className={classes.slot}>
      <div className={classes.slotHead}>
        <Typography className={classes.slotLabel}>{`Driver ${data.slot}`}</Typography>
        {activity && (
          <Chip
            size="small"
            label={activity.label}
            sx={{
              height: 18,
              fontSize: '0.68rem',
              fontWeight: 700,
              color: '#fff',
              backgroundColor: activity.color,
            }}
          />
        )}
      </div>
      {/* What the slot can be called, in the order an operator would want it:
          the holder's name, then the card, then simply whether there is one.
          A card number is not always readable (see fmc650Tacho), so "card
          inserted" with no number is a real state and not an error. */}
      <Typography className={classes.name}>
        {data.cardHolder ||
          (data.cardNumber && `Card ${cardEnding(data.cardNumber)}`) ||
          (data.cardPresent === true && 'Card inserted') ||
          (data.cardPresent === false && 'No card inserted') ||
          'Driver card not reported'}
      </Typography>
      <Typography className={classes.figureLabel}>
        {data.minutesInActivity !== null && activity
          ? `${activity.label} for ${asHours(data.minutesInActivity)}`
          : 'Activity not reported'}
        {data.cardHolder && data.cardNumber ? ` · card ${cardEnding(data.cardNumber)}` : ''}
      </Typography>
      {data.warning && (
        <div
          className={`${classes.alert} ${data.warning.level === 'bad' ? classes.bad : classes.warn}`}
        >
          <WarningAmberIcon sx={{ fontSize: 16 }} />
          <span>{data.warning.label}</span>
        </div>
      )}
      {f && (
        <div className={classes.figures}>
          <Figure
            classes={classes}
            label="Driving until break"
            value={asHours(f.drivingUntilBreak)}
          />
          <Figure
            classes={classes}
            label="Driving left today"
            value={asHours(f.drivingLeftToday)}
          />
          <Figure
            classes={classes}
            label="Driving left this week"
            value={asHours(f.drivingLeftWeek)}
          />
          <Figure
            classes={classes}
            label="Left this fortnight"
            value={asHours(f.drivingLeftFortnight)}
          />
          {expanded && (
            <>
              <Figure
                classes={classes}
                label="Driving since last break"
                value={asHours(f.continuousDriving)}
              />
              <Figure classes={classes} label="Break taken" value={asHours(f.breakTaken)} />
              <Figure classes={classes} label="Driven today" value={asHours(f.dailyDriving)} />
              <Figure classes={classes} label="Driven this week" value={asHours(f.weeklyDriving)} />
              <Figure
                classes={classes}
                label="Driven this fortnight"
                value={asHours(f.twoWeekDriving)}
              />
              <Figure
                classes={classes}
                label="Next break needed"
                value={asHours(f.nextBreakDuration)}
              />
              <Figure
                classes={classes}
                label="Until daily rest"
                value={asHours(f.untilDailyRest)}
              />
              <Figure
                classes={classes}
                label="Until weekly rest"
                value={asHours(f.untilWeeklyRest)}
              />
              <Figure
                classes={classes}
                label="Daily rest required"
                value={asHours(f.minDailyRest)}
              />
              <Figure
                classes={classes}
                label="Weekly rest required"
                value={asHours(f.minWeeklyRest)}
              />
              <Figure
                classes={classes}
                label="10h days used"
                value={f.dailyExtensionsUsed === null ? '—' : `${f.dailyExtensionsUsed} of 2`}
              />
              <Figure
                classes={classes}
                label="Last daily rest ended"
                value={f.endLastDailyRest ? dayjs(f.endLastDailyRest).format('ddd HH:mm') : '—'}
              />
              <Figure
                classes={classes}
                label="Last weekly rest ended"
                value={f.endLastWeeklyRest ? dayjs(f.endLastWeeklyRest).format('D MMM HH:mm') : '—'}
              />
            </>
          )}
        </div>
      )}
    </div>
  );
};

const TachoOverlay = ({ live, deviceName, onClose }) => {
  const { classes } = useStyles();
  const panelRef = useRef(null);
  const dragRef = useRef(null);

  const [place, setPlace] = useState(() => readStore().place || null);
  const [collapsed, setCollapsed] = useState(() => Boolean(readStore().collapsed));
  const [expanded, setExpanded] = useState(false);
  const [dragging, setDragging] = useState(false);

  // Keep the panel inside the map when the window changes shape under it.
  const clamp = useCallback((next) => {
    const panel = panelRef.current;
    const parent = panel?.offsetParent;
    if (!panel || !parent) return next;
    const maxLeft = Math.max(0, parent.clientWidth - panel.offsetWidth - EDGE);
    const maxTop = Math.max(0, parent.clientHeight - panel.offsetHeight - EDGE);
    return {
      left: Math.min(Math.max(EDGE, next.left), Math.max(EDGE, maxLeft)),
      top: Math.min(Math.max(EDGE, next.top), Math.max(EDGE, maxTop)),
    };
  }, []);

  useEffect(() => {
    if (!place) return undefined;
    const onResize = () => setPlace((current) => (current ? clamp(current) : current));
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, [place, clamp]);

  const onPointerDown = (event) => {
    if (event.button !== undefined && event.button !== 0) return;
    const panel = panelRef.current;
    if (!panel) return;
    const parent = panel.offsetParent;
    const parentRect = parent.getBoundingClientRect();
    const rect = panel.getBoundingClientRect();
    dragRef.current = {
      offsetX: event.clientX - rect.left,
      offsetY: event.clientY - rect.top,
      parentRect,
    };
    event.currentTarget.setPointerCapture?.(event.pointerId);
    setDragging(true);
  };

  const onPointerMove = (event) => {
    const drag = dragRef.current;
    if (!drag) return;
    event.preventDefault();
    setPlace(
      clamp({
        left: event.clientX - drag.parentRect.left - drag.offsetX,
        top: event.clientY - drag.parentRect.top - drag.offsetY,
      }),
    );
  };

  const endDrag = (event) => {
    if (!dragRef.current) return;
    dragRef.current = null;
    setDragging(false);
    event.currentTarget.releasePointerCapture?.(event.pointerId);
    setPlace((current) => {
      if (current) writeStore({ ...readStore(), place: current });
      return current;
    });
  };

  const toggleCollapsed = () => {
    setCollapsed((current) => {
      writeStore({ ...readStore(), collapsed: !current });
      return !current;
    });
  };

  // Not placed yet: open on the left of the map. The right-hand strip is spoken
  // for - the app's fixed Home and Compliance buttons sit there at z-index 1100,
  // with the map's zoom, compass and locate controls below them - so a panel
  // opening on that side comes up underneath them. Drag it anywhere inside the
  // map; where it is put is what it remembers.
  const style = place ? { left: place.left, top: place.top } : { left: EDGE, top: EDGE };

  const { slots, vehicle, recordedAt, stale, hasData, noCardDriving } = live;
  const speed = vehicle.tachoSpeed;
  const vehicleBits = [
    speed !== undefined && speed !== null ? `${speed} km/h` : null,
    vehicle.direction && vehicle.direction !== 'Forward' ? vehicle.direction : null,
    vehicle.performance && vehicle.performance !== 'Normal'
      ? `Tachograph: ${vehicle.performance}`
      : null,
    vehicle.handlingInfo === 'Yes' ? 'Handling info' : null,
    vehicle.systemEvent === 'Yes' ? 'Tachograph event' : null,
  ].filter(Boolean);

  return (
    <Paper ref={panelRef} className={classes.panel} style={style} elevation={0}>
      <div
        className={`${classes.header}${dragging ? ` ${classes.dragging}` : ''}`}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
      >
        <DragIndicatorIcon sx={{ fontSize: 16, color: 'text.disabled' }} />
        <Typography className={classes.headerTitle}>
          {`Tachograph${deviceName ? ` · ${deviceName}` : ''}`}
        </Typography>
        <Tooltip title={collapsed ? 'Show' : 'Hide details'}>
          <IconButton size="small" onClick={toggleCollapsed}>
            {collapsed ? <ExpandMoreIcon fontSize="small" /> : <ExpandLessIcon fontSize="small" />}
          </IconButton>
        </Tooltip>
        <Tooltip title="Close">
          <IconButton size="small" onClick={onClose}>
            <CloseIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      </div>
      {!collapsed && (
        <div className={classes.body}>
          {noCardDriving && (
            <div className={`${classes.alert} ${classes.bad}`}>
              <WarningAmberIcon sx={{ fontSize: 16 }} />
              <span>Being driven without a driver card</span>
            </div>
          )}
          {vehicle.overspeed && (
            <div className={`${classes.alert} ${classes.warn}`}>
              <WarningAmberIcon sx={{ fontSize: 16 }} />
              <span>Tachograph overspeed signal</span>
            </div>
          )}
          {!hasData && (
            <Typography className={classes.empty}>
              No tachograph data from this vehicle yet. It appears here as soon as the unit reports
              a driver card, working state or driving time.
            </Typography>
          )}
          {slots.map((data, index) => (
            <Box key={data.slot} sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
              {index > 0 && <div className={classes.divider} />}
              <DriverSlot data={data} classes={classes} expanded={expanded} />
            </Box>
          ))}
          {slots.some((s) => s.figures) && (
            <button type="button" className={classes.more} onClick={() => setExpanded((v) => !v)}>
              {expanded ? 'Less' : 'All figures'}
            </button>
          )}
          {(vehicleBits.length > 0 || vehicle.vin) && (
            <>
              <div className={classes.divider} />
              <div>
                {vehicleBits.length > 0 && (
                  <Typography className={classes.figureLabel}>{vehicleBits.join(' · ')}</Typography>
                )}
                {vehicle.vin && (
                  <Typography className={classes.foot}>{`VIN ${vehicle.vin}`}</Typography>
                )}
              </div>
            </>
          )}
          {/* The DDD files themselves: downloaded from the vehicle by TachoSync
              and archived here. A page rather than a panel - they are a list
              with dates and sizes, not something to read over a map. */}
          <div className={classes.divider} />
          <a className={classes.downloads} href="/tacho/downloads" target="_blank" rel="noreferrer">
            <DownloadIcon sx={{ fontSize: 15 }} />
            Downloads
          </a>
          {recordedAt && (
            <Typography className={classes.foot}>
              {stale
                ? `Last reported ${dayjs(recordedAt).format('HH:mm')} — may be out of date`
                : `As reported at ${dayjs(recordedAt).format('HH:mm')}`}
            </Typography>
          )}
        </div>
      )}
    </Paper>
  );
};

export default TachoOverlay;
