import { $, escapeHtml } from "./ui.js";

export const colors = {
    walk: "#30D158",
    bus: "#FF9F0A",
    mrt: "#0A84FF",
    wait: "#BF5AF2",
    special: "#FF453A",
    guardian: "#86868b",
};

let map;
let currentBaseLayer;
let polylinesLayer;
let pointsLayer;
let plannedRouteLayer;
let twinMarker;
let activePolyline = null;
let activePolylineColor = null;
let lastDrawnRecord = null;
let mapTotalDistance = 0;

function getIconHtml(faIcon) {
    return `<div style="background:rgba(0,0,0,.62);border:1px solid rgba(255,255,255,.22);border-radius:50%;width:30px;height:30px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:14px;box-shadow:0 4px 10px rgba(0,0,0,.32);"><i class="${faIcon}"></i></div>`;
}

const icons = {
    walk: () => L.divIcon({ html: getIconHtml("fa-solid fa-person-walking"), className: "", iconSize: [30, 30], iconAnchor: [15, 15] }),
    bus: () => L.divIcon({ html: getIconHtml("fa-solid fa-bus"), className: "", iconSize: [30, 30], iconAnchor: [15, 15] }),
    mrt: () => L.divIcon({ html: getIconHtml("fa-solid fa-train-subway"), className: "", iconSize: [30, 30], iconAnchor: [15, 15] }),
    wait: () => L.divIcon({ html: getIconHtml("fa-solid fa-hourglass-half"), className: "", iconSize: [30, 30], iconAnchor: [15, 15] }),
};

export function categorizeAction(action) {
    const value = String(action || "").toLowerCase();
    if (value.includes("walk")) return "walk";
    if (value.includes("bus")) return "bus";
    if (value.includes("mrt") || value.includes("station")) return "mrt";
    return "wait";
}

function colorForAction(action) {
    const value = String(action || "").toLowerCase();
    if (value.includes("precision") || value.includes("direct") || value.includes("alignment")) return colors.special;
    if (value.includes("guardian")) return colors.guardian;
    return colors[categorizeAction(action)];
}

function calcDistKm(lat1, lon1, lat2, lon2) {
    const radiusKm = 6371;
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const a = Math.sin(dLat / 2) ** 2
        + Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) * Math.sin(dLon / 2) ** 2;
    return radiusKm * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

function fixLayerOrder() {
    if (map.hasLayer(plannedRouteLayer)) plannedRouteLayer.bringToFront();
    polylinesLayer.bringToFront();
    if ($("showPoints").checked) pointsLayer.bringToFront();
}

export function initMap() {
    if (typeof L === "undefined") {
        throw new Error("Leaflet failed to load. Check your network connection or CDN availability.");
    }

    map = L.map("map", { zoomControl: false }).setView([25.1673, 121.4466], 15);
    L.control.zoom({ position: "bottomright" }).addTo(map);

    const baseMaps = {
        osmDark: L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19 }),
        cartoDark: L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", { maxZoom: 20 }),
        googleStreets: L.tileLayer("https://mt0.google.com/vt/lyrs=m&hl=en&x={x}&y={y}&z={z}", { maxZoom: 20 }),
    };

    currentBaseLayer = baseMaps.googleStreets;
    currentBaseLayer.addTo(map);
    polylinesLayer = L.featureGroup().addTo(map);
    pointsLayer = L.featureGroup().addTo(map);
    plannedRouteLayer = L.polyline([], { color: colors.special, weight: 5, opacity: 0.8, dashArray: "8, 8" }).addTo(map);
    twinMarker = L.marker([0, 0], { icon: icons.walk() }).addTo(map);

    $("mapLayerSelect").addEventListener("change", (event) => {
        map.removeLayer(currentBaseLayer);
        currentBaseLayer = baseMaps[event.target.value];
        currentBaseLayer.addTo(map);
        $("map").classList.toggle("dark-filter", event.target.value === "osmDark");
    });

    $("showPlannedRoute").addEventListener("change", (event) => {
        if (event.target.checked) {
            map.addLayer(plannedRouteLayer);
            if (window.plannedRouteDecorator) map.addLayer(window.plannedRouteDecorator);
            fixLayerOrder();
        } else {
            map.removeLayer(plannedRouteLayer);
            if (window.plannedRouteDecorator) map.removeLayer(window.plannedRouteDecorator);
        }
    });

    $("legend").innerHTML = [
        ["Walk", colors.walk],
        ["MRT", colors.mrt],
        ["Bus", colors.bus],
        ["Wait", colors.wait],
        ["Special", colors.special],
        ["Guardian", colors.guardian],
    ].map(([name, color]) => `<div class="legend-item"><div class="color-dot" style="background:${color}"></div>${name}</div>`).join("");

    let resizeTimer;
    const invalidateMapSize = () => {
        window.clearTimeout(resizeTimer);
        resizeTimer = window.setTimeout(() => map.invalidateSize({ pan: false }), 120);
    };
    window.addEventListener("resize", invalidateMapSize, { passive: true });
    window.addEventListener("orientationchange", invalidateMapSize, { passive: true });
    invalidateMapSize();
}

