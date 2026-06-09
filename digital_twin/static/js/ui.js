let toastTimer = null;

export function $(id) {
    return document.getElementById(id);
}

export function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({
        "&": "&amp;",
        "<": "&lt;",
        ">": "&gt;",
        '"': "&quot;",
        "'": "&#39;",
    }[char]));
}

export function formatDuration(seconds) {
    if (seconds === null || seconds === undefined) return "--:--";
    const total = Math.max(0, Number(seconds) || 0);
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = Math.floor(total % 60);
    return h > 0
        ? `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
        : `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export function extractTime(timestamp) {
    if (!timestamp) return "--:--:--";
    return timestamp.includes(" ") ? timestamp.split(" ")[1] : timestamp;
}

export function showToast(message, type = "info") {
    const toast = $("toast");
    toast.textContent = message;
    toast.className = `toast show ${type === "error" ? "error" : ""}`;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
        toast.className = "toast";
    }, 4200);
}

export function openModal(id) {
    $(id).classList.add("show");
}

export function closeModal(id) {
    $(id).classList.remove("show");
}

export function renderError(container, message) {
    container.innerHTML = `<div class="error-state">${escapeHtml(message)}</div>`;
}

export function renderEmpty(container, message) {
    container.innerHTML = `<div class="empty-state">${escapeHtml(message)}</div>`;
}
