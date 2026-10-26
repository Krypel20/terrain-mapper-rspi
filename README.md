# terrain-mapper-rspi

Portable GNSS terrain measurement device built on a Raspberry Pi Zero. It logs position and altitude while you walk over the terrain, together with IMU and barometric data, saves every session to a local CSV file and uploads it to a PostgreSQL/PostGIS database.

This is the measuring part of a two-component system built as my BSc Eng. thesis at AGH University of Krakow (2024). The recorded sessions are processed into 3D terrain models by the desktop application **[terrain-mapper-desktop](https://github.com/Krypel20/terrain-mapper-desktop)**.

---

## Hardware

| Component | Interface | Role |
|---|---|---|
| Raspberry Pi Zero WH | – | Main controller (Wi-Fi for database upload) |
| Waveshare L76K | UART (GPIO14/15, 9600 bps) | GNSS positioning (GPS / GLONASS / BeiDou) |
| MPU-6050 | I2C-1, 0x68 | Accelerometer + gyroscope |
| BMP390 | I2C-3, 0x77 | Barometric pressure / altitude |
| 0.96" OLED 128×64 | SPI | Status display |
| 3× push buttons | GPIO 6 / 13 / 26 | Start / pause / stop |

---

## Software Architecture

Each sensor is handled by its own thread (`SafeThread` logs any unhandled exception to `error_log.txt`):

- `l76k_thread` – reads NMEA sentences (GNGGA, GNGSA, GNRMC) from the L76K every 200 ms and pushes a measurement to the queue
- `mpu6050_thread` – reads the accelerometer and gyroscope at 5 Hz and sets the motion flag
- `bmp390_thread` – reads pressure and temperature at 5 Hz and computes barometric altitude
- `oled_update_thread` – refreshes the OLED status screen at 1 Hz
- `csv_writer_thread` – consumes the FIFO queue and appends rows to the session CSV

Threads share state through the `ui_data` dictionary (producer–consumer pattern). A measurement is queued only when the motion flag is set and recording is not paused; the motion thresholds are currently set to 0, so in practice every GNSS fix is recorded.

### Sensor fusion

`SensorFusion` implements an adaptive complementary filter that blends GNSS altitude with short-term altitude changes integrated from the IMU. The weight α (0.75–0.98) is computed from HDOP, so the filter trusts GNSS more when satellite geometry is good:

```
fused_altitude = α × (gnss_altitude + imu_delta) + (1 − α) × gnss_altitude
```

The filter is kept in the code as an experimental feature; the current version stores the raw GNSS altitude (the fusion call is disabled in `l76k_thread`).

---

## Data Storage

Each session gets a CSV file `measurements/DDMMYY_HHMMSS.csv`:

```
time,latitude,longitude,altitude,VDOP,baro_alt
2024-10-19 17:53:39,49.878161,20.651233,306.0,0.9,301.2
```

The `VDOP` column holds HDOP, because the L76K does not report VDOP reliably.

Upload to PostgreSQL + PostGIS (`db_connection.py`):

- after a measurement is stopped, the file is uploaded if the database is reachable;
- otherwise it stays on the SD card and all pending files are uploaded with the yellow button once the device is back online;
- every file becomes its own table `session_DDMMYY_HHMMSS` (points as `GEOGRAPHY(POINT, 4326)` with a GiST index) and is registered in `measurement_sessions` together with its centroid;
- uploaded files are moved to `measurements/archive/`.

The `measurement_sessions` table has to exist before the first upload. Create it with [`sql/schema.sql`](https://github.com/Krypel20/terrain-mapper-desktop/blob/main/sql/schema.sql) from the desktop repository.

---

## Setup

### Requirements

- Raspberry Pi Zero WH with Raspberry Pi OS Lite (Bookworm)
- Python 3.11

### Enable interfaces

```bash
sudo raspi-config
# Enable: I2C, SPI, Serial Port (hardware enabled, login shell disabled), SSH
```

### Install dependencies

```bash
sudo apt update
sudo apt install -y git python3-pip python3-numpy python3-pil python3-serial python3-smbus \
    python3-spidev python3-gpiozero python3-rpi.gpio python3-psycopg2 i2c-tools
sudo pip3 install --break-system-packages "micropyGPS @ git+https://github.com/inmcm/micropyGPS.git"
```

(`requirements.txt` lists the same packages for pip.)

### Configure database

Set the connection parameters in the `DatabaseConnection` constructor in `db_connection.py` (database, user, password, host, port). `test_db_con.py` checks whether the server is reachable. Without a connection the device keeps working and stores data only in CSV files.

### Run

```bash
mkdir -p measurements
python3 main.py
```

`main.py` also contains `main_service()` for running the device headless as a systemd service; the service commands are listed in `polecenia_auto_start_usługi.txt`.

---

## Controls

| Button | Before start | While measuring | After a measurement |
|---|---|---|---|
| Green | Start measurement | – | Start a new measurement |
| Yellow | Start without OLED preview | Pause / resume recording | Upload all pending CSV files |
| Red | Exit | Stop and save (upload if online) | Exit |

---

## Accuracy

Tested against official Polish elevation models (GUGiK WCS / Geoportal):

- horizontal track consistent with the reference map at HDOP 0.8–1.5 under open sky;
- vertical accuracy of about ±2.5 m in favourable conditions (HDOP < 1.5);
- systematic altitude offset of about 5–6 m, typical for a single-frequency receiver.

---

## Repository Structure

```
├── main.py                  # Entry point: threads, buttons, OLED/terminal UI, sensor fusion
├── db_connection.py         # PostgreSQL/PostGIS upload and archiving
├── config.py                # UART / GPIO / MPU-6050 initialisation for the L76K driver
├── L76X.py                  # Waveshare L76K driver (NMEA parsing via micropyGPS)
├── mpu6050.py               # MPU-6050 driver
├── BMP3XX.py                # BMP390 driver
├── get_temp_press.py        # BMP390 test script
├── test_db_con.py           # Database connectivity test
├── waveshare_OLED/          # OLED driver (Waveshare)
├── pic/                     # Fonts and bitmaps for the OLED
└── requirements.txt
```

---

## License

MIT – see [LICENSE](LICENSE). The bundled sensor/display drivers (`mpu6050.py`, `BMP3XX.py`, `L76X.py`, `waveshare_OLED/`) come from their authors and vendors and keep their original licenses.
