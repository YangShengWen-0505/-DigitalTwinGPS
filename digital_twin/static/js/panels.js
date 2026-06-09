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
