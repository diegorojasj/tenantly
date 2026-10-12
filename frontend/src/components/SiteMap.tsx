// The Locations map: one pin per placed location, coloured by its live state.
// Leaflet touches `window` on import, so it loads in the browser once the
// component settles; the server renders the empty frame. Picking a pin selects
// the location; in placing mode a click on the map drops the pin there, and the
// selected pin can be dragged when the viewer may edit it.
import 'leaflet/dist/leaflet.css';

import type { LatLngTuple, Map as LeafletMap } from 'leaflet';
import { createEffect, createMemo, createSignal, onSettled, Show } from 'solid-js';
import { env } from 'virtual:env/client';

import { t } from '../lib/i18n';
import type { SiteState } from '../lib/sites';

export interface MapSite {
  id: string;
  name: string;
  code: string;
  pin: [number, number];
  state: SiteState;
}

type Leaflet = typeof import('leaflet');

const escape = (text: string) =>
  text.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]!);

export default function SiteMap(props: {
  sites: Array<MapSite>;
  selectedId: string | null;
  /** Whether the selected pin may be dragged. */
  editable: boolean;
  /** The name of the location being placed: the next click on the map drops its pin. */
  placing: string | null;
  onSelect: (id: string) => void;
  onPlace: (pin: [number, number]) => void;
}) {
  let host: HTMLDivElement | undefined;
  const [ready, setReady] = createSignal<{ L: Leaflet; map: LeafletMap } | null>(null, { name: 'siteMap' });

  onSettled(() => {
    let map: LeafletMap | undefined;
    let gone = false;
    void import('leaflet').then((L) => {
      if (gone || !host) return;
      map = L.map(host, { zoomControl: false, worldCopyJump: true, scrollWheelZoom: false }).setView([20, 0], 2);
      L.control.zoom({ position: 'bottomright' }).addTo(map);
      L.tileLayer(env.VITE_MAP_TILES, { maxZoom: 19, attribution: env.VITE_MAP_ATTRIBUTION }).addTo(map);
      // Wheel zoom only once the map has been clicked, so the page still scrolls past it.
      map.on('focus', () => map?.scrollWheelZoom.enable());
      map.on('blur', () => map?.scrollWheelZoom.disable());
      map.on('click', (event) => {
        if (props.placing) props.onPlace([event.latlng.lat, event.latlng.lng]);
      });
      setReady({ L, map });
    });
    return () => {
      gone = true;
      map?.remove();
    };
  });

  // Pins: redrawn whenever the sites, the selection or the edit rights change.
  createEffect(
    () => ({
      leaflet: ready(),
      sites: props.sites.map((s) => ({ ...s })),
      selected: props.selectedId,
      editable: props.editable,
    }),
    ({ leaflet, sites, selected, editable }) => {
      if (!leaflet) return;
      const { L, map } = leaflet;
      const layer = L.layerGroup().addTo(map);
      for (const site of sites) {
        const isSelected = site.id === selected;
        const marker = L.marker(site.pin, {
          icon: L.divIcon({
            className: 'site-pin',
            html: `<span class="pin pin-${site.state}${isSelected ? ' selected' : ''}"></span>`,
            iconSize: [22, 22],
            iconAnchor: [11, 11],
          }),
          title: site.name,
          alt: site.name,
          keyboard: true,
          riseOnHover: true,
          zIndexOffset: isSelected ? 1000 : 0,
          draggable: editable && isSelected,
        })
          .bindTooltip(`<strong>${escape(site.name)}</strong> <span class="mono">${escape(site.code)}</span>`, {
            direction: 'top',
            offset: [0, -12],
            permanent: isSelected,
            className: 'site-tip',
          })
          .on('click', () => props.onSelect(site.id))
          .addTo(layer);
        marker.on('dragend', () => {
          const at = marker.getLatLng();
          props.onPlace([at.lat, at.lng]);
        });
      }
      return () => layer.remove();
    },
  );

  // Framing: fit every pin when the set of placed locations changes (not on every redraw)…
  const pins = createMemo(() => JSON.stringify(props.sites.map((s) => s.pin)), { name: 'siteMapPins' });
  createEffect(
    () => ({ leaflet: ready(), pins: pins() }),
    ({ leaflet, pins }) => {
      if (leaflet) fitAll(leaflet.L, leaflet.map, JSON.parse(pins) as Array<LatLngTuple>);
    },
  );
  // …and fly to a location when it is selected.
  const focus = createMemo(() => props.sites.find((s) => s.id === props.selectedId)?.pin.join(',') ?? '', {
    name: 'siteMapFocus',
  });
  createEffect(
    () => ({ leaflet: ready(), focus: focus() }),
    ({ leaflet, focus }) => {
      if (!leaflet || !focus) return;
      const [lat, lng] = focus.split(',').map(Number);
      leaflet.map.flyTo([lat, lng], Math.max(leaflet.map.getZoom(), 13), { duration: 0.6 });
    },
    { defer: true },
  );

  return (
    <div class={['site-map', { placing: !!props.placing }]}>
      <div class="site-map-canvas" ref={(el) => (host = el)} role="application" aria-label={t('structure.mapLabel')} />
      <Show when={props.placing}>
        {(name) => (
          <div class="site-map-banner" role="status">
            {t('structure.placingHint', { name: name() })}
          </div>
        )}
      </Show>
      <button
        type="button"
        class="btn small ghost site-map-fit"
        disabled={!props.sites.length}
        onClick={() => {
          const leaflet = ready();
          if (leaflet) fitAll(leaflet.L, leaflet.map, props.sites.map((s) => s.pin));
        }}
      >
        {t('structure.fitAll')}
      </button>
    </div>
  );
}

function fitAll(L: Leaflet, map: LeafletMap, pins: Array<LatLngTuple>) {
  if (!pins.length) return;
  if (pins.length === 1) map.setView(pins[0], 13);
  else map.fitBounds(L.latLngBounds(pins), { padding: [48, 48], maxZoom: 14 });
}
