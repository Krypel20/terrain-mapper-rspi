# terrain-mapper-rspi

Konfiguracja:

Raspbbery pi zero - Bullseye OS Lite

1. Update systemu 
	sudo apt update
	sudo apt update -y

2. Instalacja podstawowych narzędzi python
	sudo apt install -y git python3-pip python3-dev
	sudo apt install -y i2c-tools python3-smbus

3. Konfiguracja interfejsów systemowych
	
poprzez wykonanie polecenia raspi-config

Należy włączyć:

Interfejs I2C (Interface Options -> I2C -> Yes)
Port szeregowy (Interface Options -> Serial Port)

Nie dla konsoli szeregowej
Tak dla sprzętu szeregowego


SSH (jeśli potrzebne)

4. Konfiguracja GPIO i uprawnień
	# Dodaj użytkownika do odpowiednich grup
	sudo usermod -a -G i2c,gpio,dialout pi

	# Zainstaluj bibliotekę RPi.GPIO
	sudo pip3 install RPi.GPIO

5. Instalacja wymaganych bibliotek Pythona

# Podstawowe biblioteki
sudo pip3 install smbus2
sudo pip3 install pillow
sudo pip3 install numpy
sudo pip3 install mpu6050-raspberrypi
sudo pip3 install pandas
sudo apt-get install python3-psycopg2
sudo apt-get install python3-serial
sudo pip3 install curses

*micropyGPS*
git clone https://github.com/inmcm/micropyGPS.git
sudo python3 setup.py install


