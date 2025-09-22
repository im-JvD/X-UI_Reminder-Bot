#!/bin/bash
set -e

APP_DIR="/root/reseller-report-bot"
SERVICE_FILE="/etc/systemd/system/reseller-report-bot.service"
PYTHON_BIN="$(which python3)"

echo "📦 نصب و راه‌اندازی X-UI Reseller Reminder Bot..."

# 1) ساخت venv
cd $APP_DIR
if [ ! -d "$APP_DIR/.venv" ]; then
    echo "🔧 ایجاد virtual environment..."
    $PYTHON_BIN -m venv .venv
fi

# 2) نصب پکیج‌ها
echo "📥 نصب پکیج‌های مورد نیاز..."
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
deactivate

# 3) ساخت فایل سرویس systemd
echo "⚙️ ساخت/بروزرسانی سرویس systemd..."
cat > $SERVICE_FILE <<EOF
[Unit]
Description=X-UI Reseller Reminder Bot
After=network.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python $APP_DIR/bot.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# 4) ری‌لود و ری‌استارت systemd
echo "🔄 ری‌استارت سرویس..."
systemctl daemon-reload
systemctl enable reseller-report-bot
systemctl restart reseller-report-bot

# 5) نمایش لاگ زنده
echo "📜 نمایش لاگ زنده..."
journalctl -u reseller-report-bot -n 50 -f
