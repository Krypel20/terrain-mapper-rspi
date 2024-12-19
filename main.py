import threading
import L76X
import time
import curses
import numpy as np
import csv 
import os
import sys
import traceback
import logging
import RPi.GPIO as GPIO
import psycopg2
from BMP3XX import *
from psycopg2 import OperationalError
from db_connection import DatabaseConnection
from config import config
from datetime import datetime
from threading import Thread
from waveshare_OLED import OLED_0in96
from PIL import Image,ImageDraw,ImageFont
from queue import Queue, Empty

mpu6050_sleep = 0.2
bmp390_sleep = 0.2
l76k_sleep = 0.2
oled_sleep = 1
terminal_ui_sleep = 0.1
button_push_loop = 0.01
db = DatabaseConnection()

# Konfiguracja zapisywania logów do pliku
logging.basicConfig(filename='error_log.txt', level=logging.ERROR, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

class Button:
    def __init__(self, pin, debounce_time=1, state=True, action=None):
        self.pin = pin
        self.button_pressed = False
        self.last_press_time = 0
        self.debounce_time = debounce_time
        self.action = action
        self.state = state

	# Usuń poprzednią detekcję zdarzeń przed dodaniem nowej
        GPIO.setmode(GPIO.BCM)
        try:
            GPIO.remove_event_detect(self.pin)
        except:
            pass  # Ignoruj błąd jeśli nie było wcześniejszej detekcji

        GPIO.setup(self.pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)
        GPIO.add_event_detect(self.pin, GPIO.FALLING, callback=self.handle_button, bouncetime=200)
    
    def handle_button(self, channel=None):
        button_state = GPIO.input(self.pin)
        current_time = time.time()
    
        if button_state == GPIO.LOW and not self.button_pressed and (current_time - self.last_press_time) > self.debounce_time:
            if self.action:
                self.action()
            self.state = not self.state
            self.last_press_time = current_time
            self.button_pressed = True
        elif button_state == GPIO.HIGH:
            self.button_pressed = False

    def cleanup(self):
        GPIO.cleanup(self.pin)

# Zmodyfikowana klasa Thread
class SafeThread(Thread):
    def run(self):
        try:
            super().run()
        except Exception:
            thread_exception_handler(sys.exc_info())

class Display:
    def __init__(self, default_font_size=12):
        self.oled = OLED_0in96.OLED_0in96()
        self.oled.Init()
        self.oled.clear()
        self.image = Image.new('1', (self.oled.width, self.oled.height), 255)
        self.draw = ImageDraw.Draw(self.image)
        self.default_font = ImageFont.truetype('pic/Font.ttc', default_font_size)
        self.last_update_time = time.time()
        self.previous_data = {}
        self.text_positions = {
            'alt': (2, 0), 
            #'move_status': (72, 0),
            'csv_status': (2, 14), 
            #'measurements': (90, 14),
            'duration': (2, 26), 'speed': (72, 26),
            'hdop': (2, 38),'sat': (60, 38),
            
            #alternative display
            # 'duration2': (1, 0), 'csv_status': (28, 0), 
            # 'alt2': (1, 14),
            # 'hdop2': (1, 42),
        }

    def clear(self):
        self.oled.clear()
        self.draw.rectangle((0, 0, self.oled.width, self.oled.height), fill=255)

    def display_text(self, text, x, y, font_size=None):
        if font_size:
            font = ImageFont.truetype('pic/Font.ttc', font_size)
        else:
            font = self.default_font
        self.draw.text((x, y), text, font=font, fill=0)

    def display_message(self, message, font_size=13):
        self.clear()
        font = ImageFont.truetype('pic/Font.ttc', font_size)
        lines = message.split('\n')
        y_position = (self.oled.height - (len(lines) * font_size)) // 2
        for line in lines:
            bbox = self.draw.textbbox((0, 0), line, font=font)
            text_width = bbox[2] - bbox[0]
            x_position = (self.oled.width - text_width) // 2
            self.draw.text((x_position, y_position), line, font=font, fill=0)
            y_position += font_size
        self.oled.ShowImage(self.oled.getbuffer(self.image))

    def update_field(self, field, value):
        if field in self.text_positions and self.previous_data.get(field) != value:
            x, y = self.text_positions[field]
            # Clear the specific area
            self.draw.rectangle((x, y, 128 - x, y + 12), fill=255)
            self.display_text(f"{value}", x, y, 10)
            self.previous_data[field] = value
            return True
        return False

    def display_data(self, ui_data):
        current_time = time.time()
        if current_time - self.last_update_time < 0.1:
            return  # Skip update if interval has not passed

        updated = False

        updated |= self.update_field('duration', f"{ui_data['duration']}, d:{ui_data['delay']}s" if ui_data['duration'] is not None else "Czas: N/A")
        updated |= self.update_field('speed', f"{ui_data['speed']}km/h" if ui_data['speed'] is not None else "Speed N/A")
        updated |= self.update_field('csv_status', f"Zapis: {ui_data['csv_status']} - [{ui_data['mesurements']}]" if ui_data['mesurements'] is not None else f"Zapis: {ui_data['csv_status']} - [brak]")
        updated |= self.update_field('alt', f"Wys: {ui_data['alt']:.2f} - {ui_data['move_status']}" if ui_data['alt'] is not None else f"NO SIGNAL - {ui_data['move_status']}")
        updated |= self.update_field('hdop', f"HDOP: {ui_data['hdop']} VDOP: {ui_data['vdop']}" if ui_data['vdop'] is not None else "HDOP: N/A VDOP: N/A")

        if updated:
            self.oled.ShowImage(self.oled.getbuffer(self.image))
            self.last_update_time = current_time
    
    def display_alternative_data(self, ui_data):
        current_time = time.time()
        if current_time - self.last_update_time < 0.1:
            return  # Skip update if interval has not passed

        updated = False

        updated |= self.update_field('duration2', f"{ui_data['duration']}" if ui_data['duration'] is not None else "Czas: N/A")
        updated |= self.update_field('csv_status2', f"{ui_data['csv_status']} - [{ui_data['mesurements']}]" if ui_data['mesurements'] is not None else f"Zapis: {ui_data['csv_status']} - [brak]")
        updated |= self.update_field('alt2', f"Wys: {ui_data['alt']:.2f}" if ui_data['alt'] is not None else f"NO SIGNAL - {ui_data['move_status']}")
        updated |= self.update_field('hdop2', f"HDOP: {ui_data['hdop']}" if ui_data['vdop'] is not None else "HDOP: N/A")

        if updated:
            self.oled.ShowImage(self.oled.getbuffer(self.image))
            self.last_update_time = current_time

class SensorFusion:
    def __init__(self, base_alpha=0.96, min_alpha=0.75, max_alpha=0.98):
        """
        Inicjalizacja fuzji danych z adaptacyjnym współczynnikiem.
        
        Args:
            base_alpha: bazowy współczynnik filtra (0-1)
            min_alpha: minimalny dopuszczalny współczynnik
            max_alpha: maksymalny dopuszczalny współczynnik
        """
        self.base_alpha = base_alpha
        self.min_alpha = min_alpha
        self.max_alpha = max_alpha
        self.accumulated_altitude_change = 0
        self.last_altitude = None
        self.velocity_z = 0
        self.last_accel_z = 0
        self.dt = 0.2  # okres próbkowania (200ms jak w L76K)
        
    def calculate_adaptive_alpha(self, hdop):
        """
        Oblicza adaptacyjny współczynnik alfa na podstawie HDOP.
        
        Args:
            hdop: wartość HDOP z odbiornika GNSS
            
        Returns:
            float: dostosowany współczynnik alfa
        """
        if hdop is None or hdop <= 0:
            return self.base_alpha
            
        # HDOP jakość:
        # Doskonała: < 1
        # Dobra: 1-2
        # Umiarkowana: 2-5
        # Słaba: 5-10
        # Bardzo słaba: > 10
        
        if hdop < 1.0:
            quality_factor = 1.0
        elif hdop < 2.0:
            quality_factor = 0.9
        elif hdop < 5.0:
            quality_factor = 0.7
        elif hdop < 10.0:
            quality_factor = 0.5
        else:
            quality_factor = 0.3
            
        # Oblicz adaptacyjną alfę
        adaptive_alpha = self.base_alpha + (1 - quality_factor) * (self.max_alpha - self.base_alpha)
        
        # Ogranicz do zdefiniowanego zakresu
        return max(min(adaptive_alpha, self.max_alpha), self.min_alpha)
    
    def add_imu_data(self, accel_data, gyro_data):
        """
        Akumuluje dane z IMU między pomiarami GNSS
        """
        # Kompensacja przyspieszenia grawitacyjnego
        accel_z = accel_data['z'] - 9.81
        # Ogranicz maksymalną zmianę wysokości z pojedynczego pomiaru
        max_height_change = 1  # 1m na pomiar
        delta_height = accel_z * (self.dt * self.dt) / 2 # s = (a * t^2) / 2
        
        if abs(delta_height) < max_height_change:
            self.accumulated_altitude_change += delta_height
        
    def update(self, gnss_altitude, hdop=None):
        """
        Wykonuje fuzję danych przy każdym pomiarze GNSS (co 1s)
        """
        if self.last_altitude is None:
            self.last_altitude = gnss_altitude
            return gnss_altitude, self.base_alpha
        
        # Oblicz adaptacyjną alfę
        current_alpha = self.calculate_adaptive_alpha(hdop)
        
        # Skoryguj wysokość GNSS o zakumulowaną zmianę z IMU
        corrected_altitude = gnss_altitude + self.accumulated_height
        
        # Fuzja danych
        fused_altitude = current_alpha * corrected_altitude + (1 - current_alpha) * gnss_altitude
        
        # Reset akumulatora po fuzji
        self.accumulated_height = 0
        
        # Zapamiętaj ostatnią wysokość
        self.last_altitude = fused_altitude
        
        return fused_altitude, current_alpha
    
# Funkcja do obsługi wyjątków w wątkach
def thread_exception_handler(args):
    exc_type, exc_value, exc_traceback = args
    logging.error("Nieobsłużony wyjątek w wątku:\n" + 
                  ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback)))
    stop_event.set()  # Zatrzymaj wszystkie wątki

