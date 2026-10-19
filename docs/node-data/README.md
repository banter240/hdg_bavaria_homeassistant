# hdg_data.csv

Node list I scraped myself. Not an HDG file. 1280 rows, UTF-8 with BOM. The integration does not read it.

German names and slider limits come from the edit page on <https://myhdg-demo.hdg-bavaria.com/> (`index.php?d=set&i=<id>`, one id per call). That site is German. English names come from the same page on <https://demo-myhdg.hdg-bavaria.com/>.

Placeholder, data type, unit/format, enum type, and both enum-option columns come from a node export of 1 June 2026. 24 rows have no placeholder and no name. 550 rows have a formatter. 449 rows have an enum, written as `Key: Text (RSI: n)` and joined with `; `, otherwise `-`. The edit pages do not include the enum lists for a normal user.

`Minimum` and `Maximum` are the slider ends on the German page, unit included (`1 K`, `80 °C`, `10 s`). 576 rows. Empty means no slider. `-2147483648` and `2147483647` are not stored.

147 ids return `OBJEKT NICHT GEFUNDEN ODER NICHT BEARBEITBAR`. Those names and limits are still the June export. A page is ignored when its menu code or `data-id` belongs to another node. `dataRefresh` returns the live value only.

The edit page for 29001 is node 24002, `Fühler Puffer unten`, from `-60 °C` to `270 °C`. The names stay `Aktive Zone (Solar)` and `Active zone (Solar)`. Data type is 40. On 19 October 2026 the German demo returned `61 °C` for 29001, the same value as 29004.

9040 (`Temperaturspreizung Soll` / `Target temp. difference`) has formatter `iKELV`. The slider is `2 °C` to `20 °C`.
