# Node Watcher for Sanayi / 3X-UI

اسکریپت نظارت و بازیابی خودکار اینباندهای مشخص‌شده در پنل سنایی / 3X-UI.

## ویژگی‌ها

- فقط اینباندهایی که موقع نصب مشخص می‌کنی رو watch می‌کنه
- JSON کامل اینباند رو می‌گیری → همه اطلاعات (port, clients, streamSettings, ...) خودکار استخراج می‌شه
- اگر اینباند پاک بشه، با تنظیمات ذخیره‌شده + UUID واقعی کلاینت‌ها دوباره می‌سازه
- جدول `client_inbounds` رو هم درست می‌کنه
- منوی مدیریت (`checker`)

## نصب

```bash
git clone https://github.com/em2be/nodechecker.git
cd nodechecker
chmod +x install.sh checker.sh
sudo ./install.sh
