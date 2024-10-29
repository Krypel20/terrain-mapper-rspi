import RPi.GPIO as GPIO
import config
import math
import time
import io
from micropyGPS import MicropyGPS
import logging

g = MicropyGPS(+8)
Temp = '0123456789ABCDEF*'
BUFFSIZE = 1100

pi = 3.14159265358979324
a = 6378245.0
ee = 0.00669342162296594323
x_pi = 3.14159265358979324 * 3000.0 / 180.0


class L76X(object):
    GNSS_SYSTEMS = {
        1: "GPS",
        2: "GLONASS",
        3: "GALILEO",
        5: "BEIDOU"
    }
    
    Lon = 0.0
    Lat = 0.0
    LonGNRMC = 0.0
    LatGNRMC = 0.0
    Altitude = 0.0
    Lon_area = 'E'
    Lat_area = 'W'
    Time_H = 0
    Time_M = 0
    Time_S = 0
    Status = 0
    Satellites = 0
    Quality_Indicator = 0
    HDOP = 0.0  # Dokładność pozioma (HDOP)
    VDOP = 0.0  # Dokładność pionowa (VDOP)
    PDOP = 0.0  # Dokładność położenia (PDOP)
    GNSS_system = "Unknown"  # System GNSS
    Lon_Baidu = 0.0
    Lat_Baidu = 0.0
    Lon_Google = 0.0
    Lat_Google = 0.0
    
    GPS_Lon = 0
    GPS_Lat = 0
    GPS_Alt = 0
    
    # Startup mode
    SET_HOT_START = '$PMTK101'
    SET_WARM_START = '$PMTK102'
    SET_COLD_START = '$PMTK103'
    SET_FULL_COLD_START = '$PMTK104'

    # Standby mode -- Exit requires high level trigger
    SET_PERPETUAL_STANDBY_MODE = '$PMTK161'

    SET_PERIODIC_MODE = '$PMTK225'
    SET_NORMAL_MODE = '$PMTK225,0'
    SET_PERIODIC_BACKUP_MODE = '$PMTK225,1,1000,2000'
    SET_PERIODIC_STANDBY_MODE = '$PMTK225,2,1000,2000'
    SET_PERPETUAL_BACKUP_MODE = '$PMTK225,4'
    SET_ALWAYSLOCATE_STANDBY_MODE = '$PMTK225,8'
    SET_ALWAYSLOCATE_BACKUP_MODE = '$PMTK225,9'

    # Set the message interval,100ms~10000ms
    SET_POS_FIX = '$PMTK220'
    SET_POS_FIX_100MS = '$PMTK220,100'
    SET_POS_FIX_200MS = '$PMTK220,200'
    SET_POS_FIX_400MS = '$PMTK220,400'
    SET_POS_FIX_800MS = '$PMTK220,800'
    SET_POS_FIX_1S = '$PMTK220,1000'
    SET_POS_FIX_2S = '$PMTK220,2000'
    SET_POS_FIX_4S = '$PMTK220,4000'
    SET_POS_FIX_8S = '$PMTK220,8000'
    SET_POS_FIX_10S = '$PMTK220,10000'

    # Switching time output
    SET_SYNC_PPS_NMEA_OFF = '$PMTK255,0'
    SET_SYNC_PPS_NMEA_ON = '$PMTK255,1'

    # To restore the system default setting
    SET_REDUCTION = '$PMTK314,-1'

    # Set NMEA sentence output frequencies 
    SET_NMEA_OUTPUT = '$PMTK314,1,1,1,1,1,1,1,1,0,0,0,0,0,0,0,0,0,1,0'
    # Baud rate
    SET_NMEA_BAUDRATE = '$PMTK251'
    SET_NMEA_BAUDRATE_115200 = '$PMTK251,115200'
    SET_NMEA_BAUDRATE_57600 = '$PMTK251,57600'
    SET_NMEA_BAUDRATE_38400 = '$PMTK251,38400'
    SET_NMEA_BAUDRATE_19200 = '$PMTK251,19200'
    SET_NMEA_BAUDRATE_14400 = '$PMTK251,14400'
    SET_NMEA_BAUDRATE_9600 = '$PMTK251,9600'
    SET_NMEA_BAUDRATE_4800 = '$PMTK251,4800'

    def __init__(self):
        self.config = config.config(9600)

    def L76X_Send_Command(self, data):
        Check = ord(data[1])
        for i in range(2, len(data)):
            Check = Check ^ ord(data[i])
        data = data + Temp[16]
        data = data + Temp[(Check // 16)]
        data = data + Temp[(Check % 16)]
        self.config.Uart_SendString(data.encode())
        self.config.Uart_SendByte('\r'.encode())
        self.config.Uart_SendByte('\n'.encode())
        #print(data)

    def L76X_Gat_GNGGA(self):
        data = ''
        while True:
            if g.valid:
                self.Status = 1
            else:
                self.Status = 0
            x = self.config.Uart_ReceiveByte()
            try: 
                if x == b'$':
                    while x != b'\r':
                        data += x.decode('utf-8')
                        g.update(x.decode())
                        x = self.config.Uart_ReceiveByte()
                    data += '\r\n'
                    if '$GNGLL' in data:
                        break
            except UnicodeDecodeError:
                logging.warning(f"Wystąpił problem z dekodowaniem UTF-8. Użyto zastępczego dekodowania. Oryginalne dane: {data}")

        # Odczyt czasu
        self.Time_H = g.timestamp[0]
        self.Time_M = g.timestamp[1]
        self.Time_S = g.timestamp[2]
        
        # Odczyt danych z frazy GNGGA 
        start_index = data.find("$GNGGA")
        end_index = data.find("\n", start_index)
        if end_index == -1:  # Jeśli to ostatnia linia w ciągu
            gngga_line = data[start_index:]
        else:
            gngga_line = data[start_index:end_index]
        
        if gngga_line:
            self.Altitude = self.get_altitude(gngga_line)
            self.HDOP = self.get_hdop(gngga_line)
            self.Satellites = self.get_satellites(gngga_line)
            self.Lat, self.Lon = self.get_coordinates_from_gngga(gngga_line)
            
        # Odczyt danych z frazy GNGSA
        start_index = data.find("$GNGSA")
        end_index = data.find("\n", start_index)
        if end_index == -1:  # Jeśli to ostatnia linia w ciągu
            gngsa_line = data[start_index:]
        else:
            gngsa_line = data[start_index:end_index]
        
        if gngsa_line:
            self.PDOP = self.get_pdop(gngsa_line)
            self.VDOP = self.get_vdop(gngsa_line)
            self.GNSS_system = self.get_gnss_system(gngsa_line)
            
        #print(data)
        data = '\r\n'
    
    def get_coordinates_from_gngga(self, nmea_sentence):
        """
        Funkcja parsująca współrzędne z frazy $GNGGA.
        """
        fields = nmea_sentence.split(',')
        if fields[0] == "$GNGGA":
            try:
                # Szerokość geograficzna
                raw_lat = fields[2] 
                lat_area = fields[3] 
                # Długość geograficzna
                raw_lon = fields[4]
                lon_area = fields[5] 

                # Przetwarzanie szerokości geograficznej
                latitude = float(raw_lat[:2]) + (float(raw_lat[2:]) / 60)
                if lat_area == 'S':
                    latitude = -latitude

                # Przetwarzanie długości geograficznej
                longitude = float(raw_lon[:3]) + (float(raw_lon[3:]) / 60)
                if lon_area == 'W':
                    longitude = -longitude

                return latitude, longitude
            except (IndexError, ValueError):
                return None, None
                
        return None, None
    
    
    def get_altitude(self, nmea_sentence):
        #Funkcja parsująca wysokość z frazy $GNGGA.
        fields = nmea_sentence.split(',')
        if fields[0] == "$GNGGA":
            try:
                altitude = fields[9]  # Pole z wysokością
                unit = fields[10]  # Jednostka wysokości (powinna być "M" dla metrów)
                if altitude and unit == 'M':
                    return float(altitude)
                else:
                    return None
            except (IndexError, ValueError):
                return None
        return None
    
    def get_satellites(self, nmea_sentence):
        #Funkcja parsująca liczbe satelit z frazy $GNGGA.
        fields = nmea_sentence.split(',')
        if fields[0] == "$GNGGA":
            try:
                satellites = fields[7]  # Pole z liczbą satelit
                if satellites:
                    return int(satellites)
                else:
                    return None
            except (IndexError, ValueError):
                return None
        return None
    
    def get_quality_indicator(self, nmea_sentence):
        """
        Funkcja parsująca wskaźnik jakości sygnału GPS z frazy $GNGGA.
        """
        fields = nmea_sentence.split(',')
        if fields[0] == "$GNGGA":
            try:
                # Wskaźnik jakości sygnału znajduje się w polu 6
                quality = fields[6]
                if quality.isdigit():
                    return int(quality)
                else:
                    return None
            except (IndexError, ValueError):
                return None

    def get_hdop(self, nmea_sentence):
        """
        Funkcja parsująca HDOP (dokładność pozioma) z frazy $GNGGA.
        """
        fields = nmea_sentence.split(',')
        if fields[0] == "$GNGGA":
            try:
                # HDOP znajduje się w polu 8 w GNGGA
                hdop = fields[8]
                if hdop:
                    return float(hdop)
                else:
                    return None
            except (IndexError, ValueError):
                return None
    
    def get_pdop(self, nmea_sentence):
        fields = nmea_sentence.split(',')
        if fields[0] == "$GNGSA":
            try:
                # PDOP znajduje się w polu 4
                pdop = fields[4]
                if pdop:
                    return float(pdop)
                else:
                    return None
            except (IndexError, ValueError):
                return None
    
    def get_vdop(self, nmea_sentence):
        fields = nmea_sentence.split(',')
        if fields[0] == "$GNGSA":
            try:
                # VDOP znajduje się w polu 6
                vdop = fields[6]
                if vdop:
                    return float(vdop)
                else:
                    return None
            except (IndexError, ValueError):
                return None
    
    def get_gnss_system(self, nmea_sentence):
        fields = nmea_sentence.split(',')
        if fields[0] == "$GNGSA":
            try:
                # ID systemu GNSS znajduje się w polu 7
                gnss_system_id = fields[7]
                if gnss_system_id.isdigit():
                    return self.GNSS_SYSTEMS.get(gnss_system_id, "Unknown")
                else:
                    return None
            except (IndexError, ValueError):
                return None
    
    def transformLat(self, x, y):
        ret = -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * x * y + 0.2 *math.sqrt(abs(x))
        ret += (20.0 * math.sin(6.0 * x * pi) + 20.0 * math.sin(2.0 * x * pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(y * pi) + 40.0 * math.sin(y / 3.0 * pi)) * 2.0 / 3.0
        ret += (160.0 * math.sin(y / 12.0 * pi) + 320 * math.sin(y * pi / 30.0)) * 2.0 / 3.0
        return ret

    def transformLon(self, x, y):
        ret = 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * x * y + 0.1 * math.sqrt(abs(x))
        ret += (20.0 * math.sin(6.0 * x * pi) + 20.0 * math.sin(2.0 * x * pi)) * 2.0 / 3.0
        ret += (20.0 * math.sin(x * pi) + 40.0 * math.sin(x / 3.0 * pi)) * 2.0 / 3.0
        ret += (150.0 * math.sin(x / 12.0 * pi) + 300.0 * math.sin(x / 30.0 * pi)) * 2.0 / 3.0
        return ret

    def bd_encrypt(self):
        x = self.Lon_Goodle
        y = self.Lat_Goodle
        z = math.sqrt(x * x + y * y) + 0.00002 * math.sin(y * x_pi)
        theta = math.atan2(y, x) + 0.000003 * math.cos(x * x_pi)
        self.Lon_Baidu = z * math.cos(theta) + 0.0065
        self.Lat_Baidu = z * math.sin(theta) + 0.006

    def transform(self):
        dLat = self.transformLat(self.GPS_Lon - 105.0, self.GPS_Lat - 35.0)
        dLon = self.transformLon(self.GPS_Lon - 105.0, self.GPS_Lat - 35.0)
        radLat = self.GPS_Lat / 180.0 * pi
        magic = math.sin(radLat)
        magic = 1 - ee * magic * magic
        math.sqrtMagic = math.sqrt(magic)
        dLat = (dLat * 180.0) / ((a * (1 - ee)) / (magic * math.sqrtMagic) * pi)
        dLon = (dLon * 180.0) / (a / math.sqrtMagic * math.cos(radLat) * pi)
        self.Lat_Goodle = self.GPS_Lat + dLat
        self.Lon_Goodle = self.GPS_Lon + dLon

    def L76X_Google_Coordinates(self, U_Lat, U_Lon):
        self.GPS_Lat = U_Lat % 1 / 60 + U_Lat/1
        self.GPS_Lon = U_Lon % 1 / 60 + U_Lon/1
        self.transform()

    def L76X_Set_Baudrate(self, Baudrate):
        self.config.Uart_Set_Baudrate(Baudrate)

    def L76X_Exit_BackupMode(self):
        GPIO.setup(self.config.FORCE, GPIO.OUT)
        time.sleep(1)
        GPIO.output(self.config.FORCE, GPIO.HIGH)
        time.sleep(1)
        GPIO.output(self.config.FORCE, GPIO.LOW)
        time.sleep(1)
        GPIO.setup(self.config.FORCE, GPIO.IN)


    



