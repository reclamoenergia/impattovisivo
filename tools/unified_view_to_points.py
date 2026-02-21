#!/usr/bin/env python3
"""Sample Unified View per-turbine rasters on a regular grid and export points."""

from __future__ import annotations

import argparse
import math
import sys
import threading
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import numpy as np
import rasterio
from rasterio.crs import CRS
from rasterio.warp import transform

from unified_view.azimuth import azimuth_deg, minimal_covering_arc
from unified_view.io import Turbine, load_turbines, reproject_turbines, validate_rasters

try:
    import fiona
    from fiona.crs import CRS as FionaCRS
except ImportError:  # pragma: no cover
    fiona = None
    FionaCRS = None


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rasters", nargs="+")
    parser.add_argument("--turbines")
    parser.add_argument("--spacing", type=float, default=25.0, dest="spacing_m")
    parser.add_argument("--visibility-threshold", type=float, default=0.0)
    parser.add_argument(
        "--extent-mode", choices=["from_rasters", "custom_bbox"], default="from_rasters"
    )
    parser.add_argument("--extent-op", choices=["union", "intersection"], default="union")
    parser.add_argument("--bbox", nargs=4, type=float, metavar=("xmin", "ymin", "xmax", "ymax"))
    parser.add_argument("--mask-mode", choices=["valid_pixels", "any_valid"], default="valid_pixels")
    parser.add_argument("--out", dest="output_path")
    parser.add_argument("--output-format", choices=["gpkg", "shp"], default="gpkg")
    parser.add_argument("--layer-name", default="unified_view_points")
    parser.add_argument("--crs-epsg", type=int)
    parser.add_argument("--chunk-size", type=int, default=5000)
    parser.add_argument("--no-nulls", action="store_true", help="Use -9999 instead of NULL for azimuth fields")
    parser.add_argument("--gui", action="store_true", help="Open graphical interface")
    return parser.parse_args(argv)


def get_extent(datasets: list[rasterio.io.DatasetReader], mode: str, op: str, bbox: list[float] | None):
    if mode == "custom_bbox":
        if not bbox:
            raise ValueError("--bbox is required when extent-mode=custom_bbox")
        return tuple(bbox)
    bounds = [ds.bounds for ds in datasets]
    if op == "intersection":
        xmin = max(b.left for b in bounds)
        ymin = max(b.bottom for b in bounds)
        xmax = min(b.right for b in bounds)
        ymax = min(b.top for b in bounds)
    else:
        xmin = min(b.left for b in bounds)
        ymin = min(b.bottom for b in bounds)
        xmax = max(b.right for b in bounds)
        ymax = max(b.top for b in bounds)
    if xmin >= xmax or ymin >= ymax:
        raise ValueError("Invalid extent: empty area")
    return xmin, ymin, xmax, ymax


def build_field_names(turbines: list[Turbine], output_format: str) -> tuple[list[str], dict[str, str]]:
    mapping = {}
    fields = []
    for idx, turbine in enumerate(turbines, start=1):
        if output_format == "shp":
            field = f"h_{idx:03d}"
        else:
            tid = "".join(ch if ch.isalnum() else "_" for ch in turbine.turbine_id)
            field = f"h_{tid}"[:30]
            if field in fields:
                field = f"h_{idx:03d}"
        fields.append(field)
        mapping[field] = turbine.turbine_id
    return fields, mapping


def iter_grid_points(xmin: float, ymin: float, xmax: float, ymax: float, spacing_m: float):
    xs = np.arange(xmin, xmax + 1e-9, spacing_m)
    ys = np.arange(ymin, ymax + 1e-9, spacing_m)
    for y in ys:
        for x in xs:
            yield float(x), float(y)


def _fiona_driver(fmt: str) -> str:
    return "GPKG" if fmt == "gpkg" else "ESRI Shapefile"


