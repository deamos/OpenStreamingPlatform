#!/bin/bash
# OSP Control Script — Modern TUI Edition
# Requires: gum (auto-installed), curl, sudo
#
# SC2024: sudo doesn't affect redirects — safe here because the script
#         enforces EUID==0 at startup, so the shell process IS root and
#         all file redirects work as expected.
# shellcheck disable=SC2024
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)"
readonly DIR
readonly OSPLOG="/var/log/osp/installer.log"
OSP_VERSION=$(<version)
readonly OSP_VERSION

readonly NGINX_BUILD_VERSION="1.25.5"
readonly NGINX_RTMP_VERSION="1.2.12"
readonly NGINX_ZLIB_VERSION="1.3.1"
readonly EJABBERD_VERSION="23.04"

#######################################################
# Cleanup & Signal Handling
#######################################################
cleanup() {
  local exit_code=$?
  # Stop background spinner if running
  if [[ -n "${_SPINNER_PID:-}" ]]; then
    kill "$_SPINNER_PID" 2>/dev/null || true
    wait "$_SPINNER_PID" 2>/dev/null || true
    [[ -n "${_SPINNER_MSG_FILE:-}" ]] && rm -f "$_SPINNER_MSG_FILE"
  fi
  # Restore terminal in case gum/dialog left it in a bad state
  tput cnorm 2>/dev/null || true
  stty sane 2>/dev/null || true
  exit "$exit_code"
}
trap cleanup EXIT INT TERM

#######################################################
# Distro Detection
#######################################################
detect_distro() {
  if [[ -f /etc/os-release ]]; then
    # shellcheck disable=SC1091
    . /etc/os-release
    case "${ID:-}" in
      arch|manjaro|endeavouros)
        DISTRO="arch"
        web_root="/srv/http"
        http_user="http"
        ;;
      debian|ubuntu|pop|linuxmint)
        DISTRO="debian"
        web_root="/var/www"
        http_user="www-data"
        ;;
      *)
        echo "ERROR: Unsupported distro '${ID:-unknown}'. Supported: Debian, Ubuntu, Arch."
        exit 1
        ;;
    esac
  else
    echo "ERROR: Cannot detect distro (/etc/os-release not found)."
    exit 1
  fi
}

detect_distro

#######################################################
# Root Check
#######################################################
if [[ $EUID -ne 0 ]]; then
  echo "This script must be run as root."
  exit 1
fi

#######################################################
# Logging
#######################################################
sudo mkdir -p /var/log/osp/

log_exec() {
  "$@" >> "$OSPLOG" 2>&1
}

log_msg() {
  local level="$1"; shift
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] [$level] $*" >> "$OSPLOG"
}

#######################################################
# Package Management (Distro-Aware)
#######################################################
pkg_update() {
  case "$DISTRO" in
    debian)
      sudo apt-get update >> "$OSPLOG" 2>&1
      sudo unattended-upgrade --debug >> "$OSPLOG" 2>&1 || true
      ;;
    arch)
      sudo pacman -Sy >> "$OSPLOG" 2>&1
      ;;
  esac
}

pkg_install() {
  local packages=("$@")
  if [[ ${#packages[@]} -eq 0 ]]; then return 0; fi

  case "$DISTRO" in
    debian)
      sudo apt-get install -y "${packages[@]}" >> "$OSPLOG" 2>&1
      ;;
    arch)
      sudo pacman -S --noconfirm --needed "${packages[@]}" >> "$OSPLOG" 2>&1
      ;;
  esac
}

wait_for_pkg_lock() {
  local lock_file attempt_count=0 max_attempts=10

  case "$DISTRO" in
    debian) lock_file="/var/lib/dpkg/lock-frontend" ;;
    arch)   lock_file="/var/lib/pacman/db.lck" ;;
  esac

  log_msg "INFO" "Checking if package manager is locked..."
  while [[ $attempt_count -le $max_attempts ]]; do
    if ! sudo fuser "$lock_file" >/dev/null 2>&1; then
      log_msg "INFO" "Package manager is available."
      return 0
    fi
    log_msg "WARN" "Package manager locked. Waiting (attempt $((attempt_count + 1))/$max_attempts)..."
    sleep 5
    attempt_count=$((attempt_count + 1))
  done

  log_msg "ERROR" "Package manager locked for extended duration."
  if [[ "$DISTRO" == "debian" ]]; then
    sudo lsof /var/lib/dpkg/lock /var/lib/dpkg/lock-frontend >> "$OSPLOG" 2>&1 || true
  fi
  return 1
}

updateRunCount=0