# Funkcja do aktualizacji wyświetlacza OLED
def oled_update_thread(display, stop_event, ui_data):
    while not stop_event.is_set():
        try:
            display.display_data(ui_data)
        except:
            pass
        if stop_event.is_set():
            break
        time.sleep(oled_sleep) #aktualziacja max co 1s

# Funkcja do odczytu danych z MPU6050 (akcelerometr + żyroskop)
def read_mpu6050(mpu):
    accel = mpu.get_accel_data()  # Odczyt akcelerometru
    gyro = mpu.get_gyro_data()    # Odczyt żyroskopu
    return accel, gyro

def bmp390_thread(bmp, stop_event, ui_data, movement_detected):
    """
    Wątek obsługujący czujnik BMP390 do pomiaru ciśnienia i temperatury.
    
    Args:
        bmp: Obiekt czujnika BMP390
        stop_event: Event do sygnalizacji zatrzymania wątku
        ui_data: Słownik współdzielonych danych UI
        movement_detected: Lista z flagą wykrycia ruchu
    """
    # Stała do kalibracji wysokości (można dostosować)
    ALTITUDE_DIFF_THRESHOLD = 5.0  # metry
    
    # Inicjalizacja średniej ruchomej dla stabilizacji odczytów
    pressure_readings = []
    MAX_READINGS = 5
    
    while not stop_event.is_set():
        try:
            # Pomiar ciśnienia, temperatury i obliczenie wysokości
            pressure = bmp.get_pressure
            temperature = bmp.get_temperature
            altitude = bmp.get_altitude
            
            # Dodaj odczyt ciśnienia do listy dla średniej ruchomej
            pressure_readings.append(pressure)
            if len(pressure_readings) > MAX_READINGS:
                pressure_readings.pop(0)
            
            # Oblicz średnią z ostatnich odczytów
            avg_pressure = sum(pressure_readings) / len(pressure_readings)
            
            # Aktualizacja danych w słowniku UI
            ui_data['baro_pressure'] = round(avg_pressure, 2)
            ui_data['baro_temp'] = round(temperature, 2)
            ui_data['baro_alt'] = round(altitude, 2)
            
            # Porównanie z wysokością GNSS (jeśli dostępna)
            if ui_data.get('alt') is not None:
                alt_diff = abs(ui_data['alt'] - altitude)
                
                # Sprawdzenie czy różnica wysokości przekracza próg
                if alt_diff > ALTITUDE_DIFF_THRESHOLD and movement_detected[0]:
                    ui_data['alt_warning'] = True
                    ui_data['alt_diff'] = round(alt_diff, 2)
                else:
                    ui_data['alt_warning'] = False
                    ui_data['alt_diff'] = 0.0
            
            # Zapisz poprzednią wysokość do wykrywania zmian
            ui_data['prev_baro_alt'] = altitude
            
        except Exception as e:
            logging.error(f"Błąd w wątku BMP390: {str(e)}")
            ui_data['baro_error'] = "error"
            time.sleep(1)
            continue
            
        time.sleep(bmp390_sleep)

