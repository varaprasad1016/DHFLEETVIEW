import { useCallback, useEffect, useRef, useState } from 'react';
import {
  AppBar, Toolbar, IconButton, Typography, Button, Box, Card, CardContent,
  TextField, Chip, CircularProgress, Dialog, DialogTitle, DialogContent,
  DialogActions, List, ListItem, ListItemText, ListItemSecondaryAction,
  Divider, Alert, Snackbar, Badge,
} from '@mui/material';
import { makeStyles } from 'tss-react/mui';
import { useNavigate } from 'react-router-dom';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import StopIcon from '@mui/icons-material/Stop';
import PauseIcon from '@mui/icons-material/Pause';
import PlayCircleIcon from '@mui/icons-material/PlayCircle';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import CancelIcon from '@mui/icons-material/Cancel';
import CameraAltIcon from '@mui/icons-material/CameraAlt';
import AssignmentIcon from '@mui/icons-material/Assignment';
import AccessTimeIcon from '@mui/icons-material/AccessTime';
import WarningIcon from '@mui/icons-material/Warning';
import BackIcon from '../common/components/BackIcon';
import {
  clockIn, clockOut, toggleBreak, activeShifts, getShift,
  listJobs, acceptJob, denyJob, completeJob,
} from '../common/util/shifts';

const useStyles = makeStyles()((theme) => ({
  root: { height: '100%', display: 'flex', flexDirection: 'column' },
  toolbar: { flexGrow: 0 },
  title: { flexGrow: 1 },
  content: { flexGrow: 1, overflow: 'auto', padding: theme.spacing(2) },
  card: { marginBottom: theme.spacing(2) },
  photoSection: { display: 'flex', flexDirection: 'column', gap: theme.spacing(1.5), mt: 2 },
  photoRow: { display: 'flex', alignItems: 'center', gap: theme.spacing(1) },
  photoPreview: { width: 80, height: 60, objectFit: 'cover', borderRadius: 4, border: '1px solid #ddd' },
  bigButton: { height: 80, fontSize: '1.1rem', fontWeight: 600 },
  statusChip: { fontSize: '0.9rem', padding: '4px 12px' },
  jobCard: { marginBottom: theme.spacing(1), borderLeft: '4px solid' },
  urgent: { borderLeftColor: theme.palette.error.main },
  normal: { borderLeftColor: theme.palette.primary.main },
  low: { borderLeftColor: theme.palette.grey[400] },
  pendingBadge: { '& .MuiBadge-badge': { right: -3, top: 3 } },
}));

// Camera capture helper
function CameraCapture({ onCapture, label }) {
  const inputRef = useRef(null);
  const [preview, setPreview] = useState(null);

  const handleFile = useCallback((e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      setPreview(reader.result);
      onCapture(reader.result);
    };
    reader.readAsDataURL(file);
    e.target.value = '';
  }, [onCapture]);

  return (
    <Box className="photoRow" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
      <Button
        variant="outlined"
        size="small"
        startIcon={<CameraAltIcon />}
        onClick={() => inputRef.current?.click()}
      >
        {label}
      </Button>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        capture="environment"
        style={{ display: 'none' }}
        onChange={handleFile}
      />
      {preview && <img src={preview} alt={label} className="photoPreview" style={{ width: 80, height: 60, objectFit: 'cover', borderRadius: 4 }} />}
    </Box>
  );
}

