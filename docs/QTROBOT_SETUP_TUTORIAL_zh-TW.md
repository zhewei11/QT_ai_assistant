# QTrobot AI 衛教助理完整建置教學

本教學說明如何將本專案部署到 QTrobot，內容包含：

1. 讓電腦與 QTrobot 位於可互通的網路。
2. 將 QTrobot 的 Wi-Fi 設為 DHCP 自動取址。
3. 使用 SSH 登入並部署 `qt_ai_assistant`。
4. 安裝及操作 YuGuard iOS Bluetooth App。
5. 啟動並測試 ReSpeaker、NVIDIA Riva 語音辨識及 QTrobot 語音輸出。
6. 啟動完整 AI + 語音 + ECG 流程。

> 名稱說明：原始需求中的「Jable 語音」在本 repository 中沒有同名程式或設定。本專案實際使用的是 **NVIDIA Riva 語音辨識**與 **QTrobot TTS 語音輸出**，因此本文件以 Riva 語音流程為準。如果「Jable」是另一台硬體或第三方服務，需取得它的型號或程式後再補充對應章節。

---

## 1. 系統架構

```text
使用者說話
    ↓
QTrobot ReSpeaker 麥克風
    ↓  ROS topic: /qt_respeaker_app/channel0
NVIDIA Riva ASR（中文語音轉文字）
    ↓  ZeroMQ: tcp://localhost:5555
AI Assistant（意圖辨識、問答、ECG 指令）
    ↓  ZeroMQ: tcp://localhost:5556
ROS Behavior Dispatcher
    ├─ QTrobot TTS 說話
    ├─ 表情與手勢
    └─ 啟動 ECG 量測及臉部儀表板

YuGuard ECG 裝置
    ↓  Bluetooth Low Energy
iPhone YuGuard App
    ↓  Firebase Realtime Database
QTrobot ECG 分析程式與網頁儀表板
```

主要目錄：

```text
qtrobot/
├── bluetooth/ecg_blooth/                  # 正式 YuGuard iOS App
└── tutorials/demos/qt_ai_assistant/       # QTrobot 主專案
    ├── ai/                                 # AI / LangGraph
    ├── ros/                                # Riva ASR 與機器人控制
    ├── ecg/                                # ECG 接收、分析及 dashboard
    ├── config/                             # ECG 整合設定
    └── scripts/run.sh                      # 一鍵啟動
```

---

## 2. 準備項目

### 2.1 硬體

- QTrobot，包含 body computer、face Raspberry Pi、螢幕、喇叭及 ReSpeaker。
- 可執行 Xcode 的 Mac。
- 實體 iPhone 或 iPad；iOS Simulator 無法測試實際 BLE 裝置。
- YuGuard ECG 藍牙裝置及電極。
- 可提供 DHCP 的無線基地台或手機熱點。
- 現場網路救援用 USB 鍵盤；必要時準備滑鼠，並確認接到 QTRP 對應的 USB port。

### 2.2 需要記錄的值

先建立一份現場設定表。不要將密碼或 API key 寫入 Git：

| 名稱 | 範例 | 說明 |
|---|---|---|
| Wi-Fi SSID | `Lab-WiFi` | QTrobot 要連線的無線網路 |
| QTrobot serial | `QTRD000123` | QTRP 的 `.local` 名稱通常由此產生 |
| QTRP 外部 IP | `172.20.10.8` | 實驗室／熱點 DHCP 配發，切換網路後會改變 |
| QTRP 內部 IP | `192.168.100.1` | 本專案記錄的 QTRP／face Raspberry Pi 位址 |
| QTPC 內部 IP | `192.168.100.2` | 本專案記錄的 body computer 位址 |
| 專案遠端路徑 | `~/robot/code/tutorials/QT_ai_assistant` | 部署腳本預設值 |
| Firebase device path | `devices/yuguard_01` | iOS App 與後端必須一致 |

> QTrobot 常見內部網路為 face Raspberry Pi `192.168.100.1`、body computer `192.168.100.2`。此固定網段可能依機器版本而不同，務必先用 `ip addr` 確認。**不要為了外部上網而任意修改內部 `eth0` 固定 IP。**

---

## 3. QTrobot 網路與手機熱點

本專案使用 ROS Noetic，並在既有文件中記錄 QTRP／face Raspberry Pi 為 `192.168.100.1`、QTPC／body computer 為 `192.168.100.2`。這與 LuxAI 官方的 QTrobot QTRP + QTPC 架構相符：

