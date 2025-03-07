#!/bin/bash

set -e  # Stop script on error

# Logging function
log() {
    echo -e "\e[1;32m[INFO]\e[0m $1"
}

error() {
    echo -e "\e[1;31m[ERROR]\e[0m $1" >&2
    exit 1
}

# Ensure script is not run as root
if [[ "$EUID" -eq 0 ]]; then
    error "Do NOT run this script as root! Just run it as a normal user. It will ask for sudo when needed."
fi

# Ensure sudo access
if ! sudo -v; then
    error "You need sudo privileges to install the driver."
fi

# Detect package manager
if command -v pacman &>/dev/null; then
    PKG_MANAGER="pacman"
    INSTALL_CMD="sudo pacman -S --needed --noconfirm"
    PACKAGE_CHECK="pacman -Q"
elif command -v apt &>/dev/null; then
    PKG_MANAGER="apt"
    INSTALL_CMD="sudo apt install -y"
    PACKAGE_CHECK="dpkg -l"
else
    error "Unsupported package manager! Use Arch (pacman) or Debian-based (apt)."
fi

# Detect if running on Wayland
if [[ -z "$WAYLAND_DISPLAY" ]]; then
    error "You are not running a Wayland session. This setup only works on Wayland!"
fi

# Detect desktop environment
DESKTOP_ENV=$(echo "$XDG_CURRENT_DESKTOP" | tr '[:upper:]' '[:lower:]')

if [[ "$DESKTOP_ENV" == "gnome" || "$DESKTOP_ENV" == "xfce" || "$DESKTOP_ENV" == "lxqt" ]]; then
    error "Your desktop environment ($DESKTOP_ENV) does not support wlr-randr or wf-recorder. Exiting."
fi

log "✅ Compatible Wayland desktop environment detected: $DESKTOP_ENV"

# Function to check if a package is installed
is_installed() {
    if [[ "$PKG_MANAGER" == "pacman" ]]; then
        pacman -Q "$1" &>/dev/null
    elif [[ "$PKG_MANAGER" == "apt" ]]; then
        dpkg -l | grep -q "^ii  $1 "
    fi
}

# Install system dependencies
log "Installing system dependencies..."
DEPENDENCIES=("git" "cmake" "make" "gcc" "g++" "libusb-1.0-0-dev" "libjson-c-dev" "python3" "python3-pip" "python3-venv")
for package in "${DEPENDENCIES[@]}"; do
    if ! is_installed "$package"; then
        log "Installing $package..."
        $INSTALL_CMD "$package"
    else
        log "✅ $package is already installed. Skipping."
    fi
done

# Install Wayland tools
log "Installing Wayland tools (wlr-randr, wf-recorder)..."
WAYLAND_TOOLS=("wlr-randr" "wf-recorder" "qt5-tools")

for tool in "${WAYLAND_TOOLS[@]}"; do
    if ! is_installed "$tool"; then
        log "Installing $tool..."
        $INSTALL_CMD "$tool"
    else
        log "✅ $tool is already installed. Skipping."
    fi
done

# Ensure required Wayland tools are installed
if ! command -v wlr-randr &>/dev/null; then
    error "wlr-randr is missing! Make sure you are using a wlroots-based Wayland compositor (Hyprland, Sway, etc.)."
fi

if ! command -v wf-recorder &>/dev/null; then
    error "wf-recorder is missing! This is required for screen capture. Exiting."
fi

log "✅ Required Wayland tools installed."

# Set up a Python Virtual Environment (venv)
log "Setting up a Python virtual environment..."
VENV_DIR="$HOME/nreal_env"

if [[ -d "$VENV_DIR" ]]; then
    log "Existing virtual environment found. Updating dependencies..."
else
    python3 -m venv "$VENV_DIR"
    log "✅ Virtual environment created at $VENV_DIR"
fi

# Activate venv and install Python dependencies
source "$VENV_DIR/bin/activate"
log "Installing Python libraries inside venv..."
PYTHON_PACKAGES=("numpy" "pillow" "pygame")

for package in "${PYTHON_PACKAGES[@]}"; do
    if ! pip show "$package" &>/dev/null; then
        log "Installing $package..."
        pip install "$package"
    else
        log "✅ $package is already installed in venv. Skipping."
    fi
done

log "✅ Python dependencies installed inside the virtual environment."

# Clone and build the Nreal Air Linux Driver
log "Cloning Nreal Air Linux Driver..."
if [[ -d "nrealAirLinuxDriver" ]]; then
    log "Driver directory found. Pulling latest updates..."
    cd nrealAirLinuxDriver
    git pull
else
    git clone https://gitlab.com/TheJackiMonster/nrealAirLinuxDriver.git
    cd nrealAirLinuxDriver
fi

log "Building the driver..."
mkdir -p build && cd build
cmake ..
make -j$(nproc)
sudo make install

# Set up USB permissions
log "Configuring USB permissions..."
DEVICE_ID=$(lsusb | grep -i "nreal" | awk '{print $6}' | sed 's/:/ /')

if [[ -z "$DEVICE_ID" ]]; then
    error "Nreal device not found! Ensure the glasses are plugged in."
fi

ID_VENDOR=$(echo $DEVICE_ID | awk '{print $1}')
ID_PRODUCT=$(echo $DEVICE_ID | awk '{print $2}')

echo "SUBSYSTEM==\"usb\", ATTR{idVendor}==\"$ID_VENDOR\", ATTR{idProduct}==\"$ID_PRODUCT\", MODE=\"0666\"" | sudo tee /etc/udev/rules.d/99-nreal.rules

sudo udevadm control --reload-rules && sudo udevadm trigger

log "✅ USB permissions set. Replug your Nreal glasses."

# Check if driver works
log "Testing if the driver works..."
if ./nrealAirLinuxDriver --help &>/dev/null; then
    log "✅ Nreal driver installed successfully!"
else
    error "Something went wrong. Try rebooting and run './nrealAirLinuxDriver' manually."
fi

# Create a named pipe (FIFO) for screen capture
if [[ ! -p /tmp/screen_capture ]]; then
    log "Creating a named pipe (FIFO) for screen capture..."
    mkfifo /tmp/screen_capture
fi

log "✅ Installation complete!"
log "To run main.py, use:"
log "  source $VENV_DIR/bin/activate && python3 main.py"
