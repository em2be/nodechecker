echo ""
echo "🔄 [1/3] Checking System Package Status..."

# بررسی اینکه آیا در ۲۴ ساعت گذشته (۱۴۴۰ دقیقه) آپدیت انجام شده یا نه
if [ -f /var/lib/apt/periodic/update-success-stamp ] && [ $(find /var/lib/apt/periodic/update-success-stamp -mmin -1440 2>/dev/null) ]; then
    echo "⚡ Package list is already up-to-date. Skipping apt-get update..."
else
    echo "🌐 Updating package index..."
    DEBIAN_FRONTEND=noninteractive apt-get update -y -o Dpkg::Use-PTY=0
    # ثبت زمان آخرین آپدیت موفق
    mkdir -p /var/lib/apt/periodic
    touch /var/lib/apt/periodic/update-success-stamp
fi
