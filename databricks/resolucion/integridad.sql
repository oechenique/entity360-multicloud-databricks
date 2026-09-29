-- Restricciones de integridad de la resolución de identidades (regla 08), después de cada corrida de la
-- tarea `resolucion`. Cada consulta devuelve una fila con `falla` = 0 si la restricción se cumple.
-- Uso: databricks/resolucion/integridad.py (warehouse serverless), o pegarlas en el editor SQL.

-- 1. Cada registro, una sola vez y con entidad.
SELECT '1 registros sin entidad o repetidos' AS chequeo,
       (SELECT count(*) FROM entity360.resolution.registro) - (SELECT count(DISTINCT clave) FROM entity360.resolution.registro)
     + (SELECT count(*) FROM entity360.resolution.registro r
        LEFT ANTI JOIN entity360.resolution.entidad_registro e USING (clave)) AS falla;

-- 2. Una entidad = un golden record, con nombre.
SELECT '2 entidades sin golden record o sin nombre' AS chequeo,
       (SELECT count(DISTINCT entity_id) FROM entity360.resolution.entidad_registro)
     - (SELECT count(*) FROM entity360.resolution.golden_record WHERE nombre IS NOT NULL) AS falla;

-- 3. Ninguna entidad con dos LEI firmes distintos (GLEIF firme, OpenSanctions, SEC; Wikidata no cuenta).
SELECT '3 entidades con dos LEI firmes' AS chequeo, count(*) AS falla FROM (
  SELECT e.entity_id
  FROM entity360.resolution.entidad_registro e
  JOIN entity360.resolution.registro r USING (clave)
  LATERAL VIEW explode(r.leis) t AS lei
  WHERE r.fuente <> 'wikidata' AND (r.fuente <> 'gleif' OR r.lei_firme)
  GROUP BY e.entity_id HAVING count(DISTINCT lei) > 1);

-- 4. Ninguna entidad con dos CIK distintos (sin Wikidata).
SELECT '4 entidades con dos CIK' AS chequeo, count(*) AS falla FROM (
  SELECT e.entity_id
  FROM entity360.resolution.entidad_registro e
  JOIN entity360.resolution.registro r USING (clave)
  LATERAL VIEW explode(r.ciks) t AS cik
  WHERE r.fuente <> 'wikidata'
  GROUP BY e.entity_id HAVING count(DISTINCT cik) > 1);

-- 5. Ningún par determinístico separado, salvo los conflictos que la restricción manda a revisión.
SELECT '5 determinísticos separados sin conflicto' AS chequeo, count(*) AS falla
FROM entity360.resolution.par_candidato p
JOIN entity360.resolution.entidad_registro a ON a.clave = p.clave_a
JOIN entity360.resolution.entidad_registro b ON b.clave = p.clave_b
LEFT ANTI JOIN entity360.resolution.revision v ON v.clave_a = p.clave_a AND v.clave_b = p.clave_b
WHERE p.decision = 'determinístico' AND a.entity_id <> b.entity_id;

-- 6. Ningún par vetado dentro de la misma entidad.
SELECT '6 vetados juntos' AS chequeo, count(*) AS falla
FROM entity360.resolution.par_candidato p
JOIN entity360.resolution.entidad_registro a ON a.clave = p.clave_a
JOIN entity360.resolution.entidad_registro b ON b.clave = p.clave_b
WHERE p.decision = 'veto' AND a.entity_id = b.entity_id;

-- 7. Los aceptados que quedaron separados son exactamente los conflictos y empates de revisión.
SELECT '7 aceptados separados que no están en revisión' AS chequeo, count(*) AS falla
FROM entity360.resolution.par_candidato p
JOIN entity360.resolution.entidad_registro a ON a.clave = p.clave_a
JOIN entity360.resolution.entidad_registro b ON b.clave = p.clave_b
LEFT ANTI JOIN entity360.resolution.revision v
  ON v.clave_a = p.clave_a AND v.clave_b = p.clave_b AND v.tipo IN ('conflicto', 'empate')
WHERE p.decision = 'aceptado' AND a.entity_id <> b.entity_id;
