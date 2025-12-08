from ping3 import ping
import time
from datetime import datetime
import os
import sqlite3
import re

def validar_ip(ip: str) -> bool:
    """
    Valida si una cadena es una dirección IPv4 válida usando regex.

    Args:
        ip: Cadena a validar

    Returns:
        True si es una IP válida, False en caso contrario

    Ejemplos:
        validar_ip("192.168.1.1")  -> True
        validar_ip("8.8.8.8")      -> True
        validar_ip("256.1.1.1")    -> False
        validar_ip("192.168.1")    -> False
        validar_ip("abc.def.ghi")  -> False
    """
    # Patrón regex para IPv4
    # Cada octeto puede ser:
    # - 0-99: \d{1,2}
    # - 100-199: 1\d{2}
    # - 200-249: 2[0-4]\d
    # - 250-255: 25[0-5]
    patron = r'^((25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])\.){3}(25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])$'

    return re.match(patron, ip) is not None

def ping_unico(ip: str) -> float:
    """
    Hace un solo ping a la IP dada, con timeout de 1 segundo.
    
    - Si no hay respuesta -> retorna -1
    - Si hay respuesta -> retorna el ping en ms
      y hace un sleep para completar 1 segundo total.
    """
    rtt = ping(ip, timeout=1)

    if rtt is None:
        return -1

    ms = rtt * 1000

    espera = 1 - rtt
    if espera > 0:
        time.sleep(espera)

    return ms

def preparar_bd_sqlite(ip: str) -> sqlite3.Connection:
    """
    Prepara una base de datos SQLite para guardar los pings de una IP específica.
    Crea la estructura de carpetas pings/IP/ si no existe.
    Crea/abre el archivo datos.db y crea la tabla si no existe.

    Args:
        ip: Dirección IP a monitorear

    Returns:
        Conexión a la base de datos SQLite
    """
    # Construir ruta de la carpeta
    carpeta = os.path.join("pings", ip)

    # Verificar si 'pings' existe y es un archivo (no directorio)
    if os.path.exists("pings") and not os.path.isdir("pings"):
        raise ValueError("Error: 'pings' existe como archivo. Debe ser eliminado o renombrado.")

    # Crear la estructura de carpetas si no existe
    try:
        os.makedirs(carpeta, exist_ok=True)
    except PermissionError:
        raise PermissionError(
            f"Error: No se tienen permisos para crear el directorio '{carpeta}'. "
            "Verifica los permisos del directorio o ejecuta como administrador."
        )

    # Ruta de la base de datos
    ruta_bd = os.path.join(carpeta, "datos.db")

    # Conectar a la base de datos (se crea si no existe)
    conn = sqlite3.connect(ruta_bd, check_same_thread=False)

    # Crear la tabla si no existe
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            tiempo_ms REAL NOT NULL
        )
    """)

    # Crear índice en timestamp para consultas rápidas
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_timestamp ON pings(timestamp)
    """)

    conn.commit()

    return conn

def guardar_ping(conn: sqlite3.Connection, tiempo_ms: float):
    """
    Guarda un ping en la base de datos SQLite.

    Args:
        conn: Conexión a la base de datos SQLite
        tiempo_ms: Tiempo de respuesta en milisegundos
    """
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO pings (timestamp, tiempo_ms) VALUES (?, ?)",
        (timestamp, tiempo_ms)
    )
    conn.commit()

def grabar_ping(ip: str):
    """
    Monitorea continuamente una IP haciendo pings y guardando los resultados en SQLite.
    Todos los pings se guardan en la base de datos pings/IP/datos.db

    Args:
        ip: Dirección IP a monitorear

    Raises:
        ValueError: Si la IP no es válida

    Funciona en Windows y Linux. El loop es infinito, presiona Ctrl+C para detener.
    SQLite permite lectura concurrente, por lo que el visor puede leer mientras se escribe.
    """
    # Validar que la IP sea válida
    if not validar_ip(ip):
        raise ValueError(f"Error: '{ip}' no es una dirección IPv4 válida")

    print(f"Iniciando monitoreo de {ip}")
    print(f"Base de datos: pings/{ip}/datos.db")
    print("Presiona Ctrl+C para detener")
    print("-" * 50)

    # Preparar base de datos
    conn = preparar_bd_sqlite(ip)
    print(f"Base de datos preparada")

    contador_total = 0

    try:
        while True:
            # Hacer ping
            resultado = ping_unico(ip)

            # Guardar en la base de datos
            guardar_ping(conn, resultado)

            # Incrementar contador
            contador_total += 1

            # Mostrar progreso cada 60 pings (1 minuto)
            if contador_total % 60 == 0:
                minutos = contador_total // 60
                print(f"  {minutos} minuto(s) - Total: {contador_total} pings - Último: {resultado} ms")

    except KeyboardInterrupt:
        print(f"\n\nMonitoreo detenido")
        print(f"Total de pings guardados: {contador_total}")
    finally:
        # Cerrar la conexión al terminar
        conn.close()
        print("Conexión a base de datos cerrada")


