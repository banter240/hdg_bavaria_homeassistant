# hdg_data.csv

1280 rows, one row per node, UTF-8 with BOM. The integration does not read this file.

This is not an official HDG file. I scraped the display names and slider limits myself from the two public demos and combined them with a node export from 1 June 2026. The columns are as described below. Where an edit page is missing, or the page shows a different node, the row stays at that export. Those rows can be wrong.

## Columns

**Node ID**
Node number.

**Placeholder (desc1)**
Placeholder from the export, for example `#TNRMITNUM9021`. 24 rows are empty. Those same 24 rows also have no display name.

**German display name**
Name on the edit page `https://myhdg-demo.hdg-bavaria.com/index.php?d=set&i=<id>`. This host is German.

**English display name**
The same page on `https://demo-myhdg.hdg-bavaria.com/`. This host is English.

**Data type (data_type)**
Type number from the export.

**Unit/format (formatter)**
Formatter from the export, for example `iTEMP`, `iKELV`, `iPERC`, `iSEK`. 550 rows are filled. The rest are empty.

**Enum type**
Enum name from the export. 449 rows, otherwise `-`.

**German enum options (key: text, RSI)**
**English enum options (key: text, RSI)**
`Key: Text (RSI: n)`, with further options separated by `; `. 449 rows, otherwise `-`. The lists are the export from 1 June 2026. The demo edit pages do not return them at the normal user level.

**Minimum**
**Maximum**
Left and right end of the slider on the German edit page, with the unit shown there (`1 K`, `80 °C`, `10 s`). 576 rows. Empty means the page had no slider. The range `-2147483648` to `2147483647` is not in the file.

147 IDs have no edit page. The response is `OBJEKT NICHT GEFUNDEN ODER NICHT BEARBEITBAR`. Display names and limits on those rows are the export.

An edit page counts only when its menu code or `data-id` is the requested node number. `dataRefresh` returns only the current value for many IDs, not the name and not the limits.

## 29001

The edit page for 29001 belongs to node 24002. It shows `Fühler Puffer unten`, and the slider runs from `-60 °C` to `270 °C`. The row therefore keeps the export name `Aktive Zone (Solar)` / `Active zone (Solar)`. The export data type is 40. On 19 October 2026, `dataRefresh` on the German demo returned `61 °C` for 29001, the same value as for 29004.

## 9040

Display name `Temperaturspreizung Soll` / `Target temp. difference`. Formatter `iKELV`. Minimum `2 °C`, maximum `20 °C`.

## Not in this folder

This folder contains only this README and `hdg_data.csv`.

Data type, unit/format, enum type, and enum options are the contents of `data.json` and `enum_option.json`.

`deutsch.json` and `english.json` are the export from 1 June 2026, 4607 strings. The demos do not offer these files. Node names are in German display name and English display name.
