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
from queue import Queue, Empty

mpu6050_sleep = 0.2
l76k_sleep = 0.2
oled_sleep = 1
terminal_ui_sleep = 0.1
button_push_loop = 0.01

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
            #'move_status': (72, 0),
            'csv_status': (2, 14), 
            #'measurements': (90, 14),
            'duration': (2, 26),
            'hdop': (2, 38),'sat': (60, 38),
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
        time.sleep(oled_sleep)  # Aktualizacja co 100 ms max

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

        time.sleep(mpu6050_sleep)  # Próbkowanie MPU6050 co 150ms

# Wątek do odczytu z L76K
def l76k_thread(l76k, stop_event, ui_data, movement_detected, mesurements, pause_mesure, data_queue):
    global mesurement_saveing
    last_measurement_time = None
    
    while not stop_event.is_set():
        l76k.L76X_Gat_GNGGA()
        if l76k.Status == 1:
            current_time = datetime.now()
            mesure_time = current_time.strftime("%H:%M:%S")
            
            # Obliczanie opóźnienia pomiędzy pomiarami
            if last_measurement_time is not None:
                delay = (current_time - last_measurement_time).total_seconds()
                ui_data['delay'] = delay
            else:
                ui_data['delay'] = None  # Brak poprzedniego pomiaru
            
            last_measurement_time = current_time  # Aktualizacja czasu ostatniego pomiaru
            
            # Aktualizacja danych GPS w pamięci współdzielonej (ui_data)
            ui_data['time'] = f"{l76k.Time_H:02}:{l76k.Time_M:02}:{int(l76k.Time_S):02}"
            ui_data['lat'] = l76k.Lat
            ui_data['lon'] = l76k.Lon
            ui_data['alt'] = l76k.Altitude
            ui_data['sat'] = l76k.Satellites
            ui_data['hdop'] = l76k.HDOP
            ui_data['vdop'] = l76k.VDOP
            ui_data['pdop'] = l76k.PDOP
            ui_data['gnss_system'] = l76k.GNSS_system
            
            # Zapis do CSV, tylko gdy wykryto ruch
            if movement_detected[0] and not pause_mesure.state:
                ui_data['csv_status'] = "Aktywny"
                if l76k.Altitude:
                    mesurements += 1
                    ui_data['mesurements'] = mesurements
                    data_queue.put([str(mesure_time), round(l76k.Lat, 6), round(l76k.Lon, 6), l76k.Altitude])
            else:
                ui_data['csv_status'] = "Zatrzymany"
        
        time.sleep(l76k_sleep)  # Próbkowanie GPS co 500 ms

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

def init_csv():
    # Nazwa pliku na podstawie czasu rozpoczęcia sesji
    measure_datetime = datetime.now().strftime("%d%m%y_%H%M%S")
    folder_path = "measurements"
    file_name = f'tm{measure_datetime}.csv'
    csv_file = os.path.join(folder_path, file_name)
    
    # Tworzenie pliku z nagłówkiem
    with open(csv_file, 'w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(["time", "latitude", "longitude", "altitude"])
    
    return csv_file, file_name

# Funkcja do sprawdzania długości kolejki
def check_queue_length(measurements_queue):
    queue_length = measurements_queue.qsize()
    return queue_length

def main(stdscr):
    global stop_event
    NO_OLED = False
    curses.curs_set(0)
    display = Display()
    display.display_message("Terrain Mapper\nInicjalizacja...", 15)

    # Event do zatrzymywania wątków
    stop_event = threading.Event()
    
    conf = config(baudrate=9600, mpu_address=0x68)
    l76k=L76X.L76X()
    l76k.L76X_Send_Command(l76k.SET_COLD_START)
    # print("L76K cold start")
    # time.sleep(30)
    
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
        'vdop': None,
        'pdop': None,
        'gnss_system': None,
        'quality_index': None,
        'csv_status': None,
        'queue_length': None,
        'delay': None,
    }
    
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
            NO_OLED = True
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
    mesurements = 0 #liczba zapisanych pomiarów
    data_queue = Queue()

    # Uruchamianie wątków
    if not NO_OLED:
        oled_thread = SafeThread(target=oled_update_thread, args=(display, stop_event, ui_data))
        oled_thread.start()
    mpu_thread = SafeThread(target=mpu6050_thread, args=(conf.mpu, stop_event, ui_data, movement_detected))
    gps_thread = SafeThread(target=l76k_thread, args=(l76k, stop_event, ui_data, movement_detected, mesurements, pause_mesure, data_queue))
    csv_thread = SafeThread(target=csv_writer_thread, args=(csv_file, data_queue, stop_event))
    gps_thread.start()
    mpu_thread.start()
    csv_thread.start()
    
    start_time = datetime.now()
    if NO_OLED:
        display.display_message("************\nTRWA POMIAR\n_________________", 17)
    stop_mesure.state = False
    pause_mesure.state = False
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
                gnss_system = f"{ui_data['gnss_system']}" if ui_data['gnss_system'] is not None else "N/A"
                stdscr.addstr(5, 0, f"L76K\tLat,Lon: {lat}, {lon}, Altitude: {alt}, Satellites: {sat}")
                stdscr.addstr(6, 0, f"[index] HDOP: {hdop}, VDOP: {vdop}, PDOP: {pdop}, GNSS: {gnss_system}")
            except TypeError:
                stdscr.addstr(5, 0, "L76K\tLat,Lon: N/A, N/A, Altitude: N/A, Satellites: N/A")
                stdscr.addstr(6, 0, "HDOP: N/A, VDOP: N/A, PDOP: N/A, GNSS: N/A")

            # Odświeżenie ekranu terminala
            stdscr.refresh()
            time.sleep(terminal_ui_sleep)
            
    except KeyboardInterrupt:
            pass
    finally:
        if not NO_OLED:
            oled_thread.join()
        stop_event.set()
        mpu_thread.join()
        gps_thread.join()
        csv_thread.join()
        
        # Wyświetl informację o błędzie, jeśli wystąpił
        stdscr.clear()
        display.clear()
        if stop_mesure.state:
            start_mesure.state = False
            if not NO_OLED:
                display.display_message(f"Pomiar zakończony\npomyślnie :)", 15)
            else:
                display.display_message(f"Pomiar zakończony\n Wykonane pomiary {ui_data['mesurements']}", 12)
            print("\nProgram zakończony pomyślnie.")
            time.sleep(2)
        else:
            start_mesure.state = False
            display.display_message(f"\nProgram zatrzymany :(\nWystąpił błąd\nsprawdź error_logs.txt", 12)
            print("\nProgram zatrzymany :(\nSprawdź plik error_log.txt\naby zobaczyć szczegóły błędu.")
            time.sleep(1.25)

        stdscr.refresh()
        #stdscr.getch()  # Czekaj na naciśnięcie klawisza
        print(f"Zapisano do {file_name}\nWciśnij przycisk start, aby rozpocząć nowy pomiar")
        display.display_message(f"Pomiar zapisany do\n\n{file_name}\n Wcisnij start aby\nzaczac nowy pomiar")
        
        flag = stop_mesure.state
        while not start_mesure.state:
            start_mesure.handle_button()
            if stop_mesure.state is not flag:
                sys.exit(0)
            time.sleep(button_push_loop)

if __name__ == "__main__":
    while True:
        curses.wrapper(main)
