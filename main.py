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

# Ensure the FIFO (Named Pipe) Exists for Screen Capture
if not os.path.exists(FIFO_PATH):
    os.mkfifo(FIFO_PATH)

# Detect Wayland compositor
compositor = os.environ.get("XDG_CURRENT_DESKTOP", "").lower()

# Function to check if a command exists
def command_exists(cmd):
    return shutil.which(cmd) is not None

# Setup Virtual Displays
def setup_virtual_displays():
    logging.info("🖥️ Setting up virtual monitors...")

    if not command_exists("wlr-randr"):
        logging.error("❌ `wlr-randr` not found! Install it first.")
        exit(1)

    subprocess.run(["wlr-randr", "--output", "Virtual-1", "--mode", "1920x1080", "--pos", "1920,0"])
    subprocess.run(["wlr-randr", "--output", "Virtual-2", "--mode", "1920x1080", "--pos", "3840,0"])

    logging.info("✅ Virtual monitors created.")

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
setup_virtual_displays()
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

            # Apply smoothing to avoid jitter
            yaw = previous_yaw * (1 - SMOOTHING_FACTOR) + yaw * SMOOTHING_FACTOR

            # Debounce to prevent excessive updates
            if abs(yaw - previous_yaw) < YAW_THRESHOLD or time.time() - last_update_time < SWITCH_DELAY:
                continue

            previous_yaw = yaw
            last_update_time = time.time()

            normed_yaw_angle = translate(yaw, left_yaw_value, right_yaw_value, -1, 1)
            normed_yaw_angle = max(-1, min(1, normed_yaw_angle))  # Clamp values between -1 and 1

            # Adjust screen slicing based on head movement
            if normed_yaw_angle < 0:
                img_left_mon = np.array(frame[:, :SCREEN_WIDTH, :])
                img_center_mon = np.array(frame[:, SCREEN_WIDTH:, :])
                sliced_img_left_mon = img_left_mon[:, int((1 - abs(normed_yaw_angle)) * SCREEN_WIDTH):, :]
                sliced_img_center_mon = img_center_mon[:, :int((1 - abs(normed_yaw_angle)) * SCREEN_WIDTH), :]
                img = np.concatenate((sliced_img_left_mon, sliced_img_center_mon), axis=1)
            else:
                img_right_mon = np.array(frame[:, :SCREEN_WIDTH, :])
                img_center_mon = np.array(frame[:, SCREEN_WIDTH:, :])
                sliced_img_right_mon = img_right_mon[:, :int(abs(normed_yaw_angle) * SCREEN_WIDTH), :]
                sliced_img_center_mon = img_center_mon[:, int(abs(normed_yaw_angle) * SCREEN_WIDTH):, :]
                img = np.concatenate((sliced_img_center_mon, sliced_img_right_mon), axis=1)

            # Convert NumPy Image to Pygame Surface
            surface = pygame.surfarray.make_surface(img)

            # Display in Nreal Glasses
            screen.blit(surface, (0, 0))
            pygame.display.update()

            # Handle Quit Event
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    subprocess.run(["pkill", "wf-recorder"])  # Stop screen capture
                    exit(0)

        except Exception as e:
            logging.error(f"Couldn't parse IMU values: {e}")
