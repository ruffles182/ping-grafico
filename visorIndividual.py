"""
Visor Individual de Ping con PyQt5
Integrado con netutils.py (ping_unico + SQLite)

Instalar: pip install pyqt5 pyqtgraph
Uso: python visorIndividual.py [IP]
"""

import sys
import time
from collections import deque
from threading import Thread
from queue import Queue
import sqlite3
import os

from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QMessageBox
import pyqtgraph as pg

from netutils import ping_unico, preparar_bd_sqlite, guardar_ping, validar_ip

# Configuración
MAX_POINTS = 1800  # Puntos máximos en pantalla
BG_COLOR = "#000000"
FG_COLOR = "#00FF00"
COLOR_ALERTA = "#FF0000"
FONT_SIZE = 10
TIEMPO_MAXIMO = 100  # ms para considerar alerta


class PingThread(Thread):
    """Thread que hace pings continuos usando ping_unico()."""

    def __init__(self, ip, queue, guardar_bd=True):
        super().__init__(daemon=True)
        self.ip = ip
        self.queue = queue
        self.running = True
        self.guardar_bd = guardar_bd
        self.conn = None

        if self.guardar_bd:
            # Preparar conexión a BD
            self.conn = preparar_bd_sqlite(ip)

    def run(self):
        """Loop principal de pings."""
        try:
            while self.running:
                ts = time.time()

                # Hacer ping usando nuestra función
                resultado_ms = ping_unico(self.ip)

                # Guardar en BD si está habilitado
                if self.guardar_bd and self.conn:
                    guardar_ping(self.conn, resultado_ms)

                # Enviar a la cola para UI
                self.queue.put((ts, resultado_ms))

        except Exception as e:
            self.queue.put((time.time(), None, f"ERROR: {str(e)}"))
        finally:
            if self.conn:
                self.conn.close()

    def stop(self):
        """Detiene el thread."""
        self.running = False


