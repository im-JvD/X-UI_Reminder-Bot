#!/bin/bash

INSTALL_DIR=/root/reseller-report-bot
SERVICE_FILE=/etc/systemd/system/reseller-report-bot.service
REPO="https://github.com/im-JvD/X-UI_Reminder-Bot.git"

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
  echo -e "${GREEN}  X-UI Reseller Reminder Bot Manager   ${NC}"
  echo -e "${YELLOW}    BOT Version [${GREEN} 1.5.7 ${YELLOW}]   ${NC}"
  echo -e "${BLUE}========================================${NC}"
  echo -e ""
  echo -e "   ${GREEN}1 ${NC}-${YELLOW} Install Bot${NC}"
  echo -e "   ${GREEN}2 ${NC}-${YELLOW} Start/Restart Bot${NC}"
  echo -e "   ${GREEN}3 ${NC}-${YELLOW} Stop Bot${NC}"
  echo -e "   ${GREEN}4 ${NC}-${YELLOW} Update Bot ${NC}"
  echo -e "   ${GREEN}5 ${NC}-${YELLOW} Show Status${NC}"
  echo -e " ${GREEN}6 ${NC}- ${RED}Remove Bot ${NC}"
  echo -e " ${GREEN}7 ${NC}- ${NC}Show Live Logs"
  echo -e " ${GREEN}0 ${NC}- ${BLUE}Exit ${NC}"
  echo -e ""
  echo -e "${BLUE}========================================${NC}"
  echo -e ""
}

