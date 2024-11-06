import psycopg2
import socket
import time
from datetime import datetime

def check_host_availability(host, port):
    """Sprawdza czy host jest dostępny."""
    try:
        socket.create_connection((host, port), timeout=3)
        return True
    except (socket.timeout, socket.gaierror, ConnectionRefusedError):
        return False

def test_db_connection(host, port, dbname, user, password):
    """Testuje połączenie z bazą danych i wykonuje prostą operację."""
    print(f"\nTest połączenia z bazą danych na {host}:{port}")
    print("-" * 50)
    
    # Sprawdź dostępność hosta
    if not check_host_availability(host, port):
        print(f"Host {host}:{port} jest niedostępny!")
        return False
    
    print(f"Host {host}:{port} jest dostępny")
    
    try:
        # Próba połączenia z bazą
        conn = psycopg2.connect(
            dbname=dbname,
            user=user,
            password=password,
            host=host,
            port=port
        )
        
        print("✓ Połączenie z bazą danych ustanowione pomyślnie")
        
        # Test wykonania prostego zapytania
        cur = conn.cursor()
        cur.execute("SELECT version();")
        version = cur.fetchone()
        print(f"✓ Wersja PostgreSQL: {version[0]}")
        
        # Test zapisu i odczytu
        test_table = f"connection_test_{int(time.time())}"
        cur.execute(f"""
            CREATE TABLE {test_table} (
                id SERIAL PRIMARY KEY,
                test_time TIMESTAMP,
                message TEXT
            );
        """)
        
        test_time = datetime.now()
        cur.execute(f"""
            INSERT INTO {test_table} (test_time, message) 
            VALUES (%s, %s)
            RETURNING id;
        """, (test_time, "Test z Raspberry Pi"))
        
        inserted_id = cur.fetchone()[0]
        print(f"Test zapisu do bazy: ID={inserted_id}")
        
        # Czyszczenie po teście
        cur.execute(f"DROP TABLE {test_table};")
        conn.commit()
        
        cur.close()
        conn.close()
        print("Test zakończony pomyślnie")
        return True
        
    except psycopg2.OperationalError as e:
        print(f"Błąd połączenia z bazą danych: {str(e)}")
        return False
    except Exception as e:
        print(f"Wystąpił nieoczekiwany błąd: {str(e)}")
        return False

if __name__ == "__main__":
    # Konfiguracja połączenia
    DB_CONFIG = {
        'host': '192.168.20.13', #192.168.20.13 // 192.168.43.183
        'port': 5433, #5433 // 5434
        'dbname': 'terrain_measurements',
        'user': 'pkrypel',
        'password': '20122002'
    }
    
    # Wykonaj test
    success = test_db_connection(**DB_CONFIG)
    
    # Podsumowanie
    print("\nPodsumowanie:")
    print("-" * 50)
    if success:
        print("Wszystkie testy zakończone pomyślnie!")
    else:
        print("Wystąpiły błędy podczas testowania!")
