import { fetchJson } from "./api.js";
import { $, escapeHtml, formatDuration, openModal, renderEmpty, renderError, showToast } from "./ui.js";
import { loadHistorySession } from "./playback.js";
import { updatePlannedRoute } from "./mapView.js";

export async function openMissionModal() {
    const container = $("mission-body");
    openModal("mission-modal");
    container.innerHTML = '<div class="empty-state">Loading schedule...</div>';

    try {
        const data = await fetchJson("/api/mission", "Unable to load the current mission schedule.");
        if (!data?.stops?.length) {
            renderEmpty(container, "No active mission schedule is available.");
            return;
        }

        const rows = data.stops.map((stop, index) => `
            <div class="stop-card">
                <div class="stop-card-header">
                    <span class="stop-badge">${index + 1}</span>
                    <span class="stop-name">${escapeHtml(stop.name)}</span>
                </div>
                <div class="stop-details">
                    <div>Mode: ${escapeHtml(stop.mode)} ${stop.transit_type ? `[${escapeHtml(stop.transit_type)}]` : ""}</div>
                    <div>Wait: ${escapeHtml(stop.wait_time || "None")}</div>
                    <div>Coordinate: ${escapeHtml(stop.coord || "Auto")}</div>
                </div>
            </div>
        `).join("");

        container.innerHTML = `<div class="init-loc-banner">Start: ${escapeHtml(data.init_loc)}</div>${rows}`;
    } catch (error) {
        renderError(container, error.message || "Unable to load the current mission schedule.");
    }
}

export async function openHistoryModal() {
    const container = $("history-body");
    openModal("history-modal");
    container.innerHTML = '<div class="empty-state">Loading mission history...</div>';

    try {
        const sessions = await fetchJson("/api/history?limit=100", "Unable to load mission history.");
        if (!sessions.length) {
            renderEmpty(container, "No mission history is available yet.");
            return;
        }

        container.innerHTML = sessions.map((session) => `
            <div class="history-row" data-date="${escapeHtml(session.date)}" data-session="${escapeHtml(session.session)}">
                <div class="history-main">
                    <span class="stop-badge"><i class="fa-solid fa-route"></i></span>
                    <span class="history-title">${escapeHtml(session.id)}</span>
                </div>
                <div class="history-meta">
                    <div>Updated: ${escapeHtml(session.updated_at || "Unknown")}</div>
                    <div>Stops: ${session.stops ?? 0} | Size: ${Math.round((session.csv_size || 0) / 1024)} KB</div>
                    <div>Start: ${escapeHtml(session.start || "Unknown")}</div>
                </div>
            </div>
        `).join("");

        container.querySelectorAll(".history-row").forEach((row) => {
            row.addEventListener("click", async () => {
                container.querySelectorAll(".history-row").forEach((item) => item.classList.remove("active"));
                row.classList.add("active");
                try {
                    await loadHistorySession({
                        date: row.dataset.date,
                        session: row.dataset.session,
                        id: `${row.dataset.date}/${row.dataset.session}`,
                    });
                    showToast("Historical mission loaded.");
                } catch (error) {
                    showToast(error.message || "Unable to load historical mission data.", "error");
                }
            });
        });
    } catch (error) {
        renderError(container, error.message || "Unable to load mission history.");
    }
}

function segmentLabel(segment) {
    const type = String(segment.type || segment.travel_mode || "move").toLowerCase();
    if (type === "walk") return "Walking";
    if (type === "mrt") return "MRT";
    if (type === "bus") return "Bus";
    if (type === "transit") return "Transit";
    return type ? type.charAt(0).toUpperCase() + type.slice(1) : "Move";
}

function renderTransitMeta(segment) {
    const parts = [];
    const line = segment.line_short_name || segment.line_name;
    if (line) parts.push(`Route: ${escapeHtml(line)}`);
    if (segment.vehicle_name || segment.vehicle_type) {
        parts.push(`Vehicle: ${escapeHtml(segment.vehicle_name || segment.vehicle_type)}`);
    }
    if (segment.departure_stop || segment.arrival_stop) {
        parts.push(`Stops: ${escapeHtml(segment.departure_stop || "-")} -> ${escapeHtml(segment.arrival_stop || "-")}`);
    }
    if (segment.departure_time || segment.arrival_time) {
        parts.push(`Time: ${escapeHtml(segment.departure_time || "-")} -> ${escapeHtml(segment.arrival_time || "-")}`);
    }
    if (segment.num_stops) parts.push(`${Number(segment.num_stops)} stops`);
    return parts.map((part) => `<div>${part}</div>`).join("");
}

