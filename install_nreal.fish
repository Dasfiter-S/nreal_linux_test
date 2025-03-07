#!/usr/bin/env fish

# Stop on errors
set -e

# Logging function
function log
    echo -e "\e[1;32m[INFO]\e[0m $argv"
end

function error
    echo -e "\e[1;31m[ERROR]\e[0m $argv" >&2
    exit 1
end

# Ensure script is not run as root
if test (id -u) -eq 0
    error "Do NOT run this script as root! Just run it as a normal user. It will ask for sudo when needed."
end

# Ensure sudo access
if not sudo -v
    error "You need sudo privileges to install the driver."
end

# Detect package manager
if command -v pacman >/dev/null
    set PKG_MANAGER "pacman"
    set INSTALL_CMD "sudo pacman -S --needed --noconfirm"
    set PACKAGE_CHECK "pacman -Q"
else if command -v apt >/dev/null
    set PKG_MANAGER "apt"
    set INSTALL_CMD "sudo apt install -y"
    set PACKAGE_CHECK "dpkg -l"
else
    error "Unsupported package manager! Use Arch (pacman) or Debian-based (apt)."
end

# Detect if running on Wayland
if test -z "$WAYLAND_DISPLAY"
    error "You are not running a Wayland session. This setup only works on Wayland!"
end

# Detect desktop environment
set DESKTOP_ENV (echo "$XDG_CURRENT_DESKTOP" | tr '[:upper:]' '[:lower:]')

if test "$DESKTOP_ENV" = "gnome" -o "$DESKTOP_ENV" = "xfce" -o "$DESKTOP_ENV" = "lxqt"
    error "Your desktop environment ($DESKTOP_ENV) does not support wlr-randr or wf-recorder. Exiting."
end

log "✅ Compatible Wayland desktop environment detected: $DESKTOP_ENV"

# Function to check if a package is installed
function is_installed
    if test "$PKG_MANAGER" = "pacman"
        pacman -Q $argv >/dev/null 2>&1
    else if test "$PKG_MANAGER" = "apt"
        dpkg -l | grep -q "^ii  $argv "
    end
end

# Install system dependencies
log "Installing system dependencies..."
set DEPENDENCIES git cmake make gcc g++ libusb-1.0-0-dev libjson-c-dev python3 python3-pip python3-venv
for package in $DEPENDENCIES
    if not is_installed $package
        log "Installing $package..."
        eval "$INSTALL_CMD $package"
    else
        log "✅ $package is already installed. Skipping."
    end
end

# Install Wayland tools
log "Installing Wayland tools (wlr-randr, wf-recorder)..."
set WAYLAND_TOOLS wlr-randr wf-recorder qt5-tools

for tool in $WAYLAND_TOOLS
    if not is_installed $tool
        log "Installing $tool..."
        eval "$INSTALL_CMD $tool"
    else
        log "✅ $tool is already installed. Skipping."
    end
end

# Ensure required Wayland tools are installed
if not command -v wlr-randr >/dev/null
    error "wlr-randr is missing! Make sure you are using a wlroots-based Wayland compositor (Hyprland, Sway, etc.)."
end

if not command -v wf-recorder >/dev/null
    error "wf-recorder is missing! This is required for screen capture. Exiting."
end

log "✅ Required Wayland tools installed."

# Set up a Python Virtual Environment (venv)
log "Setting up a Python virtual environment..."
set VENV_DIR "$HOME/nreal_env"

if test -d "$VENV_DIR"
    log "Existing virtual environment found. Updating dependencies..."
else
    python3 -m venv "$VENV_DIR"
    log "✅ Virtual environment created at $VENV_DIR"
end

# Activate venv and install Python dependencies
source "$VENV_DIR/bin/activate"
log "Installing Python libraries inside venv..."
set PYTHON_PACKAGES numpy pillow pygame

for package in $PYTHON_PACKAGES
    if not pip show $package >/dev/null 2>&1
        log "Installing $package..."
        pip install $package
    else
        log "✅ $package is already installed in venv. Skipping."
    end
end

log "✅ Python dependencies installed inside the virtual environment."

# Clone and build the Nreal Air Linux Driver
log "Cloning Nreal Air Linux Driver..."
if test -d "nrealAirLinuxDriver"
    log "Driver directory found. Pulling latest updates..."
    cd nrealAirLinuxDriver
    git pull
else
    git clone https://gitlab.com/TheJackiMonster/nrealAirLinuxDriver.git
    cd nrealAirLinuxDriver
end

log "Building the driver..."
mkdir -p build
cd build
cmake ..
make -j(nproc)
sudo make install

# Set up USB permissions
log "Configuring USB permissions..."
set DEVICE_ID (lsusb | grep -i "nreal" | awk '{print $6}' | sed 's/:/ /')

if test -z "$DEVICE_ID"
    error "Nreal device not found! Ensure the glasses are plugged in."
end

set ID_VENDOR (echo $DEVICE_ID | awk '{print $1}')
set ID_PRODUCT (echo $DEVICE_ID | awk '{print $2}')

echo "SUBSYSTEM==\"usb\", ATTR{idVendor}==\"$ID_VENDOR\", ATTR{idProduct}==\"$ID_PRODUCT\", MODE=\"0666\"" | sudo tee /etc/udev/rules.d/99-nreal.rules

sudo udevadm control --reload-rules
sudo udevadm trigger

log "✅ USB permissions set. Replug your Nreal glasses."

# Check if driver works
log "Testing if the driver works..."
if ./nrealAirLinuxDriver --help >/dev/null 2>&1
    log "✅ Nreal driver installed successfully!"
else
    error "Something went wrong. Try rebooting and run './nrealAirLinuxDriver' manually."
end

# Create a named pipe (FIFO) for screen capture
if not test -p /tmp/screen_capture
    log "Creating a named pipe (FIFO) for screen capture..."
    mkfifo /tmp/screen_capture
end

log "✅ Installation complete!"
log "To run main.py, use:"
log "  source $VENV_DIR/bin/activate && python3 main.py"