class VisorIndividual(QtWidgets.QMainWindow):
    """Ventana principal del visor."""

    ping_signal = pyqtSignal(float, float)  # ts, ms

    def __init__(self, ip, guardar_bd=True):
        super().__init__()

        if not validar_ip(ip):
            raise ValueError(f"IP inválida: {ip}")

        self.ip = ip
        self.guardar_bd = guardar_bd

        # Datos para gráfica
        self.latencias = deque(maxlen=MAX_POINTS)
        self.tiempos = deque(maxlen=MAX_POINTS)

        # Historial completo (para export)
        self.historial = []

        # Estadísticas
        self.latencias_validas = []
        self.paquetes_enviados = 0
        self.paquetes_recibidos = 0
        self.paquetes_perdidos = 0

        # Queue y thread
        self.ping_queue = Queue()
        self.ping_thread = PingThread(self.ip, self.ping_queue, self.guardar_bd)

        # UI
        self.init_ui()

        # Conectar señal
        self.ping_signal.connect(self.process_ping_result)

        # Timer para revisar queue
        self.queue_timer = QtCore.QTimer()
        self.queue_timer.setInterval(50)
        self.queue_timer.timeout.connect(self.check_queue)
        self.queue_timer.start()

        # Iniciar thread de ping
        self.ping_thread.start()

    def init_ui(self):
        """Inicializa la interfaz de usuario."""
        titulo = f"Monitor de Ping - {self.ip}"
        if self.guardar_bd:
            titulo += " [Guardando en BD]"
        else:
            titulo += " [Solo visualización]"

        self.setWindowTitle(titulo)
        self.setGeometry(100, 100, 900, 600)

        # Widget central
        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout()
        central.setLayout(layout)
        self.setCentralWidget(central)

        # ===== LABEL DE ESTADO =====
        self.status_label = QtWidgets.QLabel("Iniciando monitoreo...")
        self.status_label.setStyleSheet("font-size: 14px; padding: 5px;")
        layout.addWidget(self.status_label)

        # ===== GRÁFICA =====
        pg.setConfigOptions(antialias=True)
        self.plot_widget = pg.PlotWidget()
        self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
        self.plot_widget.setLabel("left", "Latencia (ms)")
        self.plot_widget.setLabel("bottom", "Tiempo")
        self.plot_widget.setYRange(0, 200)
        layout.addWidget(self.plot_widget)

        # Línea azul para latencias
        self.curve = self.plot_widget.plot([], [], pen=pg.mkPen(color='#00CC96', width=2))

        # Puntos rojos para fallos
        self.scatter = pg.ScatterPlotItem(size=10, brush=pg.mkBrush(255, 0, 0), symbol='x')
        self.plot_widget.addItem(self.scatter)

        # ===== ESTADÍSTICAS =====
        stats_layout = QtWidgets.QHBoxLayout()

        self.label_total = QtWidgets.QLabel("Total: 0")
        self.label_promedio = QtWidgets.QLabel("Promedio: -- ms")
        self.label_perdida = QtWidgets.QLabel("Pérdida: 0%")
        self.label_minmax = QtWidgets.QLabel("Min/Max: --/--")

        for label in [self.label_total, self.label_promedio, self.label_perdida, self.label_minmax]:
            label.setStyleSheet("font-size: 12px; padding: 5px; background-color: #f0f0f0; border-radius: 3px;")
            stats_layout.addWidget(label)

        layout.addLayout(stats_layout)

        # ===== CONSOLA =====
        self.console = QtWidgets.QTextEdit()
        self.console.setReadOnly(True)
        self.console.setFontFamily("Courier")
        self.console.setStyleSheet(f"background-color: {BG_COLOR}; color: {FG_COLOR};")
        font = self.console.font()
        font.setPointSize(FONT_SIZE)
        self.console.setFont(font)
        self.console.setMaximumHeight(150)
        layout.addWidget(self.console)

        # ===== BOTONES =====
        btn_layout = QtWidgets.QHBoxLayout()

        self.btn_pause = QtWidgets.QPushButton("⏸ Pausar")
        self.btn_pause.setCheckable(True)
        self.btn_pause.toggled.connect(self.toggle_pause)
        btn_layout.addWidget(self.btn_pause)

        self.btn_clear = QtWidgets.QPushButton("🗑 Limpiar")
        self.btn_clear.clicked.connect(self.clear)
        btn_layout.addWidget(self.btn_clear)

        self.btn_console = QtWidgets.QPushButton("👁 Ocultar Consola")
        self.btn_console.setCheckable(True)
        self.btn_console.toggled.connect(self.toggle_console)
        btn_layout.addWidget(self.btn_console)

        btn_layout.addStretch()

        self.btn_export = QtWidgets.QPushButton("💾 Exportar CSV")
        self.btn_export.clicked.connect(self.export_csv)
        btn_layout.addWidget(self.btn_export)

        layout.addLayout(btn_layout)

        # Ruta de BD
        if self.guardar_bd:
            ruta_bd = f"pings/{self.ip}/datos.db"
            label_bd = QtWidgets.QLabel(f"📁 Guardando en: {ruta_bd}")
            label_bd.setStyleSheet("font-size: 10px; color: gray;")
            layout.addWidget(label_bd)

        self.show()

    def check_queue(self):
        """Revisa la cola y procesa resultados."""
        while not self.ping_queue.empty():
            ts, ms = self.ping_queue.get()
            self.ping_signal.emit(ts, ms)

    def process_ping_result(self, ts, ms):
        """Procesa un resultado de ping."""
        if self.btn_pause.isChecked():
            return

        # Agregar al historial
        self.historial.append((ts, ms))

        # Contadores
        self.paquetes_enviados += 1
        if ms == -1:
            self.paquetes_perdidos += 1
            ms_display = 0  # Para gráfica
        else:
            self.paquetes_recibidos += 1
            self.latencias_validas.append(ms)
            ms_display = ms

        # Agregar a gráfica
        self.tiempos.append(ts)
        self.latencias.append(ms_display)

        # Actualizar UI
        self.update_status(ts, ms)
        self.update_stats()
        self.update_plot()
        self.update_console(ts, ms)

    def update_status(self, ts, ms):
        """Actualiza el label de estado."""
        hora = time.strftime('%H:%M:%S', time.localtime(ts))

        if ms == -1:
            self.status_label.setText(f"🔴 {hora} - TIMEOUT")
            self.status_label.setStyleSheet("font-size: 14px; padding: 5px; color: red; font-weight: bold;")
        elif ms > TIEMPO_MAXIMO:
            self.status_label.setText(f"🟡 {hora} - {ms:.1f} ms (ALTO)")
            self.status_label.setStyleSheet("font-size: 14px; padding: 5px; color: orange; font-weight: bold;")
        else:
            self.status_label.setText(f"🟢 {hora} - {ms:.1f} ms")
            self.status_label.setStyleSheet("font-size: 14px; padding: 5px; color: green;")

    def update_stats(self):
        """Actualiza las estadísticas."""
        self.label_total.setText(f"Total: {self.paquetes_enviados}")

        if self.latencias_validas:
            promedio = sum(self.latencias_validas) / len(self.latencias_validas)
            minimo = min(self.latencias_validas)
            maximo = max(self.latencias_validas)

            self.label_promedio.setText(f"Promedio: {promedio:.1f} ms")
            self.label_minmax.setText(f"Min/Max: {minimo:.1f}/{maximo:.1f} ms")

        if self.paquetes_enviados > 0:
            perdida = (self.paquetes_perdidos / self.paquetes_enviados) * 100
            self.label_perdida.setText(f"Pérdida: {perdida:.1f}%")

            if perdida > 5:
                self.label_perdida.setStyleSheet("font-size: 12px; padding: 5px; background-color: #ffcccc; border-radius: 3px; color: red; font-weight: bold;")
            elif perdida > 0:
                self.label_perdida.setStyleSheet("font-size: 12px; padding: 5px; background-color: #fff4cc; border-radius: 3px; color: orange;")
            else:
                self.label_perdida.setStyleSheet("font-size: 12px; padding: 5px; background-color: #ccffcc; border-radius: 3px; color: green;")

    def update_plot(self):
        """Actualiza la gráfica."""
        n = len(self.latencias)
        y = list(self.latencias)

        # Actualizar curva
        self.curve.setData(range(n), y)

        # Puntos rojos para fallos
        fallos = [(i, 0) for i, val in enumerate(y) if val == 0]
        if fallos:
            x_fallos, y_fallos = zip(*fallos)
            self.scatter.setData(x_fallos, y_fallos)
        else:
            self.scatter.setData([], [])

        # Ajustar vista para mostrar últimos 120 puntos
        if n > 120:
            self.plot_widget.setXRange(n - 120, n)

        # Etiquetas del eje X
        if self.tiempos:
            x_labels = [time.strftime("%H:%M:%S", time.localtime(ts)) for ts in self.tiempos]
            step = max(1, n // 10)
            ticks = [(i, label) for i, label in enumerate(x_labels) if i % step == 0]
            self.plot_widget.getAxis('bottom').setTicks([ticks])

    def update_console(self, ts, ms):
        """Actualiza la consola."""
        hora = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))

        if ms == -1:
            color = COLOR_ALERTA
            texto = f"{hora} - TIMEOUT"
        elif ms > TIEMPO_MAXIMO:
            color = COLOR_ALERTA
            texto = f"{hora} - {ms:.1f} ms (ALTO)"
        else:
            color = FG_COLOR
            texto = f"{hora} - {ms:.1f} ms"

        self.console.append(f'<span style="color:{color}">{texto}</span>')

        # Auto-scroll
        self.console.verticalScrollBar().setValue(
            self.console.verticalScrollBar().maximum()
        )

    def toggle_pause(self, checked):
        """Pausa/reanuda el monitoreo."""
        if checked:
            self.btn_pause.setText("▶ Reanudar")
        else:
            self.btn_pause.setText("⏸ Pausar")

    def toggle_console(self, checked):
        """Muestra/oculta la consola."""
        self.console.setVisible(not checked)
        if checked:
            self.btn_console.setText("👁 Mostrar Consola")
        else:
            self.btn_console.setText("👁 Ocultar Consola")

    def clear(self):
        """Limpia datos."""
        self.latencias.clear()
        self.tiempos.clear()
        self.latencias_validas.clear()
        self.paquetes_enviados = 0
        self.paquetes_recibidos = 0
        self.paquetes_perdidos = 0
        self.historial.clear()

        self.curve.setData([], [])
        self.scatter.setData([], [])
        self.console.clear()

        self.update_stats()
        self.status_label.setText("Limpiado")

    def export_csv(self):
        """Exporta el historial a CSV."""
        if not self.historial:
            QMessageBox.warning(self, "Sin datos", "No hay datos para exportar.")
            return

        try:
            ts_inicio = self.historial[0][0]
            ts_fin = self.historial[-1][0]

            fecha_inicio = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(ts_inicio))
            fecha_fin = time.strftime("%Y-%m-%d_%H-%M-%S", time.localtime(ts_fin))

            carpeta = os.path.join("exports", self.ip)
            os.makedirs(carpeta, exist_ok=True)

            nombre = f"export_{self.ip}_{fecha_inicio}_a_{fecha_fin}.csv"
            ruta = os.path.join(carpeta, nombre)

            with open(ruta, "w", encoding="utf-8") as f:
                f.write(f"# IP: {self.ip}\n")
                f.write(f"# Inicio: {fecha_inicio}\n")
                f.write(f"# Fin: {fecha_fin}\n")
                f.write("timestamp,latencia_ms\n")

                for ts, ms in self.historial:
                    dt = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
                    f.write(f"{dt},{ms if ms != -1 else 'TIMEOUT'}\n")

            QMessageBox.information(self, "Exportado", f"Archivo guardado en:\n{ruta}")

        except Exception as e:
            QMessageBox.critical(self, "Error", f"No se pudo exportar:\n{str(e)}")

    def closeEvent(self, event):
        """Evento al cerrar la ventana."""
        self.ping_thread.stop()
        event.accept()


def main():
    """Función principal."""
    if len(sys.argv) > 1:
        ip = sys.argv[1]
    else:
        print("Uso: python visorIndividual.py [IP]")
        ip = input("Ingresa la IP a monitorear: ").strip()

    if not validar_ip(ip):
        print(f"Error: '{ip}' no es una IP válida")
        sys.exit(1)

    # Preguntar si guardar en BD
    print("\n¿Guardar pings en base de datos SQLite?")
    print("1) Sí (pings/IP/datos.db)")
    print("2) No (solo visualizar)")

    opcion = input("Opción [1]: ").strip() or "1"
    guardar_bd = (opcion == "1")

    app = QtWidgets.QApplication(sys.argv)
    visor = VisorIndividual(ip, guardar_bd)
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