update_and_install_safely() {
  local packages=("$@")

  if [[ $updateRunCount -le 0 ]]; then
    log_msg "INFO" "Running initial package update..."
    pkg_update
    updateRunCount=1
  fi

  wait_for_pkg_lock || return 1

  if [[ ${#packages[@]} -gt 0 ]]; then
    log_msg "INFO" "Installing packages: ${packages[*]}"
    pkg_install "${packages[@]}"
  fi
}

#######################################################
# Service Helpers
#######################################################
confirm_service_is_running() {
  local service_name="$1"
  local attempt_count=0 max_attempts=10

  if [[ -z "$service_name" ]]; then
    log_msg "ERROR" "confirm_service_is_running() called without parameters."
    return 1
  fi

  while [[ $attempt_count -le $max_attempts ]]; do
    if systemctl is-active --quiet "$service_name"; then
      log_msg "INFO" "$service_name is ready."
      return 0
    fi
    log_msg "WARN" "$service_name unavailable, retrying..."
    sleep 5
    attempt_count=$((attempt_count + 1))
  done

  log_msg "ERROR" "$service_name failed to start after $max_attempts attempts."
  return 1
}

#######################################################
# gum TUI Setup & Wrapper Functions
#######################################################
install_gum() {
  if command -v gum &>/dev/null; then return 0; fi

  echo "Installing gum (modern TUI toolkit)..."
  case "$DISTRO" in
    debian)
      sudo mkdir -p /etc/apt/keyrings
      curl -fsSL https://repo.charm.sh/apt/gpg.key \
        | sudo gpg --dearmor -o /etc/apt/keyrings/charm.gpg 2>/dev/null
      echo "deb [signed-by=/etc/apt/keyrings/charm.gpg] https://repo.charm.sh/apt/ * *" \
        | sudo tee /etc/apt/sources.list.d/charm.list >/dev/null
      sudo apt-get update >> "$OSPLOG" 2>&1
      sudo apt-get install -y gum >> "$OSPLOG" 2>&1
      ;;
    arch)
      sudo pacman -S --noconfirm gum >> "$OSPLOG" 2>&1
      ;;
  esac

  if ! command -v gum &>/dev/null; then
    echo "WARNING: Failed to install gum. Please install manually."
    echo "  Debian/Ubuntu: https://charm.sh/docs/installation"
    echo "  Arch: pacman -S gum"
    exit 1
  fi
}

install_gum

# -- TUI Abstraction Layer --

show_header() {
  echo ""
  gum style \
    --foreground 212 --border-foreground 99 --border double \
    --align center --width 60 --margin "1 2" --padding "1 2" \
    "Open Streaming Platform" "v${OSP_VERSION}" ""
}

show_menu() {
  local title="$1"; shift
  gum style --foreground 99 --bold --margin "0 2" "$title" >&2
  echo "" >&2
  gum choose --cursor.foreground 212 --selected.foreground 212 "$@"
}

# ---- Persistent Background Spinner ----
_SPINNER_PID=""
_SPINNER_MSG_FILE=""

_spinner_loop() {
  local frames=('⠋' '⠙' '⠹' '⠸' '⠼' '⠴' '⠦' '⠧' '⠇' '⠏')
  local i=0
  tput civis >/dev/tty 2>/dev/null || true   # hide cursor
  while true; do
    local msg
    msg=$(<"$_SPINNER_MSG_FILE")
    printf '\r\033[K  \033[38;5;212m%s\033[0m %s' "${frames[i]}" "$msg" >/dev/tty
    i=$(( (i + 1) % ${#frames[@]} ))
    sleep 0.08
  done
}

start_spinner() {
  # If already running, just update the message
  if [[ -n "$_SPINNER_PID" ]] && kill -0 "$_SPINNER_PID" 2>/dev/null; then
    echo "$1" > "$_SPINNER_MSG_FILE"
    return
  fi
  _SPINNER_MSG_FILE=$(mktemp)
  echo "$1" > "$_SPINNER_MSG_FILE"
  _spinner_loop &
  _SPINNER_PID=$!
}

update_spinner() {
  if [[ -n "$_SPINNER_MSG_FILE" ]]; then
    echo "$1" > "$_SPINNER_MSG_FILE"
  fi
}

stop_spinner() {
  if [[ -n "$_SPINNER_PID" ]]; then
    kill "$_SPINNER_PID" 2>/dev/null || true
    wait "$_SPINNER_PID" 2>/dev/null || true
    _SPINNER_PID=""
  fi
  [[ -n "$_SPINNER_MSG_FILE" ]] && rm -f "$_SPINNER_MSG_FILE"
  _SPINNER_MSG_FILE=""
  printf '\r\033[K' >/dev/tty 2>/dev/null || true    # clear spinner line
  tput cnorm >/dev/tty 2>/dev/null || true            # restore cursor
}

# Run a single command under the persistent spinner
run_with_spinner() {
  local title="$1"; shift
  start_spinner "$title"
  if ! "$@" >> "$OSPLOG" 2>&1; then
    log_msg "WARN" "Command failed during: $title ($*)"
  fi
}

# Update the spinner status (used inside install/upgrade functions)
log_step() {
  if [[ -n "$_SPINNER_PID" ]] && kill -0 "$_SPINNER_PID" 2>/dev/null; then
    update_spinner "$1"
  else
    # Spinner not running — start one
    start_spinner "$1"
  fi
}

show_result() {
  stop_spinner
  local title="$1"; shift
  echo ""
  gum style \
    --foreground 82 --border-foreground 99 --border rounded \
    --padding "1 3" --margin "1 2" \
    "$title" "" "$@"
  echo ""
  read -rp "  Press Enter to continue..."
}

ask_confirm() {
  stop_spinner
  gum confirm --prompt.foreground 212 "$1"
}

ask_input() {
  stop_spinner
  local placeholder="${1:-}" header="${2:-}"
  if [[ -n "$header" ]]; then
    gum input --placeholder "$placeholder" --header "$header" --header.foreground 99
  else
    gum input --placeholder "$placeholder"
  fi
}

#######################################################
# Directory Helpers
#######################################################
create_web_dirs() {
  local dirs=(live videos images images/stickers live-adapt stream-thumb keys keys-adapt pending ingest)
  for d in "${dirs[@]}"; do
    sudo mkdir -p "$web_root/$d"
  done >> "$OSPLOG" 2>&1
}

#######################################################
# SMTP Configuration
#######################################################
config_smtp() {
  stop_spinner
  local smtpSendAs smtpServerAddress smtpServerPort smtpUsername smtpPassword smtpEncryption

  smtpSendAs=$(ask_input "you@example.com" "Send Email As (required)") || true
  smtpServerAddress=$(ask_input "smtp.example.com" "SMTP Server Address (required)") || true
  smtpServerPort=$(ask_input "25" "SMTP Server Port (required)") || true
  smtpUsername=$(ask_input "username" "SMTP Username (optional)") || true
  smtpPassword=$(ask_input "password" "SMTP Password (optional)") || true

  gum style --foreground 99 --bold --margin "0 2" "Select SMTP Encryption:" >/dev/tty
  smtpEncryption=$(gum choose "none" "tls" "ssl") || true

  sudo sed -i "s/sendAs@email.com/$smtpSendAs/" /opt/osp/conf/config.py >> "$OSPLOG" 2>&1
  sudo sed -i "s/smtp.email.com/$smtpServerAddress/" /opt/osp/conf/config.py >> "$OSPLOG" 2>&1
  sudo sed -i "s/smtpServerPort=25/smtpServerPort=$smtpServerPort/" /opt/osp/conf/config.py >> "$OSPLOG" 2>&1
  sudo sed -i "s/smtpUsername=\"\"/smtpUsername=\"$smtpUsername\"/" /opt/osp/conf/config.py >> "$OSPLOG" 2>&1
  sudo sed -i "s/smtpPassword=\"\"/smtpPassword=\"$smtpPassword\"/" /opt/osp/conf/config.py >> "$OSPLOG" 2>&1
  sudo sed -i "s/smtpEncryption=\"none\"/smtpEncryption=\"$smtpEncryption\"/" /opt/osp/conf/config.py >> "$OSPLOG" 2>&1
}

#######################################################
# Reset Functions
#######################################################
reset_nginx() {
  (
    if cd /usr/local/nginx/conf; then
      run_with_spinner "Stopping Nginx-OSP..." sudo systemctl stop nginx-osp
      log_exec sudo systemctl disable nginx-osp

      run_with_spinner "Backing up existing conf..." bash -c "
        sudo mkdir -p /tmp/nginxbak &&
        sudo cp -R /usr/local/nginx/conf /tmp/nginxbak
      "

      cd /
      run_with_spinner "Removing previous Nginx..." sudo rm -rf /usr/local/nginx
      run_with_spinner "Rebuilding Nginx from source..." bash -c "$(declare -f install_nginx_core log_exec log_msg pkg_install pkg_update wait_for_pkg_lock update_and_install_safely install_prereq install_ffmpeg create_web_dirs confirm_service_is_running run_with_spinner log_step); install_nginx_core"
      run_with_spinner "Restoring Nginx conf..." sudo cp -R /tmp/nginxbak/conf/* /usr/local/nginx/conf/
      run_with_spinner "Restarting Nginx-OSP..." bash -c "
        sudo systemctl enable nginx-osp &&
        sudo systemctl start nginx-osp
      "
    fi
  )
}

reset_ejabberd() {
  # Delete old settings in config.py
  sudo sed -i '/^ejabberdPass/d' /opt/osp/conf/config.py >> "$OSPLOG" 2>&1
  sudo sed -i '/^ejabberdHost/d' /opt/osp/conf/config.py >> "$OSPLOG" 2>&1
  sudo sed -i '/^ejabberdAdmin/d' /opt/osp/conf/config.py >> "$OSPLOG" 2>&1

  # Add new settings lines to config.py
  echo 'ejabberdAdmin = "admin"' | sudo tee -a /opt/osp/conf/config.py >/dev/null
  echo 'ejabberdHost = "localhost"' | sudo tee -a /opt/osp/conf/config.py >/dev/null
  echo 'ejabberdPass = "CHANGE_EJABBERD_PASS"' | sudo tee -a /opt/osp/conf/config.py >/dev/null

  install_ejabberd
  generate_ejabberd_admin
}

#######################################################
# Database Upgrade
#######################################################
upgrade_db() {
  (
    run_with_spinner "Stopping OSP..." sudo systemctl stop osp.target
    cd /opt/osp
    run_with_spinner "Upgrading Database..." bash -c "
      source venv/bin/activate &&
      flask db upgrade &&
      deactivate
    "
    run_with_spinner "Starting OSP..." sudo systemctl start osp.target
  )
}

#######################################################
# Install Functions
#######################################################
install_prereq() {
  case "$DISTRO" in
    debian)
      run_with_spinner "Installing prerequisites (Debian)..." bash -c "
        $(declare -f update_and_install_safely wait_for_pkg_lock pkg_update pkg_install log_msg)
        OSPLOG='$OSPLOG'; DISTRO='$DISTRO'; updateRunCount=$updateRunCount
        update_and_install_safely wget build-essential libpcre3 libpcre3-dev libssl-dev unzip libpq-dev curl git
        update_and_install_safely python3 python3-pip python3-venv uwsgi-plugin-python3 python3-dev 
      "
      ;;
    arch)
      run_with_spinner "Installing prerequisites (Arch)..." bash -c "
        $(declare -f update_and_install_safely wait_for_pkg_lock pkg_update pkg_install log_msg)
        OSPLOG='$OSPLOG'; DISTRO='$DISTRO'; updateRunCount=$updateRunCount
        update_and_install_safely wget base-devel pcre openssl unzip postgresql-libs curl git
        update_and_install_safely python python-pip
      "
      ;;
  esac
}

install_ffmpeg() {
  run_with_spinner "Installing FFMPEG..." update_and_install_safely ffmpeg
}

install_mysql() {
  run_with_spinner "Installing MariaDB Server..." update_and_install_safely mariadb-server
  run_with_spinner "Configuring MySQL..." sudo cp "$DIR/setup/mysql/mysqld.cnf" /etc/mysql/my.cnf

  run_with_spinner "Restarting MySQL..." sudo systemctl restart mysql
  confirm_service_is_running mysql >> "$OSPLOG" 2>&1 || true

  log_step "Building database..."
  log_exec sudo mysql -e "create database osp" || true

  local SQLPASS
  SQLPASS=$(tr -dc 'a-zA-Z0-9' < /dev/urandom | fold -w 32 | head -n 1)
  local USER_EXISTS
  USER_EXISTS=$(sudo mysql -e "SELECT EXISTS(SELECT 1 FROM mysql.user WHERE user = 'osp' AND host = 'localhost');" -s -N)

  if [[ "$USER_EXISTS" -eq 1 ]]; then
    log_msg "INFO" "OSP MySQL user already exists. Resetting password..."
    sudo mysql -e "ALTER USER 'osp'@'localhost' IDENTIFIED BY '$SQLPASS';" >> "$OSPLOG" 2>&1
  else
    log_msg "INFO" "Creating OSP MySQL user..."
    sudo mysql -e "CREATE USER 'osp'@'localhost' IDENTIFIED BY '$SQLPASS'" >> "$OSPLOG" 2>&1
  fi

  sudo mysql -e "GRANT ALL PRIVILEGES ON osp.* TO 'osp'@'localhost'" >> "$OSPLOG" 2>&1
  sudo mysql -e "flush privileges" >> "$OSPLOG" 2>&1

  sudo sed -i "s/sqlpass/$SQLPASS/g" /opt/osp-rtmp/conf/config.py >> "$OSPLOG" 2>&1
  sudo sed -i "s/sqlpass/$SQLPASS/g" /opt/osp/conf/config.py >> "$OSPLOG" 2>&1
}

install_nginx_core() {
  install_prereq

  (
    cd /tmp || { echo "Unable to access /tmp! Aborting."; exit 1; }

    run_with_spinner "Downloading Nginx source..." \
      sudo wget -q "http://nginx.org/download/nginx-$NGINX_BUILD_VERSION.tar.gz"

    run_with_spinner "Downloading required modules..." bash -c "
      sudo wget -q 'https://github.com/winshining/nginx-http-flv-module/archive/refs/tags/v$NGINX_RTMP_VERSION.tar.gz' &&
      sudo wget -q 'https://github.com/madler/zlib/archive/refs/tags/v$NGINX_ZLIB_VERSION.tar.gz' &&
      sudo wget -q 'https://github.com/xuges/nginx-sticky-module-ng/archive/refs/heads/master.tar.gz'
    "

    run_with_spinner "Decompressing sources..." bash -c "
      sudo tar xfz nginx-$NGINX_BUILD_VERSION.tar.gz &&
      sudo tar xfz v$NGINX_RTMP_VERSION.tar.gz &&
      sudo tar xfz v$NGINX_ZLIB_VERSION.tar.gz &&
      sudo tar xfz master.tar.gz
    "

    cd "nginx-$NGINX_BUILD_VERSION" || { echo "Unable to build Nginx! Aborting."; exit 1; }

    run_with_spinner "Configuring Nginx build..." \
      ./configure \
        --with-http_ssl_module \
        --with-http_v2_module \
        --with-http_auth_request_module \
        --with-http_stub_status_module \
        --add-module="../nginx-http-flv-module-$NGINX_RTMP_VERSION" \
        --add-module=../nginx-sticky-module-ng-master \
        "--with-zlib=../zlib-$NGINX_ZLIB_VERSION" \
        --with-cc-opt="-Wimplicit-fallthrough=0"

    run_with_spinner "Compiling and installing Nginx..." sudo make install
  )

  # Copy configuration
  log_step "Copying Nginx config files..."
  log_exec sudo cp "$DIR/installs/nginx-core/nginx.conf" /usr/local/nginx/conf/
  log_exec sudo cp "$DIR/installs/nginx-core/mime.types" /usr/local/nginx/conf/
  for d in locations upstream servers services custom; do
    sudo mkdir -p "/usr/local/nginx/conf/$d" >> "$OSPLOG" 2>&1
  done
  log_exec sudo cp "$DIR/installs/nginx-core/osp-custom-servers.conf" /usr/local/nginx/conf/custom/
  log_exec sudo cp "$DIR/installs/nginx-core/osp-custom-serversredirect.conf" /usr/local/nginx/conf/custom/

  # SystemD setup
  log_step "Setting up Nginx SystemD service..."
  log_exec sudo cp "$DIR/installs/nginx-core/nginx-osp.service" /etc/systemd/system/nginx-osp.service
  log_exec sudo systemctl daemon-reload
  log_exec sudo systemctl enable nginx-osp.service

  install_ffmpeg

  # Create web directories
  log_step "Creating video directories..."
  sudo mkdir -p "$web_root" >> "$OSPLOG" 2>&1
  create_web_dirs

  local s3DriveMount
  s3DriveMount=$(mount | grep -iE "/var/www/videos" | grep s3fs | wc -l || true)
  if [[ "$s3DriveMount" -eq 0 ]]; then
    log_step "Setting directory ownership..."
    log_exec sudo chown -R "$http_user:$http_user" "$web_root"
  fi

  # Start Nginx
  run_with_spinner "Starting Nginx..." sudo systemctl start nginx-osp.service
}

install_osp_rtmp_venv() {
  (
    cd /opt/osp-rtmp || { log_msg "ERROR" "/opt/osp-rtmp not found"; return 1; }
    sudo python3 -m venv venv >> "$OSPLOG" 2>&1
    # shellcheck disable=SC1091
    source venv/bin/activate >> "$OSPLOG" 2>&1
    pip3 install --upgrade pip setuptools wheel >> "$OSPLOG" 2>&1
    pip3 uninstall -r "$DIR/installs/osp-rtmp/setup/remove_requirements.txt" -y >> "$OSPLOG" 2>&1 || true
    pip3 install -r "$DIR/installs/osp-rtmp/setup/requirements.txt" >> "$OSPLOG" 2>&1
    deactivate
  )
}

install_osp_rtmp() {
  run_with_spinner "Installing OSP-RTMP prerequisites..." bash -c "true"
  install_prereq

  log_step "Setting up Nginx configs for RTMP..."
  log_exec sudo cp "$DIR/installs/osp-rtmp/setup/nginx/servers/"*.conf /usr/local/nginx/conf/servers
  log_exec sudo cp "$DIR/installs/osp-rtmp/setup/nginx/services/"*.conf /usr/local/nginx/conf/services
  log_exec sudo cp "$DIR/installs/osp-rtmp/setup/nginx/custom/osp-rtmp-"* /usr/local/nginx/conf/custom

  # Create OSP-RTMP folder
  sudo mkdir -p /opt/osp-rtmp >> "$OSPLOG" 2>&1

  run_with_spinner "Installing Python requirements..." install_osp_rtmp_venv

  # Copy OSP-RTMP data
  log_step "Deploying OSP-RTMP application..."
  log_exec sudo cp -R "$DIR/installs/osp-rtmp/"* /opt/osp-rtmp
  sudo mkdir -p /opt/osp-rtmp/rtmpsocket >> "$OSPLOG" 2>&1
  log_exec sudo chown -R www-data:www-data /opt/osp-rtmp/rtmpsocket

  # Log file access fix
  sudo touch /opt/osp-rtmp/logs/access.log
  sudo touch /opt/osp-rtmp/logs/error.log
  sudo chown -R "$http_user:$http_user" /opt/osp-rtmp/logs

  log_step "Installing SystemD service..."
  log_exec sudo cp "$DIR/installs/osp-rtmp/setup/gunicorn/osp-rtmp.service" /etc/systemd/system/osp-rtmp.service
  log_exec sudo systemctl daemon-reload
  log_exec sudo systemctl enable osp-rtmp.service
}

install_redis() {
  run_with_spinner "Installing Redis server..." update_and_install_safely redis
  run_with_spinner "Configuring Redis..." \
    sudo sed -i 's/appendfsync everysec/appendfsync no/' /etc/redis/redis.conf
}

install_osp_proxy_venv() {
  (
    cd /opt/osp-proxy || { log_msg "ERROR" "/opt/osp-proxy not found"; return 1; }
    sudo python3 -m venv venv >> "$OSPLOG" 2>&1
    # shellcheck disable=SC1091
    source venv/bin/activate >> "$OSPLOG" 2>&1
    pip3 install --upgrade pip setuptools wheel >> "$OSPLOG" 2>&1
    pip3 install -r "$DIR/installs/osp-proxy/setup/requirements.txt" >> "$OSPLOG" 2>&1
    deactivate
  )
}

install_osp_proxy() {
  local user_input
  user_input=$(ask_input "https://osp.example.com" "Enter your OSP-Core Protocol and FQDN")

  log_step "Installing OSP-Proxy configuration files..."
  log_exec sudo cp "$DIR/installs/osp-proxy/setup/nginx/locations/osp-proxy-locations.conf" /usr/local/nginx/conf/locations
  log_exec sudo cp "$DIR/installs/osp-proxy/setup/nginx/servers/osp-proxy-servers.conf" /usr/local/nginx/conf/servers
  log_exec sudo cp "$DIR/installs/osp-proxy/setup/nginx/nginx.conf" /usr/local/nginx/conf/nginx.conf
  log_exec sudo cp "$DIR/installs/osp-proxy/setup/nginx/cors.conf" /usr/local/nginx/conf/cors.conf
  log_exec sudo cp "$DIR/installs/osp-proxy/setup/nginx/custom/osp-proxy-custom"* /usr/local/nginx/conf/custom/

  sudo mkdir -p /opt/osp-proxy >> "$OSPLOG" 2>&1
  log_exec sudo cp -R "$DIR/installs/osp-proxy/"* /opt/osp-proxy
  log_exec sudo cp /opt/osp-proxy/conf/config.py.dist /opt/osp-proxy/conf/config.py
  log_exec sudo chmod +x /opt/osp-proxy/updateUpstream.sh
  sudo mkdir -p /var/cache/nginx/osp_cache_temp >> "$OSPLOG" 2>&1

  run_with_spinner "Installing Python requirements..." install_osp_proxy_venv

  # Configure with OSP-Core address
  sed -i "s|#CHANGEMETOOSPCORE|$user_input|g" /opt/osp-proxy/conf/config.py >> "$OSPLOG" 2>&1

  log_step "Installing SystemD service..."
  log_exec sudo cp "$DIR/installs/osp-proxy/setup/gunicorn/osp-proxy.service" /etc/systemd/system/osp-proxy.service
  log_exec sudo systemctl daemon-reload
  log_exec sudo systemctl enable osp-proxy.service
  log_exec sudo systemctl start osp-proxy.service

  # Enable upstream updater cron
  log_step "Setting up upstream updater cron..."
  local cronjob="*/5 * * * * /opt/osp-proxy/updateUpstream.sh"
  (sudo crontab -u root -l 2>/dev/null; echo "$cronjob") | sudo crontab -u root -
  log_exec sudo systemctl restart cron
}

install_osp_edge() {
  local user_input core_input

  user_input=$(ask_input "192.168.0.4,192.168.0.5" "Enter OSP-RTMP IP(s) (comma-separated)")
  core_input=$(ask_input "192.168.0.4,192.168.0.5" "Enter OSP-Core IP(s) (comma-separated)")

  local rtmpString="" coreString=""
  IFS="," read -ra rtmpArray <<< "$user_input"
  for i in "${rtmpArray[@]}"; do
    rtmpString+="allow publish $i;\\n"
  done

  IFS="," read -ra coreArray <<< "$core_input"
  for i in "${coreArray[@]}"; do
    coreString+="allow $i;\\n"
  done

  log_step "Installing OSP-Edge configuration files..."
  log_exec sudo cp "$DIR/installs/osp-edge/setup/nginx/locations/osp-edge-redirects.conf" /usr/local/nginx/conf/locations
  log_exec sudo cp "$DIR/installs/osp-edge/setup/nginx/servers/osp-edge-servers.conf" /usr/local/nginx/conf/servers
  log_exec sudo cp "$DIR/installs/osp-edge/setup/nginx/services/osp-edge-rtmp.conf" /usr/local/nginx/conf/services
  log_exec sudo cp "$DIR/installs/osp-edge/setup/nginx/custom/osp-edge-custom"* /usr/local/nginx/conf/custom

  sed -i "s/#ALLOWRTMP/$rtmpString/g" /usr/local/nginx/conf/custom/osp-edge-custom-allowedpub.conf >> "$OSPLOG" 2>&1
  sed -i "s/#ALLOWCORE/$coreString/g" /usr/local/nginx/conf/custom/osp-edge-custom-nginxstat.conf >> "$OSPLOG" 2>&1

  sudo mkdir -p /opt/osp-edge/rtmpsocket >> "$OSPLOG" 2>&1
  sudo chown -R www-data:www-data /opt/osp-edge/rtmpsocket >> "$OSPLOG" 2>&1

  sudo mkdir -p /var/www/live >> "$OSPLOG" 2>&1
  sudo mkdir -p /var/www/live-adapt >> "$OSPLOG" 2>&1
  sudo chown -R www-data:www-data /var/www >> "$OSPLOG" 2>&1

  run_with_spinner "Restarting Nginx Core..." sudo systemctl restart nginx-osp.service
}

install_ejabberd_venv() {
  sudo python3 -m venv /opt/ejabberd/venv >> "$OSPLOG" 2>&1
  /opt/ejabberd/venv/bin/pip3 install requests >> "$OSPLOG" 2>&1
}

install_ejabberd() {
  run_with_spinner "Installing ejabberd prerequisites..." bash -c "sudo mkdir -p /opt/ejabberd"
  install_ejabberd_venv

  run_with_spinner "Downloading ejabberd..." \
    sudo wget -O "/tmp/ejabberd-$EJABBERD_VERSION-linux-x64.run" \
      "https://github.com/processone/ejabberd/releases/download/$EJABBERD_VERSION/ejabberd-$EJABBERD_VERSION-1-linux-x64.run"

  run_with_spinner "Installing ejabberd..." bash -c "
    sudo chmod +x /tmp/ejabberd-$EJABBERD_VERSION-linux-x64.run &&
    yes | sudo bash /tmp/ejabberd-$EJABBERD_VERSION-linux-x64.run --quiet
  "

  log_exec sudo ln -sf /opt/ejabberd /usr/local/ejabberd

  log_step "Installing ejabberd configuration..."
  mkdir -p /opt/ejabberd/conf >> "$OSPLOG" 2>&1
  log_exec sudo cp "$DIR/installs/ejabberd/setup/ejabberd.yml" /opt/ejabberd/conf/ejabberd.yml
  log_exec sudo cp "$DIR/installs/ejabberd/setup/inetrc" /opt/ejabberd/conf/inetrc
  # Use repo-provided service file; fall back to extracted binary path if present
  local ejabberd_svc="$DIR/installs/ejabberd/setup/ejabberd.service"
  if [[ ! -f "$ejabberd_svc" ]]; then
    ejabberd_svc="/opt/ejabberd-$EJABBERD_VERSION/bin/ejabberd.service"
  fi
  log_exec sudo cp "$ejabberd_svc" /etc/systemd/system/ejabberd.service

  local user_input="osp.internal"
  sudo sed -i "s/CHANGEME/$user_input/g" /opt/ejabberd/conf/ejabberd.yml >> "$OSPLOG" 2>&1

  log_exec sudo cp "$DIR/installs/ejabberd/setup/auth_osp.py" /opt/ejabberd/conf/auth_osp.py
  log_exec sudo systemctl daemon-reload
  log_exec sudo systemctl enable ejabberd
  run_with_spinner "Starting ejabberd..." sudo systemctl start ejabberd

  log_exec sudo cp "$DIR/installs/ejabberd/setup/nginx/locations/ejabberd.conf" /usr/local/nginx/conf/locations/
  sudo chown -R ejabberd:ejabberd /opt/ejabberd
}

generate_ejabberd_admin() {
  # Find ejabberdctl — works for both apt-installed and self-extracted versions
  local ejabberdctl
  ejabberdctl=$(find /opt /usr -name 'ejabberdctl' -type f 2>/dev/null | head -1)
  if [[ -z "$ejabberdctl" ]]; then
    log_msg "ERROR" "ejabberdctl not found — ejabberd may not be installed"
    return 1
  fi

  confirm_service_is_running ejabberd >> "$OSPLOG" 2>&1 || true
  sudo "$ejabberdctl" unregister admin localhost || true

  local ADMINPASS
  ADMINPASS=$(tr -dc 'a-zA-Z0-9' < /dev/urandom | fold -w 32 | head -n 1)

  sudo sed -i "s/CHANGE_EJABBERD_PASS/$ADMINPASS/" /opt/osp/conf/config.py >> "$OSPLOG" 2>&1

  local user_input="osp.internal"
  sudo sed -i "s/CHANGEME/$user_input/g" /opt/ejabberd/conf/ejabberd.yml >> "$OSPLOG" 2>&1

  log_exec sudo "$ejabberdctl" register admin localhost "$ADMINPASS"
  log_exec sudo "$ejabberdctl" change_password admin localhost "$ADMINPASS"
  sudo systemctl restart ejabberd
}

install_osp_venv() {
  (
    cd /opt/osp || { log_msg "ERROR" "/opt/osp not found"; return 1; }
    sudo python3 -m venv venv >> "$OSPLOG" 2>&1
    # shellcheck disable=SC1091
    source venv/bin/activate >> "$OSPLOG" 2>&1
    pip3 install --upgrade pip >> "$OSPLOG" 2>&1
    pip3 uninstall -r "$DIR/setup/remove_requirements.txt" -y >> "$OSPLOG" 2>&1 || true
    pip3 install -r "$DIR/setup/requirements.txt" >> "$OSPLOG" 2>&1
    # Reinstall setuptools/wheel after requirements.txt, which may pin an older
    # wheel that strips setuptools — required by gunicorn/flask_security on Python 3.12+
    #pip3 install --upgrade setuptools wheel >> "$OSPLOG" 2>&1
    deactivate
  )
}

install_osp() {
  log_msg "INFO" "Starting OSP Install"

  install_prereq

  # Setup OSP Directory
  log_step "Setting up OSP directory..."
  mkdir -p /opt/osp >> "$OSPLOG" 2>&1
  log_exec sudo cp -rf "$DIR/"* /opt/osp
  log_exec sudo cp -rf "$DIR/.git" /opt/osp

  run_with_spinner "Setting up Python virtual environment..." install_osp_venv

  # Gunicorn SystemD
  log_step "Configuring Gunicorn SystemD..."
  log_exec sudo cp "$DIR/setup/gunicorn/osp.target" /etc/systemd/system/
  log_exec sudo cp "$DIR/setup/gunicorn/osp-worker@.service" /etc/systemd/system/
  log_exec sudo systemctl daemon-reload
  log_exec sudo systemctl enable osp.target

  log_exec sudo cp "$DIR/setup/nginx/locations/"* /usr/local/nginx/conf/locations
  log_exec sudo cp "$DIR/setup/nginx/upstream/osp.conf" /usr/local/nginx/conf/upstream
  log_exec sudo cp "$DIR/setup/nginx/upstream/osp-edge.conf" /usr/local/nginx/conf/upstream
  log_exec sudo cp "$DIR/setup/nginx/upstream/osp-maps.conf" /usr/local/nginx/conf/upstream

  # Create web directories
  log_step "Creating video directories..."
  sudo mkdir -p "$web_root" >> "$OSPLOG" 2>&1
  create_web_dirs

  local s3DriveMount
  s3DriveMount=$(mount | grep -iE "/var/www/videos" | grep s3fs | wc -l || true)
  if [[ "$s3DriveMount" -eq 0 ]]; then
    log_exec sudo chown -R "$http_user:$http_user" "$web_root"
  fi

  log_exec sudo chown -R "$http_user:$http_user" /opt/osp
  log_exec sudo chown -R "$http_user:$http_user" /opt/osp/.git

  # Copy initial favicons
  log_step "Copying favicon assets..."
  for icon in android-chrome-192x192.png android-chrome-512x512.png apple-touch-icon.png favicon.ico favicon-16x16.png favicon-32x32.png; do
    log_exec sudo cp "$DIR/static/$icon" "$web_root/images/"
  done

  install_celery

  # Setup logrotate
  log_step "Setting up log rotation..."
  if [[ -d /etc/logrotate.d ]]; then
    log_exec sudo cp /opt/osp/setup/logrotate/* /etc/logrotate.d/
  else
    update_and_install_safely logrotate >> "$OSPLOG" 2>&1
    if [[ -d /etc/logrotate.d ]]; then
      log_exec sudo cp /opt/osp/setup/logrotate/* /etc/logrotate.d/
    else
      log_msg "WARN" "Unable to setup logrotate"
    fi
  fi
}

install_celery() {
  log_step "Setting up Celery..."
  sudo mkdir -p /var/log/celery >> "$OSPLOG" 2>&1
  sudo chown -R www-data:www-data /var/log/celery >> "$OSPLOG" 2>&1
  log_exec sudo cp -rf "$DIR/setup/celery/osp-celery.service" /etc/systemd/system
  log_exec sudo cp -rf "$DIR/setup/celery/celery" /etc/default/celery
  log_exec sudo systemctl daemon-reload
  log_exec sudo systemctl enable osp-celery
}

install_celery_beat() {
  log_step "Setting up Celery Beat..."
  log_exec sudo cp -rf "$DIR/setup/celery/osp-celery-beat.service" /etc/systemd/system
  log_exec sudo systemctl daemon-reload
  log_exec sudo systemctl enable osp-celery-beat
}

install_celery_flower() {
  log_step "Setting up Celery Flower..."
  log_exec sudo pip3 install flower
  log_exec sudo cp -rf "$DIR/setup/celery/osp-celery-flower.service" /etc/systemd/system
  log_exec sudo cp -rf "$DIR/setup/celery/celery-flower" /etc/default/celery-flower

  local ADMINPASS
  ADMINPASS=$(tr -dc 'a-zA-Z0-9' < /dev/urandom | fold -w 16 | head -n 1)
  sed -i "s/CHANGEME/$ADMINPASS/" /etc/default/celery-flower >> "$OSPLOG" 2>&1

  log_exec sudo systemctl daemon-reload
  log_exec sudo systemctl enable osp-celery-flower

  show_result "Celery Flower Installed" \
    "Visit http://FQDN:5572 to configure\nUsername: Admin\nPassword: $ADMINPASS\n\nEdit /etc/default/celery-flower to change the password."
}

#######################################################
# Upgrade Functions
#######################################################
upgrade_celery() {
  install_prereq
  install_celery
  log_exec sudo systemctl restart osp-celery
}

upgrade_celery_beat() {
  install_prereq
  install_celery_beat
  log_exec sudo systemctl restart osp-celery-beat
}

upgrade_osp() {
  install_prereq
  (
    cd /opt/osp || { log_msg "ERROR" "/opt/osp does not exist"; return 1; }

    run_with_spinner "Setting /opt/osp ownership..." sudo chown -R "$http_user:$http_user" /opt/osp
    run_with_spinner "Stopping OSP..." sudo systemctl stop osp.target
    run_with_spinner "Stopping Nginx..." sudo systemctl stop nginx-osp

    install_osp_venv

    log_step "Upgrading Nginx configurations..."
    log_exec sudo cp -rf /opt/osp/setup/nginx/locations/* /usr/local/nginx/conf/locations
    log_exec sudo cp -rf /opt/osp/setup/nginx/upstream/osp.conf /usr/local/nginx/conf/upstream
    log_exec sudo cp -rf /opt/osp/setup/nginx/upstream/osp-edge.conf /usr/local/nginx/conf/upstream
    log_exec sudo cp -rf /opt/osp/setup/nginx/upstream/osp-maps.conf /usr/local/nginx/conf/upstream
    log_exec sudo cp "$DIR/setup/gunicorn/osp.target" /etc/systemd/system/
    log_exec sudo cp "$DIR/setup/gunicorn/osp-worker@.service" /etc/systemd/system/
    log_exec sudo systemctl daemon-reload
    log_exec sudo systemctl enable osp.target

    run_with_spinner "Upgrading database..." bash -c "
      cd /opt/osp &&
      source venv/bin/activate &&
      flask db upgrade &&
      deactivate
    "

    run_with_spinner "Starting OSP..." sudo systemctl start osp.target
    run_with_spinner "Starting Nginx..." sudo systemctl start nginx-osp
  )
}

upgrade_proxy() {
  install_prereq
  log_exec sudo cp "$DIR/installs/osp-proxy/setup/nginx/locations/"*.conf /usr/local/nginx/conf/locations
  log_exec sudo cp "$DIR/installs/osp-proxy/setup/nginx/servers/"*.conf /usr/local/nginx/conf/servers
  log_exec sudo cp "$DIR/installs/osp-proxy/setup/nginx/nginx.conf" /usr/local/nginx/conf/nginx.conf
  log_exec sudo cp -R "$DIR/installs/osp-proxy/"* /opt/osp-proxy
  log_exec sudo cp "$DIR/installs/osp-proxy/setup/gunicorn/osp-proxy.service" /etc/systemd/system/osp-proxy.service
  install_osp_proxy_venv
  log_exec sudo systemctl daemon-reload
  log_exec sudo systemctl enable osp-proxy.service
}

upgrade_rtmp() {
  install_prereq
  log_exec sudo cp -rf "$DIR/installs/osp-rtmp/setup/nginx/servers/"*.conf /usr/local/nginx/conf/servers
  log_exec sudo cp -rf "$DIR/installs/osp-rtmp/setup/nginx/services/"*.conf /usr/local/nginx/conf/services
  log_exec sudo cp -R "$DIR/installs/osp-rtmp/"* /opt/osp-rtmp
  log_exec sudo cp "$DIR/installs/osp-rtmp/setup/gunicorn/osp-rtmp.service" /etc/systemd/system/osp-rtmp.service
  install_osp_rtmp_venv
  log_exec sudo systemctl daemon-reload
  log_exec sudo systemctl enable osp-rtmp.service
}

upgrade_ejabberd() {
  log_exec sudo cp -rf "$DIR/installs/ejabberd/setup/auth_osp.py" /opt/ejabberd/conf/auth_osp.py
  log_exec sudo cp -rf "$DIR/installs/ejabberd/setup/nginx/locations/ejabberd.conf" /usr/local/nginx/conf/locations/

  if [[ ! -d /opt/ejabberd/venv ]]; then
    install_ejabberd_venv
  fi

  sed -i 's/^extauth_program:.*$/extauth_program: "\/opt\/ejabberd\/venv\/bin\/python3 \/opt\/ejabberd\/conf\/auth_osp.py"/' /opt/ejabberd/conf/ejabberd.yml
}

upgrade_edge() {
  install_prereq
  log_exec sudo cp -rf "$DIR/installs/osp-edge/setup/nginx/services/osp-edge-rtmp.conf" /usr/local/nginx/conf/services/
  log_exec sudo cp -rf "$DIR/installs/osp-edge/setup/nginx/locations/osp-edge-redirects.conf" /usr/local/nginx/conf/locations/
  log_exec sudo cp -rf "$DIR/installs/osp-edge/setup/nginx/servers/osp-edge-servers.conf" /usr/local/nginx/conf/servers/
}

upgrade_nginxcore() {
  log_exec sudo cp -rf "$DIR/installs/nginx-core/nginx.conf" /usr/local/nginx/conf
}

#######################################################
# Uninstall
#######################################################
uninstall_osp() {
  stop_spinner

  # ── Prominent irreversible warning ────────────────────────────────
  gum style \
    --foreground 196 --border-foreground 196 --border double \
    --align center --width 68 --padding "1 2" --margin "1 2" \
    "⚠  WARNING — THIS CANNOT BE UNDONE  ⚠" \
    "" \
    "This will permanently remove:" \
    "  • OSP systemd services (nginx-osp, osp.target, osp-rtmp," \
    "    osp-proxy, osp-celery*, osp-celery-beat, osp-celery-flower," \
    "    ejabberd) and their unit files in /etc/systemd/system/" \
    "  • /usr/local/nginx" \
    "  • /opt/osp   /opt/osp-rtmp   /opt/osp-proxy" \
    "  • /opt/osp-edge   /opt/ejabberd*" \
    "  • /var/www/{live,live-adapt,stream-thumb,keys,keys-adapt," \
    "    images,videos,pending,ingest}" \
    "  • MariaDB 'osp' database and user" \
    "" \
    "Only OSP-installed services and files are touched." \
    "Your MariaDB install itself will NOT be removed." \
    "Backups are your responsibility."

  # ── Typed confirmation — must type UNINSTALL exactly ──────────────
  local confirm
  confirm=$(ask_input "Type UNINSTALL to confirm" "Confirm destructive action") || true
  if [[ "${confirm:-}" != "UNINSTALL" ]]; then
    echo ""
    echo "  Uninstall cancelled."
    sleep 2
    return
  fi

  # ── Stop and disable all OSP services ────────────────────────────
  local services=(
    nginx-osp
    "osp.target"
    osp-rtmp
    osp-proxy
    osp-celery
    osp-celery-beat
    osp-celery-flower
    ejabberd
  )

  start_spinner "Stopping OSP services..."
  for svc in "${services[@]}"; do
    log_step "Stopping and disabling $svc..."
    sudo systemctl stop "$svc"    >> "$OSPLOG" 2>&1 || true
    sudo systemctl disable "$svc" >> "$OSPLOG" 2>&1 || true
  done

  # ── Remove systemd unit files ──────────────────────────────────────
  log_step "Removing systemd unit files..."
  local units=(
    /etc/systemd/system/nginx-osp.service
    /etc/systemd/system/osp.target
    /etc/systemd/system/"osp-worker@.service"
    /etc/systemd/system/osp-rtmp.service
    /etc/systemd/system/osp-proxy.service
    /etc/systemd/system/osp-celery.service
    /etc/systemd/system/osp-celery-beat.service
    /etc/systemd/system/osp-celery-flower.service
    /etc/systemd/system/ejabberd.service
  )
  for unit in "${units[@]}"; do
    sudo rm -f "$unit" >> "$OSPLOG" 2>&1 || true
  done
  sudo systemctl daemon-reload >> "$OSPLOG" 2>&1 || true
  sudo systemctl reset-failed  >> "$OSPLOG" 2>&1 || true

  # ── Remove application directories ────────────────────────────────
  log_step "Removing application directories..."
  for d in /opt/osp /opt/osp-rtmp /opt/osp-proxy /opt/osp-edge /usr/local/nginx; do
    sudo rm -rf "$d" >> "$OSPLOG" 2>&1 || true
  done

  log_step "Removing ejabberd..."
  sudo find /opt -maxdepth 1 -name 'ejabberd*' -exec rm -rf {} + >> "$OSPLOG" 2>&1 || true

  # ── Remove web / media directories ────────────────────────────────
  log_step "Removing web directories..."
  # All OSP-created subdirectories under /var/www
  local www_dirs=(
    live live-adapt stream-thumb
    keys keys-adapt
    images videos
    pending ingest
  )
  for d in "${www_dirs[@]}"; do
    sudo rm -rf "/var/www/$d" >> "$OSPLOG" 2>&1 || true
  done
  # Also cover distro-specific web_root if different (e.g. Arch: /srv/http)
  if [[ "$web_root" != "/var/www" ]]; then
    for d in "${www_dirs[@]}"; do
      sudo rm -rf "${web_root:?}/$d" >> "$OSPLOG" 2>&1 || true
    done
  fi

  # ── Remove cache directories ─────────────────────────────────────
  sudo rm -rf /var/cache/nginx/osp_cache_temp >> "$OSPLOG" 2>&1 || true

  # ── Remove logrotate / cron entries ──────────────────────────────
  log_step "Removing logrotate and cron entries..."
  sudo rm -f /etc/logrotate.d/osp >> "$OSPLOG" 2>&1 || true
  ( crontab -l 2>/dev/null | grep -v 'osp' | crontab - ) >> "$OSPLOG" 2>&1 || true

  # ── Remove celery default configs ────────────────────────────────
  sudo rm -f /etc/default/celery /etc/default/celery-beat /etc/default/celery-flower >> "$OSPLOG" 2>&1 || true

  # ── Drop MariaDB osp database and user ───────────────────────────
  log_step "Dropping MariaDB 'osp' database and user..."
  sudo mysql >> "$OSPLOG" 2>&1 <<'SQL' || true
DROP DATABASE IF EXISTS osp;
DROP USER IF EXISTS 'osp'@'localhost';
FLUSH PRIVILEGES;
SQL

  stop_spinner
  show_result "Uninstall Complete" \
    "All OSP components have been removed." \
    "" \
    "You may also want to:" \
    "  sudo apt remove --purge redis mariadb-server" \
    "" \
    "Full log: ${OSPLOG}"
}

#######################################################
# Overwrite Warning
#######################################################
config_overwrite_warning_dialog() {
  if ! ask_confirm "If you have existing local installations of Nginx and MariaDB, they will be replaced/modified during the OSP single-server installation. Proceed?"; then
    echo "Program terminated."
    exit 0
  fi
}

config_overwrite_warning_cli() {
  echo "If you have existing local installations of Nginx and MariaDB,"
  echo "they will be replaced/modified during the OSP single-server installation."
  echo ""
  read -rp "Do you want to proceed? (Enter 'YES' to proceed, or anything else to abort)  " read_input
  if [[ "$read_input" != "YES" ]]; then
    echo "Program terminated."
    exit 0
  fi
}

##########################################################
# Menu System
##########################################################
install_menu() {
  while true; do
    stop_spinner
    clear
    show_header
    local selection
    selection=$(show_menu "Install Components" \
      "Install OSP - Single Server" \
      "Install OSP-Core" \
      "Install OSP-RTMP" \
      "Install OSP-Edge" \
      "Install OSP-Proxy" \
      "Install eJabberd" \
      "Install Celery Beat" \
      "Install Celery Flower" \
      "← Back" \
    ) || { echo "Program terminated."; exit 0; }

    case "$selection" in
      "Install OSP - Single Server")
        config_overwrite_warning_dialog
        run_with_spinner "Installing Nginx Core..." install_nginx_core
        run_with_spinner "Installing Redis..." install_redis
        run_with_spinner "Installing ejabberd..." install_ejabberd
        run_with_spinner "Installing OSP-RTMP..." install_osp_rtmp
        run_with_spinner "Installing OSP Core..." install_osp
        log_exec sudo cp /opt/osp-rtmp/conf/config.py.dist /opt/osp-rtmp/conf/config.py
        log_exec sudo cp /opt/osp/conf/config.py.dist /opt/osp/conf/config.py
        config_smtp
        run_with_spinner "Setting up Celery..." install_celery
        run_with_spinner "Setting up Celery Beat..." install_celery_beat
        run_with_spinner "Configuring eJabberd admin..." generate_ejabberd_admin
        run_with_spinner "Installing MySQL..." install_mysql
        run_with_spinner "Restarting Nginx Core..." sudo systemctl restart nginx-osp
        run_with_spinner "Starting OSP Core..." sudo systemctl start osp.target
        upgrade_db
        run_with_spinner "Starting OSP-RTMP..." sudo systemctl start osp-rtmp
        run_with_spinner "Starting Celery..." bash -c "
          sudo systemctl start osp-celery &&
          sudo systemctl start osp-celery-beat
        "
        stop_spinner
        show_result "OSP Install Complete" \
          "OSP has been installed successfully!" \
          "" \
          "Visit http://YOUR-FQDN to configure OSP." \
          "" \
          "Install log: ${OSPLOG}"
        ;;
      "Install OSP-Core")
        run_with_spinner "Installing Nginx Core..." install_nginx_core
        run_with_spinner "Installing OSP Core..." install_osp
        install_celery
        run_with_spinner "Restarting Nginx Core..." sudo systemctl restart nginx-osp
        show_result "Install Complete" "OSP-Core installation completed!\n\nInstall log: ${OSPLOG}"
        ;;
      "Install OSP-RTMP")
        run_with_spinner "Installing Nginx Core..." install_nginx_core
        run_with_spinner "Installing OSP-RTMP..." install_osp_rtmp
        run_with_spinner "Restarting Nginx Core..." sudo systemctl restart nginx-osp
        show_result "Install Complete" "OSP-RTMP installation completed!\n\nInstall log: ${OSPLOG}"
        ;;
      "Install OSP-Edge")
        run_with_spinner "Installing Nginx Core..." install_nginx_core
        install_osp_edge
        run_with_spinner "Restarting Nginx Core..." sudo systemctl restart nginx-osp
        show_result "Install Complete" "OSP-Edge installation completed!\n\nInstall log: ${OSPLOG}"
        ;;
      "Install OSP-Proxy")
        run_with_spinner "Installing Nginx Core..." install_nginx_core
        run_with_spinner "Installing Redis..." install_redis
        install_osp_proxy
        run_with_spinner "Restarting Nginx Core..." sudo systemctl restart nginx-osp
        show_result "Install Complete" "OSP-Proxy installation completed!\n\nInstall log: ${OSPLOG}"
        ;;
      "Install eJabberd")
        run_with_spinner "Installing Nginx Core..." install_nginx_core
        run_with_spinner "Installing ejabberd..." install_ejabberd
        run_with_spinner "Restarting Nginx Core..." sudo systemctl restart nginx-osp
        show_result "Install Complete" "eJabberd installation completed!\n\nInstall log: ${OSPLOG}"
        ;;
      "Install Celery Beat")
        install_celery_beat
        run_with_spinner "Starting Celery..." bash -c "
          sudo systemctl start osp-celery &&
          sudo systemctl start osp-celery-beat
        "
        show_result "Install Complete" "Celery Beat installation completed!"
        ;;
      "Install Celery Flower")
        install_celery_flower
        run_with_spinner "Starting Celery Flower..." bash -c "
          sudo systemctl start osp-celery &&
          sudo systemctl start osp-celery-beat &&
          sudo systemctl start osp-celery-flower
        "
        show_result "Services Started" "Celery, Celery Beat, and Celery Flower are now running."
        ;;
      "← Back")
        return
        ;;
    esac
  done
}

upgrade_menu() {
  while true; do
    stop_spinner
    clear
    show_header
    local selection
    selection=$(show_menu "Upgrade Components" \
      "Upgrade OSP - Single Server" \
      "Upgrade OSP-Core" \
      "Upgrade OSP-RTMP" \
      "Upgrade OSP-Edge" \
      "Upgrade OSP-Proxy" \
      "Upgrade eJabberd" \
      "Upgrade DB" \
      "← Back" \
    ) || { echo "Program terminated."; exit 0; }

    case "$selection" in
      "Upgrade OSP - Single Server")
        upgrade_osp
        upgrade_nginxcore
        upgrade_rtmp
        upgrade_ejabberd
        run_with_spinner "Restarting ejabberd..." sudo systemctl restart ejabberd
        run_with_spinner "Restarting Nginx Core..." sudo systemctl restart nginx-osp
        run_with_spinner "Restarting OSP Core..." sudo systemctl restart osp.target
        upgrade_celery
        upgrade_celery_beat
        run_with_spinner "Restarting OSP-RTMP..." sudo systemctl restart osp-rtmp
        show_result "Upgrade Complete" "OSP Single Server upgrade completed successfully!"
        ;;
      "Upgrade OSP-Core")
        upgrade_osp
        upgrade_nginxcore
        run_with_spinner "Restarting Nginx Core..." sudo systemctl restart nginx-osp
        run_with_spinner "Restarting OSP Core..." sudo systemctl restart osp.target
        upgrade_celery
        show_result "Upgrade Complete" "OSP Core upgrade completed!"
        ;;
      "Upgrade OSP-RTMP")
        upgrade_nginxcore
        upgrade_rtmp
        run_with_spinner "Restarting Nginx Core..." sudo systemctl restart nginx-osp
        run_with_spinner "Restarting OSP-RTMP..." sudo systemctl restart osp-rtmp
        show_result "Upgrade Complete" "OSP-RTMP upgrade completed!"
        ;;
      "Upgrade OSP-Edge")
        upgrade_nginxcore
        upgrade_edge
        run_with_spinner "Restarting Nginx Core..." sudo systemctl restart nginx-osp
        show_result "Upgrade Complete" "OSP-Edge upgrade completed!"
        ;;
      "Upgrade OSP-Proxy")
        upgrade_proxy
        run_with_spinner "Restarting OSP-Proxy..." sudo systemctl restart osp-proxy
        show_result "Upgrade Complete" "OSP-Proxy upgrade completed!"
        ;;
      "Upgrade eJabberd")
        upgrade_nginxcore
        upgrade_ejabberd
        run_with_spinner "Restarting ejabberd..." sudo systemctl restart ejabberd
        run_with_spinner "Restarting Nginx Core..." sudo systemctl restart nginx-osp
        show_result "Upgrade Complete" "eJabberd upgrade completed!\nNote: Edit /opt/ejabberd/conf/auth_osp.py if needed."
        ;;
      "Upgrade DB")
        upgrade_db
        show_result "Upgrade Complete" "Database upgrade completed!"
        ;;
      "← Back")
        return
        ;;
    esac
  done
}

##########################################################
# Main Script Execution
##########################################################
if [[ $# -eq 0 ]]; then
  # Interactive TUI mode
  while true; do
    stop_spinner
    clear
    show_header
    selection=$(show_menu "Main Menu" \
      "Install..." \
      "Upgrade..." \
      "Reset Nginx Configuration" \
      "Reset eJabberd Configuration" \
      "Recreate eJabberd Admin Account" \
      "Uninstall..." \
      "Exit" \
    ) || { clear; echo "Program terminated."; exit 0; }

    case "$selection" in
      "Install...")
        install_menu
        ;;
      "Upgrade...")
        upgrade_menu
        ;;
      "Reset Nginx Configuration")
        reset_nginx
        show_result "Reset Complete" \
          "Nginx configuration has been reset.\nBackup stored at /tmp/nginxbak/"
        ;;
      "Reset eJabberd Configuration")
        reset_ejabberd
        show_result "Reset Complete" "eJabberd has been reset and OSP has been restarted."
        ;;
      "Recreate eJabberd Admin Account")
        generate_ejabberd_admin
        show_result "Complete" "eJabberd admin account has been recreated."
        ;;
      "Uninstall...")
        uninstall_osp
        ;;
      "Exit")
        clear
        echo "Goodbye!"
        exit 0
        ;;
    esac
  done
else
  # CLI mode
  case "$1" in
    help)
      gum style --foreground 212 --border-foreground 99 --border rounded \
        --padding "1 2" --margin "1 0" \
        "OSP Control Script v${OSP_VERSION}" "" \
        "Usage: osp-config.sh [command] [component]" "" \
        "Commands:" \
        "  help      Show this help" \
        "  install   Install components (osp, osp-core, nginx, rtmp, edge, proxy, ejabberd)" \
        "  restart   Restart components (osp, osp-core, nginx, rtmp, ejabberd)" \
        "  upgrade   Upgrade components (osp, osp-core, rtmp, ejabberd, db)" \
        "  reset     Reset components  (nginx, ejabberd)"
      ;;
    install)
      case "${2:-}" in
        osp)
          config_overwrite_warning_cli
          install_nginx_core
          install_redis
          install_ejabberd
          install_osp_rtmp
          install_osp
          log_exec sudo cp /opt/osp-rtmp/conf/config.py.dist /opt/osp-rtmp/conf/config.py
          log_exec sudo cp /opt/osp/conf/config.py.dist /opt/osp/conf/config.py
          generate_ejabberd_admin
          install_mysql
          log_exec sudo systemctl restart nginx-osp
          log_exec sudo systemctl start osp.target
          log_exec sudo systemctl start osp-rtmp
          ;;
        nginx)    install_nginx_core ;;
        rtmp)     install_nginx_core; install_osp_rtmp ;;
        proxy)    install_nginx_core; install_osp_proxy ;;
        edge)     install_nginx_core; install_osp_edge ;;
        ejabberd) install_nginx_core; install_ejabberd ;;
        osp-core) install_nginx_core; install_osp ;;
        *)        echo "Unknown install target: ${2:-}. Run 'osp-config.sh help' for usage." ;;
      esac
      ;;
    restart)
      case "${2:-}" in
        osp)
          log_exec sudo systemctl restart ejabberd
          log_exec sudo systemctl restart nginx-osp
          log_exec sudo systemctl restart osp-rtmp
          log_exec sudo systemctl restart osp.target
          ;;
        osp-core) log_exec sudo systemctl restart osp.target ;;
        nginx)    log_exec sudo systemctl restart nginx-osp ;;
        rtmp)     log_exec sudo systemctl restart osp-rtmp ;;
        ejabberd) log_exec sudo systemctl restart ejabberd ;;
        *)        echo "Unknown restart target: ${2:-}. Run 'osp-config.sh help' for usage." ;;
      esac
      ;;
    upgrade)
      case "${2:-}" in
        osp)
          upgrade_osp
          upgrade_nginxcore
          upgrade_rtmp
          upgrade_ejabberd
          log_exec sudo systemctl restart ejabberd
          log_exec sudo systemctl restart nginx-osp
          log_exec sudo systemctl restart osp.target
          upgrade_celery
          upgrade_celery_beat
          log_exec sudo systemctl restart osp-rtmp
          ;;
        osp-core) upgrade_osp; log_exec sudo systemctl restart osp.target ;;
        rtmp)     upgrade_rtmp ;;
        ejabberd) upgrade_ejabberd ;;
        db)       upgrade_db ;;
        *)        echo "Unknown upgrade target: ${2:-}. Run 'osp-config.sh help' for usage." ;;
      esac
      ;;
    reset)
      case "${2:-}" in
        nginx)    reset_nginx ;;
        ejabberd) reset_ejabberd ;;
        *)        echo "Unknown reset target: ${2:-}. Run 'osp-config.sh help' for usage." ;;
      esac
      ;;
    *)
      echo "Unknown command: $1. Run 'osp-config.sh help' for usage."
      ;;
  esac
fi
