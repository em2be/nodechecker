# Node Watcher for Sanayi / 3X-UI

اسکریپت نظارت و بازیابی خودکار اینباندهای مشخص‌شده در پنل سنایی / 3X-UI.

## ویژگی‌ها

- فقط اینباندهایی که موقع نصب مشخص می‌کنی را watch می‌کند
- اگر اینباند پاک شود، با تنظیمات ذخیره‌شده + UUID واقعی کلاینت‌ها دوباره می‌سازد
- جدول `client_inbounds` را هم درست می‌کند (Attached inbounds دیگر `---` نمی‌ماند)
- UUID رندوم نمی‌سازد؛ از جدول `clients` می‌خواند
- کلاینت‌های دستی دیگر را پاک نمی‌کند
- فقط وقتی چیزی واقعاً کم باشد کار می‌کند (بدون حلقه بی‌نهایت)

## پیش‌نیاز

فقط در صورت نبودن نصب می‌شود:
- python3
- jq

## نصب

```bash
git clone https://github.com/em2be/nodechecker.git
cd nodechecker
chmod +x install.sh checker.sh
sudo ./install.sh