# Wątek do odczytu z MPU6050 
def mpu6050_thread(mpu, stop_event, ui_data, movement_detected, sensor_fusion):
    mv_threshold = 0 #13.5 Próg ruchu
    rt_threshold = 0 #100  Próg rotacji
    try:
        while not stop_event.is_set():
            accel, gyro = read_mpu6050(mpu)
            movement = abs(accel['x']) + abs(accel['y']) + abs(accel['z']) # Wektor przyspieszenia ruchu
            rotation = abs(gyro['x']) + abs(gyro['y']) + abs(gyro['z'])
            ui_data['accel'] = accel
            ui_data['gyro'] = gyro

            # Fuzja danych z L76K
            sensor_fusion.add_imu_data(accel, gyro)    
            
            # Sprawdzanie, czy urządzenie jest w ruchu
            if movement > mv_threshold and rotation > rt_threshold:
                movement_detected[0] = True  # Wykryto ruch
                ui_data['move'] = f"W ruchu, movement {movement:.2f} | rotation {rotation:.2f}"
                ui_data['move_status'] = "W ruchu"
            else:
                movement_detected[0] = False  # Brak ruchu
                ui_data['move'] = f"W miejscu, movement {movement:.2f} | rotation {rotation:.2f}"
                ui_data['move_status'] = "W miejscu"

            time.sleep(mpu6050_sleep)  # Próbkowanie MPU6050 co 150ms
    except Exception as e:
        logging.error(f"Wystapil blad podczas wykonywania wątku mpu6050: {e}", exc_info=True)
        stop_event.set()

