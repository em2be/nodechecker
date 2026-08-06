# Node Watcher for MHSanaei / 3X-UI

اسکریپت نظارت و بازیابی خودکار اینباندهای مشخص‌شده در پنل سنایی / 3X-UI.

## ویژگی‌ها

- فقط اینباندهایی که موقع نصب (یا بعداً از منو) مشخص می‌کنی را watch می‌کند
- اگر اینباند پاک شود، با تنظیمات ذخیره‌شده + UUID واقعی کلاینت‌ها دوباره می‌سازد
- جدول `client_inbounds` را درست می‌کند (Attached inbounds دیگر `---` نمی‌ماند)
- UUID را از جدول `clients` می‌خواند (رندوم نمی‌سازد)
- کلاینت‌های دستی دیگر را پاک نمی‌کند
- فقط وقتی چیزی واقعاً کم باشد کار می‌کند (بدون حلقه بی‌نهایت)
- نصب و افزودن با **پیست JSON اکسپورت‌شده از پنل** (Ctrl+D)
- منوی مدیریت inboundها: View / Add / Edit / Remove / Export / Import

## پیش‌نیاز

فقط در صورت نبودن نصب می‌شود:

- `python3`
- `jq`

## نصب

```bash
git clone https://github.com/Gravithm/nodechecker.git
cd nodechecker
chmod +x install.sh checker.sh
sudo ./install.sh
```

# وضعیت
```bash
systemctl status node-watcher
```
# لاگ زنده
```bash
journalctl -u node-watcher -f
```
# ری‌استارت
```bash
systemctl restart node-watcher
```
# ویرایش کانفیگ (یا از منوی checker گزینه ۱۰)
```bash
nano /opt/node-watcher/config.json
systemctl restart node-watcher
```
