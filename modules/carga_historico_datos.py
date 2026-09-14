import sqlite3
from datetime import datetime
 
from openpyxl import load_workbook
 
from modules.parsers import obtener_parser
 
HOJA_DATOS = "Productos"
ENCABEZADOS = ["Fecha", "N° Remito", "Proveedor", "Código", "Descripción", "Cantidad"]
 
 
def _fecha_iso(valor) -> str:
    """El Excel trae las fechas como texto dd/mm/aaaa; SQLite guarda mejor
    en formato ISO (comparable como texto y compatible con funciones de
    fecha de SQLite)."""
    if isinstance(valor, datetime):
        return valor.date().isoformat()
    return datetime.strptime(str(valor).strip(), "%d/%m/%Y").date().isoformat()
 
 
def _obtener_o_crear(conexion: sqlite3.Connection, tabla: str, columna: str, valor: str) -> int:
    fila = conexion.execute(f"SELECT id FROM {tabla} WHERE {columna} = ?", (valor,)).fetchone()
    if fila:
        return fila[0]
    cursor = conexion.execute(f"INSERT INTO {tabla} ({columna}) VALUES (?)", (valor,))
    return cursor.lastrowid
 
 
def _obtener_o_crear_repuesto(conexion: sqlite3.Connection, proveedor_id: int, linea) -> int:
    """Resuelve la identidad del repuesto por (proveedor, código de
    proveedor): es la clave de `repuesto_codigo_proveedor`. Si ya existe esa
    combinación, reutiliza el repuesto; si no, crea el repuesto y su mapeo.
    """
    fila = conexion.execute(
        """SELECT repuesto_id FROM repuesto_codigo_proveedor
           WHERE proveedor_id = ? AND codigo_proveedor = ?""",
        (proveedor_id, linea.codigo_proveedor),
    ).fetchone()
    if fila:
        return fila[0]
 
    marca_id = _obtener_o_crear(conexion, "marcas", "nombre", linea.marca)
    cursor = conexion.execute(
        "INSERT INTO repuestos (descripcion_normalizada, marca_id) VALUES (?, ?)",
        (linea.descripcion, marca_id),
    )
    repuesto_id = cursor.lastrowid
    conexion.execute(
        """INSERT INTO repuesto_codigo_proveedor
           (repuesto_id, proveedor_id, codigo_proveedor, codigo_interno_taller)
           VALUES (?, ?, ?, ?)""",
        (repuesto_id, proveedor_id, linea.codigo_proveedor, linea.codigo_interno_taller),
    )
    return repuesto_id
 
 
def cargar_historico(conexion: sqlite3.Connection, ruta_excel: str) -> None:
    """Punto de entrada del importador. Asume que el esquema ya existe
    (ver `modules.base_datos.crear_esquema`).
 
    No hace commit ni rollback propios: la transacción la controla quien
    llama (`modules.base_datos.inicializar_si_hace_falta`), para poder
    deshacer todo de una si algo falla a mitad de la carga.
    """
    libro = load_workbook(ruta_excel, read_only=True, data_only=True)
    hoja = libro[HOJA_DATOS]
 
    total_producto = 0
    total_cargo_excluido = 0
 
    for valores in hoja.iter_rows(min_row=2, values_only=True):
        if valores[0] is None:  # fila vacía (puede quedar al final de la hoja)
            continue
        fila = dict(zip(ENCABEZADOS, valores))
 
        parser = obtener_parser(fila["Proveedor"])
        linea = parser.parsear(fila)
 
        if linea.tipo_linea != "PRODUCTO":
            # Cargos administrativos (flete, seguro): no son stock, no se
            # guardan. El Excel original en data/ queda como registro por
            # si hace falta auditarlos más adelante.
            total_cargo_excluido += 1
            continue
 
        proveedor_id = _obtener_o_crear(conexion, "proveedores", "nombre", linea.proveedor)
        repuesto_id = _obtener_o_crear_repuesto(conexion, proveedor_id, linea)
        fecha = _fecha_iso(fila["Fecha"])
 
        # stock_actual se actualiza solo, vía el trigger
        # trg_movimientos_actualiza_stock (ver modules/base_datos.py): no
        # hace falta (ni conviene) tocarlo a mano acá.
        conexion.execute(
            """INSERT INTO movimientos_stock
               (repuesto_id, proveedor_id, fecha, tipo, cantidad, codigo_proveedor_raw, origen)
               VALUES (?, ?, ?, 'INGRESO', ?, ?, 'carga_inicial')""",
            (repuesto_id, proveedor_id, fecha, linea.cantidad, linea.codigo_proveedor),
        )
        total_producto += 1
 
    print(
        f"Carga inicial completa: {total_producto} movimientos de stock cargados, "
        f"{total_cargo_excluido} líneas de cargos administrativos excluidas (no son stock)."
    )