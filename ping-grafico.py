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
import pyqtgraph as pg

load_dotenv()

DEFAULT_IP = os.getenv("DEFAULT_IP", "8.8.8.8")
DEFAULT_INTERVAL = float(os.getenv("DEFAULT_INTERVAL", 2.0))
MAX_POINTS = 1800 


# ---------------------------
# Función ping (Windows)
# ---------------------------
def hacer_ping(ip):
    """Hace un ping -n 1 en Windows y devuelve latencia en ms o None si falla."""
    try:
        salida = subprocess.run(["ping", "-n", "1", ip], capture_output=True, text=True, timeout=3).stdout
    except subprocess.TimeoutExpired:
        return None

    # Regex flexible (español/inglés)
    m = re.search(r"(?:Tiempo|tiempo|time|Time)=? ?(\d+)ms", salida)
    if m:
        try:
            return int(m.group(1))
        except:
            return None
    return None

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

        self.btn_clear = QtWidgets.QPushButton("Limpiar")
        self.btn_clear.clicked.connect(self.clear)
        btn_layout.addWidget(self.btn_clear)

        self.btn_export = QtWidgets.QPushButton("Exportar sesión / última hora")
        self.btn_export.clicked.connect(self.export_current_block)
        btn_layout.addWidget(self.btn_export)


        layout.addLayout(btn_layout)

        # inicial tamaño
        self.resize(700, 400)
        # mostrar
        self.show()

    def tick_ping(self):
        """Se llama por QTimer cada intervalo: hace ping y actualiza datos/gráfica."""
        if self.btn_pause.isChecked():
            return

        ts = time.time()
        ms = hacer_ping(self.ip)
        self.historial.append((ts, ms))
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
        self.historial.append((ts, ms))

        # Guardar cada MAX_POINTS muestras en un archivo
        if len(self.historial) % MAX_POINTS == 0:
            self.export_current_block()

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
                f.write(f"timestamp,datetime,latencia_ms\n")
                for ts, ms in self.historial:
                    dt = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
                    f.write(f"{ts},{dt},{ms if ms is not None else 'FAIL'}\n")
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
    ip_input = input(f"IP a monitorear [{DEFAULT_IP}]: ").strip() or DEFAULT_IP
    try:
        intervalo = float(input(f"Tiempo de muestreo (s) [{DEFAULT_INTERVAL}]: ").strip() or DEFAULT_INTERVAL)
    except:
        intervalo = DEFAULT_INTERVAL

    app = QtWidgets.QApplication(sys.argv)
    win = PingMonitor(ip_input, intervalo)
    # Ejecutar loop Qt
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
