import { useEffect, useMemo, useRef, useState } from 'react';
import { useSelector } from 'react-redux';
import {
  Alert,
  AppBar,
  Box,
  Button,
  Checkbox,
  Chip,
  IconButton,
  MenuItem,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Toolbar,
  Tooltip,
  Typography,
} from '@mui/material';
import { makeStyles } from 'tss-react/mui';
import { useNavigate } from 'react-router-dom';
import dayjs from 'dayjs';
import SendIcon from '@mui/icons-material/Send';
import DeleteIcon from '@mui/icons-material/Delete';
import AddIcon from '@mui/icons-material/Add';
import BackIcon from '../common/components/BackIcon';

const API = '/tacho/api/dvr';

const request = async (path, init = {}) => {
  const response = await fetch(`${API}${path}`, {
    credentials: 'include',
    headers: init.body ? { 'Content-Type': 'application/json' } : undefined,
    ...init,
  });
  let data;
  try {
    data = await response.json();
  } catch {
    data = null;
  }
  if (!response.ok) {
    const detail = data?.detail;
    throw new Error(
      typeof detail === 'string'
        ? detail
        : detail?.message || `Request failed (${response.status})`,
    );
  }
  return data;
};

const useStyles = makeStyles()((theme) => ({
  root: { height: '100%', display: 'flex', flexDirection: 'column' },
  content: {
    flexGrow: 1,
    overflow: 'auto',
    padding: theme.spacing(2),
    display: 'flex',
    flexDirection: 'column',
    gap: theme.spacing(2),
  },
  card: { padding: theme.spacing(2) },
  row: { display: 'flex', gap: theme.spacing(1), alignItems: 'flex-start' },
  send: { display: 'flex', gap: theme.spacing(1), flexWrap: 'wrap', alignItems: 'center' },
  mono: { fontFamily: 'monospace', fontSize: '0.8rem' },
}));

