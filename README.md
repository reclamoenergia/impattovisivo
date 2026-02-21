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

## Ripartenza da zero (senza controlli manuali)
Se vuoi ripartire completamente da zero in locale:

1. cancella la tua vecchia cartella locale;
2. riclona il repository;
3. esegui lo script qui sotto dalla root del progetto.

```bat
bootstrap_clean.bat
```

Lo script automatizza tutto:
- crea/aggiorna `.venv`;
- installa le dipendenze;
- esegue smoke checks (`compileall` + import dei moduli critici);
- termina con errore se qualcosa non va.

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

## Build EXE script CLI `unified_view_to_points.py`
Per creare un eseguibile dedicato allo script CLI di campionamento Unified View:

```bat
build_unified_view_to_points.bat
```

In PowerShell:
```powershell
.\build_unified_view_to_points.bat
```

Output atteso:
- `dist\unified_view_to_points\unified_view_to_points.exe`

La build usa `unified_view_to_points.spec` e include dipendenze geospaziali (`rasterio`, `fiona`).

## Build EXE (consigliata)
```bat
build_fast.bat
```
Se usi **PowerShell**, esegui con percorso relativo esplicito:
```powershell
.\build_fast.bat
```
Lo script prova automaticamente `py -3.11` (poi `py -3.10`) se il launcher `py` è disponibile.
- Se `py` non è disponibile sul tuo PC, gli script provano automaticamente `python3.11` e `python3.10` prima di usare `python`.
Esegue:
```bat
py -3.11 -m pip install -r requirements.txt
py -3.11 -m PyInstaller --noconfirm --clean wind_visible_height.spec
```

Output consigliato: `dist\wind_visible_height\wind_visible_height.exe` (one-folder, più robusto).

## Build onefile (opzionale)
```bat
build_onefile.bat
```
Se usi **PowerShell**:
```powershell
.\build_onefile.bat
```
Esegue:
```bat
py -3.11 -m PyInstaller --noconfirm --clean --onefile wind_visible_height.spec
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
5. **Errore `Failed to load Python DLL ... _internal\python3xx.dll` su altri PC**
   - Non copiare solo l'`.exe`: distribuisci tutta la cartella `dist\wind_visible_height\` mantenendo la sottocartella `_internal`.
   - Evita Python 3.13/3.14 in build: usa Python 3.10 o 3.11 (gli script ora fanno controllo automatico).
   - Se il file DLL esiste ma non viene caricato, installa/ripara **Microsoft Visual C++ Redistributable 2015-2022 (x64)** sul PC target.
6. **Numba non usato**
   - Controlla log GUI: deve indicare `Numba disponibile: True`.
   - Reinstalla dipendenze e ricompila con Python 3.10/3.11.
7. **Errore `"pyinstaller" non è riconosciuto`**
   - Usa gli script aggiornati oppure lancia esplicitamente:
     - `py -3.11 -m PyInstaller --noconfirm --clean wind_visible_height.spec`
   - In PowerShell ricorda il prefisso `./` per gli script locali (`.\build_fast.bat`).
8. **Hai installato Python 3.11 ma la build usa ancora 3.14**
   - Verifica: `py -0p` (lista interpreti registrati nel launcher).
   - Esegui la build con launcher: `py -3.11 build_fast.bat` oppure usa direttamente `.\build_fast.bat` (ora seleziona `py -3.11` in automatico).
   - Se vedi ancora `[0/3] Check Python version` stai eseguendo una vecchia copia di `build_fast.bat`: rifai `git pull` e verifica il file con `Get-Content .\build_fast.bat -Head 20`.



## Script CLI: Unified View -> punti campionati

È disponibile lo script `tools/unified_view_to_points.py` per convertire una lista di raster Unified View (uno per turbina) in un layer punti (`.gpkg` o `.shp`) con attributi:
- `n_vis`
- `h_*` (altezza visibile per turbina)
- `az_ctr`, `az_min`, `az_max`, `fov_az`

Esempio:
```bat
python tools/unified_view_to_points.py --rasters r1.tif r2.tif --turbines turbines.csv --spacing 25 --out out.gpkg
```

### Interfaccia grafica (GUI) per `unified_view_to_points`

Ora lo strumento supporta anche una GUI desktop Tkinter.

- Avvio GUI esplicito:
  ```bat
  python tools/unified_view_to_points.py --gui
  ```
- Avvio GUI senza parametri (comodo da doppio click su `.exe`):
  ```bat
  python tools/unified_view_to_points.py
  ```

Nella GUI trovi:
- selettori file per raster, turbine e output;
- tutti i parametri principali (`spacing`, `threshold`, `extent`, `mask`, formato output, EPSG, chunk);
- una sezione con spiegazione sintetica dell'algoritmo e degli input richiesti;
- area log con avanzamento elaborazione.

Se preferisci l'uso da riga di comando, il comportamento CLI resta invariato quando passi gli argomenti richiesti (`--rasters`, `--turbines`, `--out`).

## Specifica core radiale (aggiornata)

Il file `core_radial_visibility.py` contiene la specifica implementata del core.

### Decisioni applicate
- **Fuori dal dominio radiale** (`R`): nel raster principale il valore è `0`.
- **`step_global` impostabile** via `RadialConfig.step_m` (default suggerito `24 m`, utile con DTM 8 m).
- **Direzioni radiali**: `K` consigliato da `K≈2πR/s` con snapping ai preset qualità `4096/8192/12288/16384` (`suggest_k_from_radius`).
  - Esempi: `R=10 km`, `s=8 m` -> `K≈7854` -> `8192`.
  - `R=15 km` -> `K≈11781` -> `12288` (o `16384` se si vuole più robustezza angolare).
- **Infittimento bbox opzionale**: secondo pass separato con `step_fine` + `K_fine`, solo nella bbox (CRS DEM), con output raster dedicato.
- **Output infittito raster separato** GeoTIFF float32 (non vettoriale).

### Output
1. **Output principale** (GeoTIFF float32): stesso CRS/transform/shape del DEM, `compress=LZW`, `nodata=-9999`, fuori da `R` = `0`.
2. **Output infittito opzionale** (GeoTIFF float32):
   - default **croppato alla bbox**, allineato alla griglia DEM (`aligned_bbox_window`).
   - `nodata=-9999` fuori dall'area calcolata.
   - opzione `full_extent=True`: dimensione DEM completa, valori solo nella bbox e nodata fuori.

### Nodata
- Se la turbina cade su nodata -> errore.
- `strict_nodata=True`: ai campioni nodata lungo il raggio il raggio viene interrotto.
- `strict_nodata=False`: i campioni nodata vengono ignorati.

### Nota performance
- Struttura pronta per Numba-friendly (array numpy + loop lineari + tipi semplici).
- Multiprocessing **non introdotto** in questa specifica.
