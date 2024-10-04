import threading
import L76X
import time
import curses
import numpy as np
import csv 
import os
from config import config
from datetime import datetime

class KalmanFilter:
    def __init__(self):
        # Stan: pozycja GPS (lat, lon, alt)
        self.x = np.zeros(3)  # Wektor stanu: [lat, lon, alt]
        self.P = np.eye(3)    # Macierz błędów oszacowania
        self.F = np.eye(3)    # Macierz przejścia (stanowa)
        self.H = np.eye(3)    # Macierz obserwacji (dostosowana do trzech zmiennych: lat, lon, alt)
        self.R = np.eye(3) * 0.01  # Macierz szumów pomiarowych (dla lat, lon, alt)
        self.Q = np.eye(3) * 0.0001  # Macierz szumów procesu

    def predict(self):
        # Predykcja stanu i błędów oszacowania
        self.x = np.dot(self.F, self.x)
        self.P = np.dot(self.F, np.dot(self.P, self.F.T)) + self.Q

    def update(self, z):
        # Aktualizacja na podstawie nowych danych z GPS (lat, lon, alt)
        y = z - np.dot(self.H, self.x)  # Błąd innowacji
        S = np.dot(self.H, np.dot(self.P, self.H.T)) + self.R  # Macierz innowacji
        K = np.dot(np.dot(self.P, self.H.T), np.linalg.inv(S))  # Wzmocnienie Kalmana
        self.x += np.dot(K, y)  # Aktualizacja stanu
        self.P = np.dot((np.eye(3) - np.dot(K, self.H)), self.P)  # Aktualizacja błędów oszacowania

    def get_state(self):
        return self.x  # Zwraca współrzędne [lat, lon, alt]

# Funkcja do odczytu danych z MPU6050 (akcelerometr + żyroskop)
def read_mpu6050(mpu):
    accel = mpu.get_accel_data()  # Odczyt akcelerometru
    gyro = mpu.get_gyro_data()    # Odczyt żyroskopu
    return accel, gyro

# Wątek do odczytu z MPU6050 
def mpu6050_thread(mpu, stop_event, ui_data, movement_detected):
    mv_threshold = 1 #13.5 # Próg ruchu
    rt_threshold = 1 #100  # Próg rotacji
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
        else:
            movement_detected[0] = False  # Brak ruchu
            ui_data['move'] = f"W miejscu, movement {movement:.2f} | rotation {rotation:.2f}"

        time.sleep(0.03)  # Próbkowanie MPU6050 co 5 ms (200 Hz)

