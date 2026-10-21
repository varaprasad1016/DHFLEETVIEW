import { useEffect, useState } from 'react';
import { Popup } from 'maplibre-gl';
import { map } from './core/MapView';
import useMapLayer from './core/useMapLayer';
import { findFonts } from './core/mapUtil';

/*
 * Live closures and roadworks on the strategic road network, from National
 * Highways.
 *
 * Only what is happening now: their feed carries five hundred records, four
 * hundred of which start weeks from today, and a map of those is a map nobody
 * reads. Refreshed every five minutes, which is as often as the server fetches
 * it, and silent on failure - a vehicle map that will not draw because a
 * third-party feed is down would be a poor trade.
 */

const REFRESH_MS = 5 * 60 * 1000;

// Amber for works, red where lanes are shut: the distinction an operator
// actually routes around.
const COLOUR = ['case', ['==', ['get', 'lanes'], 'closed'], '#dc2626', '#f59e0b'];

const MapDisruptions = ({ enabled = true }) => {
  const [features, setFeatures] = useState([]);

  useEffect(() => {
    if (!enabled) {
      setFeatures([]);
      return undefined;
    }
    const controller = new AbortController();
    const load = async () => {
      try {
        const response = await fetch('/api/disruptions', { signal: controller.signal });
        if (!response.ok) return;
        const data = await response.json();
        setFeatures(
          (data.items || [])
            .filter((d) => d.latitude || d.longitude)
            .map((d) => ({
              type: 'Feature',
              geometry: { type: 'Point', coordinates: [d.longitude, d.latitude] },
              properties: {
                road: d.road || '',
                lanes: d.lanes || '',
                where: d.where || '',
                description: d.description || '',
                cause: d.cause || '',
                end: d.end || '',
              },
            })),
        );
      } catch {
        // the fleet matters more than the roadworks: leave the map alone
      }
    };
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [enabled]);

  useMapLayer({
    enabled,
    layers: [
      {
        key: 'point',
        type: 'circle',
        metadata: { 'traccar:title': 'Road disruption' },
        paint: {
          'circle-radius': 7,
          'circle-color': COLOUR,
          'circle-opacity': 0.85,
          'circle-stroke-width': 1.5,
          'circle-stroke-color': '#ffffff',
        },
        on: {
          click: (event) => {
            const p = event.features[0].properties;
            const line = (text) => (text ? `<div style="margin-top:4px">${text}</div>` : '');
            new Popup({ offset: 12, maxWidth: '280px' })
              .setLngLat(event.features[0].geometry.coordinates)
              .setHTML(
                `<div style="font:13px/1.45 system-ui,sans-serif;color:#11151c">
                   <b style="font-size:14px">${p.road || 'Road disruption'}</b>
                   ${p.lanes === 'closed' ? ' <span style="color:#dc2626;font-weight:700">lanes closed</span>' : ''}
                   ${line(p.description)}
                   ${line(`<span style="color:#5b6472">${p.where}</span>`)}
                   ${line(p.end ? `<span style="color:#5b6472">until ${new Date(p.end).toLocaleString('en-GB', { dateStyle: 'medium', timeStyle: 'short' })}</span>` : '')}
                 </div>`,
              )
              .addTo(map);
          },
          mouseenter: () => {
            map.getCanvas().style.cursor = 'pointer';
          },
          mouseleave: () => {
            map.getCanvas().style.cursor = '';
          },
        },
      },
      {
        key: 'label',
        type: 'symbol',
        metadata: { 'traccar:title': 'Road disruption' },
        // Only at close zoom: the road number over every works on the network
        // is unreadable at county scale.
        minzoom: 9,
        layout: {
          'text-field': '{road}',
          'text-font': findFonts(map),
          'text-size': 11,
          'text-offset': [0, 1.1],
          'text-allow-overlap': false,
        },
        paint: {
          'text-color': '#11151c',
          'text-halo-color': '#ffffff',
          'text-halo-width': 1.5,
        },
      },
    ],
    layersDeps: [],
    data: { type: 'FeatureCollection', features },
    dataDeps: [features],
  });

  return null;
};

export default MapDisruptions;
