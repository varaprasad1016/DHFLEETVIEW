import { useCallback, useEffect } from 'react';
import { useSelector } from 'react-redux';
import { map } from './core/MapView';
import MapMarkers from './MapMarkers';
import { formatTime } from '../common/util/formatter';
import { useTranslation } from '../common/components/LocalizationProvider';
import { mapIconKey } from './core/preloadImages';
import {
  drivingSpeed,
  getVehicleStatus,
  getStatusColor as getVehicleStatusColor,
} from '../common/util/vehicleStatus';
import { useAttributePreference } from '../common/util/preferences';
import { fromMapCoordinates } from './core/mapUtil';

const MapPositionMarkers = ({
  positions,
  onMapClick,
  onMarkerClick,
  showStatus,
  selectedPosition,
  titleField,
  disabled,
}) => {
  const devices = useSelector((state) => state.devices.items);
  const selectedDeviceId = useSelector((state) => state.devices.selectedId);

  const mapCluster = useAttributePreference('mapCluster', true);
  const directionType = useAttributePreference('mapDirection', 'selected');
  const speedUnit = useAttributePreference('speedUnit', 'mph');
  const t = useTranslation();

  const onMapClickCallback = useCallback(
    (event) => {
      if (!event.defaultPrevented && onMapClick) {
        const [longitude, latitude] = fromMapCoordinates(event.lngLat.lng, event.lngLat.lat);
        onMapClick(latitude, longitude);
      }
    },
    [onMapClick],
  );

  useEffect(() => {
    map.on('click', onMapClickCallback);
    return () => map.off('click', onMapClickCallback);
  }, [onMapClickCallback]);

  const buildMarker = (position) => {
    const device = devices[position.deviceId];
    let showDirection;
    switch (directionType) {
      case 'none':
        showDirection = false;
        break;
      case 'all':
        showDirection = position.course > 0;
        break;
      default:
        showDirection = selectedPosition?.id === position.id && position.course > 0;
        break;
    }
    // Ignition-based coloring: gray when ignition OFF / parked, green when running (spec)
    // DVR/CNMS unchanged (ignition), Teltonika via fallback (io239 etc). Preserve custom color if set.
    let color;
    if (showStatus) {
      if (position.attributes.color) {
        color = position.attributes.color;
      } else {
        const vehicleStatus = getVehicleStatus(device, position);
        // Without a lock the pin is the last known one, not where the vehicle
        // is now. Grey says that; amber would read as a vehicle sitting there.
        color = vehicleStatus === 'nofix' ? 'neutral' : getVehicleStatusColor(vehicleStatus);
      }
    } else {
      color = 'neutral';
    }
    // While a vehicle is driving its speed sits under the name on the map, so it
    // is readable without opening the vehicle.
    const speed = showStatus ? drivingSpeed(device, position, speedUnit, t) : null;
    // A stale pin says so on the map itself, rather than looking like a parked
    // lorry at a place it left hours ago.
    const stale =
      showStatus && getVehicleStatus(device, position) === 'nofix'
        ? `no satellite lock · last fix ${formatTime(position.fixTime, 'minutes')}`
        : null;
    const titles = {
      name: [device.name, speed, stale].filter(Boolean).join('\n'),
      fixTime: formatTime(position.fixTime, 'seconds'),
    };
    return {
      id: position.id,
      deviceId: position.deviceId,
      latitude: position.latitude,
      longitude: position.longitude,
      image: `${mapIconKey(device.category)}-${color}`,
      title: titles[titleField || 'name'],
      rotation: position.course,
      direction: showDirection,
    };
  };

  const markers = positions.filter((it) => devices.hasOwnProperty(it.deviceId)).map(buildMarker);

  const onClick = useCallback(
    (properties) => onMarkerClick?.(properties.id, properties.deviceId),
    [onMarkerClick],
  );

  return (
    <>
      <MapMarkers
        markers={markers.filter((it) => it.deviceId !== selectedDeviceId)}
        showTitles
        direction
        cluster={mapCluster}
        onClick={onClick}
        disabled={disabled}
      />
      <MapMarkers
        markers={markers.filter((it) => it.deviceId === selectedDeviceId)}
        showTitles
        direction
        onClick={onClick}
        disabled={disabled}
      />
    </>
  );
};

export default MapPositionMarkers;
