# 🛡️ Node Inbound Watcher (3x-ui / Sanaei)

An automated background watcher service designed for **3x-ui (Sanaei)** node servers. 

If a Master server overwrites or deletes local tunnel inbounds during sync cycles, this service automatically detects the missing inbound and client, re-creates them via local API, and re-attaches target users within 60 seconds.

---

## ⚡ One-Line Installation

Run the following command on your **Node Server** via SSH:

```bash
git clone [https://github.com/em2be/nodechecker.git](https://github.com/em2be/nodechecker.git) node-watcher && cd node-watcher && chmod +x install.sh && ./install.sh
