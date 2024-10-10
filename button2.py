import RPi.GPIO as GPIO
import time

# Ustawienie numeracji pinów
GPIO.setmode(GPIO.BCM)

# Numer pinu, do którego podłączony jest przycisk
BUTTON_PIN = 26

# Konfiguracja pinu jako wejście z rezystorem pull-up
GPIO.setup(BUTTON_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)

# Zmienne do obsługi stanu przycisku
button_pressed = False
last_press_time = 0
debounce_time = 0.3  # czas debounce'ingu w sekundach

print("Test pojedynczego wciśnięcia przycisku na GPIO 26. Naciśnij Ctrl+C, aby zakończyć.")

try:
    while True:
        # Odczyt stanu przycisku
        button_state = GPIO.input(BUTTON_PIN)
        current_time = time.time()
        
        if button_state == GPIO.LOW and not button_pressed and (current_time - last_press_time) > debounce_time:
            print("Przycisk naciśnięty!")
            button_pressed = True
            last_press_time = current_time
        
        if button_state == GPIO.HIGH:
            button_pressed = False
        
        # Krótka pauza, aby zmniejszyć obciążenie CPU
        time.sleep(0.01)

except KeyboardInterrupt:
    print("\nProgram zakończony przez użytkownika.")

finally:
    # Czyszczenie ustawień GPIO
    GPIO.cleanup()
