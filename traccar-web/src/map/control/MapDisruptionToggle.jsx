import { useEffect, useRef } from 'react';
import { createRoot } from 'react-dom/client';
import { useTheme } from '@mui/material';
import { makeStyles } from 'tss-react/mui';
import ConstructionIcon from '@mui/icons-material/Construction';
import { map } from '../core/MapView';

/*
 * Shows and hides the road disruption layer.
 *
 * A map control rather than a floating chip: it belongs with zoom and the
 * ruler, in the corner the other map controls already occupy, instead of
 * adding one more thing hovering over the vehicles.
 */

const useStyles = makeStyles()(() => ({
  button: {
    '&&': {
      display: 'flex',
      alignItems: 'center',
      justifyContent: 'center',
      color: '#333',
    },
    '&.active': {
      backgroundColor: '#e6e6e6',
      borderRadius: 'inherit',
    },
  },
}));

const MapDisruptionToggle = ({ enabled, onChange }) => {
  const theme = useTheme();
  const { classes } = useStyles();
  const buttonRef = useRef();
  // The control is added once; the handler changes with every render, so it is
  // reached through a ref rather than rebuilding the control each time.
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const enabledRef = useRef(enabled);
  enabledRef.current = enabled;

  useEffect(() => {
    let container;
    let root;
    const control = {
      onAdd: () => {
        container = document.createElement('div');
        container.className = 'maplibregl-ctrl maplibregl-ctrl-group';
        const button = document.createElement('button');
        button.type = 'button';
        button.title = 'Roadworks and closures';
        button.className = `maplibregl-ctrl-icon ${classes.button}`;
        button.onclick = () => onChangeRef.current(!enabledRef.current);
        container.appendChild(button);
        root = createRoot(button);
        root.render(<ConstructionIcon fontSize="small" />);
        buttonRef.current = button;
        return container;
      },
      onRemove: () => {
        queueMicrotask(() => root.unmount());
        container.remove();
      },
    };
    map.addControl(control, theme.direction === 'rtl' ? 'top-left' : 'top-right');
    return () => map.removeControl(control);
  }, [theme.direction, classes.button]);

  useEffect(() => {
    buttonRef.current?.classList.toggle('active', enabled);
  }, [enabled]);

  return null;
};

export default MapDisruptionToggle;
