import { useEffect, useState } from 'react';
import { useSelector } from 'react-redux';
import { formatAddress } from '../util/formatter';
import { usePreference } from '../util/preferences';
import fetchOrThrow from '../util/fetchOrThrow';

const AddressValue = ({ latitude, longitude, originalAddress }) => {
  const addressEnabled = useSelector((state) => state.session.server.geocoderEnabled);
  const coordinateFormat = usePreference('coordinateFormat');

  const [address, setAddress] = useState(originalAddress);

  useEffect(() => {
    let active = true;
    if (originalAddress) {
      setAddress(originalAddress);
    } else if (addressEnabled && latitude != null && longitude != null) {
      // Auto-resolve the address instead of waiting for a click. On failure
      // (e.g. geocoder rate limit) we silently fall back to coordinates.
      setAddress(undefined);
      (async () => {
        try {
          const query = new URLSearchParams({ latitude, longitude });
          const response = await fetchOrThrow(`/api/server/geocode?${query.toString()}`);
          const text = await response.text();
          if (active) {
            setAddress(text);
          }
        } catch {
          // keep coordinates on failure
        }
      })();
    } else {
      setAddress(undefined);
    }
    return () => {
      active = false;
    };
  }, [latitude, longitude, originalAddress, addressEnabled]);

  if (address) {
    return address;
  }
  return formatAddress({ latitude, longitude }, coordinateFormat);
};

export default AddressValue;