def run(args: argparse.Namespace, log: callable = print) -> None:
    if fiona is None:
        raise RuntimeError("fiona is required to write Shapefile/GeoPackage outputs")

    if not args.rasters:
        raise ValueError("--rasters is required")
    if not args.turbines:
        raise ValueError("--turbines is required")
    if not args.output_path:
        raise ValueError("--out is required")

    datasets = validate_rasters(args.rasters)
    raster_crs = datasets[0].crs
    working_crs = raster_crs

    turbines, turbines_crs = load_turbines(args.turbines)
    if len(turbines) != len(datasets):
        raise ValueError(
            f"Number of turbines ({len(turbines)}) must equal number of rasters ({len(datasets)})"
        )

    if turbines_crs is not None and turbines_crs != working_crs:
        turbines = reproject_turbines(turbines, turbines_crs, working_crs)

    out_crs = CRS.from_epsg(args.crs_epsg) if args.crs_epsg else working_crs

    xmin, ymin, xmax, ymax = get_extent(datasets, args.extent_mode, args.extent_op, args.bbox)
    total_points = (math.floor((xmax - xmin) / args.spacing_m) + 1) * (
        math.floor((ymax - ymin) / args.spacing_m) + 1
    )

    log(f"[INFO] Processing extent {xmin:.2f},{ymin:.2f},{xmax:.2f},{ymax:.2f} | grid points ~{total_points}")

    h_fields, h_field_map = build_field_names(turbines, args.output_format)

    schema = {
        "geometry": "Point",
        "properties": {
            "pt_id": "int",
            "x": "float",
            "y": "float",
            "n_vis": "int",
            "az_ctr": "float",
            "az_min": "float",
            "az_max": "float",
            "fov_az": "float",
            **{field: "float" for field in h_fields},
        },
    }

    output = Path(args.output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    dropped_nodata = 0
    written = 0
    point_id = 1

    with fiona.open(
        output,
        mode="w",
        driver=_fiona_driver(args.output_format),
        schema=schema,
        crs=FionaCRS.from_wkt(out_crs.to_wkt()),
        layer=args.layer_name if args.output_format == "gpkg" else None,
    ) as sink:
        points_iter = iter_grid_points(xmin, ymin, xmax, ymax, args.spacing_m)
        while True:
            batch = list()
            for _ in range(args.chunk_size):
                try:
                    batch.append(next(points_iter))
                except StopIteration:
                    break
            if not batch:
                break

            sampled = [list(ds.sample(batch, indexes=1, masked=True)) for ds in datasets]

            for p_idx, (x, y) in enumerate(batch):
                vals = []
                valid_flags = []
                for ridx in range(len(datasets)):
                    scalar = sampled[ridx][p_idx]
                    if np.ma.is_masked(scalar) and bool(np.ma.getmaskarray(scalar).any()):
                        valid_flags.append(False)
                        vals.append(0.0)
                    else:
                        valid_flags.append(True)
                        vals.append(float(np.asarray(scalar).item()))

                if args.mask_mode == "valid_pixels" and not all(valid_flags):
                    dropped_nodata += 1
                    continue
                if args.mask_mode == "any_valid" and not any(valid_flags):
                    dropped_nodata += 1
                    continue

                visible_idx = [i for i, v in enumerate(vals) if v > args.visibility_threshold]
                n_vis = len(visible_idx)
                az_null = -9999.0 if args.no_nulls else None

                if n_vis == 0:
                    az_ctr = az_min = az_max = fov_az = az_null
                else:
                    az_values = [
                        azimuth_deg(x, y, turbines[i].x, turbines[i].y)
                        for i in visible_idx
                    ]
                    az_min, az_max, fov_az = minimal_covering_arc(az_values)
                    cx = float(np.mean([turbines[i].x for i in visible_idx]))
                    cy = float(np.mean([turbines[i].y for i in visible_idx]))
                    az_ctr = azimuth_deg(x, y, cx, cy)

                if out_crs != working_crs:
                    tx, ty = transform(working_crs, out_crs, [x], [y])
                    out_x, out_y = tx[0], ty[0]
                else:
                    out_x, out_y = x, y

                props = {
                    "pt_id": point_id,
                    "x": out_x,
                    "y": out_y,
                    "n_vis": n_vis,
                    "az_ctr": az_ctr,
                    "az_min": az_min,
                    "az_max": az_max,
                    "fov_az": fov_az,
                }
                for i, field in enumerate(h_fields):
                    props[field] = vals[i] if i in visible_idx else 0.0

                sink.write(
                    {
                        "geometry": {"type": "Point", "coordinates": (out_x, out_y)},
                        "properties": props,
                    }
                )
                point_id += 1
                written += 1

            progress = min(100.0, (written + dropped_nodata) * 100.0 / max(total_points, 1))
            log(f"[INFO] progress: {progress:6.2f}% | written={written} dropped={dropped_nodata}")

    mapping_path = output.with_suffix(output.suffix + ".field_map.csv")
    with mapping_path.open("w", encoding="utf-8", newline="") as fp:
        fp.write("field_name;turbine_id\n")
        for field, tid in h_field_map.items():
            fp.write(f"{field};{tid}\n")

    log("[INFO] Completed")
    log(f"[INFO] points_written={written}")
    log(f"[INFO] points_dropped_nodata={dropped_nodata}")
    log(f"[INFO] output_path={output}")
    log(
        "[INFO] params="
        f"spacing_m={args.spacing_m}, threshold={args.visibility_threshold}, "
        f"mask_mode={args.mask_mode}, extent_mode={args.extent_mode}, output_format={args.output_format}"
    )

    for ds in datasets:
        ds.close()


class UnifiedViewPointsGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Unified View to Points")
        self.root.geometry("1020x760")

        self.rasters_var = tk.StringVar()
        self.turbines_var = tk.StringVar()
        self.out_var = tk.StringVar()
        self.spacing_var = tk.StringVar(value="25")
        self.threshold_var = tk.StringVar(value="0")
        self.extent_mode_var = tk.StringVar(value="from_rasters")
        self.extent_op_var = tk.StringVar(value="union")
        self.bbox_var = tk.StringVar()
        self.mask_mode_var = tk.StringVar(value="valid_pixels")
        self.output_format_var = tk.StringVar(value="gpkg")
        self.layer_name_var = tk.StringVar(value="unified_view_points")
        self.crs_epsg_var = tk.StringVar()
        self.chunk_size_var = tk.StringVar(value="5000")
        self.no_nulls_var = tk.BooleanVar(value=False)

        self.is_running = False
        self._build_ui()

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)

        form = ttk.LabelFrame(outer, text="Input / Output")
        form.pack(fill="x", pady=(0, 10))

        ttk.Label(form, text="Raster Unified View (separati da ';')").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        ttk.Entry(form, textvariable=self.rasters_var).grid(row=0, column=1, sticky="ew", padx=8, pady=6)
        ttk.Button(form, text="Seleziona", command=self._pick_rasters).grid(row=0, column=2, padx=8, pady=6)

        ttk.Label(form, text="CSV turbine").grid(row=1, column=0, sticky="w", padx=8, pady=6)
        ttk.Entry(form, textvariable=self.turbines_var).grid(row=1, column=1, sticky="ew", padx=8, pady=6)
        ttk.Button(form, text="Seleziona", command=self._pick_turbines).grid(row=1, column=2, padx=8, pady=6)

        ttk.Label(form, text="Output file").grid(row=2, column=0, sticky="w", padx=8, pady=6)
        ttk.Entry(form, textvariable=self.out_var).grid(row=2, column=1, sticky="ew", padx=8, pady=6)
        ttk.Button(form, text="Salva come", command=self._pick_out).grid(row=2, column=2, padx=8, pady=6)
        form.columnconfigure(1, weight=1)

        params = ttk.LabelFrame(outer, text="Parametri")
        params.pack(fill="x", pady=(0, 10))
        items = [
            ("Spacing (m)", self.spacing_var),
            ("Visibility threshold", self.threshold_var),
            ("Extent mode (from_rasters/custom_bbox)", self.extent_mode_var),
            ("Extent op (union/intersection)", self.extent_op_var),
            ("BBox xmin ymin xmax ymax", self.bbox_var),
            ("Mask mode (valid_pixels/any_valid)", self.mask_mode_var),
            ("Output format (gpkg/shp)", self.output_format_var),
            ("Layer name", self.layer_name_var),
            ("CRS EPSG (opzionale)", self.crs_epsg_var),
            ("Chunk size", self.chunk_size_var),
        ]
        for i, (label, var) in enumerate(items):
            ttk.Label(params, text=label).grid(row=i, column=0, sticky="w", padx=8, pady=4)
            ttk.Entry(params, textvariable=var).grid(row=i, column=1, sticky="ew", padx=8, pady=4)
        ttk.Checkbutton(params, text="Usa -9999 invece di NULL per i campi azimut", variable=self.no_nulls_var).grid(
            row=len(items), column=0, columnspan=2, sticky="w", padx=8, pady=6
        )
        params.columnconfigure(1, weight=1)

        algo = ttk.LabelFrame(outer, text="Spiegazione algoritmo e input")
        algo.pack(fill="both", expand=True, pady=(0, 10))
        expl = tk.Text(algo, height=14, wrap="word")
        expl.pack(fill="both", expand=True, padx=8, pady=8)
        expl.insert(
            "1.0",
            """Questo tool legge N raster Unified View (uno per turbina) e produce una griglia di punti regolari.\n\n"
            "Input richiesti:\n"
            "- Rasters: elenco file .tif Unified View, stesso CRS e griglia.\n"
            "- Turbines: CSV/GeoJSON con turbine (deve avere lo stesso numero di record dei raster).\n"
            "- Output: file .gpkg o .shp da creare.\n\n"
            "Parametri principali:\n"
            "- Spacing: passo della griglia punti in metri.\n"
            "- Visibility threshold: una turbina è contata visibile se h_i > soglia.\n"
            "- Extent mode/op: area di calcolo da raster (union/intersection) o bbox manuale.\n"
            "- Mask mode: valid_pixels richiede tutti i raster validi; any_valid richiede almeno un raster valido.\n"
            "- CRS EPSG: opzionale, riproietta i punti in output.\n\n"
            "Per ogni punto la procedura:\n"
            "1) campiona tutti i raster nel punto;\n"
            "2) calcola n_vis e campi h_* per turbina;\n"
            "3) stima azimut centro, azimut minimo/massimo e campo visivo orizzontale (fov_az);\n"
            "4) scrive feature punto nel layer output.\n"
            """,
        )
        expl.configure(state="disabled")

        actions = ttk.Frame(outer)
        actions.pack(fill="x")
        ttk.Button(actions, text="Esegui", command=self._start).pack(side="left")

        self.log_widget = tk.Text(outer, height=10, wrap="word")
        self.log_widget.pack(fill="both", expand=False, pady=(8, 0))

    def _log(self, message: str) -> None:
        self.log_widget.insert("end", message + "\n")
        self.log_widget.see("end")
        self.root.update_idletasks()

    def _pick_rasters(self) -> None:
        paths = filedialog.askopenfilenames(filetypes=[("GeoTIFF", "*.tif *.tiff"), ("All", "*.*")])
        if paths:
            self.rasters_var.set(";".join(paths))

    def _pick_turbines(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("Vector/CSV", "*.csv *.geojson *.gpkg *.shp"), ("All", "*.*")])
        if path:
            self.turbines_var.set(path)

    def _pick_out(self) -> None:
        path = filedialog.asksaveasfilename(defaultextension=".gpkg", filetypes=[("GeoPackage", "*.gpkg"), ("Shapefile", "*.shp")])
        if path:
            self.out_var.set(path)

    def _start(self) -> None:
        if self.is_running:
            return
        try:
            args = self._collect_args()
        except ValueError as exc:
            messagebox.showerror("Parametri non validi", str(exc))
            return

        self.is_running = True
        self._log("[INFO] Avvio elaborazione...")
        thread = threading.Thread(target=self._run_thread, args=(args,), daemon=True)
        thread.start()

    def _collect_args(self) -> argparse.Namespace:
        rasters = [p.strip() for p in self.rasters_var.get().split(";") if p.strip()]
        if not rasters:
            raise ValueError("Seleziona almeno un raster")
        if not self.turbines_var.get().strip():
            raise ValueError("Seleziona il file turbine")
        if not self.out_var.get().strip():
            raise ValueError("Seleziona il file output")

        bbox = None
        bbox_text = self.bbox_var.get().strip()
        if bbox_text:
            parts = bbox_text.replace(",", " ").split()
            if len(parts) != 4:
                raise ValueError("La bbox deve contenere 4 valori: xmin ymin xmax ymax")
            bbox = [float(v) for v in parts]

        crs_epsg = self.crs_epsg_var.get().strip()
        return argparse.Namespace(
            rasters=rasters,
            turbines=self.turbines_var.get().strip(),
            spacing_m=float(self.spacing_var.get()),
            visibility_threshold=float(self.threshold_var.get()),
            extent_mode=self.extent_mode_var.get().strip(),
            extent_op=self.extent_op_var.get().strip(),
            bbox=bbox,
            mask_mode=self.mask_mode_var.get().strip(),
            output_path=self.out_var.get().strip(),
            output_format=self.output_format_var.get().strip(),
            layer_name=self.layer_name_var.get().strip() or "unified_view_points",
            crs_epsg=int(crs_epsg) if crs_epsg else None,
            chunk_size=int(self.chunk_size_var.get()),
            no_nulls=self.no_nulls_var.get(),
            gui=True,
        )

    def _run_thread(self, args: argparse.Namespace) -> None:
        try:
            run(args, log=lambda msg: self.root.after(0, self._log, msg))
            self.root.after(0, messagebox.showinfo, "Completato", f"Output creato: {args.output_path}")
        except Exception as exc:
            self.root.after(0, messagebox.showerror, "Errore", str(exc))
        finally:
            self.is_running = False


def launch_gui() -> None:
    root = tk.Tk()
    UnifiedViewPointsGUI(root)
    root.mainloop()


def main() -> None:
    args = parse_args()
    if args.gui or len(sys.argv) == 1:
        launch_gui()
        return
    run(args)


if __name__ == "__main__":
    main()
