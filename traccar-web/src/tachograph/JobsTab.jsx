import { useCallback, useEffect, useState } from 'react';
import {
  Box, Button, Card, CardContent, Chip, Dialog, DialogTitle, DialogContent,
  DialogActions, TextField, Typography, Table, TableBody, TableCell,
  TableContainer, TableHead, TableRow, Paper, MenuItem, IconButton,
  Alert, Snackbar, Tabs, Tab, Badge,
} from '@mui/material';
import { makeStyles } from 'tss-react/mui';
import AddIcon from '@mui/icons-material/Add';
import CancelIcon from '@mui/icons-material/Cancel';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import WarningIcon from '@mui/icons-material/Warning';
import {
  createJob, listJobs, cancelJob, completeJob,
} from '../common/util/shifts';
import { useSelector } from 'react-redux';

const useStyles = makeStyles()((theme) => ({
  root: { p: 2 },
  header: { display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 },
  tabContent: { mt: 2 },
  priorityLow: { borderLeft: `4px solid ${theme.palette.grey[400]}` },
  priorityNormal: { borderLeft: `4px solid ${theme.palette.primary.main}` },
  priorityUrgent: { borderLeft: `4px solid ${theme.palette.error.main}` },
  statusPending: { bgcolor: 'warning.light', color: 'warning.contrastText' },
  statusAccepted: { bgcolor: 'success.light', color: 'success.contrastText' },
  statusDenied: { bgcolor: 'error.light', color: 'error.contrastText' },
  statusCompleted: { bgcolor: 'grey.300', color: 'text.primary' },
  statusCancelled: { bgcolor: 'grey.200', color: 'text.secondary' },
}));

