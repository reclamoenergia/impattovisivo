import math
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import numpy as np
import rasterio
from rasterio.transform import rowcol, xy

try:
    from numba import njit  # type: ignore

    NUMBA_AVAILABLE = True
except Exception:
    NUMBA_AVAILABLE = False

    def njit(*args, **kwargs):
        def decorator(func):
            return func

        return decorator


OUTPUT_NODATA = -9999.0


@njit(cache=True)
def _clamp_numba(value: float, min_v: float, max_v: float) -> float:
    if value < min_v:
        return min_v
    if value > max_v:
        return max_v
    return value


def bresenham_line(r0: int, c0: int, r1: int, c1: int):
    """Yield integer grid cells on a line from start to end (inclusive)."""
    dr = abs(r1 - r0)
    dc = abs(c1 - c0)
    sr = 1 if r0 < r1 else -1
    sc = 1 if c0 < c1 else -1

    r, c = r0, c0
    if dc > dr:
        err = dc // 2
        while c != c1:
            yield r, c
            err -= dr
            if err < 0:
                r += sr
                err += dc
            c += sc
        yield r1, c1
    else:
        err = dr // 2
        while r != r1:
            yield r, c
            err -= dc
            if err < 0:
                c += sc
                err += dr
            r += sr
        yield r1, c1


def is_nodata(value: float, dem_nodata):
    if np.isnan(value):
        return True
    if dem_nodata is None:
        return False
    return bool(np.isclose(value, dem_nodata))