ensure_service() {
  sudo bash -c "cat > $SERVICE_FILE" <<EOF
[Unit]
Description=X-UI Reseller Reminder Bot
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

configure_env() {
  echo -e "${YELLOW}🔐 Please enter required information:${NC}"
  read -p "Telegram Bot Token: " BOT_TOKEN
  read -p "Required Channel Username or ID (e.g. @MyChannel): " CHANNEL
  read -p "Super Admin Telegram ID(s, comma separated): " SUPERADMIN
  echo ""
  echo -e "${YELLOW}Enter your FULL X-UI panel URL (including schema, port, and base path if any):${NC}"
  echo -e "${BLUE}Example:${NC} https://sub.example.com:2053/webbasepath"
  read -p "Panel Full URL: " FULL_URL
  read -p "Panel Username: " PANEL_USER
  read -p "Panel Password: " PANEL_PASS

  PANEL_BASE=$(echo $FULL_URL | sed -E 's#(https?://[^/]+).*#\1#')
  WEBBASEPATH=$(echo $FULL_URL | sed -E 's#https?://[^/]+(/.*)?#\1#')
  [ "$WEBBASEPATH" = "/" ] && WEBBASEPATH=""

  echo -e "${GREEN}✅ Detected PANEL_BASE=$PANEL_BASE${NC}"
  echo -e "${GREEN}✅ Detected WEBBASEPATH=${WEBBASEPATH:-'(none)'}${NC}"

  rm -f "$INSTALL_DIR/.env"

  cat > "$INSTALL_DIR/.env" <<EOF
  
BOT_TOKEN=$BOT_TOKEN
REQUIRED_CHANNEL_ID=$CHANNEL
SUPERADMINS=$SUPERADMIN

PANEL_BASE=$PANEL_BASE
WEBBASEPATH=$WEBBASEPATH/
PANEL_USERNAME=$PANEL_USER
PANEL_PASSWORD=$PANEL_PASS

EXPIRING_DAYS_THRESHOLD=1
EXPIRING_GB_THRESHOLD=1

EOF

  echo -e "${GREEN}✅ Configuration file (.env) created successfully!${NC}"
}

install_bot() {
  echo -e "${GREEN}🔧 Installing bot...${NC}"
  sudo systemctl stop reseller-report-bot 2>/dev/null || true
  sudo systemctl disable reseller-report-bot 2>/dev/null || true
  rm -rf "$INSTALL_DIR"

  git clone "$REPO" "$INSTALL_DIR"
  cd "$INSTALL_DIR"

  echo -e "${BLUE}📦 Creating Python virtual environment${NC}"
  sudo apt install python3.10-venv -y
  rm -rf .venv
  python3 -m venv .venv
  if [ ! -f ".venv/bin/activate" ]; then
    echo -e "${RED}❌ Failed to create virtual environment${NC}"
    pause
    return
  fi

  source .venv/bin/activate
  pip install --upgrade pip || { echo -e "${RED}❌ pip upgrade failed${NC}"; deactivate; pause; return; }
  pip install -r requirements.txt || { echo -e "${RED}❌ Package installation failed${NC}"; deactivate; pause; return; }
  pip install jdatetime || { echo -e "${RED}❌ jdatetime installation failed${NC}"; deactivate; pause; return; }
  deactivate

  configure_env

  ensure_service
  sudo systemctl enable reseller-report-bot
  sudo systemctl restart reseller-report-bot

  echo -e "\n${GREEN}✅ Installation Completed Successfully!${NC}"
  echo -e "${BLUE}Press ENTER to return to menu...${NC}"
  read
}

restart_bot() {
  echo -e "${BLUE}🔄 Restarting bot service...${NC}"
  sudo systemctl stop reseller-report-bot
  sudo systemctl enable reseller-report-bot
  sudo systemctl start reseller-report-bot
  sleep 1
  echo -e "${GREEN}✅ Bot has Start/Restarted.${NC}"
  pause
}

stop_bot() {
  echo -e "${BLUE}🔄 Stoping BOT service...${NC}"
  sudo systemctl disable reseller-report-bot
  sudo systemctl stop reseller-report-bot
  sleep 1
  echo -e "${GREEN}✅ Bot has Stoped ...${NC}"
  pause
}

update_bot() {
  echo -e "${YELLOW}⚡️ Updating bot source...${NC}"
  sudo systemctl stop reseller-report-bot 2>/dev/null || true

  if [ ! -d "$INSTALL_DIR" ]; then
    echo -e "${RED}❌ Bot not installed.${NC}"
    pause
    return
  fi

  cd "$INSTALL_DIR"
  
  echo -e "${BLUE}💾 Backing up database files...${NC}"
  cp *.db /tmp/ 2>/dev/null || true

  echo -e "${BLUE}📥 Fetching latest version from GitHub...${NC}"
  git fetch --all
  git reset --hard origin/main

  echo -e "${BLUE}♻️ Restoring database files...${NC}"
  mv /tmp/*.db . 2>/dev/null || true

  echo -e "${BLUE}📦 Updating Python packages...${NC}"
  if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}⚠️ Virtual environment not found. Creating new one...${NC}"
    sudo apt install python3.10-venv -y
    python3 -m venv .venv
  fi

  source .venv/bin/activate || { echo -e "${RED}❌ Failed to activate venv${NC}"; pause; return; }
  pip install --upgrade pip
  pip install -r requirements.txt || { echo -e "${RED}❌ Package installation failed${NC}"; deactivate; pause; return; }
  pip install jdatetime || { echo -e "${RED}❌ jdatetime installation failed${NC}"; deactivate; pause; return; }
  deactivate

  echo -e "\n${YELLOW}⚙️ Reconfiguring bot settings...${NC}"
  configure_env

  ensure_service
  sudo systemctl enable reseller-report-bot
  sudo systemctl daemon-reload
  sudo systemctl restart reseller-report-bot

  echo -e "${GREEN}✅ Update Completed and Service Restarted.${NC}"
  pause
}

status_bot() {
  echo -e "${GREEN}Bot Status ...${NC}"
  sudo systemctl status reseller-report-bot
}

remove_bot() {
  echo -e "${RED}🗑 Removing bot...${NC}"
  sudo systemctl stop reseller-report-bot 2>/dev/null || true
  sudo systemctl disable reseller-report-bot 2>/dev/null || true
  sudo rm -f $SERVICE_FILE
  sudo systemctl daemon-reload
  rm -rf $INSTALL_DIR
  echo -e "${GREEN}✅ Bot removed Completely!${NC}"
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
    3) stop_bot ;;
    4) update_bot ;;
    5) status_bot ;;
    6) remove_bot ;;
    7) show_logs_live ;;
    0) echo -e "${YELLOW}Support us by giving us a ${GREEN}star on GitHub${YELLOW}, Thank You.${NC}"; exit 0 ;;
    *) echo -e "${RED}Invalid option${NC}"; sleep 1 ;;
  esac
done
