-- Fase 2 (regla 04): modelo transaccional normalizado del ERP "legacy".
-- Datos reales de GLEIF (CC0). Idempotente: se puede correr más de una vez.

IF DB_ID('entity360_erp') IS NULL
    CREATE DATABASE entity360_erp;
GO

USE entity360_erp;
GO

IF SCHEMA_ID('erp') IS NULL EXEC('CREATE SCHEMA erp');
GO
IF SCHEMA_ID('etl') IS NULL EXEC('CREATE SCHEMA etl');
GO

-- Entidad legal (una fila por LEI).
IF OBJECT_ID('erp.entidad') IS NULL
CREATE TABLE erp.entidad (
    lei                        CHAR(20)       NOT NULL CONSTRAINT pk_entidad PRIMARY KEY,
    nombre_legal               NVARCHAR(500)  NOT NULL,
    idioma_nombre              VARCHAR(10)    NULL,
    jurisdiccion               VARCHAR(10)    NULL,
    categoria                  VARCHAR(30)    NULL,
    forma_juridica_codigo      VARCHAR(10)    NULL,
    forma_juridica_otra        NVARCHAR(200)  NULL,
    estado_entidad             VARCHAR(20)    NOT NULL,   -- ACTIVE / INACTIVE / NULL (GLEIF)
    fecha_creacion_entidad     DATE           NULL,
    estado_registro            VARCHAR(30)    NOT NULL,   -- ISSUED / LAPSED / RETIRED / ANNULLED / ...
    fecha_registro_inicial     DATETIMEOFFSET NULL,
    fecha_ultima_actualizacion DATETIMEOFFSET NULL,
    fecha_proxima_renovacion   DATETIMEOFFSET NULL,
    lou_gestor                 CHAR(20)       NULL,
    alcance                    VARCHAR(20)    NOT NULL,   -- universo_ar / sede_ar / control
    modificado_en              DATETIME2(3)   NOT NULL CONSTRAINT df_entidad_mod DEFAULT SYSUTCDATETIME()
);
GO

-- Direcciones: legal y sede (una de cada tipo por entidad).
IF OBJECT_ID('erp.direccion') IS NULL
CREATE TABLE erp.direccion (
    lei             CHAR(20)       NOT NULL CONSTRAINT fk_direccion_entidad REFERENCES erp.entidad (lei),
    tipo            VARCHAR(10)    NOT NULL CONSTRAINT ck_direccion_tipo CHECK (tipo IN ('LEGAL', 'SEDE')),
    linea1          NVARCHAR(500)  NULL,
    numero          NVARCHAR(50)   NULL,
    linea_adicional NVARCHAR(500)  NULL,
    ciudad          NVARCHAR(200)  NULL,
    region          VARCHAR(10)    NULL,
    pais            CHAR(2)        NULL,
    codigo_postal   NVARCHAR(50)   NULL,
    modificado_en   DATETIME2(3)   NOT NULL CONSTRAINT df_direccion_mod DEFAULT SYSUTCDATETIME(),
    CONSTRAINT pk_direccion PRIMARY KEY (lei, tipo)
);
GO

-- Nombres alternativos (anteriores, traducidos, transliterados), en el orden de GLEIF.
IF OBJECT_ID('erp.nombre_alternativo') IS NULL
CREATE TABLE erp.nombre_alternativo (
    lei           CHAR(20)       NOT NULL CONSTRAINT fk_nombre_entidad REFERENCES erp.entidad (lei),
    orden         TINYINT        NOT NULL,
    nombre        NVARCHAR(500)  NOT NULL,
    tipo          VARCHAR(60)    NULL,
    idioma        VARCHAR(10)    NULL,
    modificado_en DATETIME2(3)   NOT NULL CONSTRAINT df_nombre_mod DEFAULT SYSUTCDATETIME(),
    CONSTRAINT pk_nombre_alternativo PRIMARY KEY (lei, orden)
);
GO

-- Relaciones matriz/filial (GLEIF RR). FK en las dos puntas: por eso el universo incluye el
-- conjunto de control (contrapartes no argentinas).
IF OBJECT_ID('erp.relacion') IS NULL
CREATE TABLE erp.relacion (
    lei_hijo                   CHAR(20)       NOT NULL CONSTRAINT fk_relacion_hijo  REFERENCES erp.entidad (lei),
    lei_padre                  CHAR(20)       NOT NULL CONSTRAINT fk_relacion_padre REFERENCES erp.entidad (lei),
    tipo                       VARCHAR(40)    NOT NULL,
    estado_relacion            VARCHAR(20)    NULL,
    estado_registro            VARCHAR(30)    NULL,
    fecha_inicio               DATETIMEOFFSET NULL,
    fecha_ultima_actualizacion DATETIMEOFFSET NULL,
    modificado_en              DATETIME2(3)   NOT NULL CONSTRAINT df_relacion_mod DEFAULT SYSUTCDATETIME(),
    CONSTRAINT pk_relacion PRIMARY KEY (lei_hijo, lei_padre, tipo)
);
GO

-- Control de aplicación de archivos de GLEIF (idempotencia de la carga y de los deltas).
-- Fuera de CDC: es metadata del proceso, no del negocio.
IF OBJECT_ID('etl.aplicacion_gleif') IS NULL
CREATE TABLE etl.aplicacion_gleif (
    archivo      VARCHAR(200)  NOT NULL CONSTRAINT pk_aplicacion_gleif PRIMARY KEY,
    tipo         VARCHAR(20)   NOT NULL,   -- full / delta_LastDay / delta_LastWeek
    publicacion  VARCHAR(30)   NOT NULL,
    sha256       CHAR(64)      NOT NULL,
    filas_leidas INT           NOT NULL,
    insertadas   INT           NOT NULL,
    actualizadas INT           NOT NULL,
    aplicado_en  DATETIME2(3)  NOT NULL CONSTRAINT df_aplicacion_en DEFAULT SYSUTCDATETIME()
);
GO
