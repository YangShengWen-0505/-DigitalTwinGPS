# 🛰️ DigitalTwinGPS

<div align="center">

**透過 Tailscale P2P 網路，將模擬 GPS 座標即時串流至 Android 裝置的數位分身系統。**

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.0.0-000000?style=flat-square&logo=flask&logoColor=white)](https://flask.palletsprojects.com)
[![Google Maps](https://img.shields.io/badge/Google%20Maps%20API-Directions-4285F4?style=flat-square&logo=googlemaps&logoColor=white)](https://developers.google.com/maps)
[![Tailscale](https://img.shields.io/badge/Network-Tailscale%20P2P-242424?style=flat-square&logo=tailscale&logoColor=white)](https://tailscale.com)

</div>

---

## 📖 目錄

- [系統概覽](#-系統概覽)
- [架構說明](#️-架構說明)
- [功能特色](#-功能特色)
- [事前準備](#-事前準備)
- [安裝方式](#-安裝方式)
- [環境設定](#️-環境設定)
- [手機端設定（MacroDroid）](#-手機端設定macrodroid)
- [API 文件](#-api-文件)
- [任務格式說明](#-任務格式說明)
- [監控儀表板](#️-監控儀表板)
- [DevContainer](#-devcontainer)
- [常見問題](#-常見問題)

---

## 🌐 系統概覽

**DigitalTwinGPS** 是一套架設在電腦上的伺服器，作為 Android 手機的 **GPS 數位分身**。它透過 Google Maps Directions API 計算多模式路徑、模擬真實人類移動行為（步行噪音、紅綠燈、捷運站停靠），並透過 Tailscale P2P 私人網路，將即時 GPS 座標推送至手機，讓手機看起來像是真實在移動。

```
┌──────────────────────────────────────────────────────────────────┐
│                      DigitalTwinGPS 運作流程                      │
│                                                                  │
│  客戶端 (MacroDroid)  ──POST /start_task──►  Flask 伺服器 (電腦)  │
│                                                    │             │
│                                         Google Maps Directions   │
│                                                    │             │
│                                           導航引擎               │
│                                          (smooth_move_v2)        │
│                                                    │             │
│  Android 手機  ◄──GET /gps?cmd=move&lat=..──  Tailscale P2P    │
│  (Mock GPS)                                                      │
└──────────────────────────────────────────────────────────────────┘
```

---

## 🏗️ 架構說明

```
DigitalTwinGPS/
├── run_server.py                 # 進入點：啟動 Flask 伺服器
├── update_docker.bat             # 快捷指令：讀取最新 .env 並重啟 Docker 容器
├── Caddyfile                     # 生產環境反向代理設定（Caddy TLS internal）
├── requirements.txt              # Python 套件依賴
├── .gitignore                    # Git 排除清單（已包含 .env 與 logs）
├── .env                          # 環境變數（已加入 .gitignore）
├── .env.example                  # 環境變數範本
├── .devcontainer/                # VS Code Dev Container 設定
│   ├── Dockerfile                # 容器環境定義
│   ├── docker-compose.yml        # 定義多容器環境與動態 Port 映射
│   └── devcontainer.json         # VS Code 整合設定
├── logs/                         # 自動產生的日誌目錄
│   ├── server.log                # 持久伺服器日誌
│   └── YYYY-MM-DD/               # 每日資料夾
│       └── HH-MM-SS/             # 每次任務資料夾
│           ├── all.log
│           ├── error.log
│           ├── route.log
│           └── movement.csv      # GPS 軌跡紀錄
└── digital_twin/                 # 主套件
    ├── __init__.py               # Flask App Factory
    ├── config.py                 # 全域設定與 API 客戶端初始化
    ├── state.py                  # 執行緒安全的共享狀態
    ├── logger.py                 # 多層次日誌系統
    ├── api/
    │   ├── __init__.py
    │   ├── routes.py             # HTTP API 路由
    │   └── middleware.py         # API Key 驗證中間件
    ├── core/
    │   ├── __init__.py
    │   └── navigation.py         # 核心導航引擎
    ├── data/
    │   └── settings.json         # 速度設定與捷運站資料庫
    └── templates/
        └── map.html              # 即時監控儀表板（前端單頁應用）
```

---

## ✨ 功能特色

### 🧭 導航引擎
- **多模式路徑規劃** — 步行、捷運（MRT）、公車、機車，透過 Google Maps Directions API
- **平滑移動插值** — 基於時間進度的線性插值，沿 Polyline 路徑點移動
- **GPS 噪音模擬** — 慣性高斯漂移模型，模擬步行時的不穩定軌跡
- **智慧捷運站偵測** — 自動偵測站點；偵測半徑隨 `SPEED_MULTIPLIER` 動態擴充（`max(50, 50 * SPEED_MULTIPLIER)`）
- **紅綠燈模擬** — 步行/公車模式有 25% 機率隨機停等 10–20 秒，模擬真實路口延遲
- **排程等待** — `smart_wait()` 等待至指定時刻（HH:MM 格式）
- **無縫路徑銜接** — 自動偵測當前座標與導航起點差距，平滑插入銜接點防止座標「閃現」
- **極低速最終對齊** — 抵達終點前以 0.75m/s (約 2.7km/h) 極慢速滑入精確座標，模擬真實收尾感

### 🔒 安全性
- **API Key 驗證** — 所有修改性端點需要 `X-API-Key` Header
- **HTTPS 傳輸** — 開發用自簽憑證（可升級至 Caddy 反向代理）
- **Tailscale P2P** — 所有手機通訊透過加密的 Tailscale 覆蓋網路

### 📡 任務控制
- **任務世代計數器** — 透過 `mission_generation` 確保新任務即時搶佔並中止舊執行緒
- **Location Guardian** — 最後防線執行緒；若主流程因 API 延遲卡死，自動補發座標並具備指數退避保護
- **任務統計** — 即時追蹤總站數、完成站數、當前目標位址
- **抵達後原地保持** — 任務完成後自動進入 Holding 模式，持續串流最終位置維持 Mock 狀態

### 📊 監控儀表板（`/map`）
- **即時地圖**（Leaflet.js）— Google Streets / CartoDB Dark / OSM Dark 底圖切換
- **彩色軌跡渲染** — 步行（🟢）、捷運（🔵）、公車（🟠）、等待（🟣）、特殊（🔴）
- **計劃路徑疊加** — 紅色虛線 + 方向箭頭
- **歷史回放** — 時間軸滑桿搜尋，支援播放/暫停
- **系統監控** — 即時 CPU、RAM、任務進度、P2P 目標
- **快速日誌存取** — 直接連結至 all.log、route.log、error.log、movement.csv
- **任務排程檢視** — Modal 顯示所有停靠站、模式與等待時間

### 📝 結構化日誌
| 檔案 | 內容 |
|---|---|
| `logs/server.log` | 伺服器生命週期事件 |
| `HH-MM-SS/all.log` | 任務期間所有日誌 |
| `HH-MM-SS/error.log` | Warning 以上等級 |
| `HH-MM-SS/route.log` | 路由導航事件 |
| `HH-MM-SS/movement.csv` | GPS 座標時序紀錄 |

---

## 📋 事前準備

- Python **3.10+**
- [Google Maps API Key](https://developers.google.com/maps/documentation/directions/get-api-key)，需啟用 **Directions API**
- 電腦與 Android 手機都安裝 [Tailscale](https://tailscale.com)
- 手機端安裝 **MacroDroid**（用於接收 GPS 並設定 Mock Location）

---

## 🚀 安裝方式

### 方式 A — 本機 Python 環境

```bash
# 1. 克隆專案
git clone <repo-url>
cd DigitalTwinGPS

# 2. 建立並啟動虛擬環境
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

# 3. 安裝套件
pip install -r requirements.txt

# 4. 設定環境變數
copy .env.example .env
# 編輯 .env，填入你的 API 金鑰與 IP

# 5. 啟動伺服器
python run_server.py
```

### 方式 B — VS Code Dev Container
1. 安裝 **Docker Desktop** 與 VS Code **Dev Containers** 擴充套件
2. 以 VS Code 開啟專案資料夾
3. 按 `Ctrl+Shift+P` → **Dev Containers: Reopen in Container**
4. 容器自動安裝依賴並根據 `.env` 設定動態開放 Port (預設 5050)

> [!TIP]
> 修改 `.env` 後，可直接執行 `update_docker.bat` 快速應用變更並重啟容器。

---

## ⚙️ 環境設定

### `.env` 檔案

> [!IMPORTANT]
> `.env` 檔案包含敏感的 API Key，已設定由 Git 忽略。部署或移轉時請務必參考 `.env.example` 手動建立。

```ini
GOOGLE_MAPS_API_KEY="AIza..."

# ── Tailscale 網路 ──────────────────────────────────────────────────
# 你的電腦的 Tailscale 虛擬 IP（啟動訊息中顯示的連線網址會用到）
PC_TAILSCALE_IP="100.x.x.x"

# 手機的 Tailscale 虛擬 IP（GPS 座標推送目標）
PHONE_TAILSCALE_IP="100.x.x.x"

# ── API 安全 ────────────────────────────────────────────────────────
# 需與 MacroDroid 發送的 X-API-Key Header 一致
API_SECRET_KEY="your_secure_secret_key_here"

# ── 伺服器模式 ──────────────────────────────────────────────────────
# true = Caddy 反向代理模式（生產環境）
# false = adhoc 自簽憑證（預設，開發環境）
USE_CADDY="false"

# Flask 監聽 Port
FLASK_PORT=5050

# 系統時區
TZ="Asia/Taipei"
```

### `digital_twin/data/settings.json`

```json
{
  "settings": {
    "SPEED_MULTIPLIER": 1,
    "GUARD_INTERVAL": 1.5
  },
  "mrt_stations": {
    "R28 淡水": [25.167750, 121.445680],
    ...
  }
}
```

| 參數 | 預設值 | 說明 |
|---|---|---|
| `SPEED_MULTIPLIER` | `1` | 移動速度倍率（例如 `2` = 2 倍速） |
| `GUARD_INTERVAL` | `1.5` | Guardian 補發座標的觸發間隔（秒） |
| `mrt_stations` | 30+ 個站 | 捷運站座標資料庫（用於站點偵測） |

---

## 📱 手機端設定（MacroDroid）

伺服器透過以下 URL 推送 GPS 座標至手機：

```
GET http://<PHONE_TAILSCALE_IP>:8080/gps?cmd=move&lat=25.xxx&lng=121.xxx
GET http://<PHONE_TAILSCALE_IP>:8080/gps?cmd=stop
```

### MacroDroid 設定步驟

**步驟 1 — 開啟 HTTP 伺服器（接收座標）**

在 MacroDroid 建立一個 Macro：
- **觸發器（Trigger）**：`Web Hook / HTTP Server`
  - Port：`8080`
  - Path：`/gps`
  - Method：`GET`

**步驟 2 — 讀取參數並設定 Mock Location**

在該 Macro 的 **動作（Actions）** 中加入：
1. **If/Else** — 判斷 `[http_server_query_string_cmd]` 的值
2. **若 `cmd == move`**：
   - 使用 `[http_server_query_string_lat]` 與 `[http_server_query_string_lng]` 設定 Mock Location
3. **若 `cmd == stop`**：
   - 停止 Mock Location / 執行停止動作

**步驟 3 — 設定 Mock Location 權限**

- 在 Android 開發者選項中，將 MacroDroid 設為「模擬位置應用程式」

**MacroDroid 收到的 HTTP 參數**

| 參數 | 說明 | 範例 |
|---|---|---|
| `cmd` | 指令類型 | `move` 或 `stop` |
| `lat` | 緯度（字串） | `25.167712` |
| `lng` | 經度（字串） | `121.445683` |

> **注意：** MacroDroid 的 HTTP Server 預設不需要驗證，但 Tailscale 的加密已保護通訊安全。

---

## 📡 API 文件

### 驗證方式

所有修改性端點需要 `X-API-Key` HTTP Header：

```
X-API-Key: your_secure_secret_key_here
```

---

### `POST /start_task`
啟動新的導航任務。

**Headers：** `Content-Type: application/json`、`X-API-Key: <key>`

**Request Body：**
```json
{
  "uuid": "Device-Alpha",
  "init_loc": "25.1677,121.4457",
  "stops": [
    {
      "name": "台北車站",
      "mode": "transit",
      "transit_type": "MRT",
      "wait_time": "09:30",
      "skip_if_late": true,
      "coord": "25.0478,121.5170"
    },
    {
      "name": "信義區",
      "mode": "walking",
      "transit_type": "",
      "wait_time": "",
      "skip_if_late": false,
      "coord": ""
    }
  ]
}
```

| 欄位 | 類型 | 必填 | 說明 |
|---|---|---|---|
| `uuid` | string | 否 | 裝置識別碼（預設：`"Agent"`） |
| `init_loc` | string | ✅ | 起始座標 `"lat,lng"` |
| `stops` | array | ✅ | 停靠站陣列 |
| `stops[].name` | string | ✅ | 目的地名稱或地址（傳入 Google Maps） |
| `stops[].mode` | string | ✅ | `walking` / `transit` / `motorcycle` |
| `stops[].transit_type` | string | 否 | `MRT` 或 `BUS`（mode 為 transit 時有效） |
| `stops[].wait_time` | string | 否 | 出發前等待至此時刻 `"HH:MM"` |
| `stops[].skip_if_late` | bool | 否 | 若已過時刻則跳過等待 |
| `stops[].coord` | string | 否 | 精確目的地座標 `"lat,lng"`，用於最終對齊步行 |

**回應：**
```json
{ "status": "Mission Started" }
```

---

### `GET /stop_task` 或 `POST /stop_task`
立即中止當前任務。

**Headers：** `X-API-Key: <key>`

**回應：**
```json
{ "status": "Mission Aborted" }
```

---

### `GET /api/system_status`
回傳伺服器與任務健康狀態。

```json
{
  "cpu": 12.5,
  "ram": 45.2,
  "devices": 1,
  "active_device": "Device-Alpha",
  "mission_stats": {
    "total_stops": 3,
    "completed_stops": 1,
    "current_target": "台北車站"
  },
  "p2p_target": "100.x.x.x"
}
```

| 欄位 | 說明 |
|---|---|
| `devices` | 任務執行中為 `1`，閒置為 `0` |
| `active_device` | 當前任務 UUID（閒置時為 `null`） |

---

### `GET /api/planned_route`
回傳當前導航步驟的計劃路徑點列表。

```json
[
  { "lat": 25.1677, "lng": 121.4457 },
  { "lat": 25.1680, "lng": 121.4461 }
]
```

---

### `GET /api/csv?start_line=<N>`
從第 N 行開始回傳 CSV 移動記錄（用於增量輪詢）。

```
Timestamp,Latitude,Longitude,Action,Note
2026-05-07 09:30:01,25.167712,121.445683,Walking,
```

---

### `GET /api/log/<log_name>`
回傳日誌檔案內容。`log_name` 可為 `all`、`route`、`error`。

---

### `GET /api/mission`
回傳當前任務資料（起點 + 停靠站陣列）。

---

### `GET /map`
回傳互動式監控儀表板 HTML。

---

## 📦 任務格式說明

### 交通模式

| `mode` 值 | 說明 |
|---|---|
| `walking` | 步行（Google Maps 導航） |
| `transit` + `MRT` | 捷運路徑（優先選擇含地鐵的路線） |
| `transit` + `BUS` | 公車路徑 |
| `motorcycle` | 機車路徑 |

### 移動模擬細節

| 模式 | GPS 噪音 | 紅綠燈 | 站點停靠 |
|---|---|---|---|
| 步行 | ✅ 高斯漂移 | ✅ 25% 機率 | ❌ |
| 捷運 | ❌ | ❌ | ✅ 50 公尺內自動偵測 |
| 公車 | ❌ | ✅ 25% 機率 | ❌ |
| 機車 | ❌ | ❌ | ❌ |

---

## 🗺️ 監控儀表板

**開發模式**（`USE_CADDY=false`，預設）：
- 本地：`https://localhost:<FLASK_PORT>/map`
- 網路：`https://<PC_TAILSCALE_IP>:<FLASK_PORT>/map`

> [!WARNING]
> adhoc 自簽憑證會觸發瀏覽器安全警告，點擊「進階 → 繼續前往」即可。若在手機端瀏覽，建議使用 Chrome 或支援略過 SSL 警告的瀏覽器。

**生產模式**（`USE_CADDY=true` + Caddy 執行中）：
- 本地：`https://localhost/map`
- 網路：`https://<PC_TAILSCALE_IP>/map`

> [!NOTE]
> Caddy 使用 `tls internal` 發行受信任憑證。在信任 Caddy 根憑證的裝置上將顯示為綠色鎖頭。請確保 `Caddyfile` 中的 IP 與你的 `PC_TAILSCALE_IP` 一致。

### 儀表板操作說明

| 控制項 | 說明 |
|---|---|
| **SYS Log** | 在新分頁開啟 all.log |
| **Route Log** | 在新分頁開啟 route.log |
| **Errors** | 在新分頁開啟 error.log |
| **CSV** | 在新分頁開啟原始移動資料 |
| **Schedule** | 顯示當前任務停靠站列表 |
| **Auto Camera** | 切換自動跟隨地圖相機 |
| **Show Points** | 切換顯示個別 GPS 點標記 |
| **Show Route** | 切換顯示計劃路徑疊加層 |
| **底圖** | 切換 Google Streets / OSM Dark / CartoDB Dark |
| **類型篩選** | 依移動模式篩選顯示軌跡 |
| **Clear Traces** | 清除地圖上所有軌跡 |
| **LIVE** | 跳至最新位置並啟用即時追蹤 |
| **時間滑桿** | 搜尋歷史軌跡 |
| **▶ 播放** | 以 10 倍速自動播放歷史軌跡 |

---

## 🐳 DevContainer

本專案包含完整的 VS Code Dev Container 設定。

**規格：**
- **專案名稱**：`DigitalTwinGPS`（容器與專案前綴皆已固定）
- 基底映像：`python:3.10-slim`
- **啟動方式**：基於 `docker-compose` 以支援動態環境變數注入
- **動態 Port**：自動從根目錄 `.env` 讀取 `FLASK_PORT` 進行映射
- VS Code 擴充套件：Python + Pylance + ESLint
- **自動化**：啟動時自動偵測主機 Port 並完成 Port Forwarding

---

## 🔧 常見問題與疑難排解

| 問題 | 解決方式 |
|---|---|
| 瀏覽器顯示 SSL 警告（開發模式） | 點擊「進階 → 繼續前往」—— adhoc 自簽憑證為預期行為 |
| Caddy 憑證不被瀏覽器信任 | 執行 `caddy trust` 安裝 Caddy 根憑證（每台裝置只需一次） |
| 啟動訊息顯示錯誤 IP | 在 `.env` 設定 `PC_TAILSCALE_IP` 為你電腦的 Tailscale 虛擬 IP |
| 手機收不到 GPS | 確認兩端都已連上 Tailscale；確認 `.env` 中 `PHONE_TAILSCALE_IP` 正確 |
| MacroDroid 收不到請求 | 確認手機 MacroDroid HTTP Server 已啟用，監聽 Port `8080`，路徑 `/gps` |
| `Missing GOOGLE_MAPS_API_KEY` 錯誤 | 確認 `.env` 存在且包含有效金鑰，且已啟用 Directions API |
| 儀表板無資料顯示 | 先透過 `POST /start_task` 啟動任務 |
| 任務無法停止 | 確認 `X-API-Key` Header 正確後，發送 `GET /stop_task` |
| 導航路徑不符合預期 | 嘗試在 `stops` 中加入 `transit_type` 指定 `MRT` 或 `BUS` |
| `API_SECRET_KEY` 報錯 | 請確保金鑰長度至少 16 位，並與 MacroDroid 端一致 |
| 新任務無法中止舊任務 | 確認 `X-API-Key` 正確；伺服器會等待 200ms 讓舊執行緒退出後再啟動新任務 |
| 地圖顯示空白 | 檢查 `GOOGLE_MAPS_API_KEY` 是否有效，且已啟用 JavaScript API（雖然本機使用 Leaflet，但部分組件可能參考 API） |
| Caddy 連線失敗 | 檢查 `Caddyfile` 中的 IP 是否與 `.env` 中的 `PC_TAILSCALE_IP` 一致 |

---

<div align="center">
Built with ❤️ — DigitalTwinGPS
</div>
