import { useEffect, useRef, useState } from 'react';
import {
  Alert,
  AppBar,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  IconButton,
  MenuItem,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  TextField,
  Toolbar,
  Tooltip,
  Typography,
  useMediaQuery,
  useTheme,
} from '@mui/material';
import { makeStyles } from 'tss-react/mui';
import { useNavigate } from 'react-router-dom';
import dayjs from 'dayjs';
import RefreshIcon from '@mui/icons-material/Refresh';
import UploadIcon from '@mui/icons-material/UploadFile';
import BackIcon from '../common/components/BackIcon';

const API = '/tacho/api/sims';

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
    // A flex child will not shrink below its content without this, and then
    // the scroll never starts - the page just runs off the bottom.
    minHeight: 0,
    padding: theme.spacing(2),
    display: 'flex',
    flexDirection: 'column',
    gap: theme.spacing(2),
  },
  card: { padding: theme.spacing(2), minWidth: 0 },
  head: {
    display: 'flex',
    alignItems: 'center',
    gap: theme.spacing(1),
    flexWrap: 'wrap',
    marginBottom: theme.spacing(1),
    [theme.breakpoints.down('sm')]: { '& > *': { flex: '1 1 100%' } },
  },
  spacer: { flexGrow: 1 },
  figure: { fontVariantNumeric: 'tabular-nums' },
  code: { fontFamily: 'monospace', fontSize: '0.78rem' },
}));