- 外部 Wi-Fi 由頭部 QTRP 管理。
- QTRP 透過內部 Ethernet 將網路分享給 QTPC。
- `qt_wlan0_client` 負責連接實驗室／家用 Wi-Fi。
- `qt_wlan0_ap` 負責 QTrobot 自己的 hotspot。
- `qt_wifi_manager` 在開機時檢查連線；外部網路失敗時會嘗試恢復 QTrobot hotspot。

> 重要：這個架構不是一般 Ubuntu laptop 的 NetworkManager 設定。不要套用 `nmcli`、Netplan、手動啟用 NetworkManager，或修改其他 systemd network 檔案。LuxAI 官方也要求不要停用或修改 `qt_wifi_manager`，否則可能破壞 QTrobot 的開機網路與 QTRP／QTPC 互連。

官方參考：

- [Connect QTrobot to a home network and Internet](https://docs.luxai.com/docs/intro_code#3-connect-qtrobot-to-a-home-network-and-internet)
- [QTrobot Computation and networking](https://docs.luxai.com/docs/modules/processor#networking)

### 3.1 實機架構確認

在修改手機熱點設定前，先將螢幕與鍵盤接到 QTPC。在 QTPC terminal 連進 QTRP：

```bash
ssh developer@192.168.100.1
# 官方預設密碼：qtrobot
```

只執行以下唯讀檢查：

```bash
hostname
cat /etc/os-release
ip -br addr

systemctl is-active qt_wlan0_client.service
systemctl is-enabled qt_wlan0_client.service
systemctl is-active qt_wlan0_ap.service
systemctl is-enabled qt_wlan0_ap.service
systemctl is-active qt_wifi_manager.service
systemctl is-enabled qt_wifi_manager.service

sudo wpa_cli -i wlan0 status
systemctl status qt_wlan0_client.service --no-pager
```

預期至少看到：

- 目前所在主機是 QTRP，而不是 QTPC。
- `wlan0` 存在。
- 使用 `qt_wlan0_client.service` 與 `qt_wifi_manager.service`。
- `wpa_state=COMPLETED` 時，`ssid` 是目前的實驗室 Wi-Fi，且 `ip_address` 是實驗室 DHCP 位址。
- `qt_wlan0_ap` 與 `qt_wlan0_client` 不會同時啟用。

QTRD000629 實機已確認：

| 項目 | 實機結果 |
|---|---|
| QTRP hostname | `QTRD000629` |
| QTRP 內部 Ethernet | `eth0 = 192.168.100.1/24` |
| 目前外部 Wi-Fi | `wlan0 = 192.168.0.153/24`，由 CBICLAB DHCP 配發 |
| Wi-Fi client | `qt_wlan0_client.service = active/enabled` |
| QTrobot AP | `qt_wlan0_ap.service = inactive` |
| Wi-Fi manager | `qt_wifi_manager.service = active/enabled` |
| wpa_supplicant | `wpa_state=COMPLETED` |

實機的已存網路與優先權：

| Network ID | SSID | Priority | 用途 |
|---:|---|---:|---|
| 0 | `Zheway` | 20 | 手機熱點 |
| 1 | `Jarvis` | 20 | 另一組已存網路 |
| 2 | `CBICLAB` | 10 | 實驗室 Wi-Fi |

數字較大的 network priority 優先。因此 `Zheway` 與 CBICLAB 同時可用時，QTRP 會優先選 `Zheway`。目前不需要再新增手機熱點，也不需要修改 wpa_supplicant 設定。

### 3.2 為什麼開機有時連不到手機熱點

實機的 `/etc/luxai/ros/qt_wifi_manager.sh` 流程已確認為：

```text
開機啟動 qt_wlan0_client
    ↓
等待 wlan0 取得 routable IP，最多 30 秒
    ├─ 30 秒內成功：維持 Wi-Fi client 模式
    └─ 30 秒內失敗：
         停止 qt_wlan0_client
         等待 2 秒
         啟動 qt_wlan0_ap
         等待 AP 最多 10 秒
```

因此，若 QTRP 開機時 `Zheway` 還沒有開始廣播、手機尚未允許其他裝置加入，或 DHCP 未能在 30 秒內完成，QTrobot 會依原廠設計切回自己的 AP。之後才開啟 `Zheway` 不會自動切回，因為 `qt_wlan0_client` 已被 manager 停止。

日誌中的開機日期突然從 8 月 7 日跳到 8 月 31 日，推測是 QTRP 開機時尚未完成網路校時，連線後才由 NTP 修正；不代表 Wi-Fi 真的等待了多日。

### 3.3 正確的手機熱點開機順序

1. 先在手機開啟 `Zheway` 熱點。
2. 確認手機允許其他裝置加入，且熱點名稱與密碼沒有變更。
3. 保持手機熱點可被搜尋；第一次連線時可暫時停留在熱點設定頁。
4. 等待約 5–10 秒後再開啟 QTrobot。
5. QTrobot 開機後，必須在 30 秒內完成 Wi-Fi association 與 DHCP。
6. 讓 Mac 也加入 `Zheway`，再使用 QTRP 的新 DHCP IP 或 `QTRD000629.local` 連線。

這台實機已在 CBICLAB 使用 `5220 MHz` 與 `802.11ac`，因此確認可使用 5 GHz。手機熱點是否使用 2.4 GHz 或 5 GHz不是目前的主要問題；只有在 QTRP 完全掃描不到 `Zheway` 時，才需要嘗試手機的相容／2.4 GHz 模式。

開機後可在 QTRP 驗證：

```bash
sudo wpa_cli -i wlan0 status
ip -4 addr show wlan0
networkctl status wlan0 --no-pager
```

成功時應看到：

```text
ssid=Zheway
wpa_state=COMPLETED
ip_address=<手機熱點配發的IP>
```

### 3.4 從 CBICLAB 手動切到 Zheway

切換 Wi-Fi 會中斷目前經由 CBICLAB 的遠端 SSH。建議在 QTPC 接螢幕與鍵盤操作，或先確保能使用 QTrobot 自己的 AP 作為恢復路徑。

1. 先開啟 `Zheway` 手機熱點。
2. 從 QTPC 進入 QTRP：

```bash
ssh developer@192.168.100.1
```

3. 確認 network 0 已啟用，再要求 wpa_supplicant 重新選擇網路：

```bash
sudo wpa_cli -i wlan0 enable_network 0
sudo wpa_cli -i wlan0 reassociate
```

4. 等待數秒後檢查：

```bash
sudo wpa_cli -i wlan0 status
```

若仍停在 CBICLAB，可暫時指定 Zheway：

```bash
sudo wpa_cli -i wlan0 select_network 0
```

`select_network 0` 會在目前這次 wpa_supplicant 執行期間停用其他 network。要恢復自動選擇全部已存網路：

```bash
sudo wpa_cli -i wlan0 enable_network all
sudo wpa_cli -i wlan0 reassociate
```

不要執行 `save_config`，即可避免把這次臨時選擇意外寫回設定檔。

### 3.5 離開實驗室後：從頭部螢幕恢復網路

離開 CBICLAB 後，若 QTRP 沒有在開機 30 秒內連上手機熱點，外部網路與 Mac SSH 入口都不存在。現場主要恢復方式是直接在 QTrobot 頭部 QTRP 螢幕開 terminal。

QTrobot 頭部顯示器連接到 QTRP，[LuxAI 官方說明](https://docs.luxai.com/docs/modules/display)它可作為一般 Linux 顯示器使用，但不是觸控螢幕。因此現場需準備接到 QTRP 的 USB 鍵盤；若桌面需要點選，也要準備滑鼠。

#### 已保存 Zheway 時

1. 先開啟 `Zheway` 手機熱點並保持可被搜尋。
2. 在頭部螢幕使用桌面選單或系統設定的 terminal 快捷鍵開啟 terminal。
3. 確認 terminal prompt 是 QTRP：

```bash
hostname
```

預期輸出：

```text
QTRD000629
```

4. 檢查目前是否已切回 QTrobot AP：

```bash
systemctl is-active qt_wlan0_ap.service
systemctl is-active qt_wlan0_client.service
```

5. 停止 AP 並重新啟動 Wi-Fi client：

```bash
sudo systemctl stop qt_wlan0_ap.service
sudo systemctl restart qt_wlan0_client.service
```

6. 等待約 5–15 秒後驗證：

```bash
sudo wpa_cli -i wlan0 status
ip -4 addr show wlan0
```

成功時應看到 `ssid=Zheway`、`wpa_state=COMPLETED` 與手機 DHCP 配發的 `ip_address`。

#### 手機熱點尚未保存或名稱／密碼已變更時

只有在 `sudo wpa_cli -i wlan0 list_networks` 找不到新的 SSID 時，才修改 LuxAI 指定的設定檔。先備份：

```bash
sudo cp -a /etc/wpa_supplicant/wpa_supplicant-wlan0.conf \
  /etc/wpa_supplicant/wpa_supplicant-wlan0.conf.backup-before-mobile
```

編輯正確的檔案：

```bash
sudo nano /etc/wpa_supplicant/wpa_supplicant-wlan0.conf
```

保留原有 CBICLAB 等 network block，在檔案末端新增：

```text
network={
    ssid="<NEW_HOTSPOT_SSID>"
    psk="<NEW_HOTSPOT_PASSWORD>"
    priority=20
}
```

儲存後執行：

```bash
sudo systemctl stop qt_wlan0_ap.service
sudo systemctl restart qt_wlan0_client.service
```

確認連線：

```bash
sudo wpa_cli -i wlan0 list_networks
sudo wpa_cli -i wlan0 status
```

不要把此設定檔內容貼到 issue、報告或 terminal log，因為 `psk` 可能是明碼密碼。

若編輯後無法啟動 client，可從仍開著的頭部 terminal 還原：

```bash
sudo cp -a /etc/wpa_supplicant/wpa_supplicant-wlan0.conf.backup-before-mobile \
  /etc/wpa_supplicant/wpa_supplicant-wlan0.conf
sudo systemctl restart qt_wlan0_client.service
```

#### 連線失敗時恢復 QTrobot AP

若手機熱點仍無法使用，可從頭部 terminal 回到原廠 offline AP：

```bash
sudo systemctl stop qt_wlan0_client.service
sudo systemctl start qt_wlan0_ap.service
```

確認：

```bash
systemctl is-active qt_wlan0_ap.service
networkctl status wlan0 --no-pager
```

之後 Mac 應可看到 `QTRD000629` Wi-Fi。

#### Mac 連 QTRD000629 的備援路徑

若 `QTRD000629` AP 正常出現，也可以不用操作頭部 terminal：

1. 讓 Mac 連到 `QTRD000629` Wi-Fi。
2. 依原廠 offline 模式登入 QTPC：

```bash
ssh qtrobot@192.168.100.2
```

3. 從 QTPC 進入 QTRP：

```bash
ssh developer@192.168.100.1
```

4. 開啟 `Zheway` 後，在 QTRP 執行：

```bash
sudo systemctl stop qt_wlan0_ap.service
sudo systemctl restart qt_wlan0_client.service
```

執行後 `QTRD000629` AP 與目前 SSH 會中斷，這是正常現象。等待 QTRP 連上 `Zheway`，再讓 Mac 也加入 `Zheway`。

在手機的已連線裝置清單查找 QTRP 新 IP，或嘗試：

```bash
ping QTRD000629.local
```

找到 QTRP 後，透過 ProxyJump 回到 QTPC：

```bash
ssh -J developer@<QTRP_HOTSPOT_IP_OR_QTRD000629.local> qtrobot@qtpc
```

### 3.6 安全限制

- 不修改 `/etc/luxai/ros/qt_wifi_manager.sh` 的 30 秒 timeout。
- 不停用 `qt_wifi_manager.service`。
- 不直接修改 `/etc/systemd/network/08-wifi.network`；client service 每次啟動都會用 LuxAI 提供的檔案覆蓋它。
- 不使用 `nmcli` 或 Netplan 管理這台 QTRP 的 Wi-Fi。
- 不修改 QTRP／QTPC 內部 `eth0` 的 `192.168.100.1/2`。
- `qt_wlan0_client` 與 `qt_wlan0_ap` 互相衝突，不應同時啟動。
- 手機熱點名稱或密碼若改變，需依 LuxAI 官方方式更新指定的 `/etc/wpa_supplicant/wpa_supplicant-wlan0.conf`，並先備份原檔。


---

## 4. 透過 SSH 連線 QTrobot

### 4.1 在 QTrobot 端確認 SSH

```bash
hostname
hostname -I
sudo systemctl status ssh --no-pager
```

不要先修改 SSH service。只確認它在 QTRP 與 QTPC 上是否已經是 `active (running)`。

### 4.2 Offline：連到 QTrobot 自己的 hotspot

若外部 Wi-Fi 連線失敗，先在 Mac 的 Wi-Fi 清單尋找以機器人 serial 命名的 `QTRD...` hotspot。連上後，官方提供的 QTPC 固定入口為：

```bash
ssh qtrobot@192.168.100.2
```

### 4.3 Online：透過 QTRP 跳到 QTPC

當 QTrobot 已連上實驗室 Wi-Fi 或手機熱點時，先找 QTRP 的外部 DHCP IP。可在 QTPC terminal 執行：

```bash
ssh qtrp 'ip -4 addr show wlan0'
```

也可以從 Mac 嘗試使用機器人 serial 的 mDNS 名稱；並非所有網路都允許 mDNS：

```bash
ping <QTROBOT_SERIAL>.local
```

取得 QTRP IP 或名稱後，使用 SSH ProxyJump 進入 QTPC：

```bash
ssh -J developer@<QTRP_IP_OR_SERIAL.local> qtrobot@qtpc
```

官方預設的 QTRP 使用者為 `developer`，QTPC 使用者為 `qtrobot`。密碼依實機設定；原廠預設通常為 `qtrobot`。

第一次連線會詢問 host fingerprint。請先在 QTrobot 執行 `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub`，比對無誤後再輸入 `yes`。

登入後確認連到正確主機：

```bash
whoami
hostname
ip -4 addr
```

### 4.4 設定 SSH key（實機網路確認後）

在 Mac 建立 key；如果已經有 `~/.ssh/id_ed25519` 可略過：

```bash
ssh-keygen -t ed25519 -C "qtrobot-deploy"
```

先將 key 安裝到 QTRP：

```bash
ssh-copy-id developer@<QTRP_IP_OR_SERIAL.local>
```

再經由 QTRP 安裝到 QTPC：

```bash
ssh-copy-id \
  -o ProxyJump=developer@<QTRP_IP_OR_SERIAL.local> \
  qtrobot@qtpc
```

驗證免密登入：

```bash
ssh -o BatchMode=yes \
  -J developer@<QTRP_IP_OR_SERIAL.local> \
  qtrobot@qtpc 'hostname'
```

也可在 Mac 的 `~/.ssh/config` 建立固定別名：

```sshconfig
Host qtrp
    HostName <QTRP_IP_OR_SERIAL.local>
    User developer
    IdentityFile ~/.ssh/id_ed25519

Host qtrobot qtpc
    HostName qtpc
    User qtrobot
    IdentityFile ~/.ssh/id_ed25519
    ProxyJump qtrp
```

之後即可使用：

```bash
ssh qtrobot
```

若 QTPC 需要遠端控制 QTRP 顯示 ECG，也要**從 QTPC**設定到 QTRP 的 SSH key：

```bash
ssh-copy-id <FACE_USER>@<QT_FACE_IP>
ssh -o BatchMode=yes <FACE_USER>@<QT_FACE_IP> 'hostname'
```

---

## 5. 部署專案到 QTrobot

### 5.1 由 Mac 預覽部署內容

在 Mac 執行：

```bash
cd /Users/zhangzhewei/Documents/qtrobot/tutorials/demos/qt_ai_assistant

DEPLOY_SSH_OPTS="-J developer@<QTRP_IP_OR_SERIAL.local>" \
DEPLOY_DRY_RUN=true \
./scripts/deploy_to_robot.sh qtrobot@qtpc
```

確認清單沒有敏感環境檔或不必要的大型檔案後，正式部署：

```bash
DEPLOY_SSH_OPTS="-J developer@<QTRP_IP_OR_SERIAL.local>" \
./scripts/deploy_to_robot.sh qtrobot@qtpc
```

若 Mac 是直接連到 QTrobot 自己的 `QTRD...` hotspot，則不需要 ProxyJump：

```bash
./scripts/deploy_to_robot.sh qtrobot@192.168.100.2
```

此腳本預設部署到：

```text
~/robot/code/tutorials/QT_ai_assistant
```

它預設不會上傳 `.env`、虛擬環境、cache、runtime、log 與 Git metadata。若現場無法使用 `rsync`，請參考 [`scp_deploy_without_env.md`](scp_deploy_without_env.md)。

### 5.2 在 QTrobot 設定環境檔

登入 QTrobot：

```bash
ssh qtrobot
cd ~/robot/code/tutorials/QT_ai_assistant
```

此處假設已依 4.4 節建立 SSH alias；若沒有，請使用 4.2 或 4.3 節對應的完整 SSH 指令。

若設定檔尚未建立：

```bash
cp config/ecg_integration.env.example config/ecg_integration.env
```

編輯 ECG 整合設定：

```bash
nano config/ecg_integration.env
```

至少確認：

```dotenv
ECG_ENABLED=true
ECG_FIREBASE_DATABASE_URL=https://ecg-monitor-bf64d-default-rtdb.firebaseio.com
ECG_FIREBASE_DEVICE_PATH=devices/yuguard_01
ECG_DASHBOARD_URL=https://ecg-monitor-bf64d.web.app
QT_FACE_HOST=<QT_FACE_IP>
QT_FACE_USER=<FACE_USER>
QT_FACE_DISPLAY=:0
```

`ECG_FIREBASE_DEVICE_PATH` 必須和 iOS App 的 `devices/yuguard_01` 一致。初次整合建議保持：

```dotenv
ECG_MEASURE_ON_START=false
ECG_OPEN_DASHBOARD_ON_START=false
ECG_YBC_MODEL_ENABLED=false
```

接著編輯 AI 設定：

```bash
nano ai/config/.env
```

至少放入本專案需要的服務 key，例如：

```dotenv
OPENAI_API_KEY=<YOUR_OPENAI_API_KEY>
TAVILYT_API_KEY=<YOUR_TAVILY_API_KEY>
```

> 不要將 `ai/config/.env`、`config/ecg_integration.env` 或任何 API key 提交到 Git，也不要把 key 貼進 tutorial、截圖或 terminal log。

### 5.3 建立 Python 環境

`run.sh` 預期 `ai/.venv`、`ros/.venv` 已存在。ROS 環境需能讀取系統的 `rospy`：

```bash
cd ~/robot/code/tutorials/QT_ai_assistant

python3.11 -m venv ai/.venv
ai/.venv/bin/pip install -U pip
ai/.venv/bin/pip install -r ai/requirements.txt

python3.8 -m venv --system-site-packages ros/.venv
ros/.venv/bin/pip install -U pip
ros/.venv/bin/pip install -r ros/requirements.txt

python3 -m venv ecg/.venv
ecg/.venv/bin/pip install -U pip
ecg/.venv/bin/pip install -r ecg/requirements.txt
```

ROS requirements 內的 Torch／Torchaudio wheel 是 JetPack aarch64 與 Python 3.8 專用。若 QTrobot 映像不是此版本，不要強行安裝，應先確認 Python、JetPack 與 CUDA 版本。

如果系統沒有 `python3.11`，需使用機器上已安裝且能滿足 AI dependencies 的 Python，並相應重建 `ai/.venv`。

---

## 6. YuGuard Bluetooth iOS App

本專案的正式手機橋接程式是：

```text
/Users/zhangzhewei/Documents/qtrobot/bluetooth/ecg_blooth/
```

`bluetooth/ios-bridge` 與根目錄 Node bridge 是舊版。**同一時間只能啟動一個 bridge**，否則多個程式會同時寫入 Firebase 的 command 與 stream path。

### 6.1 使用 Xcode 安裝到 iPhone

1. 在 Mac 開啟 `bluetooth/ecg_blooth/ecg_blooth.xcodeproj`。
2. 等待 Swift Package Manager 下載 Firebase Database 與 Swifter dependencies。
3. 選擇 app target `ecg_blooth`。
4. 在 Signing & Capabilities 選擇自己的 Apple Development Team。
5. 確認 bundle identifier 可由該 Team 簽署；必要時改成自己的唯一 ID。
6. 以 USB 連接並解鎖 iPhone，在 iPhone 開啟 Developer Mode。
7. 將執行目標改成實體 iPhone，再按 Run。
8. 第一次開啟 App 時允許 Bluetooth 與 Local Network 權限。

專案中已有 `GoogleService-Info.plist`。如果要改用另一個 Firebase project，必須在 Firebase Console 登錄新的 iOS bundle ID，下載新的 plist 並替換；同時修改後端的 database URL 與 dashboard URL。

### 6.2 連接 YuGuard

1. 開啟 YuGuard 裝置並確認沒有被其他手機占用。
2. 開啟 iOS App；App 會自動開始掃描名稱包含 `YuGuard` 的 BLE 裝置。
3. 在 `Discovered Devices` 點選正確裝置。
4. 等待 App 完成 erase handshake、RSA handshake 與 ECG notification 訂閱。
5. 確認畫面狀態：
   - `BLUETOOTH READY`
   - `CLOUD ONLINE`
   - 電池電量不是 `--`
6. 貼好電極後按 `START`，或由 QTrobot／web dashboard 發出 `start` 指令。

App 的資料流程為：

```text
YuGuard BLE → iPhone 濾波 → Firebase devices/yuguard_01/stream
```

Firebase command path：

```text
devices/yuguard_01/command
```

### 6.3 單獨測試 ECG

先保持 iOS App 在前景，並確認 `BLUETOOTH READY`、`CLOUD ONLINE`，再到 QTrobot 執行：

```bash
cd ~/robot/code/tutorials/QT_ai_assistant
ECG_TEST_DURATION=15 ./scripts/test_ecg_standalone.sh
```

程式會依序送出 `reset`、清除舊 stream、送出 `start`，在確認穩定訊號、R peak 與 R-R interval 後才開始倒數。

成功後檢查：

```bash
cat runtime/ecg_test_latest.json
```

也可開啟 dashboard：

```text
https://ecg-monitor-bf64d.web.app
```

### 6.4 YuGuard 常見問題

| 現象 | 檢查方式 |
|---|---|
| 找不到裝置 | 確認 YuGuard 已開機、靠近 iPhone、未連到其他手機；按 `CLEAR BLE` 後重新 `SCAN` |
| 顯示 `SETTING UP` | BLE 已連線但 characteristic handshake 或 notify 尚未完成；看 Xcode console |
| `CLOUD OFFLINE` | 確認 iPhone 可上網、Firebase plist 與 Realtime Database 設定正確 |
| 有連線但沒有 ECG | 重新貼電極、檢查接觸品質，確認 App 為 `START/STREAMING ECG` |
| 重複或異常資料 | 關閉舊版 `ios-bridge` 與 Node bridge，只保留原生 iOS App |
| `signal_timeout` | 延長 `ECG_SIGNAL_WAIT_TIMEOUT_SECONDS`，並改善電極接觸及減少動作 |
| `stream_lost` | 檢查 iPhone App 是否進入背景、BLE 是否斷線、網路是否中斷 |

> ECG 結果只供訊號品質、心率及節律篩檢研究使用，不是醫療診斷。

---

## 7. Riva 語音設定與測試

### 7.1 語音設定位置

語音辨識參數：

```text
ros/config/riva_speech_recognition.yaml
```

目前重要設定：

```yaml
audio_topic: /qt_respeaker_app/channel0
default_language: zh-CN
vad_confidence_threshold: 0.85
consecutive_voice_chunks: 4
pre_roll_seconds: 1.8
min_voice_rms: 320
resume_cooldown: 0.4
```

QTrobot 語音輸出參數：

```text
ros/config/dispatcher.yaml
```

目前中文 mapping 為：

```text
App language: zh-TW
Riva ASR:     zh-CN
QTrobot TTS:  zh-MA
```

### 7.2 確認 ROS 與 ReSpeaker

```bash
source /opt/ros/noetic/setup.bash
source ~/catkin_ws/devel/setup.bash

rosnode list
rostopic list | grep qt_respeaker_app
rostopic hz /qt_respeaker_app/channel0
```

如果找不到 `/qt_respeaker_app/channel0`，啟動 ReSpeaker app：

```bash
roslaunch qt_respeaker_app qt_respeaker_app.launch
```

再用 `rostopic hz` 確認音訊持續發布。

### 7.3 啟動與確認 Riva Server

```bash
cd ~/robot/riva_quickstart_arm64_v2.14.0
bash ./riva_start.sh ./config.sh -s
```

確認容器與 port `50051`：

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}' | grep riva
ss -ltn | grep 50051
```

專案的 `scripts/run.sh` 也會啟動 Riva；不要在同一台機器重複啟動多套 Riva container。

### 7.4 測試 QTrobot 語音輸出 TTS

```bash
source /opt/ros/noetic/setup.bash
source ~/catkin_ws/devel/setup.bash

rosservice list | grep /qt_robot/speech
rosservice call /qt_robot/behavior/talkText \
  "message: '你好，我是 QTrobot，語音測試成功。'"
```

如果服務存在但沒有聲音，檢查音量：

```bash
rosservice call /qt_robot/setting/setVolume "volume: 100"
```

### 7.5 單獨測試 Riva ASR

停止完整 `run.sh` 後，執行測試，避免 port `5555` 被重複占用：

```bash
cd ~/robot/code/tutorials/QT_ai_assistant
source /opt/ros/noetic/setup.bash
source ~/catkin_ws/devel/setup.bash
source ros/.venv/bin/activate
./scripts/run_riva_tests.sh
```

依 terminal 提示對 QTrobot 說中文。成功時會顯示 timestamp、language 與辨識文字。按 `Ctrl+C` 停止測試。

### 7.6 語音調校

| 現象 | 建議調整 |
|---|---|
| 環境聲音常誤觸 | 提高 `vad_confidence_threshold` 或 `min_voice_rms` |
| 說話很小聲時無法觸發 | 降低 `min_voice_rms`，或檢查 ReSpeaker gain |
| 句首經常被吃掉 | 增加 `pre_roll_seconds` |
| 觸發太慢 | 小幅降低 `consecutive_voice_chunks` |
| 機器人聽到自己的 TTS | 增加 `resume_cooldown` 或 dispatcher 的 `mic_resume_delay` |
| 中文辨識成英文 | 確認 Riva 使用 `zh-CN`，dispatcher 預設語言為 `zh-TW` |

一次只修改一個參數，每次用相同距離與句子測試，較容易找出有效設定。

---

## 8. 啟動完整系統

### 8.1 啟動前檢查

```bash
cd ~/robot/code/tutorials/QT_ai_assistant
source /opt/ros/noetic/setup.bash
source ~/catkin_ws/devel/setup.bash

test -f ai/config/.env && echo "AI env: OK"
test -f config/ecg_integration.env && echo "ECG env: OK"
test -x ai/.venv/bin/python && echo "AI venv: OK"
test -x ros/.venv/bin/python && echo "ROS venv: OK"
test -x ecg/.venv/bin/python && echo "ECG venv: OK"

rosservice list | grep -E '/qt_robot/(speech|behavior|gesture)'
rostopic hz /qt_respeaker_app/channel0
```

iPhone App 也應顯示 `BLUETOOTH READY` 與 `CLOUD ONLINE`。

### 8.2 一鍵啟動

```bash
cd ~/robot/code/tutorials/QT_ai_assistant
source /opt/ros/noetic/setup.bash
source ~/catkin_ws/devel/setup.bash
./scripts/run.sh
```

正常啟動順序：

```text
[0/6] ECG integration readiness
[1/6] Riva Core Server
[2/6] ROS behavior dispatcher，port 5556
[3/6] Face memory（預設停用）
[4/6] Riva speech recognition
[5/6] AI brain，port 5555
```

看到以下訊息代表主要程序已就緒：

```text
All nodes have been successfully started in the background!
```

接著可測試：

1. 對 QTrobot 說：「你好，請介紹你自己。」
2. 確認 terminal 顯示收到的文字、AI 狀態與最後輸出。
3. 確認 QTrobot 能說話，並執行表情或手勢。
4. 對 QTrobot 說：「請幫我測量心電圖。」
5. 確認 dashboard 開啟、iOS App 開始 streaming，且量測完成後機器人能說明結果。

按 `Ctrl+C` 可讓 `run.sh` 清理 AI、Riva client、dispatcher、ECG session 與機器人輸出。

---

## 9. 驗收清單

### 網路與 SSH

- [ ] QTrobot Wi-Fi 介面由 DHCP 取得 IP。
- [ ] `ip route` 有正確的 default route。
- [ ] 可解析 DNS 並連到網際網路。
- [ ] Mac 可 SSH 到 QTrobot body computer。
- [ ] body computer 可免密 SSH 到 face Raspberry Pi。
- [ ] 未破壞 QTrobot body／face 之間的內部 Ethernet 固定網段。

### YuGuard

- [ ] App 安裝在實體 iPhone。
- [ ] Bluetooth 與 Local Network 權限已允許。
- [ ] App 顯示 `BLUETOOTH READY`。
- [ ] App 顯示 `CLOUD ONLINE`。
- [ ] dashboard 能看到即時 ECG。
- [ ] `test_ecg_standalone.sh` 可產生結果 JSON。

### 語音與完整系統

- [ ] `/qt_respeaker_app/channel0` 有持續音訊。
- [ ] Riva port `50051` 正常。
- [ ] 中文 ASR 能在 terminal 顯示辨識結果。
- [ ] QTrobot TTS 可正常說中文。
- [ ] AI port `5555` 與 dispatcher port `5556` 啟動成功。
- [ ] 語音可觸發一般問答及 ECG 量測。

---

## 10. 快速故障排除

### SSH 顯示 `Connection timed out`

```bash
ping <QTROBOT_BODY_IP>
ip route
sudo systemctl status ssh --no-pager
sudo ss -ltnp | grep ':22'
```

確認 IP 沒有因 DHCP 更新而改變，並檢查 AP 是否啟用了 client isolation。

### `REMOTE HOST IDENTIFICATION HAS CHANGED`

先在 QTrobot 本機重新確認 host fingerprint。如果只是同一 IP 改配到另一台已確認的主機，再在 Mac 移除舊紀錄：

```bash
ssh-keygen -R <QTROBOT_BODY_IP>
```

不要在未確認主機身份時直接忽略警告。

### Riva 無法啟動或 port 50051 不存在

```bash
docker ps -a | grep riva
docker logs --tail 100 <RIVA_CONTAINER_NAME>
df -h
free -h
```

檢查 Riva model 是否已部署、container 是否因 GPU／記憶體不足退出。

### `Address already in use`（5555／5556）

```bash
ss -ltnp | grep -E ':5555|:5556'
```

先回到原本執行 `run.sh` 的 terminal 按 `Ctrl+C`。不要同時啟動完整系統與 `run_riva_tests.sh`。

### ECG dashboard 沒有出現在 QTrobot 臉部

```bash
grep -E '^QT_FACE_' config/ecg_integration.env
ssh -o BatchMode=yes <FACE_USER>@<QT_FACE_IP> 'echo SSH_OK'
./scripts/open_ecg_kiosk.sh
```

若仍失敗，到 face Pi 檢查：

```bash
cat /tmp/qt_ecg_kiosk.log
command -v chromium-browser || command -v chromium
```

### 完整系統無回應

依序確認資料鏈，而不是一次重啟全部：

```text
ReSpeaker topic
  → Riva 50051
  → 辨識文字
  → AI 5555
  → dispatcher 5556
  → QTrobot speech/behavior ROS services
```

先找出第一個沒有輸出的節點，再查看該節點的 terminal log。
