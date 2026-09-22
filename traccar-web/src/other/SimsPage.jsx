import { useEffect, useState } from 'react';
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
  Paper,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Toolbar,
  Tooltip,
  Typography,
} from '@mui/material';
import { makeStyles } from 'tss-react/mui';
import { useNavigate } from 'react-router-dom';
import RefreshIcon from '@mui/icons-material/Refresh';
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
    padding: theme.spacing(2),
    display: 'flex',
    flexDirection: 'column',
    gap: theme.spacing(2),
  },
  card: { padding: theme.spacing(2) },
  head: { display: 'flex', alignItems: 'center', gap: theme.spacing(1), flexWrap: 'wrap' },
  spacer: { flexGrow: 1 },
  figure: { fontVariantNumeric: 'tabular-nums' },
  code: { fontFamily: 'monospace', fontSize: '0.78rem' },
}));

// What the network says about each camera's SIM. A camera that will not come
// online is nearly always its SIM, and that answer lived in another portal.
const SimsPage = () => {
  const { classes } = useStyles();
  const navigate = useNavigate();

  const [sims, setSims] = useState([]);
  const [withoutSim, setWithoutSim] = useState([]);
  const [portalReady, setPortalReady] = useState(false);
  const [live, setLive] = useState({});
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [confirming, setConfirming] = useState(null);

  const keyOf = (sim) => sim.iccid || sim.msisdn;

  const load = async () => {
    try {
      const listing = await request('');
      setSims(listing.sims || []);
      setWithoutSim(listing.without_sim || []);
      setPortalReady(Boolean(listing.portal_ready));
      setError('');
    } catch (e) {
      setError(e.message);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const checkAll = async () => {
    setChecking(true);
    setNotice('');
    try {
      const answer = await request('/status', { method: 'POST', body: JSON.stringify({}) });
      const byKey = {};
      (answer.sims || []).forEach((sim) => {
        byKey[sim.iccid || sim.msisdn] = sim;
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

        <Paper variant="outlined" className={classes.card}>
          <div className={classes.head}>
            <Typography variant="subtitle1">{`${sims.length} SIM${sims.length === 1 ? '' : 's'}`}</Typography>
            <div className={classes.spacer} />
            <Button
              variant="contained"
              startIcon={checking ? <CircularProgress size={16} /> : <RefreshIcon />}
              onClick={checkAll}
              disabled={checking || !portalReady}
            >
              {checking ? 'Asking the network…' : 'Check all'}
            </Button>
          </div>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Vehicle</TableCell>
                <TableCell>Mobile number</TableCell>
                <TableCell>ICCID</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>This month</TableCell>
                <TableCell align="right">&nbsp;</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {sims.map((sim) => {
                const found = live[keyOf(sim)];
                return (
                  <TableRow key={keyOf(sim)}>
                    <TableCell>{sim.vehicle}</TableCell>
                    <TableCell className={classes.code}>{sim.msisdn || '—'}</TableCell>
                    <TableCell className={classes.code}>
                      {sim.iccid || (
                        <Tooltip title="Not recorded — add it when the label is next photographed">
                          <span>—</span>
                        </Tooltip>
                      )}
                    </TableCell>
                    <TableCell>{statusChip(sim)}</TableCell>
                    <TableCell className={classes.figure}>{usageOf(sim)}</TableCell>
                    <TableCell align="right">
                      {sim.iccid && found?.status && (
                        <Button
                          size="small"
                          color={found.status === 'Active' ? 'warning' : 'primary'}
                          disabled={found.status === 'Closed'}
                          onClick={() => setConfirming({ sim, active: found.status !== 'Active' })}
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
                  <TableCell colSpan={6}>
                    <Typography variant="body2" color="text.secondary">
                      No SIMs recorded yet. They are picked up from vehicles added from a label
                      photo.
                    </Typography>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
          <Typography variant="caption" color="text.secondary">
            Statuses are asked of the network when you press Check all, not on opening the page — a
            fleet takes a few seconds to ask about.
          </Typography>
        </Paper>

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

      <Dialog open={Boolean(confirming)} onClose={() => setConfirming(null)}>
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
