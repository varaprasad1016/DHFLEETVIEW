import { useState } from 'react';
import { Button, TextField, Typography, IconButton } from '@mui/material';
import { makeStyles } from 'tss-react/mui';
import { useNavigate } from 'react-router-dom';
import CheckCircleRoundedIcon from '@mui/icons-material/CheckCircleRounded';
import LoginLayout from './LoginLayout';
import { useTranslation } from '../common/components/LocalizationProvider';
import { useCatch } from '../reactHelper';
import BackIcon from '../common/components/BackIcon';
import fetchOrThrow from '../common/util/fetchOrThrow';

const useStyles = makeStyles()((theme) => ({
  container: {
    display: 'flex',
    flexDirection: 'column',
    gap: theme.spacing(2),
  },
  header: {
    display: 'flex',
    alignItems: 'center',
  },
  title: {
    fontSize: '1.35rem',
    fontWeight: 650,
    letterSpacing: '-0.01em',
    marginLeft: theme.spacing(1),
  },
  subtitle: {
    color: theme.palette.text.secondary,
    fontSize: '0.85rem',
    marginTop: theme.spacing(-1),
    marginBottom: theme.spacing(0.5),
  },
  success: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    textAlign: 'center',
    gap: theme.spacing(1.5),
    padding: theme.spacing(1, 0, 2),
  },
  successIcon: {
    fontSize: 64,
    color: theme.palette.success.main,
  },
  successTitle: {
    fontSize: '1.3rem',
    fontWeight: 700,
    letterSpacing: '-0.01em',
  },
  successText: {
    color: theme.palette.text.secondary,
    fontSize: '0.9rem',
    maxWidth: 320,
  },
}));

const RegisterPage = () => {
  const { classes } = useStyles();
  const navigate = useNavigate();
  const t = useTranslation();

  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [phone, setPhone] = useState('');
  const [submitted, setSubmitted] = useState(false);

  const emailValid = /(.+)@(.+)\.(.{2,})/.test(email);
  const valid = name.trim() && emailValid && phone.trim();

  const handleSubmit = useCatch(async (event) => {
    event.preventDefault();
    await fetchOrThrow('/api/enquiry', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, email, phone }),
    });
    setSubmitted(true);
  });

  if (submitted) {
    return (
      <LoginLayout>
        <div className={classes.success}>
          <CheckCircleRoundedIcon className={classes.successIcon} />
          <span className={classes.successTitle}>Enquiry received</span>
          <span className={classes.successText}>
            Thank you for your interest in DH FleetView. Our team will review your
            enquiry and be in touch with you shortly.
          </span>
          <Button
            variant="contained"
            color="primary"
            onClick={() => navigate('/login')}
            fullWidth
            style={{ height: 46, fontSize: '0.95rem', marginTop: 8 }}
          >
            Back to sign in
          </Button>
        </div>
      </LoginLayout>
    );
  }

  return (
    <LoginLayout>
      <div className={classes.container}>
        <div className={classes.header}>
          <IconButton color="primary" onClick={() => navigate('/login')}>
            <BackIcon />
          </IconButton>
          <Typography className={classes.title} color="primary">
            Request access
          </Typography>
        </div>
        <span className={classes.subtitle}>
          Tell us how to reach you and our team will get in touch.
        </span>
        <TextField
          required
          label={t('sharedName')}
          name="name"
          value={name}
          autoComplete="name"
          autoFocus
          onChange={(event) => setName(event.target.value)}
        />
        <TextField
          required
          type="email"
          label={t('userEmail')}
          name="email"
          value={email}
          autoComplete="email"
          onChange={(event) => setEmail(event.target.value)}
        />
        <TextField
          required
          type="tel"
          label={t('sharedPhone')}
          name="phone"
          value={phone}
          autoComplete="tel"
          onChange={(event) => setPhone(event.target.value)}
        />
        <Button
          variant="contained"
          color="primary"
          onClick={handleSubmit}
          type="submit"
          disabled={!valid}
          fullWidth
          style={{ height: 46, fontSize: '0.95rem', marginTop: 4 }}
        >
          Submit enquiry
        </Button>
      </div>
    </LoginLayout>
  );
};

export default RegisterPage;
