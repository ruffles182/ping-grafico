"""
API REST para acceder a datos de monitoreo de ping desde la red.

Uso:
    python api.py

Luego acceder desde otra PC usando:
    http://<IP-DE-ESTE-PC>:8000/docs para documentación interactiva
    http://<IP-DE-ESTE-PC>:8000/api/ips para listar IPs monitoreadas
    http://<IP-DE-ESTE-PC>:8000/api/ping/{ip} para obtener datos de ping

Instalar dependencias:
    pip install fastapi uvicorn python-multipart
"""

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from datetime import datetime, timedelta
import sqlite3
import os
from pathlib import Path
import uvicorn

app = FastAPI(
    title="Ping Monitor API",
    description="API para acceder a datos de monitoreo de ping almacenados en SQLite",
    version="1.0.0"
)

# Configurar CORS para permitir acceso desde cualquier origen
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Permite todas las IPs (cambiar si necesitas más seguridad)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PINGS_DIR = Path("pings")


def get_available_ips() -> List[str]:
    """
    Obtiene lista de IPs que tienen base de datos disponible.

    Returns:
        Lista de direcciones IP monitoreadas
    """
    if not PINGS_DIR.exists():
        return []

    ips = []
    for item in PINGS_DIR.iterdir():
        if item.is_dir():
            db_path = item / "datos.db"
            if db_path.exists():
                ips.append(item.name)

    return sorted(ips)


def get_db_connection(ip: str) -> sqlite3.Connection:
    """
    Obtiene conexión a la base de datos de una IP específica.

    Args:
        ip: Dirección IP

    Returns:
        Conexión a SQLite

    Raises:
        HTTPException: Si la base de datos no existe
    """
    db_path = PINGS_DIR / ip / "datos.db"

    if not db_path.exists():
        raise HTTPException(status_code=404, detail=f"No se encontró base de datos para IP {ip}")

    # Abrir en modo de solo lectura para evitar conflictos con el proceso que escribe
    # y no requerir permisos de escritura (importante para bases de datos en modo WAL)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row  # Permite acceso por nombre de columna
    return conn


@app.get("/")
async def root():
    """Endpoint raíz con información de la API."""
    return {
        "message": "Ping Monitor API",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": {
            "list_ips": "/api/ips",
            "get_pings": "/api/ping/{ip}",
            "get_stats": "/api/stats/{ip}"
        }
    }


@app.get("/api/ips")
async def list_ips():
    """
    Lista todas las IPs que tienen datos de monitoreo disponibles.

    Returns:
        Lista de IPs con información básica
    """
    ips = get_available_ips()

    result = []
    for ip in ips:
        try:
            conn = get_db_connection(ip)
            cursor = conn.cursor()

            # Obtener estadísticas básicas
            cursor.execute("SELECT COUNT(*) as total FROM pings")
            total = cursor.fetchone()["total"]

            cursor.execute("SELECT MIN(timestamp) as first, MAX(timestamp) as last FROM pings")
            row = cursor.fetchone()

            conn.close()

            result.append({
                "ip": ip,
                "total_pings": total,
                "first_ping": row["first"],
                "last_ping": row["last"]
            })
        except Exception as e:
            result.append({
                "ip": ip,
                "error": str(e)
            })

    return {"ips": result, "total": len(result)}


