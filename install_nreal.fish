#!/usr/bin/env fish

# Function to handle errors
function on_error
    echo -e "\e[1;31m[ERROR]\e[0m An error occurred. Exiting."
    exit 1
end

# Logging function
function log
    echo -e "\e[1;32m[INFO]\e[0m $argv"
end

function error
    echo -e "\e[1;31m[ERROR]\e[0m $argv" >&2
    exit 1
end

# Ensure sudo access, prompt for password if needed
if not sudo -n true 2>/dev/null
    log "🔑 Sudo access is required. Enter your password:"
    if not sudo -v
        error "You need sudo privileges to install the driver."
    end
end

# Detect package manager
if command -v pacman >/dev/null
    set PKG_MANAGER "pacman"
    set INSTALL_CMD "sudo pacman -S --needed --noconfirm"
else if command -v apt >/dev/null
    set PKG_MANAGER "apt"
    set INSTALL_CMD "sudo apt install -y"
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
    error "Your desktop environment ($DESKTOP_ENV) does not support virtual screens. Exiting."
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

# Install system dependencies (only if missing)
log "Installing system dependencies..."
if test "$PKG_MANAGER" = "pacman"
    set DEPENDENCIES git cmake make base-devel libusb json-c python python-pip python-pipx
else
    set DEPENDENCIES git cmake make gcc g++ libusb-1.0-0-dev libjson-c-dev python3 python3-pip python3-venv
end

for package in $DEPENDENCIES
    if not is_installed $package
        log "Installing $package..."
        eval "$INSTALL_CMD $package" || on_error
    else
        log "✅ $package is already installed. Skipping."
    end
end

# Install the correct display tool based on desktop environment
if test "$DESKTOP_ENV" = "kde"
    log "KDE detected: Using system `kscreen-doctor` (part of plasma-workspace)."
    set DISPLAY_TOOL ""
else
    set DISPLAY_TOOL "wlr-randr"
end

log "Installing display tools (wf-recorder)..."
set WAYLAND_TOOLS wf-recorder qt5-tools $DISPLAY_TOOL

for tool in $WAYLAND_TOOLS
    if test -n "$tool"  # Only install if tool is set
        if not is_installed $tool
            log "Installing $tool..."
            eval "$INSTALL_CMD $tool" || on_error
        else
            log "✅ $tool is already installed. Skipping."
        end
    end
end

# Set up Python Virtual Environment (venv) Without Activation
log "Setting up a Python virtual environment..."
set VENV_DIR "$HOME/nreal_env"

if test -d "$VENV_DIR"
    log "Existing virtual environment found. Updating dependencies..."
else
    python -m venv "$VENV_DIR" || on_error
    log "✅ Virtual environment created at $VENV_DIR"
end

# Install Python packages without activating venv (fix for PEP 668)
log "Installing Python packages..."
"$VENV_DIR/bin/python" -m pip install --upgrade pip numpy pillow pygame || on_error

# Add virtual environment binaries to Fish path
set -x PATH $VENV_DIR/bin $PATH

log "✅ Python dependencies installed."

# Clone and build the Nreal Air Linux Driver
log "Cloning Nreal Air Linux Driver..."
if test -d "nrealAirLinuxDriver"
    log "Driver directory found. Pulling latest updates..."
    cd nrealAirLinuxDriver
    git pull || on_error
else
    git clone --recursive https://gitlab.com/TheJackiMonster/nrealAirLinuxDriver.git || on_error
    cd nrealAirLinuxDriver
end

# Ensure submodules are initialized and updated
log "Updating Git submodules..."
git submodule update --init --recursive || on_error

log "Building the driver..."
mkdir -p build
cd build
cmake .. || on_error
make -j (nproc) || on_error

# Fix: Manually install the driver (since there's no 'make install' target)
log "Manually installing the XREAL driver..."
sudo cp xrealAirLinuxDriver /usr/local/bin/nrealAirLinuxDriver || on_error
sudo chmod +x /usr/local/bin/nrealAirLinuxDriver || on_error

log "✅ XREAL driver installed successfully!"

# Improved device detection (XREAL instead of Nreal)
set DEVICE_ID (lsusb | grep -i "XREAL" | awk '{print $6}' | sed 's/:/ /')

if test -z "$DEVICE_ID"
    log "⚠️ XREAL glasses not detected. Trying again in 5 seconds..."
    sleep 5
    set DEVICE_ID (lsusb | grep -i "XREAL" | awk '{print $6}' | sed 's/:/ /')
end

if test -z "$DEVICE_ID"
    error "❌ XREAL device still not found! Try unplugging and reconnecting the glasses."
end

# Extract vendor and product ID
set ID_VENDOR (echo $DEVICE_ID | awk '{print $1}')
set ID_PRODUCT (echo $DEVICE_ID | awk '{print $2}')

# Update udev rules to ensure proper USB permissions
echo "SUBSYSTEM==\"usb\", ATTR{idVendor}==\"$ID_VENDOR\", ATTR{idProduct}==\"$ID_PRODUCT\", MODE=\"0666\"" | sudo tee /etc/udev/rules.d/99-xreal.rules

sudo udevadm control --reload-rules && sudo udevadm trigger

log "✅ USB permissions set. Replug your XREAL glasses."

# Check if driver works (✅ Fixed missing `end`)
log "Testing if the driver works..."
if /usr/local/bin/nrealAirLinuxDriver --help >/dev/null 2>&1
    log "✅ XREAL driver installed successfully!"
else
    error "Something went wrong. Try rebooting and run 'nrealAirLinuxDriver' manually."
end

# Ensure we can find `main.py`
set SCRIPT_DIR (pwd)

log "✅ Installation complete!"
if test -f "$SCRIPT_DIR/main.py"
    log "To run main.py, use:"
    log "  ~/nreal_env/bin/python3 $SCRIPT_DIR/main.py"
else
    error "Could not find main.py! Make sure you are in the correct directory."
end
