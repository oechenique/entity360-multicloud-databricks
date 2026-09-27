-- Proyección del lote de SEC EDGAR (fase 3): un emisor por línea, con el JSON de submissions anidado.
-- Si falta un campo anidado (la SEC cambia el formato), la proyección falla y el lote va a cuarentena.
SELECT cik, ticker, extraido_utc,
       submissions.name AS nombre,
       submissions.stateOfIncorporation AS estado_incorporacion,
       ultima_presentacion.fecha AS ultima_presentacion,
       ultima_presentacion.form AS ultima_presentacion_form
FROM crudo
