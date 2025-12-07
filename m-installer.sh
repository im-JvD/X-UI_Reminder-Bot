#!/bin/bash

# ==========================================
# X-UI Reminder Bot Multi-Instance Installer
# Modified based on original script
# ==========================================

REPO="https://github.com/im-JvD/X-UI_Reminder-Bot.git"
BASE_INSTALL_PATH="/etc/X-UI_Reminder"

# Colors
GREEN='\033[1;92m'
YELLOW='\033[1;93m'
BLUE='\033[1;94m'
RED='\033[1;91m'
NC='\033[0m'

# Global variables to be set dynamically
CURRENT_INSTANCE_NAME=""
INSTALL_DIR=""
SERVICE_NAME=""
SERVICE_FILE=""

pause() {
  echo -e "\n${YELLOW}Press Enter to return to main menu...${NC}"
  read
}

# --- Helper Functions for Multi-Instance ---

get_new_instance_name() {
  echo -e "${BLUE}========================================${NC}"
  echo -e "${YELLOW}Enter a unique Name for this BOT Instance.${NC}"
  echo -e "Examples: ${GREEN}bo1${NC}, ${GREEN}bot2${NC}, ${GREEN}bot3${NC}"
  echo -e "${BLUE}========================================${NC}"
  read -p "Instance Name: " INSTANCE_NAME

  # Validate name (alphanumeric only)
  if [[ ! "$INSTANCE_NAME" =~ ^[a-zA-Z0-9_]+$ ]]; then
    echo -e "${RED}❌ Invalid name. Use only letters, numbers, and underscores.${NC}"
    pause
    return 1
  fi

  CURRENT_INSTANCE_NAME="$INSTANCE_NAME"
  INSTALL_DIR="$BASE_INSTALL_PATH/$CURRENT_INSTANCE_NAME"
  SERVICE_NAME="x-ui-reminder-$CURRENT_INSTANCE_NAME"
  SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME.service"

  if [ -d "$INSTALL_DIR" ]; then
    echo -e "${RED}❌ An instance with name '$INSTANCE_NAME' already exists!${NC}"
    pause
    return 1
  fi
  return 0
}

