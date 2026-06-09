import { apiFetch } from "./api.js";
import { $, extractTime, showToast } from "./ui.js";
import { renderRecords, renderRecordsIncremental, updateMarker } from "./mapView.js";

let allRecords = [];
let totalLinesRead = 0;
let isLive = true;
let isPlaying = false;
let playbackIndex = 0;
let playTimer = null;
let csvFetchTimer = null;
let csvFetchInterval = 1000;
let dataSource = { mode: "current", url: "/api/csv" };

function parseCsvLines(csvText, startingLine) {
    const lines = csvText.trim().split("\n").filter((line) => line.length > 0);
    const records = [];
    let lineCursor = startingLine;

    lines.forEach((line, index) => {
        if (lineCursor === 0 && index === 0 && line.startsWith("Timestamp")) {
            lineCursor += 1;
            return;
        }
        const cols = line.split(",");
        if (cols.length >= 4) {
            const lat = parseFloat(cols[1]);
            const lng = parseFloat(cols[2]);
            const action = cols[3].replace(/"/g, "");
            if (!Number.isNaN(lat) && !Number.isNaN(lng)) {
                records.push({ originalIndex: lineCursor, time: cols[0], lat, lng, action });
            }
        }
        lineCursor += 1;
    });

    return { records, nextLine: lineCursor };
}

function syncPlaybackUi() {
    const slider = $("timeSlider");
    slider.max = Math.max(0, allRecords.length - 1);
    slider.value = Math.min(playbackIndex, allRecords.length - 1);
    $("playback-end-time").textContent = allRecords.length ? extractTime(allRecords[allRecords.length - 1].time) : "--:--:--";
}

export function updatePlaybackState() {
    if (!allRecords.length) return;
    const record = allRecords[playbackIndex];
    $("timeSlider").value = playbackIndex;
    $("playback-time").textContent = extractTime(record.time);
    $("lat").textContent = record.lat.toFixed(6);
    $("lng").textContent = record.lng.toFixed(6);
    $("action").textContent = record.action;
    $("lastFix").textContent = extractTime(record.time);
    $("liveMode").textContent = isLive ? "LIVE" : "PLAY";
    $("liveBtn").classList.toggle("active", isLive);
    $("status-title-text").textContent = isLive ? "Current Status (LIVE)" : "Historical Playback";
    updateMarker(record, $("autoFollow").checked);
}

export function toggleLiveMode(forceLive) {
    isLive = forceLive !== undefined ? forceLive : !isLive;
    if (isLive) {
        dataSource = { mode: "current", url: "/api/csv" };
        totalLinesRead = 0;
        allRecords = [];
        playbackIndex = 0;
        renderRecords([]);
        if (isPlaying) togglePlay();
    }
    $("liveBtn").classList.toggle("active", isLive);
    $("liveMode").textContent = isLive ? "LIVE" : "PLAY";
}

export function togglePlay() {
    if (!allRecords.length) {
        showToast("No movement data is available for playback yet.", "error");
        return;
    }
    isPlaying = !isPlaying;
    $("playPauseBtn").innerHTML = isPlaying ? '<i class="fa-solid fa-pause"></i>' : '<i class="fa-solid fa-play"></i>';
    if (!isPlaying) {
        clearInterval(playTimer);
        return;
    }

    isLive = false;
    if (playbackIndex >= allRecords.length - 1) playbackIndex = 0;
    playTimer = setInterval(() => {
        if (playbackIndex < allRecords.length - 1) {
            playbackIndex += 1;
            updatePlaybackState();
        } else {
            togglePlay();
        }
    }, 100);
}

export function clearPlaybackData() {
    allRecords = [];
    totalLinesRead = 0;
    playbackIndex = 0;
    syncPlaybackUi();
    renderRecords([]);
}

export async function loadCsvFromUrl(url, { append = false, live = false } = {}) {
    const response = await apiFetch(url);
    if (response.status === 404) {
        if (!append) clearPlaybackData();
        throw new Error(live ? "No live movement data is available yet." : "No movement CSV was found for this mission.");
    }
    if (!response.ok) throw new Error(`CSV request failed with HTTP ${response.status}.`);

    const text = await response.text();
    if (!text.trim()) return [];

    const start = append ? totalLinesRead : 0;
    const { records, nextLine } = parseCsvLines(text, start);
    totalLinesRead = append ? nextLine : nextLine;

    if (!append) {
        allRecords = records;
        playbackIndex = allRecords.length ? allRecords.length - 1 : 0;
        renderRecords(allRecords);
    } else if (records.length) {
        allRecords.push(...records);
        renderRecordsIncremental(records, allRecords.length);
        if (isLive) playbackIndex = allRecords.length - 1;
    }

    syncPlaybackUi();
    if (allRecords.length) updatePlaybackState();
    return records;
}

export function scheduleLiveCsvFetch() {
    clearTimeout(csvFetchTimer);
    csvFetchTimer = setTimeout(fetchLiveCsvData, csvFetchInterval);
}

export async function fetchLiveCsvData() {
    if (dataSource.mode !== "current") return;
    try {
        const records = await loadCsvFromUrl(`/api/csv?start_line=${totalLinesRead}`, { append: true, live: true });
        csvFetchInterval = records.length ? 1000 : Math.min(csvFetchInterval * 1.2, 1800);
    } catch (error) {
        if (!String(error.message).includes("No live movement data")) {
            showToast(error.message || "Unable to load live CSV data.", "error");
        }
        csvFetchInterval = Math.min(csvFetchInterval * 1.4, 2200);
    } finally {
        scheduleLiveCsvFetch();
    }
}

export async function loadHistorySession(session) {
    if (isPlaying) togglePlay();
    isLive = false;
    dataSource = { mode: "history", url: `/api/history/${encodeURIComponent(session.date)}/${encodeURIComponent(session.session)}/csv` };
    clearPlaybackData();
    await loadCsvFromUrl(dataSource.url, { append: false, live: false });
    $("status-title-text").textContent = `Historical Playback (${session.id})`;
    $("liveMode").textContent = "HISTORY";
    $("liveBtn").classList.remove("active");
}

export function bindPlaybackControls() {
    $("playPauseBtn").addEventListener("click", togglePlay);
    $("liveBtn").addEventListener("click", () => {
        toggleLiveMode(true);
        showToast("Returned to live mode.");
    });
    $("timeSlider").addEventListener("input", (event) => {
        if (isPlaying) togglePlay();
        isLive = false;
        playbackIndex = Number(event.target.value);
        updatePlaybackState();
    });
    $("showPoints").addEventListener("change", () => renderRecords(allRecords));
    $("typeFilter").addEventListener("change", () => renderRecords(allRecords));
}
