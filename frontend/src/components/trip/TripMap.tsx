import { useEffect, useRef, useMemo } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { TripPlan, Block } from "@/lib/types";

// Fix default marker icons for Leaflet + bundlers
delete (L.Icon.Default.prototype as any)._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
});

const DEFAULT_ICON = L.icon({
  iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
});

const HIGHLIGHT_ICON = L.icon({
  iconUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png",
  iconRetinaUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png",
  shadowUrl: "https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png",
  iconSize: [35, 57],
  iconAnchor: [17, 57],
  popupAnchor: [1, -48],
  className: "leaflet-marker-highlight",
});

interface TripMapProps {
  trip: TripPlan;
  hoveredBlockId: string | null;
}

interface MapMarker {
  blockId: string;
  lat: number;
  lng: number;
  title: string;
  kind: string;
}

export default function TripMap({ trip, hoveredBlockId }: TripMapProps) {
  const mapRef = useRef<L.Map | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const markersRef = useRef<Map<string, L.Marker>>(new Map());

  // Collect all blocks with coordinates
  const markers = useMemo<MapMarker[]>(() => {
    const result: MapMarker[] = [];
    for (const day of trip.days ?? []) {
      for (const block of day.blocks) {
        if (block.place_ref?.lat != null && block.place_ref?.lng != null) {
          result.push({
            blockId: block.block_id,
            lat: block.place_ref.lat,
            lng: block.place_ref.lng,
            title: block.title,
            kind: block.kind,
          });
        }
      }
    }
    return result;
  }, [trip]);

  // Initialize map
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = L.map(containerRef.current, {
      zoomControl: true,
      scrollWheelZoom: true,
    }).setView([48.8566, 2.3522], 12);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a>',
      maxZoom: 19,
    }).addTo(map);

    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Update markers when trip data changes
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    // Clear existing markers
    markersRef.current.forEach((m) => m.remove());
    markersRef.current.clear();

    if (markers.length === 0) return;

    // Add new markers
    for (const m of markers) {
      const marker = L.marker([m.lat, m.lng], { icon: DEFAULT_ICON })
        .addTo(map)
        .bindPopup(`<strong>${m.title}</strong><br/><span style="text-transform:capitalize">${m.kind.replace("_", " ")}</span>`);
      markersRef.current.set(m.blockId, marker);
    }

    // Fit bounds
    const bounds = L.latLngBounds(markers.map((m) => [m.lat, m.lng]));
    map.fitBounds(bounds, { padding: [40, 40], maxZoom: 14 });
  }, [markers]);

  // Highlight hovered marker
  useEffect(() => {
    markersRef.current.forEach((marker, blockId) => {
      if (blockId === hoveredBlockId) {
        marker.setIcon(HIGHLIGHT_ICON);
        marker.setZIndexOffset(1000);
        marker.openPopup();
      } else {
        marker.setIcon(DEFAULT_ICON);
        marker.setZIndexOffset(0);
        marker.closePopup();
      }
    });
  }, [hoveredBlockId]);

  return (
    <div
      ref={containerRef}
      className="w-full h-full rounded-lg border border-border/60 overflow-hidden"
      style={{ minHeight: 400 }}
    />
  );
}
