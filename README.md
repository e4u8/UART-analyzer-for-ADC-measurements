# UART ADC Analyzer (DA14706)

## Overview
Real-time plotting of 2 ADC channels (CH0, CH1) from DA14706 via UART, with basic stats (min, max, peak to peak, RMS).

## Requirements
- Python 3
- pyserial
- matplotlib

## Install
pip install pyserial matplotlib

## Configuration
Edit in script:
PORT     = "COM7"
BAUD     = 115200
WINDOW   = 200
CH0_YMAX = 3300
CH1_YMAX = 3300

## Data Format (from MCU)
mv_ch0,mv_ch1 

Example:
1234.5,567.8

- Values in mV

## Run
python uart_analyzer.py

## Notes
- Match COM port & baud rate with firmware
- Adjust Y-axis limits based on signal range
- Serial port closes automatically on exit