@app.get("/api/ping/{ip}")
async def get_pings(
    ip: str,
    limit: int = Query(100, description="Número máximo de registros a retornar", ge=1, le=10000),
    offset: int = Query(0, description="Número de registros a saltar", ge=0),
    from_date: Optional[str] = Query(None, description="Fecha inicio (YYYY-MM-DD HH:MM:SS)"),
    to_date: Optional[str] = Query(None, description="Fecha fin (YYYY-MM-DD HH:MM:SS)"),
    min_latency: Optional[float] = Query(None, description="Latencia mínima en ms"),
    max_latency: Optional[float] = Query(None, description="Latencia máxima en ms"),
    only_failures: bool = Query(False, description="Solo mostrar pings fallidos (timeout)")
):
    """
    Obtiene datos de ping para una IP específica con filtros opcionales.

    Args:
        ip: Dirección IP a consultar
        limit: Número máximo de registros
        offset: Saltar primeros N registros
        from_date: Filtrar desde fecha
        to_date: Filtrar hasta fecha
        min_latency: Latencia mínima
        max_latency: Latencia máxima
        only_failures: Solo pings fallidos

    Returns:
        Datos de ping con metadatos
    """
    conn = get_db_connection(ip)
    cursor = conn.cursor()

    # Construir query con filtros
    query = "SELECT * FROM pings WHERE 1=1"
    params = []

    if from_date:
        query += " AND timestamp >= ?"
        params.append(from_date)

    if to_date:
        query += " AND timestamp <= ?"
        params.append(to_date)

    if min_latency is not None:
        query += " AND tiempo_ms >= ?"
        params.append(min_latency)

    if max_latency is not None:
        query += " AND tiempo_ms <= ?"
        params.append(max_latency)

    if only_failures:
        query += " AND tiempo_ms = -1"

    # Ordenar por timestamp descendente (más recientes primero)
    query += " ORDER BY timestamp DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    cursor.execute(query, params)
    rows = cursor.fetchall()

    # Obtener total de registros que coinciden con filtros (sin limit/offset)
    count_query = query.split("ORDER BY")[0].replace("SELECT *", "SELECT COUNT(*) as total")
    cursor.execute(count_query, params[:-2])  # Excluir limit y offset
    total = cursor.fetchone()["total"]

    conn.close()

    # Convertir a lista de diccionarios
    pings = []
    for row in rows:
        pings.append({
            "id": row["id"],
            "timestamp": row["timestamp"],
            "tiempo_ms": row["tiempo_ms"],
            "status": "timeout" if row["tiempo_ms"] == -1 else "success"
        })

    return {
        "ip": ip,
        "total_results": total,
        "returned": len(pings),
        "offset": offset,
        "limit": limit,
        "pings": pings
    }


@app.get("/api/stats/{ip}")
async def get_stats(
    ip: str,
    from_date: Optional[str] = Query(None, description="Fecha inicio (YYYY-MM-DD HH:MM:SS)"),
    to_date: Optional[str] = Query(None, description="Fecha fin (YYYY-MM-DD HH:MM:SS)")
):
    """
    Obtiene estadísticas de ping para una IP específica.

    Args:
        ip: Dirección IP a consultar
        from_date: Fecha inicio para calcular estadísticas
        to_date: Fecha fin para calcular estadísticas

    Returns:
        Estadísticas de ping (min, max, avg, pérdida de paquetes, etc.)
    """
    conn = get_db_connection(ip)
    cursor = conn.cursor()

    # Construir query base
    where_clauses = []
    params = []

    if from_date:
        where_clauses.append("timestamp >= ?")
        params.append(from_date)

    if to_date:
        where_clauses.append("timestamp <= ?")
        params.append(to_date)

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    # Estadísticas generales
    cursor.execute(f"""
        SELECT
            COUNT(*) as total_pings,
            SUM(CASE WHEN tiempo_ms = -1 THEN 1 ELSE 0 END) as timeouts,
            SUM(CASE WHEN tiempo_ms != -1 THEN 1 ELSE 0 END) as successful,
            MIN(CASE WHEN tiempo_ms != -1 THEN tiempo_ms END) as min_latency,
            MAX(CASE WHEN tiempo_ms != -1 THEN tiempo_ms END) as max_latency,
            AVG(CASE WHEN tiempo_ms != -1 THEN tiempo_ms END) as avg_latency,
            MIN(timestamp) as first_ping,
            MAX(timestamp) as last_ping
        FROM pings
        WHERE {where_sql}
    """, params)

    stats = cursor.fetchone()

    # Calcular percentiles (mediana, p95, p99)
    cursor.execute(f"""
        SELECT tiempo_ms
        FROM pings
        WHERE {where_sql} AND tiempo_ms != -1
        ORDER BY tiempo_ms
    """, params)

    latencies = [row["tiempo_ms"] for row in cursor.fetchall()]

    conn.close()

    # Calcular percentiles
    percentiles = {}
    if latencies:
        sorted_latencies = sorted(latencies)
        n = len(sorted_latencies)
        percentiles = {
            "p50": sorted_latencies[int(n * 0.50)] if n > 0 else None,
            "p95": sorted_latencies[int(n * 0.95)] if n > 0 else None,
            "p99": sorted_latencies[int(n * 0.99)] if n > 0 else None
        }

    total = stats["total_pings"]
    packet_loss = (stats["timeouts"] / total * 100) if total > 0 else 0

    return {
        "ip": ip,
        "period": {
            "from": from_date or stats["first_ping"],
            "to": to_date or stats["last_ping"]
        },
        "total_pings": total,
        "successful": stats["successful"],
        "timeouts": stats["timeouts"],
        "packet_loss_percent": round(packet_loss, 2),
        "latency": {
            "min_ms": stats["min_latency"],
            "max_ms": stats["max_latency"],
            "avg_ms": round(stats["avg_latency"], 2) if stats["avg_latency"] else None,
            "median_ms": percentiles.get("p50"),
            "p95_ms": percentiles.get("p95"),
            "p99_ms": percentiles.get("p99")
        }
    }