# Wątek do odczytu z L76K
def l76k_thread(l76k, kalman_filter, stop_event, ui_data, movement_detected, csv_file, mesurements):
    while not stop_event.is_set():
        l76k.L76X_Gat_GNRMC()
        if l76k.Status == 1:
            mesure_time = datetime.now().strftime("%H:%M:%S")
            gps_data = np.array([l76k.Lat, l76k.Lon, l76k.Altitude])
            kalman_filter.update(gps_data)
            kalman_filter.predict()
            lat, lon, alt = kalman_filter.get_state()
            
            # Aktualizacja danych GPS w pamięci współdzielonej (ui_data)
            ui_data['time'] = f"{l76k.Time_H:02}:{l76k.Time_M:02}:{int(l76k.Time_S):02}"
            ui_data['lat'] = l76k.Lat
            ui_data['lon'] = l76k.Lon
            ui_data['alt'] = l76k.Altitude
            ui_data['sat'] = l76k.Satellites
            l76k.L76X_Baidu_Coordinates(l76k.Lat, l76k.Lon)
            ui_data['ba.lat'] = l76k.Lat_Baidu
            ui_data['ba.lon'] = l76k.Lon_Baidu
            l76k.L76X_Google_Coordinates(l76k.Lat, l76k.Lon)
            ui_data['go.lat'] = l76k.Lat
            ui_data['go.lon'] = l76k.Lon
            ui_data['kf.lat'] = lat
            ui_data['kf.lon'] = lon
            ui_data['kf.alt'] = alt
            
            # Zapis do CSV, tylko gdy wykryto ruch
            if movement_detected[0]:
                with open(csv_file, 'a', newline='') as file:
                    mesurements += 1
                    ui_data['mesurements'] = mesurements
                    writer = csv.writer(file)
                    writer.writerow([str(mesure_time), round(l76k.Lat, 6), round(l76k.Lon, 6), l76k.Altitude])
                    
                #time.sleep(1) # Odczyt L76K co 1 sekundę (1 Hz), max czestotliwosc
        # else:
        #     ui_data['lat'] = None
        #     ui_data['lon'] = None
        #     ui_data['alt'] = None

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
    curses.curs_set(0)
    
    conf = config(baudrate=9600, mpu_address=0x68)
    l76k=L76X.L76X()
    l76k.L76X_Send_Command(l76k.SET_COLD_START)
    l76k.L76X_Set_Baudrate(9600)
    l76k.L76X_Send_Command(l76k.SET_POS_FIX_400MS)
    l76k.L76X_Send_Command(l76k.SET_NMEA_OUTPUT)
    l76k.L76X_Exit_BackupMode()
    
    # Inicjalizacja filtra Kalmana
    kf = KalmanFilter()
    
    # Współdzielona pamięć do przechowywania danych dla UI
    ui_data = {
        'datetime': None,
        'time': None,
        'lat': None,
        'lon': None,
        'ba.lat': None,
        'ba.lon': None,
        'go.lat': None,
        'go.lon': None,
        'kf.lat': None,
        'kf.lon': None,
        'kf.alt': None,
        'alt': None,
        'sat': None,
        'accel': {'x': 0, 'y': 0, 'z': 0},
        'gyro': {'x': 0, 'y': 0, 'z': 0},
        'move': None,
        'mesurements': None
    }
    
    # Flaga wykrycia ruchu
    movement_detected = [False]
    
    # Event do zatrzymywania wątków
    stop_event = threading.Event()
    
    # Inicjalizacja CSV
    csv_file = init_csv()
    mesurements = 0 #liczba zapisanych pomiarów
    
    # Uruchamianie wątków
    mpu_thread = threading.Thread(target=mpu6050_thread, args=(conf.mpu, stop_event, ui_data, movement_detected))
    gps_thread = threading.Thread(target=l76k_thread, args=(l76k, kf, stop_event, ui_data, movement_detected ,csv_file, mesurements))
    
    time.sleep(5)
    mpu_thread.start()
    gps_thread.start()
    
    try:
        while True:
            stdscr.clear()
            ui_data['datetime'] = datetime.now()

            # Nagłówek
            stdscr.addstr(0, 0, f"[MPU6050] Stan urządzenia: {ui_data['move']}")
            stdscr.addstr(1, 0, f"Akcelerometr: X={ui_data['accel']['x']:.2f}, Y={ui_data['accel']['y']:.2f}, Z={ui_data['accel']['z']:.2f}")
            stdscr.addstr(2, 0, f"Żyroskop: X={ui_data['gyro']['x']:.2f}, Y={ui_data['gyro']['y']:.2f}, Z={ui_data['gyro']['z']:.2f}")

            # Nagłówek GPS
            stdscr.addstr(4, 0, f"[L76K] {ui_data['time']}, {ui_data['datetime']}, Pomiary: {ui_data['mesurements']}")
            if ui_data['lat'] is not None:
                stdscr.addstr(5, 0, f"L76K\tLat: {ui_data['lat']:.6f}, Lon: {ui_data['lon']:.6f}, Altitude: {ui_data['alt']:.2f}, Satellites: {ui_data['sat']}")
                stdscr.addstr(6, 0, f"Kalm\tLat: {ui_data['kf.lat']:.6f}, Lon: {ui_data['kf.lon']:.6f}, Alt: {ui_data['kf.alt']:.2f}")
                stdscr.addstr(7, 0, f"Baid\tLat: {ui_data['ba.lat']:.6f}, Lon: {ui_data['ba.lon']:.6f}")
                stdscr.addstr(8, 0, f"Goog\tLat: {ui_data['go.lat']:.6f}, Lon: {ui_data['go.lon']:.6f}")
            else:
                stdscr.addstr(5, 0, "Brak ustalonej pozycji GPS")

            # Odświeżenie ekranu terminala
            stdscr.refresh()

            time.sleep(0.1)  # Aktualizacja co 100 ms
            
    except KeyboardInterrupt:
        stop_event.set()
        mpu_thread.join()
        gps_thread.join()
    
if __name__ == "__main__":
    curses.wrapper(main)