# Wątek do odczytu z L76K
def l76k_thread(l76k, stop_event, ui_data, movement_detected, mesurements, pause_mesure, data_queue, sensor_fusion):
    global mesurement_saveing
    last_measurement_time = None
    try:
        while not stop_event.is_set():
            l76k.L76X_Gat_GNGGA()
            if l76k.Status == 1:
                current_time = datetime.now()
                mesure_timestamp = current_time.strftime("%Y-%m-%d %H:%M:%S")
                
                # Obliczanie opóźnienia pomiędzy pomiarami
                if last_measurement_time is not None:
                    delay = (current_time - last_measurement_time).total_seconds()
                    ui_data['delay'] = round(delay,2)
                else:
                    ui_data['delay'] = None
                last_measurement_time = current_time
                
                corrected_altitude, current_alpha = sensor_fusion.update(
                    l76k.Altitude,
                    l76k.HDOP
                )
                
                # Aktualizacja danych GPS w pamięci współdzielonej (ui_data)
                ui_data['time'] = f"{l76k.Time_H:02}:{l76k.Time_M:02}:{int(l76k.Time_S):02}"
                ui_data['lat'] = l76k.Lat
                ui_data['lon'] = l76k.Lon
                ui_data['alt'] = l76k.Altitude
                ui_data['new_alt'] = corrected_altitude
                ui_data['sat'] = l76k.Satellites
                ui_data['hdop'] = l76k.HDOP
                ui_data['vdop'] = l76k.VDOP
                ui_data['pdop'] = l76k.PDOP
                ui_data['speed'] = l76k.speed
                ui_data['headed'] = l76k.direction
                ui_data['fusion_alpha'] = current_alpha
                
                # Zapis do CSV, tylko gdy wykryto ruch
                if movement_detected[0] and not pause_mesure.state:
                    ui_data['csv_status'] = "Aktywny"
                    if l76k.Altitude:
                        mesurements += 1
                        ui_data['mesurements'] = mesurements
                        data_queue.put([str(mesure_timestamp), round(ui_data['lat'], 6), round(ui_data['lon'], 6), ui_data['alt'], ui_data['hdop'], ui_data['baro_alt']]) #powinien byc VDOP ale odbiornik nie zwraca tej wartosci poprawnie
                else:
                    ui_data['csv_status'] = "Zatrzymany"
            
            time.sleep(l76k_sleep)
    except Exception as e:
        logging.error(f"Wystapil blad podczas wykonywania wątku l76k: {e}", exc_info=True)
        
# Wątek do zapisywania bierzących pomiarów do pliku CSV
def csv_writer_thread(csv_file, data_queue, stop_event):
    with open(csv_file, 'a', newline='') as file:
        writer = csv.writer(file)
        while not stop_event.is_set():
            try:
                data = data_queue.get(timeout=1)
                writer.writerow(data)
                file.flush()  # upewnienie sie ze dane sa zapisane
            except Empty:
                continue
            except Exception as e:
                logging.error(f"Error in CSV writer thread: {str(e)}")
                break 