const JobCreateDialog = ({ open, onClose, onCreated, drivers }) => {
  const [form, setForm] = useState({
    driver_name: '',
    vehicle_reg: '',
    title: '',
    description: '',
    pickup_location: '',
    dropoff_location: '',
    priority: 'normal',
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleSubmit = useCallback(async () => {
    if (!form.driver_name || !form.title) {
      setError('Driver name and title are required.');
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await createJob(form);
      onCreated();
      setForm({ driver_name: '', vehicle_reg: '', title: '', description: '', pickup_location: '', dropoff_location: '', priority: 'normal' });
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [form, onCreated]);

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>Send Job to Driver</DialogTitle>
      <DialogContent>
        {error && <Alert severity="error" sx={{ mb: 1 }}>{error}</Alert>}
        <TextField
          select label="Driver Name" value={form.driver_name}
          onChange={(e) => setForm({ ...form, driver_name: e.target.value })}
          fullWidth size="small" sx={{ mb: 1.5 }}
        >
          {drivers.map((d) => (
            <MenuItem key={d.name} value={d.name}>{d.name}</MenuItem>
          ))}
          <MenuItem value="__custom">Other (type below)</MenuItem>
        </TextField>
        {form.driver_name === '__custom' && (
          <TextField
            label="Driver Name" value=""
            onChange={(e) => setForm({ ...form, driver_name: e.target.value })}
            fullWidth size="small" sx={{ mb: 1.5 }}
          />
        )}
        <TextField
          label="Job Title" value={form.title}
          onChange={(e) => setForm({ ...form, title: e.target.value })}
          fullWidth size="small" sx={{ mb: 1.5 }}
        />
        <TextField
          label="Description" value={form.description}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
          fullWidth size="small" multiline rows={2} sx={{ mb: 1.5 }}
        />
        <TextField
          label="Vehicle Registration" value={form.vehicle_reg}
          onChange={(e) => setForm({ ...form, vehicle_reg: e.target.value })}
          fullWidth size="small" sx={{ mb: 1.5 }}
        />
        <TextField
          label="Pickup Location" value={form.pickup_location}
          onChange={(e) => setForm({ ...form, pickup_location: e.target.value })}
          fullWidth size="small" sx={{ mb: 1.5 }}
        />
        <TextField
          label="Drop-off Location" value={form.dropoff_location}
          onChange={(e) => setForm({ ...form, dropoff_location: e.target.value })}
          fullWidth size="small" sx={{ mb: 1.5 }}
        />
        <TextField
          select label="Priority" value={form.priority}
          onChange={(e) => setForm({ ...form, priority: e.target.value })}
          fullWidth size="small"
        >
          <MenuItem value="low">Low</MenuItem>
          <MenuItem value="normal">Normal</MenuItem>
          <MenuItem value="urgent">Urgent</MenuItem>
        </TextField>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button onClick={handleSubmit} variant="contained" disabled={loading}>
          {loading ? 'Sending...' : 'Send Job'}
        </Button>
      </DialogActions>
    </Dialog>
  );
};

const JobsTab = () => {
  const classes = useStyles();
  const [jobs, setJobs] = useState([]);
  const [tab, setTab] = useState(0);
  const [createOpen, setCreateOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState('');

  const devices = useSelector((state) => Object.values(state.devices.items));
  const drivers = useSelector((state) => {
    const driverSet = new Set();
    Object.values(state.devices.items).forEach((d) => {
      if (d.driverUniqueId) driverSet.add(d.driverUniqueId);
    });
    return Array.from(driverSet).map((name) => ({ name }));
  });

  const statusFilter = ['all', 'pending', 'accepted', 'denied', 'completed', 'cancelled'];
  const currentFilter = statusFilter[tab];
  const filteredJobs = currentFilter === 'all' ? jobs : jobs.filter((j) => j.status === currentFilter);

  const loadJobs = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listJobs();
      setJobs(data || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadJobs(); }, [loadJobs]);

  const handleCancel = useCallback(async (jobId) => {
    try {
      await cancelJob(jobId);
      await loadJobs();
      setSuccess('Job cancelled.');
    } catch (e) {
      setError(e.message);
    }
  }, [loadJobs]);

  const pendingCount = jobs.filter((j) => j.status === 'pending').length;
  const acceptedCount = jobs.filter((j) => j.status === 'accepted').length;

  const getStatusColor = (status) => {
    switch (status) {
      case 'pending': return 'warning';
      case 'accepted': return 'success';
      case 'denied': return 'error';
      case 'completed': return 'default';
      case 'cancelled': return 'default';
      default: return 'default';
    }
  };

  const getPriorityColor = (priority) => {
    switch (priority) {
      case 'urgent': return 'error';
      case 'normal': return 'primary';
      case 'low': return 'default';
      default: return 'default';
    }
  };

  return (
    <Box className={classes.root}>
      <Box className={classes.header}>
        <Typography variant="h6">Job Management</Typography>
        <Button
          variant="contained"
          startIcon={<AddIcon />}
          onClick={() => setCreateOpen(true)}
        >
          Send Job
        </Button>
      </Box>

      <Tabs value={tab} onChange={(_, v) => setTab(v)} variant="scrollable" scrollButtons="auto">
        <Tab label={<Badge badgeContent={jobs.length} color="default">All</Badge>} />
        <Tab label={<Badge badgeContent={pendingCount} color="warning">Pending</Badge>} />
        <Tab label={<Badge badgeContent={acceptedCount} color="success">Accepted</Badge>} />
        <Tab label="Denied" />
        <Tab label="Completed" />
        <Tab label="Cancelled" />
      </Tabs>

      <Box className={classes.tabContent}>
        <TableContainer component={Paper}>
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell>Job</TableCell>
                <TableCell>Driver</TableCell>
                <TableCell>Vehicle</TableCell>
                <TableCell>Priority</TableCell>
                <TableCell>Status</TableCell>
                <TableCell>Created</TableCell>
                <TableCell>Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {filteredJobs.map((job) => (
                <TableRow key={job.id} sx={{ borderLeft: `4px solid ${
                  job.priority === 'urgent' ? '#f44336' :
                  job.priority === 'normal' ? '#1976d2' : '#bdbdbd'
                }` }}>
                  <TableCell>
                    <Typography variant="body2" fontWeight={600}>{job.title}</Typography>
                    {job.deny_reason && (
                      <Typography variant="caption" color="error">Reason: {job.deny_reason}</Typography>
                    )}
                  </TableCell>
                  <TableCell>{job.driver_name}</TableCell>
                  <TableCell>{job.vehicle_reg || '-'}</TableCell>
                  <TableCell>
                    <Chip size="small" label={job.priority} color={getPriorityColor(job.priority)} />
                  </TableCell>
                  <TableCell>
                    <Chip size="small" label={job.status} color={getStatusColor(job.status)} />
                  </TableCell>
                  <TableCell>
                    {job.assigned_at ? new Date(job.assigned_at).toLocaleString() : '-'}
                  </TableCell>
                  <TableCell>
                    {(job.status === 'pending' || job.status === 'accepted') && (
                      <IconButton
                        size="small"
                        color="error"
                        onClick={() => handleCancel(job.id)}
                        title="Cancel job"
                      >
                        <CancelIcon fontSize="small" />
                      </IconButton>
                    )}
                  </TableCell>
                </TableRow>
              ))}
              {filteredJobs.length === 0 && (
                <TableRow>
                  <TableCell colSpan={7} align="center">
                    <Typography color="text.secondary">
                      {loading ? 'Loading...' : 'No jobs found'}
                    </Typography>
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TableContainer>
      </Box>

      <JobCreateDialog
        open={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={() => { setCreateOpen(false); loadJobs(); }}
        drivers={drivers}
      />

      <Snackbar open={!!success} autoHideDuration={3000} onClose={() => setSuccess('')}>
        <Alert severity="success" onClose={() => setSuccess('')}>{success}</Alert>
      </Snackbar>
      {error && (
        <Snackbar open autoHideDuration={5000} onClose={() => setError(null)}>
          <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>
        </Snackbar>
      )}
    </Box>
  );
};

export default JobsTab;
