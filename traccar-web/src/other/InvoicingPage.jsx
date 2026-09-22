import { useEffect, useState } from 'react';
import {
  Alert,
  AppBar,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
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
  Typography,
  useMediaQuery,
  useTheme,
} from '@mui/material';
import { makeStyles } from 'tss-react/mui';
import { useNavigate } from 'react-router-dom';
import dayjs from 'dayjs';
import ReceiptIcon from '@mui/icons-material/ReceiptLong';
import DownloadIcon from '@mui/icons-material/Download';
import OpenInNewIcon from '@mui/icons-material/OpenInNew';
import BackIcon from '../common/components/BackIcon';

const API = '/tacho/api/billing';

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

const money = (value) =>
  `£${Number(value || 0).toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const useStyles = makeStyles()((theme) => ({
  root: { height: '100%', display: 'flex', flexDirection: 'column' },
  content: {
    flexGrow: 1,
    overflowY: 'auto',
    overflowX: 'hidden',
    minWidth: 0,
    padding: theme.spacing(2),
    display: 'flex',
    flexDirection: 'column',
    gap: theme.spacing(2),
  },
  card: { padding: theme.spacing(2), minWidth: 0, overflow: 'hidden' },
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
  form: { display: 'flex', flexDirection: 'column', gap: theme.spacing(2), minWidth: 0 },
  rates: { display: 'flex', gap: theme.spacing(1), flexWrap: 'wrap' },
}));

const statusColour = { sent: 'success', failed: 'error', draft: 'default' };

// Invoicing, for the super administrator: who is billed, what they pay, and
// every invoice that has gone out.
const InvoicingPage = () => {
  const { classes } = useStyles();
  const navigate = useNavigate();
  const theme = useTheme();
  // Mostly used at a desk, but must still work on a phone: the columns that
  // can be worked out from the others are dropped, and the rest scrolls.
  const phone = useMediaQuery(theme.breakpoints.down('md'));

  const [overview, setOverview] = useState(null);
  const [invoices, setInvoices] = useState([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState('');
  const [editing, setEditing] = useState(null);
  const [preview, setPreview] = useState(null);
  const [viewing, setViewing] = useState(null);
  const [month, setMonth] = useState(() => dayjs().format('YYYY-MM'));

  const load = async () => {
    try {
      const [summary, listing] = await Promise.all([
        request('/overview'),
        request('/invoices?limit=200'),
      ]);
      setOverview(summary);
      setInvoices(listing.invoices || []);
      setError('');
    } catch (e) {
      setError(e.message);
    }
  };

  useEffect(() => {
    load();
  }, []);

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

  const saveAccount = () =>
    act('save', async () => {
      const { user_id: userId, ...rest } = editing;
      await request(`/accounts/${userId}`, { method: 'PUT', body: JSON.stringify(rest) });
      setEditing(null);
      setNotice('Account saved.');
      await load();
    });

  const showPreview = (account) =>
    act(`preview-${account.user_id}`, async () => {
      const [year, monthNumber] = month.split('-');
      const quote = await request('/preview', {
        method: 'POST',
        body: JSON.stringify({
          user_id: account.user_id,
          year: Number(year),
          month: Number(monthNumber),
        }),
      });
      setPreview(quote);
    });

  const runMonth = () =>
    act('run', async () => {
      const [year, monthNumber] = month.split('-');
      const result = await request('/run', {
        method: 'POST',
        body: JSON.stringify({ year: Number(year), month: Number(monthNumber) }),
      });
      const raised = result.raised?.length || 0;
      setNotice(
        raised
          ? `${raised} invoice${raised === 1 ? '' : 's'} raised as draft${raised === 1 ? '' : 's'}.`
          : 'Nothing to raise — every active account is already invoiced for that month.',
      );
      await load();
    });

  const startBilling = (candidate) =>
    setEditing({
      user_id: candidate.id,
      name: candidate.name,
      account_email: candidate.email,
      started_on: dayjs().format('YYYY-MM-DD'),
      invoicing_email: '',
      rates: { tracking: '', camera: '', tachograph: '' },
      isNew: true,
    });

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
          <Typography variant="h6">Invoicing</Typography>
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
        {overview?.not_ready?.length > 0 && (
          <Alert severity="warning">
            <Typography variant="subtitle2">Invoices cannot be emailed yet</Typography>
            <ul style={{ margin: '4px 0 0', paddingLeft: 18 }}>
              {overview.not_ready.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          </Alert>
        )}

        <Paper variant="outlined" className={classes.card}>
          <div className={classes.head}>
            <Typography variant="subtitle1">Customers billed</Typography>
            <div className={classes.spacer} />
            <TextField
              size="small"
              type="month"
              label="Month"
              value={month}
              onChange={(e) => setMonth(e.target.value)}
              slotProps={{ inputLabel: { shrink: true } }}
            />
            <Button variant="contained" onClick={runMonth} disabled={busy === 'run'}>
              {busy === 'run' ? 'Raising…' : 'Raise invoices'}
            </Button>
          </div>
          <Box sx={{ overflowX: 'auto' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Customer</TableCell>
                  <TableCell>Billed from</TableCell>
                  {!phone && <TableCell>Invoices go to</TableCell>}
                  {!phone && <TableCell>Rates</TableCell>}
                  <TableCell align="right">&nbsp;</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {(overview?.accounts || []).map((account) => (
                  <TableRow key={account.user_id}>
                    <TableCell>
                      {account.name}
                      {!account.active && <Chip size="small" label="paused" sx={{ ml: 1 }} />}
                    </TableCell>
                    <TableCell>{dayjs(account.started_on).format('D MMM YYYY')}</TableCell>
                    {!phone && (
                      <TableCell>
                        {account.send_to || '—'}
                        {account.invoicing_email && (
                          <Chip size="small" variant="outlined" label="invoicing" sx={{ ml: 1 }} />
                        )}
                      </TableCell>
                    )}
                    {!phone && (
                      <TableCell className={classes.figure}>
                        {['tracking', 'camera', 'tachograph']
                          .map((item) =>
                            account.rates[item] == null
                              ? money(overview.standard_rates[item])
                              : `${money(account.rates[item])}*`,
                          )
                          .join(' / ')}
                      </TableCell>
                    )}
                    <TableCell align="right">
                      <Button
                        size="small"
                        onClick={() => showPreview(account)}
                        disabled={busy === `preview-${account.user_id}`}
                      >
                        Preview
                      </Button>
                      <Button size="small" onClick={() => setEditing({ ...account })}>
                        Edit
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {!overview?.accounts?.length && (
                  <TableRow>
                    <TableCell colSpan={phone ? 3 : 5}>
                      <Typography variant="body2" color="text.secondary">
                        No customers are being billed yet. Pick one below to start.
                      </Typography>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </Box>
          <Typography variant="caption" color="text.secondary">
            Rates are tracking / camera / tachograph per vehicle per month. An asterisk marks a rate
            agreed with that customer; the rest are the standard rates.
          </Typography>
        </Paper>

        {overview?.candidates?.length > 0 && (
          <Paper variant="outlined" className={classes.card}>
            <Typography variant="subtitle1" gutterBottom>
              Not billed yet
            </Typography>
            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
              {overview.candidates.map((candidate) => (
                <Button
                  key={candidate.id}
                  size="small"
                  variant="outlined"
                  onClick={() => startBilling(candidate)}
                >
                  {candidate.name}
                </Button>
              ))}
            </Box>
          </Paper>
        )}

        <Paper variant="outlined" className={classes.card}>
          <Typography variant="subtitle1" gutterBottom>
            Invoices issued
          </Typography>
          <Box sx={{ overflowX: 'auto' }}>
            <Table size="small">
              <TableHead>
                <TableRow>
                  <TableCell>Number</TableCell>
                  <TableCell>Customer</TableCell>
                  <TableCell>Period</TableCell>
                  {!phone && <TableCell align="right">Net</TableCell>}
                  {!phone && <TableCell align="right">VAT</TableCell>}
                  <TableCell align="right">Total</TableCell>
                  <TableCell>Status</TableCell>
                  <TableCell align="right">&nbsp;</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {invoices.map((invoice) => (
                  <TableRow key={invoice.id}>
                    <TableCell>{invoice.number}</TableCell>
                    <TableCell>{invoice.account}</TableCell>
                    <TableCell>{invoice.period}</TableCell>
                    {!phone && (
                      <TableCell align="right" className={classes.figure}>
                        {money(invoice.net)}
                      </TableCell>
                    )}
                    {!phone && (
                      <TableCell align="right" className={classes.figure}>
                        {money(invoice.vat)}
                      </TableCell>
                    )}
                    <TableCell align="right" className={classes.figure}>
                      {money(invoice.total)}
                    </TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        color={statusColour[invoice.status] || 'default'}
                        label={
                          invoice.status === 'sent' && invoice.sent_at
                            ? `sent ${dayjs(invoice.sent_at).format('D MMM')}`
                            : invoice.status
                        }
                      />
                    </TableCell>
                    <TableCell align="right">
                      <Button
                        size="small"
                        startIcon={<ReceiptIcon />}
                        onClick={() => setViewing(invoice)}
                      >
                        View
                      </Button>
                      <Button
                        size="small"
                        startIcon={<DownloadIcon />}
                        href={`${API}/invoices/${invoice.id}/pdf?download=1`}
                      >
                        Download
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
                {!invoices.length && (
                  <TableRow>
                    <TableCell colSpan={phone ? 6 : 8}>
                      <Typography variant="body2" color="text.secondary">
                        No invoices yet.
                      </Typography>
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </Box>
        </Paper>
      </div>

      <Dialog open={Boolean(editing)} onClose={() => setEditing(null)} fullScreen={phone}>
        <DialogTitle>
          {editing?.isNew ? `Start billing ${editing?.name}` : editing?.name}
        </DialogTitle>
        <DialogContent>
          <div className={classes.form} style={{ paddingTop: 8 }}>
            <TextField
              size="small"
              type="date"
              label="Billed from"
              value={editing?.started_on || ''}
              onChange={(e) => setEditing({ ...editing, started_on: e.target.value })}
              slotProps={{ inputLabel: { shrink: true } }}
              helperText="The first invoice runs from this day to the end of that month."
            />
            <TextField
              size="small"
              label="Invoicing email"
              value={editing?.invoicing_email || ''}
              onChange={(e) => setEditing({ ...editing, invoicing_email: e.target.value })}
              helperText={`Leave blank to use ${editing?.account_email || 'the signup address'}.`}
            />
            <div className={classes.rates}>
              {['tracking', 'camera', 'tachograph'].map((item) => (
                <TextField
                  key={item}
                  size="small"
                  label={item}
                  value={editing?.rates?.[item] ?? ''}
                  onChange={(e) =>
                    setEditing({
                      ...editing,
                      rates: { ...editing.rates, [item]: e.target.value },
                    })
                  }
                  sx={{ width: 110 }}
                  placeholder={String(overview?.standard_rates?.[item] ?? '')}
                />
              ))}
            </div>
            <Typography variant="caption" color="text.secondary">
              Leave a rate blank to use the standard one.
            </Typography>
            {!editing?.isNew && (
              <TextField
                select
                size="small"
                label="Billing"
                value={editing?.active ? 'active' : 'paused'}
                onChange={(e) => setEditing({ ...editing, active: e.target.value === 'active' })}
              >
                <MenuItem value="active">Active</MenuItem>
                <MenuItem value="paused">Paused — raise no invoices</MenuItem>
              </TextField>
            )}
          </div>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setEditing(null)}>Cancel</Button>
          <Button variant="contained" onClick={saveAccount} disabled={busy === 'save'}>
            Save
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog
        open={Boolean(viewing)}
        onClose={() => setViewing(null)}
        maxWidth="md"
        fullWidth
        fullScreen={phone}
        slotProps={{ paper: { sx: { height: '92vh' } } }}
      >
        <DialogTitle>
          {viewing?.number}
          <Typography variant="body2" color="text.secondary">
            {`${viewing?.account} — ${viewing?.period}`}
          </Typography>
        </DialogTitle>
        <DialogContent dividers sx={{ p: 0 }}>
          {viewing && (
            <iframe
              title={`Invoice ${viewing.number}`}
              src={`${API}/invoices/${viewing.id}/pdf`}
              style={{ width: '100%', height: '100%', border: 0, display: 'block' }}
            />
          )}
        </DialogContent>
        <DialogActions>
          <Button
            startIcon={<OpenInNewIcon />}
            href={viewing ? `${API}/invoices/${viewing.id}/pdf` : undefined}
            target="_blank"
            rel="noopener noreferrer"
          >
            Open in a tab
          </Button>
          <Button
            variant="contained"
            startIcon={<DownloadIcon />}
            href={viewing ? `${API}/invoices/${viewing.id}/pdf?download=1` : undefined}
          >
            Download
          </Button>
          <Button onClick={() => setViewing(null)}>Close</Button>
        </DialogActions>
      </Dialog>

      <Dialog
        open={Boolean(preview)}
        onClose={() => setPreview(null)}
        maxWidth="sm"
        fullWidth
        fullScreen={phone}
      >
        <DialogTitle>
          {preview?.account}
          <Typography variant="body2" color="text.secondary">
            {preview?.period} — nothing is issued or sent
          </Typography>
        </DialogTitle>
        <DialogContent>
          <Box sx={{ overflowX: 'auto' }}>
            <Table size="small">
              <TableBody>
                {(preview?.lines || []).map((line) => (
                  <TableRow key={`${line.vehicle}-${line.item}`}>
                    <TableCell>{line.description}</TableCell>
                    <TableCell align="right" className={classes.figure}>
                      {money(line.amount)}
                    </TableCell>
                  </TableRow>
                ))}
                {!preview?.lines?.length && (
                  <TableRow>
                    <TableCell>Nothing chargeable this period.</TableCell>
                  </TableRow>
                )}
                <TableRow>
                  <TableCell align="right">Net</TableCell>
                  <TableCell align="right" className={classes.figure}>
                    {money(preview?.net)}
                  </TableCell>
                </TableRow>
                <TableRow>
                  <TableCell align="right">VAT</TableCell>
                  <TableCell align="right" className={classes.figure}>
                    {money(preview?.vat)}
                  </TableCell>
                </TableRow>
                <TableRow>
                  <TableCell align="right">
                    <b>Total</b>
                  </TableCell>
                  <TableCell align="right" className={classes.figure}>
                    <b>{money(preview?.total)}</b>
                  </TableCell>
                </TableRow>
              </TableBody>
            </Table>
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPreview(null)}>Close</Button>
        </DialogActions>
      </Dialog>
    </div>
  );
};

export default InvoicingPage;
