import { IconButton, Tooltip } from '@mui/material';
import DarkModeOutlinedIcon from '@mui/icons-material/DarkModeOutlined';
import LightModeOutlinedIcon from '@mui/icons-material/LightModeOutlined';
import { useThemeMode } from '../../AppThemeProvider';

const ThemeModeButton = ({ size = 'medium', className }) => {
  const { darkMode, toggleDarkMode } = useThemeMode();
  const label = darkMode ? 'Switch to light mode' : 'Switch to dark mode';

  return (
    <Tooltip title={label}>
      <IconButton size={size} className={className} onClick={toggleDarkMode} aria-label={label}>
        {darkMode ? (
          <DarkModeOutlinedIcon sx={{ color: '#a5b4fc' }} />
        ) : (
          <LightModeOutlinedIcon sx={{ color: '#f5a524' }} />
        )}
      </IconButton>
    </Tooltip>
  );
};

export default ThemeModeButton;
