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
from config import config
from datetime import datetime
from threading import Thread
from waveshare_OLED import OLED_0in96
from PIL import Image,ImageDraw,ImageFont

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
        GPIO.setmode(GPIO.BCM)
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

# Funkcja do obsługi wyjątków w wątkach
def thread_exception_handler(args):
    exc_type, exc_value, exc_traceback = args
    logging.error("Nieobsłużony wyjątek w wątku:\n" + 
                  ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback)))
    stop_event.set()  # Zatrzymaj wszystkie wątki

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
            'move_status': (72, 0),
            'csv_status': (2, 14), 
            'measurements': (90, 14),
            'duration': (2, 26),
            'hdop': (2, 38),'sat': (60, 38),
            'status': (2, 14)
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

        #updated |= self.update_field('move_status', f"{ui_data['move_status']}")
        updated |= self.update_field('duration', f"{ui_data['duration']}")
        updated |= self.update_field('csv_status', f"Zapis: {ui_data['csv_status']} - [{ui_data['mesurements']}]" if ui_data['mesurements'] is not None else f"Zapis: {ui_data['csv_status']} - [brak]")
        #updated |= self.update_field('measurements', f"- {ui_data['mesurements']}")
        updated |= self.update_field('alt', f"Wys: {ui_data['alt']:.2f} - {ui_data['move_status']}" if ui_data['alt'] is not None else f"NO SIGNAL - {ui_data['move_status']}")
        #updated |= self.update_field('sat', f"sat: {ui_data['sat']}" if ui_data['sat'] is not None else "sat: N/A")
        updated |= self.update_field('hdop', f"HDOP: {ui_data['hdop']} Sat: {ui_data['sat']}" if ui_data['sat'] is not None else "HDOP: N/A Sat: N/A")

        if updated:
            self.oled.ShowImage(self.oled.getbuffer(self.image))
            self.last_update_time = current_time

# Funkcja do aktualizacji wyświetlacza OLED
def oled_update_thread(display, stop_event, ui_data):
    while not stop_event.is_set():
        display.display_data(ui_data)
        time.sleep(0.05)  # Aktualizacja co 50 ms

# Funkcja do odczytu danych z MPU6050 (akcelerometr + żyroskop)
def read_mpu6050(mpu):
    accel = mpu.get_accel_data()  # Odczyt akcelerometru
    gyro = mpu.get_gyro_data()    # Odczyt żyroskopu
    return accel, gyro

# Wątek do odczytu z MPU6050 
def mpu6050_thread(mpu, stop_event, ui_data, movement_detected):
    mv_threshold = 0 #13.5 Próg ruchu
    rt_threshold = 0 #100  Próg rotacji
    while not stop_event.is_set():
        accel, gyro = read_mpu6050(mpu)
        movement = abs(accel['x']) + abs(accel['y']) + abs(accel['z']) # Wektor przyspieszenia ruchu
        rotation = abs(gyro['x']) + abs(gyro['y']) + abs(gyro['z'])
        ui_data['accel'] = accel
        ui_data['gyro'] = gyro

        # Sprawdzanie, czy urządzenie jest w ruchu
        if movement > mv_threshold and rotation > rt_threshold:
            movement_detected[0] = True  # Wykryto ruch
            ui_data['move'] = f"W ruchu, movement {movement:.2f} | rotation {rotation:.2f}"
            ui_data['move_status'] = "W ruchu"
        else:
            movement_detected[0] = False  # Brak ruchu
            ui_data['move'] = f"W miejscu, movement {movement:.2f} | rotation {rotation:.2f}"
            ui_data['move_status'] = "W miejscu"

        time.sleep(0.05)  # Próbkowanie MPU6050 co 5 ms (200 Hz)

# Wątek do odczytu z L76K
def l76k_thread(l76k, stop_event, ui_data, movement_detected, csv_file, mesurements, pause_mesure):
    global mesurement_saveing
    while not stop_event.is_set():
        l76k.L76X_Gat_GNGGA()
        if l76k.Status == 1:
            mesure_time = datetime.now().strftime("%H:%M:%S")
            
            # Aktualizacja danych GPS w pamięci współdzielonej (ui_data)
            ui_data['time'] = f"{l76k.Time_H:02}:{l76k.Time_M:02}:{int(l76k.Time_S):02}"
            ui_data['lat'] = l76k.Lat
            ui_data['lon'] = l76k.Lon
            ui_data['alt'] = l76k.Altitude
            ui_data['sat'] = l76k.Satellites
            ui_data['hdop'] = l76k.HDOP
            ui_data['quality_index'] = l76k.Quality_Indicator
            
            # Zapis do CSV, tylko gdy wykryto ruch
            if movement_detected[0]:
                if not pause_mesure.state:
                    ui_data['csv_status'] = "Aktywny"
                    with open(csv_file, 'a', newline='') as file:
                        mesurements += 1
                        ui_data['mesurements'] = mesurements
                        writer = csv.writer(file)
                        writer.writerow([str(mesure_time), round(l76k.Lat, 6), round(l76k.Lon, 6), l76k.Altitude])
                else:
                    ui_data['csv_status'] = "Zatrzymany"
        
        #time.sleep(0.5)  # Próbkowanie GPS co 500 ms

