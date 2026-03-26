# -*- coding: utf-8 -*-
"""Main plugin class + QgsTask orchestration."""

import os
from typing import List

from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import Qgis, QgsApplication, QgsProject, QgsRasterLayer, QgsTask, QgsVectorLayer

from .calc_core import BBox, FineConfig, RadialConfig, compute_visibility_radial
from .dialog import WtgVisibilityDialog
from .raster_utils import is_metric_projected_crs, qgis_raster_source_path, read_dem_from_path, write_geotiff
from .wtg_batch import run_batch, vector_features_to_items


class ComputeTask(QgsTask):
    def __init__(self, description: str, fn, done_cb, fail_cb):
        super().__init__(description, QgsTask.CanCancel)
        self._fn = fn
        self._done_cb = done_cb
        self._fail_cb = fail_cb
        self._result = None
        self._error = None

    def run(self):
        try:
            self._result = self._fn(self)
            return True
        except Exception as exc:  # pylint: disable=broad-except
            self._error = exc
            return False

    def finished(self, ok):
        if ok:
            self._done_cb(self._result)
        else:
            self._fail_cb(self._error)


class WtgVisibilityPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dialog = None

    def tr(self, message):
        return QCoreApplication.translate("WtgVisibilityPlugin", message)

    def initGui(self):
        self.action = QAction(self.tr("WTG Visible Height"), self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu(self.tr("&WTG Visible Height"), self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        if self.action:
            self.iface.removePluginMenu(self.tr("&WTG Visible Height"), self.action)
            self.iface.removeToolBarIcon(self.action)

    def run(self):
        if self.dialog is None:
            self.dialog = WtgVisibilityDialog(self.iface.mainWindow())
            self.dialog.run_btn.clicked.connect(self._on_execute)
            self.dialog.dem_combo.currentIndexChanged.connect(self._on_dem_changed)
            self.dialog.wtg_combo.currentIndexChanged.connect(self._on_wtg_changed)
        self._refresh_layers()
        self.dialog.show()
        self.dialog.raise_()

    def _refresh_layers(self):
        d = self.dialog
        d.dem_combo.clear()
        d.wtg_combo.clear()

        for layer in QgsProject.instance().mapLayers().values():
            if isinstance(layer, QgsRasterLayer):
                d.dem_combo.addItem(layer.name(), layer.id())
            elif isinstance(layer, QgsVectorLayer):
                if layer.geometryType() == Qgis.GeometryType.Point:
                    d.wtg_combo.addItem(layer.name(), layer.id())
        self._on_dem_changed()
        self._on_wtg_changed()

    def _layer_by_combo(self, combo):
        layer_id = combo.currentData()
        return QgsProject.instance().mapLayer(layer_id) if layer_id else None

    def _on_dem_changed(self):
        layer = self._layer_by_combo(self.dialog.dem_combo)
        if not layer:
            return
        extent = layer.extent()
        self.dialog.x_spin.setValue(extent.center().x())
        self.dialog.y_spin.setValue(extent.center().y())

    def _on_wtg_changed(self):
        d = self.dialog
        d.h_field_combo.clear()
        d.id_field_combo.clear()
        layer = self._layer_by_combo(d.wtg_combo)
        if not layer:
            return
        for fld in layer.fields():
            d.id_field_combo.addItem(fld.name())
            if fld.isNumeric():
                d.h_field_combo.addItem(fld.name())

    def _pick_dem_path(self):
        if self.dialog.dem_file_edit.text().strip():
            return self.dialog.dem_file_edit.text().strip()
        layer = self._layer_by_combo(self.dialog.dem_combo)
        return qgis_raster_source_path(layer) if layer else ""

    def _validate(self):
        d = self.dialog
        dem_path = self._pick_dem_path()
        if not dem_path or not os.path.exists(dem_path):
            raise ValueError("DEM mancante o non valido")

        dem_layer = self._layer_by_combo(d.dem_combo)
        if dem_layer and not is_metric_projected_crs(dem_layer.crs()):
            raise ValueError("DEM in CRS geografico: usare un raster metrico proiettato")

        if d.selected_mode() == "single" and not d.out_file_edit.text().strip():
            raise ValueError("Specificare output raster")

        if d.selected_mode() == "multi":
            vec_layer = self._layer_by_combo(d.wtg_combo)
            if vec_layer is None:
                raise ValueError("Layer WTG mancante")
            if d.h_field_combo.count() == 0:
                raise ValueError("Nessun campo numerico per altezza WTG")
            out_dir = d.out_dir_edit.text().strip()
            if not out_dir:
                raise ValueError("Cartella output mancante")
            if not os.path.isdir(out_dir):
                raise ValueError("Cartella output non valida")

    def _on_execute(self):
        d = self.dialog
        try:
            self._validate()
        except Exception as exc:  # pylint: disable=broad-except
            QMessageBox.warning(self.iface.mainWindow(), "WTG Visible Height", str(exc))
            return

        dem_layer = self._layer_by_combo(d.dem_combo)
        dem_path = self._pick_dem_path()
        run_ctx = {
            "mode": d.selected_mode(),
            "dem_path": dem_path,
            "dem_layer_crs": dem_layer.crs() if dem_layer else None,
            "observer_height": float(d.observer_spin.value()),
            "radial_cfg": RadialConfig(
                radius_m=float(d.radius_spin.value()),
                step_m=float(d.step_spin.value()),
                k_rays=int(d.k_spin.value()),
                strict_nodata=bool(d.strict_check.isChecked()),
            ),
            "fine_cfg": FineConfig(
                enabled=bool(d.fine_enable_check.isChecked()),
                bbox=BBox(d.bbox_minx.value(), d.bbox_miny.value(), d.bbox_maxx.value(), d.bbox_maxy.value()) if d.fine_enable_check.isChecked() else None,
                step_m=float(d.step_fine.value()),
                k_rays=int(d.k_fine.value()),
                create_separate_raster=bool(d.fine_separate_check.isChecked()),
            ),
            "single": {
                "x": float(d.x_spin.value()),
                "y": float(d.y_spin.value()),
                "h": float(d.h_spin.value()),
                "out_path": d.out_file_edit.text().strip(),
            },
            "multi": {
                "vector_layer_id": d.wtg_combo.currentData(),
                "h_field": d.h_field_combo.currentText(),
                "id_field": d.id_field_combo.currentText() if d.id_field_combo.currentText() else None,
                "output_dir": d.out_dir_edit.text().strip(),
                "csv_path": d.csv_edit.text().strip() if d.csv_check.isChecked() else None,
            },
        }

        d.log("Avvio calcolo...")
        d.set_progress(0)
        d.run_btn.setEnabled(False)

        task = ComputeTask(
            "WTG Visible Height",
            lambda t: self._run_compute(t, run_ctx),
            self._on_done,
            self._on_fail,
        )
        QgsApplication.taskManager().addTask(task)

    def _run_compute(self, task, run_ctx):
        dem_path = run_ctx["dem_path"]
        dem_data = read_dem_from_path(dem_path)
        radial_cfg = run_ctx["radial_cfg"]
        fine_cfg = run_ctx["fine_cfg"]
        mode = run_ctx["mode"]
        if mode == "single":
            single_ctx = run_ctx["single"]
            out_path = single_ctx["out_path"]
            values = compute_visibility_radial(
                dem=dem_data.array,
                transform=dem_data.transform,
                dem_nodata=dem_data.nodata,
                turbine_x=single_ctx["x"],
                turbine_y=single_ctx["y"],
                turbine_height=single_ctx["h"],
                observer_height=run_ctx["observer_height"],
                config=radial_cfg,
                progress_cb=lambda p: task.setProgress(p * 90.0),
            )
            write_geotiff(out_path, dem_data.profile, values)
            outputs: List[str] = [out_path]

            if fine_cfg.enabled and fine_cfg.bbox and fine_cfg.create_separate_raster:
                fine_values = compute_visibility_radial(
                    dem=dem_data.array,
                    transform=dem_data.transform,
                    dem_nodata=dem_data.nodata,
                    turbine_x=single_ctx["x"],
                    turbine_y=single_ctx["y"],
                    turbine_height=single_ctx["h"],
                    observer_height=run_ctx["observer_height"],
                    config=RadialConfig(
                        radius_m=radial_cfg.radius_m,
                        step_m=fine_cfg.step_m,
                        k_rays=fine_cfg.k_rays,
                        strict_nodata=radial_cfg.strict_nodata,
                    ),
                    clip_bbox=fine_cfg.bbox,
                )
                fine_path = out_path.replace(".tif", "_fine.tif")
                write_geotiff(fine_path, dem_data.profile, fine_values)
                outputs.append(fine_path)

            task.setProgress(100)
            return {"outputs": outputs, "summary": "1 WTG elaborata: 1 successo, 0 errori"}

        multi_ctx = run_ctx["multi"]
        vector_layer = QgsProject.instance().mapLayer(multi_ctx["vector_layer_id"])
        if vector_layer is None:
            raise ValueError("Layer WTG non disponibile")
        items = vector_features_to_items(
            vector_layer,
            multi_ctx["h_field"],
            multi_ctx["id_field"],
            run_ctx["dem_layer_crs"],
        )

        res = run_batch(
            dem_data=dem_data,
            items=items,
            observer_height=run_ctx["observer_height"],
            radial_cfg=radial_cfg,
            output_dir=multi_ctx["output_dir"],
            log_cb=lambda m: None,
            progress_cb=lambda p: task.setProgress(p * 100.0),
            csv_path=multi_ctx["csv_path"],
        )
        summary = f"WTG elaborate={len(items)}, successi={res.success}, errori={res.failed}"
        return {"outputs": res.outputs, "summary": summary, "errors": res.errors}

    def _on_done(self, result):
        d = self.dialog
        d.run_btn.setEnabled(True)
        d.set_progress(100)
        d.log(result.get("summary", "Completato"))
        for err in result.get("errors", []):
            d.log(f"Errore: {err}")
        if d.add_to_project_check.isChecked():
            for path in result.get("outputs", []):
                self.iface.addRasterLayer(path, os.path.basename(path))

    def _on_fail(self, exc):
        d = self.dialog
        d.run_btn.setEnabled(True)
        d.log(f"Errore: {exc}")
        QMessageBox.critical(self.iface.mainWindow(), "WTG Visible Height", str(exc))
