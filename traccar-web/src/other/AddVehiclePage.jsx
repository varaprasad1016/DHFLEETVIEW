import { useEffect, useRef, useState } from 'react';
import {
  Alert,
  AppBar,
  Box,
  Button,
  Chip,
  CircularProgress,
  IconButton,
  MenuItem,
  Paper,
  TextField,
  Toolbar,
  Typography,
} from '@mui/material';
import { makeStyles } from 'tss-react/mui';
import { useNavigate } from 'react-router-dom';
import PhotoCameraIcon from '@mui/icons-material/PhotoCamera';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import BackIcon from '../common/components/BackIcon';

const API = '/tacho/api';

const request = async (path, init = {}) => {
  const response = await fetch(`${API}${path}`, {
    credentials: 'include',
    headers:
      init.body && typeof init.body === 'string'
        ? { 'Content-Type': 'application/json' }
        : undefined,
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
  drop: {
    border: `2px dashed ${theme.palette.divider}`,
    borderRadius: 12,
    padding: theme.spacing(4),
    textAlign: 'center',
    cursor: 'pointer',
  },
  card: { padding: theme.spacing(2), display: 'flex', gap: theme.spacing(2), flexWrap: 'wrap' },
  photo: {
    width: 190,
    maxHeight: 260,
    objectFit: 'contain',
    borderRadius: 8,
    border: `1px solid ${theme.palette.divider}`,
    cursor: 'zoom-in',
  },
  fields: {
    flex: '1 1 320px',
    display: 'flex',
    flexDirection: 'column',
    gap: theme.spacing(1.5),
    minWidth: 260,
  },
  readRow: { display: 'flex', gap: theme.spacing(1), flexWrap: 'wrap' },
}));

