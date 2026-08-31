# 衛教機器人海報素材

## 海報標題

**結合語音互動與心電量測的衛教機器人系統**

## 副標題

以 QTrobot 為平台，整合 AI 對話、ROS 動作表情、心電圖量測與醫療風險分流，建立可互動的健康衛教輔助系統。

## 一、介紹

本專案實作一套衛教機器人系統，讓使用者能以自然語音和 QTrobot 對話，並在需要時啟動心電圖量測。系統可根據使用者語句判斷一般聊天、健康衛教、ECG 量測、ECG 結果查詢與系統控制等意圖，再由 AI 層、ROS 層與 ECG 層分工完成互動。

系統定位為「健康衛教與篩檢輔助」，不是醫療診斷工具。對於個人症狀或高風險描述，例如胸悶、喘不過氣、昏厥等，系統會採取保守回應，提醒使用者尋求醫療協助；對於低風險的醫學科普問題，則提供較簡短、低隨機性的衛教說明。

## 二、方法

本系統採用分層式架構，將 AI 推理、語音辨識、機器人控制與 ECG 訊號處理拆開執行，降低單一流程阻塞造成的延遲。

### 系統流程

```text
使用者語音
  ↓
Riva STT 語音轉文字
  ↓
AI Router 判斷意圖
  ├─ 一般對話 / 衛教回答
  ├─ ECG 量測指令
  ├─ ECG 結果查詢
  └─ 系統控制：語言、音量、暫停回答等
  ↓
ROS Dispatcher
  ├─ TTS 語音輸出
  ├─ 表情顯示
  ├─ 手勢動作
  └─ ECG dashboard 開啟 / 關閉
```

### 核心模組

| 模組 | 功能 |
|---|---|
| AI 對話層 | 使用 LangGraph 進行意圖路由，處理對話、衛教、ECG 查詢與系統控制 |
| 醫療安全層 | 依問題風險分流，高風險症狀採保守回應，避免幻覺式醫療建議 |
| ROS 控制層 | 控制 QTrobot 的語音、表情與手勢，並支援平行輸出 |
| 語音辨識層 | 使用 NVIDIA Riva 進行 STT，並支援中文與英文語音輸入 |
| ECG 量測層 | 透過藍牙資料流取得 ECG，偵測有效 R 波後開始正式量測 |
| ECG 顯示層 | 將 ECG dashboard 投影到 QTrobot 臉部螢幕，顯示心率、HRV 與波形 |
| YBC 模型層 | 對 ECG beat 進行 N/S/V/F/Q 類別篩檢，提供非診斷式異常搏動提示 |

### ECG 量測設計

1. 使用者說出「幫我測量心電圖」後，系統觸發 `measureECG`。
2. 機器人開啟臉部 ECG dashboard。
3. 系統等待藍牙裝置連線與有效 ECG 訊號。
4. 偵測到足夠的 R 波與 RR interval 後，才開始 60 秒倒數。
5. 量測完成後輸出 BPM、RMSSD、pNN50、R peak、訊號品質與節律篩檢結果。
6. 使用者詢問「剛剛結果是多少」時，AI 直接讀取最新 ECG 結果，不再交給一般 LLM 隨機回答。

## 三、結果

目前 `demos/qt_ai_assistant` 已完成完整的實機互動流程：

- 可由中文語音觸發 ECG 量測。
- ECG 量測不會在程式啟動時自動開始，避免長時間運行時誤測。
- 量測期間可暫停收音，降低誤觸發與環境音干擾。
- 量測結果可寫入本地 runtime 檔案，並由 AI 在後續對話中讀取。
- ECG 結果查詢採 deterministic route，實測可在毫秒等級取得回應。
- QTrobot 可同步輸出語音、表情與手勢，提高互動自然度。
- 已加入可用手勢清單，避免 AI 產生無法執行的動作。
- Terminal debug 已整理為語音文字、系統狀態、延遲、最後輸出、表情與動作，方便現場測試。
- YBC 模型可輸出 beat-level 分類結果，例如正常搏動 N、上心室異常 S、心室異常 V、融合搏動 F 與未知 Q。

### ECG 回答範例

```text
剛剛心電篩檢心率為 70.1 BPM，RMSSD 為 57.0 毫秒，pNN50 為 43.7%。
節律篩檢顯示不規則心律型態。YBC 模型未偵測到明顯異常搏動。
這是篩檢結果，不是診斷；若有胸悶、喘或不舒服，建議儘快尋求醫療協助。
```

### 醫療安全回應範例

```text
你提到喘和心臟不舒服，這可能需要立即注意。
我不能替你診斷，建議先停止活動、坐下休息，並盡快聯絡醫療人員；
若症狀明顯或持續，請立即就醫或撥打緊急電話。
```

## 四、結論

本專案建立了一個可持續運行的衛教機器人原型，整合 AI 對話、機器人多模態輸出與 ECG 量測。透過 deterministic routing 與醫療風險分流，系統能在降低 LLM 隨機性與幻覺風險的同時，保留自然語音互動的彈性。

未來可進一步強化外接麥克風抗噪、人臉記憶穩定性、醫療知識庫覆蓋率與 ECG 模型臨床驗證，使系統更適合教學展示、健康衛教與長時間實機測試。

## 建議海報版面

### 左上：系統目標

放置 QTrobot 與使用者互動主視覺，搭配一句話：

> 讓衛教機器人能聽懂問題、做出回應，並在需要時完成 ECG 篩檢。

### 右上：方法流程圖

使用「語音 → AI Router → ROS Dispatcher → TTS/表情/動作/ECG」流程圖。

### 左下：ECG 功能展示

放 ECG dashboard 截圖，標示：

- 60 秒量測
- 心率 BPM
- HRV 指標 RMSSD / pNN50
- R 波偵測
- YBC beat-level 篩檢

### 右下：結果與限制

使用三個重點數字或標籤：

- ECG 結果查詢：deterministic route
- 回答安全：高風險症狀保守回應
- 多模態互動：語音 + 表情 + 手勢

再加一句限制：

> 本系統提供衛教與篩檢輔助，不提供診斷。

## 圖像素材建議

### 主視覺生成提示

```text
A clean academic poster hero image showing a friendly small humanoid education robot interacting with a student, a glowing ECG waveform dashboard on the robot face screen, speech bubbles, and subtle medical education icons. Modern laboratory setting, teal and white color palette, professional research poster style, high clarity, no text, no logo, landscape composition.
```

### 流程圖元素

可使用 6 個圖示：

- 麥克風：語音輸入
- 文字泡泡：STT
- 腦部 / 節點圖：AI Router
- 齒輪：ROS Dispatcher
- 機器人臉：TTS、表情、動作
- 心電波：ECG 量測

### ECG dashboard 圖說

```text
圖 1. ECG dashboard 於 QTrobot 臉部螢幕顯示，可即時呈現心率、HRV 指標與心電波形。
```

### 系統架構圖說

```text
圖 2. 系統以 AI、ROS 與 ECG 三層架構實作，透過 ZeroMQ 與 ROS service 串接語音、動作與生理訊號流程。
```

### 實機互動圖說

```text
圖 3. 使用者可直接以中文語音要求機器人進行心電圖量測，並於量測後詢問結果。
```

## 一句話摘要

**本系統讓 QTrobot 從單純對話機器人，擴展為可進行語音衛教、動作互動與 ECG 篩檢輔助的健康教育平台。**
