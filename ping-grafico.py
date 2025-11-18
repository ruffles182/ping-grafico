"""
ping_pyqtgraph.py
Monitorea una IP con ping persistente (-t) y muestra gráfica en tiempo real usando pyqtgraph.
Instalar: pip install pyqt5 pyqtgraph
"""

import sys
import subprocess
import re
import time
from collections import deque
import os
from dotenv import load_dotenv
from threading import Thread
from queue import Queue

from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QMessageBox
import pyqtgraph as pg
import json

load_dotenv()

DEFAULT_IP = os.getenv("DEFAULT_IP", "8.8.8.8")
DEFAULT_INTERVAL = float(os.getenv("DEFAULT_INTERVAL", 2.0))
MAX_POINTS = 1800

RUTA_JSON = "direcciones.json"

# Colores
BG_COLOR = os.getenv("BG_COLOR", "#000000")
FG_COLOR = os.getenv("FG_COLOR", "#00FF00")
FONT_SIZE = int(os.getenv("FONT_SIZE", 12))
TIEMPO_MAXIMO = int(os.getenv("TIEMPO_MAXIMO", 100))
COLOR_ALERTA = os.getenv("COLOR_ALERTA", "#FF0000")


def validar_ip(ip):
    import ipaddress
    try:
        ipaddress.ip_address(ip)
        return True
    except:
        return False

