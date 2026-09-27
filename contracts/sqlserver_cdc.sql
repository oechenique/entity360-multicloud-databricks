-- Proyección del lote del extractor CDC (fase 2): una fila por cambio de una tabla del ERP.
-- La clave de la fila (lei, o lei_hijo en relacion) se lee del JSON: cada tabla trae otras columnas.
SELECT tabla, op, lsn, seqval,
       TRY_CAST(commit_time AS TIMESTAMP) AS commit_time,
       coalesce(json_extract_string(to_json(datos), '$.lei'), json_extract_string(to_json(datos), '$.lei_hijo')) AS lei
FROM crudo
