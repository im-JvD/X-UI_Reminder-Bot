#!/bin/bash

INSTALL_DIR=/root/reseller-report-bot
SERVICE_FILE=/etc/systemd/system/reseller-report-bot.service
REPO="https://github.com/im-JvD/X-UI_Reminder-Bot.git"

# رنگ‌ها
GREEN='\033[1;92m'
YELLOW='\033[1;93m'
BLUE='\033[1;94m'
RED='\033[1;91m'
NC='\033[0m'

pause() {
  echo -e "\n${YELLOW}Press Enter to return to main menu...${NC}"
  read
}

show_menu() {
  clear
  echo -e "${BLUE}========================================${NC}"
  echo -e "${GREEN}   3X-UI Reseller Report Bot Manager    ${NC}"
  echo -e "${BLUE}========================================${NC}"
  echo -e "${GREEN}1)${NC} Install Bot"
  echo -e "${GREEN}2)${NC} Start/Restart Bot"
  echo -e "${GREEN}3)${NC} Update Bot (Reinstall source, keep .env & DB)"
  echo -e "${RED}4) Remove Bot (full wipe)${NC}"
  echo -e "${BLUE}5) Show Last 100 Log Lines${NC}"
  echo -e "${BLUE}6) Show Live Logs${NC}"
  echo -e "${YELLOW}0) Exit${NC}"
  echo -e "${BLUE}========================================${NC}"
}

ensure_service() {
  sudo bash -c "cat > $SERVICE_FILE" <<EOF
[Unit]
Description=3X-UI Reseller Report Bot
After=network-online.target

[Service]
User=$USER
WorkingDirectory=$INSTALL_DIR
Environment="PYTHONUNBUFFERED=1"
ExecStart=$INSTALL_DIR/.venv/bin/python $INSTALL_DIR/bot.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  sudo systemctl daemon-reload
}

install_bot() {
  echo -e "${GREEN}🔧 Installing bot...${NC}"
  sudo systemctl stop reseller-report-bot 2>/dev/null || true
  sudo systemctl disable reseller-report-bot 2>/dev/null || true
  rm -rf "$INSTALL_DIR"

  git clone "$REPO" "$INSTALL_DIR"
  cd "$INSTALL_DIR"

  echo -e "${BLUE}📦 Creating Python virtual environment${NC}"
  python3 -m venv .venv
  source .venv/bin/activate
  pip install --upgrade pip
  pip install -r requirements.txt

  if [ ! -f ".env" ]; then
    echo -e "${YELLOW}🔑 Please configure your bot (.env will be created)${NC}"
    cp .env.example .env
    nano .env
  fi

  ensure_service
  sudo systemctl enable reseller-report-bot
  sudo systemctl restart reseller-report-bot
  echo -e "${GREEN}✅ Bot installed and started successfully!${NC}"
  pause
}

restart_bot() {
  echo -e "${BLUE}🔄 Restarting bot service...${NC}"
  sudo systemctl restart reseller-report-bot
  sleep 1
  echo -e "${GREEN}✅ Bot restarted.${NC}"
  pause
}

update_bot() {
  echo -e "${YELLOW}⬆️ Updating bot source...${NC}"
  sudo systemctl stop reseller-report-bot 2>/dev/null || true

  if [ ! -d "$INSTALL_DIR" ]; then
    echo -e "${RED}❌ Bot not installed.${NC}"
    pause
    return
  fi

  cd "$INSTALL_DIR"
  # پشتیبان‌گیری از env و DB
  cp .env /tmp/.env.backup 2>/dev/null || true
  cp *.db /tmp/ 2>/dev/null || true

  # آپدیت کامل از گیت‌هاب
  git fetch --all
  git reset --hard origin/main

  # بازگردانی env و DB
  mv /tmp/.env.backup .env 2>/dev/null || true
  mv /tmp/*.db . 2>/dev/null || true

  source .venv/bin/activate || true
  pip install --upgrade pip
  pip install -r requirements.txt

  ensure_service
  sudo systemctl restart reseller-report-bot
  echo -e "${GREEN}✅ Update completed and service restarted.${NC}"
  pause
}

remove_bot() {
  echo -e "${RED}🗑 Removing bot...${NC}"
  sudo systemctl stop reseller-report-bot 2>/dev/null || true
  sudo systemctl disable reseller-report-bot 2>/dev/null || true
  sudo rm -f $SERVICE_FILE
  sudo systemctl daemon-reload
  rm -rf $INSTALL_DIR
  echo -e "${GREEN}✅ Bot removed completely!${NC}"
  pause
}

show_logs() {
  echo -e "${BLUE}📜 Showing last 100 lines of logs:${NC}"
  sudo journalctl -u reseller-report-bot -n 100 --no-pager
  pause
}

show_logs_live() {
  echo -e "${YELLOW}📡 Showing live logs (Press Ctrl+C to exit)${NC}"
  sudo journalctl -u reseller-report-bot -f
}

# --- MAIN MENU LOOP ---
while true; do
  show_menu
  read -p "Choose an option: " opt
  case $opt in
    1) install_bot ;;
    2) restart_bot ;;
    3) update_bot ;;
    4) remove_bot ;;
    5) show_logs ;;
    6) show_logs_live ;;
    0) echo -e "${GREEN}Exiting...${NC}"; exit 0 ;;
    *) echo -e "${RED}Invalid option${NC}"; sleep 1 ;;
  esac
done
