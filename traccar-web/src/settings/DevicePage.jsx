import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Typography,
  FormControlLabel,
  Checkbox,
  TextField,
  Button,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import FileInput from '../common/components/FileInput';
import EditItemView from './components/EditItemView';
import EditAttributesAccordion from './components/EditAttributesAccordion';
import { Box, Avatar, Tooltip } from '@mui/material';
import SelectField from '../common/components/SelectField';
import deviceCategories from '../common/util/deviceCategories';
import { useTranslation } from '../common/components/LocalizationProvider';
import useDeviceAttributes from '../common/attributes/useDeviceAttributes';
import { useManager } from '../common/util/permissions';
import SettingsMenu from './components/SettingsMenu';
import useCommonDeviceAttributes from '../common/attributes/useCommonDeviceAttributes';
import { useCatch } from '../reactHelper';
import useSettingsStyles from './common/useSettingsStyles';
import QrCodeDialog from '../common/components/QrCodeDialog';
import fetchOrThrow from '../common/util/fetchOrThrow';
import { mapIcons, mapIconKey } from '../map/core/preloadImages';

const DevicePage = () => {
  const { classes } = useSettingsStyles();
  const t = useTranslation();

  const manager = useManager();

  const commonDeviceAttributes = useCommonDeviceAttributes(t);
  const deviceAttributes = useDeviceAttributes(t);

  const [searchParams] = useSearchParams();
  const uniqueId = searchParams.get('uniqueId');

  const [item, setItem] = useState(uniqueId ? { uniqueId } : null);
  const [showQr, setShowQr] = useState(false);
  const [imageFile, setImageFile] = useState(null);

  const handleFileInput = useCatch(async (newFile) => {
    setImageFile(newFile);
    if (newFile && item?.id) {
      const response = await fetchOrThrow(`/api/devices/${item.id}/image`, {
        method: 'POST',
        body: newFile,
      });
      setItem({ ...item, attributes: { ...item.attributes, deviceImage: await response.text() } });
    } else if (!newFile) {
      // eslint-disable-next-line no-unused-vars
      const { deviceImage, ...remainingAttributes } = item.attributes || {};
      setItem({ ...item, attributes: remainingAttributes });
    }
  });

  const validate = () => item && item.name && item.uniqueId;

  return (
    <EditItemView
      endpoint="devices"
      item={item}
      setItem={setItem}
      validate={validate}
      menu={<SettingsMenu />}
      breadcrumbs={['settingsTitle', 'sharedDevice']}
    >
      {item && (
        <>
          <Accordion defaultExpanded>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="subtitle1">{t('sharedRequired')}</Typography>
            </AccordionSummary>
            <AccordionDetails className={classes.details}>
              <TextField
                value={item.name || ''}
                onChange={(event) => setItem({ ...item, name: event.target.value })}
                label={t('sharedName')}
              />
              <TextField
                value={item.uniqueId || ''}
                onChange={(event) => setItem({ ...item, uniqueId: event.target.value })}
                label={t('deviceIdentifier')}
                helperText={t('deviceIdentifierHelp')}
                disabled={Boolean(uniqueId)}
              />
            </AccordionDetails>
          </Accordion>
          <Accordion>
            <AccordionSummary expandIcon={<ExpandMoreIcon />}>
              <Typography variant="subtitle1">{t('sharedExtra')}</Typography>
            </AccordionSummary>
            <AccordionDetails className={classes.details}>
              <SelectField
                value={item.groupId}
                onChange={(event) => setItem({ ...item, groupId: Number(event.target.value) })}
                endpoint="/api/groups"
                label={t('groupParent')}
              />
              <TextField
                value={item.phone || ''}
                onChange={(event) => setItem({ ...item, phone: event.target.value })}
                label={t('sharedPhone')}
              />
              <TextField
                value={item.model || ''}
                onChange={(event) => setItem({ ...item, model: event.target.value })}
                label={t('deviceModel')}
              />
              <TextField
                value={item.contact || ''}
                onChange={(event) => setItem({ ...item, contact: event.target.value })}
                label={t('deviceContact')}
              />
              <SelectField
                value={item.category || 'default'}
                onChange={(event) => setItem({ ...item, category: event.target.value })}
                data={deviceCategories
                  .map((category) => ({
                    id: category,
                    name: t(`category${category.replace(/^\w/, (c) => c.toUpperCase())}`),
                  }))
                  .sort((a, b) => a.name.localeCompare(b.name))}
                label={t('deviceCategory')}
              />
              {/* Icon library – selectable gallery, preview gray (ignition OFF) vs green (running) */}
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1, width: '100%' }}>
                <Typography variant="caption" color="textSecondary">
                  Icon library – tap to select. Preview: gray = ignition OFF (parked/stopped), green = running (ignition ON).
                </Typography>
                <Box sx={{ display: 'flex', gap: 1.5, alignItems: 'center', flexWrap: 'wrap' }}>
                  <Tooltip title="Selected icon – ignition OFF (gray)">
                    <Avatar sx={{ bgcolor: 'neutral.main', width: 44, height: 44, borderRadius: 2 }}>
                      <img src={mapIcons[mapIconKey(item.category || 'default')]} alt={item.category} style={{ width: 24, height: 24, filter: 'brightness(0) invert(1)' }} />
                    </Avatar>
                  </Tooltip>
                  <Tooltip title="Selected icon – ignition ON / running (green)">
                    <Avatar sx={{ bgcolor: 'success.main', width: 44, height: 44, borderRadius: 2 }}>
                      <img src={mapIcons[mapIconKey(item.category || 'default')]} alt={item.category} style={{ width: 24, height: 24, filter: 'brightness(0) invert(1)' }} />
                    </Avatar>
                  </Tooltip>
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>{t(`category${(item.category || 'default').replace(/^\w/, (c) => c.toUpperCase())}`)}</Typography>
                </Box>
                <Box
                  sx={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(auto-fill, minmax(64px, 1fr))',
                    gap: 1,
                    maxHeight: 220,
                    overflowY: 'auto',
                    p: 1,
                    border: '1px solid',
                    borderColor: 'divider',
                    borderRadius: 2,
                    bgcolor: 'background.paper',
                  }}
                >
                  {deviceCategories.map((category) => {
                    const selected = (item.category || 'default') === category;
                    return (
                      <Tooltip key={category} title={t(`category${category.replace(/^\w/, (c) => c.toUpperCase())}`)}>
                        <Box
                          onClick={() => setItem({ ...item, category })}
                          sx={{
                            display: 'flex',
                            flexDirection: 'column',
                            alignItems: 'center',
                            gap: 0.5,
                            p: 1,
                            borderRadius: 1.5,
                            cursor: 'pointer',
                            border: '2px solid',
                            borderColor: selected ? 'primary.main' : 'transparent',
                            bgcolor: selected ? 'action.selected' : 'transparent',
                            '&:hover': { bgcolor: 'action.hover' },
                          }}
                        >
                          <Avatar sx={{ bgcolor: selected ? 'success.main' : 'neutral.main', width: 36, height: 36, borderRadius: 1.5 }}>
                            <img src={mapIcons[category]} alt={category} style={{ width: 20, height: 20, filter: 'brightness(0) invert(1)' }} />
                          </Avatar>
                          <Typography variant="caption" noWrap sx={{ maxWidth: 64, fontSize: '0.65rem' }}>
                            {t(`category${category.replace(/^\w/, (c) => c.toUpperCase())}`)}
                          </Typography>
                        </Box>
                      </Tooltip>
                    );
                  })}
                </Box>
              </Box>
              <SelectField
                value={item.calendarId}
                onChange={(event) => setItem({ ...item, calendarId: Number(event.target.value) })}
                endpoint="/api/calendars"
                label={t('sharedCalendar')}
              />
              <TextField
                label={t('userExpirationTime')}
                type="date"
                value={item.expirationTime ? item.expirationTime.split('T')[0] : '2099-01-01'}
                onChange={(e) => {
                  if (e.target.value) {
                    setItem({ ...item, expirationTime: new Date(e.target.value).toISOString() });
                  }
                }}
                disabled={!manager}
              />
              <FormControlLabel
                control={
                  <Checkbox
                    checked={item.disabled}
                    onChange={(event) => setItem({ ...item, disabled: event.target.checked })}
                  />
                }
                label={t('sharedDisabled')}
                disabled={!manager}
              />
              <FormControlLabel
                control={
                  <Checkbox
                    checked={Boolean(item.attributes?.cmsv9DeviceId)}
                    onChange={(event) => {
                      if (event.target.checked) {
                        setItem({ ...item, attributes: { ...item.attributes, cmsv9DeviceId: '' } });
                      } else {
                        const { cmsv9DeviceId, ...remainingAttributes } = item.attributes || {};
                        setItem({ ...item, attributes: remainingAttributes });
                      }
                    }}
                  />
                }
                label={t('cmsv9CameraDevice')}
              />
              {item.attributes?.cmsv9DeviceId !== undefined && (
                <TextField
                  value={item.attributes.cmsv9DeviceId || ''}
                  onChange={(event) =>
                    setItem({ ...item, attributes: { ...item.attributes, cmsv9DeviceId: event.target.value } })
                  }
                  label={t('cmsv9DeviceId')}
                  helperText={t('cmsv9DeviceIdHelp')}
                />
              )}
              <Button variant="outlined" color="primary" onClick={() => setShowQr(true)}>
                {t('sharedQrCode')}
              </Button>
            </AccordionDetails>
          </Accordion>
          {item.id && (
            <Accordion>
              <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                <Typography variant="subtitle1">{t('attributeDeviceImage')}</Typography>
              </AccordionSummary>
              <AccordionDetails className={classes.details}>
                <FileInput
                  placeholder={t('attributeDeviceImage')}
                  value={imageFile}
                  onChange={handleFileInput}
                  slotProps={{ htmlInput: { accept: 'image/*' } }}
                />
              </AccordionDetails>
            </Accordion>
          )}
          <EditAttributesAccordion
            attributes={item.attributes}
            setAttributes={(attributes) => setItem({ ...item, attributes })}
            definitions={{ ...commonDeviceAttributes, ...deviceAttributes }}
          />
        </>
      )}
      <QrCodeDialog open={showQr} onClose={() => setShowQr(false)} />
    </EditItemView>
  );
};

export default DevicePage;
