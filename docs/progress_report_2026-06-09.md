# QT AI Assistant ECG Integration Progress Report

日期：2026-06-09

## 一、目前完成成果

### 1. ECG 量測流程已整合到 AI 對話系統

目前系統已改為「對話觸發 ECG」，不再於程式啟動時自動量測。當使用者說出「幫我測量心電圖」或「幫我連測 ECG」等指令時，AI 會透過 deterministic routing 直接觸發 `measureECG`，避免交給 LLM 隨機判斷。

已支援繁體與簡體中文 ASR 輸入，例如：

- `幫我測量心電圖`
- `帮我测量心电图`
- `我要做心電圖`
- `請幫我量心电图`

實測結果顯示 ECG 量測可以正常啟動，並且會在偵測到有效 R 波後才開始正式倒數 60 秒。

### 2. ECG 資料讀取與 AI 回答已可運作

量測完成後，系統會將結果寫入：

```text
runtime/ecg_latest.json
```

實測資料範例：

```text
status = complete
heart rate = 70.1 BPM
RMSSD = 57.0 ms
pNN50 = 43.7%
R peak count = 73
signal quality = good
rhythm label = irregular_rhythm_pattern
irregular rhythm screening score = 0.624
disease_probabilities = {}
```

AI 目前可以透過 `ecg_result` route 直接讀取 ECG 結果回答，不再走醫療 RAG，也不會被 medical guard 誤擋。

實測 latency：

```text
route = ecg_result
Graph = 7.5 ms
AI total = 9.0 ms
router = keyword:ecg_result
```

這表示「詢問 ECG 結果」已經從原本約 6 至 9 秒的 RAG 流程，降低到約 10 ms 等級的 deterministic response。

### 3. ECG 回答安全性已調整

目前系統不會將 `screening_scores` 說成疾病機率。AI 會使用較保守的說法：

```text
不規則心律篩檢分數
```

而不是：

```text
心律不整機率
```

原因是目前演算法是根據 RR interval 變異、RMSSD、pNN50、entropy、turning point ratio 等特徵產生的啟發式篩檢分數，尚未經過臨床資料集訓練、校準與外部驗證，因此不能宣稱為正式疾病機率或診斷結果。

目前 AI 回答格式已精簡為：

```text
剛剛心電篩檢心率 70.1 BPM，節律顯示不規則心律型態，不規則篩檢分數 0.624。目前沒有疾病機率模型輸出。這只是篩檢結果，不是診斷。
```

### 4. QTrobot 臉部螢幕顯示 ECG 網頁已可遠端控制

已確認可由主控端 SSH 到臉部 Raspberry Pi：

```bash
ssh developer@192.168.100.1
```

並可透過 Chromium kiosk 顯示 ECG dashboard：

```bash
DISPLAY=:0 chromium-browser --disable-gpu --no-sandbox --kiosk --incognito "https://ecg-monitor-bf64d.web.app"
```

新增腳本：

```text
scripts/open_ecg_kiosk.sh
scripts/close_ecg_kiosk.sh
```

`measureECG` 觸發時會自動開啟 ECG dashboard，量測結束後會自動關閉。

### 5. 量測期間麥克風暫停機制已加入

目前 dispatcher 已加入 mic pause reason 管理：

- TTS 說話時暫停麥克風，避免自言自語與 TTS echo。
- ECG 量測期間暫停麥克風，避免量測時誤收音。
- 若 TTS 與 ECG 同時需要暫停，會以 reason set 管理，不會因其中一個結束而誤恢復。

相關 log 範例：

```text
[Mic] paused=True reasons=['ecg']
[ECG measurement] Microphone paused during ECG measurement.
[ECG measurement] process finished return_code=0
[Mic] paused=False reasons=['none']
[ECG measurement] Microphone resumed after ECG measurement.
```

### 6. AI 終端輸出已整理

目前 terminal 輸出已改為更適合 debug 與展示的格式，只保留：

- 收到的語音文字
- 當前狀態
- latency
- AI route 與細分時間
- 最後輸出文字
- 表情
- 動作
- 是否可以繼續對話

這使現場測試時較容易判斷問題發生在 ASR、AI graph、dispatcher、TTS、動作或 ECG pipeline。

## 二、目前已驗證項目

### 1. ECG standalone 測試成功

已可單獨執行 ECG 測試腳本，並取得 BPM、HRV 與心律篩檢結果。

已驗證：

- Firebase stream 可連線。
- 有效 R 波偵測後才開始倒數。
- 量測完成後會輸出 `runtime/ecg_latest.json`。
- `disease_probabilities` 目前為空，表示尚無上游疾病機率模型輸出。

### 2. AI 觸發 ECG 成功

中文語音指令：

```text
帮我测量心电图
```

已可正確進入：

```text
route = system_control
action = measureECG
```

### 3. AI 查詢 ECG 結果成功

中文語音：

```text
说明一下刚才的心电图，结果。
```

已可正確進入：

```text
route = ecg_result
```

並正確回答 BPM、節律型態、不規則篩檢分數與非診斷提醒。

### 4. QTrobot TTS / gesture / expression 平行執行已確認

dispatcher 已改為 multimodal dispatch，表情、動作與說話不再完全 serial blocking。已驗證語音可播放，動作與表情也能透過 action payload 發送。

### 5. 中文 TTS / ASR 語言 mapping 已修正

目前 app/AI 層可使用 `zh-TW` 表示中文輸出，但底層 QTrobot TTS 會轉為：

```text
TTS = zh-MA
ASR = zh-CN
```

避免使用錯誤的 `zh-TW` 導致 TTS 不正常。

## 三、尚未完成或仍需處理的問題

### 1. 疾病機率模型尚未完成

目前 ECG 演算法只能輸出：

