import threading
import L76X
import time
import curses
import numpy as np
from config import config

class KalmanFilter:
    def __init__(self):
        # Stan: pozycja GPS (x, y) oraz prędkość (vx, vy)
        self.x = np.zeros(4)  # Wektor stanu: [lat, lon, v_lat, v_lon]
        self.P = np.eye(4)    # Macierz błędów oszacowania
        self.F = np.eye(4)    # Macierz przejścia
        self.H = np.eye(4)    # Macierz obserwacji
        self.R = np.eye(4) * 0.01  # Macierz szumów pomiarowych
        self.Q = np.eye(4) * 0.0001  # Macierz szumów procesu

    def predict(self):
        # Predykcja stanu i błędów oszacowania
        self.x = np.dot(self.F, self.x)
        self.P = np.dot(self.F, np.dot(self.P, self.F.T)) + self.Q

    def update(self, z):
        # Aktualizacja na podstawie nowych danych z GPS
        y = z - np.dot(self.H, self.x)  # Błąd innowacji
        S = np.dot(self.H, np.dot(self.P, self.H.T)) + self.R  # Macierz innowacji
        K = np.dot(np.dot(self.P, self.H.T), np.linalg.inv(S))  # Wzmocnienie Kalmana
        self.x += np.dot(K, y)  # Aktualizacja stanu
        self.P = np.dot((np.eye(4) - np.dot(K, self.H)), self.P)  # Aktualizacja błędów oszacowania

    def get_state(self):
        return self.x[:2]  # Zwraca tylko współrzędne [lat, lon]

# Wątek do odczytu z MPU6050
def mpu6050_thread(mpu, stop_event, ui_data):
    while not stop_event.is_set():
        accel, gyro = read_mpu6050(mpu)
        ui_data['accel'] = accel
        ui_data['gyro'] = gyro
        time.sleep(0.01)  # Próbkowanie MPU6050 co 10 ms (100 Hz)

# Wątek do odczytu z L76K
def l76k_thread(l76k, kalman_filter, stop_event, ui_data):
    while not stop_event.is_set():
        l76k.L76X_Gat_GNRMC()
        if l76k.Status == 1:
            #print('Pozycja ustalona')
            gps_data = np.array([l76k.Lat, l76k.Lon, 0, 0])
            kalman_filter.update(gps_data)
            kalman_filter.predict()
            lat, lon = kalman_filter.get_state()
            
            # Aktualizacja danych GPS w pamięci współdzielonej (ui_data)
            ui_data['time'] = f"{l76k.Time_H-6:02}:{l76k.Time_M:02}:{int(l76k.Time_S):02}"
            ui_data['lat'] = l76k.Lat
            ui_data['lon'] = l76k.Lon
            ui_data['sat'] = l76k.Satellites
            l76k.L76X_Baidu_Coordinates(l76k.Lat, l76k.Lon)
            ui_data['ba.lat'] = l76k.Lat_Baidu
            ui_data['ba.lon'] = l76k.Lon_Baidu
            l76k.L76X_Google_Coordinates(l76k.Lat, l76k.Lon)
            ui_data['go.lat'] = l76k.Lat
            ui_data['go.lon'] = l76k.Lon
            ui_data['kf.lat'] = lat
            ui_data['kf.lon'] = lon
            ui_data['alt'] = l76k.Altitude
            
            # print('Lon = %f'%l76k.Lon,'  Lat=',l76k.Lat,'  Alt=',l76k.Altitude,'  Sat=',l76k.Satellites)
            # l76k.L76X_Baidu_Coordinates(l76k.Lat, l76k.Lon)
            # print('Baidu coordinate ',l76k.Lat_Baidu,',',l76k.Lon_Baidu)
            # l76k.L76X_Google_Coordinates(l76k.Lat, l76k.Lon)
            # print('Google coordinate ', l76k.Lat,',',l76k.Lon)
            # print('Przewidywana lokalizacja ', lat,',',lon)
        else:
            print('')
            #print('Brak ustalonej pozycji')
        
        time.sleep(1)  # Odczyt L76K co 1 sekundę (1 Hz), max czestotliwosc

