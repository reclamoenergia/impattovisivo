# Wind Visible Height GUI (Windows Desktop)

Applicazione desktop **Tkinter** (GUI, non web app e non CLI) per calcolare, dato un DEM GeoTIFF e la posizione XY di una turbina, i **metri di aerogeneratore visibili** per ogni cella (`0..H`) considerando l'orografia.

## Deliverables
1. `wind_visible_height_gui.py`
2. `requirements.txt`
3. `wind_visible_height.spec`
4. `build_fast.bat` (consigliato, one-folder)
5. `build_onefile.bat` (opzionale, più fragile)
6. `README.md`

## Requisiti
- **Windows**
- **Python 3.10 o 3.11 consigliati**
- DEM con **CRS metrico proiettato** (UTM o simili)

> Nota: con Python 3.13 sono frequenti incompatibilità nella catena `numba/llvmlite + pyinstaller`, per via della maturità non uniforme dei wheel binari e dell'integrazione del JIT nel bundle.

Installazione dipendenze:
```bat
python -m pip install -r requirements.txt
```

## Avvio in sviluppo
```bat
python wind_visible_height_gui.py
```

## Parametri GUI
- Selezione DEM (`GeoTIFF`)
- X, Y turbina (float)
- H turbina (default `200.0`)
- Altezza osservatore (default `1.6`)
- `strict nodata` (default ON)
- `max_distance_m` (default `15000`, `0=illimitato`)
- `sample_step_m` (default `25`, minimo `1 pixel`)
- `n_workers` (default = CPU count)
- Pulsante **Calcola**
- Progress bar + log con timestamp

## Algoritmo
Per ogni cella osservatore:
- `z_obs = dem[r,c] + observer_height`
- turbina: `z_base` dal pixel nearest in cui cade `(X,Y)`, `z_top = z_base + H`
- campionamento profilo osservatore→turbina a passo metrico `sample_step_m` (nearest)
- `alpha_i = (z_i - z_obs)/d_i`, `max_alpha = max(alpha_i)`
- `beta_base = (z_base - z_obs)/D`
- `beta_top  = (z_top  - z_obs)/D`
- regole:
  - `max_alpha <= beta_base` -> `visible = H`
  - `max_alpha >= beta_top` -> `visible = 0`
  - altrimenti
    - `h_block = (z_obs + max_alpha*D) - z_base`
    - `visible = H - h_block`
- clamp finale `[0,H]`

Output:
- GeoTIFF `float32`
- `nodata=-9999`
- `compress=LZW`
- stesso `CRS/transform/shape` del DEM

## Ottimizzazioni implementate
1. **Filtro distanza**: oltre `max_distance_m` il valore è `0`.
2. **Stepping metrico** (`sample_step_m`) invece di attraversare tutti i pixel intermedi.
3. **Parallelizzazione process-based** (`ProcessPoolExecutor`) a blocchi di righe.
4. **Numba JIT** (`@njit(cache=True, fastmath=True)`) sul loop core, con fallback Python se non disponibile.

## Build EXE (consigliata)
```bat
build_fast.bat
```
Esegue:
```bat
python -m pip install -r requirements.txt
pyinstaller --noconfirm --clean wind_visible_height.spec
```

Output consigliato: `dist\wind_visible_height\wind_visible_height.exe` (one-folder, più robusto).

## Build onefile (opzionale)
```bat
build_onefile.bat
```
Esegue:
```bat
pyinstaller --noconfirm --clean --onefile wind_visible_height.spec
```

## Packaging notes (GDAL/PROJ + Numba)
- Lo `.spec` include hidden imports di `rasterio`, `numba`, `llvmlite`.
- Include librerie dinamiche per `rasterio` e `llvmlite`.
- All'avvio l'app imposta `GDAL_DATA` e `PROJ_LIB` cercando directory nel bundle (`sys._MEIPASS` / cartella exe) **prima di importare rasterio**.

## Troubleshooting
1. **"CRS geografico non supportato"**
   - Riproietta il DEM in CRS metrico (es. UTM) e riprova.
2. **Calcolo troppo lento**
   - Riduci `max_distance_m` (parametro più impattante).
   - Aumenta `sample_step_m` (es. 30–50 m).
   - Imposta `n_workers` vicino al numero di core fisici/logici.
3. **Output vuoto/quasi zero**
   - Verifica coordinate XY turbina nel CRS corretto del DEM.
   - Verifica che la cella turbina non sia `nodata`.
4. **Errore runtime GDAL/PROJ nell'exe**
   - Preferisci build `one-folder` (`build_fast.bat`).
   - Verifica che nella cartella `dist\wind_visible_height\` siano presenti dati PROJ/GDAL.
5. **Numba non usato**
   - Controlla log GUI: deve indicare `Numba disponibile: True`.
   - Reinstalla dipendenze e ricompila con Python 3.10/3.11.