- 不規則心律篩檢分數
- possible AF pattern 篩檢分數
- premature beat pattern 篩檢分數

但這些不是疾病機率。

尚未完成：

- 使用有標註 ECG 資料集訓練分類模型。
- 對模型輸出進行 probability calibration。
- 驗證 sensitivity、specificity、AUC、calibration curve。
- 將經驗證的疾病機率寫入 `disease_probabilities`。

因此目前 AI 只能說「篩檢分數」，不能說「心律不整機率」或「疾病機率」。

### 2. 人臉記憶尚未完全驗證

已實作 `face_identity_memory.py`，設計上可記憶最多 4 個 person slot，並將 ECG 結果綁定到目前看到的人臉。

但實測時 `/qt_nuitrack_app/faces` topic 曾出現 publisher 存在但沒有新 message：

```text
rostopic hz /qt_nuitrack_app/faces
no new messages
```

目前 camera image 可顯示，但 Nuitrack face topic 尚未穩定輸出 face message。

尚未完成：

- 確認 Nuitrack face detection 是否需要額外啟用參數。
- 確認人臉需位於畫面中心、距離、光線與角度條件。
- 確認 `/qt_nuitrack_app/faces` message 是否正常 publish。
- 完成「不同使用者對應不同 ECG 結果」的實機驗證。

### 3. ECG dashboard 網頁部署狀態需確認

本地前端已修改 ECG dashboard 顯示邏輯，但 Firebase hosting 上曾看到舊頁面。

尚未完成：

- 確認 `https://ecg-monitor-bf64d.web.app/` 是否已部署最新版本。
- 確認手機端、Firebase stream、web dashboard 顯示欄位一致。
- 確認 dashboard 狀態能正確顯示 waiting device、waiting signal、measuring、complete、stream lost。

### 4. ASR 收音品質仍需實機微調

目前已改善：

- mic pause 避免 TTS echo。
- 短句 allowlist，避免「你好」被當作太短而忽略。
- 中文 mapping 使用 Riva `zh-CN`。

但開放空間仍可能出現：

- 句首被吃掉。
- 收到旁人聲音。
- 中文辨識簡繁與詞彙差異。
- 長時間接收 latency 偏高。

尚未完成：

- 根據現場環境微調 VAD threshold、silence duration、pre-roll、resume cooldown。
- 評估是否加入 speaker direction / wake word / push-to-talk。
- 建立固定測試句集，量化 ASR 成功率。

### 5. AI 醫療回答仍需更多驗證

目前已完成：

- 高風險症狀保守回答。
- 醫學科普走 RAG 或低風險 fallback。
- ECG 結果直接讀取 measurement，不進 RAG guard。
- 不把篩檢分數說成疾病機率。

尚需驗證：

- 不同醫療問題是否能正確分流到 high risk、personal medical、education。
- RAG evidence gate 是否過度保守或過度放行。
- 中文 ASR 簡體輸入是否都能正確判斷 intent。

### 6. 部署流程仍需標準化

目前已新增 deployment script，但實際上仍常使用 `scp` 手動上傳單一檔案。

尚未完成：

- 建立固定部署流程。
- 確認不會覆蓋 `.venv`、runtime、env config。
- 建立機器人端一鍵 restart 與 health check。
- 將測試順序文件化。

## 四、目前系統執行流程

目前建議流程如下：

1. 啟動主系統：

```bash
cd ~/robot/code/tutorials/QT_ai_assistant
./scripts/run.sh
```

2. 使用者說：

```text
幫我測量心電圖
```

3. AI router 進入：

```text
system_control -> measureECG
```

4. ROS dispatcher：

- 開啟 ECG dashboard 到 QTrobot 臉部螢幕。
- 暫停麥克風。
- 啟動 ECG session。

5. ECG session：

- 等待手機與 BLE ECG stream。
- 等待有效 R 波。
- 有效心跳確認後才開始 60 秒量測。
- 量測完成後寫入 `runtime/ecg_latest.json`。

6. Dispatcher：

- 恢復麥克風。
- 關閉 ECG dashboard。
- terminal 提示可以繼續對話。

7. 使用者問：

```text
剛剛心電圖結果是多少？
```

8. AI router 進入：

```text
ecg_result
```

9. AI 直接讀取 ECG result 並回答精簡結果。

## 五、下一步建議

### 短期優先

1. 完成人臉 topic publish 問題排查，確認 face memory 是否能穩定綁定 ECG 結果。
2. 確認 ECG dashboard 最新前端是否已成功部署到 Firebase hosting。
3. 在實機上跑完整 demo 流程 5 至 10 次，記錄成功率與 latency。
4. 微調 ASR 收音參數，降低句首遺失與旁人聲音干擾。
5. 整理固定測試指令與預期 route。

### 中期目標

1. 若需要疾病機率，建立真正的 ECG 分類模型與校準流程。
2. 建立 deployment checklist，降低每次上傳漏檔風險。
3. 將 latency log 匯出成 CSV 或 JSON，方便後續分析瓶頸。
4. 對醫療問題建立測試集，驗證安全回答與 RAG 分流。

## 六、目前結論

目前 ECG 與 AI 對話整合的核心流程已經可運作：

- 可以用語音觸發 ECG 量測。
- 可以等待有效心跳後才開始 60 秒。
- 可以將 ECG 網頁顯示在 QTrobot 臉部螢幕。
- 量測期間可以暫停麥克風。
- 量測完成後可以關閉網頁。
- AI 可以快速讀取並精簡回答 ECG 結果。
- 回答中已避免把篩檢分數誤稱為疾病機率或診斷。

目前主要未完成項目集中在：人臉記憶實機驗證、前端部署確認、ASR 現場穩定性調參，以及真正疾病機率模型的建立與驗證。
