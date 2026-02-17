# Wind Turbine Visible Height GUI (Desktop)

Tool desktop **Tkinter** (non web, non CLI) per calcolare, da un DEM GeoTIFF, i **metri verticali visibili** di un aerogeneratore per ogni pixel osservatore.

## Deliverable
- `wind_turbine_visible_height_gui.py`
- `requirements.txt`
- `build.bat`

## Requisiti
- Python 3.10+
- Windows (target build `.exe`)

Dipendenze principali:
- `rasterio`
- `numpy`
- `numba` (opzionale, fallback automatico se assente)
- `tqdm` (opzionale, non necessaria alla GUI ma inclusa)
- `pyinstaller` (per build EXE)

## Uso
1. Avvia:
   ```bash
   python wind_turbine_visible_height_gui.py
   ```
2. Seleziona il file DEM GeoTIFF (`Sfoglia…`).
3. Inserisci coordinate turbina `X`, `Y` (stesso CRS del DEM).
4. Imposta parametri:
   - Altezza turbina `H` (default 200 m)
   - Altezza osservatore (default 1.6 m)
   - `Strict nodata` (default ON)
5. Seleziona output (`Salva come…`).
6. Clicca `Calcola`.

Output:
- GeoTIFF `float32`
- stesso `CRS`, `transform`, `shape` del DEM
- `compress=LZW`
- `nodata=-9999`

## Algoritmo implementato
Per ogni pixel osservatore valido:
- `z_obs = dem[r,c] + observer_height`
- turbina da coordinate XY in `(rt,ct)` con inverse affine (`rowcol`)
- `z_base = dem[rt,ct]`, `z_top = z_base + H`
- distanza orizzontale `D` tra centri pixel (via affine)
- campionamento celle intermedie su linea osservatore→turbina con Bresenham (esclusi start/end)
- per ciascun campione valido: `alpha_i = (dem_i - z_obs)/d_i`
- `max_alpha = max(alpha_i)` (oppure `-inf` se nessun campione valido)
- `beta_base = (z_base - z_obs)/D`, `beta_top = (z_top - z_obs)/D`
- regole:
  - se `max_alpha <= beta_base` ⇒ visibile `H`
  - se `max_alpha >= beta_top` ⇒ visibile `0`
  - altrimenti interpolazione del tratto occultato
- clamp finale in `[0, H]`

Nodata intermedi:
- `Strict nodata = ON`: se presente nodata su campioni intermedi, output pixel = nodata.
- `Strict nodata = OFF`: campioni nodata ignorati.

## Build EXE con PyInstaller
Esegui:
```bat
build.bat
```

Comando standard:
```bat
pyinstaller --noconfirm --onefile --windowed wind_turbine_visible_height_gui.py
```

Fallback utile per rasterio/GDAL/PROJ:
```bat
pyinstaller --noconfirm --onefile --windowed --collect-all rasterio wind_turbine_visible_height_gui.py
```

## Problemi noti packaging rasterio (GDAL/PROJ)
Se l'EXE si avvia ma fallisce all'apertura/scrittura raster:
1. Prova prima `--collect-all rasterio`.
2. Usa un `.spec` custom includendo `datas` e `binaries` di rasterio/GDAL/PROJ.
3. Imposta variabili ambiente in runtime, se necessario:
   - `PROJ_LIB`
   - `GDAL_DATA`
4. Verifica che l'ambiente di build abbia versioni compatibili di `rasterio`, `gdal`, `proj`.

Suggerimento: testare l'EXE su macchina pulita (senza Python installato) per validare il packaging completo.
