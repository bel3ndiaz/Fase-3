-- =====================================================================
-- crear_bd.sql
-- Biblioteca Digital de Instrucciones de Trabajo - Impresos Múltiples
-- Fase 3: MySQL (XAMPP + phpMyAdmin) con documentos en LONGBLOB
--
-- Cómo usarlo: en phpMyAdmin → pestaña "Importar" → elegir este archivo → Continuar.
-- Si la base ya existe, borra y vuelve a crear las tablas (los datos se reinician).
-- =====================================================================

-- XAMPP trae max_allowed_packet = 1M: un documento más grande corta la conexión.
-- Esta línea lo sube a 16 MB hasta que se reinicie MySQL. Para que sea permanente,
-- poner max_allowed_packet=16M en la sección [mysqld] de xampp/mysql/bin/my.ini.
SET GLOBAL max_allowed_packet = 16777216;

CREATE DATABASE IF NOT EXISTS biblioteca_impresos
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE biblioteca_impresos;

-- Se borran primero las tablas relacionadas (las que tienen llave foránea)
DROP TABLE IF EXISTS archivos;
DROP TABLE IF EXISTS historial_versiones;
DROP TABLE IF EXISTS instrucciones;

-- ---------------------------------------------------------------------
-- Tabla principal: instrucciones de trabajo
-- ---------------------------------------------------------------------
CREATE TABLE instrucciones (
    id                  INT AUTO_INCREMENT PRIMARY KEY,
    codigo              VARCHAR(20)  NOT NULL UNIQUE,
    titulo              VARCHAR(100) NOT NULL,
    area                VARCHAR(50)  NOT NULL,
    version             INT          NOT NULL DEFAULT 0,  -- (Desafío 2) se reemplaza por la tabla archivos
    version_vigente     INT          NOT NULL DEFAULT 0,  -- (Desafío 2) se reemplaza por la tabla archivos
    enlace_video        VARCHAR(255) NULL,
    fecha_actualizacion DATE         NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- Tabla relacionada: historial de versiones de cada instrucción.
-- Una fila por cada versión del documento que se crea (subida o restauración).
-- instruccion_id es la LLAVE FORÁNEA: apunta a instrucciones.id
-- ON DELETE RESTRICT: NO se puede borrar una instrucción que tenga historial.
-- Así el historial nunca se pierde por eliminar un registro.
-- ---------------------------------------------------------------------
CREATE TABLE historial_versiones (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    instruccion_id INT          NOT NULL,
    version        INT          NOT NULL,
    accion         VARCHAR(255) NOT NULL DEFAULT 'Versión registrada',
    fecha          DATETIME     NOT NULL,
    CONSTRAINT fk_historial_instruccion
        FOREIGN KEY (instruccion_id) REFERENCES instrucciones (id)
        ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- Tabla de documentos (Fase 3): un documento PDF o Word por instrucción,
-- con historial de versiones. Subir de nuevo el documento crea una fila
-- nueva con version = MAX(version) + 1; las anteriores no se tocan.
-- instruccion_id es la LLAVE FORÁNEA: apunta a instrucciones.id
-- ON DELETE RESTRICT: MySQL rechaza borrar una instrucción que tenga
-- documentos, así que nunca quedan archivos huérfanos ni se pierden versiones.
-- ---------------------------------------------------------------------
CREATE TABLE archivos (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    instruccion_id  INT          NOT NULL,
    version         INT          NOT NULL,          -- 1, 2, 3... por instrucción
    nombre_original VARCHAR(255) NOT NULL,          -- nombre con el que se subió
    extension       VARCHAR(5)   NOT NULL,          -- pdf, doc o docx
    tamano_bytes    INT          NOT NULL,
    contenido       LONGBLOB     NOT NULL,          -- el archivo completo
    enlace_video    VARCHAR(255) NULL,              -- enlace del video al subir esta versión
    fecha_subida    DATETIME     NOT NULL,
    CONSTRAINT uq_archivo_version UNIQUE (instruccion_id, version),
    CONSTRAINT fk_archivo_instruccion
        FOREIGN KEY (instruccion_id) REFERENCES instrucciones (id)
        ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------
-- Datos de ejemplo: 8 instrucciones (sin documentos: los documentos se
-- suben desde el navegador; el script no guarda archivos reales)
-- ---------------------------------------------------------------------
INSERT INTO instrucciones (id, codigo, titulo, area, version, version_vigente, enlace_video, fecha_actualizacion) VALUES
    (1, 'IM-OFF-001', 'Preparación de máquina offset', 'Impresión Offset', 3, 3, 'https://intranet.ejemplo.com/videos/offset-preparacion', '2026-09-02'),
    (2, 'IM-OFF-002', 'Cambio de planchas', 'Impresión Offset', 2, 3, 'https://intranet.ejemplo.com/videos/cambio-planchas', '2026-07-15'),
    (3, 'IM-TIN-001', 'Preparación de tinta Pantone', 'Preparación de Tintas', 4, 4, NULL, '2026-09-10'),
    (4, 'IM-TRO-001', 'Ajuste de troquel', 'Troquelado', 1, 2, 'https://intranet.ejemplo.com/videos/ajuste-troquel', '2026-05-20'),
    (5, 'IM-ACA-001', 'Laminado brillante', 'Acabados', 2, 2, NULL, '2026-08-01'),
    (6, 'IM-ENC-001', 'Encuadernado hot melt', 'Encuadernación', 1, 3, 'https://intranet.ejemplo.com/videos/hot-melt', '2026-04-11'),
    (7, 'IM-MAN-001', 'Calibración de cortadora', 'Mantenimiento', 5, 5, NULL, '2026-09-25'),
    (8, 'IM-CAL-001', 'Inspección de calidad de impresión', 'Control de Calidad', 2, 2, 'https://intranet.ejemplo.com/videos/inspeccion-calidad', '2026-08-18');
