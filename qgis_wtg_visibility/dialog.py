# -*- coding: utf-8 -*-
"""Dialog principale plugin."""

from qgis.PyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QProgressBar,
    QRadioButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class WtgVisibilityDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("WTG Visible Height")
        self.resize(720, 760)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)

        # DEM
        dem_row = QHBoxLayout()
        self.dem_combo = QComboBox()
        self.dem_file_edit = QLineEdit()
        self.dem_file_btn = QPushButton("DEM da file…")
        dem_row.addWidget(QLabel("Layer DEM:"))
        dem_row.addWidget(self.dem_combo, 2)
        dem_row.addWidget(self.dem_file_edit, 2)
        dem_row.addWidget(self.dem_file_btn)
        root.addLayout(dem_row)

        # mode
        mode_box = QGroupBox("Modalità")
        mode_layout = QHBoxLayout(mode_box)
        self.single_radio = QRadioButton("Singola WTG")
        self.multi_radio = QRadioButton("Multi-WTG")
        self.single_radio.setChecked(True)
        mode_layout.addWidget(self.single_radio)
        mode_layout.addWidget(self.multi_radio)
        root.addWidget(mode_box)

        self.single_group = self._single_group()
        self.multi_group = self._multi_group()
        root.addWidget(self.single_group)
        root.addWidget(self.multi_group)

        self.common_group = self._common_group()
        root.addWidget(self.common_group)

        actions = QHBoxLayout()
        self.run_btn = QPushButton("Esegui")
        self.close_btn = QPushButton("Chiudi")
        actions.addStretch(1)
        actions.addWidget(self.run_btn)
        actions.addWidget(self.close_btn)
        root.addLayout(actions)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        root.addWidget(self.progress)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        root.addWidget(self.log_text, 1)

        self.dem_file_btn.clicked.connect(self._pick_dem)
        self.close_btn.clicked.connect(self.reject)
        self.single_radio.toggled.connect(self._refresh_mode)
        self._refresh_mode()

    def _single_group(self):
        box = QGroupBox("Singola WTG")
        form = QFormLayout(box)

        self.x_spin = QDoubleSpinBox()
        self.x_spin.setDecimals(3)
        self.x_spin.setRange(-1e9, 1e9)
        self.y_spin = QDoubleSpinBox()
        self.y_spin.setDecimals(3)
        self.y_spin.setRange(-1e9, 1e9)
        self.h_spin = QDoubleSpinBox()
        self.h_spin.setRange(0.1, 1000.0)
        self.h_spin.setValue(200.0)

        self.out_file_edit = QLineEdit()
        self.out_file_btn = QPushButton("Output raster…")
        out_row = QHBoxLayout()
        out_row.addWidget(self.out_file_edit, 1)
        out_row.addWidget(self.out_file_btn)
        out_wrap = QWidget()
        out_wrap.setLayout(out_row)

        form.addRow("WTG X", self.x_spin)
        form.addRow("WTG Y", self.y_spin)
        form.addRow("WTG H (m)", self.h_spin)
        form.addRow("Output", out_wrap)

        self.out_file_btn.clicked.connect(self._pick_out_file)
        return box

    def _multi_group(self):
        box = QGroupBox("Multi-WTG")
        form = QFormLayout(box)

        self.wtg_combo = QComboBox()
        self.h_field_combo = QComboBox()
        self.id_field_combo = QComboBox()
        self.out_dir_edit = QLineEdit()
        self.out_dir_btn = QPushButton("Cartella output…")
        dir_row = QHBoxLayout()
        dir_row.addWidget(self.out_dir_edit, 1)
        dir_row.addWidget(self.out_dir_btn)
        dir_wrap = QWidget()
        dir_wrap.setLayout(dir_row)

        self.csv_check = QCheckBox("Genera CSV riepilogativo")
        self.csv_edit = QLineEdit()
        self.csv_btn = QPushButton("CSV…")
        csv_row = QHBoxLayout()
        csv_row.addWidget(self.csv_edit, 1)
        csv_row.addWidget(self.csv_btn)
        csv_wrap = QWidget()
        csv_wrap.setLayout(csv_row)

        form.addRow("Layer WTG", self.wtg_combo)
        form.addRow("Campo altezza", self.h_field_combo)
        form.addRow("Campo ID (opzionale)", self.id_field_combo)
        form.addRow("Cartella output", dir_wrap)
        form.addRow(self.csv_check)
        form.addRow("CSV", csv_wrap)

        self.out_dir_btn.clicked.connect(self._pick_out_dir)
        self.csv_btn.clicked.connect(self._pick_csv)
        return box

    def _common_group(self):
        box = QGroupBox("Parametri comuni")
        form = QFormLayout(box)

        self.observer_spin = QDoubleSpinBox()
        self.observer_spin.setRange(0.0, 100.0)
        self.observer_spin.setValue(1.6)
        self.radius_spin = QSpinBox()
        self.radius_spin.setRange(1, 15000)
        self.radius_spin.setValue(10000)
        self.step_spin = QDoubleSpinBox()
        self.step_spin.setRange(0.1, 1000.0)
        self.step_spin.setValue(24.0)
        self.k_spin = QSpinBox()
        self.k_spin.setRange(16, 200000)
        self.k_spin.setValue(8192)
        self.strict_check = QCheckBox("strict nodata")
        self.strict_check.setChecked(True)
        self.add_to_project_check = QCheckBox("Aggiungi raster al progetto")
        self.add_to_project_check.setChecked(True)

        self.fine_enable_check = QCheckBox("Abilita bbox infittimento")
        self.bbox_minx = QDoubleSpinBox(); self.bbox_minx.setRange(-1e9, 1e9)
        self.bbox_miny = QDoubleSpinBox(); self.bbox_miny.setRange(-1e9, 1e9)
        self.bbox_maxx = QDoubleSpinBox(); self.bbox_maxx.setRange(-1e9, 1e9)
        self.bbox_maxy = QDoubleSpinBox(); self.bbox_maxy.setRange(-1e9, 1e9)
        self.step_fine = QDoubleSpinBox(); self.step_fine.setRange(0.1, 1000.0); self.step_fine.setValue(12.0)
        self.k_fine = QSpinBox(); self.k_fine.setRange(16, 300000); self.k_fine.setValue(12288)
        self.fine_separate_check = QCheckBox("Crea raster infittito separato")
        self.fine_separate_check.setChecked(True)

        form.addRow("Observer height (m)", self.observer_spin)
        form.addRow("max_distance_m", self.radius_spin)
        form.addRow("step_global", self.step_spin)
        form.addRow("K_global", self.k_spin)
        form.addRow(self.strict_check)
        form.addRow(self.add_to_project_check)
        form.addRow(self.fine_enable_check)
        form.addRow("bbox minX", self.bbox_minx)
        form.addRow("bbox minY", self.bbox_miny)
        form.addRow("bbox maxX", self.bbox_maxx)
        form.addRow("bbox maxY", self.bbox_maxy)
        form.addRow("step_fine", self.step_fine)
        form.addRow("K_fine", self.k_fine)
        form.addRow(self.fine_separate_check)
        return box

    def _refresh_mode(self):
        self.single_group.setVisible(self.single_radio.isChecked())
        self.multi_group.setVisible(self.multi_radio.isChecked())

    def _pick_dem(self):
        path, _ = QFileDialog.getOpenFileName(self, "DEM", "", "GeoTIFF (*.tif *.tiff)")
        if path:
            self.dem_file_edit.setText(path)

    def _pick_out_file(self):
        path, _ = QFileDialog.getSaveFileName(self, "Output raster", "visible_height.tif", "GeoTIFF (*.tif)")
        if path:
            self.out_file_edit.setText(path)

    def _pick_out_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Cartella output")
        if path:
            self.out_dir_edit.setText(path)

    def _pick_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "CSV output", "wtg_summary.csv", "CSV (*.csv)")
        if path:
            self.csv_edit.setText(path)

    def log(self, msg: str):
        self.log_text.append(msg)
        self.log_text.moveCursor(self.log_text.textCursor().End)

    def set_progress(self, pct: float):
        self.progress.setValue(int(max(0.0, min(100.0, pct))))

    def show_warning(self, text: str):
        self.log(f"⚠ {text}")

    def selected_mode(self) -> str:
        return "single" if self.single_radio.isChecked() else "multi"
