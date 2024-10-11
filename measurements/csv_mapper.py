import pandas as pd
import folium
import os

# Wczytanie danych z pliku CSV
file_path = 'measurements\gnojnik_lewniowa_gorki.csv'  # Zmień na odpowiednią ścieżkę do pliku CSV
data = pd.read_csv(file_path)
nazwa = os.path.splitext(os.path.basename(file_path))[0]

# Sprawdzenie pierwszych kilku wierszy danych
print(data.head())

# Ustalanie pierwszego punktu jako punkt startowy mapy
start_location = [data['Latitude'][0], data['Longitude'][0]]

# Tworzenie mapy z punktu startowego
mapa = folium.Map(location=start_location, zoom_start=15)

# Dodanie punktów z każdego pomiaru na mapę
for index, row in data.iterrows():
    folium.Marker(
        location=[row['Latitude'], row['Longitude']],
        popup=f"Time: {row['Time']}, Altitude: {row['Altitude']}m",
        icon=folium.Icon(color="blue", icon="info-sign")
    ).add_to(mapa)

# Rysowanie linii trasy (współrzędne lat/lon)
coordinates = list(zip(data['Latitude'], data['Longitude']))
folium.PolyLine(coordinates, color="red", weight=2.5, opacity=1).add_to(mapa)

# Zapisanie mapy do pliku HTML
mapa.save(f"measurements\mapa_{nazwa}.html")

print("Mapa została zapisana jako mapa_trasa.html")
