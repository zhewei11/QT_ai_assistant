# QTrobot AI Assistant

QTrobot AI Assistant is an advanced interactive brain designed specifically for the QT social robot. It combines traditional hardware control (ROS) with Large Language Models (LLMs) to achieve a **"Dual-Track" intelligent architecture featuring voice interaction, real-time web search, local medical knowledge base retrieval (RAG), and synchronous physical gestures.**

---

## Architecture and Core Features

This project utilizes a **Dual-Track Architecture**, completely decoupling "cognitive computing" from "hardware control" and using ZeroMQ for zero-latency communication:

![State Architecture](./picture/state.png)

1. **AI Brain Layer (Python 3.11 + LangGraph)**
   - **LangGraph Workflow**: Features an intelligent Router mechanism to accurately determine user intent and automatically assign tasks.
   - **RAG Medical Knowledge Base**: Combines **FAISS** with local `.txt` documents. Whenever a medical or disease-related question is asked, it rapidly retrieves precise information from the local `ai/document` folder.
   - **Tavily Global Web Search**: Automatically switches to real-time global web search when asked about weather, news, or other general knowledge.
   - **Synchronous Behavior Decoding**: Fuses responses with gestures (e.g., `<PHYSICAL_ACTION_REQUEST>`), extracts them independently, and dispatches them to the control layer.

2. **Hardware Control Layer (Python 3.7 + ROS 1)**
   - **NVIDIA Riva (Ear)**: Real-time Automatic Speech Recognition (ASR). Sensitively listens to environmental voice inputs and sends queries to the AI Brain (`Port 5555`).
   - **Behavior Dispatcher (Mouth & Limbs)**: Receives JSON payloads from the AI Brain (`Port 5556`) to trigger `/qt_robot/gesture/play`, audio recording, and facial expressions via ROS Services, allowing the robot to "speak and act simultaneously."

---

## Project Structure

```text
QT_ai_assistant/
│
├── ai/                      # AI Brain Layer (Run in isolated Python 3.11 virtual environment)
│   ├── .venv/               # Isolated Python execution environment
│   ├── document/            # Local disease/medical .txt files for RAG retrieval
│   ├── src/                 # Main LangGraph logic, Agent State definition, and RAG engine
│   └── requirements.txt     # Dependencies for AI (Langchain, FAISS, ZMQ, etc.)
│
├── ros/                     # Hardware Control Layer (Depends on ROS 1 and Python 3.7)
│   ├── src/
│   │   ├── riva_speech_recongnition.py # ASR Voice Receiver
│   │   └── ros_behavior_dispatcher.py  # Gesture and Speech Dispatcher
│
├── scripts/                 # Automated startup and testing scripts
│   ├── run.sh               # Main startup script, launches all nodes at once
│   ├── run_behavior_tests.sh
│   └── run_riva_tests.sh
│
├── picture/                 # Project images and diagrams
│   └── state.png
│
└── README.md
```

---

## Quick Start

We provide an extremely user-friendly integration script, `run.sh`, which automatically utilizes ZeroMQ's "asynchronous Port Polling mechanism" to ensure all services safely wake up in the correct order.

### Prerequisites
- Ensure **NVIDIA Riva Core Server** is downloaded and running (listening on `localhost:50051` by default).
- Create a `.venv` virtual environment in the `ai` directory and install dependencies using `pip install -r requirements.txt`.
- To use the Knowledge Base Search (RAG), place your plain text `.txt` files into the `ai/document` directory.

### Launching the Assistant
Navigate to the project directory and execute the startup script:
```bash
./scripts/run.sh
```

**Startup Sequence & Initialization Checks**:
1. **[0/4] Riva Core Server**: Checks if `50051` is correctly pushed to GPU and accepting connections.
2. **[1/4] ROS Dispatcher**: Launches the ROS behavior control node and listens on command port `5556`.
3. **[2/4] Riva ASR**: Starts the voice receiver, ready to broadcast speech.
4. **[3/4] AI Brain**: Mounts the main LangGraph model and FAISS RAG engine, binding to `5555` to receive voice inputs.

As long as the script runs without errors, it means these three independent cores are connected in the background. You can now speak loudly to the QTrobot!

---

## How Does the RAG Knowledge Base Work?

We have integrated the FAISS vector database into `rag_engine.py`.
This knowledge base supports **hot startup**, meaning every time `./scripts/run.sh` initializes, it automatically scans all `.txt` files in `ai/document/**/*.txt`, performing **text chunking, Embeddings**, and indexing them straight into memory.

- **No Manual Updates Needed**: Simply drop new disease information into the folder, and the robot will automatically know it on the next startup!
- **Coexists with Web Search**: Relies on the intelligent Router. Standard conversations and encyclopedic facts will smoothly process through the Tavily API, and only special medical domains will be directed to RAG.
