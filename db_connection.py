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
            host='192.168.20.13', #192.168.20.13 // 192.168.43.183
            port=5433 #5433 // 5434
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
            # Odczytaj dane z pliku CSV
            with open(csv_file_path, 'r') as f:
                csv_reader = csv.reader(f)
                header = next(csv_reader)  # Pomiń nagłówek
                
                # Pobierz nazwę pliku bez ścieżki i rozszerzenia
                file_name = csv_file_path.split('/')[-1].replace('.csv', '')
                table_name = f"session_{file_name.lower()}"
                
                # Sprawdź czy tabela już istnieje
                if self.table_exists(table_name):
                    print(f"Tabela {table_name} już istnieje. Pomijanie importu.")
                    return False
                
                # Utwórz tabelę z dodaną kolumną vdop
                cursor.execute(sql.SQL("""
                    CREATE TABLE IF NOT EXISTS {} (
                        id SERIAL PRIMARY KEY,
                        measurement_time TIMESTAMP WITHOUT TIME ZONE,
                        location GEOGRAPHY(POINT, 4326),
                        altitude NUMERIC(10, 2),
                        vdop NUMERIC(10, 2)
                    )
                """).format(sql.Identifier(table_name)))
                
                # Wstaw dane z uwzględnieniem vdop
                for row in csv_reader:
                    time_str, lat, lon, alt, vdop = row
                    
                    # Konwersja formatu czasu jeśli potrzebna
                    if ':' in time_str and len(time_str.split(':')) == 3:
                        if ' ' not in time_str:
                            time_str = f"{datetime.now().date()} {time_str}"
                    
                    cursor.execute(
                        sql.SQL("""
                            INSERT INTO {} (measurement_time, location, altitude, vdop)
                            VALUES (%s, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s, %s)
                        """).format(sql.Identifier(table_name)),
                        (time_str, float(lon), float(lat), float(alt), float(vdop))
                    )
                
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
                print(f"Dane zostały pomyślnie zaimportowane do tabeli {table_name}")
                return True
            
        except Exception as e:
            conn.rollback()
            print(f"Wystąpił błąd podczas importu danych: {str(e)}")
            return None
        finally:
            cursor.close()
            # Nie zamykamy połączenia, ponieważ jest zarządzane przez klasę
    
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