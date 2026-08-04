# Node Watcher for Sanayi / 3X-UI

اسکریپت نظارت و بازیابی خودکار اینباندهای مشخص‌شده در پنل سنایی / 3X-UI.

## ویژگی‌ها

- فقط اینباندهایی که موقع نصب مشخص می‌کنی رو watch می‌کنه
- اگر اینباند پاک بشه، با تنظیمات ذخیره‌شده + UUID واقعی کلاینت‌ها دوباره می‌سازه
- جدول `client_inbounds` رو هم درست می‌کنه (Attached inbounds دیگه `---` نمی‌مونه)
- UUID رندوم نمی‌سازه؛ از جدول `clients` می‌خونه
- منوی مدیریت (`checker`) برای uninstall / update / edit / logs و ...

## نصب

```bash
git clone https://github.com/em2be/nodechecker.git
cd nodechecker
chmod +x install.sh checker.sh
sudo ./install.sh


# وضعیت
systemctl status node-watcher

# لاگ زنده
journalctl -u node-watcher -f

# ویرایش کانفیگ
nano /opt/node-watcher/config.json
systemctl restart node-watcher

# توقف / شروع
systemctl stop node-watcher
systemctl start node-watcher
