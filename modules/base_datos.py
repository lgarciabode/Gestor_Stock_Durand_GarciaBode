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
    descripcion_normalizada TEXT NOT NULL,
    marca_id INTEGER REFERENCES marcas(id),
    categoria_id INTEGER REFERENCES categorias(id),
    especificaciones TEXT,
    unidad_medida TEXT NOT NULL DEFAULT 'unidad',
    stock_minimo REAL NOT NULL DEFAULT 0,
    stock_maximo REAL,
    punto_reorden REAL,
    stock_actual REAL NOT NULL DEFAULT 0,
    activo INTEGER NOT NULL DEFAULT 1
);

-- Resuelve el problema central: el mismo repuesto puede tener códigos
-- distintos según el proveedor (y ED-MA aporta además un código interno
-- del taller). Ver docs/modelo_datos_y_limpieza.md, sección 3.
CREATE TABLE IF NOT EXISTS repuesto_codigo_proveedor (
    id INTEGER PRIMARY KEY,
    repuesto_id INTEGER NOT NULL REFERENCES repuestos(id),
    proveedor_id INTEGER NOT NULL REFERENCES proveedores(id),
    codigo_proveedor TEXT NOT NULL,
    codigo_interno_taller TEXT,
    UNIQUE (proveedor_id, codigo_proveedor)
);

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
    codigo_proveedor_raw TEXT,  -- trazabilidad opcional (se completa solo en la carga histórica)
    origen TEXT NOT NULL DEFAULT 'manual' CHECK (origen IN ('carga_inicial', 'manual'))
);

-- El módulo predictivo (RF04) va a filtrar por repuesto_id y recorrer por
-- fecha constantemente; sin este índice cada consulta escanea toda la tabla.
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

-- Bandera de estado de la carga inicial: se usa para decidir si hay que
-- correr `cargar_historico`, en vez de basarse en si el archivo .sqlite3
-- existe. Así, si la carga se corta a mitad de camino (Excel corrupto,
-- corte de luz, lo que sea), el próximo arranque la vuelve a intentar en
-- vez de quedarse con una base a medio poblar y creer que ya terminó.
CREATE TABLE IF NOT EXISTS estado_sistema (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    carga_inicial_completa INTEGER NOT NULL DEFAULT 0
);
INSERT OR IGNORE INTO estado_sistema (id, carga_inicial_completa) VALUES (1, 0);

-- Tablas de soporte para etapas siguientes del proyecto (login, pedidos,
-- alertas). Se crean desde ahora para no tener que migrar el esquema
-- después; todavía no las llena ningún módulo.
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

CREATE TABLE IF NOT EXISTS alertas (
    id INTEGER PRIMARY KEY,
    repuesto_id INTEGER NOT NULL REFERENCES repuestos(id),
    fecha DATE NOT NULL,
    tipo TEXT NOT NULL,
    mensaje TEXT NOT NULL,
    atendida INTEGER NOT NULL DEFAULT 0
);
"""


def obtener_conexion(ruta_bd: str) -> sqlite3.Connection:
    conexion = sqlite3.connect(ruta_bd)
    conexion.row_factory = sqlite3.Row
    conexion.execute("PRAGMA foreign_keys = ON;")
    return conexion


def crear_esquema(conexion: sqlite3.Connection) -> None:
    conexion.executescript(ESQUEMA_SQL)
    conexion.commit()


def _carga_inicial_completa(conexion: sqlite3.Connection) -> bool:
    fila = conexion.execute(
        "SELECT carga_inicial_completa FROM estado_sistema WHERE id = 1"
    ).fetchone()
    return bool(fila and fila[0])


def inicializar_si_hace_falta(ruta_bd: str, ruta_excel_historico: str) -> None:
    """Punto de entrada único para arrancar el sistema.

    Crea el esquema si hace falta (idempotente: `CREATE TABLE IF NOT
    EXISTS`) y, si la carga inicial todavía no se completó, la corre.

    El chequeo se hace contra la bandera `estado_sistema.carga_inicial_completa`
    y no contra "¿existe el archivo .sqlite3?": el archivo se crea apenas se
    abre la conexión, así que si la carga se corta a mitad de camino (Excel
    corrupto, corte de luz) el archivo ya existiría con el esquema pero sin
    datos, y un chequeo por existencia de archivo nunca reintentaría. Por
    eso además la carga corre en una transacción explícita: si falla, se
    hace rollback de lo insertado hasta ese momento y la bandera queda en 0,
    para que el próximo arranque la reintente de cero en vez de dejar datos
    a medias mezclados con una bandera que diga "completo".
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