# Funkcja do inicjalizacji pliku CSV
def init_csv():
    # Nazwa pliku na podstawie czasu rozpoczęcia sesji
    measure_datetime = datetime.now().strftime("%d%m%y_%H%M%S")
    folder_path = "measurements"
    file_name = f'{measure_datetime}.csv'
    csv_file = os.path.join(folder_path, file_name)
    
    # Tworzenie pliku z nagłówkiem
    with open(csv_file, 'w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["time", "latitude", "longitude", "altitude", "VDOP","baro_alt"])
    
    return csv_file, file_name

# Funkcja do sprawdzania połączenia z bazą danych
def check_db_connection(db):
    try:
        with db.connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
        return True
    except OperationalError:
        return False

# Funkcja do sprawdzania długości kolejki
def check_queue_length(measurements_queue):
    queue_length = measurements_queue.qsize()
    return queue_length

# Współdzielona pamięć do przechowywania danych
ui_data = {
    'duration': None,
    'time': None,
    'lat': None,
    'lon': None,
    'alt': None,
    'new_alt': None,
    'sat': None,
    'accel': {'x': 0, 'y': 0, 'z': 0},
    'gyro': {'x': 0, 'y': 0, 'z': 0},
    'move': None,
    'move_status': None,
    'mesurements': None,
    'hdop': None,
    'vdop': None,
    'pdop': None,
    'quality_index': None,
    'csv_status': None,
    'queue_length': None,
    'delay': None,
    'db_connection': None,
    'wifi_connection': None,
    'speed': None,
    'headed': None,
    'baro_pressure': None,
    'baro_temp': None,
    'baro_alt': None,
    'alt_diff': None,
    'fusion_alpha': None,
}

def main(stdscr):
    global stop_event, db
    alternative_display = False

    curses.curs_set(0)
    display = Display()
    sensor_fusion = SensorFusion(base_alpha=0.96, min_alpha=0.75, max_alpha=0.98)
    display.display_message("Terrain Mapper\nInicjalizacja...", 15)

    # Inicjalizacja połączenia z bazą danych
    try:
        db = DatabaseConnection()
        logging.info("Połączenie z bazą danych zostało zainicjalizowane.")
    except Exception as e:
        logging.error(f"Nie udało się zainicjalizować połączenia z bazą danych: {e}")
        sys.exit(1)

    if check_db_connection(db):
        ui_data['db_connection'] = "Połączono"
        print("Polaczono z baza danych")
    else:
        ui_data['db_connection'] = "Brak połączenia"
        print("Brak polaczenia z baza danych")

    # Event do zatrzymywania wątków
    stop_event = threading.Event()
    
    bmp = BMP3XX_I2C(i2c_addr = 0x77,bus = 3) #adres BMP390
    if not bmp.begin():
        logging.error("Nie można zainicjalizować BMP390")
    else:
        bmp.set_common_sampling_mode(HIGH_PRECISION)
        
    mpu6050 = config(baudrate=9600, mpu_address=0x68) #adres MPU6050
    l76k=L76X.L76X()
    l76k.L76X_Send_Command(l76k.SET_COLD_START)
    # print("L76K cold start")
    # time.sleep(30)
    
    # Flaga wykrycia ruchu
    movement_detected = [False]
    
    #inicjalizacja przyciskuów
    stop_mesure = Button(26, 1, False, stop_event.set) #red
    pause_mesure = Button(13, 0.3, False) #yellow
    start_mesure = Button(6, 0.3, False)  #green
    
    print("Oczekiwanie na naciśnięcie przycisku start")
    display.display_message("Wcisnij przycisk\nstart", 15)
    
    stop_flag = stop_mesure.state
    pause_flag = pause_mesure.state
    
    while not start_mesure.state:
        start_mesure.handle_button()
        if stop_mesure.state is not stop_flag:
            l76k.L76X_Send_Command(l76k.SET_COLD_START)
            sys.exit(0)
        
        #opcja uruchomienia programu bez odświerzania wyświetlacza OLED
        if pause_mesure.state is not pause_flag:
            alternative_display = True
            display.display_message("Pomiar bez podglądu\nOLED OFF\nWcisnij start", 13)
            while not start_mesure.state:
                start_mesure.handle_button()
                time.sleep(button_push_loop)
                
        time.sleep(button_push_loop)
        
    l76k.L76X_Set_Baudrate(9600)
    l76k.L76X_Send_Command(l76k.SET_POS_FIX_200MS)
    l76k.L76X_Send_Command(l76k.SET_NMEA_OUTPUT)
    l76k.L76X_Exit_BackupMode()
    
    # Inicjalizacja CSV
    display.clear()
    csv_file, file_name = init_csv()
    mesurements = 0 #zmienna przechowująca liczbe zapisanych pomiarów
    data_queue = Queue()

    # Uruchamianie wątków
    if not alternative_display:
        oled_thread = SafeThread(target=oled_update_thread, args=(display, stop_event, ui_data))
        oled_thread.start()
    mpu_thread = SafeThread(target=mpu6050_thread, args=(mpu6050.mpu, stop_event, ui_data, movement_detected, sensor_fusion))
    gps_thread = SafeThread(target=l76k_thread, args=(l76k, stop_event, ui_data, movement_detected, mesurements, pause_mesure, data_queue, sensor_fusion))
    csv_thread = SafeThread(target=csv_writer_thread, args=(csv_file, data_queue, stop_event))
    bmp_thread = SafeThread(target=bmp390_thread, args=(bmp, stop_event, ui_data, movement_detected))
    
    gps_thread.start()
    mpu_thread.start()
    csv_thread.start()
    bmp_thread.start()
    
    start_time = datetime.now()
    if alternative_display:
        display.display_message("************\nTRWA POMIAR\n_________________", 17)
    stop_mesure.state = False
    pause_mesure.state = False
    
    stdscr.clear()
    print("\nPomiar rozpoczęty")
    
    try:
        while not stop_event.is_set():
            stdscr.clear()
            stop_mesure.handle_button()
            pause_mesure.handle_button()
            
            elapsed_time = datetime.now() - start_time
            ui_data['duration'] = str(elapsed_time).split('.')[0]
            
            if not pause_mesure.state:
                ui_data['csv_status'] = "Aktywny"
            else:
                ui_data['csv_status'] = "Zatrzymany"
                
            ui_data['queue_length'] = check_queue_length(data_queue)

            if int(time.time()) % 60 == 0:
                if check_db_connection(db):
                    ui_data['db_connection'] = "Połączono"
                else:
                    ui_data['db_connection'] = "Brak połączenia"
            
            # Nagłówek czujnika ruchu UI TERMINALA
            stdscr.addstr(0, 0, f"[MPU6050] Stan urządzenia: {ui_data['move']}")
            stdscr.addstr(1, 0, f"Akcelerometr: X={ui_data['accel']['x']:.2f}, Y={ui_data['accel']['y']:.2f}, Z={ui_data['accel']['z']:.2f}")
            stdscr.addstr(2, 0, f"Żyroskop: X={ui_data['gyro']['x']:.2f}, Y={ui_data['gyro']['y']:.2f}, Z={ui_data['gyro']['z']:.2f}")
            
            # Nagłówek GPS UI TERMINALA
            stdscr.addstr(4, 0, f"[L76K] {ui_data['time']}, Czas pomiaru {ui_data['duration']}, Delay: {ui_data['delay']} Zapis pomiarów: {ui_data['csv_status']}, Pomiary: {ui_data['mesurements']}, W kolejce do zapisu: {ui_data['queue_length']}")
            try:
                # UI TERMINALA
                lat = f"{ui_data['lat']:.6f}" if ui_data['lat'] is not None else "N/A"
                lon = f"{ui_data['lon']:.6f}" if ui_data['lon'] is not None else "N/A"
                alt = f"{ui_data['alt']:.2f}" if ui_data['alt'] is not None else "N/A"
                sat = f"{ui_data['sat']}" if ui_data['sat'] is not None else "N/A"
                hdop = f"{ui_data['hdop']}" if ui_data['hdop'] is not None else "N/A"
                vdop = f"{ui_data['vdop']}" if ui_data['vdop'] is not None else "N/A"
                pdop = f"{ui_data['pdop']}" if ui_data['pdop'] is not None else "N/A"
                speed = f"{ui_data['speed']}" if ui_data['speed'] is not None else "N/A"
                headed = f"{ui_data['headed']}" if ui_data['headed'] is not None else "N/A"
                stdscr.addstr(5, 0, f"L76K\tLat,Lon: {lat}, {lon}, Altitude: {alt}, Fusion alt: {ui_data['new_alt']}, Satellites: {sat}")
                stdscr.addstr(6, 0, f"[index] HDOP: {hdop}, VDOP: {vdop}, Speed: {speed} Direction: {headed}")
            except TypeError:
                stdscr.addstr(5, 0, "L76K\tLat,Lon: N/A, N/A, Altitude: N/A, Satellites: N/A")
                stdscr.addstr(6, 0, "HDOP: N/A, VDOP: N/A, PDOP: N/A, GNSS: N/A")
            
            stdscr.addstr(7, 0, f"[BMP390] Cisnienie: {ui_data['baro_pressure']} hPa, Temp: {ui_data['baro_temp']} C")
            stdscr.addstr(8, 0, f"Wysokosc: {ui_data['baro_alt']} m, Różnica wys.: {ui_data['alt_diff']} m")
            stdscr.addstr(10, 0, f"Połączenie z bazą danych: {ui_data['db_connection']}")

            # Odświeżenie ekranu terminala
            stdscr.refresh()
            time.sleep(terminal_ui_sleep)
            
    except KeyboardInterrupt:
            pass
    except Exception as e:
        logging.error(f"Wystapil blad podczas wykonywania glownej petli programu: {e}", exc_info=True)
    finally:
        if not alternative_display:
            oled_thread.join()
        stop_event.set()
        mpu_thread.join()
        gps_thread.join()
        csv_thread.join()
        bmp_thread.join()
        
        # Wyświetl informację o błędzie, jeśli wystąpił
        stdscr.clear()
        display.clear()
        if stop_mesure.state:
            start_mesure.state = False
            if not alternative_display:
                display.display_message(f"Pomiar zakończony\npomyślnie :)", 15)
            else:
                display.display_message(f"Pomiar zakończony\n Wykonane pomiary {ui_data['mesurements']}", 12)
            print("\nProgram zakończony pomyślnie.")
            time.sleep(1)
            
            # Próba importu danych do bazy po zakończeniu pomiaru
            if check_db_connection(db):
                try:
                    db.upload_csv_to_db(csv_file)
                    print(f"\n\nDane z pliku {file_name} zostały zaimportowane do bazy danych.")
                    display.display_message(f"Pomiar pomyslnie\n zapisany do\nbazy danych :)", 12)
                except Exception as e:
                    print(f"Błąd podczas importu danych do bazy: {str(e)}")
            else:
                print("\n\nBrak połączenia z bazą danych. Import nie został wykonany.")
                display.display_message(f"Nie udalo sie\n zapisac pomiaru\n do bazy danych", 11)
                
            time.sleep(2)
        else:
            start_mesure.state = False
            display.display_message(f"Program zatrzymany :(\nWystąpił błąd\nsprawdź error_logs.txt", 12)
            print("\n\nProgram zatrzymany :(\nSprawdź plik error_log.txt\naby zobaczyć szczegóły błędu.")
            time.sleep(1.25)

        stdscr.touchwin()
        stdscr.refresh()
        print(f"Zapisano do {file_name} Wciśnij przycisk start, aby rozpocząć nowy pomiar")
        display.display_message(f"Pomiar zapisany do\n\n{file_name}\n Wcisnij start aby\nzaczac nowy pomiar")
        
        stop_flag = stop_mesure.state
        save_flag = pause_mesure.state
        start_flag = start_mesure.state
        while True:
            start_mesure.handle_button()
            pause_mesure.handle_button()
            stop_mesure.handle_button()
            
            if stop_mesure.state is not stop_flag:
                db.close()
                sys.exit(0)
            
            if pause_mesure.state is not save_flag:
                print(f"Trwa zapisywanie wszystkich pomiarów do bazy danych")
                db.import_all_csv_files()
                save_flag = pause_mesure.state
                print(f"Pomiar zapisany wcisnij start by kontynułować")
                continue
            
            if start_flag is not start_mesure.state:
                break
                
            time.sleep(button_push_loop)

def main_service():
    global stop_event, db
    alternative_display = False

    display = Display()
    sensor_fusion = SensorFusion(base_alpha=0.96, min_alpha=0.75, max_alpha=0.98)
    display.display_message("Terrain Mapper\nInicjalizacja...", 15)

    # Inicjalizacja połączenia z bazą danych
    try:
        db = DatabaseConnection()
        logging.info("Połączenie z bazą danych zostało zainicjalizowane.")
    except Exception as e:
        logging.error(f"Nie udało się zainicjalizować połączenia z bazą danych: {e}")
        sys.exit(1)

    if check_db_connection(db):
        ui_data['db_connection'] = "Połączono"
        display.display_message("Polaczono z BD", 14)
    else:
        ui_data['db_connection'] = "Brak połączenia"
        display.display_message("Brak polaczenia\nz BD", 14)
        
    # Event do zatrzymywania wątków
    stop_event = threading.Event()
    
    bmp = BMP3XX_I2C(i2c_addr = 0x77,bus = 3) #adres BMP390
    if not bmp.begin():
        logging.error("Nie można zainicjalizować BMP390")
    else:
        bmp.set_common_sampling_mode(HIGH_PRECISION)
        
    mpu6050 = config(baudrate=9600, mpu_address=0x68)
    l76k=L76X.L76X()
    l76k.L76X_Send_Command(l76k.SET_COLD_START)
    
    # Flaga wykrycia ruchu
    movement_detected = [False]
    
    #inicjalizacja przyciskuów
    stop_mesure = Button(26, 1, False, stop_event.set) #red
    pause_mesure = Button(13, 0.3, False) #yellow
    start_mesure = Button(6, 0.3, False)  #green
    
    display.display_message("Wcisnij przycisk\nstart", 15)
    
    stop_flag = stop_mesure.state
    pause_flag = pause_mesure.state
    
    while not start_mesure.state:
        start_mesure.handle_button()
        if stop_mesure.state is not stop_flag:
            l76k.L76X_Send_Command(l76k.SET_COLD_START)
            sys.exit(0)
        
        if pause_mesure.state is not pause_flag:
            alternative_display = True
            display.display_message("Pomiar bez podglądu\nOLED OFF\nWcisnij start", 13)
            while not start_mesure.state:
                start_mesure.handle_button()
                time.sleep(button_push_loop)
                
        time.sleep(button_push_loop)
        
    l76k.L76X_Set_Baudrate(9600)
    l76k.L76X_Send_Command(l76k.SET_POS_FIX_200MS)
    l76k.L76X_Send_Command(l76k.SET_NMEA_OUTPUT)
    l76k.L76X_Exit_BackupMode()
    
    # Inicjalizacja CSV
    display.clear()
    csv_file, file_name = init_csv()
    mesurements = 0 #zmienna przechowująca liczbe zapisanych pomiarów
    data_queue = Queue()

    # Uruchamianie wątków
    if not alternative_display:
        oled_thread = SafeThread(target=oled_update_thread, args=(display, stop_event, ui_data))
        oled_thread.start()
    mpu_thread = SafeThread(target=mpu6050_thread, args=(mpu6050.mpu, stop_event, ui_data, movement_detected, sensor_fusion))
    gps_thread = SafeThread(target=l76k_thread, args=(l76k, stop_event, ui_data, movement_detected, mesurements, pause_mesure, data_queue, sensor_fusion))
    csv_thread = SafeThread(target=csv_writer_thread, args=(csv_file, data_queue, stop_event))
    bmp_thread = SafeThread(target=bmp390_thread, args=(bmp, stop_event, ui_data, movement_detected))
    
    gps_thread.start()
    mpu_thread.start()
    csv_thread.start()
    bmp_thread.start()
    
    start_time = datetime.now()
    if alternative_display:
        display.display_message("************\nTRWA POMIAR\n_________________", 17)
    stop_mesure.state = False
    pause_mesure.state = False
    
    try:
        while True:
            stop_mesure.handle_button()
            pause_mesure.handle_button()
            
            if stop_event.is_set():
                break
            
            elapsed_time = datetime.now() - start_time
            ui_data['duration'] = str(elapsed_time).split('.')[0]
            
            if not pause_mesure.state:
                ui_data['csv_status'] = "Aktywny"
            else:
                ui_data['csv_status'] = "Zatrzymany"
                
            ui_data['queue_length'] = check_queue_length(data_queue)

            if int(time.time()) % 60 == 0:
                if check_db_connection(db):
                    ui_data['db_connection'] = "Połączono"
                else:
                    ui_data['db_connection'] = "Brak połączenia"
            
    except Exception as e:
        logging.error(f"Wystapil problem podczas glownej petli: {e}")
    
    finally:
        if not alternative_display:
            oled_thread.join()
        stop_event.set()
        mpu_thread.join()
        gps_thread.join()
        csv_thread.join()
        bmp_thread.join()
        
        display.clear()
        
        if stop_mesure.state:
            stop_mesure.state = False
            if not alternative_display:
                display.display_message(f"Pomiar zakończony\npomyślnie :)", 15)
                time.sleep(1)
            else:
                display.display_message(f"Pomiar zakończony\n Wykonane pomiary {ui_data['mesurements']}", 12)
                time.sleep(1)
            
            # Sprawdzenie połączenia przed próbą zapisu
            if check_db_connection(db):
                display.display_message(f"Trwa zapis {ui_data['mesurements']} do\nbazy danych...", 13)
                try:
                    db.upload_csv_to_db(csv_file)
                    display.display_message(f"Pomiar pomyslnie\n zapisany do\nbazy danych :)", 12)
                except Exception as e:
                    print(f"Błąd podczas importu danych do bazy: {str(e)}")
                    display.display_message("Błąd zapisu\ndo bazy danych", 13)
            else:
                display.display_message(f"\nBrak polaczenia\nz baza danych\n :(", 12)

            time.sleep(2)
        else:
            start_mesure.state = False
            display.display_message(f"\nProgram zatrzymany :(\nWystąpił błąd\nsprawdź error_logs.txt", 12)
            time.sleep(2)

        display.display_message(f"Pomiar zapisany\n\n{file_name}\n Wcisnij start aby\nzaczac nowy pomiar", 11)
        
        stop_flag = stop_mesure.state
        save_flag = pause_mesure.state
        start_flag = start_mesure.state
        
        waiting_for_input = True
        while waiting_for_input:
            start_mesure.handle_button()
            pause_mesure.handle_button()
            stop_mesure.handle_button()
            
            if stop_mesure.state is not stop_flag:
                db.close()
                sys.exit(0)
            
            if pause_mesure.state is not save_flag:
                display.display_message(f"Zapisywanie\nwszystkich pomiarów\ndo bazy danych", 13)
                db.import_all_csv_files()
                save_flag = pause_mesure.state
                display.display_message(f"Wszystkie pomiary\nzostaly pomyslnie zapisane\ndo bazy danych", 12)
                time.sleep(1.5)
                continue
            
            if start_mesure.state is not start_flag:
                waiting_for_input = False  # Zakończ pętlę oczekiwania
                break
                
            time.sleep(button_push_loop)


if __name__ == "__main__":
    # Sprawdzenie czy skrypt jest uruchomiony jako usługa
    if os.environ.get('INVOKED_BY_SYSTEMD') == 'yes':
        while True:
            try:
                main_service()
            except Exception as e:
                logging.error(f"Error in main service: {str(e)}")
    else:
        while True:
            # Uruchomienie w trybie terminala
            curses.wrapper(main)