import { $, closeModal, showToast } from "./ui.js";
import { initMap, resetMapStats } from "./mapView.js";
import { bindPlaybackControls, clearPlaybackData, fetchLiveCsvData } from "./playback.js";
import { openHistoryModal, openMissionModal, openNavigationHistoryModal, refreshPlannedRoute, refreshSystemStatus } from "./panels.js";

function bindShellControls() {
    const sidebar = $("right-sidebar");
    const compactSidebarQuery = window.matchMedia("(max-width: 1180px)");
    const commandMenuBtn = $("commandMenuBtn");
    const compactCommandQuery = window.matchMedia("(max-width: 900px)");
    const statusPanelBtn = $("statusPanelBtn");
    const compactStatusQuery = window.matchMedia("(max-width: 900px)");
    const closeCommandMenu = () => document.body.classList.remove("commands-open");
    const syncCommandMode = () => {
        if (!compactCommandQuery.matches) closeCommandMenu();
    };
    const syncStatusMode = () => {
        if (compactStatusQuery.matches) {
            document.body.classList.remove("status-collapsed");
            document.body.classList.remove("status-open");
        } else {
            document.body.classList.remove("status-open");
            document.body.classList.remove("status-collapsed");
        }
    };
    const syncSidebarMode = () => {
        if (compactSidebarQuery.matches) {
            const open = document.body.classList.contains("tools-open");
            sidebar.classList.toggle("collapsed", !open);
            document.body.classList.remove("tools-collapsed");
        } else {
            document.body.classList.remove("tools-open");
            sidebar.classList.remove("collapsed");
            document.body.classList.remove("tools-collapsed");
        }
    };

    commandMenuBtn.addEventListener("click", () => {
        document.body.classList.toggle("commands-open");
    });
    compactCommandQuery.addEventListener("change", syncCommandMode);
    syncCommandMode();

    statusPanelBtn.addEventListener("click", () => {
        closeCommandMenu();
        if (compactStatusQuery.matches) {
            document.body.classList.toggle("status-open");
            return;
        }
        document.body.classList.toggle("status-collapsed");
    });
    compactStatusQuery.addEventListener("change", syncStatusMode);
    syncStatusMode();

    $("sidebarBtn").addEventListener("click", () => {
        if (compactSidebarQuery.matches) {
            const open = document.body.classList.toggle("tools-open");
            sidebar.classList.toggle("collapsed", !open);
            document.body.classList.remove("tools-collapsed");
            return;
        }
        const collapsed = sidebar.classList.toggle("collapsed");
        document.body.classList.toggle("tools-collapsed", collapsed);
    });
    compactSidebarQuery.addEventListener("change", syncSidebarMode);
    syncSidebarMode();

    $("scheduleBtn").addEventListener("click", () => {
        closeCommandMenu();
        openMissionModal();
    });
    $("historyBtn").addEventListener("click", () => {
        closeCommandMenu();
        openHistoryModal();
    });
    $("navigationHistoryBtn").addEventListener("click", () => {
        closeCommandMenu();
        openNavigationHistoryModal();
    });
    $("clearTracks").addEventListener("click", () => {
        clearPlaybackData();
        resetMapStats();
        showToast("Visible traces were cleared.");
    });

    document.querySelectorAll("[data-close-modal]").forEach((button) => {
        button.addEventListener("click", () => closeModal(button.dataset.closeModal));
    });

    document.querySelectorAll("[data-open-log]").forEach((button) => {
        button.addEventListener("click", () => {
            closeCommandMenu();
            window.open(`/api/log/${button.dataset.openLog}`, "_blank");
        });
    });

    document.querySelector("[data-open-csv]").addEventListener("click", () => {
        closeCommandMenu();
        window.open("/api/csv", "_blank");
    });

    document.querySelector(".logout-form").addEventListener("submit", closeCommandMenu);

    document.querySelectorAll(".modal").forEach((modal) => {
        modal.addEventListener("click", (event) => {
            if (event.target === modal) closeModal(modal.id);
        });
    });
}

async function boot() {
    try {
        initMap();
        bindShellControls();
        bindPlaybackControls();
        await refreshSystemStatus();
        await refreshPlannedRoute();
        await fetchLiveCsvData();
        setInterval(refreshSystemStatus, 1000);
        setInterval(refreshPlannedRoute, 1500);
    } catch (error) {
        showToast(error.message || "Dashboard initialization failed.", "error");
        console.error(error);
    }
}

boot();
