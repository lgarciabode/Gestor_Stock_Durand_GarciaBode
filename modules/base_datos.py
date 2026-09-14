"""Conexión a SQLite, creación de esquema e inicialización automática.

Según `data/README.md` del proyecto, la base SQLite no se trackea en git
(`*.sqlite3` está en `.gitignore`), así que el sistema tiene que poder
crearla y poblarla solo la primera vez que se detecta que no existe, sin
pasos manuales. Ese es el trabajo de `inicializar_si_hace_falta`.
"""
import sqlite3
from pathlib import Path

#from modules.importador import cargar_historico

ESQUEMA_SQL = """
CREATE TABLE IF NOT EXISTS proveedores (
    id INTEGER PRIMARY KEY,
    nombre TEXT NOT NULL UNIQUE,
    contacto TEXT,
    telefono TEXT,
    email TEXT
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
    stock_actual REAL NOT NULL DEFAULT 0
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

-- Tabla de hechos (fact table) de movimientos de stock: un renglón por cada
-- ingreso/egreso/ajuste, sin cabecera de remito -no se trackea información
-- de remitos más allá de esta carga inicial-. Es la fuente de la serie de
-- tiempo para el módulo predictivo (RF04): se lee tal cual, por fecha,
-- nunca se reescribe un movimiento ya cargado.
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
    conexion.execute("PRAGMA foreign_keys = ON;")
    return conexion


def crear_esquema(conexion: sqlite3.Connection) -> None:
    conexion.executescript(ESQUEMA_SQL)
    conexion.commit()


def inicializar_si_hace_falta(ruta_bd: str, ruta_excel_historico: str) -> None:
    """Punto de entrada único para arrancar el sistema.

    Si el archivo SQLite ya existe, no hace nada (evita recargar el
    histórico dos veces). Si no existe -por ejemplo, al clonar el
    repositorio por primera vez, ya que `*.sqlite3` está en `.gitignore`-
    crea el esquema completo y hace la carga inicial desde el Excel
    histórico del taller.
    """
    ya_existia = Path(ruta_bd).exists()

    Path(ruta_bd).parent.mkdir(parents=True, exist_ok=True)
    conexion = obtener_conexion(ruta_bd)
    try:
        crear_esquema(conexion)
        if not ya_existia:
            cargar_historico(conexion, ruta_excel_historico)
    finally:
        conexion.close()