// What the network says about each camera's SIM. A camera that will not come
// online is nearly always its SIM, and that answer lived in another portal.
const SimsPage = () => {
  const { classes } = useStyles();
  const navigate = useNavigate();
  const theme = useTheme();
  // Admin screens are mostly used at a desk, but must still work on a phone:
  // the widest columns are dropped and what is left scrolls sideways.
  const phone = useMediaQuery(theme.breakpoints.down('md'));

  const [sims, setSims] = useState([]);
  const [withoutSim, setWithoutSim] = useState([]);
  const [portalReady, setPortalReady] = useState(false);
  const [live, setLive] = useState({});
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [confirming, setConfirming] = useState(null);
  const [spare, setSpare] = useState([]);
  const [vehicles, setVehicles] = useState([]);
  const [assigning, setAssigning] = useState(null);
  const [nearCutoff, setNearCutoff] = useState([]);
  const [importedAt, setImportedAt] = useState(null);
  const [raising, setRaising] = useState(null);
  const fileInputRef = useRef(null);

  const keyOf = (sim) => `${sim.fitted || 'camera'}:${sim.iccid || sim.msisdn}`;

  const load = async () => {
    try {
      const listing = await request('');
      setSims(listing.sims || []);
      setSpare(listing.spare || []);
      setVehicles(listing.vehicles || []);
      setWithoutSim(listing.without_sim || []);
      setNearCutoff(listing.near_cutoff || []);
      setImportedAt(listing.imported_at || null);
      setPortalReady(Boolean(listing.portal_ready));
      setError('');
    } catch (e) {
      setError(e.message);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const importList = async (file) => {
    if (!file) {
      return;
    }
    setNotice('');
    try {
      const form = new FormData();
      form.append('file', file);
      const response = await fetch(`${API}/import`, {
        method: 'POST',
        credentials: 'include',
        body: form,
      });
      const answer = await response.json();
      if (!response.ok) {
        throw new Error(answer?.detail || `Import failed (${response.status})`);
      }
      setNotice(
        `${answer.added} new SIM${answer.added === 1 ? '' : 's'} imported` +
          `, ${answer.updated} updated` +
          (answer.skipped_total ? `, ${answer.skipped_total} row(s) not understood.` : '.'),
      );
      setError('');
      await load();
    } catch (e) {
      setError(e.message);
    }
  };

  const assignSim = async (iccid, deviceId, fitted) => {
    try {
      await request(`/${iccid}/assign`, {
        method: 'POST',
        body: JSON.stringify({ device_id: deviceId, fitted }),
      });
      setAssigning(null);
      setNotice(deviceId ? 'SIM assigned.' : 'SIM taken out of the vehicle.');
      setError('');
      await load();
    } catch (e) {
      setError(e.message);
    }
  };

  const raiseCutoff = async (sim) => {
    setRaising(sim.iccid);
    try {
      const answer = await request(`/${sim.iccid}/limit`, {
        method: 'POST',
        body: JSON.stringify({}),
      });
      setNotice(
        `${answer.vehicle || answer.iccid} — cut-off raised to ${answer.limit_mb} MB` +
          `, warning at ${answer.warning_mb} MB.`,
      );
      setError('');
      await load();
    } catch (e) {
      setError(e.message);
    } finally {
      setRaising(null);
    }
  };

  const usedOf = (sim) => {
    if (sim.used_mb == null) {
      return '—';
    }
    const limit = sim.limit_mb ? ` of ${sim.limit_mb} MB` : ' MB';
    const share = sim.share_used == null ? '' : ` (${Math.round(sim.share_used * 100)}%)`;
    return `${sim.used_mb.toFixed(0)}${limit}${share}`;
  };

  const checkAll = async () => {
    setChecking(true);
    setNotice('');
    try {
      const answer = await request('/status', { method: 'POST', body: JSON.stringify({}) });
      const byKey = {};
      (answer.sims || []).forEach((sim) => {
        byKey[`${sim.fitted || 'camera'}:${sim.iccid || sim.msisdn}`] = sim;
      });
      setLive(byKey);
      setError('');
    } catch (e) {
      setError(e.message);
    } finally {
      setChecking(false);
    }
  };

  const setActive = async () => {
    const { sim, active } = confirming;
    setConfirming(null);
    try {
      const answer = await request(`/${sim.iccid}/enable`, {
        method: 'POST',
        body: JSON.stringify({ active }),
      });
      setLive((current) => ({
        ...current,
        [keyOf(sim)]: { ...(current[keyOf(sim)] || sim), status: answer.status },
      }));
      setNotice(`${sim.vehicle} — SIM is now ${answer.status}.`);
      setError('');
    } catch (e) {
      setError(e.message);
    }
  };

  const statusChip = (sim) => {
    const found = live[keyOf(sim)];
    if (!found) {
      return <Chip size="small" variant="outlined" label="not checked" />;
    }
    if (found.problem) {
      return (
        <Tooltip title={found.problem}>
          <Chip size="small" color="error" label="portal refused" />
        </Tooltip>
      );
    }
    const colour = { Active: 'success', Deactivated: 'warning', Closed: 'error' };
    return <Chip size="small" color={colour[found.status] || 'default'} label={found.status} />;
  };

  const usageOf = (sim) => {
    const found = live[keyOf(sim)];
    if (!found?.usage) {
      return '—';
    }
    const { data_mb: data, sms } = found.usage;
    const parts = [];
    if (data != null) parts.push(`${data.toFixed(1)} MB`);
    if (sms != null) parts.push(`${sms} SMS`);
    return parts.join(' · ') || '—';
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
          <Typography variant="h6">SIM management</Typography>
        </Toolbar>
      </AppBar>

      <div className={classes.content}>
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
        {!portalReady && (
          <Alert severity="warning">
            The SIM portal is not set up on this server yet, so statuses cannot be checked. Set
            SMS_URL, SMS_USERNAME and SMS_PASSWORD and restart the tacho-api task.
          </Alert>
        )}

        {nearCutoff.length > 0 && (
          <Paper variant="outlined" className={classes.card}>
            <Typography variant="subtitle1" gutterBottom>
              {`${nearCutoff.length} SIM${nearCutoff.length === 1 ? '' : 's'} heading for cut-off`}
            </Typography>
            <Typography variant="body2" color="text.secondary" gutterBottom>
              At its limit the provider disables the SIM&apos;s traffic and the camera goes dark.
              Raising the cut-off moves it to the next level up and sets the warning halfway.
            </Typography>
            <Box sx={{ overflowX: 'auto' }}>
              <Table size="small">
                <TableBody>
                  {nearCutoff.map((sim) => (
                    <TableRow key={sim.iccid}>
                      <TableCell>{sim.vehicle || sim.msisdn}</TableCell>
                      <TableCell className={classes.figure}>{usedOf(sim)}</TableCell>
                      <TableCell align="right">
                        <Button
                          size="small"
                          variant="contained"
                          disabled={raising === sim.iccid}
                          onClick={() => raiseCutoff(sim)}
                        >
                          {raising === sim.iccid ? 'Raising…' : 'Raise cut-off'}
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Box>
          </Paper>
        )}

        <Paper variant="outlined" className={classes.card}>
          <div className={classes.head}>
            <Typography variant="subtitle1">{`${sims.length} SIM${sims.length === 1 ? '' : 's'}`}</Typography>
            <div className={classes.spacer} />
            <Button startIcon={<UploadIcon />} onClick={() => fileInputRef.current?.click()}>
              Import SIM list
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".xlsx,.csv,text/csv"
              hidden
              onChange={(e) => {
                importList(e.target.files?.[0]);
                e.target.value = '';
              }}
            />
            <Button
              variant="contained"
              startIcon={checking ? <CircularProgress size={16} /> : <RefreshIcon />}
              onClick={checkAll}
              disabled={checking || !portalReady}
            >
              {checking ? 'Asking the network…' : 'Check all'}
            </Button>
          </div>
          <Box sx={{ overflowX: 'auto' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Vehicle</TableCell>
                  <TableCell>Fitted to</TableCell>
                  <TableCell>Mobile number</TableCell>
                  {!phone && <TableCell>ICCID</TableCell>}
                  <TableCell>Status</TableCell>
                  <TableCell>Data this month</TableCell>
                  <TableCell align="right">&nbsp;</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {sims.map((sim) => {
                  const found = live[keyOf(sim)];
                  return (
                    <TableRow key={keyOf(sim)}>
                      <TableCell>{sim.vehicle}</TableCell>
                      <TableCell>
                        <Chip
                          size="small"
                          variant="outlined"
                          label={sim.fitted === 'tracker' ? 'Tracker' : 'Camera'}
                        />
                      </TableCell>
                      <TableCell className={classes.code}>{sim.msisdn || '—'}</TableCell>
                      {!phone && (
                        <TableCell className={classes.code}>
                          {sim.iccid || (
                            <Tooltip title="Not recorded — add it when the label is next photographed">
                              <span>—</span>
                            </Tooltip>
                          )}
                        </TableCell>
                      )}
                      <TableCell>{statusChip(sim)}</TableCell>
                      <TableCell className={classes.figure}>
                        {sim.used_mb == null ? usageOf(sim) : usedOf(sim)}
                        {sim.near_cutoff && (
                          <Chip size="small" color="warning" label="near cut-off" sx={{ ml: 1 }} />
                        )}
                      </TableCell>
                      <TableCell align="right">
                        {sim.iccid && found?.status && (
                          <Button
                            size="small"
                            color={found.status === 'Active' ? 'warning' : 'primary'}
                            disabled={found.status === 'Closed'}
                            onClick={() =>
                              setConfirming({ sim, active: found.status !== 'Active' })
                            }
                          >
                            {found.status === 'Active' ? 'Deactivate' : 'Activate'}
                          </Button>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
                {!sims.length && (
                  <TableRow>
                    <TableCell colSpan={phone ? 6 : 7}>
                      <Typography variant="body2" color="text.secondary">
                        No SIMs recorded yet. They are picked up from vehicles added from a label
                        photo.
                      </Typography>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </Box>
          <Typography variant="caption" color="text.secondary">
            Statuses are asked of the network when you press Check all, not on opening the page — a
            fleet takes a few seconds to ask about. Data usage is from the last import
            {importedAt ? ` on ${dayjs(importedAt).format('D MMM HH:mm')}` : ''}.
          </Typography>
        </Paper>

        {spare.length > 0 && (
          <Paper variant="outlined" className={classes.card}>
            <Typography variant="subtitle1" gutterBottom>
              {`${spare.length} SIM${spare.length === 1 ? '' : 's'} not in a vehicle`}
            </Typography>
            <Box sx={{ overflowX: 'auto' }}>
              <Table size="small">
                <TableHead>
                  <TableRow>
                    <TableCell>Mobile number</TableCell>
                    {!phone && <TableCell>ICCID</TableCell>}
                    <TableCell>Status</TableCell>
                    {!phone && <TableCell>Used</TableCell>}
                    <TableCell align="right">&nbsp;</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {spare.map((sim) => (
                    <TableRow key={sim.iccid}>
                      <TableCell className={classes.code}>{sim.msisdn || '—'}</TableCell>
                      {!phone && <TableCell className={classes.code}>{sim.iccid}</TableCell>}
                      <TableCell>
                        <Chip
                          size="small"
                          color={sim.status === 'Active' ? 'success' : 'default'}
                          label={sim.status || 'unknown'}
                        />
                      </TableCell>
                      {!phone && (
                        <TableCell className={classes.figure}>
                          {sim.data_mb == null ? '—' : `${sim.data_mb.toFixed(1)} MB`}
                        </TableCell>
                      )}
                      <TableCell align="right">
                        <Button
                          size="small"
                          onClick={() => setAssigning({ sim, deviceId: '', fitted: 'camera' })}
                        >
                          Assign
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </Box>
            <Typography variant="caption" color="text.secondary">
              Imported from the provider&apos;s SIM list. Assigning one writes its number and ICCID
              onto the vehicle.
            </Typography>
          </Paper>
        )}

        {withoutSim.length > 0 && (
          <Paper variant="outlined" className={classes.card}>
            <Typography variant="subtitle1" gutterBottom>
              Vehicles with no SIM recorded
            </Typography>
            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
              {withoutSim.map((name) => (
                <Chip key={name} size="small" variant="outlined" label={name} />
              ))}
            </Box>
            <Typography variant="caption" color="text.secondary">
              These have no mobile number or ICCID stored, so the network cannot be asked about
              them. Photographing the DVR label records both.
            </Typography>
          </Paper>
        )}
      </div>

      <Dialog
        open={Boolean(assigning)}
        onClose={() => setAssigning(null)}
        fullScreen={phone}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle>
          Assign SIM
          <Typography variant="body2" color="text.secondary">
            {assigning?.sim?.msisdn || assigning?.sim?.iccid}
          </Typography>
        </DialogTitle>
        <DialogContent>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}>
            <TextField
              select
              size="small"
              label="Vehicle"
              value={assigning?.deviceId ?? ''}
              onChange={(e) => setAssigning({ ...assigning, deviceId: e.target.value })}
            >
              {vehicles.map((vehicle) => (
                <MenuItem key={vehicle.id} value={vehicle.id}>
                  {vehicle.name}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              select
              size="small"
              label="Fitted to"
              value={assigning?.fitted ?? 'camera'}
              onChange={(e) => setAssigning({ ...assigning, fitted: e.target.value })}
              helperText="Which unit on that vehicle this SIM is in"
            >
              <MenuItem value="camera">Camera</MenuItem>
              <MenuItem value="tracker">Tracker</MenuItem>
            </TextField>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setAssigning(null)}>Cancel</Button>
          <Button
            variant="contained"
            disabled={!assigning?.deviceId}
            onClick={() => assignSim(assigning.sim.iccid, assigning.deviceId, assigning.fitted)}
          >
            Assign
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog open={Boolean(confirming)} onClose={() => setConfirming(null)} fullScreen={phone}>
        <DialogTitle>
          {confirming?.active ? 'Activate this SIM?' : 'Deactivate this SIM?'}
        </DialogTitle>
        <DialogContent>
          <DialogContentText>
            {confirming?.active
              ? `${confirming?.sim?.vehicle} will be able to carry traffic again. Its camera should come back online by itself.`
              : `${confirming?.sim?.vehicle} will stop carrying traffic and its camera will go dark until the SIM is turned back on. The tariff is unchanged, so this does not reduce what the SIM costs.`}
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirming(null)}>Cancel</Button>
          <Button
            variant="contained"
            color={confirming?.active ? 'primary' : 'warning'}
            onClick={setActive}
          >
            {confirming?.active ? 'Activate' : 'Deactivate'}
          </Button>
        </DialogActions>
      </Dialog>
    </div>
  );
};

export default SimsPage;
