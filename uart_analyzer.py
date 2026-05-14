import serial
import math
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import numpy as np
import time
from collections import deque

# Running mean accumulators
ch0_all = []
ch1_all = []
rate_window_count = 0
rate_window_start = time.time()
measured_rate_hz  = 0.0
measured_freq_hz  = 0.0
prev_sample_ch1   = 0.0
zero_cross_samples = []
MIDPOINT_MV       = 1600

# ── NEW: Temperature/Humidity accumulators ────────────────────────────────────
temp_all     = []   # stores all received temperature values (float °C)
humid_all    = []   # stores all received humidity values (int %)
latest_temp  = None
latest_humid = None
# ─────────────────────────────────────────────────────────────────────────────

# ── Configuration ─────────────────────────────────────────────────────────────
PORT     = "COM7"
BAUD     = 115200
WINDOW   = 200
CH0_YMAX = 3300
CH1_YMAX = 3300
# ─────────────────────────────────────────────────────────────────────────────

try:
    ser = serial.Serial(PORT, BAUD, timeout=0.1)
    print(f"Connected to {PORT} at {BAUD} baud.")
except serial.SerialException as e:
    print(f"ERROR: Could not open {PORT}.\nDetails: {e}")
    exit(1)

ch0_mv = deque([0.0] * WINDOW, maxlen=WINDOW)
ch1_mv = deque([0.0] * WINDOW, maxlen=WINDOW)
sample_count = 0

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

stats_text = fig.text(
    0.01, 0.01,
    "Waiting for data...",
    fontsize=8, family="monospace", verticalalignment="bottom"
)

# ── NEW: Temperature display box in top-right corner ─────────────────────────
temp_text = fig.text(
    0.75, 0.01,
    "Temp: --.-°C   Humidity: --%",
    fontsize=9, family="monospace", verticalalignment="bottom",
    color="white",
    bbox=dict(boxstyle="round,pad=0.4", facecolor="#2a5f2a", edgecolor="green")
)
# ─────────────────────────────────────────────────────────────────────────────

def parse_line(raw_line: str):
    """
    Accepts two formats:
      Old (2 fields): mv_ch0,mv_ch1
      New (4 fields): mv_ch0,mv_ch1,temp_raw,humidity
        where temp_raw = temp_celsius * 10  (e.g. 21.5°C → 215)

    Returns (mv0, mv1, temp_c, humidity) or (mv0, mv1, None, None)
    or None on parse failure.
    """
    line = raw_line.strip()
    if not line or line.startswith("[") or line.startswith("*"):
        return None

    parts = line.split(",")

    # 4-field format (ADC + temperature)
    if len(parts) == 4:
        try:
            mv0      = float(parts[0])
            mv1      = float(parts[1])
            temp_c   = int(parts[2]) / 10.0   # convert back from *10 integer
            humidity = int(parts[3])
            return mv0, mv1, temp_c, humidity
        except ValueError:
            pass

    # 2-field format (ADC only — backwards compatible)
    if len(parts) == 2:
        try:
            return float(parts[0]), float(parts[1]), None, None
        except ValueError:
            pass

    return None

def update(frame):
    global sample_count, rate_window_count, rate_window_start
    global measured_rate_hz, measured_freq_hz, prev_sample_ch1
    global latest_temp, latest_humid

    while ser.in_waiting:
        try:
            raw    = ser.readline().decode("utf-8", errors="replace")
            result = parse_line(raw)
            if result:
                mv0, mv1, temp_c, humidity = result

                ch0_mv.append(mv0)
                ch1_mv.append(mv1)
                ch0_all.append(mv0)
                ch1_all.append(mv1)

                # ── NEW: store temperature if present ─────────────────────────
                if temp_c is not None:
                    latest_temp  = temp_c
                    latest_humid = humidity
                    temp_all.append(temp_c)
                    humid_all.append(humidity)
                # ─────────────────────────────────────────────────────────────

                # Zero-crossing frequency detection (unchanged)
                if prev_sample_ch1 < MIDPOINT_MV and mv1 >= MIDPOINT_MV:
                    zero_cross_samples.append(sample_count)
                    if len(zero_cross_samples) > 12:
                        zero_cross_samples.pop(0)
                    if len(zero_cross_samples) >= 2 and measured_rate_hz > 0:
                        gaps = [zero_cross_samples[i+1] - zero_cross_samples[i]
                                for i in range(len(zero_cross_samples)-1)]
                        avg_gap_samples = sum(gaps) / len(gaps)
                        measured_freq_hz = measured_rate_hz / avg_gap_samples

                prev_sample_ch1 = mv1

                rate_window_count += 1
                now     = time.time()
                elapsed = now - rate_window_start
                if elapsed >= 2.0:
                    measured_rate_hz  = rate_window_count / elapsed
                    rate_window_count = 0
                    rate_window_start = now

                sample_count += 1

        except Exception as e:
            print(f"Read error: {e}")

    line0.set_data(range(WINDOW), ch0_mv)
    line1.set_data(range(WINDOW), ch1_mv)

    if len(ch0_all) > 0:
        c0 = list(ch0_mv)
        c1 = list(ch1_mv)

        cur0  = c0[-1]
        cur1  = c1[-1]
        mean0 = sum(ch0_all) / len(ch0_all)
        mean1 = sum(ch1_all) / len(ch1_all)
        rms0  = math.sqrt(sum(x*x for x in c0) / len(c0))
        rms1  = math.sqrt(sum(x*x for x in c1) / len(c1))

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

        # ── NEW: update temperature display ───────────────────────────────────
        if latest_temp is not None:
            mean_temp  = sum(temp_all)  / len(temp_all)
            mean_humid = sum(humid_all) / len(humid_all)
            temp_text.set_text(
                f"Temp:     {latest_temp:.1f} °C  (mean: {mean_temp:.1f})\n"
                f"Humidity: {latest_humid} %      (mean: {mean_humid:.1f})"
            )
        # ─────────────────────────────────────────────────────────────────────

    return line0, line1, stats_text, temp_text

ani = animation.FuncAnimation(fig, update, interval=20, blit=False, cache_frame_data=False)
plt.tight_layout(rect=[0, 0.11, 1, 1])

try:
    plt.show()
finally:
    ser.close()
    print("Serial port closed.")