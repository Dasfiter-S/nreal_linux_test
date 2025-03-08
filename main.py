import subprocess
import threading
import collections
import time
import numpy as np
import os
import logging
import shutil
import pygame  # SDL-based rendering for Wayland
from PIL import Image
import re
import atexit

logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")

SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080
NUM_INPUT_SCREENS = 2
FIFO_PATH = "/tmp/screen_capture"
SMOOTHING_FACTOR = 0.2  # Controls how smoothly the screen transitions
YAW_THRESHOLD = 5  # Minimum yaw difference to update screen
SWITCH_DELAY = 0.3  # Prevents excessive updates
previous_yaw = 0
last_update_time = time.time()

DESKTOP_ENV = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()

def command_exists(cmd):
    return shutil.which(cmd) is not None

def find_nreal_driver():
    possible_paths = [
        "/usr/local/bin/nrealAirLinuxDriver",  # System-wide install
        os.path.expanduser("~/nrealAirLinuxDriver/build/nrealAirLinuxDriver"),  # User build directory
    ]

    for path in possible_paths:
        if os.path.exists(path) and os.access(path, os.X_OK):
            logging.info(f"✅ Found Nreal driver at {path}")
            return path

    logging.error("❌ Nreal Air Linux Driver not found! Make sure it is installed.")
    exit(1)

def start_imu_driver():
    driver_path = find_nreal_driver()
    process = subprocess.Popen(
        driver_path,
        stdout=subprocess.PIPE,
        universal_newlines=True,
    )
    if process.poll() is not None:
        logging.error("❌ Failed to start Nreal Air Linux Driver!")
        exit(1)
    return process

def get_connected_displays():
    """
    Detects the number of connected physical and virtual displays.
    Uses `kscreen-doctor` for KDE, `wlr-randr` for wlroots, and `xrandr` as a fallback.
    """
    try:
        if DESKTOP_ENV == "kde" and command_exists("kscreen-doctor"):
            output = subprocess.run(["kscreen-doctor"], capture_output=True, text=True).stdout
        elif command_exists("wlr-randr"):
            output = subprocess.run(["wlr-randr"], capture_output=True, text=True).stdout
        elif command_exists("xrandr"):
            output = subprocess.run(["xrandr"], capture_output=True, text=True).stdout
        else:
            logging.error("❌ No display detection tool found (kscreen-doctor, wlr-randr, or xrandr).")
            return 0

        # Count lines with "connected" but ignore "disconnected" outputs
        connected = sum(1 for line in output.split("\n") if " connected" in line.lower() and "disconnected" not in line.lower())

        logging.info(f"🖥️ Detected {connected} connected displays.")
        if connected == 0:
            logging.error("❌ No connected displays detected! Ensure your monitors are connected and try again.")
            return 0
        return connected
    except FileNotFoundError as e:
        logging.error(f"❌ Display detection command failed: {e}")
        return 0


def add_virtual_screens():
    logging.info("🖥️ Adding virtual screens...")
    connected_displays = get_connected_displays()

    if connected_displays >= 3:
        logging.info("⚠️ You already have 3 physical monitors. Virtual screens will be added without modifying them.")

    if DESKTOP_ENV == "kde":
        if command_exists("kscreen-doctor"):
            subprocess.run(["kscreen-doctor", "output.Virtual-1.position.5760,0"])
            subprocess.run(["kscreen-doctor", "output.Virtual-2.position.7680,0"])
        else:
            logging.error("❌ kscreen-doctor not found! Ensure KDE Plasma has `plasma-workspace` installed.")
            exit(1)
    else:
        if command_exists("wlr-randr"):
            subprocess.run(["wlr-randr", "--output", "Virtual-1", "--mode", "1920x1080", "--pos", "5760,0"])
            subprocess.run(["wlr-randr", "--output", "Virtual-2", "--mode", "1920x1080", "--pos", "7680,0"])
        else:
            logging.error("❌ wlr-randr not found! Ensure you are using a wlroots-based compositor (Hyprland, Sway).")
            exit(1)
    logging.info("✅ Virtual screens added.")

def remove_virtual_screens():
    logging.info("🖥️ Removing virtual screens...")
    if DESKTOP_ENV == "kde":
        subprocess.run(["kscreen-doctor", "output.Virtual-1.disable"])
        subprocess.run(["kscreen-doctor", "output.Virtual-2.disable"])
    else:
        subprocess.run(["wlr-randr", "--output", "Virtual-1", "--off"])
        subprocess.run(["wlr-randr", "--output", "Virtual-2", "--off"])
    logging.info("✅ Virtual screens removed.")

atexit.register(remove_virtual_screens)

if not os.path.exists(FIFO_PATH):
    os.mkfifo(FIFO_PATH)

def start_screen_capture():
    logging.info("🎥 Starting screen capture...")
    process = subprocess.Popen(["wf-recorder", "-o", "HDMI-A-1", "-g", "1920x1080+0+0", "-f", FIFO_PATH])
    time.sleep(2)
    if process.poll() is not None:
        logging.error("❌ `wf-recorder` failed to start! Check if Wayland is running and try again.")
        exit(1)

# IMU Data Handling
q = collections.deque(maxlen=1)

def read_output(process, append):
    for stdout_line in iter(process.stdout.readline, ""):
        append(stdout_line)

def get_pitch_roll_yaw(input_str):
    try:
        match = re.search(r"Yaw:\s*(-?\d+\.\d+)", input_str)
        if match:
            return float(match.group(1))
    except Exception as e:
        logging.error(f"Error parsing IMU data: {e}")
    return None

# Setup Pygame for Rendering
pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))

# Setup Virtual Displays and Start Everything
add_virtual_screens()
start_screen_capture()
imu_process = start_imu_driver()

t = threading.Thread(target=read_output, args=(imu_process, q.append))
t.daemon = True
t.start()

logging.info("🧭 Calibrating head position...")
start_time = time.time()
initial_yaw_value = None

while time.time() - start_time < 10:
    if q:
        initial_yaw_value = get_pitch_roll_yaw("".join(q))
        if initial_yaw_value is not None:
            logging.info(f"✅ Initial yaw value: {initial_yaw_value:.2f}")
            break

# Main Loop
while True:
    with open(FIFO_PATH, "rb") as fifo:
        raw_image = fifo.read()

    frame = np.array(Image.frombytes("RGB", (SCREEN_WIDTH * NUM_INPUT_SCREENS, SCREEN_HEIGHT), raw_image))

    if q:
        try:
            yaw = get_pitch_roll_yaw("".join(q))
            if yaw is None:
                continue

            # Apply smoothing
            yaw = previous_yaw * (1 - SMOOTHING_FACTOR) + yaw * SMOOTHING_FACTOR

            # Debounce updates
            if abs(yaw - previous_yaw) < YAW_THRESHOLD or time.time() - last_update_time < SWITCH_DELAY:
                continue

            previous_yaw = yaw
            last_update_time = time.time()

            surface = pygame.surfarray.make_surface(frame)

            # Display in Nreal Glasses
            screen.blit(surface, (0, 0))
            pygame.display.update()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    subprocess.run(["pkill", "wf-recorder"])
                    exit(0)

        except Exception as e:
            logging.error(f"Couldn't parse IMU values: {e}")
