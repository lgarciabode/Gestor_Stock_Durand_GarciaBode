import sqlite3
from pathlib import Path

from modules.carga_historico_datos import cargar_historico

ESQUEMA_SQL = """
CREATE TABLE IF NOT EXISTS proveedores (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE,
    contacto TEXT,
    telefono TEXT,
    email TEXT,
    activo INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS marcas (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS categorias (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE,
    descripcion TEXT
);

CREATE TABLE IF NOT EXISTS repuestos (
    id INTEGER PRIMARY KEY,
    codigo TEXT NOT NULL,
    marca_id INTEGER NOT NULL REFERENCES marcas(id),
    categoria_id INTEGER NOT NULL REFERENCES categorias(id),
    especificaciones TEXT,
    unidad_medida TEXT NOT NULL DEFAULT 'unidad' CHECK (unidad_medida IN ('unidad', 'cm')),
    stock_minimo REAL NOT NULL DEFAULT 0,
    stock_maximo REAL,
    punto_reorden REAL,
    stock_actual REAL NOT NULL DEFAULT 0,
    activo INTEGER NOT NULL DEFAULT 1,
    -- 1 = los umbrales (minimo, reorden, maximo) los corrigio una persona a
    -- mano: el recalculo automatico no los pisa (ver docs/modulo_alertas.md).
    parametros_manuales INTEGER NOT NULL DEFAULT 0 CHECK (parametros_manuales IN (0, 1)),
    UNIQUE (marca_id, codigo)
);

-- Relación proveedor <-> repuesto (muchos a muchos): no tiene tabla propia.
-- Se obtiene de `movimientos_stock`, donde cada INGRESO guarda a qué
-- proveedor se le compró. Ver docs de decisiones del modelo (13/10/2026).

-- Tabla de hechos (fact table) de movimientos de stock: un renglón por cada
-- ingreso/egreso/ajuste, sin cabecera de remito -no se trackea información
-- de remitos más allá de esta carga inicial-. Es la fuente de la serie de
-- tiempo para el módulo predictivo (RF04): se lee tal cual, por fecha,
-- nunca se reescribe un movimiento ya cargado.
-- IMPORTANTE: `repuestos.stock_actual` es un cache derivado de esta tabla,
-- mantenido por el trigger `trg_movimientos_actualiza_stock` de más abajo.
-- Ningún código de aplicación debe hacer UPDATE de stock_actual a mano:
-- basta con insertar el movimiento y el trigger lo actualiza solo (así no
-- hay riesgo de que un módulo nuevo se olvide de sincronizarlo).
-- Convención de signo: en INGRESO y EGRESO, `cantidad` es siempre positiva
-- (el trigger decide sumar o restar según `tipo`). En AJUSTE, `cantidad` es
-- un delta con signo (positivo para corregir hacia arriba, negativo hacia
-- abajo), porque un ajuste no tiene una dirección implícita como sí la
-- tienen un ingreso o un egreso.
CREATE TABLE IF NOT EXISTS movimientos_stock (
    id INTEGER PRIMARY KEY,
    repuesto_id INTEGER NOT NULL REFERENCES repuestos(id),
    proveedor_id INTEGER REFERENCES proveedores(id),  -- solo tiene sentido en INGRESO
    fecha DATE NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('INGRESO', 'EGRESO', 'AJUSTE')),
    cantidad REAL NOT NULL,
    codigo_proveedor_raw TEXT,  -- trazabilidad opcional 
    origen TEXT NOT NULL DEFAULT 'manual' CHECK (origen IN ('carga_inicial', 'manual')),
    -- Si este movimiento ANULA a otro (cargado por error), su id. Un movimiento
    -- nunca se borra ni se edita: se compensa con un AJUSTE inverso que lo
    -- referencia. Ver _migrar() para bases creadas antes de esta columna.
    anula_id INTEGER REFERENCES movimientos_stock(id)
);

CREATE INDEX IF NOT EXISTS idx_movimientos_repuesto_fecha
    ON movimientos_stock (repuesto_id, fecha);

CREATE TRIGGER IF NOT EXISTS trg_movimientos_actualiza_stock
AFTER INSERT ON movimientos_stock
BEGIN
    UPDATE repuestos
    SET stock_actual = stock_actual + (
        CASE NEW.tipo
            WHEN 'INGRESO' THEN NEW.cantidad
            WHEN 'EGRESO' THEN -NEW.cantidad
            ELSE NEW.cantidad
        END
    )
    WHERE id = NEW.repuesto_id;
END;


-- correr `cargar_historico`, en vez de basarse en si el archivo .sqlite3
-- existe. 
CREATE TABLE IF NOT EXISTS estado_sistema (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    carga_inicial_completa INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO estado_sistema (id, carga_inicial_completa) VALUES (1, 0);


CREATE TABLE IF NOT EXISTS usuarios (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    recordar_sesion INTEGER NOT NULL DEFAULT 0,
    ultimo_dispositivo TEXT
);

CREATE TABLE IF NOT EXISTS ordenes_compra (
    id INTEGER PRIMARY KEY,
    fecha DATE NOT NULL,
    proveedor_id INTEGER NOT NULL REFERENCES proveedores(id),
    estado TEXT NOT NULL DEFAULT 'Pendiente',
    archivo_txt TEXT
);

CREATE TABLE IF NOT EXISTS detalle_orden_compra (
    id INTEGER PRIMARY KEY,
    orden_id INTEGER NOT NULL REFERENCES ordenes_compra(id),
    repuesto_id INTEGER NOT NULL REFERENCES repuestos(id),
    cantidad_sugerida REAL NOT NULL
);

-- Alertas de stock (modulo de alertas, ver docs/modulo_alertas.md).
-- Se cierran a mano (atendida = 1) y nunca se borran: quedan como historial.
CREATE TABLE IF NOT EXISTS alertas (
    id INTEGER PRIMARY KEY,
    repuesto_id INTEGER NOT NULL REFERENCES repuestos(id),
    fecha DATE NOT NULL,
    tipo TEXT NOT NULL CHECK (tipo IN ('REORDEN', 'CRITICO', 'SOBRESTOCK')),
    mensaje TEXT NOT NULL CHECK (length(trim(mensaje)) > 0),
    atendida INTEGER NOT NULL DEFAULT 0 CHECK (atendida IN (0, 1))
);

-- Invariante del modulo: nunca dos alertas ABIERTAS del mismo tipo para el
-- mismo repuesto. Indice unico "parcial": solo cuenta las filas con
-- atendida = 0, asi las alertas ya atendidas pueden repetirse en el historial.
CREATE UNIQUE INDEX IF NOT EXISTS idx_alertas_abierta_unica
    ON alertas (repuesto_id, tipo) WHERE atendida = 0;
"""


