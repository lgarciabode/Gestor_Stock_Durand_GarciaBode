"""Modulo de operaciones CRUD, gestion de inventario. Transaccional diario
Encapsula las operaciones de persistencia (alta, lectura, modificacion y baja) sobre la BD SQLite para las entidades Repuesto, Proveedor y Movimientos de Stock"""

import sqlite3
from typing import List, Optional
from modules.modelos import Categoria, Marca, MovimientoStock, Proveedor, Repuesto, validar_umbrales

def _fila_a_repuesto(f: sqlite3.Row) -> Repuesto:
    """Convierte una fila de la tabla repuestos en un objeto Repuesto."""
    return Repuesto(
        id=f["id"],
        codigo=f["codigo"],
        marca_id=f["marca_id"],
        categoria_id=f["categoria_id"],
        especificaciones=f["especificaciones"],
        unidad_medida=f["unidad_medida"],
        stock_minimo=f["stock_minimo"],
        stock_maximo=f["stock_maximo"],
        punto_reorden=f["punto_reorden"],
        stock_actual=f["stock_actual"],
        activo=bool(f["activo"]),
        parametros_manuales=bool(f["parametros_manuales"]),
    )


class GestorInventarioBD:
    """Clase de servicio que maneja las operaciones CRUD sobre la BD"""
    def __init__(self, conexion: sqlite3.Connection):
        self.conexion = conexion

#PROVEEDORES
    def crear_proveedor(self, prov: Proveedor) -> int:
        """Inserta un nuevo proveedor en la BD y retorna su ID asignado"""
        cursor = self.conexion.execute(
            """INSERT INTO proveedores (nombre, contacto, telefono, email, activo) VALUES (?, ?, ?, ?, ?)""", (prov.nombre, prov.contacto, prov.telefono, prov.email, int(prov.activo)),
        )
        self.conexion.commit()
        return cursor.lastrowid

    def obtener_proveedores(self, solo_activos: bool = True) -> List[Proveedor]:
        """Obtiene la lista de todos los proveedores registrados."""
        query = "SELECT * FROM proveedores"
        if solo_activos:
            query += " WHERE activo = 1"
        cursor = self.conexion.execute(query)
        filas = cursor.fetchall()
        return [Proveedor(
            id = f["id"],
            nombre = f["nombre"],
            contacto = f["contacto"],
            telefono = f["telefono"],
            email = f["email"],
            activo = bool(f["activo"]),
        )
        for f in filas
        ]


    def actualizar_proveedor(self, prov: Proveedor) -> None:
        """Actualiza los datos de un proveedor existente."""
        self.conexion.execute(
            """UPDATE proveedores
            SET nombre = ?, contacto = ?, telefono = ?, email = ?, activo = ? WHERE id = ?""",
            (
                prov.nombre,
                prov.contacto,
                prov.telefono,
                prov.email,
                int(prov.activo),
                prov.id
            ),
        )
        self.conexion.commit()

    def desactivar_proveedor(self, proveedor_id: int) -> None:
        """Baja logica de un proveedor, su estado ser inactivo = 0"""
        self.conexion.execute(
            """UPDATE proveedores SET activo = 0 WHERE id = ?""", (proveedor_id,)
        )
        self.conexion.commit()


#MARCAS Y CATEGORIAS
    def crear_marca(self, marca: Marca) -> int:
        """Da de alta una marca nueva y retorna su ID"""
        cursor = self.conexion.execute("INSERT INTO marcas (nombre) VALUES (?)", (marca.nombre,))
        self.conexion.commit()
        return cursor.lastrowid

    def obtener_marcas(self) -> List[Marca]:
        """Lista de marcas, ordenada por nombre (para elegir en un formulario)"""
        filas = self.conexion.execute("SELECT * FROM marcas ORDER BY nombre").fetchall()
        return [Marca(id=f["id"], nombre=f["nombre"]) for f in filas]

    def crear_categoria(self, categoria: Categoria) -> int:
        """Da de alta una categoría nueva (la lista es cerrada, pero el usuario puede ampliarla)"""
        cursor = self.conexion.execute(
            "INSERT INTO categorias (nombre, descripcion) VALUES (?, ?)",
            (categoria.nombre, categoria.descripcion),
        )
        self.conexion.commit()
        return cursor.lastrowid

    def obtener_categorias(self) -> List[Categoria]:
        """Lista de categorías, ordenada por nombre (para elegir en un formulario)"""
        filas = self.conexion.execute("SELECT * FROM categorias ORDER BY nombre").fetchall()
        return [Categoria(id=f["id"], nombre=f["nombre"], descripcion=f["descripcion"]) for f in filas]


