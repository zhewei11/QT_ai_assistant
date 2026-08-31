# QTrobot eth0 改成 DHCP 操作 README

這份文件用於把 QTrobot/Linux 裝置的 `eth0` 從固定 IP 設定改成 DHCP 自動取得 IP。

> 注意：如果你目前是透過 `eth0` SSH 連線，改成 DHCP 後 SSH 可能會中斷。建議先確認你還有另一條可連線路徑，例如 Wi-Fi、螢幕鍵盤，或 QTrobot 內部另一台樹莓派。

---

## 1. 先確認 eth0 目前狀態

```bash
ip -4 addr show eth0
ip route
networkctl status eth0 --no-pager
```

常見固定 IP 設定會看到類似：

```text
Address: 192.168.100.1
Network File: /etc/systemd/network/04-wired.network
```

---

## 2. 備份原本 eth0 設定

```bash
sudo cp /etc/systemd/network/04-wired.network \
/etc/systemd/network/04-wired.network.backup
```

如果實際檔名不是 `04-wired.network`，請用 `networkctl status eth0 --no-pager` 顯示的 `Network File` 路徑替換。

---

## 3. 將 eth0 改成 DHCP

```bash
sudo tee /etc/systemd/network/04-wired.network >/dev/null <<'EOF'
[Match]
Name=eth0

[Network]
DHCP=yes
IPv6AcceptRA=yes
EOF
```

---

## 4. 重啟 systemd-networkd

```bash
sudo systemctl restart systemd-networkd.service
sleep 10
```

若系統支援，也可以使用：

```bash
sudo networkctl renew eth0
```

但部分 QTrobot/Raspberry Pi 系統版本沒有 `renew` 或 `reconfigure`，這時使用 `systemctl restart systemd-networkd.service` 即可。

---

## 5. 驗證 DHCP 是否成功

```bash
ip -4 addr show eth0
ip route
ping -c 3 8.8.8.8
ping -c 3 google.com
```

成功時應看到：

```text
inet <DHCP分配的IP>/<prefix>
default via <DHCP閘道IP> dev eth0
```

若只有 IP 但沒有 default route，代表 DHCP 有拿到位址，但閘道沒有正確分配。

---

## 6. 回復原本固定 IP 設定

如果改完後網路不正常，使用備份還原：

```bash
sudo cp /etc/systemd/network/04-wired.network.backup \
/etc/systemd/network/04-wired.network

sudo systemctl restart systemd-networkd.service
sleep 10
```

再檢查：

```bash
ip -4 addr show eth0
ip route
```

---

## 7. NetworkManager 系統的替代指令

如果你的系統不是 `systemd-networkd` 管理 `eth0`，而是 NetworkManager，使用：

```bash
nmcli con show
nmcli dev status
```

找到 eth0 對應的連線名稱後，例如 `Wired connection 1`：

```bash
sudo nmcli con mod "Wired connection 1" ipv4.method auto
sudo nmcli con mod "Wired connection 1" ipv4.addresses ""
sudo nmcli con mod "Wired connection 1" ipv4.gateway ""
sudo nmcli con mod "Wired connection 1" ipv4.dns ""
sudo nmcli con down "Wired connection 1"
sudo nmcli con up "Wired connection 1"
```

驗證：

```bash
ip -4 addr show eth0
ip route
```

---

## 8. QTrobot 內部網路提醒

QTrobot 常見內部網段：

```text
QTRD / face Raspberry Pi: 192.168.100.1
QTPC / body computer:    192.168.100.2
```

如果 `eth0` 用於這條內部連線，將它改成 DHCP 可能會讓兩台機器失去固定互連能力。只有在你確定 `eth0` 是接到外部 DHCP 網路，或你有其他方式恢復設定時，才建議執行。

