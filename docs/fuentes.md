# Fuentes, licencias y atribución

Todas las fuentes son registros públicos reales (principio 1). Verificado en el spike
(2026-09-24/25); evidencia en `spike/evidencia/`.

| Fuente | Qué aporta | Acceso | Licencia | Atribución / condiciones |
|---|---|---|---|---|
| **GLEIF** (Global LEI Index) | Entidades legales con LEI, nombre legal, domicilio, jurisdicción, estado; relaciones matriz/filial (RR) | Golden copy CSV diario (`goldencopy.gleif.org`) + deltas; API `api.gleif.org` | **CC0 1.0** | No exige atribución; se cita igual: "Fuente: GLEIF Golden Copy, gleif.org". |
| **SEC EDGAR** | Emisores ante la SEC por CIK: nombre, domicilio, nombres anteriores, presentaciones | `data.sec.gov/submissions/CIK##########.json`, `www.sec.gov/files/company_tickers.json` | Dominio público (información del gobierno de EE. UU.) | Política de acceso justo: `User-Agent` con nombre y mail y ≤10 requests/s (el spike usa 5/s). |
| **Wikidata** | Puente de identificadores: LEI (P1278), CIK (P5531), ticker (P414 + P249) | SPARQL `query.wikidata.org` | **CC0 1.0** (datos) | Pautas del endpoint: `User-Agent` identificable, sin ráfagas. |
| **OpenSanctions** (colección `default`) | Entidades con riesgo (sanciones, PEP, registros de riesgo), alias e identificadores | `data.opensanctions.org/datasets/latest/default/` (`targets.simple.csv`) | **CC BY-NC 4.0** | Uso no comercial: "a student project, a hobby analysis, personal research… you don't need our permission" (opensanctions.org/docs/commercial/exemption). Atribución obligatoria: "Datos: OpenSanctions (opensanctions.org), CC BY-NC 4.0". Este portfolio es no comercial. |
| **GDELT** | Menciones de organizaciones en noticias, con tono | BigQuery `gdelt-bq` (y archivos cada 15 min) | Uso libre con cita | Pendiente de verificar en B.10. |