@app.get("/api/recent/{ip}")
async def get_recent_pings(
    ip: str,
    minutes: int = Query(60, description="Minutos hacia atrás desde ahora", ge=1, le=1440)
):
    """
    Obtiene pings recientes de una IP (últimos N minutos).

    Args:
        ip: Dirección IP
        minutes: Número de minutos hacia atrás

    Returns:
        Pings de los últimos N minutos
    """
    # Calcular timestamp de hace N minutos
    now = datetime.now()
    from_time = now - timedelta(minutes=minutes)
    from_date = from_time.strftime("%Y-%m-%d %H:%M:%S")

    conn = get_db_connection(ip)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM pings
        WHERE timestamp >= ?
        ORDER BY timestamp DESC
    """, (from_date,))

    rows = cursor.fetchall()
    conn.close()

    pings = []
    for row in rows:
        pings.append({
            "id": row["id"],
            "timestamp": row["timestamp"],
            "tiempo_ms": row["tiempo_ms"],
            "status": "timeout" if row["tiempo_ms"] == -1 else "success"
        })

    return {
        "ip": ip,
        "minutes": minutes,
        "from": from_date,
        "total": len(pings),
        "pings": pings
    }


if __name__ == "__main__":
    # Obtener IP local para mostrar al usuario
    import socket
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)

    print("=" * 60)
    print("Ping Monitor API - Iniciando servidor")
    print("=" * 60)
    print(f"\nAcceder desde esta PC:")
    print(f"  http://localhost:8000/docs")
    print(f"\nAcceder desde otra PC en la red:")
    print(f"  http://{local_ip}:8000/docs")
    print(f"\nEndpoints disponibles:")
    print(f"  GET  /api/ips          - Listar IPs monitoreadas")
    print(f"  GET  /api/ping/{{ip}}    - Obtener datos de ping")
    print(f"  GET  /api/stats/{{ip}}   - Obtener estadísticas")
    print(f"  GET  /api/recent/{{ip}}  - Obtener pings recientes")
    print(f"\nPresiona Ctrl+C para detener")
    print("=" * 60)
    print()

    # Iniciar servidor en 0.0.0.0 para que sea accesible desde la red
    uvicorn.run(app, host="0.0.0.0", port=8000)
