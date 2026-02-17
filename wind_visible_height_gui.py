import math
import os
import queue
import sys
import threading
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from multiprocessing import cpu_count
from tkinter import filedialog, messagebox
import tkinter as tk
from tkinter import ttk

import numpy as np


OUTPUT_NODATA = -9999.0
_WORKER_STATE = {}


def _configure_gdal_env_for_bundle() -> None:
    """Set GDAL/PROJ environment variables for PyInstaller bundles before rasterio import."""
    candidates = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        exe_dir = os.path.dirname(sys.executable)
        candidates.extend([meipass, exe_dir])

    for base in candidates:
        if not base:
            continue
        proj_candidates = [
            os.path.join(base, "proj_data"),
            os.path.join(base, "proj"),
            os.path.join(base, "share", "proj"),
        ]
        gdal_candidates = [
            os.path.join(base, "gdal_data"),
            os.path.join(base, "gdal"),
            os.path.join(base, "share", "gdal"),
        ]

        for p in proj_candidates:
            if os.path.exists(os.path.join(p, "proj.db")):
                os.environ.setdefault("PROJ_LIB", p)
                break

        for p in gdal_candidates:
            if os.path.exists(p):
                os.environ.setdefault("GDAL_DATA", p)
                break


_configure_gdal_env_for_bundle()

import rasterio  # noqa: E402
from rasterio.transform import rowcol  # noqa: E402

try:
    from numba import njit

    NUMBA_AVAILABLE = True
except Exception:
    NUMBA_AVAILABLE = False

    def njit(*args, **kwargs):
        def _wrap(func):
            return func

        return _wrap


@njit(cache=True, fastmath=True)
def _compute_chunk_numba(
    dem,
    row_start,
    row_end,
    x0,
    y0,
    px_w,
    px_h,
    rt,
    ct,
    z_base,
    z_top,
    turbine_h,
    observer_h,
    strict_nodata,
    has_nodata,
    dem_nodata,
    max_distance,
    sample_step,
    out_nodata,
):
    rows, cols = dem.shape
    out = np.full((row_end - row_start, cols), out_nodata, dtype=np.float32)

    x_t = x0 + (ct + 0.5) * px_w
    y_t = y0 + (rt + 0.5) * px_h

    x_center0 = x0 + 0.5 * px_w
    y_center0 = y0 + 0.5 * px_h

    for rr in range(row_start, row_end):
        local_r = rr - row_start
        y_obs = y0 + (rr + 0.5) * px_h
        for c in range(cols):
            z_cell = dem[rr, c]
            nodata_cell = np.isnan(z_cell)
            if not nodata_cell and has_nodata:
                nodata_cell = abs(z_cell - dem_nodata) <= 1e-6
            if nodata_cell:
                out[local_r, c] = out_nodata
                continue

            x_obs = x0 + (c + 0.5) * px_w
            z_obs = z_cell + observer_h

            dx = x_t - x_obs
            dy = y_t - y_obs
            D = math.hypot(dx, dy)

            if D == 0.0:
                out[local_r, c] = turbine_h
                continue

            if max_distance > 0.0 and D > max_distance:
                out[local_r, c] = 0.0
                continue

            max_alpha = -1e30
            has_sample = False
            blocked = False

            n_steps = int(D / sample_step)
            for s in range(1, n_steps + 1):
                t = s * sample_step
                if t >= D:
                    break

                ratio = t / D
                x_i = x_obs + dx * ratio
                y_i = y_obs + dy * ratio

                c_i = int(round((x_i - x_center0) / px_w))
                r_i = int(round((y_i - y_center0) / px_h))

                if r_i < 0 or r_i >= rows or c_i < 0 or c_i >= cols:
                    continue

                z_i = dem[r_i, c_i]
                nodata_i = np.isnan(z_i)
                if not nodata_i and has_nodata:
                    nodata_i = abs(z_i - dem_nodata) <= 1e-6

                if nodata_i:
                    if strict_nodata:
                        blocked = True
                        break
                    continue

                alpha_i = (z_i - z_obs) / t
                if alpha_i > max_alpha:
                    max_alpha = alpha_i
                has_sample = True

            if blocked:
                out[local_r, c] = out_nodata
                continue

            if not has_sample:
                max_alpha = -1e30

            beta_base = (z_base - z_obs) / D
            beta_top = (z_top - z_obs) / D

            if max_alpha <= beta_base:
                visible = turbine_h
            elif max_alpha >= beta_top:
                visible = 0.0
            else:
                h_block = (z_obs + max_alpha * D) - z_base
                visible = turbine_h - h_block

            if visible < 0.0:
                visible = 0.0
            elif visible > turbine_h:
                visible = turbine_h

            out[local_r, c] = visible

    return out