def cargar_direcciones():
    """Carga lista de direcciones desde JSON."""
    if not os.path.exists(RUTA_JSON):
        return []
    try:
        with open(RUTA_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def guardar_direcciones(lista):
    """Guarda lista de direcciones en JSON."""
    try:
        with open(RUTA_JSON, "w", encoding="utf-8") as f:
            json.dump(lista, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print("Error guardando archivo JSON:", e)

def menu_principal():
    while True:
        os.system('cls')
        print("\n=========== MENÚ PRINCIPAL ===========")
        print("\n")
        print("1) Iniciar monitoreo")
        print("2) Agregar nueva dirección")
        print("3) Salir")
        print("\n")
        print("======================================")

        opcion = input("Elige una opción: ").strip()

        if opcion == "1":
            return "monitorear"
        elif opcion == "2":
            return "agregar"
        elif opcion == "3":
            return "salir"
        else:
            print("Opción inválida.")

def menu_monitoreo():
    while True:
        os.system('cls')
        print("\n======= INICIAR MONITOREO =======")
        print("\n")
        print("1) Elegir de direcciones guardadas")
        print("2) Introducir IP manualmente")
        print("3) Volver")
        print("\n")
        print("==================================")

        opcion = input("Elige una opción: ").strip()

        if opcion in ("1", "2", "3"):
            return opcion
        print("Opción inválida.")

def elegir_guardada():
    direcciones = cargar_direcciones()
    if not direcciones:
        print("\nNo hay direcciones guardadas.")
        return None, None

    print("\n===== DIRECCIONES GUARDADAS =====")
    for idx, item in enumerate(direcciones, start=1):
        print(f"{idx}) {item['nombre']} — {item['ip']}")

    print(f"{len(direcciones)+1}) Volver")

    while True:
        op = input("Elige una dirección: ").strip()

        if op.isdigit():
            op = int(op)
            if 1 <= op <= len(direcciones):
                seleccion = direcciones[op-1]
                return seleccion["ip"], seleccion["nombre"]
            elif op == len(direcciones)+1:
                return None, None

        print("Opción inválida.")

def agregar_direccion():
    print("\n=== AGREGAR NUEVA DIRECCIÓN ===")

    nombre = input("Nombre descriptivo: ").strip()
    if not nombre:
        print("Nombre no válido.")
        return

    ip = input("IP: ").strip()

    if not validar_ip(ip):
        print("IP no válida.")
        return

    direcciones = cargar_direcciones()

    # validar duplicados
    for d in direcciones:
        if d["ip"] == ip:
            print("Esa IP ya está guardada.")
            return

    direcciones.append({"nombre": nombre, "ip": ip})
    guardar_direcciones(direcciones)

    print("Dirección guardada.")


# ---------------------------
# Thread para leer ping continuo
# ---------------------------
class PingThread(Thread):
    def __init__(self, ip, queue):
        super().__init__(daemon=True)
        self.ip = ip
        self.queue = queue
        self.running = True
        self.process = None

    def run(self):
        """Ejecuta ping -t y lee línea por línea."""
        try:
            # Ejecutar ping -t (Windows) o ping sin límite (Linux/Mac)
            if sys.platform == "win32":
                cmd = ["ping", "-t", self.ip]
            else:
                cmd = ["ping", self.ip]
            
            self.process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            # Leer línea por línea
            for line in iter(self.process.stdout.readline, ''):
                if not self.running:
                    break
                
                line = line.strip()
                if not line:
                    continue

                # Procesar línea
                ts = time.time()
                ms, linea_limpia = self.parse_line(line)
                
                # Enviar a la cola
                self.queue.put((ts, ms, linea_limpia))

        except Exception as e:
            self.queue.put((time.time(), None, f"error: {str(e)}"))
        finally:
            if self.process:
                self.process.terminate()

    def parse_line(self, line):
        """Parsea una línea de ping y extrae latencia y mensaje limpio."""
        # Buscar línea de respuesta
        if "Respuesta desde" in line or "Reply from" in line or "bytes from" in line.lower():
            # Extraer latencia
            m = re.search(r"(?:Tiempo|tiempo|time|Time)=? ?(\d+)ms", line)
            if m:
                ms = int(m.group(1))
                return ms, line
            else:
                return None, line
        
        # Detectar errores comunes
        elif "inaccesible" in line.lower() or "unreachable" in line.lower():
            return None, f"error: {line}"
        elif "no pudo encontrar" in line.lower() or "could not find" in line.lower():
            return None, f"error: {line}"
        elif "Tiempo de espera" in line or "Request timed out" in line or "timed out" in line.lower():
            return None, "error: Tiempo de espera agotado"
        
        # Ignorar líneas de encabezado o estadísticas
        elif "Haciendo ping" in line or "Pinging" in line:
            return None, None  # Ignorar
        elif "Estadísticas" in line or "Statistics" in line:
            return None, None  # Ignorar
        elif "Paquetes:" in line or "Packets:" in line:
            return None, None  # Ignorar
        elif "Aproximado" in line or "Approximate" in line:
            return None, None  # Ignorar
        elif "Mínimo" in line or "Minimum" in line:
            return None, None  # Ignorar
        
        # Línea desconocida pero podría ser relevante
        return None, line

    def stop(self):
        """Detiene el thread."""
        self.running = False
        if self.process:
            self.process.terminate()


# ---------------------------
# Ventana principal
# ---------------------------
class PingMonitor(QtWidgets.QMainWindow):
    ping_signal = pyqtSignal(float, object, str)  # ts, ms, linea

    def __init__(self, ip, nombre=None):
        super().__init__()
        self.ip = ip
        self.nombre = nombre

        self.latencias = []
        self.tiempos = []
        self.historial = []

        self.ts_inicio = time.time()
        self.historial = []

        # Datos
        self.latencias = deque(maxlen=MAX_POINTS)
        self.tiempos = deque(maxlen=MAX_POINTS)
        
        # Para estadísticas
        self.latencias_validas = []  # Solo latencias exitosas (no None)
        self.paquetes_enviados = 0
        self.paquetes_recibidos = 0
        self.paquetes_perdidos = 0

        # Queue para comunicación con thread
        self.ping_queue = Queue()
        
        # Thread de ping
        self.ping_thread = PingThread(self.ip, self.ping_queue)

        # UI
        self.init_ui()
        self.plot_widget.setYRange(0, 300)

        # Conectar señal
        self.ping_signal.connect(self.process_ping_result)

        # Timer para chequear la cola
        self.queue_timer = QtCore.QTimer()
        self.queue_timer.setInterval(50)  # Chequear cada 50ms
        self.queue_timer.timeout.connect(self.check_queue)
        self.queue_timer.start()

        # Iniciar thread de ping
        self.ping_thread.start()

    def init_ui(self):
        # Título con nombre (si existe) e IP
        if self.nombre:
            titulo = f"Ping Monitor — {self.nombre} ({self.ip})"
        else:
            titulo = f"Ping Monitor — {self.ip}"
        
        self.setWindowTitle(titulo)
        try:
            self.setWindowFlag(Qt.WindowStaysOnTopHint, False)
        except Exception:
            pass

        # Central widget y layout
        cw = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout()
        cw.setLayout(layout)
        self.setCentralWidget(cw)

        # Label de estado
        self.status_label = QtWidgets.QLabel("Iniciando ping persistente...")
        layout.addWidget(self.status_label)

        # Plot widget de pyqtgraph
        pg.setConfigOptions(antialias=True)
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.showGrid(x=True, y=True)
        self.plot_widget.setLabel("left", "Latencia (ms)")
        self.plot_widget.setLabel("bottom", "Hora")
        layout.addWidget(self.plot_widget)

        # Curve (línea) y scatter para fallos
        self.curve = self.plot_widget.plot([], [], pen=pg.mkPen(color='b', width=3))
        self.scatter = pg.ScatterPlotItem(size=8, brush=pg.mkBrush(255, 0, 0))
        self.plot_widget.addItem(self.scatter)

        # Botones
        btn_layout = QtWidgets.QHBoxLayout()
        
        self.btn_pause = QtWidgets.QPushButton("Pausar")
        self.btn_pause.setCheckable(True)
        self.btn_pause.toggled.connect(self.toggle_pause)
        btn_layout.addWidget(self.btn_pause)

        self.console = QtWidgets.QTextEdit()
        self.console.setReadOnly(True)
        self.console.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
        self.console.setFontFamily("Courier")

        self.btn_toggle_console = QtWidgets.QPushButton("Ocultar Terminal")
        self.btn_toggle_console.setCheckable(True)
        self.btn_toggle_console.toggled.connect(self.toggle_console)
        btn_layout.addWidget(self.btn_toggle_console)

        # Estilo
        self.console.setStyleSheet(f"""
            background-color: {BG_COLOR};
            color: {FG_COLOR};
        """)

        font = self.console.font()
        font.setPointSize(FONT_SIZE)
        self.console.setFont(font)

        layout.addWidget(self.console)

        self.btn_clear = QtWidgets.QPushButton("Limpiar")
        self.btn_clear.clicked.connect(self.clear)
        btn_layout.addWidget(self.btn_clear)

        self.btn_save = QtWidgets.QPushButton("Exportar sesión")
        self.btn_save.clicked.connect(self.guardar_manual)
        btn_layout.addWidget(self.btn_save)

        layout.addLayout(btn_layout)

        self.resize(700, 400)
        self.show()

    def toggle_console(self, checked):
        self.console.setVisible(not checked)
        if checked:
            self.btn_toggle_console.setText("Mostrar Terminal")
        else:
            self.btn_toggle_console.setText("Ocultar Terminal")

    def check_queue(self):
        """Revisa la cola y emite señales para procesar en el thread principal."""
        while not self.ping_queue.empty():
            ts, ms, linea = self.ping_queue.get()
            if linea is not None:  # Ignorar líneas vacías
                self.ping_signal.emit(ts, ms, linea)

    def process_ping_result(self, ts, ms, linea_limpia):
        """Procesa el resultado de un ping (ejecutado en thread principal de Qt)."""
        if self.btn_pause.isChecked():
            return

        self.historial.append((ts, ms, linea_limpia))

        # hora
        hora = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))

        # color según alerta
        if ms is None or ms > TIEMPO_MAXIMO:
            color = COLOR_ALERTA
        else:
            color = FG_COLOR

        # Guardar latencia válida para estadísticas
        if ms is not None:
            self.latencias_validas.append(ms)

        # Limpiar el contenido de la consola y redibujar todo
        self.console.clear()
        
        # Mostrar todas las líneas del historial
        for hist_ts, hist_ms, hist_linea in self.historial:
            hist_hora = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(hist_ts))
            
            if hist_ms is None or hist_ms > TIEMPO_MAXIMO:
                hist_color = COLOR_ALERTA
            else:
                hist_color = FG_COLOR
            
            self.console.append(
                f'<span style="color:{hist_color}">{hist_hora} - {hist_linea}</span>'
            )
        
        # Agregar línea de estadísticas al final
        if self.latencias_validas:
            minimo = min(self.latencias_validas)
            maximo = max(self.latencias_validas)
            media = sum(self.latencias_validas) / len(self.latencias_validas)
            
            self.console.append(
                f'<br><span style="color:{FG_COLOR}">──────────────────────────────────────</span>'
            )
            self.console.append(
                f'<span style="color:{FG_COLOR}">Estadísticas: Mínimo = {minimo}ms, Máximo = {maximo}ms, Media = {media:.1f}ms</span>'
            )

        # scroll automático al final
        self.console.verticalScrollBar().setValue(
            self.console.verticalScrollBar().maximum()
        )

        # registrar
        self.tiempos.append(ts)
        self.latencias.append(ms if ms is not None else 0)

        # actualizar status label
        if ms is None:
            self.status_label.setText(f"{hora} - FAIL")
        else:
            self.status_label.setText(f"{hora} - {ms} ms")

        # actualizar gráfica
        self.update_plot()

        # Guardar cada MAX_POINTS muestras
        if len(self.historial) % MAX_POINTS == 0:
            self.export_current_block()

    def guardar_manual(self):
        """Guarda manualmente el historial actual."""
        try:
            if not self.historial:
                QMessageBox.warning(self, "Sin datos", "No hay datos para guardar.")
                return

            ts_inicio = self.historial[0][0]
            ts_fin = self.historial[-1][0]

            fecha_inicio = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(ts_inicio))
            fecha_fin = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(ts_fin))

            base_dir = os.path.dirname(os.path.abspath(__file__))
            carpeta_ip = os.path.join(base_dir, "saves", self.ip)
            os.makedirs(carpeta_ip, exist_ok=True)

            nombre_archivo = f"save_{self.ip}_{fecha_inicio}_a_{fecha_fin}.csv"
            ruta_completa = os.path.join(carpeta_ip, nombre_archivo)

            with open(ruta_completa, "w", encoding="utf-8") as f:
                f.write(f"# Ping session (manual save)\n")
                f.write(f"# IP: {self.ip}\n")
                f.write(f"# Inicio: {fecha_inicio}\n")
                f.write(f"# Fin: {fecha_fin}\n")
                f.write("datetime,latencia_ms,respuesta\n")

                for item in self.historial:
                    if len(item) == 3:
                        ts, ms, linea = item
                    else:
                        ts, ms = item
                        linea = ""
                    dt = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
                    f.write(f"{dt},{ms if ms is not None else 'FAIL'},\"{linea}\"\n")

            QMessageBox.information(self, "Guardado", f"Archivo guardado en:\n{ruta_completa}")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo guardar:\n{str(e)}")

    def export_current_block(self):
        """Guarda la sesión actual en un archivo y continúa."""
        if not self.historial:
            return

        ts_inicio = self.historial[0][0]
        ts_fin = self.historial[-1][0]

        fecha_inicio = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(ts_inicio))
        fecha_fin = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(ts_fin))

        base_dir = os.path.dirname(os.path.abspath(__file__))
        carpeta_ip = os.path.join(base_dir, "pings", self.ip)
        os.makedirs(carpeta_ip, exist_ok=True)

        nombre_archivo = f"sesion_{self.ip}_{fecha_inicio}_a_{fecha_fin}.csv"
        ruta_completa = os.path.join(carpeta_ip, nombre_archivo)

        try:
            with open(ruta_completa, "w", encoding="utf-8") as f:
                f.write(f"# Ping session\n")
                f.write(f"# IP: {self.ip}\n")
                f.write(f"# Inicio: {fecha_inicio}\n")
                f.write(f"# Fin: {fecha_fin}\n")
                f.write("datetime,latencia_ms,respuesta\n")
                for ts, ms, linea in self.historial:
                    dt = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
                    f.write(f"{dt},{ms if ms is not None else 'FAIL'},\"{linea}\"\n")

            print(f"Bloque guardado: {ruta_completa}")
            self.historial = []
        except Exception as e:
            print("Error al guardar archivo:", e)

    def update_plot(self):
        n = len(self.latencias)
        y = list(self.latencias)

        # Curva azul
        self.curve.setData(range(n), y)

        # Eje X con hora
        x_labels = [time.strftime("%H:%M:%S", time.localtime(ts)) for ts in self.tiempos]

        vb = self.plot_widget.getViewBox()
        x_range = vb.viewRange()[0]
        num_visible_points = int(x_range[1] - x_range[0]) + 1

        if num_visible_points <= 0:
            num_visible_points = 1

        step = max(1, num_visible_points // 5)

        ticks = [(i, label) for i, label in enumerate(x_labels) if i % step == 0]
        self.plot_widget.getAxis('bottom').setTicks([ticks])

        # Fallos: puntos rojos
        puntos = [{'pos': (i, 0)} for i, v in enumerate(y) if v == 0]
        self.scatter.setData([p['pos'][0] for p in puntos], [p['pos'][1] for p in puntos])

        # Limitar vista
        if n > 120:
            self.plot_widget.setXRange(n - 120, n)

    def toggle_pause(self, paused):
        if paused:
            self.btn_pause.setText("Reanudar")
            self.status_label.setText("Pausado")
        else:
            self.btn_pause.setText("Pausar")

    def clear(self):
        self.latencias.clear()
        self.tiempos.clear()
        self.latencias_validas.clear()
        self.curve.setData([], [])
        self.scatter.setData([], [])
        self.console.clear()
        self.status_label.setText("Limpio")
    
    def closeEvent(self, event):
        # Detener thread de ping
        self.ping_thread.stop()
        # Guardar historial
        self.export_current_block()
        event.accept()


# ---------------------------
# Main
# ---------------------------
def main():
    while True:
        accion = menu_principal()

        if accion == "salir":
            print("Saliendo...")
            return

        elif accion == "agregar":
            agregar_direccion()

        elif accion == "monitorear":
            opcion = menu_monitoreo()

            if opcion == "3":
                continue

            elif opcion == "1":
                ip, nombre = elegir_guardada()
                if not ip:
                    continue

            elif opcion == "2":
                ip = input("IP a monitorear: ").strip()
                if not validar_ip(ip):
                    print("IP inválida.")
                    continue
                nombre = None  # No tiene nombre guardado

            # Iniciar monitor
            app = QtWidgets.QApplication(sys.argv)
            win = PingMonitor(ip, nombre)
            sys.exit(app.exec_())

if __name__ == "__main__":
    main()