const DriverShiftPage = () => {
  const { classes } = useStyles();
  const navigate = useNavigate();

  const [driverName, setDriverName] = useState(() => localStorage.getItem('shift_driver_name') || '');
  const [vehicleReg, setVehicleReg] = useState(() => localStorage.getItem('shift_vehicle_reg') || '');
  const [activeShift, setActiveShift] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [pendingJobs, setPendingJobs] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [success, setSuccess] = useState('');

  // Clock-in form
  const [odometerIn, setOdometerIn] = useState('');
  const [fuelIn, setFuelIn] = useState('');
  const [adblueIn, setAdblueIn] = useState('');
  const [photosIn, setPhotosIn] = useState({});

  // Clock-out form
  const [odometerOut, setOdometerOut] = useState('');
  const [fuelOut, setFuelOut] = useState('');
  const [adblueOut, setAdblueOut] = useState('');
  const [photosOut, setPhotosOut] = useState({});

  // Deny dialog
  const [denyDialog, setDenyDialog] = useState(null);
  const [denyReason, setDenyReason] = useState('');

  // Refresh data
  const refreshData = useCallback(async () => {
    if (!driverName) return;
    try {
      const active = await activeShifts();
      const myShift = (active || []).find((s) => s.driver_name === driverName);
      setActiveShift(myShift || null);

      const allJobs = await listJobs('pending', driverName);
      setPendingJobs(allJobs || []);

      if (myShift) {
        const shiftDetail = await getShift(myShift.id);
        setJobs(shiftDetail.jobs || []);
      }
    } catch (e) {
      console.error('Refresh failed:', e);
    }
  }, [driverName]);

  useEffect(() => { refreshData(); }, [refreshData]);

  // Auto-refresh every 15s
  useEffect(() => {
    const interval = setInterval(refreshData, 15000);
    return () => clearInterval(interval);
  }, [refreshData]);

  const handleClockIn = useCallback(async () => {
    if (!driverName) { setError('Enter your name.'); return; }
    setLoading(true);
    setError(null);
    try {
      const photoList = Object.entries(photosIn).map(([type, image]) => ({
        photo_type: type, image,
      }));
      const data = await clockIn({
        driver_name: driverName,
        vehicle_reg: vehicleReg || null,
        odometer_km: odometerIn ? parseInt(odometerIn, 10) : null,
        fuel_level_pct: fuelIn ? parseInt(fuelIn, 10) : null,
        adblue_level_pct: adblueIn ? parseInt(adblueIn, 10) : null,
        photos: photoList,
      });
      localStorage.setItem('shift_driver_name', driverName);
      if (vehicleReg) localStorage.setItem('shift_vehicle_reg', vehicleReg);
      setActiveShift(data);
      setSuccess('Clocked in successfully!');
      setPhotosIn({});
      setOdometerIn('');
      setFuelIn('');
      setAdblueIn('');
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [driverName, vehicleReg, odometerIn, fuelIn, adblueIn, photosIn]);

  const handleClockOut = useCallback(async () => {
    if (!activeShift) return;
    setLoading(true);
    setError(null);
    try {
      const photoList = Object.entries(photosOut).map(([type, image]) => ({
        photo_type: type, image,
      }));
      await clockOut(activeShift.id, {
        odometer_out_km: odometerOut ? parseInt(odometerOut, 10) : null,
        fuel_level_out_pct: fuelOut ? parseInt(fuelOut, 10) : null,
        adblue_level_out_pct: adblueOut ? parseInt(adblueOut, 10) : null,
        photos: photoList,
      });
      setActiveShift(null);
      setSuccess('Clocked out successfully!');
      setPhotosOut({});
      setOdometerOut('');
      setFuelOut('');
      setAdblueOut('');
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [activeShift, odometerOut, fuelOut, adblueOut, photosOut]);

  const handleBreak = useCallback(async (type) => {
    if (!activeShift) return;
    setLoading(true);
    try {
      await toggleBreak(activeShift.id, type);
      await refreshData();
      setSuccess(type === 'start' ? 'Break started' : 'Break ended');
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [activeShift, refreshData]);

  const handleAcceptJob = useCallback(async (jobId) => {
    setLoading(true);
    try {
      await acceptJob(jobId);
      await refreshData();
      setSuccess('Job accepted!');
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [refreshData]);

  const handleDenyJob = useCallback(async () => {
    if (!denyDialog) return;
    setLoading(true);
    try {
      await denyJob(denyDialog.id, denyReason || undefined);
      setDenyDialog(null);
      setDenyReason('');
      await refreshData();
      setSuccess('Job denied.');
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [denyDialog, denyReason, refreshData]);

  const handleCompleteJob = useCallback(async (jobId) => {
    setLoading(true);
    try {
      await completeJob(jobId);
      await refreshData();
      setSuccess('Job completed!');
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [refreshData]);

  const isClockedIn = activeShift && ['clocked_in', 'on_break', 'active'].includes(activeShift.status);
  const isOnBreak = activeShift?.status === 'on_break';

  return (
    <div className={classes.root}>
      <AppBar position="static" color="transparent" elevation={0} sx={{ borderBottom: 1, borderColor: 'divider' }}>
        <Toolbar>
          <IconButton edge="start" sx={{ mr: 2 }} onClick={() => navigate(-1)}>
            <BackIcon />
          </IconButton>
          <Typography variant="h6" className={classes.title}>Driver Shift</Typography>
          {isClockedIn && (
            <Chip
              label={isOnBreak ? 'ON BREAK' : 'CLOCKED IN'}
              color={isOnBreak ? 'warning' : 'success'}
              className={classes.statusChip}
            />
          )}
        </Toolbar>
      </AppBar>

      <div className={classes.content}>
        {/* Driver Info */}
        <Card className={classes.card}>
          <CardContent>
            <Typography variant="subtitle1" gutterBottom>Driver Information</Typography>
            <TextField
              label="Driver Name"
              value={driverName}
              onChange={(e) => setDriverName(e.target.value)}
              fullWidth
              size="small"
              disabled={isClockedIn}
              sx={{ mb: 1 }}
            />
            <TextField
              label="Vehicle Registration"
              value={vehicleReg}
              onChange={(e) => setVehicleReg(e.target.value)}
              fullWidth
              size="small"
              disabled={isClockedIn}
            />
          </CardContent>
        </Card>

        {/* Pending Jobs - Only show when clocked in */}
        {isClockedIn && pendingJobs.length > 0 && (
          <Card className={classes.card}>
            <CardContent>
              <Badge badgeContent={pendingJobs.length} color="error" className={classes.pendingBadge}>
                <Typography variant="subtitle1" sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <AssignmentIcon /> New Job Assignments
                </Typography>
              </Badge>
              <List dense>
                {pendingJobs.map((job) => (
                  <ListItem key={job.id} sx={{ px: 0 }}>
                    <ListItemText
                      primary={job.title}
                      secondary={
                        <>
                          {job.vehicle_reg && <Typography variant="caption">Vehicle: {job.vehicle_reg}</Typography>}
                          {job.pickup_location && <Typography variant="caption" display="block">Pickup: {job.pickup_location}</Typography>}
                          {job.dropoff_location && <Typography variant="caption" display="block">Drop-off: {job.dropoff_location}</Typography>}
                        </>
                      }
                    />
                    <ListItemSecondaryAction>
                      <Button size="small" color="success" onClick={() => handleAcceptJob(job.id)} disabled={loading}>
                        Accept
                      </Button>
                      <Button size="small" color="error" onClick={() => setDenyDialog(job)} disabled={loading}>
                        Deny
                      </Button>
                    </ListItemSecondaryAction>
                  </ListItem>
                ))}
              </List>
            </CardContent>
          </Card>
        )}

        {/* Clock In Form - Only when not clocked in */}
        {!isClockedIn && (
          <Card className={classes.card}>
            <CardContent>
              <Typography variant="subtitle1" gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <PlayArrowIcon color="success" /> Clock In
              </Typography>

              <TextField label="Odometer (km)" type="number" value={odometerIn}
                onChange={(e) => setOdometerIn(e.target.value)} fullWidth size="small" sx={{ mb: 1 }} />
              <TextField label="Fuel Level (%)" type="number" value={fuelIn}
                onChange={(e) => setFuelIn(e.target.value)} fullWidth size="small" sx={{ mb: 1 }} />
              <TextField label="AdBlue Level (%)" type="number" value={adblueIn}
                onChange={(e) => setAdblueIn(e.target.value)} fullWidth size="small" />

              <Box className={classes.photoSection}>
                <Typography variant="caption" color="text.secondary">Required Photos</Typography>
                <CameraCapture label="Odometer" onCapture={(img) => setPhotosIn((p) => ({ ...p, odometer: img }))} />
                <CameraCapture label="Fuel Level" onCapture={(img) => setPhotosIn((p) => ({ ...p, fuel: img }))} />
                <CameraCapture label="AdBlue Level" onCapture={(img) => setPhotosIn((p) => ({ ...p, adblue: img }))} />
              </Box>

              <Button
                variant="contained"
                color="success"
                fullWidth
                className={classes.bigButton}
                sx={{ mt: 2 }}
                onClick={handleClockIn}
                disabled={loading || !driverName}
                startIcon={loading ? <CircularProgress size={20} /> : <PlayArrowIcon />}
              >
                {loading ? 'Processing...' : 'Start Shift'}
              </Button>
            </CardContent>
          </Card>
        )}

        {/* Active Shift Controls - When clocked in */}
        {isClockedIn && (
          <Card className={classes.card}>
            <CardContent>
              <Typography variant="subtitle1" gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <AccessTimeIcon color="primary" /> Active Shift
              </Typography>
              <Typography variant="body2" color="text.secondary" gutterBottom>
                Started: {new Date(activeShift.clocked_in_at).toLocaleString()}
              </Typography>

              <Box sx={{ display: 'flex', gap: 1, mt: 2, flexWrap: 'wrap' }}>
                {!isOnBreak ? (
                  <Button
                    variant="contained"
                    color="warning"
                    startIcon={<PauseIcon />}
                    onClick={() => handleBreak('start')}
                    disabled={loading}
                    sx={{ flex: 1 }}
                  >
                    Take Break
                  </Button>
                ) : (
                  <Button
                    variant="contained"
                    color="success"
                    startIcon={<PlayCircleIcon />}
                    onClick={() => handleBreak('end')}
                    disabled={loading}
                    sx={{ flex: 1 }}
                  >
                    End Break
                  </Button>
                )}
              </Box>
            </CardContent>
          </Card>
        )}

        {/* Clock Out Form - When clocked in */}
        {isClockedIn && (
          <Card className={classes.card}>
            <CardContent>
              <Typography variant="subtitle1" gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <StopIcon color="error" /> End Shift
              </Typography>

              <TextField label="Odometer Out (km)" type="number" value={odometerOut}
                onChange={(e) => setOdometerOut(e.target.value)} fullWidth size="small" sx={{ mb: 1 }} />
              <TextField label="Fuel Level Out (%)" type="number" value={fuelOut}
                onChange={(e) => setFuelOut(e.target.value)} fullWidth size="small" sx={{ mb: 1 }} />
              <TextField label="AdBlue Level Out (%)" type="number" value={adblueOut}
                onChange={(e) => setAdblueOut(e.target.value)} fullWidth size="small" />

              <Box className={classes.photoSection}>
                <Typography variant="caption" color="text.secondary">End of Shift Photos</Typography>
                <CameraCapture label="Odometer" onCapture={(img) => setPhotosOut((p) => ({ ...p, odometer: img }))} />
                <CameraCapture label="Fuel Level" onCapture={(img) => setPhotosOut((p) => ({ ...p, fuel: img }))} />
                <CameraCapture label="AdBlue Level" onCapture={(img) => setPhotosOut((p) => ({ ...p, adblue: img }))} />
              </Box>

              <Button
                variant="contained"
                color="error"
                fullWidth
                className={classes.bigButton}
                sx={{ mt: 2 }}
                onClick={handleClockOut}
                disabled={loading}
                startIcon={loading ? <CircularProgress size={20} /> : <StopIcon />}
              >
                {loading ? 'Processing...' : 'End Shift'}
              </Button>
            </CardContent>
          </Card>
        )}

        {/* Active Jobs - When clocked in */}
        {isClockedIn && jobs.length > 0 && (
          <Card className={classes.card}>
            <CardContent>
              <Typography variant="subtitle1" gutterBottom>Active Jobs</Typography>
              <List dense>
                {jobs.map((job) => (
                  <ListItem key={job.id} sx={{ px: 0 }}>
                    <ListItemText
                      primary={
                        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                          <Typography variant="body2" fontWeight={600}>{job.title}</Typography>
                          <Chip size="small" label={job.status} color={
                            job.status === 'accepted' ? 'success' :
                            job.status === 'completed' ? 'default' : 'warning'
                          } />
                          {job.priority === 'urgent' && <WarningIcon color="error" fontSize="small" />}
                        </Box>
                      }
                      secondary={
                        <>
                          {job.vehicle_reg && <Typography variant="caption">Vehicle: {job.vehicle_reg}</Typography>}
                        </>
                      }
                    />
                    {job.status === 'accepted' && (
                      <ListItemSecondaryAction>
                        <Button size="small" color="primary" onClick={() => handleCompleteJob(job.id)} disabled={loading}>
                          Complete
                        </Button>
                      </ListItemSecondaryAction>
                    )}
                  </ListItem>
                ))}
              </List>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Deny Dialog */}
      <Dialog open={!!denyDialog} onClose={() => setDenyDialog(null)} maxWidth="sm" fullWidth>
        <DialogTitle>Deny Job</DialogTitle>
        <DialogContent>
          <Typography gutterBottom>You are denying: <strong>{denyDialog?.title}</strong></Typography>
          <TextField
            label="Reason (optional)"
            value={denyReason}
            onChange={(e) => setDenyReason(e.target.value)}
            fullWidth
            multiline
            rows={3}
            sx={{ mt: 1 }}
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDenyDialog(null)}>Cancel</Button>
          <Button onClick={handleDenyJob} color="error" disabled={loading}>Confirm Deny</Button>
        </DialogActions>
      </Dialog>

      {/* Snackbar for success */}
      <Snackbar open={!!success} autoHideDuration={3000} onClose={() => setSuccess('')}>
        <Alert severity="success" onClose={() => setSuccess('')}>{success}</Alert>
      </Snackbar>

      {/* Error alert */}
      {error && (
        <Snackbar open autoHideDuration={5000} onClose={() => setError(null)}>
          <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>
        </Snackbar>
      )}
    </div>
  );
};

export default DriverShiftPage;