def _compute_chunk_python(*args):
    return _compute_chunk_numba.py_func(*args)


def _init_worker(dem_path):
    with rasterio.open(dem_path) as src:
        dem = src.read(1).astype(np.float32, copy=False)
        tr = src.transform
        nodata = src.nodata

    _WORKER_STATE["dem"] = dem
    _WORKER_STATE["x0"] = float(tr.c)
    _WORKER_STATE["y0"] = float(tr.f)
    _WORKER_STATE["px_w"] = float(tr.a)
    _WORKER_STATE["px_h"] = float(tr.e)
    _WORKER_STATE["nodata"] = np.nan if nodata is None else float(nodata)
    _WORKER_STATE["has_nodata"] = nodata is not None


def _worker_compute(payload):
    dem = _WORKER_STATE["dem"]
    compute_fn = _compute_chunk_numba if NUMBA_AVAILABLE else _compute_chunk_python
    arr = compute_fn(
        dem,
        payload["row_start"],
        payload["row_end"],
        _WORKER_STATE["x0"],
        _WORKER_STATE["y0"],
        _WORKER_STATE["px_w"],
        _WORKER_STATE["px_h"],
        payload["rt"],
        payload["ct"],
        payload["z_base"],
        payload["z_top"],
        payload["turbine_h"],
        payload["observer_h"],
        payload["strict_nodata"],
        _WORKER_STATE["has_nodata"],
        _WORKER_STATE["nodata"],
        payload["max_distance"],
        payload["sample_step"],
        OUTPUT_NODATA,
    )
    return payload["row_start"], payload["row_end"], arr


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Wind Visible Height (Desktop)")
        self.root.geometry("920x640")

        self.ui_queue = queue.Queue()
        self.worker_thread = None

        self.dem_path = tk.StringVar()
        self.out_path = tk.StringVar()
        self.x_turb = tk.StringVar()
        self.y_turb = tk.StringVar()
        self.h_turb = tk.StringVar(value="200.0")
        self.h_obs = tk.StringVar(value="1.6")
        self.strict_nodata = tk.BooleanVar(value=True)
        self.max_distance_m = tk.StringVar(value="15000")
        self.sample_step_m = tk.StringVar(value="25")
        self.n_workers = tk.StringVar(value=str(cpu_count()))

        self._build_ui()
        self.root.after(100, self._poll_queue)

    def _build_ui(self):
        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(1, weight=1)

        r = 0
        ttk.Label(frame, text="DEM GeoTIFF").grid(row=r, column=0, sticky="w")
        ttk.Entry(frame, textvariable=self.dem_path).grid(row=r, column=1, sticky="ew", padx=6)
        ttk.Button(frame, text="Sfoglia…", command=self.pick_dem).grid(row=r, column=2)

        r += 1
        ttk.Label(frame, text="Output GeoTIFF").grid(row=r, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(frame, textvariable=self.out_path).grid(row=r, column=1, sticky="ew", padx=6, pady=(8, 0))
        ttk.Button(frame, text="Salva come…", command=self.pick_out).grid(row=r, column=2, pady=(8, 0))

        fields = [
            ("X turbina", self.x_turb),
            ("Y turbina", self.y_turb),
            ("H turbina (m)", self.h_turb),
            ("Altezza osservatore (m)", self.h_obs),
            ("max_distance_m (0=illimitato)", self.max_distance_m),
            ("sample_step_m", self.sample_step_m),
            ("n_workers", self.n_workers),
        ]
        for label, var in fields:
            r += 1
            ttk.Label(frame, text=label).grid(row=r, column=0, sticky="w", pady=(8, 0))
            ttk.Entry(frame, textvariable=var).grid(row=r, column=1, sticky="ew", padx=6, pady=(8, 0))

        r += 1
        ttk.Checkbutton(frame, text="strict nodata", variable=self.strict_nodata).grid(
            row=r, column=1, sticky="w", pady=(8, 0)
        )

        r += 1
        self.btn_run = ttk.Button(frame, text="Calcola", command=self.start)
        self.btn_run.grid(row=r, column=1, sticky="w", pady=(12, 0))

        r += 1
        self.progress = ttk.Progressbar(frame, orient="horizontal", mode="determinate", maximum=100)
        self.progress.grid(row=r, column=0, columnspan=3, sticky="ew", pady=(10, 0))

        r += 1
        self.log = tk.Text(frame, height=14, wrap="word")
        self.log.grid(row=r, column=0, columnspan=3, sticky="nsew", pady=(10, 0))
        frame.rowconfigure(r, weight=1)

    def _log(self, msg: str):
        ts = datetime.now().strftime("%H:%M:%S")
        self.log.insert(tk.END, f"[{ts}] {msg}\n")
        self.log.see(tk.END)

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.ui_queue.get_nowait()
                if kind == "log":
                    self._log(payload)
                elif kind == "progress":
                    self.progress["value"] = payload
                elif kind == "done":
                    self.btn_run.configure(state="normal")
                    messagebox.showinfo("Completato", payload)
                elif kind == "error":
                    self.btn_run.configure(state="normal")
                    messagebox.showerror("Errore", payload)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def pick_dem(self):
        p = filedialog.askopenfilename(filetypes=[("GeoTIFF", "*.tif *.tiff"), ("All", "*.*")])
        if p:
            self.dem_path.set(p)
            if not self.out_path.get().strip():
                stem, _ = os.path.splitext(p)
                self.out_path.set(stem + "_visible_height.tif")

    def pick_out(self):
        p = filedialog.asksaveasfilename(defaultextension=".tif", filetypes=[("GeoTIFF", "*.tif")])
        if p:
            self.out_path.set(p)

    def start(self):
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("Attendi", "Calcolo in corso.")
            return

        self.btn_run.configure(state="disabled")
        self.progress["value"] = 0
        self.log.delete("1.0", tk.END)

        self.worker_thread = threading.Thread(target=self._run_compute, daemon=True)
        self.worker_thread.start()

    def _run_compute(self):
        try:
            dem_path = self.dem_path.get().strip()
            out_path = self.out_path.get().strip()
            if not dem_path or not os.path.exists(dem_path):
                raise ValueError("Seleziona un DEM valido.")
            if not out_path:
                raise ValueError("Seleziona il percorso di output.")

            x_turb = float(self.x_turb.get())
            y_turb = float(self.y_turb.get())
            turbine_h = float(self.h_turb.get())
            observer_h = float(self.h_obs.get())
            max_distance = float(self.max_distance_m.get())
            sample_step = float(self.sample_step_m.get())
            n_workers = int(self.n_workers.get())
            strict_nodata = bool(self.strict_nodata.get())

            if turbine_h <= 0:
                raise ValueError("H turbina deve essere > 0.")
            if sample_step <= 0:
                raise ValueError("sample_step_m deve essere > 0.")
            if n_workers <= 0:
                raise ValueError("n_workers deve essere >= 1.")

            self.ui_queue.put(("log", f"Numba disponibile: {NUMBA_AVAILABLE}"))
            if not NUMBA_AVAILABLE:
                self.ui_queue.put(("log", "ATTENZIONE: fallback Python attivo (più lento)."))

            with rasterio.open(dem_path) as src:
                if src.crs is None:
                    raise ValueError("Il DEM non ha CRS definito.")
                if src.crs.is_geographic:
                    raise ValueError("CRS geografico (gradi) non supportato: usare CRS metrico proiettato.")

                transform = src.transform
                if abs(transform.b) > 1e-9 or abs(transform.d) > 1e-9:
                    raise ValueError("Transform ruotato/skew non supportato in questa versione.")

                pixel_m = min(abs(transform.a), abs(transform.e))
                if sample_step < pixel_m:
                    self.ui_queue.put(("log", f"sample_step_m troppo basso, portato a {pixel_m:.3f} m (1 pixel)."))
                    sample_step = pixel_m

                dem_shape = src.shape
                rt, ct = rowcol(transform, x_turb, y_turb, op=round)
                rt, ct = int(rt), int(ct)
                if rt < 0 or rt >= dem_shape[0] or ct < 0 or ct >= dem_shape[1]:
                    raise ValueError("Coordinate turbina fuori dal DEM.")

                z_base = float(src.read(1, window=((rt, rt + 1), (ct, ct + 1)))[0, 0])
                nodata = src.nodata
                if np.isnan(z_base) or (nodata is not None and math.isclose(z_base, float(nodata), rel_tol=0, abs_tol=1e-6)):
                    raise ValueError("La cella della turbina è nodata.")

                profile = src.profile.copy()

            z_top = z_base + turbine_h
            rows = dem_shape[0]
            cols = dem_shape[1]
            out = np.full((rows, cols), OUTPUT_NODATA, dtype=np.float32)

            chunk = max(64, rows // (n_workers * 4) if n_workers > 0 else rows)
            tasks = []
            for row_start in range(0, rows, chunk):
                row_end = min(rows, row_start + chunk)
                tasks.append(
                    {
                        "row_start": row_start,
                        "row_end": row_end,
                        "rt": rt,
                        "ct": ct,
                        "z_base": z_base,
                        "z_top": z_top,
                        "turbine_h": turbine_h,
                        "observer_h": observer_h,
                        "strict_nodata": strict_nodata,
                        "max_distance": max_distance,
                        "sample_step": sample_step,
                    }
                )

            done_rows = 0
            self.ui_queue.put(("log", f"Avvio calcolo su {rows}x{cols}, workers={n_workers}, chunk={chunk}."))

            with ProcessPoolExecutor(max_workers=n_workers, initializer=_init_worker, initargs=(dem_path,)) as ex:
                future_map = {ex.submit(_worker_compute, t): t for t in tasks}
                for fut in as_completed(future_map):
                    rs, re, arr = fut.result()
                    out[rs:re, :] = arr
                    done_rows += re - rs
                    self.ui_queue.put(("progress", 100.0 * done_rows / rows))

            profile.update(dtype="float32", count=1, nodata=OUTPUT_NODATA, compress="LZW")
            with rasterio.open(out_path, "w", **profile) as dst:
                dst.write(out, 1)

            self.ui_queue.put(("log", f"Output salvato: {out_path}"))
            self.ui_queue.put(("done", "Calcolo completato con successo."))
        except Exception as exc:
            self.ui_queue.put(("error", str(exc)))


if __name__ == "__main__":
    # Necessario su Windows/PyInstaller: evita che i processi figli di multiprocessing
    # rieseguano il bootstrap GUI aprendo nuove finestre.
    freeze_support()
    root = tk.Tk()
    app = App(root)
    root.mainloop()
