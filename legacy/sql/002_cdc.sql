-- Fase 2 (regla 04): CDC en las tablas de negocio del ERP. Idempotente.
-- Requiere SQL Server Agent (edición Developer, MSSQL_AGENT_ENABLED=true).

USE entity360_erp;
GO

IF (SELECT is_cdc_enabled FROM sys.databases WHERE name = 'entity360_erp') = 0
    EXEC sys.sp_cdc_enable_db;
GO

DECLARE @tablas TABLE (nombre SYSNAME);
INSERT INTO @tablas VALUES ('entidad'), ('direccion'), ('nombre_alternativo'), ('relacion');

DECLARE @t SYSNAME, @instancia SYSNAME;
DECLARE c CURSOR LOCAL FAST_FORWARD FOR SELECT nombre FROM @tablas;
OPEN c;
FETCH NEXT FROM c INTO @t;
WHILE @@FETCH_STATUS = 0
BEGIN
    -- Instancia de captura erp_<tabla>: la usa el extractor (cdc.fn_cdc_get_all_changes_erp_<tabla>).
    SET @instancia = N'erp_' + @t;
    IF NOT EXISTS (SELECT 1 FROM cdc.change_tables WHERE capture_instance = @instancia)
        EXEC sys.sp_cdc_enable_table
             @source_schema        = N'erp',
             @source_name          = @t,
             @capture_instance     = @instancia,
             @role_name            = NULL,
             @supports_net_changes = 1;
    FETCH NEXT FROM c INTO @t;
END
CLOSE c;
DEALLOCATE c;
GO
