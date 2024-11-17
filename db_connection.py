# db_connection.py
import psycopg2
from psycopg2 import sql
import csv
from datetime import datetime
import os

class DatabaseConnection:
    def __init__(self, 
            dbname='terrain_measurements', 
            user='pkrypel', 
            password='20122002', 
            host='192.168.43.183', #192.168.20.13 // 192.168.43.183
            port=5434 #5433 // 5434
        ):
        self.dbname = dbname
        self.user = user
        self.password = password
        self.host = host
        self.port = port
        self.conn = None

    def connect(self):
        if self.conn is None:
            self.conn = psycopg2.connect(
                dbname=self.dbname,
                user=self.user,
                password=self.password,
                host=self.host,
                port=self.port
            )
        return self.conn

    def close(self):
        if self.conn:
            self.conn.close()
            self.conn = None

    def table_exists(self, table_name):
        with self.connect().cursor() as cur:
            cur.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_name = %s
                );
            """, (table_name,))
            return cur.fetchone()[0]

    def upload_csv_to_db(self, csv_file_path):
        conn = self.connect()
        cursor = conn.cursor()
        
        try:
            # Dodaj logowanie dla debugowania
            print(f"Rozpoczynam import pliku: {csv_file_path}")
            
            with open(csv_file_path, 'r') as f:
                csv_reader = csv.DictReader(f)  # Użyj DictReader zamiast reader
                
                # Pobierz nazwę pliku
                file_name = os.path.basename(csv_file_path).replace('.csv', '')
                table_name = f"session_{file_name.lower()}"
                
                print(f"Tworzę tabelę: {table_name}")
                
                # Sprawdź czy tabela istnieje
                if self.table_exists(table_name):
                    print(f"Tabela {table_name} już istnieje. Pomijanie importu.")
                    return False
                
                # Utwórz tabelę
                cursor.execute(sql.SQL("""
                    CREATE TABLE IF NOT EXISTS {} (
                        id SERIAL PRIMARY KEY,
                        measurement_time TIMESTAMP WITHOUT TIME ZONE,
                        location GEOGRAPHY(POINT, 4326),
                        altitude NUMERIC(10, 2),
                        vdop NUMERIC(10, 2)
                    )
                """).format(sql.Identifier(table_name)))
                
                # Licznik wierszy dla debugowania
                row_count = 0
                
                # Wstaw dane
                for row in csv_reader:
                    try:
                        # Parsuj dane używając nazw kolumn z pliku CSV
                        measurement_time = row['time']
                        lat = float(row['latitude'])
                        lon = float(row['longitude'])
                        alt = float(row['altitude'])
                        vdop = float(row['VDOP'])
                        
                        cursor.execute(
                            sql.SQL("""
                                INSERT INTO {} (measurement_time, location, altitude, vdop)
                                VALUES (%s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s, %s)
                            """).format(sql.Identifier(table_name)),
                            (measurement_time, lon, lat, alt, vdop)
                        )
                        row_count += 1
                        
                    except ValueError as e:
                        print(f"Błąd konwersji danych w wierszu: {row}")
                        print(f"Szczegóły błędu: {str(e)}")
                        continue
                
                # Utwórz indeks przestrzenny
                cursor.execute(sql.SQL("""
                    CREATE INDEX IF NOT EXISTS {} 
                    ON {} USING GIST (location)
                """).format(
                    sql.Identifier(f"idx_{table_name}_location"), 
                    sql.Identifier(table_name)
                ))
                
                # Dodaj wpis do tabeli measurement_sessions
                cursor.execute(sql.SQL("""
                    INSERT INTO measurement_sessions (session_name, start_time, end_time, location_name)
                    SELECT %s, MIN(measurement_time), MAX(measurement_time), %s
                    FROM {}
                """).format(sql.Identifier(table_name)),
                (file_name, file_name.split('_')[0]))
                
                conn.commit()
                print(f"Pomyślnie zaimportowano {row_count} wierszy do tabeli {table_name}")
                return True
            
        except Exception as e:
            conn.rollback()
            print(f"Wystąpił błąd podczas importu danych:")
            print(f"Typ błędu: {type(e).__name__}")
            print(f"Szczegóły błędu: {str(e)}")
            return None
        finally:
            cursor.close()
    
    def import_all_csv_files(self, directory='measurements'):
        success_count = 0
        skip_count = 0
        fail_count = 0

        for filename in os.listdir(directory):
            if filename.endswith('.csv'):
                file_path = os.path.join(directory, filename)
                result = self.upload_csv_to_db(file_path)
                if result is True:
                    success_count += 1
                elif result is False:
                    skip_count += 1
                else:
                    fail_count += 1

        print(f"Podsumowanie importu:")
        print(f"- Pomyślnie zaimportowano: {success_count} plików")
        print(f"- Pominięto (tabele już istnieją): {skip_count} plików")
        print(f"- Nie udało się zaimportować: {fail_count} plików")
    
    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()