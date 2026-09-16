import { useState } from 'react';
import { useDispatch } from 'react-redux';
import TextField from '@mui/material/TextField';
import {
  Accordion,
  AccordionSummary,
  AccordionDetails,
  Typography,
  FormControlLabel,
  Switch,
  Alert,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import EditItemView from './components/EditItemView';
import EditAttributesAccordion from './components/EditAttributesAccordion';
import { useTranslation } from '../common/components/LocalizationProvider';
import SettingsMenu from './components/SettingsMenu';
import useSettingsStyles from './common/useSettingsStyles';
import { useManager } from '../common/util/permissions';
import { useAsyncTask } from '../reactHelper';
import { errorsActions } from '../store';
import { getDriverAppAccount, saveDriverAppAccount } from '../common/util/driverApp';

const formatDate = (iso) =>
  iso
    ? new Date(iso).toLocaleString('en-GB', {
        timeZone: 'Europe/London',
        day: '2-digit',
        month: 'short',
        hour: '2-digit',
        minute: '2-digit',
      })
    : 'never';

const accountStatus = (account) => {
  if (!account || !account.id)
    return 'No PIN yet — this driver can’t sign in to the driver screens.';
  if (!account.active) return 'App access switched off.';
  if (account.locked) return 'Locked after wrong PINs — set a new PIN to unlock.';
  return `PIN set · last sign-in ${formatDate(account.last_login_at)} · ${account.devices} device${account.devices === 1 ? '' : 's'}`;
};

const DriverPage = () => {
  const { classes } = useSettingsStyles();
  const t = useTranslation();
  const dispatch = useDispatch();
  const manager = useManager();

  const [item, setItem] = useState();
  const [pin, setPin] = useState('');
  const [account, setAccount] = useState(null);
  const [active, setActive] = useState(true);
  const [accountError, setAccountError] = useState(null);
  const [pinsDisabled, setPinsDisabled] = useState(false);

  useAsyncTask(async () => {
    if (!manager || !item?.id || account || accountError) return;
    try {
      const result = await getDriverAppAccount(item.id);
      setAccount(result);
      setActive(result.id ? result.active : true);
    } catch (error) {
      if (error.code === 'module_disabled') setPinsDisabled(true);
      setAccountError(error.message);
    }
  }, [manager, item?.id, account, accountError]);

  const pinValid = !pin || /^\d{6}$/.test(pin);
  const validate = () => item && item.name && item.uniqueId && pinValid;

  const accessChanged = account?.id ? active !== account.active : false;

  // Runs after DH FleetView saves the driver, so a new driver gets their PIN in the same step.
  const onItemSaved = async (saved) => {
    if (!manager || accountError || (!pin && !accessChanged)) return;
    try {
      await saveDriverAppAccount(saved.id, { pin, active: account?.id ? active : true });
    } catch (error) {
      dispatch(errorsActions.push(`Driver saved, but the app PIN wasn't: ${error.message}`));
    }
  };

  return (
    <EditItemView
      endpoint="drivers"
      item={item}
      setItem={setItem}
      validate={validate}
      onItemSaved={onItemSaved}
      menu={<SettingsMenu />}
      breadcrumbs={['settingsTitle', 'sharedDriver']}
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
              />
            </AccordionDetails>
          </Accordion>
          {manager && !pinsDisabled && (
            <Accordion defaultExpanded>
              <AccordionSummary expandIcon={<ExpandMoreIcon />}>
                <Typography variant="subtitle1">Driver app sign-in</Typography>
              </AccordionSummary>
              <AccordionDetails className={classes.details}>
                {accountError ? (
                  <Alert severity="warning">{accountError}</Alert>
                ) : (
                  <>
                    <Typography variant="body2" color="text.secondary">
                      The driver signs in on the normal login screen with their name (or identifier)
                      and this PIN, and goes straight to the driver screens.
                    </Typography>
                    {item.id && (
                      <Typography variant="body2">
                        {account ? accountStatus(account) : 'Loading…'}
                      </Typography>
                    )}
                    <TextField
                      value={pin}
                      onChange={(event) =>
                        setPin(event.target.value.replace(/\D/g, '').slice(0, 6))
                      }
                      label={account?.id ? 'New 6-digit PIN (leave blank to keep)' : '6-digit PIN'}
                      error={!pinValid}
                      helperText={!pinValid ? 'The PIN must be exactly 6 digits' : ' '}
                      autoComplete="off"
                      slotProps={{ htmlInput: { inputMode: 'numeric', pattern: '[0-9]*' } }}
                    />
                    {account?.id && (
                      <FormControlLabel
                        control={
                          <Switch
                            checked={active}
                            onChange={(event) => setActive(event.target.checked)}
                          />
                        }
                        label="App access enabled"
                      />
                    )}
                  </>
                )}
              </AccordionDetails>
            </Accordion>
          )}
          <EditAttributesAccordion
            attributes={item.attributes}
            setAttributes={(attributes) => setItem({ ...item, attributes })}
            definitions={{}}
          />
        </>
      )}
    </EditItemView>
  );
};

export default DriverPage;