select_existing_instance() {
  echo -e "${BLUE}========================================${NC}"
  echo -e "${YELLOW}   Select an existing Bot Instance    ${NC}"
  echo -e "${BLUE}========================================${NC}"

  # Find services starting with x-ui-reminder-
  INSTANCES=($(ls /etc/systemd/system/x-ui-reminder-*.service 2>/dev/null | awk -F/ '{print $NF}' | sed 's/x-ui-reminder-//;s/.service//'))

  if [ ${#INSTANCES[@]} -eq 0 ]; then
    echo -e "${RED}❌ No installed bot instances found.${NC}"
    pause
    return 1
  fi

  local i=1
  for inst in "${INSTANCES[@]}"; do
    echo -e "   ${GREEN}$i ${NC}- ${YELLOW}$inst${NC}"
    ((i++))
  done

  echo -e ""
  read -p "Select number: " choice

  if [[ ! "$choice" =~ ^[0-9]+$ ]] || [ "$choice" -lt 1 ] || [ "$choice" -gt ${#INSTANCES[@]} ]; then
    echo -e "${RED}❌ Invalid selection.${NC}"
    pause
    return 1
  fi

  CURRENT_INSTANCE_NAME="${INSTANCES[$((choice-1))]}"
  INSTALL_DIR="$BASE_INSTALL_PATH/$CURRENT_INSTANCE_NAME"
  SERVICE_NAME="x-ui-reminder-$CURRENT_INSTANCE_NAME"
  SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME.service"
  
  echo -e "${BLUE}Selected Instance: ${GREEN}$CURRENT_INSTANCE_NAME${NC}"
  return 0
}

# --- Core Functions (Modified for Dynamic Paths) ---

configure_env() {
  echo -e "${YELLOW}🔐 Please enter required information for ($CURRENT_INSTANCE_NAME):${NC}"
  read -p "Telegram Bot Token: " BOT_TOKEN
  read -p "Required Channel Username or ID (e.g. @MyChannel or leave empty): " CHANNEL
  read -p "Super Admin Telegram ID(s, comma separated): " SUPERADMIN

  rm -f "$INSTALL_DIR/.env"

  cat > "$INSTALL_DIR/.env" <<EOF
# ============================================
# Telegram Bot Configuration
# ============================================
# Bot token from @BotFather
BOT_TOKEN=$BOT_TOKEN

# Required channel ID for membership check (optional)
# Example: @YourChannel or -1001234567890
REQUIRED_CHANNEL_ID=$CHANNEL

# Superadmin Telegram IDs (comma separated)
# Example: 123456789,987654321
SUPERADMINS=$SUPERADMIN

# ============================================
# Notification Thresholds
# ============================================
# Days remaining threshold for expiring users
EXPIRING_DAYS_THRESHOLD=1

# GB remaining threshold for expiring users
EXPIRING_GB_THRESHOLD=1

# ============================================
# Scheduler Configuration
# ============================================
# Daily report time (24-hour format, Tehran timezone)
# Hour: 0-23
DAILY_REPORT_HOUR=23

# Minute: 0-59
DAILY_REPORT_MINUTE=59

# Change detection interval in minutes (recommended: 5-15)
# Lower values = more frequent checks = higher RAM usage
CHANGE_CHECK_INTERVAL_MINUTES=8
EOF

  echo -e "${GREEN}✅ Configuration file (.env) Created Successfully!${NC}"
}

ensure_service() {
  sudo bash -c "cat > $SERVICE_FILE" <<EOF
[Unit]
Description=X-UI Reminder Bot ($CURRENT_INSTANCE_NAME)
After=network-online.target

[Service]
User=root
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
  if ! get_new_instance_name; then return; fi

  echo -e "${GREEN}🔧 Installing bot ($CURRENT_INSTANCE_NAME)...${NC}"
  
  # Just in case
  mkdir -p "$BASE_INSTALL_PATH"

  git clone "$REPO" "$INSTALL_DIR"
  cd "$INSTALL_DIR"

  echo -e "${BLUE}📦 Creating Python virtual environment${NC}"
  sudo apt update -y
  sudo apt install python3 python3-pip python3-venv sqlite3 -y 
  
  rm -rf .venv
  python3 -m venv .venv
  if [ ! -f ".venv/bin/activate" ]; then
    echo -e "${RED}❌ Failed to create virtual environment${NC}"
    pause
    return
  fi
  
  # Cleanup unnecessary files from repo
  sudo rm -rf Pic m-installer.sh installer.sh api.py README.md

  source .venv/bin/activate
  find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
  find . -type f -name "*.pyc" -delete
  pip install --upgrade pip || { echo -e "${RED}❌ pip upgrade failed${NC}"; deactivate; pause; return; }
  pip install -r requirements.txt || { echo -e "${RED}❌ Package installation failed${NC}"; deactivate; pause; return; }
  pip install jdatetime || { echo -e "${RED}❌ jdatetime installation failed${NC}"; deactivate; pause; return; }
  deactivate

  configure_env

  ensure_service
  sudo systemctl enable $SERVICE_NAME
  sudo systemctl restart $SERVICE_NAME

  echo -e "\n${GREEN}✅ Installation of ($CURRENT_INSTANCE_NAME) Completed Successfully!${NC}"
  pause
}

restart_bot() {
  if ! select_existing_instance; then return; fi
  
  echo -e "${BLUE}🔄 Restarting bot service ($CURRENT_INSTANCE_NAME)...${NC}"
  sudo systemctl stop $SERVICE_NAME
  sudo systemctl enable $SERVICE_NAME
  sudo systemctl start $SERVICE_NAME
  sleep 1
  echo -e "${GREEN}✅ Bot has Start/Restarted.${NC}"
  pause
}

stop_bot() {
  if ! select_existing_instance; then return; fi

  echo -e "${BLUE}🔄 Stoping BOT service ($CURRENT_INSTANCE_NAME)...${NC}"
  sudo systemctl disable $SERVICE_NAME
  sudo systemctl stop $SERVICE_NAME
  sleep 1
  echo -e "${GREEN}✅ Bot has Stoped ...${NC}"
  pause
}

update_bot() {
  if ! select_existing_instance; then return; fi

  echo -e "${YELLOW}⚡️ Updating bot source ($CURRENT_INSTANCE_NAME)...${NC}"
  sudo systemctl stop $SERVICE_NAME 2>/dev/null || true

  if [ ! -d "$INSTALL_DIR" ]; then
    echo -e "${RED}❌ Bot directory not found.${NC}"
    pause
    return
  fi

  cd "$INSTALL_DIR"

  echo -e "${BLUE}💾 Backing up database files...${NC}"
  cp *.db /tmp/ 2>/dev/null || true
  # Backup .env just in case
  cp .env /tmp/${CURRENT_INSTANCE_NAME}_env_backup 2>/dev/null || true

  echo -e "${BLUE}📥 Fetching latest version from GitHub...${NC}"
  git fetch --all
  git reset --hard origin/main

  echo -e "${BLUE}♻️ Restoring database files...${NC}"
  mv /tmp/*.db . 2>/dev/null || true
  # Restore .env if git overwrite killed it (though hard reset usually keeps untracked, better safe)
  # But wait, user wants to Reconfigure env usually. 
  # The original script calls configure_env AGAIN. So we do the same.

  echo -e "${BLUE}📦 Updating Python packages...${NC}"
  if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}⚠️ Virtual environment not found. Creating new one...${NC}"
    python3 -m venv .venv
  fi
  
  sudo rm -rf Pic m-installer.sh installer.sh api.py README.md

  source .venv/bin/activate || { echo -e "${RED}❌ Failed to activate venv${NC}"; pause; return; }
  find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null
  find . -type f -name "*.pyc" -delete
  pip install --upgrade pip
  pip install -r requirements.txt || { echo -e "${RED}❌ Package installation failed${NC}"; deactivate; pause; return; }
  pip install jdatetime || { echo -e "${RED}❌ jdatetime installation failed${NC}"; deactivate; pause; return; }
  deactivate

  echo -e "\n${YELLOW}⚙️ Reconfiguring bot settings...${NC}"
  configure_env

  ensure_service
  sudo systemctl enable $SERVICE_NAME
  sudo systemctl daemon-reload
  sudo systemctl restart $SERVICE_NAME

  echo -e "${GREEN}✅ Update Completed and Service Restarted.${NC}"
  pause
}

status_bot() {
  if ! select_existing_instance; then return; fi
  echo -e "${GREEN}Bot Status ($CURRENT_INSTANCE_NAME) ...${NC}"
  sudo systemctl status $SERVICE_NAME
  pause
}

remove_bot() {
  if ! select_existing_instance; then return; fi

  echo -e "${RED}🗑 Removing bot ($CURRENT_INSTANCE_NAME)...${NC}"
  sudo systemctl stop $SERVICE_NAME 2>/dev/null || true
  sudo systemctl disable $SERVICE_NAME 2>/dev/null || true
  sudo rm -f $SERVICE_FILE
  sudo systemctl daemon-reload
  rm -rf $INSTALL_DIR
  echo -e "${GREEN}✅ Bot removed Completely!${NC}"
  pause
}

show_logs_live() {
  if ! select_existing_instance; then return; fi
  echo -e "${YELLOW}📡 Showing live logs for $CURRENT_INSTANCE_NAME (Press Ctrl+C to exit)${NC}"
  sudo journalctl -u $SERVICE_NAME -f
}

show_menu() {
  clear
  echo -e "${BLUE}============================================${NC}"
  echo -e "${GREEN}  X-UI Reseller Reminder Multi-Bot Manager   ${NC}"
  echo -e "${YELLOW}        BOT Version     [${GREEN} 2.0.0 ${YELLOW}]   ${NC}"
  echo -e "${BLUE}============================================${NC}"
  echo -e ""
  echo -e "   ${GREEN}1 ${NC}-${YELLOW} Install New Bot ${NC}( Instance )"
  echo -e "   ${GREEN}2 ${NC}-${YELLOW} Start/Restart Bot's${NC}"
  echo -e "   ${GREEN}3 ${NC}-${YELLOW} Stop Bot's${NC}"
  echo -e "   ${GREEN}4 ${NC}-${YELLOW} Update Bot's ${NC}"
  echo -e "   ${GREEN}5 ${NC}-${YELLOW} Show Bot's Status${NC}"
  echo -e " ${GREEN}6 ${NC}- ${RED}Remove Bot'sod ${NC}"
  echo -e " ${GREEN}7 ${NC}- ${NC}Show Live Logs"
  echo -e " ${GREEN}0 ${NC}- ${BLUE}Exit ${NC}"
  echo -e ""
  echo -e "${BLUE}========================================${NC}"
  echo -e ""
}

# --- MAIN MENU LOOP ---
# Check root
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root" 
   exit 1
fi

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