// Adding a camera from a photo of its label: the numbers come from the barcodes,
// the registration and customer are confirmed against the photo.
const AddVehiclePage = () => {
  const { classes } = useStyles();
  const navigate = useNavigate();
  const fileInputRef = useRef(null);

  const [labels, setLabels] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [cnms, setCnms] = useState({ companies: [], default: '', available: false });
  const [reading, setReading] = useState(0);
  const [error, setError] = useState('');

  useEffect(() => {
    request('/bridge/companies')
      .then((r) => setAccounts(r?.companies || []))
      .catch(() => setAccounts([]));
    request('/dvr/cnms/companies')
      .then((r) => setCnms(r || { companies: [], available: false }))
      .catch(() => setCnms({ companies: [], available: false }));
  }, []);

  const addPhotos = async (files) => {
    setError('');
    for (const file of Array.from(files)) {
      setReading((n) => n + 1);
      try {
        const form = new FormData();
        form.append('photo', file);
        const label = await request('/dvr/labels', { method: 'POST', body: form });
        setLabels((current) => [
          ...current,
          {
            ...label,
            key: label.photo_id,
            registration: label.registration || '',
            account_user_id: '',
            cnms_company: cnms.default || '',
            channels: 4,
            state: label.already_here ? 'exists' : 'new',
          },
        ]);
      } catch (e) {
        setError(e.message);
      } finally {
        setReading((n) => n - 1);
      }
    }
  };

  const update = (key, field, value) =>
    setLabels((current) => current.map((l) => (l.key === key ? { ...l, [field]: value } : l)));

  const create = async (label) => {
    update(label.key, 'state', 'creating');
    try {
      const result = await request('/dvr/vehicles', {
        method: 'POST',
        body: JSON.stringify({
          registration: label.registration,
          device_id: label.device_id,
          sim_no: label.sim_no,
          mobile_no: label.mobile_no,
          serial: label.serial,
          iccid: label.iccid,
          photo_id: label.photo_id,
          account_user_id: label.account_user_id || null,
          cnms_company: label.cnms_company || null,
          channels: label.channels,
        }),
      });
      setLabels((current) =>
        current.map((l) => (l.key === label.key ? { ...l, state: 'created', created: result } : l)),
      );
    } catch (e) {
      setError(e.message);
      update(label.key, 'state', 'new');
    }
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
          <Typography variant="h6">Add vehicles from label photos</Typography>
        </Toolbar>
      </AppBar>

      <div className={classes.content}>
        <Typography variant="body2" color="text.secondary">
          Photograph the label on each DVR. The device ID, SIM number and mobile number are read
          from its barcodes; type the registration you wrote on the label and choose the customer
          account it belongs to.
        </Typography>

        {error && (
          <Alert severity="error" onClose={() => setError('')}>
            {error}
          </Alert>
        )}

        <Paper
          variant="outlined"
          className={classes.drop}
          onClick={() => fileInputRef.current?.click()}
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            addPhotos(e.dataTransfer.files);
          }}
        >
          <PhotoCameraIcon color="action" fontSize="large" />
          <Typography variant="body1">Take or drop label photos here</Typography>
          <Typography variant="caption" color="text.secondary">
            Several at once is fine — one card per camera
          </Typography>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            capture="environment"
            multiple
            hidden
            onChange={(e) => addPhotos(e.target.files)}
          />
        </Paper>

        {reading > 0 && (
          <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
            <CircularProgress size={18} />
            <Typography variant="body2">{`Reading ${reading} photo${reading === 1 ? '' : 's'}…`}</Typography>
          </Box>
        )}

        {labels.map((label) => (
          <Paper variant="outlined" className={classes.card} key={label.key}>
            <a href={label.photo_url} target="_blank" rel="noopener noreferrer">
              <img className={classes.photo} src={label.photo_url} alt="DVR label" />
            </a>
            <div className={classes.fields}>
              <div className={classes.readRow}>
                {label.device_id_source === 'barcode' && (
                  <Chip size="small" color="success" label={`ID ${label.device_id}`} />
                )}
                {label.sim_no && <Chip size="small" label={`SIM ${label.sim_no}`} />}
                {label.mobile_no && <Chip size="small" label={`Mobile ${label.mobile_no}`} />}
                {label.serial && (
                  <Chip size="small" variant="outlined" label={`SN ${label.serial}`} />
                )}
              </div>

              {label.already_here && (
                <Alert severity="info">{`Already on DH FleetView as ${label.already_here.name}.`}</Alert>
              )}
              {label.already_in_cnms && (
                <Alert severity="info">
                  {`Already in CNMS under ${label.already_in_cnms.company}${label.already_in_cnms.plate ? ` as ${label.already_in_cnms.plate}` : ''}.`}
                </Alert>
              )}

              {label.device_id_source !== 'barcode' && (
                <TextField
                  size="small"
                  label="Device ID"
                  value={label.device_id || ''}
                  onChange={(e) =>
                    update(label.key, 'device_id', e.target.value.replace(/\D/g, ''))
                  }
                  disabled={label.state === 'created'}
                  error={Boolean(label.device_id) && !/^\d{12}$/.test(label.device_id)}
                  helperText={
                    label.device_id_source === 'text'
                      ? 'Read from the printed ID line — check it against the photo'
                      : 'Not readable on this photo — type the number after ID: on the label'
                  }
                />
              )}
              <TextField
                size="small"
                label="Registration (handwritten on the label)"
                value={label.registration}
                onChange={(e) => update(label.key, 'registration', e.target.value.toUpperCase())}
                disabled={label.state === 'created'}
              />
              <TextField
                select
                size="small"
                label="Customer account on DH FleetView"
                value={label.account_user_id}
                onChange={(e) => update(label.key, 'account_user_id', e.target.value)}
                disabled={label.state === 'created'}
              >
                <MenuItem value="">Administrators only for now</MenuItem>
                {accounts.map((account) => (
                  <MenuItem key={account.id} value={account.id}>
                    {account.name}
                  </MenuItem>
                ))}
              </TextField>
              {cnms.available && !label.already_in_cnms && (
                <>
                  <TextField
                    select
                    size="small"
                    label="Company in CNMS"
                    value={label.cnms_company}
                    onChange={(e) => update(label.key, 'cnms_company', e.target.value)}
                    disabled={label.state === 'created'}
                    helperText="The camera is created in CNMS under this company too"
                  >
                    {cnms.companies.map((company) => (
                      <MenuItem key={company.id} value={company.name}>
                        {`${company.name} (${company.used}/${company.limit})`}
                      </MenuItem>
                    ))}
                  </TextField>
                  <TextField
                    select
                    size="small"
                    label="Cameras on this unit"
                    value={label.channels}
                    onChange={(e) => update(label.key, 'channels', Number(e.target.value))}
                    disabled={label.state === 'created'}
                    helperText="Count the camera leads going into the DVR"
                  >
                    {[1, 2, 3, 4, 5, 6, 7, 8].map((count) => (
                      <MenuItem key={count} value={count}>
                        {count}
                      </MenuItem>
                    ))}
                  </TextField>
                </>
              )}

              {label.state === 'created' ? (
                <>
                  <Alert severity="success" icon={<CheckCircleIcon fontSize="inherit" />}>
                    {`${label.registration} created${label.created?.account ? ' and shared with the account' : ''}.`}
                  </Alert>
                  {label.created?.cnms && (
                    <Alert severity="success">
                      {`Added to CNMS under ${label.created.cnms.company}, so video will work once the camera dials in.`}
                    </Alert>
                  )}
                  {label.created?.cnms_existing && (
                    <Alert severity="success">
                      {`CNMS already had this camera under ${label.created.cnms_existing.company}${
                        label.created.cnms_existing.plate
                          ? ` as ${label.created.cnms_existing.plate}`
                          : ''
                      }, and was left as it is.`}
                    </Alert>
                  )}
                  {label.created?.cnms_error && (
                    <Alert severity="warning">
                      {`${label.created.cnms_error} Add device ${label.device_id}${label.sim_no ? ` with SIM ${label.sim_no}` : ''} in CNMS by hand, under ${label.cnms_company || cnms.default}.`}
                    </Alert>
                  )}
                  {label.mobile_no && (
                    <Box>
                      <Button
                        variant="outlined"
                        size="small"
                        onClick={() =>
                          navigate(`/dvr-commands?device=${label.created?.device?.id || ''}`)
                        }
                      >
                        Send setup commands
                      </Button>
                    </Box>
                  )}
                </>
              ) : (
                <Box sx={{ display: 'flex', gap: 1 }}>
                  <Button
                    variant="contained"
                    disabled={
                      !/^\d{12}$/.test(label.device_id || '') ||
                      !label.registration ||
                      label.state === 'creating'
                    }
                    onClick={() => create(label)}
                  >
                    {label.state === 'creating' ? 'Creating…' : 'Create vehicle'}
                  </Button>
                  <Button onClick={() => setLabels((c) => c.filter((l) => l.key !== label.key))}>
                    Discard
                  </Button>
                </Box>
              )}
            </div>
          </Paper>
        ))}
      </div>
    </div>
  );
};

export default AddVehiclePage;
