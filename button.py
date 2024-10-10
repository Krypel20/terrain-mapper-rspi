import RPi.GPIO as GPIO
import time

# Ustawienia GPIO dla przycisku
GPIO.setmode(GPIO.BCM)
GPIO.setup(26, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

# Funkcja do obsługi przycisku
def button_callback(channel):
    print("klik")

# Przypisanie funkcji do zdarzenia przycisku
try:
    GPIO.add_event_detect(26, GPIO.RISING, callback=button_callback, bouncetime=300)
except RuntimeError as e:
    print(f"RuntimeError: {e}")
    GPIO.cleanup()

# Utrzymanie skryptu w działaniu
try:
    while True:
    	time.sleep(0.01)
except KeyboardInterrupt:
    print("Program zakończony")
finally:
    GPIO.cleanup()
