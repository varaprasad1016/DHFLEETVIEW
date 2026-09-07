import { useEffect, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  Divider,
  FormControlLabel,
  MenuItem,
  Paper,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material';
import { useSelector } from 'react-redux';
import { useCatch, useCatchCallback } from '../reactHelper';
import {
  tachoGetConfiguration,
  tachoSaveConfiguration,
  tachoRequestDownload,
  tachoFormatDate,
} from '../common/util/tachograph';

/**
 * Per-vehicle tachograph settings, and the button that starts a download by hand.
 *
 * <p>The two intervals are the compliance clock. UK and EU rules require vehicle unit data at
 * least every 90 days and driver card data every 28, so those are the defaults; an operator can
 * shorten them but the page says plainly what the legal ceiling is, because a number typed into
 * a box with no context is how a fleet drifts out of compliance without noticing.
 */
const DRIVER_LEGAL_MAX_DAYS = 28;
const VEHICLE_LEGAL_MAX_DAYS = 90;

const TachographVehiclesTab = () => {
  const devices = useSelector((state) => Object.values(state.devices.items));

  const [deviceId, setDeviceId] = useState('');
  const [config, setConfig] = useState(null);
  const [saved, setSaved] = useState(false);
  const [requested, setRequested] = useState(null);

  const loadConfig = useCatch(async (id) => {
    if (!id) {
      setConfig(null);
      return;
    }
    setConfig(await tachoGetConfiguration(Number(id)));
    setSaved(false);
    setRequested(null);
  });

  useEffect(() => {
    loadConfig(deviceId);
    // eslint-disable-next-line @eslint-react/exhaustive-deps
  }, [deviceId]);

  const handleSave = useCatchCallback(async () => {
    const result = await tachoSaveConfiguration(Number(deviceId), config);
    setConfig(result);
    setSaved(true);
  }, [config, deviceId]);

  const handleDownload = useCatchCallback(
    async (type) => {
      const job = await tachoRequestDownload(Number(deviceId), type);
      setRequested(
        `${type === 'DRIVER' ? 'Driver card' : 'Vehicle unit'} download queued as job ${job.id}.`,
      );
    },
    [deviceId],
  );

  const update = (changes) => {
    setConfig((current) => ({ ...current, ...changes }));
    setSaved(false);
  };

  const driverOverLimit = (config?.driverDownloadIntervalDays ?? 0) > DRIVER_LEGAL_MAX_DAYS;
  const vehicleOverLimit = (config?.vehicleDownloadIntervalDays ?? 0) > VEHICLE_LEGAL_MAX_DAYS;

  return (
    <Paper sx={{ p: 2 }}>
      <Typography variant="h6" gutterBottom>
        Vehicle settings
      </Typography>

      <TextField
        select
        label="Vehicle"
        value={deviceId}
        onChange={(event) => setDeviceId(event.target.value)}
        fullWidth
        sx={{ mb: 2, maxWidth: 480 }}
        helperText="Choose a vehicle to see and change its tachograph schedule"
      >
        {devices.map((device) => (
          <MenuItem key={device.id} value={String(device.id)}>
            {device.name}
          </MenuItem>
        ))}
      </TextField>

      {!deviceId && (
        <Alert severity="info">Select a vehicle to configure automatic tachograph downloads.</Alert>
      )}

      {config && (
        <Box>
          <FormControlLabel
            control={
              <Switch
                checked={!!config.enabled}
                onChange={(event) => update({ enabled: event.target.checked })}
              />
            }
            label="Tachograph downloads enabled for this vehicle"
          />

          <Divider sx={{ my: 2 }} />

          <Stack spacing={2} sx={{ maxWidth: 640 }}>
            <Box>
              <FormControlLabel
                control={
                  <Switch
                    checked={!!config.vehicleDownloadEnabled}
                    onChange={(event) => update({ vehicleDownloadEnabled: event.target.checked })}
                  />
                }
                label="Download vehicle unit data automatically"
              />
              <TextField
                label="Vehicle unit interval (days)"
                type="number"
                size="small"
                value={config.vehicleDownloadIntervalDays ?? VEHICLE_LEGAL_MAX_DAYS}
                onChange={(event) =>
                  update({ vehicleDownloadIntervalDays: Number(event.target.value) })
                }
                error={vehicleOverLimit}
                helperText={
                  vehicleOverLimit
                    ? `Longer than the ${VEHICLE_LEGAL_MAX_DAYS} day legal maximum`
                    : `Legal maximum is ${VEHICLE_LEGAL_MAX_DAYS} days`
                }
                sx={{ mt: 1, width: 260 }}
              />
              <Typography variant="caption" display="block" color="text.secondary" sx={{ mt: 1 }}>
                {`Last: ${tachoFormatDate(config.lastVehicleDownload)} · Next: ${tachoFormatDate(config.nextVehicleDownload)}`}
              </Typography>
            </Box>

            <Box>
              <FormControlLabel
                control={
                  <Switch
                    checked={!!config.driverDownloadEnabled}
                    onChange={(event) => update({ driverDownloadEnabled: event.target.checked })}
                  />
                }
                label="Download the inserted driver card automatically"
              />
              <TextField
                label="Driver card interval (days)"
                type="number"
                size="small"
                value={config.driverDownloadIntervalDays ?? DRIVER_LEGAL_MAX_DAYS}
                onChange={(event) =>
                  update({ driverDownloadIntervalDays: Number(event.target.value) })
                }
                error={driverOverLimit}
                helperText={
                  driverOverLimit
                    ? `Longer than the ${DRIVER_LEGAL_MAX_DAYS} day legal maximum`
                    : `Legal maximum is ${DRIVER_LEGAL_MAX_DAYS} days`
                }
                sx={{ mt: 1, width: 260 }}
              />
              <Typography variant="caption" display="block" color="text.secondary" sx={{ mt: 1 }}>
                {`Last: ${tachoFormatDate(config.lastDriverDownload)} · Next: ${tachoFormatDate(config.nextDriverDownload)}`}
              </Typography>
            </Box>
          </Stack>

          <Divider sx={{ my: 2 }} />

          <Stack direction="row" spacing={1} flexWrap="wrap" useFlexGap>
            <Button variant="contained" onClick={handleSave}>
              Save settings
            </Button>
            <Button variant="outlined" onClick={() => handleDownload('VEHICLE')}>
              Download vehicle unit now
            </Button>
            <Button variant="outlined" onClick={() => handleDownload('DRIVER')}>
              Download driver card now
            </Button>
            {saved && <Chip label="Saved" color="success" size="small" />}
          </Stack>

          {requested && (
            <Alert severity="success" sx={{ mt: 2 }}>
              {requested}
            </Alert>
          )}
        </Box>
      )}
    </Paper>
  );
};

export default TachographVehiclesTab;