#REPUESTOS
    def crear_repuestos(self, rep: Repuesto) -> int:
        """Crea un nuevo repuesto en el catalogo.
        Lanza sqlite3.IntegrityError si ya existe un repuesto con la misma
        marca y codigo, o si la unidad de medida no es 'unidad' ni 'cm'."""
        cursor = self.conexion.execute(
            """INSERT INTO repuestos (codigo, marca_id, categoria_id, especificaciones,
                unidad_medida, stock_minimo, stock_maximo, punto_reorden, stock_actual, activo,
                parametros_manuales)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
            rep.codigo,
            rep.marca_id,
            rep.categoria_id,
            rep.especificaciones,
            rep.unidad_medida,
            rep.stock_minimo,
            rep.stock_maximo,
            rep.punto_reorden,
            rep.stock_actual,
            int(rep.activo),
            int(rep.parametros_manuales),
            ),
        )
        self.conexion.commit()
        return cursor.lastrowid

    def obtener_repuestos(self, solo_activos: bool = True) -> List[Repuesto]:
        """Obtiene el catalogo de repuestos con su stock actual"""
        query = "SELECT * FROM repuestos"
        if solo_activos:
            query += " WHERE activo = 1"
        filas = self.conexion.execute(query).fetchall()
        return [_fila_a_repuesto(f) for f in filas]

    def obtener_repuesto_id(self, repuesto_id: int) -> Optional[Repuesto]:
        """Busca un repuesto por su PK"""
        f = self.conexion.execute(
            "SELECT * FROM repuestos WHERE id = ?", (repuesto_id,)
        ).fetchone()
        return _fila_a_repuesto(f) if f else None

    def obtener_repuesto_por_codigo(self, marca_id: int, codigo: str) -> Optional[Repuesto]:
        """Busca un repuesto por su identidad de negocio: marca + codigo"""
        f = self.conexion.execute(
            "SELECT * FROM repuestos WHERE marca_id = ? AND codigo = ?", (marca_id, codigo)
        ).fetchone()
        return _fila_a_repuesto(f) if f else None

    def actualizar_repuesto(self, rep: Repuesto) -> None:
        """Actualiza la informacion de un repuesto"""
        self.conexion.execute(
            """UPDATE repuestos
            SET codigo = ?, marca_id = ?, categoria_id = ?, especificaciones = ?, unidad_medida = ?, activo = ? WHERE id = ?""",
            (
            rep.codigo,
            rep.marca_id,
            rep.categoria_id,
            rep.especificaciones,
            rep.unidad_medida,
            int(rep.activo),
            rep.id,
            ),
        )
        self.conexion.commit()


#PARAMETROS DE STOCK Y ALERTAS
    def actualizar_parametros_stock(self, repuesto_id: int, stock_minimo: float, stock_maximo: Optional[float],
                                    punto_reorden: Optional[float], manual: bool = True) -> None:
        """Guarda los umbrales de un repuesto.

        Pre: los umbrales son coherentes (minimo <= punto_reorden <= maximo, ninguno
        negativo); si no, lanza RepuestoInvalidoError y NO guarda nada.
        `manual=True` (valor por defecto, el de la interfaz) marca el repuesto como
        corregido a mano: el recalculo automatico no lo va a pisar. El calculo
        automatico (ServicioParametrosStock) llama con `manual=False`.
        """
        validar_umbrales(stock_minimo, punto_reorden, stock_maximo)
        self.conexion.execute(
            """UPDATE repuestos SET stock_minimo = ?, stock_maximo = ?, punto_reorden = ?, parametros_manuales = ?
               WHERE id = ?""",
            (stock_minimo, stock_maximo, punto_reorden, int(manual), repuesto_id),
        )
        self.conexion.commit()


    def obtener_repuestos_bajo_reorden(self) -> List[Repuesto]:
        """Retorna repuestos cuyo stock actual cayo por debajo o es igual al punto de reorden"""
        filas = self.conexion.execute(
            """SELECT * FROM repuestos WHERE stock_actual <= punto_reorden AND activo = 1"""
        ).fetchall()
        return [_fila_a_repuesto(f) for f in filas]


#MOVIMIENTOS DE STOCK
    def registrar_movimiento(self, mov: MovimientoStock) -> int:
        """Registra un movimiento de ingreso, egreso o ajuste"""
        cursor = self.conexion.execute(
            """INSERT INTO movimientos_stock (repuesto_id, proveedor_id, fecha, tipo, cantidad, codigo_proveedor_raw, origen) VALUES (?,?,?,?,?,?,?)""",
            (
                mov.repuesto_id,
                mov.proveedor_id,
                mov.fecha,
                mov.tipo,
                mov.cantidad,
                mov.codigo_proveedor_raw,
                mov.origen,
            ),
        )
        self.conexion.commit()
        return cursor.lastrowid

    def obtener_movimientos(self, repuesto_id: int) -> List[MovimientoStock]:
        """Todos los movimientos de un repuesto, del mas viejo al mas nuevo.
        Es la entrada del calculo de umbrales (modules/alertas.py)."""
        filas = self.conexion.execute(
            "SELECT * FROM movimientos_stock WHERE repuesto_id = ? ORDER BY fecha, id", (repuesto_id,)
        ).fetchall()
        return [
            MovimientoStock(
                id=f["id"],
                repuesto_id=f["repuesto_id"],
                fecha=f["fecha"],
                tipo=f["tipo"],
                cantidad=f["cantidad"],
                proveedor_id=f["proveedor_id"],
                codigo_proveedor_raw=f["codigo_proveedor_raw"],
                origen=f["origen"],
            )
            for f in filas
        ]

    def obtener_periodo_movimientos(self) -> Optional[tuple]:
        """Fecha del primer y del ultimo movimiento registrado (texto ISO), o None si no hay."""
        fila = self.conexion.execute("SELECT MIN(fecha), MAX(fecha) FROM movimientos_stock").fetchone()
        if fila[0] is None:
            return None
        return fila[0], fila[1]
