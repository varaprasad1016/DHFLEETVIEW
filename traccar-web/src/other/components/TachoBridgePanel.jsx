import { useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material';
import DownloadIcon from '@mui/icons-material/Download';
import ContentCopyIcon from '@mui/icons-material/ContentCopy';

const API = '/tacho/api/bridge';

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

const when = (iso) => (iso ? new Date(iso).toLocaleString() : '-');

const StatusChip = ({ online, onLabel = 'Online', offLabel = 'Offline' }) => (
  <Chip size="small" label={online ? onLabel : offLabel} color={online ? 'success' : 'default'} />
);

const CopyField = ({ label, value }) => (
  <TextField
    label={label}
    value={value}
    fullWidth
    margin="dense"
    InputProps={{
      readOnly: true,
      sx: { fontFamily: 'monospace' },
      endAdornment: (
        <Tooltip title="Copy">
          <IconButton size="small" onClick={() => navigator.clipboard?.writeText(value)}>
            <ContentCopyIcon fontSize="small" />
          </IconButton>
        </Tooltip>
      ),
    }}
  />
);

// Tacho Bridge App: installer download, the sign-ins the app connects with, and the
// apps, company cards and card racks that are connected to DH FleetView.
const TachoBridgePanel = () => {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [label, setLabel] = useState('');
  const [created, setCreated] = useState(null);
  const [revoking, setRevoking] = useState(null);
  const [busy, setBusy] = useState('');
  const [checks, setChecks] = useState({});

  const load = async () => {
    try {
      setData(await request('/overview'));
      setError('');
    } catch (e) {
      setError(e.message);
    }
  };

  useEffect(() => {
    load();
    const timer = setInterval(load, 15000);
    return () => clearInterval(timer);
  }, []);

  const act = async (key, action) => {
    setBusy(key);
    try {
      await action();
      setError('');
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy('');
      load();
    }
  };

  const createSignIn = () =>
    act('create', async () => {
      const result = await request('/sign-ins', {
        method: 'POST',
        body: JSON.stringify({ label: label.trim() }),
      });
      setCreated(result);
      setLabel('');
    });

  const revoke = () =>
    act('revoke', async () => {
      await request(`/sign-ins/${revoking.id}`, { method: 'DELETE' });
      setRevoking(null);
    });

  const checkCard = (card) =>
    act(`check-${card.id}`, async () => {
      const result = await request(`/cards/${encodeURIComponent(card.key)}/test`, {
        method: 'POST',
      });
      setChecks((current) => ({ ...current, [card.id]: result }));
    });

  const forget = (node) =>
    act(`forget-${node.id}`, () => request(`/nodes/${node.id}`, { method: 'DELETE' }));

  const signIns = (data?.sign_ins || []).filter((s) => !s.revoked);
  const showCompany = [
    ...(data?.sign_ins || []),
    ...(data?.apps || []),
    ...(data?.cards || []),
  ].some((x) => x.company);

  return (
    <Paper sx={{ p: 2 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 1 }}>
        <Typography variant="h6">Tacho Bridge</Typography>
        <Button size="small" onClick={load}>
          Refresh
        </Button>
      </Box>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Install the Tacho Bridge App on the PC with your company card readers or Lisle card rack. It
        connects securely to DH FleetView and answers company-card authentication during remote
        tachograph downloads.
      </Typography>

      <Box sx={{ display: 'flex', gap: 1, mb: 2, flexWrap: 'wrap', alignItems: 'center' }}>
        <Button
          variant="contained"
          startIcon={<DownloadIcon />}
          href={data?.release?.download || '/tacho/bridge/download'}
          disabled={data !== null && !data.release}
        >
          Download Tacho Bridge App (Windows)
        </Button>
        {data?.release && <Chip size="small" label={`Version ${data.release.version}`} />}
        {data !== null && !data.release && (
          <Typography variant="body2" color="text.secondary">
            The installer hasn&apos;t been published yet.
          </Typography>
        )}
      </Box>

      <Box component="ol" sx={{ pl: 3, mt: 0, mb: 2, '& li': { mb: 0.5 } }}>
        <Typography component="li" variant="body2">
          Install the app and open it (it keeps running in the system tray).
        </Typography>
        <Typography component="li" variant="body2">
          In the app&apos;s settings the server address is{' '}
          <b>{data?.server || 'dhfleetview.co.uk:443'}</b>.
        </Typography>
        <Typography component="li" variant="body2">
          Turn on <b>Server authentication</b> and enter a sign-in created below.
        </Typography>
        <Typography component="li" variant="body2">
          Insert the company cards (or connect the card rack) and add each company card number in
          the app.
        </Typography>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError('')}>
          {error}
        </Alert>
      )}

      <Typography variant="subtitle1" sx={{ mt: 1 }}>
        Sign-ins
      </Typography>
      <Box sx={{ display: 'flex', gap: 1, my: 1, flexWrap: 'wrap', alignItems: 'center' }}>
        <TextField
          size="small"
          label="Name (e.g. Yard office PC)"
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          inputProps={{ maxLength: 80 }}
        />
        <Button variant="outlined" onClick={createSignIn} disabled={busy === 'create'}>
          Create sign-in
        </Button>
      </Box>
      <TableContainer sx={{ mb: 2 }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Name</TableCell>
              {showCompany && <TableCell>Company</TableCell>}
              <TableCell>Username</TableCell>
              <TableCell>Created</TableCell>
              <TableCell>Last used</TableCell>
              <TableCell />
            </TableRow>
          </TableHead>
          <TableBody>
            {signIns.map((s) => (
              <TableRow key={s.id}>
                <TableCell>{s.label || '-'}</TableCell>
                {showCompany && <TableCell>{s.company || '-'}</TableCell>}
                <TableCell sx={{ fontFamily: 'monospace' }}>{s.username}</TableCell>
                <TableCell>{when(s.created_at)}</TableCell>
                <TableCell>{when(s.last_used_at)}</TableCell>
                <TableCell align="right">
                  <Button size="small" color="error" onClick={() => setRevoking(s)}>
                    Revoke
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            {signIns.length === 0 && (
              <TableRow>
                <TableCell colSpan={showCompany ? 6 : 5} align="center">
                  No sign-ins yet — create one for each PC running the app
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>

      <Typography variant="subtitle1">Apps</Typography>
      <TableContainer sx={{ mb: 2 }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>App ID</TableCell>
              {showCompany && <TableCell>Company</TableCell>}
              <TableCell>Version</TableCell>
              <TableCell>Computer</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Last seen</TableCell>
              <TableCell />
            </TableRow>
          </TableHead>
          <TableBody>
            {(data?.apps || []).map((a) => (
              <TableRow key={a.id}>
                <TableCell sx={{ fontFamily: 'monospace' }}>{a.key}</TableCell>
                {showCompany && <TableCell>{a.company || '-'}</TableCell>}
                <TableCell>{a.version || '-'}</TableCell>
                <TableCell>{a.os || '-'}</TableCell>
                <TableCell>
                  <StatusChip online={a.online} />
                </TableCell>
                <TableCell>{a.online ? 'Now' : when(a.last_seen)}</TableCell>
                <TableCell align="right">
                  {!a.online && (
                    <Button
                      size="small"
                      onClick={() => forget(a)}
                      disabled={busy === `forget-${a.id}`}
                    >
                      Remove
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
            {(data?.apps || []).length === 0 && (
              <TableRow>
                <TableCell colSpan={showCompany ? 7 : 6} align="center">
                  No app has connected yet
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>

      <Typography variant="subtitle1">Company cards</Typography>
      <TableContainer sx={{ mb: 2 }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>Card number</TableCell>
              {showCompany && <TableCell>Company</TableCell>}
              <TableCell>In</TableCell>
              <TableCell>Status</TableCell>
              <TableCell>Last check</TableCell>
              <TableCell />
            </TableRow>
          </TableHead>
          <TableBody>
            {(data?.cards || []).map((c) => {
              const check = checks[c.id] || c.last_test;
              return (
                <TableRow key={c.id}>
                  <TableCell sx={{ fontFamily: 'monospace' }}>{c.key}</TableCell>
                  {showCompany && <TableCell>{c.company || '-'}</TableCell>}
                  <TableCell>
                    {c.via === 'rack'
                      ? `Card rack ${c.rack || ''}${c.slot ? `, slot ${c.slot}` : ''}`
                      : 'Card reader'}
                  </TableCell>
                  <TableCell>
                    <StatusChip online={c.online} />
                    {!c.online && c.last_seen && (
                      <Typography variant="caption" color="text.secondary" sx={{ ml: 1 }}>
                        {when(c.last_seen)}
                      </Typography>
                    )}
                  </TableCell>
                  <TableCell>
                    {check ? (
                      <Tooltip title={check.message || ''}>
                        <Chip
                          size="small"
                          label={check.ok ? 'Card OK' : 'Check failed'}
                          color={check.ok ? 'success' : 'warning'}
                        />
                      </Tooltip>
                    ) : (
                      '-'
                    )}
                  </TableCell>
                  <TableCell align="right">
                    {c.online && c.via !== 'rack' && (
                      <Button
                        size="small"
                        onClick={() => checkCard(c)}
                        disabled={busy === `check-${c.id}`}
                      >
                        {busy === `check-${c.id}` ? 'Checking…' : 'Check card'}
                      </Button>
                    )}
                    {!c.online && (
                      <Button
                        size="small"
                        onClick={() => forget(c)}
                        disabled={busy === `forget-${c.id}`}
                      >
                        Remove
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              );
            })}
            {(data?.cards || []).length === 0 && (
              <TableRow>
                <TableCell colSpan={showCompany ? 6 : 5} align="center">
                  No company card has connected yet
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </TableContainer>

      {(data?.racks || []).length > 0 && (
        <>
          <Typography variant="subtitle1">Card racks</Typography>
          <TableContainer sx={{ mb: 1 }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Rack</TableCell>
                  {showCompany && <TableCell>Company</TableCell>}
                  <TableCell>Connected to app</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell>Last seen</TableCell>
                  <TableCell />
                </TableRow>
              </TableHead>
              <TableBody>
                {data.racks.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell sx={{ fontFamily: 'monospace' }}>{r.key}</TableCell>
                    {showCompany && <TableCell>{r.company || '-'}</TableCell>}
                    <TableCell sx={{ fontFamily: 'monospace' }}>{r.app || '-'}</TableCell>
                    <TableCell>
                      <StatusChip online={r.online} onLabel="Linked" />
                    </TableCell>
                    <TableCell>{r.online ? 'Now' : when(r.last_seen)}</TableCell>
                    <TableCell align="right">
                      {!r.online && (
                        <Button
                          size="small"
                          onClick={() => forget(r)}
                          disabled={busy === `forget-${r.id}`}
                        >
                          Remove
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
          <Typography variant="caption" color="text.secondary">
            The rack is detected and linked. Downloads using cards in the rack also need the
            rack&apos;s command protocol on the server, which is being added.
          </Typography>
        </>
      )}

      <Dialog open={Boolean(created)} onClose={() => setCreated(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Sign-in created</DialogTitle>
        <DialogContent>
          <Alert severity="warning" sx={{ mb: 1 }}>
            Copy the password now — it isn&apos;t shown again. Enter these in the Tacho Bridge App
            under Server authentication.
          </Alert>
          <CopyField label="Server address" value={created?.server || ''} />
          <CopyField label="Username" value={created?.username || ''} />
          <CopyField label="Password" value={created?.password || ''} />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setCreated(null)}>Done</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(revoking)} onClose={() => setRevoking(null)}>
        <DialogTitle>Revoke sign-in?</DialogTitle>
        <DialogContent>
          <Typography variant="body2">
            {`Apps using "${revoking?.label || revoking?.username}" are disconnected straight away and can't reconnect until they're given a new sign-in.`}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRevoking(null)}>Cancel</Button>
          <Button color="error" onClick={revoke} disabled={busy === 'revoke'}>
            Revoke
          </Button>
        </DialogActions>
      </Dialog>
    </Paper>
  );
};

export default TachoBridgePanel;
