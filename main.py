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

# Logging setup
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")

# Constants
IMU_PROCESS = "./nrealAirLinuxDriver"
SCREEN_WIDTH = 1920
SCREEN_HEIGHT = 1080
NUM_INPUT_SCREENS = 2
FIFO_PATH = "/tmp/screen_capture"
SMOOTHING_FACTOR = 0.2  # Controls how smoothly the screen transitions
YAW_THRESHOLD = 5  # Minimum yaw difference to update screen
SWITCH_DELAY = 0.3  # Prevents excessive updates
previous_yaw = 0
last_update_time = time.time()

# Detect Wayland compositor
DESKTOP_ENV = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()

# Function to check if a command exists
def command_exists(cmd):
    return shutil.which(cmd) is not None

# Function to get number of connected displays
def get_connected_displays():
    if DESKTOP_ENV == "kde":
        output = subprocess.run(["kscreen-doctor"], capture_output=True, text=True).stdout
        return output.count("connected")
    else:
        output = subprocess.run(["wlr-randr"], capture_output=True, text=True).stdout
        return output.count("connected")

# Function to add virtual screens dynamically
def add_virtual_screens():
    logging.info("🖥️ Adding virtual screens...")
    connected_displays = get_connected_displays()
    logging.info(f"Detected {connected_displays} connected displays.")

    if connected_displays >= 3:
        logging.info("⚠️ You already have 3 physical monitors. Virtual screens will be added without modifying them.")

    if DESKTOP_ENV == "kde":
        if command_exists("kscreen-doctor"):
            subprocess.run(["kscreen-doctor", "output.Virtual-1.position.5760,0"])
            subprocess.run(["kscreen-doctor", "output.Virtual-2.position.7680,0"])
        else:
            logging.error("❌ kscreen-doctor not found! Ensure KDE Plasma has `kscreen-doctor` installed.")
            exit(1)
    else:
        if command_exists("wlr-randr"):
            subprocess.run(["wlr-randr", "--output", "Virtual-1", "--mode", "1920x1080", "--pos", "5760,0"])
            subprocess.run(["wlr-randr", "--output", "Virtual-2", "--mode", "1920x1080", "--pos", "7680,0"])
        else:
            logging.error("❌ wlr-randr not found! Ensure you are using a wlroots-based compositor (Hyprland, Sway).")
            exit(1)
    logging.info("✅ Virtual screens added.")

# Function to remove virtual screens when the script exits
def remove_virtual_screens():
    logging.info("🖥️ Removing virtual screens...")
    if DESKTOP_ENV == "kde":
        subprocess.run(["kscreen-doctor", "output.Virtual-1.disable"])
        subprocess.run(["kscreen-doctor", "output.Virtual-2.disable"])
    else:
        subprocess.run(["wlr-randr", "--output", "Virtual-1", "--off"])
        subprocess.run(["wlr-randr", "--output", "Virtual-2", "--off"])
    logging.info("✅ Virtual screens removed.")

# Ensure virtual screens are removed when the script exits
import atexit
atexit.register(remove_virtual_screens)

# Ensure the FIFO (Named Pipe) Exists for Screen Capture
if not os.path.exists(FIFO_PATH):
    os.mkfifo(FIFO_PATH)

# Start Screen Capture Using `wf-recorder`
def start_screen_capture():
    logging.info("Starting screen capture...")
    subprocess.Popen(["wf-recorder", "-o", "HDMI-A-1", "-g", "1920x1080+0+0", "-f", FIFO_PATH])

# Start Nreal Air Driver
def start_imu_driver():
    process = subprocess.Popen(
        IMU_PROCESS,
        stdout=subprocess.PIPE,
        universal_newlines=True,
        cwd="/home/nrealAirLinuxDriver/build/",
    )
    return process

# Function to Read IMU Output
q = collections.deque(maxlen=1)

def read_output(process, append):
    for stdout_line in iter(process.stdout.readline, ""):
        append(stdout_line)

# Function to parse IMU data
def get_pitch_roll_yaw(input_str):
    try:
        match = re.search(r"Yaw:\s*(-?\d+\.\d+)", input_str)
        if match:
            yaw = float(match.group(1))
            return yaw
    except Exception as e:
        logging.error(f"Error parsing IMU data: {e}")
    return None

# Setup Pygame for Rendering
pygame.init()
screen = pygame.display.set_mode((SCREEN_WIDTH, SCREEN_HEIGHT))

# Setup Virtual Displays and Start Screen Capture
add_virtual_screens()
start_screen_capture()
imu_process = start_imu_driver()

t = threading.Thread(target=read_output, args=(imu_process, q.append))
t.daemon = True
t.start()

# Calibration
logging.info("Calibrating head position...")
start_time = time.time()
initial_yaw_value = None

while time.time() - start_time < 10:
    if q:
        initial_yaw_value = get_pitch_roll_yaw("".join(q))
        if initial_yaw_value is not None:
            logging.info(f"Initial yaw value: {initial_yaw_value:.2f}")
            break

# Define left and right boundaries based on user calibration
left_yaw_value = float(input("Look at the leftmost screen and press enter: "))
right_yaw_value = float(input("Look at the rightmost screen and press enter: "))

# Function to normalize yaw movement
def translate(value, leftMin, leftMax, rightMin, rightMax):
    leftSpan = leftMax - leftMin
    rightSpan = rightMax - rightMin
    valueScaled = float(value - leftMin) / float(leftSpan)
    return rightMin + (valueScaled * rightSpan)

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

            yaw = previous_yaw * (1 - SMOOTHING_FACTOR) + yaw * SMOOTHING_FACTOR

            if abs(yaw - previous_yaw) < YAW_THRESHOLD or time.time() - last_update_time < SWITCH_DELAY:
                continue

            previous_yaw = yaw
            last_update_time = time.time()

            normed_yaw_angle = translate(yaw, left_yaw_value, right_yaw_value, -1, 1)
            normed_yaw_angle = max(-1, min(1, normed_yaw_angle))

            # Convert NumPy Image to Pygame Surface
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