export function resetMapStats() {
    activePolyline = null;
    activePolylineColor = null;
    lastDrawnRecord = null;
    mapTotalDistance = 0;
    polylinesLayer.clearLayers();
    pointsLayer.clearLayers();
    $("totalPoints").textContent = "0";
    $("totalDistance").innerHTML = '0.00<span class="stat-unit">km</span>';
}

export function renderRecords(records) {
    resetMapStats();
    renderRecordsIncremental(records, records.length);
}

export function renderRecordsIncremental(records, totalCount) {
    const typeFilter = $("typeFilter").value;
    const showPoints = $("showPoints").checked;

    records.forEach((record) => {
        if (typeFilter !== "ALL" && categorizeAction(record.action) !== typeFilter) return;

        const latlng = [record.lat, record.lng];
        const isContinuous = lastDrawnRecord && (record.originalIndex - lastDrawnRecord.originalIndex <= 2);
        if (isContinuous) mapTotalDistance += calcDistKm(lastDrawnRecord.lat, lastDrawnRecord.lng, record.lat, record.lng);

        const recordColor = colorForAction(record.action);
        if (!activePolyline || activePolylineColor !== recordColor || !isContinuous) {
            activePolyline = L.polyline(isContinuous ? [[lastDrawnRecord.lat, lastDrawnRecord.lng], latlng] : [latlng], {
                color: recordColor,
                weight: 5,
                opacity: 0.85,
            }).addTo(polylinesLayer);
            activePolylineColor = recordColor;
        } else {
            activePolyline.addLatLng(latlng);
        }

        if (showPoints) {
            const tooltip = `<div><strong style="color:${recordColor}">${escapeHtml(record.action)}</strong><br><span>${escapeHtml(record.time)}</span></div>`;
            L.circleMarker(latlng, { radius: 4, color: "#fff", weight: 1, fillColor: recordColor, fillOpacity: 0.9 })
                .bindTooltip(tooltip, { className: "custom-tooltip", direction: "top", opacity: 1 })
                .addTo(pointsLayer);
        }
        lastDrawnRecord = record;
    });

    $("totalPoints").textContent = Number(totalCount || 0).toLocaleString();
    $("totalDistance").innerHTML = `${mapTotalDistance.toFixed(2)}<span class="stat-unit">km</span>`;
    fixLayerOrder();
}

export function updateMarker(record, autoFollow) {
    if (!record) return;
    const latlng = [record.lat, record.lng];
    twinMarker.setLatLng(latlng).setIcon((icons[categorizeAction(record.action)] || icons.walk)());
    if (autoFollow) map.panTo(latlng, { animate: true, duration: 0.7, easeLinearity: 0.1 });
}

export function updatePlannedRoute(points) {
    if (!Array.isArray(points) || points.length === 0) {
        plannedRouteLayer.setLatLngs([]);
        if (window.plannedRouteDecorator) {
            map.removeLayer(window.plannedRouteDecorator);
            window.plannedRouteDecorator = null;
        }
        return;
    }

    plannedRouteLayer.setLatLngs(points.map((point) => [point.lat, point.lng]));
    if (window.plannedRouteDecorator) map.removeLayer(window.plannedRouteDecorator);
    window.plannedRouteDecorator = L.polylineDecorator(plannedRouteLayer, {
        patterns: [{ offset: 25, repeat: 100, symbol: L.Symbol.arrowHead({ pixelSize: 12, polygon: false, pathOptions: { stroke: true, weight: 2, color: colors.special } }) }],
    });
    if ($("showPlannedRoute").checked) {
        if (!map.hasLayer(plannedRouteLayer)) map.addLayer(plannedRouteLayer);
        map.addLayer(window.plannedRouteDecorator);
    }
    fixLayerOrder();
}
