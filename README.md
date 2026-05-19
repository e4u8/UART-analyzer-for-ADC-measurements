# UART ADC Analyzer (DA14706)

## Overview

Real-time plotting and analysis of 2 ADC channels (CH0, CH1) received from a DA14706
microcontroller over UART. Displays a live scrolling waveform for each channel alongside
a full statistics panel: mean, min, max, peak-to-peak, AC RMS, sample rate, and estimated
signal frequency. Optionally displays temperature and humidity when the MCU sends the
extended 4-field data format.

---

## Requirements

- Python 3.8+
- pyserial
- matplotlib

```
pip install pyserial matplotlib
```

---

## Configuration

Edit the constants at the top of `uart_analyzer.py`:

| Parameter | Default | Description |
|---|---|---|
| `PORT` | `"COM7"` | Serial port. Use `/dev/ttyUSB0` or `/dev/tty.usbserial-*` on Linux/macOS |
| `BAUD` | `115200` | Baud rate — must match firmware |
| `WINDOW` | `500` | Number of samples shown on the plot (rolling display window) |
| `STATS_WIN` | `1000` | Number of samples used for statistics (min, max, pp, RMS, mean) |
| `TEMP_WIN` | `200` | Number of temperature/humidity samples used for their rolling mean |
| `CH0_YMAX` | `3300` | Y-axis upper limit for CH0 in mV |
| `CH1_YMAX` | `3300` | Y-axis upper limit for CH1 in mV |
| `SIGNAL_FREQ_NOMINAL` | `50.0` | Expected signal frequency in Hz — used to scale the crossing guard |
| `HYST_MV` | `50.0` | Hysteresis band in mV for zero-crossing frequency detection |

### Choosing window sizes

At 500 Hz sampling a 50 Hz signal, one period = 10 samples:

- `WINDOW = 500` → 10 periods visible on the plot
- `STATS_WIN = 1000` → 20 full periods for statistics (zero fractional-period error in RMS)

At higher sample rates (1–10 kHz), `STATS_WIN = 1000` covers 20–200 periods automatically,
so the defaults remain appropriate. Raise `STATS_WIN` only if you want a longer averaging
window at very high sample rates.

---

## Data Format (from MCU)

Two formats are accepted. The script auto-detects which one the MCU is sending.

**2-field (ADC only):**
```
mv_ch0,mv_ch1
```

**4-field (ADC + environment):**
```
mv_ch0,mv_ch1,temp_raw,humidity
```

- `mv_ch0`, `mv_ch1` — ADC readings in millivolts (float)
- `temp_raw` — temperature in °C multiplied by 10, sent as integer (e.g. `215` = 21.5 °C)
- `humidity` — relative humidity as integer percent

Lines starting with `[` or `*` are ignored (firmware debug output).

**Example lines:**
```
1234.5,567.8
1234.5,567.8,215,48
```

---

## Statistics — Definitions

All statistics are computed over `STATS_WIN` samples (a bounded rolling buffer), not over
the entire session. This keeps memory use fixed and ensures the values reflect the current
signal rather than a long historical average.

**Mean** — arithmetic mean of the rolling stats window. Also used as the dynamic threshold
for zero-crossing detection, so it automatically tracks DC offset drift.

**Min / Max / Peak-to-peak** — computed over the stats window. A larger `STATS_WIN` is
important here: too small a window risks missing the signal's true extremes, especially
at low signal frequencies or with noise.

**AC RMS** — true root-mean-square of the AC component, computed by subtracting the mean
(DC offset) before squaring:

```
RMS_ac = sqrt( mean( (x - mean(x))^2 ) )
```

This equals the standard deviation of the signal. It correctly represents signal power
regardless of DC bias, unlike a naive RMS of the raw values which would include the DC
component. For best accuracy, `STATS_WIN` should contain an integer number of complete
signal periods (e.g. at 500 Hz / 50 Hz: multiples of 10 samples; the default of 1000 = 20
periods is exact).

**Signal frequency** — estimated from rising zero-crossings of CH1, using a Schmitt-trigger
style detector:

- Threshold is the dynamic mean of CH1 (not a hardcoded midpoint), so it follows DC drift.
- Hysteresis (`HYST_MV`): the signal must fall at least `HYST_MV` below the mean before the
  next rising crossing is armed. This prevents false triggers from noise near the threshold.
- A minimum crossing gap (≈ half a nominal period, derived from `SIGNAL_FREQ_NOMINAL` and
  the measured sample rate) further suppresses glitches.
- Frequency is averaged over the last 20 crossings for stability.

---

## Running

```
python uart_analyzer.py
```

Statistics are displayed once `STATS_WIN` samples have been received (buffer fill phase).
The plot updates at approximately 50 fps (20 ms interval).

The serial port is closed automatically on window close or Ctrl+C.

---

## Notes

- Match `PORT` and `BAUD` to your firmware settings exactly.
- Adjust `CH0_YMAX` / `CH1_YMAX` to fit your signal's voltage range.
- If frequency detection is unstable (noisy signal), increase `HYST_MV`.
- If frequency detection misses crossings (small-amplitude signal), decrease `HYST_MV`.
- The temperature/humidity display box only appears when the MCU sends 4-field data.
  With 2-field firmware it remains at `--`.