def init_csv():
    # Nazwa pliku na podstawie czasu rozpoczęcia sesji
    measure_datetime = datetime.now().strftime("%d%m%y_%H%M%S")
    folder_path = "measurements"
    csv_file = os.path.join(folder_path, f'dane{measure_datetime}.csv')
    
    # Tworzenie pliku z nagłówkiem
    with open(csv_file, 'w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["Time", "Latitude", "Longitude", "Altitude"])
    
    #print(f"Zapis pomiarów do pliku: {csv_file}")
    return csv_file

def main(stdscr):
    global stop_event
    curses.curs_set(0)
    display = Display()

    # Display initialization message on OLED
    display.display_message("Terrain Mapper\nInicjalizacja...")

    # Event do zatrzymywania wątków
    stop_event = threading.Event()
    
    #inicjalizacja przycisku
    stop_mesure = Button(13, 1, False, stop_event.set)
    pause_mesure = Button(26, 0.3, False)
    start_mesure = Button(26, 0.3, False)
    
    conf = config(baudrate=9600, mpu_address=0x68)
    l76k=L76X.L76X()
    l76k.L76X_Send_Command(l76k.SET_COLD_START)
    #print("L76K cold start")
    #time.sleep(30)
    l76k.L76X_Set_Baudrate(9600)
    l76k.L76X_Send_Command(l76k.SET_POS_FIX_400MS)
    l76k.L76X_Send_Command(l76k.SET_NMEA_OUTPUT)
    l76k.L76X_Exit_BackupMode()
    
    # Współdzielona pamięć do przechowywania danych dla UI terminala
    ui_data = {
        'duration': None,
        'time': None,
        'lat': None,
        'lon': None,
        'alt': None,
        'sat': None,
        'accel': {'x': 0, 'y': 0, 'z': 0},
        'gyro': {'x': 0, 'y': 0, 'z': 0},
        'move': None,
        'move_status': None,
        'mesurements': None,
        'hdop': None,
        'quality_index': None,
        'csv_status': None
    }
    
    # Flaga wykrycia ruchu
    movement_detected = [False]
    
    print("Oczekiwanie na naciśnięcie przycisku start")
    display.display_message("Wcisnij przycisk\nstart")
    while not start_mesure.state:
        start_mesure.handle_button()
        time.sleep(0.1)

    # Inicjalizacja CSV
    display.clear()
    csv_file = init_csv()
    mesurements = 0 #liczba zapisanych pomiarów
    
    # Uruchamianie wątków
    mpu_thread = SafeThread(target=mpu6050_thread, args=(conf.mpu, stop_event, ui_data, movement_detected))
    gps_thread = SafeThread(target=l76k_thread, args=(l76k, stop_event, ui_data, movement_detected ,csv_file, mesurements, pause_mesure))
    oled_thread = SafeThread(target=oled_update_thread, args=(display, stop_event, ui_data))
    gps_thread.start()
    oled_thread.start()
    mpu_thread.start()
    start_time = datetime.now()
    
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
            
            # Nagłówek czujnika ruchu UI TERMINALA
            stdscr.addstr(0, 0, f"[MPU6050] Stan urządzenia: {ui_data['move']}")
            stdscr.addstr(1, 0, f"Akcelerometr: X={ui_data['accel']['x']:.2f}, Y={ui_data['accel']['y']:.2f}, Z={ui_data['accel']['z']:.2f}")
            stdscr.addstr(2, 0, f"Żyroskop: X={ui_data['gyro']['x']:.2f}, Y={ui_data['gyro']['y']:.2f}, Z={ui_data['gyro']['z']:.2f}")
            
            # Nagłówek GPS UI TERMINALA
            stdscr.addstr(4, 0, f"[L76K] {ui_data['time']}, Czas pomiaru {ui_data['duration']} Zapis pomiarów: {ui_data['csv_status']}, Pomiary: {ui_data['mesurements']}")
            try:
                # UI TERMINALA
                lat = f"{ui_data['lat']:.6f}" if ui_data['lat'] is not None else "N/A"
                lon = f"{ui_data['lon']:.6f}" if ui_data['lon'] is not None else "N/A"
                alt = f"{ui_data['alt']:.2f}" if ui_data['alt'] is not None else "N/A"
                sat = f"{ui_data['sat']}" if ui_data['sat'] is not None else "N/A"
                hdop = f"{ui_data['hdop']}" if ui_data['hdop'] is not None else "N/A"
                stdscr.addstr(5, 0, f"L76K\tLat,Lon: {lat}, {lon}, Altitude: {alt}, Satellites: {sat}")
                stdscr.addstr(6, 0, f"index HDOP: {hdop}")
            except TypeError:
                stdscr.addstr(5, 0, "L76K\tLat,Lon: N/A, N/A, Altitude: N/A, Satellites: N/A")
                stdscr.addstr(6, 0, "Quality Indicator: N/A, HDOP: N/A")

            # Odświeżenie ekranu terminala
            stdscr.refresh()
            time.sleep(0.1)  # Aktualizacja co 100 ms
            
    except KeyboardInterrupt:
            pass
    finally:
        stop_event.set()
        mpu_thread.join()
        gps_thread.join()
        oled_thread.join()
        
        # Wyświetl informację o błędzie, jeśli wystąpił
        stdscr.clear()
        display.clear()
        if stop_mesure.state:
            start_mesure.state = False
            display.display_message("Pomiar\nzakończony :)")
            print("\nProgram zakończony pomyślnie.")
        else:
            start_mesure.state = False
            display.display_message("Wystapil blad :(")
            print("\nProgram zatrzymany. Sprawdź plik error_log.txt, aby zobaczyć szczegóły błędu.")

        stdscr.refresh()
        #stdscr.getch()  # Czekaj na naciśnięcie klawisza

        print("\nWciśnij przycisk start, aby rozpocząć nowy pomiar")
        display.display_message("Wcisnij start aby\nzaczac nowy pomiar")
        while not start_mesure.state:
            start_mesure.handle_button()
            time.sleep(0.1)

if __name__ == "__main__":
    while True:
        curses.wrapper(main)
