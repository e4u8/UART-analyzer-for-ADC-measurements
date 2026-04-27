import serial
import math
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import numpy as np 
import time
from collections import deque

# Running mean accumulators — store ALL samples received, not just the visible window
ch0_all = []
ch1_all = []
rate_window_count = 0
rate_window_start = time.time()
measured_rate_hz  = 0.0
measured_freq_hz  = 0.0   
prev_sample_ch1   = 0.0
zero_cross_samples = []   # stores sample_count value at each crossing
MIDPOINT_MV       = 1600  # midpoint of your 200mV-3000mV signal

# ── Configuration — edit these as needed ──────────────────────────────────────
PORT     = "COM7"    # Change to your current COM port
BAUD     = 115200    # Must match your MCU's baud rate
WINDOW   = 200       # How many samples are visible in the plot at once
CH0_YMAX = 3300      # Expected max mV for CH0 (voltage signal)
CH1_YMAX = 3300      # Expected max mV for CH1 (current signal) — adjust once you know the range
# ──────────────────────────────────────────────────────────────────────────────

# --- Serial connection --------------------------------------------------------
try:
    ser = serial.Serial(PORT, BAUD, timeout=0.1)
    print(f"Connected to {PORT} at {BAUD} baud.")
except serial.SerialException as e:
    print(f"ERROR: Could not open {PORT}. Check the port name and that your MCU is connected.")
    print(f"Details: {e}")
    exit(1)

# --- Data buffers -------------------------------------------------------------
ch0_mv = deque([0.0] * WINDOW, maxlen=WINDOW)
ch1_mv = deque([0.0] * WINDOW, maxlen=WINDOW)

# Live stats computed by the analyzer itself (no longer from MCU)
sample_count = 0
stats = {"ch0_min": 0, "ch0_max": 0, "ch0_rms": 0,
         "ch1_min": 0, "ch1_max": 0, "ch1_rms": 0}

# --- Plot setup --------------------------------------------------------------
fig, (ax0, ax1) = plt.subplots(2, 1, figsize=(13, 7))
fig.suptitle(f"UART ADC Analyzer  —  {PORT} @ {BAUD}", fontsize=13)

line0, = ax0.plot([], [], color="royalblue", linewidth=1.2, label="CH0 mV")
ax0.set_title("CH0 — Voltage Signal")
ax0.set_ylim(-50, CH0_YMAX)
ax0.set_xlim(0, WINDOW)
ax0.set_ylabel("mV")
ax0.axhline(0, color="gray", linewidth=0.5, linestyle="--")
ax0.legend(loc="upper right")

line1, = ax1.plot([], [], color="tomato", linewidth=1.2, label="CH1 mV")
ax1.set_title("CH1 — Current Signal")
ax1.set_ylim(-50, CH1_YMAX)
ax1.set_xlim(0, WINDOW)
ax1.set_ylabel("mV")
ax1.axhline(0, color="gray", linewidth=0.5, linestyle="--")
ax1.legend(loc="upper right")

# Stats text shown at the bottom of the figure 
stats_text = fig.text(
    0.01, 0.01,
    "Waiting for data...",
    fontsize=8, family="monospace", verticalalignment="bottom"
)

# --- Parsing -----------------------------------------------------------------
def parse_line(raw_line: str):
    """
    Expects only the new MCU format: mv_ch0,mv_ch1
    Returns (float, float) or None on any parse failure.
    Silently ignores header/status lines starting with '[' or '*'.
    """
    line = raw_line.strip()
    if not line or line.startswith("[") or line.startswith("*"):
        return None

    parts = line.split(",")
    if len(parts) == 2:
        try:
            return float(parts[0]), float(parts[1])
        except ValueError:
            pass
    return None

# --- Animation update function -----------------------------------------------
def update(frame):
    global sample_count, rate_window_count, rate_window_start
    global measured_rate_hz, measured_freq_hz, prev_sample_ch1

    while ser.in_waiting:
        try:
            raw = ser.readline().decode("utf-8", errors="replace")
            result = parse_line(raw)
            if result:
                mv0, mv1 = result
                ch0_mv.append(mv0)
                ch1_mv.append(mv1)
                # Detect rising zero-crossing (signal crosses midpoint upward)
                if prev_sample_ch1 < MIDPOINT_MV and mv1 >= MIDPOINT_MV:
                    zero_cross_samples.append(sample_count)
                    if len(zero_cross_samples) > 6:
                        zero_cross_samples.pop(0)
                    # Need at least 2 crossings and a valid sample rate to compute frequency
                    if len(zero_cross_samples) >= 2 and measured_rate_hz > 0:
                        gaps = [zero_cross_samples[i+1] - zero_cross_samples[i]
                                for i in range(len(zero_cross_samples)-1)]
                        avg_gap_samples = sum(gaps) / len(gaps)
                        measured_freq_hz = measured_rate_hz / avg_gap_samples

                prev_sample_ch1 = mv1
                ch0_all.append(mv0)   # accumulate for mean
                ch1_all.append(mv1)
                rate_window_count += 1
                now = time.time()
                elapsed = now - rate_window_start
                if elapsed >= 2.0:   # measure over 2 seconds for stability
                    measured_rate_hz  = rate_window_count / elapsed
                    rate_window_count = 0
                    rate_window_start = now

                sample_count += 1
        except Exception as e:
            print(f"Read error: {e}")

    line0.set_data(range(WINDOW), ch0_mv)
    line1.set_data(range(WINDOW), ch1_mv)

    # Compute live stats from the visible window
    if len(ch0_all) > 0:
        c0 = list(ch0_mv)
        c1 = list(ch1_mv)

        # Current value = last received sample
        cur0 = c0[-1]
        cur1 = c1[-1]

        # Running mean over ALL samples since start
        mean0 = sum(ch0_all) / len(ch0_all)
        mean1 = sum(ch1_all) / len(ch1_all)

        # RMS over visible window
        rms0 = math.sqrt(sum(x*x for x in c0) / len(c0))
        rms1 = math.sqrt(sum(x*x for x in c1) / len(c1))

        stats_text.set_text(
            f"samples received: {sample_count}\n"
            f"sample rate: {measured_rate_hz:.1f} Hz\n"
            f"signal freq: {measured_freq_hz:.2f} Hz\n"
            f"[CH0] current={cur0:.1f} mV  mean={mean0:.1f} mV  "
            f"min={min(c0):.0f} mV  max={max(c0):.0f} mV  "
            f"pp={max(c0)-min(c0):.0f} mV  rms={rms0:.1f} mV\n"
            f"[CH1] current={cur1:.1f} mV  mean={mean1:.1f} mV  "
            f"min={min(c1):.0f} mV  max={max(c1):.0f} mV  "
            f"pp={max(c1)-min(c1):.0f} mV  rms={rms1:.1f} mV"
        )

    return line0, line1, stats_text

# --- Run ---------------------------------------------------------------------
ani = animation.FuncAnimation(fig, update, interval=20, blit=False, cache_frame_data=False)
plt.tight_layout(rect=[0, 0.09, 1, 1])

try:
    plt.show()
finally:
    ser.close()
    print("Serial port closed.")