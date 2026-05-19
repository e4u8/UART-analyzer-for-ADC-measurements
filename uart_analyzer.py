import serial
import math
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import time
from collections import deque

# ── Configuration ──────────────────────────────────────────────────────────────
PORT       = "COM7"
BAUD       = 115200

# Rolling display window (what you SEE on the plot)
WINDOW     = 500    # samples — at 500 Hz = 10 periods of 50 Hz; scales well to 1-10 kHz

# Stats window: larger than display window for stable min/max/pp/RMS.
# At 500 Hz, 1000 samples = 20 full periods of 50 Hz. Fine minimum.
# At 10 kHz, 1000 samples = 5 periods — consider raising to 5000 then.
STATS_WIN  = 1000

# Temperature stats window (samples, not time — temperature changes slowly)
TEMP_WIN   = 200

CH0_YMAX   = 3300   # mV
CH1_YMAX   = 3300   # mV

SIGNAL_FREQ_NOMINAL = 50.0   # Hz — used only to set hysteresis guard
# ──────────────────────────────────────────────────────────────────────────────


# ── Serial ────────────────────────────────────────────────────────────────────
try:
    ser = serial.Serial(PORT, BAUD, timeout=0.1)
    print(f"Connected to {PORT} at {BAUD} baud.")
except serial.SerialException as e:
    print(f"ERROR: Could not open {PORT}.\nDetails: {e}")
    exit(1)
# ──────────────────────────────────────────────────────────────────────────────


# ── Rolling buffers ───────────────────────────────────────────────────────────
# Display (plot)
ch0_plot  = deque([0.0] * WINDOW,    maxlen=WINDOW)
ch1_plot  = deque([0.0] * WINDOW,    maxlen=WINDOW)

# Stats (larger window → better min/max/pp/RMS estimates)
ch0_stats = deque([0.0] * STATS_WIN, maxlen=STATS_WIN)
ch1_stats = deque([0.0] * STATS_WIN, maxlen=STATS_WIN)

# Temperature / humidity (bounded)
temp_buf  = deque(maxlen=TEMP_WIN)
humid_buf = deque(maxlen=TEMP_WIN)
# ──────────────────────────────────────────────────────────────────────────────


# ── Sample-rate measurement ───────────────────────────────────────────────────
sample_count      = 0
rate_window_count = 0
rate_window_start = time.time()
measured_rate_hz  = 0.0
# ──────────────────────────────────────────────────────────────────────────────


# ── Frequency detection (CH1) — Schmitt-trigger style zero-crossing ───────────
#
#  We track crossings around the DYNAMIC mean of CH1 (not a hardcoded midpoint).
#  Hysteresis: after a rising crossing, we require the signal to drop at least
#  HYST_MV below the mean before we can detect the next rising crossing.
#  This eliminates chatter caused by noise near the threshold.
#
#  Guard: once a crossing is detected, we ignore the next MIN_CROSS_SAMPLES
#  samples to avoid double-counting within one period.
#  At 500 Hz / 50 Hz → ~10 samples/period, so guard = 5 is half a period.
#  This scales automatically as measured_rate_hz updates.
#
HYST_MV            = 50.0   # mV — adjust if signal is very small or very noisy
cross_armed        = True   # True when we are below threshold and can detect next rise
cross_timestamps   = deque(maxlen=20)   # stores sample-index of each rising crossing
last_cross_sample  = -9999
measured_freq_hz   = 0.0
# ──────────────────────────────────────────────────────────────────────────────


# ── Latest temp/humid for display ─────────────────────────────────────────────
latest_temp  = None
latest_humid = None
# ──────────────────────────────────────────────────────────────────────────────


# ── Matplotlib setup ──────────────────────────────────────────────────────────
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

temp_text = fig.text(
    0.75, 0.01,
    "Temp: --.-°C   Humidity: --%",
    fontsize=9, family="monospace", verticalalignment="bottom",
    color="white",
    bbox=dict(boxstyle="round,pad=0.4", facecolor="#2a5f2a", edgecolor="green")
)
# ──────────────────────────────────────────────────────────────────────────────


def parse_line(raw_line: str):
    """
    Accepts two formats:
      2-field: mv_ch0,mv_ch1
      4-field: mv_ch0,mv_ch1,temp_raw,humidity
               where temp_raw = temp_celsius * 10  (e.g. 215 → 21.5 °C)

    Returns (mv0, mv1, temp_c, humidity) or (mv0, mv1, None, None).
    Returns None on parse failure or non-data lines.
    """
    line = raw_line.strip()
    if not line or line.startswith("[") or line.startswith("*"):
        return None

    parts = line.split(",")

    if len(parts) == 4:
        try:
            mv0      = float(parts[0])
            mv1      = float(parts[1])
            temp_c   = int(parts[2]) / 10.0
            humidity = int(parts[3])
            return mv0, mv1, temp_c, humidity
        except ValueError:
            pass

    if len(parts) == 2:
        try:
            return float(parts[0]), float(parts[1]), None, None
        except ValueError:
            pass

    return None


def ac_rms(buf):
    """
    True AC RMS — mean is subtracted first (DC component removed).

    Formula:  RMS_ac = sqrt( mean( (x - mean(x))^2 ) )

    This equals the standard deviation of the signal and represents
    the actual power-equivalent amplitude of the AC component,
    regardless of DC offset.

    The buffer should ideally contain an integer number of complete
    signal periods. With STATS_WIN=1000 and fs=500 Hz / f=50 Hz,
    that is exactly 20 periods — no truncation error.
    At higher sample rates the number of periods grows further,
    making the fractional-period edge error negligible.
    """
    n    = len(buf)
    mean = sum(buf) / n
    return math.sqrt(sum((x - mean) ** 2 for x in buf) / n)


