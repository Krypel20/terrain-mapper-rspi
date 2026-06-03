# terrain-mapper-rspi

Portable 3D terrain measurement system running on Raspberry Pi Zero. Collects GNSS, IMU, and barometric data in real time, fuses them using an adaptive complementary filter, and stores measurements locally or syncs to a PostgreSQL/PostGIS database.

Built as a Bachelor's thesis project at AGH University of Kraków (2024).

---

## Hardware

| Component | Role |
|---|---|
| Raspberry Pi Zero WH | Main controller |
| Waveshare L76K | GNSS positioning (GPS/GLONASS/BeiDou) |
| MPU-6050 | IMU — accelerometer + gyroscope |
| BMP390 | Barometric pressure / altitude support |
| 0.96" OLED (128×64) | Status display |
| 3× push buttons | Start / pause / stop |

---

## Software Architecture

The system uses a multi-threaded design where each sensor runs in an independent thread:

- `l76k_thread` — reads GNSS NMEA messages (GNGGA, GNGSA, GNRMC) via UART at 1 Hz
- `mpu6050_thread` — reads accelerometer and gyroscope data at 5 Hz, detects motion
- `barometer_thread` — reads atmospheric pressure and computes altitude via barometric formula
- `display_thread` — updates OLED at 1 Hz with current measurement status
- `data_writer` — consumes FIFO queue and writes to CSV / PostgreSQL

Threads communicate through a shared memory dictionary (`ui_data`) and a FIFO data queue. Measurements are only saved when motion is detected, preventing accumulation of static noise.

### Sensor Fusion

GNSS altitude is fused with IMU-derived altitude changes using an adaptive complementary filter. The blending coefficient α is dynamically adjusted based on the HDOP quality factor:

```
fused_altitude = α × (gnss_altitude + imu_delta) + (1 - α) × gnss_altitude
```

When HDOP is low (good satellite geometry), the filter trusts GNSS more. When HDOP degrades, it relies more on relative IMU changes to maintain continuity.

---

## Data Storage

Measurements are written to:
- **Local CSV** — always, as a fallback
- **PostgreSQL + PostGIS** — when network is available

Each session is stored in a dedicated table named `session_DDMMYY_HHMMSS`. The system automatically syncs local CSV files to the database when connectivity is restored.

---

## Setup

### Requirements

- Raspberry Pi Zero WH with Raspberry Pi OS Lite (Bullseye)
- Python 3.9

### Enable interfaces

```bash
sudo raspi-config
# Enable: I2C, Serial Port (hardware, no console), SSH
```

### Install dependencies

```bash
sudo apt update
sudo apt install -y git python3-pip python3-dev i2c-tools python3-smbus python3-psycopg2 python3-serial
sudo pip3 install RPi.GPIO smbus2 pillow numpy mpu6050-raspberrypi pandas --break-system-packages
git clone https://github.com/inmcm/micropyGPS.git && cd micropyGPS && sudo python3 setup.py install
```

### Configure database (optional)

Edit `config.py` with your PostgreSQL connection details. If no connection is available, the system falls back to local CSV storage automatically.

### Run

```bash
python3 main.py
```

---

## Controls

| Button | Idle state | Measuring state |
|---|---|---|
| Green | Start measurement | Resume (if paused) |
| Yellow | — | Pause / sync to DB |
| Red | — | Stop and save |

---

## Accuracy

Tested against official Polish terrain models (WCS/Geoportal):

- Horizontal accuracy: consistent with GNSS HDOP 0.8–1.5 under open sky
- Vertical accuracy: ±2.5 m under favorable conditions (HDOP < 1.5)
- Systematic altitude offset of ~5–6 m observed, consistent with low-cost GNSS behavior

---

## Repository Structure

```
├── main.py                  # Entry point, thread orchestration
├── config.py                # Database and system configuration
├── L76X.py                  # GNSS module driver (Waveshare L76K)
├── mpu6050.py               # IMU driver
├── BMP3XX.py                # Barometer driver
├── get_temp_press.py        # Barometric altitude calculation
├── db_connection.py         # PostgreSQL/PostGIS interface
├── waveshare_OLED/          # OLED display driver
└── requirements.txt
```

---

## License

MIT