export async function openNavigationHistoryModal() {
    const container = $("navigation-body");
    openModal("navigation-modal");
    container.innerHTML = '<div class="empty-state">Loading navigation history...</div>';

    try {
        const routes = await fetchJson("/api/navigation_history", "Unable to load navigation history.");
        if (!routes.length) {
            renderEmpty(container, "No navigation history is available for the current mission.");
            return;
        }

        container.innerHTML = routes.map((route, routeIndex) => {
            const segments = Array.isArray(route.segments) ? route.segments : [];
            const segmentRows = segments.map((segment) => `
                <div class="navigation-step ${escapeHtml(segment.type || "")}">
                    <div class="navigation-step-head">
                        <span class="stop-badge">${Number(segment.index || 0) || ""}</span>
                        <div>
                            <div class="navigation-step-title">${escapeHtml(segmentLabel(segment))}${segment.line_short_name ? ` ${escapeHtml(segment.line_short_name)}` : ""}</div>
                            <div class="navigation-step-sub">${escapeHtml(segment.distance_text || "-")} | ${escapeHtml(segment.duration_text || "-")}</div>
                        </div>
                    </div>
                    <div class="navigation-step-body">
                        ${segment.instruction ? `<div>${escapeHtml(segment.instruction)}</div>` : ""}
                        ${renderTransitMeta(segment)}
                    </div>
                </div>
            `).join("");

            return `
                <section class="navigation-route">
                    <div class="navigation-route-head">
                        <div>
                            <div class="history-title">Route ${routeIndex + 1}: ${escapeHtml(route.origin)} -> ${escapeHtml(route.destination)}</div>
                            <div class="history-meta compact">
                                <div>Mode: ${escapeHtml(route.mode || "-")} ${route.requested_transit_type ? `(${escapeHtml(route.requested_transit_type)})` : ""}</div>
                                <div>Distance: ${escapeHtml(route.distance_text || "-")} | Duration: ${escapeHtml(route.duration_text || "-")}</div>
                                <div>Created: ${escapeHtml(route.created_at || "-")}</div>
                            </div>
                        </div>
                    </div>
                    <div class="navigation-steps">${segmentRows || '<div class="empty-state">No step details were returned.</div>'}</div>
                </section>
            `;
        }).join("");
    } catch (error) {
        renderError(container, error.message || "Unable to load navigation history.");
    }
}

export async function refreshSystemStatus() {
    try {
        const data = await fetchJson("/api/system_status", "Unable to load system status.");
        const statusText = (data.mission_stats?.status || (data.mission_active ? "running" : "idle")).toUpperCase();
        const status = $("mission-status");
        status.textContent = statusText;
        status.className = `status-pill ${statusText.toLowerCase()}`;
        $("mission-state-text").textContent = statusText;
        $("p2p-state-text").textContent = data.p2p_target ? "Ready" : "Standby";

        $("mission-progress").textContent = `${data.mission_stats.completed_stops}/${data.mission_stats.total_stops}`;
        $("mission-target").textContent = data.mission_stats.current_target || "Idle";
        $("tunnel-url").textContent = data.p2p_target ? `P2P Target: ${data.p2p_target}` : "Tailscale standby";
        $("elapsed-time").textContent = formatDuration(data.elapsed_seconds);
        $("speed-multiplier").textContent = `${data.speed_multiplier}x`;
        $("guard-interval").textContent = `${data.guard_interval}s`;
        $("route-points").textContent = data.planned_route_points || 0;
        $("mission-generation").textContent = data.mission_generation || 0;
        $("log-session").textContent = data.log_session?.session_dir || "No active log session";
    } catch (error) {
        showToast(error.message || "Unable to load system status.", "error");
    }
}

export async function refreshPlannedRoute() {
    try {
        const points = await fetchJson("/api/planned_route", "Unable to load the planned route.");
        updatePlannedRoute(points);
    } catch (error) {
        showToast(error.message || "Unable to load the planned route.", "error");
    }
}