# Funkcja do odczytu danych z MPU6050
def read_mpu6050(mpu):
    accel = mpu.get_accel_data()  # Odczyt akcelerometru
    gyro = mpu.get_gyro_data()    # Odczyt żyroskopu
    return accel, gyro

def main(stdscr):
    curses.curs_set(0)
    
    conf = config(baudrate=9600, mpu_address=0x68)
    l76k=L76X.L76X()
    l76k.L76X_Set_Baudrate(9600)
    l76k.L76X_Send_Command(l76k.SET_POS_FIX_400MS)
    l76k.L76X_Send_Command(l76k.SET_NMEA_OUTPUT)
    l76k.L76X_Exit_BackupMode()
    
    # Inicjalizacja filtra Kalmana
    kf = KalmanFilter()
    
    # Współdzielona pamięć do przechowywania danych dla UI
    ui_data = {
        'time': None,
        'lat': None,
        'lon': None,
        'ba.lat': None,
        'ba.lon': None,
        'go.lat': None,
        'go.lon': None,
        'kf.lat': None,
        'kf.lon': None,
        'alt': None,
        'sat': None,
        'accel': {'x': 0, 'y': 0, 'z': 0},
        'gyro': {'x': 0, 'y': 0, 'z': 0}
    }
    
    # Event do zatrzymywania wątków
    stop_event = threading.Event()
    
    # Uruchamianie wątków
    mpu_thread = threading.Thread(target=mpu6050_thread, args=(conf.mpu, stop_event, ui_data))
    gps_thread = threading.Thread(target=l76k_thread, args=(l76k, kf, stop_event, ui_data))

    mpu_thread.start()
    gps_thread.start()
    
    try:
        while True:
            # Aktualizacja danych na ekranie co 100 ms
            stdscr.clear()

            # Nagłówek
            stdscr.addstr(0, 0, "[MPU6050]")
            stdscr.addstr(1, 0, f"Akcelerometr: X={ui_data['accel']['x']:.2f}, Y={ui_data['accel']['y']:.2f}, Z={ui_data['accel']['z']:.2f}")
            stdscr.addstr(2, 0, f"Żyroskop: X={ui_data['gyro']['x']:.2f}, Y={ui_data['gyro']['y']:.2f}, Z={ui_data['gyro']['z']:.2f}")

            # Nagłówek GPS
            stdscr.addstr(4, 0, f"[L76K] {ui_data['time']}")
            if ui_data['lat'] is not None:
                stdscr.addstr(5, 0, f"L76K\tLat: {ui_data['lat']:.6f}, Long: {ui_data['lon']:.6f}, Altitude: {ui_data['alt']:.2f}, Satellites: {ui_data['sat']}")
                stdscr.addstr(6, 0, f"Goog\tLat: {ui_data['go.lat']:.6f}, Long: {ui_data['go.lon']:.6f}")
                stdscr.addstr(7, 0, f"Baid\tLat: {ui_data['ba.lat']:.6f}, Long: {ui_data['ba.lon']:.6f}")
                stdscr.addstr(8, 0, f"Kfil\tLat: {ui_data['kf.lat']:.6f}, Long: {ui_data['kf.lon']:.6f}")
            else:
                stdscr.addstr(5, 0, "Brak ustalonej pozycji GPS")

            # Odświeżenie ekranu terminala
            stdscr.refresh()
            time.sleep(0.1)  # Aktualizacja co 100 ms
            
    except KeyboardInterrupt:
        stop_event.set()
        mpu_thread.join()
        gps_thread.join()
        print("end")
        
    print("Program zakończony")
    
if __name__ == "__main__":
    curses.wrapper(main)
