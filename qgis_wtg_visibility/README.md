# WTG Visible Height - Plugin QGIS 3.x

Plugin desktop QGIS per calcolare i **metri visibili della WTG** su DEM/DTM, coerente con la logica dello strumento exe.

## Struttura
- `__init__.py`
- `metadata.txt`
- `plugin_main.py`
- `dialog.py` (UI costruita in codice)
- `calc_core.py`
- `raster_utils.py`
- `wtg_batch.py`

## Installazione manuale
1. Chiudi QGIS.
2. Copia la cartella `qgis_wtg_visibility` dentro la cartella plugin utente QGIS:
   - Windows: `%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\`
   - Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/`
   - macOS: `~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/`
3. Riavvia QGIS.
4. Vai su **Plugin > Gestisci e Installa Plugin** e abilita **WTG Visible Height**.

## Modalità operative
- **Singola WTG**: inserimento manuale X/Y/H e output `.tif`.
- **Multi-WTG**: layer punti + campo altezza, output raster separato per ogni feature + CSV opzionale.

## Logica di calcolo implementata
Per ogni cella osservatore:
- `z_obs = dem[cell] + observer_height`
- `z_base = quota DEM nel punto WTG`
- `z_top = z_base + H`
- lungo ogni raggio si stima `max_alpha`
- confronto con `beta_base` e `beta_top`
- output clampato in `[0, H]`

## Output
- GeoTIFF `float32`
- `nodata=-9999`
- `compress=LZW`
- stesso `CRS/transform/shape` del DEM (output principale)

## Fase 1 (MVP già inclusa)
- Dialog unico con modalità singola/multi.
- Core radiale separato dalla UI.
- Batch multi-WTG con gestione errori per singola turbina.
- Esecuzione asincrona con `QgsTask`.

## Fase 2 (ottimizzazioni consigliate)
- Numba opzionale sul core (`calc_core.py`) con fallback automatico.
- Migliore progress per raggi + scrittura incrementale.
- Crop/allineamento rigoroso raster bbox infittito su finestra DEM.
- Test automatici su dataset DEM sintetico.
