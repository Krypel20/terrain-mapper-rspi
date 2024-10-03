import L76X
import time
import math
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


# Funkcja do odczytu danych z MPU6050
def read_mpu6050(mpu):
    accel = mpu.get_accel_data()  # Odczyt akcelerometru
    gyro = mpu.get_gyro_data()    # Odczyt żyroskopu
    return accel, gyro

try:
    conf = config(baudrate=9600, mpu_address=0x68)
    x=L76X.L76X()
    x.L76X_Set_Baudrate(9600)
    #x.L76X_Send_Command(x.SET_NMEA_BAUDRATE_115200)
    #time.sleep(2)
    #x.L76X_Set_Baudrate(115200)
    x.L76X_Send_Command(x.SET_POS_FIX_400MS);
    #Set output message
    x.L76X_Send_Command(x.SET_NMEA_OUTPUT);
    x.L76X_Exit_BackupMode();
    
    # Inicjalizacja filtra Kalmana
    kf = KalmanFilter()
    
    while(1):
        x.L76X_Gat_GNRMC()
        if(x.Status == 1):
            print('Already positioned')
        else:
            print('No positioning')
            
        print('Time:','{:02}'.format(x.Time_H),':{:02}'.format(x.Time_M),':{:02}'.format(int(x.Time_S)))
        print('Lon = %f'%x.Lon,'  Lat=',x.Lat,'  Alt=',x.Altitude,'  Sat=',x.Satellites)
        x.L76X_Baidu_Coordinates(x.Lat, x.Lon)
        print('Baidu coordinate ',x.Lat_Baidu,',',x.Lon_Baidu)
        x.L76X_Google_Coordinates(x.Lat, x.Lon)
        print('Google coordinate ', x.Lat,',',x.Lon)
        
        # Odczyt danych z MPU6050
        accel, gyro = read_mpu6050(conf.mpu)
        print(f"Accel: {accel} \nGyro: {gyro}")

        # Aktualizowanie filtra z danymi GPS (lat, lon)
        gps_data = np.array([x.Lat, x.Lon, 0, 0])  # Dodaj dane GPS google
        kf.update(gps_data)
        kf.predict()
        
        lat, lon = kf.get_state()
        print(f'Przewidywana lokalizacja Google: ', lat,',',lon)
        
        gps_data = np.array([x.Lat_Baidu, x.Lon_Baidu, 0, 0])  # Dodaj dane GPS baidu
        kf.update(gps_data)

        kf.predict()
        lat, lon = kf.get_state()
        print(f'Przewidywana lokalizacja Baidu: ', lat,',',lon)
        
        # Zapis danych do pliku (dodajemy nową funkcję zapisu danych)
        with open('dane.csv', 'a')  as f:
            f.write(f"{time.time()}, {x.Lat}, {x.Lon}, {x.Altitude}, {accel}, {gyro}\n")
        
        time.sleep(1)  # Odczyty co 200ms (5 razy na sekundę)
                
except KeyboardInterrupt:
    #GPIO.cleanup()
    print("\nProgram end")
    exit()
