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
import useComplianceAccess from '../common/util/useComplianceAccess';
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
  if (account && !account.id && account.existing_login)
    return 'This driver already has a driver login from another company. Save to give them your jobs on the same login — they keep their existing PIN.';
  if (!account || !account.id)
    return 'No PIN yet — this driver can’t sign in to the driver screens.';
  if (!account.active) return 'App access switched off.';
  if (account.locked) return 'Locked after wrong PINs — set a new PIN to unlock.';
  const shared = account.shared
    ? ` · also drives for ${account.other_companies} other compan${account.other_companies === 1 ? 'y' : 'ies'}`
    : '';
  return `PIN set · last sign-in ${formatDate(account.last_login_at)} · ${account.devices} device${account.devices === 1 ? '' : 's'}${shared}`;
};

const DriverPage = () => {
  const { classes } = useSettingsStyles();
  const t = useTranslation();
  const dispatch = useDispatch();
  // Driver app PINs: managers, or users given compliance modules (the server checks driver_pins).
  const manager = useComplianceAccess();

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
  // One login per person: a driver who also works for another company keeps the PIN they have.
  const linkExisting = Boolean(account && !account.id && account.existing_login);
  const pinLocked =
    linkExisting || Boolean(account?.id && account.shared && !account.can_change_pin);

  // Runs after DH FleetView saves the driver, so a new driver gets their PIN in the same step.
  const onItemSaved = async (saved) => {
    // A driver with app access is always updated, so a changed name or identifier
    // (e.g. a driver card number added later) reaches their driver login.
    if (!manager || accountError || (!pin && !accessChanged && !linkExisting && !account?.id))
      return;
    const body = { pin: pinLocked ? null : pin, active: account?.id ? active : true };
    try {
      await saveDriverAppAccount(saved.id, body);
    } catch (error) {
      if (error.code === 'shared_login' && body.pin) {
        // Same identifier as a login another company set up: link them without changing the PIN.
        try {
          await saveDriverAppAccount(saved.id, { ...body, pin: null });
          dispatch(
            errorsActions.push(`${error.message} They were linked to their existing login.`),
          );
          return;
        } catch (linkError) {
          dispatch(errorsActions.push(`Driver saved, but app access wasn't: ${linkError.message}`));
          return;
        }
      }
      dispatch(
        errorsActions.push(
          `Driver saved, but their driver app sign-in wasn't updated: ${error.message}`,
        ),
      );
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
                helperText="Driver card number (or mobile number). It links the driver app login and their tachograph hours, and lets a driver who works for several companies use one login."
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
                    {pinLocked ? (
                      <Alert severity="info">
                        {linkExisting
                          ? 'The driver signs in with the PIN they already use.'
                          : 'This login is shared with another company, so only the super administrator can change the PIN.'}
                      </Alert>
                    ) : (
                      <TextField
                        value={pin}
                        onChange={(event) =>
                          setPin(event.target.value.replace(/\D/g, '').slice(0, 6))
                        }
                        label={
                          account?.id ? 'New 6-digit PIN (leave blank to keep)' : '6-digit PIN'
                        }
                        error={!pinValid}
                        helperText={!pinValid ? 'The PIN must be exactly 6 digits' : ' '}
                        autoComplete="off"
                        slotProps={{ htmlInput: { inputMode: 'numeric', pattern: '[0-9]*' } }}
                      />
                    )}
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
