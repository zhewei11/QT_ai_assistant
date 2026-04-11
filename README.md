# QTrobot AI Assistant

QTrobot AI Assistant 是一個專為 QT 社交機器人設計的高階互動大腦。它將傳統的硬體控制（ROS）與最先進的在地化大語言模型（LLM）結合，實現了**語音互動、實時網路搜尋、本地疾病知識庫檢索 (RAG) 以及同步實體肢體動作**的「雙軌制」智慧架構。

---

## 🌟 核心架構與特色 (Core Features)

本專案採用**雙軌制架構**，將「認知運算」與「硬體控制」徹底解耦，以 ZeroMQ 達成無延遲通訊：

1. **AI 大腦層 (Python 3.11 + LangGraph)**
   - **LangGraph 工作流**：具備智慧路由機制，能精準判斷使用者意圖並自動分配任務。
   - **RAG 醫療知識庫**：結合 **FAISS** 與本地端 `.txt` 文件，無論何時詢問醫療、疾病相關建議，皆能從本地資料夾 (`ai/document`) 即時檢索出精確資訊。
   - **Tavily 全球網路搜尋**：如果詢問天氣、新聞或其他常識，將自動切換為全球網路即時檢索模式。
   - **同步行為解碼**：將回應與動作（如：`<PHYSICAL_ACTION_REQUEST>`）融合並獨立抽離，傳送到控制層。

2. **硬體控制層 (Python 3.7 + ROS 1)**
   - **NVIDIA Riva (Ear)**：即時語音轉文字 (ASR)，靈敏監聽環境語音，並向 AI 大腦發送提問 (`Port 5555`)。
   - **Behavior Dispatcher (Mouth & Limbs)**：接收 AI 傳回的 JSON 封包 (`Port 5556`)，觸發 `/qt_robot/gesture/play`、錄音、表情等 ROS Server 機制，讓機器人「邊講話邊做動作」。

---

## 📂 專案目錄結構 (Project Structure)

```text
QT_ai_assistant/
│
├── ai/                      # AI 大腦層 (建議在獨立的虛擬環境 Python 3.11 中執行)
│   ├── .venv/               # 隔離的 Python 執行環境
│   ├── document/            # 存放 RAG 檢索用的本地疾病/醫療 .txt 文件
│   ├── src/                 # LangGraph 主程式、Agent State 定義與 RAG 引擎
│   └── requirements.txt     # AI 需要的相關套件清單 (Langchain, FAISS, ZMQ 等)
│
├── ros/                     # 硬體控制層 (依賴 ROS 1 與原本的 Python 3.7)
│   ├── src/
│   │   ├── riva_speech_recongnition.py # ASR 語音收音端
│   │   └── ros_behavior_dispatcher.py  # 肢體與語音發送端
│
├── scripts/                 # 懶人啟動與測試腳本
│   ├── run.sh               # 🚀 主啟動腳本，一鍵啟動所有節點
│   ├── run_behavior_tests.sh
│   └── run_riva_tests.sh
│
└── README.md
```

---

## 🚀 快速啟動 (Quick Start)

我們提供了一個極度友善的整合腳本 `run.sh`，會自動利用 ZeroMQ 的「非同步 Port Polling 機制」保障所有服務按順序成功喚醒。

### 1️⃣ 前置準備
- 確保您已下載並啟動了 **NVIDIA Riva Core Server**（預設監聽在 `localhost:50051`）。
- 進入 `ai` 目錄建立 `.venv` 虛擬環境，並透過 `pip install -r requirements.txt` 安裝相關套件。
- 如需使用知識庫搜尋 (RAG)，請將相關的純文字 `.txt` 文件放置於 `ai/document` 目錄中。

### 2️⃣ 一鍵啟動
將目錄切換至本專案下，執行我們的啟動腳本：
```bash
./scripts/run.sh
```

**運行順序與檢測流程**：
1. **[0/4] Riva Core Server**：檢查本機 `50051` 是否已正確推入 GPU 並接受連線。
2. **[1/4] ROS Dispatcher**：啟動 ROS 行為控制節點，並監聽指令埠 `5556`。
3. **[2/4] Riva ASR**：啟動語音接收端，準備向外發送語音。
4. **[3/4] AI Brain**：掛載主 LangGraph 模型與 FAISS RAG 引擎，綁定 `5555` 收取語音。

只要腳本沒有報錯卡住，就代表這三個獨立的靈魂已經在背景連上線，您可以大聲向 QTrobot 說話了！

---

## ⚙️ RAG 知識庫如何運作？

我們將最尖端的 FAISS 向量資料庫整合至 `rag_engine.py`。
此知識庫能**熱啟動**，意即每次 `./scripts/run.sh` 啟動時，它都會自動去掃描 `ai/document/**/*.txt` 中的所有文字檔，為它們進行**文本切割、嵌入 (Embeddings)** 並索引到記憶體中。

- **不需手動更新**：有新疾病的資料只要丟進資料夾，下次啟動就會自動會了！
- **不排擠網路搜尋**：依賴強大的智慧 Router 判斷。一般聊天與百科事實依然能暢通無阻地透過 Tavily API 完成；特殊醫療領域才會導引至 RAG。