// Setting a new camera up: the SMS commands that point it at this server, sent
// to the SIM in the DVR (the "Mobile No." printed on its label).
const DvrCommandsPage = () => {
  const { classes } = useStyles();
  const navigate = useNavigate();

  // Take the devices map itself rather than Object.values(...): that builds a
  // new array on every store update, and vehicles report constantly.
  const deviceItems = useSelector((state) => state.devices.items);
  const cameraDevices = useMemo(
    () =>
      Object.values(deviceItems)
        .filter((d) => d.attributes?.cmsv9DeviceId)
        .sort((a, b) => a.name.localeCompare(b.name)),
    [deviceItems],
  );

  const [commands, setCommands] = useState([]);
  const [gatewayNumber, setGatewayNumber] = useState('');
  const [selected, setSelected] = useState({});
  // Arriving straight from a vehicle that was just added, with it already chosen.
  const [deviceId, setDeviceId] = useState(
    () => new URLSearchParams(window.location.search).get('device') || '',
  );
  const [number, setNumber] = useState('');
  const [messages, setMessages] = useState([]);
  const [stalled, setStalled] = useState(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState('');

  const load = async () => {
    try {
      const [saved, history] = await Promise.all([
        request('/commands'),
        request('/messages?limit=50'),
      ]);
      setCommands(saved.commands || []);
      setGatewayNumber(saved.gateway_number || '');
      setSelected(Object.fromEntries((saved.commands || []).map((c) => [c.id, true])));
      setMessages(history.messages || []);
      setStalled(history.nothing_is_collecting ? history.waiting_since : null);
      setError('');
    } catch (e) {
      setError(e.message);
    }
  };

  useEffect(() => {
    load();
    const timer = setInterval(async () => {
      try {
        const history = await request('/messages?limit=50');
        setMessages(history.messages || []);
        setStalled(history.nothing_is_collecting ? history.waiting_since : null);
      } catch {
        // leave the last view in place
      }
    }, 10000);
    return () => clearInterval(timer);
  }, []);

  // Choosing a vehicle fills in its own number, but only on the change of
  // choice: a vehicle reporting its position mid-typing must not overwrite what
  // is being typed, and the number can always be corrected by hand.
  const numberFilledForRef = useRef(undefined);
  useEffect(() => {
    if (numberFilledForRef.current === deviceId) {
      return;
    }
    const device = cameraDevices.find((d) => String(d.id) === String(deviceId));
    if (deviceId && !device) {
      return; // arrived with a vehicle in the link; its details are still loading
    }
    numberFilledForRef.current = deviceId;
    setNumber(device?.attributes?.cmsv9Mobile || device?.phone || '');
  }, [deviceId, cameraDevices]);

  const act = async (key, action) => {
    setBusy(key);
    setNotice('');
    try {
      await action();
      setError('');
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy('');
    }
  };

  const save = () =>
    act('save', async () => {
      const saved = await request('/commands', {
        method: 'PUT',
        body: JSON.stringify({ commands }),
      });
      setCommands(saved.commands || []);
      setNotice('Commands saved.');
    });

  const send = () =>
    act('send', async () => {
      const chosen = commands.filter((c) => selected[c.id]).map((c) => c.id);
      const result = await request('/send', {
        method: 'POST',
        body: JSON.stringify({
          device_id: deviceId ? Number(deviceId) : null,
          to_number: number,
          command_ids: chosen,
        }),
      });
      setNotice(
        `${result.queued.length} message${result.queued.length === 1 ? '' : 's'} queued for ${result.to_number}.`,
      );
      setMessages((await request('/messages?limit=50')).messages || []);
    });

  const update = (id, field, value) =>
    setCommands((current) => current.map((c) => (c.id === id ? { ...c, [field]: value } : c)));

  const status = (value) => {
    const colour = { sent: 'success', failed: 'error', sending: 'warning' }[value] || 'default';
    return <Chip size="small" color={colour} label={value} />;
  };

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
          <Typography variant="h6">Camera setup commands</Typography>
        </Toolbar>
      </AppBar>

      <div className={classes.content}>
        <Typography variant="body2" color="text.secondary">
          These are the text messages that tell a new camera where this server is. They go to the
          SIM inside the DVR — the <b>Mobile No.</b> printed on its label — and are sent by the
          phone
          {gatewayNumber ? ` on ${gatewayNumber}` : ''}, which picks them up from here.
        </Typography>

        {error && (
          <Alert severity="error" onClose={() => setError('')}>
            {error}
          </Alert>
        )}
        {notice && (
          <Alert severity="success" onClose={() => setNotice('')}>
            {notice}
          </Alert>
        )}
        {stalled && (
          <Alert severity="warning">
            {`Nothing is sending these. Messages have been waiting since ${dayjs(stalled).format('D MMM HH:mm')} — queueing them here is not the same as sending them, and they will all go out at once whenever a sender is connected.`}
          </Alert>
        )}

        <Paper variant="outlined" className={classes.card}>
          <Typography variant="subtitle1" gutterBottom>
            Send to a vehicle
          </Typography>
          <div className={classes.send}>
            <TextField
              select
              size="small"
              label="Vehicle"
              value={deviceId}
              onChange={(e) => setDeviceId(e.target.value)}
              sx={{ minWidth: 200 }}
            >
              <MenuItem value="">Not listed — type the number</MenuItem>
              {cameraDevices.map((device) => (
                <MenuItem key={device.id} value={device.id}>
                  {device.name}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              size="small"
              label="DVR mobile number"
              value={number}
              onChange={(e) => setNumber(e.target.value)}
              sx={{ minWidth: 200 }}
            />
            <Button
              variant="contained"
              startIcon={<SendIcon />}
              onClick={send}
              disabled={busy === 'send' || !number || !commands.some((c) => selected[c.id])}
            >
              Send selected
            </Button>
          </div>
        </Paper>

        <Paper variant="outlined" className={classes.card}>
          <Box
            sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}
          >
            <Typography variant="subtitle1">Saved commands</Typography>
            <Box sx={{ display: 'flex', gap: 1 }}>
              <Button
                size="small"
                startIcon={<AddIcon />}
                onClick={() =>
                  setCommands((c) => [
                    ...c,
                    { id: `new-${Date.now()}`, name: '', body: '', enabled: true },
                  ])
                }
              >
                Add
              </Button>
              <Button size="small" variant="outlined" onClick={save} disabled={busy === 'save'}>
                Save
              </Button>
            </Box>
          </Box>
          {commands.map((command) => (
            <div className={classes.row} key={command.id} style={{ marginBottom: 8 }}>
              <Tooltip title="Include when sending">
                <Checkbox
                  checked={Boolean(selected[command.id])}
                  onChange={(e) => setSelected((s) => ({ ...s, [command.id]: e.target.checked }))}
                />
              </Tooltip>
              <TextField
                size="small"
                label="Name"
                value={command.name}
                onChange={(e) => update(command.id, 'name', e.target.value)}
                sx={{ width: 180 }}
              />
              <TextField
                size="small"
                label="Message"
                value={command.body}
                onChange={(e) => update(command.id, 'body', e.target.value)}
                fullWidth
                InputProps={{ className: classes.mono }}
              />
              <IconButton
                onClick={() => setCommands((current) => current.filter((c) => c.id !== command.id))}
                title="Remove"
              >
                <DeleteIcon fontSize="small" />
              </IconButton>
            </div>
          ))}
        </Paper>

        <Paper variant="outlined" className={classes.card}>
          <Typography variant="subtitle1" gutterBottom>
            Recently sent
          </Typography>
          <TableContainer>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>When</TableCell>
                  <TableCell>Vehicle</TableCell>
                  <TableCell>To</TableCell>
                  <TableCell>Command</TableCell>
                  <TableCell>Status</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {messages.map((message) => (
                  <TableRow key={message.id}>
                    <TableCell>
                      {dayjs(message.sent_at || message.queued_at).format('D MMM HH:mm')}
                    </TableCell>
                    <TableCell>{message.device || '-'}</TableCell>
                    <TableCell className={classes.mono}>{message.to}</TableCell>
                    <TableCell>
                      <Tooltip title={message.body}>
                        <span>{message.command || '-'}</span>
                      </Tooltip>
                    </TableCell>
                    <TableCell>
                      <Tooltip title={message.detail || ''}>
                        <span>{status(message.status)}</span>
                      </Tooltip>
                    </TableCell>
                  </TableRow>
                ))}
                {messages.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5} align="center">
                      Nothing sent yet
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </TableContainer>
        </Paper>
      </div>
    </div>
  );
};

export default DvrCommandsPage;
