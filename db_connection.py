# db_connection.py
import psycopg2
from psycopg2 import sql
import os

class DatabaseConnection:
    def __init__(self, dbname='terrain_measurements', user='pkrypel', password='20122002', host='localhost', port=5434):
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

    def import_csv_data(self, file_path):
        with self.connect() as conn:
            with conn.cursor() as cur:
                session_name = os.path.splitext(os.path.basename(file_path))[0]
                table_name = f"session_{session_name.lower().replace(' ', '_')}"
                
                if self.table_exists(table_name):
                    print(f"Tabela {table_name} już istnieje. Pomijam import pliku {file_path}.")
                    return False
                
                try:
                    cur.execute(
                        sql.SQL("SELECT import_csv_data({})").format(sql.Literal(file_path))
                    )
                    conn.commit()
                    print(f"Pomyślnie zaimportowano dane z {file_path}")
                    return True
                except psycopg2.Error as e:
                    print(f"Błąd podczas importowania danych z {file_path}: {e}")
                    conn.rollback()
                    return False

    def import_all_csv_files(self, directory='measurements'):
        success_count = 0
        skip_count = 0
        fail_count = 0

        for filename in os.listdir(directory):
            if filename.endswith('.csv'):
                file_path = os.path.join(directory, filename)
                result = self.import_csv_data(file_path)
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