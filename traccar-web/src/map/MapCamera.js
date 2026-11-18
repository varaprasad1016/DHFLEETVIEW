import { useEffect } from 'react';
import * as maplibregl from 'maplibre-gl';
import { map } from './core/MapView';
import { toMapCoordinates } from './core/mapUtil';

// `zoom` is the closest the camera will pull back to; it keeps the user's own
// zoom if they have gone in further. 10 shows a town, which is right for a
// general map and too far out when the point is to see where one vehicle is.
const MapCamera = ({ latitude, longitude, positions, coordinates, zoom = 10 }) => {
  useEffect(() => {
    if (coordinates || positions) {
      const coords = coordinates
        ? coordinates.map(([longitude, latitude]) => toMapCoordinates(longitude, latitude))
        : positions.map((item) => toMapCoordinates(item.longitude, item.latitude));
      if (coords.length) {
        const bounds = coords.reduce(
          (bounds, item) => bounds.extend(item),
          new maplibregl.LngLatBounds(coords[0], coords[0]),
        );
        const canvas = map.getCanvas();
        map.fitBounds(bounds, {
          padding: Math.min(canvas.width, canvas.height) * 0.1,
          duration: 0,
        });
      }
    } else {
      map.jumpTo({
        center: toMapCoordinates(longitude, latitude),
        zoom: Math.max(map.getZoom(), zoom),
      });
    }
  }, [latitude, longitude, positions, coordinates, zoom]);

  return null;
};

export default MapCamera;