def compute_visible_heights(
    dem: np.ndarray,
    transform,
    dem_nodata,
    turbine_x: float,
    turbine_y: float,
    turbine_height: float,
    observer_height: float,
    strict_nodata: bool,
    progress_callback=None,
    log_callback=None,
):
    rows, cols = dem.shape
    out = np.full((rows, cols), OUTPUT_NODATA, dtype=np.float32)

    rt, ct = rowcol(transform, turbine_x, turbine_y, op=round)
    rt = int(rt)
    ct = int(ct)

    if rt < 0 or rt >= rows or ct < 0 or ct >= cols:
        raise ValueError("Le coordinate della turbina sono fuori dal DEM.")

    z_base = float(dem[rt, ct])
    if is_nodata(z_base, dem_nodata):
        raise ValueError("La cella della turbina è nodata nel DEM.")

    z_top = z_base + turbine_height
    x_t, y_t = xy(transform, rt, ct, offset="center")

    start_t = time.time()
    progress_every = max(1, rows // 200)

    for r in range(rows):
        for c in range(cols):
            z_cell = float(dem[r, c])
            if is_nodata(z_cell, dem_nodata):
                out[r, c] = OUTPUT_NODATA
                continue

            z_obs = z_cell + observer_height

            x_o, y_o = xy(transform, r, c, offset="center")
            dx = x_t - x_o
            dy = y_t - y_o
            D = math.hypot(dx, dy)

            # Observer in turbine cell: full visible by definition.
            if D == 0.0:
                out[r, c] = np.float32(turbine_height)
                continue

            max_alpha = -math.inf
            has_valid_samples = False
            blocked_by_strict_nodata = False

            line_cells = list(bresenham_line(r, c, rt, ct))
            if len(line_cells) > 2:
                for ir, ic in line_cells[1:-1]:
                    z_i = float(dem[ir, ic])
                    if is_nodata(z_i, dem_nodata):
                        if strict_nodata:
                            blocked_by_strict_nodata = True
                            break
                        continue

                    x_i, y_i = xy(transform, ir, ic, offset="center")
                    d_i = math.hypot(x_i - x_o, y_i - y_o)
                    if d_i <= 0.0:
                        continue

                    alpha_i = (z_i - z_obs) / d_i
                    if alpha_i > max_alpha:
                        max_alpha = alpha_i
                    has_valid_samples = True

            if blocked_by_strict_nodata:
                out[r, c] = OUTPUT_NODATA
                continue

            if not has_valid_samples:
                max_alpha = -math.inf

            beta_base = (z_base - z_obs) / D
            beta_top = (z_top - z_obs) / D

            if max_alpha <= beta_base:
                visible = turbine_height
            elif max_alpha >= beta_top:
                visible = 0.0
            else:
                h_block = (z_obs + max_alpha * D) - z_base
                visible = turbine_height - h_block

            if NUMBA_AVAILABLE:
                visible = _clamp_numba(visible, 0.0, turbine_height)
            else:
                visible = max(0.0, min(turbine_height, visible))
            out[r, c] = np.float32(visible)

        if progress_callback and ((r + 1) % progress_every == 0 or (r + 1) == rows):
            progress_callback((r + 1) / rows)

    if log_callback:
        elapsed = time.time() - start_t
        log_callback(f"Calcolo completato in {elapsed:.2f} s")

    return out


class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Wind Turbine Visible Height")
        self.root.geometry("800x520")

        self.worker_thread = None
        self.ui_queue = queue.Queue()

        self.dem_path_var = tk.StringVar()
        self.x_var = tk.StringVar()
        self.y_var = tk.StringVar()
        self.h_var = tk.StringVar(value="200")
        self.obs_var = tk.StringVar(value="1.6")
        self.strict_nodata_var = tk.BooleanVar(value=True)
        self.output_path_var = tk.StringVar()

        self._build_ui()
        self.root.after(100, self._poll_ui_queue)

    def _build_ui(self):
        frm = ttk.Frame(self.root, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)

        row = 0
        ttk.Label(frm, text="DEM").grid(row=row, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.dem_path_var, width=70).grid(row=row, column=1, sticky="ew", padx=6)
        ttk.Button(frm, text="Sfoglia…", command=self.select_dem).grid(row=row, column=2)

        row += 1
        ttk.Label(frm, text="X turbina").grid(row=row, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(frm, textvariable=self.x_var).grid(row=row, column=1, sticky="ew", padx=6, pady=(8, 0))

        row += 1
        ttk.Label(frm, text="Y turbina").grid(row=row, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(frm, textvariable=self.y_var).grid(row=row, column=1, sticky="ew", padx=6, pady=(8, 0))

        row += 1
        ttk.Label(frm, text="Altezza turbina H (m)").grid(row=row, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(frm, textvariable=self.h_var).grid(row=row, column=1, sticky="ew", padx=6, pady=(8, 0))

        row += 1
        ttk.Label(frm, text="Altezza osservatore (m)").grid(row=row, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(frm, textvariable=self.obs_var).grid(row=row, column=1, sticky="ew", padx=6, pady=(8, 0))

        row += 1
        ttk.Checkbutton(frm, text="Strict nodata", variable=self.strict_nodata_var).grid(
            row=row, column=1, sticky="w", pady=(10, 0)
        )

        row += 1
        ttk.Label(frm, text="Output").grid(row=row, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(frm, textvariable=self.output_path_var, width=70).grid(row=row, column=1, sticky="ew", padx=6, pady=(8, 0))
        ttk.Button(frm, text="Salva come…", command=self.select_output).grid(row=row, column=2, pady=(8, 0))

        row += 1
        self.calc_btn = ttk.Button(frm, text="Calcola", command=self.start_calculation)
        self.calc_btn.grid(row=row, column=1, sticky="w", pady=(12, 0))

        row += 1
        self.progress = ttk.Progressbar(frm, orient="horizontal", mode="determinate", maximum=100)
        self.progress.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(12, 0))

        row += 1
        ttk.Label(frm, text="Log").grid(row=row, column=0, sticky="w", pady=(10, 0))
        row += 1
        self.log_text = tk.Text(frm, height=12, wrap="word")
        self.log_text.grid(row=row, column=0, columnspan=3, sticky="nsew", pady=(4, 0))

        frm.columnconfigure(1, weight=1)
        frm.rowconfigure(row, weight=1)

    def log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{ts}] {msg}\n")
        self.log_text.see(tk.END)

    def select_dem(self):
        p = filedialog.askopenfilename(
            title="Seleziona DEM",
            filetypes=[("GeoTIFF", "*.tif *.tiff"), ("All files", "*.*")],
        )
        if p:
            self.dem_path_var.set(p)

    def select_output(self):
        p = filedialog.asksaveasfilename(
            title="Salva output GeoTIFF",
            defaultextension=".tif",
            filetypes=[("GeoTIFF", "*.tif *.tiff"), ("All files", "*.*")],
        )
        if p:
            self.output_path_var.set(p)

    def start_calculation(self):
        if self.worker_thread and self.worker_thread.is_alive():
            messagebox.showwarning("In corso", "Un calcolo è già in esecuzione.")
            return

        dem_path = self.dem_path_var.get().strip()
        out_path = self.output_path_var.get().strip()

        if not dem_path:
            messagebox.showerror("Errore", "Seleziona un file DEM.")
            return
        if not out_path:
            messagebox.showerror("Errore", "Seleziona un file di output.")
            return

        try:
            x = float(self.x_var.get())
            y = float(self.y_var.get())
            h = float(self.h_var.get())
            obs_h = float(self.obs_var.get())
        except ValueError:
            messagebox.showerror("Errore", "X, Y, H e altezza osservatore devono essere numeri validi.")
            return

        if h <= 0:
            messagebox.showerror("Errore", "L'altezza turbina H deve essere > 0.")
            return

        self.progress["value"] = 0
        self.calc_btn.config(state=tk.DISABLED)
        self.log("Avvio calcolo...")

        self.worker_thread = threading.Thread(
            target=self._worker,
            args=(dem_path, out_path, x, y, h, obs_h, self.strict_nodata_var.get()),
            daemon=True,
        )
        self.worker_thread.start()

    def _worker(self, dem_path, out_path, x, y, h, obs_h, strict_nodata):
        try:
            t0 = time.time()
            self.ui_queue.put(("log", f"Apertura DEM: {dem_path}"))
            with rasterio.open(dem_path) as src:
                dem = src.read(1).astype(np.float64, copy=False)
                transform = src.transform
                dem_nodata = src.nodata
                profile = src.profile.copy()

            self.ui_queue.put(("log", f"DEM caricato ({dem.shape[0]}x{dem.shape[1]})."))
            if NUMBA_AVAILABLE:
                self.ui_queue.put(("log", "Numba disponibile: clamp numerico JIT attivo."))
            else:
                self.ui_queue.put(("log", "Numba non disponibile: uso fallback puro Python."))

            result = compute_visible_heights(
                dem=dem,
                transform=transform,
                dem_nodata=dem_nodata,
                turbine_x=x,
                turbine_y=y,
                turbine_height=h,
                observer_height=obs_h,
                strict_nodata=strict_nodata,
                progress_callback=lambda p: self.ui_queue.put(("progress", p)),
                log_callback=lambda m: self.ui_queue.put(("log", m)),
            )

            profile.update(dtype=rasterio.float32, nodata=OUTPUT_NODATA, count=1, compress="LZW")
            self.ui_queue.put(("log", f"Scrittura output: {out_path}"))
            with rasterio.open(out_path, "w", **profile) as dst:
                dst.write(result, 1)

            total = time.time() - t0
            self.ui_queue.put(("done", f"Completato in {total:.2f} s"))
        except Exception as e:
            self.ui_queue.put(("error", str(e)))

    def _poll_ui_queue(self):
        try:
            while True:
                kind, payload = self.ui_queue.get_nowait()
                if kind == "log":
                    self.log(payload)
                elif kind == "progress":
                    self.progress["value"] = float(payload) * 100.0
                elif kind == "done":
                    self.progress["value"] = 100.0
                    self.log(payload)
                    self.calc_btn.config(state=tk.NORMAL)
                    messagebox.showinfo("OK", "Calcolo terminato con successo.")
                elif kind == "error":
                    self.log(f"ERRORE: {payload}")
                    self.calc_btn.config(state=tk.NORMAL)
                    messagebox.showerror("Errore", payload)
        except queue.Empty:
            pass
        finally:
            self.root.after(100, self._poll_ui_queue)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
