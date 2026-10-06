import { useSelector } from 'react-redux';
import { useTheme } from '@mui/material/styles';
import useMapLayer from '../core/useMapLayer';
import { useAttributePreference } from '../../common/util/preferences';
import { toMapCoordinates } from '../core/mapUtil';
import { trailPoints } from '../../store/session';

// While a vehicle is being followed, its last minute of GPS fixes is drawn as a
// trail behind it, so it is obvious which way it came and whether it is moving.
const MapFollowTrail = () => {
  const theme = useTheme();

  const mapFollow = useAttributePreference('mapFollow', false);
  const selectedDeviceId = useSelector((state) => state.devices.selectedId);
  const device = useSelector((state) => state.devices.items[selectedDeviceId]);
  const trail = useSelector((state) =>
    selectedDeviceId ? state.session.trail[selectedDeviceId] : null,
  );

  const points = mapFollow ? trailPoints(trail) : [];
  const coordinates = points.map(([longitude, latitude]) => toMapCoordinates(longitude, latitude));
  const color = device?.attributes?.['web.reportColor'] || theme.palette.primary.main;

  useMapLayer({
    enabled: coordinates.length > 1,
    layers: [
      {
        type: 'line',
        metadata: { 'traccar:title': 'Follow trail' },
        layout: { 'line-join': 'round', 'line-cap': 'round' },
        paint: { 'line-color': color, 'line-width': 4, 'line-opacity': 0.85 },
      },
      {
        key: 'points',
        type: 'circle',
        filter: ['==', '$type', 'Point'],
        paint: {
          'circle-radius': 3,
          'circle-color': color,
          'circle-opacity': 0.9,
          'circle-stroke-width': 1,
          'circle-stroke-color': '#fff',
        },
      },
    ],
    layersDeps: [color],
    data: {
      type: 'FeatureCollection',
      features: [
        { type: 'Feature', geometry: { type: 'LineString', coordinates }, properties: {} },
        ...coordinates.slice(0, -1).map((coordinate) => ({
          type: 'Feature',
          geometry: { type: 'Point', coordinates: coordinate },
          properties: {},
        })),
      ],
    },
    dataDeps: [coordinates, color],
  });

  return null;
};

export default MapFollowTrail;
