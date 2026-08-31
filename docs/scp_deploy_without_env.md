# 用 scp 上傳整個專案但避開環境設定

這份文件用於從 Mac 將整個 `QT_ai_assistant` 專案上傳到 QTrobot，同時避開會破壞機器人現場設定的檔案。

會避開：

- `ai/config/.env`
- `config/ecg_integration.env`
- `.venv` / `ai/.venv` / `ecg/.venv` / `ros/.venv`
- `runtime/`
- `logs/`
- `__pycache__/`
- `.git/`
- 大型或平台不相容的本機資料夾，例如 `ecg/src/ybc/lib`

---

## 1. 在 Mac 建立上傳壓縮檔

```bash
cd /Users/zhangzhewei/Documents/qtrobot/tutorials/demos/qt_ai_assistant

COPYFILE_DISABLE=1 tar -czf /tmp/QT_ai_assistant_upload.tar.gz \
  --exclude='.git' \
  --exclude='.venv' \
  --exclude='*/.venv' \
  --exclude='*/__pycache__' \
  --exclude='runtime' \
  --exclude='logs' \
  --exclude='ai/.langgraph_api' \
  --exclude='ai/config/.env' \
  --exclude='config/ecg_integration.env' \
  --exclude='ecg/src/ybc/lib' \
  --exclude='ecg/src/SDM_DEMO_GUI' \
  --exclude='.DS_Store' \
  .
```

`COPYFILE_DISABLE=1` 會避免 macOS 將 extended attributes 打進 tar，機器人端解壓時就不會出現 `LIBARCHIVE.xattr...` 這類警告。

---

## 2. 使用 scp 上傳到機器人

請依實際機器人 IP 修改 `172.20.10.8`。

```bash
scp /tmp/QT_ai_assistant_upload.tar.gz \
qtrobot@172.20.10.8:/tmp/QT_ai_assistant_upload.tar.gz
```

---

## 3. 在機器人端解壓覆蓋專案

```bash
ssh qtrobot@172.20.10.8 '
mkdir -p ~/robot/code/tutorials/QT_ai_assistant &&
tar -xzf /tmp/QT_ai_assistant_upload.tar.gz \
-C ~/robot/code/tutorials/QT_ai_assistant &&
chmod +x ~/robot/code/tutorials/QT_ai_assistant/scripts/*.sh &&
rm /tmp/QT_ai_assistant_upload.tar.gz
'
```

---

## 4. 確認環境檔沒有被覆蓋

```bash
ssh qtrobot@172.20.10.8 '
ls -l ~/robot/code/tutorials/QT_ai_assistant/ai/config/.env
ls -l ~/robot/code/tutorials/QT_ai_assistant/config/ecg_integration.env
grep -E "ECG_YBC_MODEL_ENABLED|FACE_MEMORY_ENABLED|QT_FACE_HOST" \
~/robot/code/tutorials/QT_ai_assistant/config/ecg_integration.env
'
```

---

## 5. 啟動專案

```bash
ssh qtrobot@172.20.10.8
cd ~/robot/code/tutorials/QT_ai_assistant
./scripts/run.sh
```

---

## 6. 如果只要上傳單一檔案

例如只上傳 AI router：

```bash
scp /Users/zhangzhewei/Documents/qtrobot/tutorials/demos/qt_ai_assistant/ai/src/nodes.py \
qtrobot@172.20.10.8:~/robot/code/tutorials/QT_ai_assistant/ai/src/nodes.py
```

例如只上傳 ROS ASR：

```bash
scp /Users/zhangzhewei/Documents/qtrobot/tutorials/demos/qt_ai_assistant/ros/src/riva_speech_recongnition.py \
qtrobot@172.20.10.8:~/robot/code/tutorials/QT_ai_assistant/ros/src/riva_speech_recongnition.py
```

---

## 7. 注意事項

- 這個方法會覆蓋專案程式碼，但不覆蓋環境檔。
- 若新增了新的設定檔，確認是否需要加入 `--exclude`。
- 如果要同步刪除機器人上已不存在於本機的檔案，`scp` 不適合，請改用 `scripts/deploy_to_robot.sh` 的 `rsync` 流程。
- 如果機器人 IP 改變，先用 `ip -4 addr show wlan0` 或現場網路工具確認。
