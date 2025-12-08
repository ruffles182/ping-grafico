"""
mos_functions.py
Funciones core para cálculo de MOS en VoIP
"""

import ping3
import statistics
from datetime import datetime
import time
import os


def hacer_ping(ip, cantidad=10):
    """
    Realiza ping a una IP y guarda los resultados en un archivo.
    Ejecuta 1 ping por segundo para simular tráfico real.
    
    Parámetros:
    - ip: Dirección IP a hacer ping
    - cantidad: Número de pings a realizar (default: 10)
    
    Retorna:
    - nombre_archivo: Ruta del archivo creado o None si hay error
    """
    # Crear carpeta pings si no existe
    if not os.path.exists('pings'):
        os.makedirs('pings')
    
    fecha_hora = datetime.now().strftime("%Y%m%d-%H%M%S")
    nombre_archivo = f"pings/ping-{ip}-{fecha_hora}.txt"
    
    try:
        latencias = []
        paquetes_enviados = 0
        paquetes_recibidos = 0
        
        # Realizar pings con intervalo de 1 segundo
        for i in range(cantidad):
            inicio = time.time()
            paquetes_enviados += 1
            
            try:
                # ping3 retorna el tiempo en segundos o None si falla
                resultado = ping3.ping(ip, timeout=1)
                # Validar que el resultado sea válido (mayor a 0.001 segundos = 1ms y no None)
                # Rechazamos latencias menores a 1ms ya que son probablemente errores o localhost
                if resultado is not None and resultado > 0.001:
                    # Convertir a milisegundos
                    latencia_ms = resultado * 1000
                    latencias.append(latencia_ms)
                    paquetes_recibidos += 1
            except Exception:
                pass  # Paquete perdido
            
            # Esperar para completar 1 segundo total
            tiempo_transcurrido = time.time() - inicio
            if tiempo_transcurrido < 1.0:
                time.sleep(1.0 - tiempo_transcurrido)
        
        # Calcular pérdida
        paquetes_perdidos = paquetes_enviados - paquetes_recibidos
        porcentaje_perdida = (paquetes_perdidos / paquetes_enviados) * 100 if paquetes_enviados > 0 else 0
        
        # Guardar resultados en archivo
        with open(nombre_archivo, 'w', encoding='utf-8') as f:
            f.write(f"Ping a {ip} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("=" * 60 + "\n\n")
            f.write(f"Paquetes: enviados = {paquetes_enviados}, recibidos = {paquetes_recibidos}, ")
            f.write(f"perdidos = {paquetes_perdidos} ({porcentaje_perdida:.2f}% perdidos)\n\n")
            
            if latencias:
                f.write("Estadísticas:\n")
                f.write(f"  Latencia mínima: {min(latencias):.2f} ms\n")
                f.write(f"  Latencia máxima: {max(latencias):.2f} ms\n")
                f.write(f"  Latencia promedio: {statistics.mean(latencias):.2f} ms\n")
                if len(latencias) > 1:
                    f.write(f"  Jitter (desv. estándar): {statistics.stdev(latencias):.2f} ms\n")
                f.write("\nDetalles de cada ping:\n")
                for i, lat in enumerate(latencias, 1):
                    f.write(f"  Ping {i}: time={lat:.2f} ms\n")
            else:
                f.write("No se recibieron respuestas válidas.\n")
        
        # Solo retornar el archivo si hay al menos algunas respuestas válidas
        # y la pérdida no es mayor al 50% (VoIP no funciona con más pérdida)
        if latencias and len(latencias) >= 5 and porcentaje_perdida <= 50:
            return nombre_archivo
        else:
            return None
        
    except Exception as e:
        return None


def calcular_latencia_promedio(archivo):
    """
    Calcula la latencia promedio desde un archivo de ping.
    
    Parámetros:
    - archivo: Ruta del archivo con resultados de ping
    
    Retorna:
    - latencia_promedio: Latencia promedio en ms o None si hay error
    """
    try:
        with open(archivo, 'r', encoding='utf-8') as f:
            contenido = f.read()
        
        # Buscar líneas con formato "Ping X: time=XX.XX ms"
        import re
        patron = r'time=(\d+\.?\d*)\s*ms'
        matches = re.findall(patron, contenido, re.IGNORECASE)
        
        if not matches:
            # Intentar con formato alternativo
            patron_alt = r'Latencia promedio:\s*(\d+\.?\d*)\s*ms'
            match_alt = re.search(patron_alt, contenido, re.IGNORECASE)
            if match_alt:
                return float(match_alt.group(1))
            return None
        
        latencias = [float(m) for m in matches]
        return statistics.mean(latencias)
        
    except FileNotFoundError:
        return None
    except Exception as e:
        return None


def calcular_jitter(archivo):
    """
    Calcula el jitter según el método de PingPlotter:
    promedio de diferencias absolutas entre latencias consecutivas.
    
    Parámetros:
    - archivo: Ruta del archivo con resultados de ping
    
    Retorna:
    - jitter: Jitter en ms o None si hay error
    """
    try:
        with open(archivo, 'r', encoding='utf-8') as f:
            contenido = f.read()

        import re

        # Buscar líneas con formato "Ping X: time=XX.XX ms"
        patron = r'time=(\d+\.?\d*)\s*ms'
        matches = re.findall(patron, contenido, re.IGNORECASE)

        if not matches:
            # Intentar extraer jitter pre-calculado si existiera
            patron_alt = r'Jitter.*?:\s*(\d+\.?\d*)\s*ms'
            match_alt = re.search(patron_alt, contenido, re.IGNORECASE)
            if match_alt:
                return float(match_alt.group(1))
            return None

        latencias = [float(m) for m in matches]

        if len(latencias) < 2:
            return None

        # Cálculo de jitter según PingPlotter:
        # diferencia absoluta entre muestras consecutivas
        diferencias = [
            abs(latencias[i+1] - latencias[i])
            for i in range(len(latencias) - 1)
        ]

        jitter = sum(diferencias) / len(diferencias)
        return jitter

    except FileNotFoundError:
        return None
    except Exception:
        return None



def calcular_paquetes_perdidos(archivo):
    """
    Calcula el porcentaje de paquetes perdidos desde un archivo de ping.
    
    Parámetros:
    - archivo: Ruta del archivo con resultados de ping
    
    Retorna:
    - porcentaje_perdida: Porcentaje de paquetes perdidos (0-100) o None si hay error
    """
    try:
        with open(archivo, 'r', encoding='utf-8') as f:
            contenido = f.read()
        
        import re
        # Formato propio: "enviados = X, recibidos = Y, perdidos = Z (W% perdidos)"
        match = re.search(r'enviados\s*=\s*(\d+).*?recibidos\s*=\s*(\d+)', contenido, re.IGNORECASE)
        if match:
            enviados = int(match.group(1))
            recibidos = int(match.group(2))
            perdidos = enviados - recibidos
            porcentaje = (perdidos / enviados) * 100 if enviados > 0 else 0
            return porcentaje
        
        # Buscar porcentaje directo
        match = re.search(r'(\d+\.?\d*)%\s+(perdidos|loss)', contenido, re.IGNORECASE)
        if match:
            return float(match.group(1))
        
        return None
        
    except FileNotFoundError:
        return None
    except Exception as e:
        return None


def calcular_mos(latencia_promedio, jitter, perdida_paquetes):
    """
    Calcula el MOS (Mean Opinion Score) para llamadas VoIP.
    
    Parámetros:
    - latencia_promedio: Latencia promedio en ms
    - jitter: Jitter en ms
    - perdida_paquetes: Porcentaje de pérdida de paquetes (0-100)
    
    Retorna:
    - tupla: (MOS, R-Factor, latencia_efectiva)
    """
    latencia_efectiva = latencia_promedio + (jitter * 2) + 10
    
    if latencia_efectiva < 160:
        R = 93.2 - (latencia_efectiva / 40)
    else:
        R = 93.2 - ((latencia_efectiva - 120) / 10)
    
    R = R - (perdida_paquetes * 2.5)
    
    # Limitar R entre 0 y 100
    R = max(0, min(100, R))
    
    MOS = 1 + (0.035 * R) + (0.000007 * R * (R - 60) * (100 - R))
    
    # Limitar MOS entre 1 y 5
    MOS = max(1.0, min(5.0, MOS))
    
    return MOS, R, latencia_efectiva


def clasificar_mos(mos):
    """
    Clasifica la calidad de la llamada según el valor MOS.
    
    Parámetros:
    - mos: Valor MOS (1-5)
    
    Retorna:
    - calidad: String con la clasificación
    """
    if mos >= 4.3:
        return "Excelente"
    elif mos >= 4.0:
        return "Buena"
    elif mos >= 3.6:
        return "Aceptable"
    elif mos >= 3.1:
        return "Pobre"
    else:
        return "Mala"


def analizar_ip(ip, cantidad_pings):
    """
    Realiza análisis completo de una IP: ping y cálculo de métricas.
    
    Parámetros:
    - ip: Dirección IP a analizar
    - cantidad_pings: Cantidad de pings a realizar
    
    Retorna:
    - dict con resultados o dict con error
    """
    try:
        # Realizar ping
        archivo = hacer_ping(ip, cantidad_pings)
        if not archivo:
            return {'error': True, 'mensaje': 'Conexión inestable o sin respuesta (>50% pérdida)'}
        
        # Calcular métricas
        latencia = calcular_latencia_promedio(archivo)
        jitter = calcular_jitter(archivo)
        perdida = calcular_paquetes_perdidos(archivo)
        
        # Verificar que tenemos todos los datos
        if latencia is None:
            return {'error': True, 'mensaje': 'No se pudo calcular la latencia'}
        if jitter is None:
            return {'error': True, 'mensaje': 'No se pudo calcular el jitter'}
        if perdida is None:
            return {'error': True, 'mensaje': 'No se pudo calcular la pérdida de paquetes'}
        
        # Verificar que la pérdida no sea excesiva (backup check)
        if perdida > 50:
            return {'error': True, 'mensaje': f'Pérdida de paquetes excesiva ({perdida:.1f}%)'}
        
        # Calcular MOS
        mos, r_factor, lat_efectiva = calcular_mos(latencia, jitter, perdida)
        calidad = clasificar_mos(mos)
        
        return {
            'ip': ip,
            'latencia': latencia,
            'jitter': jitter,
            'perdida': perdida,
            'mos': mos,
            'r_factor': r_factor,
            'latencia_efectiva': lat_efectiva,
            'calidad': calidad,
            'archivo': archivo,
            'error': False
        }
    except Exception as e:
        return {'error': True, 'mensaje': f'Error inesperado: {str(e)}'}