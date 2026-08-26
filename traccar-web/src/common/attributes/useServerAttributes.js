import { useMemo } from 'react';

export default (t) =>
  useMemo(
    () => ({
      support: {
        name: t('settingsSupport'),
        type: 'string',
      },
      title: {
        name: t('serverName'),
        type: 'string',
      },
      description: {
        name: t('serverDescription'),
        type: 'string',
      },
      logo: {
        name: t('serverLogo'),
        type: 'string',
      },
      logoInverted: {
        name: t('serverLogoInverted'),
        type: 'string',
      },
      colorPrimary: {
        name: t('serverColorPrimary'),
        type: 'string',
        dataType: 'color',
      },
      colorSecondary: {
        name: t('serverColorSecondary'),
        type: 'string',
        dataType: 'color',
      },
      disableChange: {
        name: t('serverChangeDisable'),
        type: 'boolean',
      },
      darkMode: {
        name: t('settingsDarkMode'),
        type: 'boolean',
      },
      termsUrl: {
        name: t('userTerms'),
        type: 'string',
      },
      privacyUrl: {
        name: t('userPrivacy'),
        type: 'string',
      },
      totpEnable: {
        name: t('settingsTotpEnable'),
        type: 'boolean',
      },
      totpForce: {
        name: t('settingsTotpForce'),
        type: 'boolean',
      },
      serviceWorkerUpdateInterval: {
        name: t('settingsServiceWorkerUpdateInterval'),
        type: 'number',
      },
      'ui.disableLoginLanguage': {
        name: t('attributeUiDisableLoginLanguage'),
        type: 'boolean',
      },
      disableShare: {
        name: t('serverDisableShare'),
        type: 'boolean',
      },
      cmsv9Url: {
        name: 'CMSV9 URL',
        type: 'string',
      },
      cmsv9Account: {
        name: 'CMSV9 Account',
        type: 'string',
      },
      cmsv9Password: {
        name: 'CMSV9 Password',
        type: 'string',
        dataType: 'password',
      },
      cmsv9MediaPort: {
        name: 'CMSV9 Media Port',
        type: 'number',
      },
      cmsv9Channels: {
        name: 'CMSV9 Channels',
        type: 'number',
      },
    }),
    [t],
  );
