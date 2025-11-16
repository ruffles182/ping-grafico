"""
ping_pyqtgraph.py
Monitorea una IP con ping cada intervalo y muestra gráfica en tiempo real usando pyqtgraph.
Instalar: pip install pyqt5 pyqtgraph
"""

import sys
import subprocess
import re
import time
from collections import deque
import os
from dotenv import load_dotenv

from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox
import pyqtgraph as pg
import argparse
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


# ---------------------------
# Función ping (Windows)
# ---------------------------
def hacer_ping(ip):
    """Hace un ping -n 1 en Windows y devuelve latencia en ms y línea completa."""
    try:
        result = subprocess.run(
            ["ping", "-n", "1", ip],
            capture_output=True,
            text=True,
            timeout=3
        )
        salida = result.stdout.strip()
    except subprocess.TimeoutExpired:
        return None, f"Timeout al hacer ping a {ip}"

    # Regex para extraer latencia
    m = re.search(r"(?:Tiempo|tiempo|time|Time)=? ?(\d+)ms", salida)
    if m:
        try:
            return int(m.group(1)), salida
        except:
            return None, salida

    return None, salida

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
        return None

    print("\n===== DIRECCIONES GUARDADAS =====")
    for idx, item in enumerate(direcciones, start=1):
        print(f"{idx}) {item['nombre']} — {item['ip']}")

    print(f"{len(direcciones)+1}) Volver")

    while True:
        op = input("Elige una dirección: ").strip()

        if op.isdigit():
            op = int(op)
            if 1 <= op <= len(direcciones):
                return direcciones[op-1]["ip"]
            elif op == len(direcciones)+1:
                return None

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
# Ventana principal
# ---------------------------
class PingMonitor(QtWidgets.QMainWindow):
    def __init__(self, ip, intervalo):
        super().__init__()
        self.ip = ip
        self.intervalo = intervalo

        self.latencias = []
        self.tiempos = []
        self.historial = []

        self.ts_inicio = time.time()        # timestamp inicio de sesión
        self.historial = []                 # guardará (timestamp, ms)

        # Datos
        self.latencias = deque(maxlen=MAX_POINTS)
        self.tiempos = deque(maxlen=MAX_POINTS)
        self.ultimo_ts = time.time()

        # UI
        self.init_ui()
        self.plot_widget.setYRange(0, 300)  # O el máximo que quieras

        # QTimer para pings periódicos (no bloqueante)
        self.timer = QtCore.QTimer()
        self.timer.setInterval(int(self.intervalo * 1000))
        self.timer.timeout.connect(self.tick_ping)
        self.timer.start()

    def init_ui(self):
        self.setWindowTitle(f"Ping Monitor — {self.ip} every {self.intervalo}s")
        # quitar siempre-arriba por si acaso
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
        self.status_label = QtWidgets.QLabel("Iniciando...")
        layout.addWidget(self.status_label)

        # Plot widget de pyqtgraph
        pg.setConfigOptions(antialias=True)  # suaviza líneas
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.showGrid(x=True, y=True)
        self.plot_widget.setLabel("left", "Latencia (ms)")
        self.plot_widget.setLabel("bottom", "Hora")
        layout.addWidget(self.plot_widget)

        # Curve (línea) y scatter para fallos
        self.curve = self.plot_widget.plot([], [], pen=pg.mkPen(color='b', width=3))
        self.scatter = pg.ScatterPlotItem(size=8, brush=pg.mkBrush(255, 0, 0))
        self.plot_widget.addItem(self.scatter)

        # Botones simples
        btn_layout = QtWidgets.QHBoxLayout()
        self.btn_pause = QtWidgets.QPushButton("Pausar")
        self.btn_pause.setCheckable(True)
        self.btn_pause.toggled.connect(self.toggle_pause)
        btn_layout.addWidget(self.btn_pause)

        self.console = QtWidgets.QTextEdit()
        self.console.setReadOnly(True)
        self.console.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
        self.console.setFontFamily("Courier")  # monoespaciado

        self.btn_toggle_console = QtWidgets.QPushButton("Ocultar Terminal")
        self.btn_toggle_console.setCheckable(True)
        self.btn_toggle_console.toggled.connect(self.toggle_console)
        btn_layout.addWidget(self.btn_toggle_console)

        # Estilo dinámico
        self.console.setStyleSheet(f"""
            background-color: {BG_COLOR};
            color: {FG_COLOR};
        """)

        # Tamaño de fuente
        font = self.console.font()
        font.setPointSize(FONT_SIZE)
        self.console.setFont(font)

        layout.addWidget(self.console)

        self.btn_clear = QtWidgets.QPushButton("Limpiar")
        self.btn_clear.clicked.connect(self.clear)
        btn_layout.addWidget(self.btn_clear)

        self.btn_save = QtWidgets.QPushButton("Exportar sesión / última hora")
        self.btn_save.clicked.connect(self.guardar_manual)
        btn_layout.addWidget(self.btn_save)

        layout.addLayout(btn_layout)

        # inicial tamaño
        self.resize(700, 400)
        # mostrar
        self.show()

    def toggle_console(self, checked):
        """
        Alterna visibilidad de la consola.
        Si está oculta, la gráfica ocupa todo el espacio.
        """
        self.console.setVisible(not checked)
        if checked:
            self.btn_toggle_console.setText("Mostrar Terminal")
        else:
            self.btn_toggle_console.setText("Ocultar Terminal")

    def tick_ping(self):
        """Se llama por QTimer cada intervalo: hace ping y actualiza datos/gráfica."""
        if self.btn_pause.isChecked():
            return

        ms, linea_completa = hacer_ping(self.ip)
        ts = time.time()
        self.historial.append((ts, ms, linea_completa))

        # línea original del ping
        # convertir saltos de línea a <br> para que QTextEdit respete la separación
        linea_html = linea_completa.replace("\n", "<br>")

        # hora
        hora = time.strftime('%H:%M:%S', time.localtime(ts))

        # color según alerta
        if ms is None or ms > TIEMPO_MAXIMO:
            color = COLOR_ALERTA
        else:
            color = FG_COLOR

        # agregar SOLO UNA línea a la consola
        self.console.append(
            f'<span style="color:{color}">{hora} - {linea_html}</span>'
        )

        # scroll automático
        self.console.verticalScrollBar().setValue(
            self.console.verticalScrollBar().maximum()
        )
        # Auto scroll
        self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())

        linea_mostrar = f"{time.strftime('%H:%M:%S')} - {linea_completa}"
        self.console.append(linea_mostrar)
        self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())

        # registrar
        self.tiempos.append(ts)
        self.latencias.append(ms if ms is not None else 0)

        # actualizar status label
        if ms is None:
            self.status_label.setText(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - FAIL")
        else:
            self.status_label.setText(f"{time.strftime('%Y-%m-%d %H:%M:%S')} - {ms} ms")

        # actualizar gráfica
        self.update_plot()

        # Guardar cada MAX_POINTS muestras en un archivo
        if len(self.historial) % MAX_POINTS == 0:
            self.export_current_block()

    def guardar_manual(self):
        """Guarda manualmente el contenido actual del historial."""
        try:
            ip_folder = f"saves/{self.ip}"
            os.makedirs(ip_folder, exist_ok=True)

            timestamp = time.strftime("%Y%m%d_%H%M%S")
            filename = f"{ip_folder}/save_{timestamp}.txt"

            with open(filename, "w", encoding="utf-8") as f:
                for item in self.historial:
                    # Asegurar que tiene 3 campos
                    if len(item) == 3:
                        ts, ms, linea = item
                    else:
                        # si por error quedó de 2, completar
                        ts, ms = item
                        linea = ""
                    hora = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))
                    f.write(f"{hora} | {ms} ms | {linea}\n")

            QMessageBox.information(self, "Guardado", f"Archivo guardado en:\n{filename}")

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
                f.write("timestamp,datetime,latencia_ms,linea_ping\n")
                for ts, ms, linea in self.historial:
                    dt = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
                    f.write(f"{ts},{dt},{ms if ms is not None else 'FAIL'},\"{linea}\"\n")

            print(f"Bloque guardado: {ruta_completa}")
            self.historial = []  # limpiar para siguiente bloque
        except Exception as e:
            print("Error al guardar archivo:", e)


    def update_plot(self):
        n = len(self.latencias)
        y = list(self.latencias)

        # Curva azul
        self.curve.setData(range(n), y)

        # Eje X con hora
        x_labels = [time.strftime("%H:%M:%S", time.localtime(ts)) for ts in self.tiempos]

        # Calcular la cantidad de etiquetas según el rango visible
        vb = self.plot_widget.getViewBox()
        x_range = vb.viewRange()[0]  # devuelve [min, max] del eje X visible
        num_visible_points = int(x_range[1] - x_range[0]) + 1

        if num_visible_points <= 0:
            num_visible_points = 1

        step = max(1, num_visible_points // 5)  # al menos 5 etiquetas visibles

        ticks = [(i, label) for i, label in enumerate(x_labels) if i % step == 0]
        self.plot_widget.getAxis('bottom').setTicks([ticks])

        # Fallos: puntos rojos donde y==0
        puntos = [{'pos': (i, 0)} for i, v in enumerate(y) if v == 0]
        self.scatter.setData([p['pos'][0] for p in puntos], [p['pos'][1] for p in puntos])

        # Limitar vista a última porción
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
        self.curve.setData([], [])
        self.scatter.setData([], [])
        self.status_label.setText("Limpio")
    
    
    def closeEvent(self, event):
        # Guardar lo que quede en historial
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

            if opcion == "3":  # volver
                continue

            elif opcion == "1":
                ip = elegir_guardada()
                if not ip:
                    continue

            elif opcion == "2":
                ip = input("IP a monitorear: ").strip()
                if not validar_ip(ip):
                    print("IP inválida.")
                    continue

            # intervalo se mantiene como antes
            try:
                intervalo = float(input(
                    f"Tiempo de muestreo (s) [{DEFAULT_INTERVAL}]: "
                ).strip() or DEFAULT_INTERVAL)
            except:
                intervalo = DEFAULT_INTERVAL
            
            # inicio del monitor
            app = QtWidgets.QApplication(sys.argv)
            win = PingMonitor(ip, intervalo)
            sys.exit(app.exec_())

if __name__ == "__main__":
    main()
