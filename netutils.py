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
    Hace un solo ping a la IP dada, con timeout de 4 segundos (estándar Windows).
    Intenta mantener un intervalo de 1 segundo entre pings (como ping -t en Windows).

    - Si no hay respuesta -> retorna -1
    - Si hay respuesta en < 1 seg -> retorna el ping en ms y espera hasta completar 1 segundo
    - Si tarda >= 1 seg -> retorna el ping en ms sin espera adicional
    """
    rtt = ping(ip, timeout=4)

    if rtt is None:
        return -1

    ms = rtt * 1000

    # Solo espera si el ping fue más rápido que 1 segundo
    espera = 1 - rtt
    if espera > 0:
        time.sleep(espera)

    return ms

def preparar_bd_sqlite(ip: str) -> sqlite3.Connection:
    """
    Prepara una base de datos SQLite para guardar los pings de una IP específica.
    Crea la estructura de carpetas pings/IP/ si no existe.
    Crea/abre el archivo datos.db y crea la tabla si no existe.

    OPTIMIZACIONES PARA GRABACIÓN 24/7:
    - Modo WAL (Write-Ahead Logging) para mejor concurrencia
    - Pragmas optimizados para reducir latencia de escritura
    - Batch commits para evitar bloquear el thread de pings

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

    # ===== OPTIMIZACIONES DE RENDIMIENTO =====
    cursor = conn.cursor()

    # 1. Modo WAL (Write-Ahead Logging): permite lecturas concurrentes durante escrituras
    #    y reduce latencia de escritura significativamente
    cursor.execute("PRAGMA journal_mode=WAL")

    # 2. synchronous=NORMAL: Balance entre velocidad y seguridad
    #    FULL (default) = fsync en cada commit (~10-15ms)
    #    NORMAL = fsync solo en checkpoints (~1-2ms por commit)
    #    Riesgo: Solo se pierden datos si hay fallo de SO + fallo de energía simultáneamente
    cursor.execute("PRAGMA synchronous=NORMAL")

    # 3. cache_size: Mantener más páginas en memoria (default=2000 páginas = ~8MB)
    #    Aumentar a 10000 páginas = ~40MB para operaciones 24/7
    cursor.execute("PRAGMA cache_size=10000")

    # 4. temp_store=MEMORY: Usar RAM para operaciones temporales
    cursor.execute("PRAGMA temp_store=MEMORY")

    # Crear la tabla si no existe
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

class BatchPingSaver:
    """
    Gestor de guardado por lotes para optimizar escrituras a SQLite.

    En lugar de hacer commit() después de cada ping (bloqueante ~10-15ms),
    acumula pings en un buffer y hace commit cada N pings o cada X segundos.

    Esto reduce drásticamente la latencia de I/O en el thread de pings,
    permitiendo que los pings se ejecuten con mayor precisión temporal.
    """

    def __init__(self, conn: sqlite3.Connection, batch_size: int = 10):
        """
        Args:
            conn: Conexión a la base de datos SQLite
            batch_size: Cantidad de pings a acumular antes de hacer commit
        """
        self.conn = conn
        self.batch_size = batch_size
        self.buffer = []  # [(timestamp, tiempo_ms), ...]
        self.cursor = conn.cursor()

    def agregar_ping(self, tiempo_ms: float):
        """
        Agrega un ping al buffer. Hace commit automático si se alcanza batch_size.

        Args:
            tiempo_ms: Tiempo de respuesta en milisegundos (-1 si timeout)
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.buffer.append((timestamp, tiempo_ms))

        # Hacer commit si se alcanzó el tamaño del batch
        if len(self.buffer) >= self.batch_size:
            self.flush()

    def flush(self):
        """
        Fuerza el guardado de todos los pings pendientes en el buffer.
        Llamar al cerrar la aplicación para no perder datos.
        """
        if not self.buffer:
            return

        # Insertar todos los pings del buffer
        self.cursor.executemany(
            "INSERT INTO pings (timestamp, tiempo_ms) VALUES (?, ?)",
            self.buffer
        )
        self.conn.commit()

        # Limpiar buffer
        self.buffer.clear()

    def close(self):
        """Guarda datos pendientes y cierra."""
        self.flush()


def guardar_ping(conn: sqlite3.Connection, tiempo_ms: float):
    """
    Guarda un ping en la base de datos SQLite (modo inmediato, sin batch).

    NOTA: Esta función hace commit() inmediato, lo cual puede causar latencia
    en operaciones 24/7. Para mejor rendimiento, usar BatchPingSaver.

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