def update(frame):
    global sample_count, rate_window_count, rate_window_start
    global measured_rate_hz, measured_freq_hz
    global cross_armed, last_cross_sample
    global latest_temp, latest_humid

    while ser.in_waiting:
        try:
            raw    = ser.readline().decode("utf-8", errors="replace")
            result = parse_line(raw)
            if result is None:
                continue

            mv0, mv1, temp_c, humidity = result

            # ── Append to all buffers ──────────────────────────────────────────
            ch0_plot.append(mv0)
            ch1_plot.append(mv1)
            ch0_stats.append(mv0)
            ch1_stats.append(mv1)

            if temp_c is not None:
                latest_temp  = temp_c
                latest_humid = humidity
                temp_buf.append(temp_c)
                humid_buf.append(humidity)

            # ── Sample rate measurement (updated every 2 s) ────────────────────
            rate_window_count += 1
            now     = time.time()
            elapsed = now - rate_window_start
            if elapsed >= 2.0:
                measured_rate_hz  = rate_window_count / elapsed
                rate_window_count = 0
                rate_window_start = now

            # ── Frequency detection on CH1 — Schmitt-trigger zero crossing ─────
            #
            #  Threshold = dynamic mean of the stats buffer (removes DC offset).
            #  Hysteresis band: [mean - HYST_MV, mean + HYST_MV]
            #
            #  State machine:
            #    cross_armed = False  →  signal is above threshold; waiting for
            #                            it to fall below (mean - HYST_MV)
            #    cross_armed = True   →  signal is below threshold; next rise
            #                            above mean triggers a crossing event
            #
            #  Additionally, MIN_CROSS_SAMPLES enforces a minimum gap between
            #  two consecutive crossings (≈ half a nominal period) to ignore
            #  fast noise glitches even if hysteresis is overcome.
            #
            if measured_rate_hz > 0:
                min_cross_gap = int(measured_rate_hz / SIGNAL_FREQ_NOMINAL / 2)
            else:
                min_cross_gap = 4   # safe default before rate is known

            ch1_mean = sum(ch1_stats) / len(ch1_stats)

            if cross_armed:
                # Looking for a rising crossing above the mean
                if (mv1 >= ch1_mean and
                        sample_count - last_cross_sample > min_cross_gap):
                    cross_timestamps.append(sample_count)
                    last_cross_sample = sample_count
                    cross_armed = False   # now wait for signal to drop again

                    # Recompute frequency from recent crossing intervals
                    if len(cross_timestamps) >= 2:
                        gaps = [
                            cross_timestamps[i + 1] - cross_timestamps[i]
                            for i in range(len(cross_timestamps) - 1)
                        ]
                        avg_gap = sum(gaps) / len(gaps)
                        measured_freq_hz = measured_rate_hz / avg_gap
            else:
                # Waiting for signal to drop below (mean - HYST_MV) before
                # the next rising crossing can be armed
                if mv1 < ch1_mean - HYST_MV:
                    cross_armed = True

            sample_count += 1

        except Exception as e:
            print(f"Read error: {e}")

    # ── Update plot lines ──────────────────────────────────────────────────────
    line0.set_data(range(WINDOW), ch0_plot)
    line1.set_data(range(WINDOW), ch1_plot)

    # ── Compute and display statistics ────────────────────────────────────────
    if sample_count > STATS_WIN:
        c0 = list(ch0_stats)
        c1 = list(ch1_stats)

        # Mean (over stats window — bounded, not session-long)
        mean0 = sum(c0) / len(c0)
        mean1 = sum(c1) / len(c1)

        # True AC RMS (DC-free) — see ac_rms() docstring
        rms0 = ac_rms(c0)
        rms1 = ac_rms(c1)

        # Min, max, peak-to-peak (over stats window)
        min0, max0 = min(c0), max(c0)
        min1, max1 = min(c1), max(c1)

        stats_text.set_text(
            f"samples: {sample_count}    "
            f"sample rate: {measured_rate_hz:.1f} Hz    "
            f"signal freq (CH1): {measured_freq_hz:.2f} Hz\n"
            f"[CH0]  current={c0[-1]:.1f} mV   mean={mean0:.1f} mV   "
            f"min={min0:.0f} mV   max={max0:.0f} mV   "
            f"pp={max0 - min0:.0f} mV   AC-RMS={rms0:.1f} mV\n"
            f"[CH1]  current={c1[-1]:.1f} mV   mean={mean1:.1f} mV   "
            f"min={min1:.0f} mV   max={max1:.0f} mV   "
            f"pp={max1 - min1:.0f} mV   AC-RMS={rms1:.1f} mV"
        )

        if latest_temp is not None and len(temp_buf) > 0:
            mean_temp  = sum(temp_buf)  / len(temp_buf)
            mean_humid = sum(humid_buf) / len(humid_buf)
            temp_text.set_text(
                f"Temp:     {latest_temp:.1f} °C  (mean: {mean_temp:.1f})\n"
                f"Humidity: {latest_humid} %      (mean: {mean_humid:.1f})"
            )

    return line0, line1, stats_text, temp_text


ani = animation.FuncAnimation(
    fig, update, interval=20, blit=False, cache_frame_data=False
)
plt.tight_layout(rect=[0, 0.11, 1, 1])

try:
    plt.show()
finally:
    ser.close()
    print("Serial port closed.")
