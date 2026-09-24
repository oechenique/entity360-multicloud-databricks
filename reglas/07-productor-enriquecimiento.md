# 07 — Fase 5: Container de enriquecimiento (OpenSanctions + Wikidata)

- Imagen Docker (Python) publicada en GitHub Container Registry.
- Ejecución programada con GitHub Actions (cron), una vez por día.
- OpenSanctions: descarga del dataset consolidado (o el subconjunto útil), filtrado a
  entidades que puedan cruzarse con el universo.
- Wikidata: consulta SPARQL de empresas del universo con sus identificadores (LEI, CIK,
  sitio web, país). Respetar las pautas de uso del endpoint.
- Empuja al volume con el contrato de landing.
- Licencias y atribuciones en `docs/fuentes.md`.