def obtener_conexion(ruta_bd: str) -> sqlite3.Connection:
    conexion = sqlite3.connect(ruta_bd)
    conexion.row_factory = sqlite3.Row
    conexion.execute("PRAGMA foreign_keys = ON;")
    # WAL en vez del rollback-journal por defecto: ademas de permitir mejor
    # concurrencia de lectura, evita "disk I/O error" en carpetas sincronizadas
    # por OneDrive/Drive (el journal por defecto necesita un tipo de locking
    # de archivo que esas carpetas no siempre soportan bien). Sigue siendo
    # seguro ante cortes/crashes: el WAL se escribe a disco antes de aplicarse.
    conexion.execute("PRAGMA journal_mode = WAL;")
    return conexion


def crear_esquema(conexion: sqlite3.Connection) -> None:
    conexion.executescript(ESQUEMA_SQL)
    _migrar(conexion)
    conexion.commit()


def _migrar(conexion: sqlite3.Connection) -> None:
    """Actualiza bases creadas con una versión anterior del esquema.

    `CREATE TABLE IF NOT EXISTS` no agrega columnas a una tabla que ya existe,
    así que las columnas nuevas se agregan acá, solo si faltan (se puede correr
    muchas veces sin problema). No se pierde ningún dato.
    """
    columnas = {fila[1] for fila in conexion.execute("PRAGMA table_info(movimientos_stock)")}
    if "anula_id" not in columnas:
        conexion.execute("ALTER TABLE movimientos_stock ADD COLUMN anula_id INTEGER REFERENCES movimientos_stock(id)")
    # Invariante: un movimiento se anula una sola vez.
    conexion.execute(
        """CREATE UNIQUE INDEX IF NOT EXISTS idx_movimientos_anula_unica
           ON movimientos_stock (anula_id) WHERE anula_id IS NOT NULL"""
    )


def _carga_inicial_completa(conexion: sqlite3.Connection) -> bool:
    fila = conexion.execute(
        "SELECT carga_inicial_completa FROM estado_sistema WHERE id = 1"
    ).fetchone()
    return bool(fila and fila[0])


def inicializar_si_hace_falta(ruta_bd: str, ruta_excel_historico: str) -> None:
    """Punto de entrada para arrancar el sistema.
    """
    Path(ruta_bd).parent.mkdir(parents=True, exist_ok=True)
    conexion = obtener_conexion(ruta_bd)
    try:
        crear_esquema(conexion)
        if not _carga_inicial_completa(conexion):
            try:
                cargar_historico(conexion, ruta_excel_historico)
                conexion.execute(
                    "UPDATE estado_sistema SET carga_inicial_completa = 1 WHERE id = 1"
                )
                conexion.commit()
            except Exception:
                conexion.rollback()
                raise
    finally:
        conexion.close()