"""Modulo de operaciones CRUD, gestion de inventario. 
Encapsula las operaciones de persistencia (alta, lectura, modificacion y baja) sobre la BD SQLite para las entidades Repuesto, Proveedor y Movimientos de Stock"""

import sqlite3
from typing import List, Optional
from modelos import Categoria, Marca, MovimientoStock, Proveedor, Repuesto

class GestorInventarioBD:
    """"Clase de servicio que maneja las operaciones CRUD sobre la BD"""
    def __init__(self, conexion: sqlite3.Connection):
        self.conexion = conexion

#PROVEEDORES
    def crear_proveedor(self, prov: Proveedor) -> int:
        """Inserta un nuevo proveedor en la BS y sretorna su ID asimando"""
        cursor = self.conexion.execute(
            """INSERT INTO proveedores (nombre, contacto, telefono, email, activo) VALUES (?, ?, ?, ?, ?)""", (prov.nombre, prov.contacto, prov.telefono, prov.email, int(prov.activo)),
        )
        self.conexion.commit()
        return cursor.lastowid

    def obtener_proveedores(self, solo_activos: bool = True) -> List[Proveedor]:
        """Obtiene la lista de todos los proveedores regitstrados."""
        query = "SELECT * FROM proveedores"
        if solo_activos:
            query += " WHERE activo = 1"
        cursor= self.conexion.execure(query)
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
        """Actualiza los datos de un provrrdor existente."""
        self.conexion.execute(
            """UPDATE proveedores
            SET nombre = ?, contacto = ?, telefono = ?. email = ?, activo = ?WHERE id = ?""",
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


#REPUESTOS
    def crear_repuestos(self, rep: Repuesto) -> int:
        """Crea un nuevo repuesto en el catalogo"""
        cursor = self.conexion.execute(
            """INSERT INTO repuestos (descripcion_normalizada, marca_id, categoria_id, especificaciones,
                unidad_medida, stock_minimo, stock_maximo, punto_reorden, stock_actual, activo)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
            (
            rep.descripcion_normalizada,
            rep.marca_id,
            rep.categoria_id,
            rep.especificaciones,
            rep.unidad_medida,
            rep.stock_minimo,
            rep.stock_maximo,
            rep.punto_reorden,
            rep.stock_actual,
            int(rep.activo), 
            ),
        )
        self.conexion.commit()
        return cursor.lastrowid

    def obtener_repuestos(self, solo_activos: bool = True) -> List[Repuesto]:
        """Obtiene el catalogo de repuestos con su stock actual"""
        query = "SELECT * FROM repuestos"
        if solo_activos:
            query += " WHERE activo = 1"
        cursor = self.conexion.execute(query)
        filas = cursor.fetchall()
        return [
            Repuesto(
                id = f["id"],
                descripcion_normalizada = f["descripcion_normalizada"],
                marca_id = f["marca_id"],
                categoria_id = f["categoria_id"],
                especificaciones = f["especificaciones"],
                unidad_medida = f["unidad_medida"],
                stock_minimo = f["stock_minimo"],
                stock_maximo = f["stock_maximo"],
                punto_reorden = f["punto_reorden"],
                stock_actual = f["stock_actual"],
                activo = bool(f["activo"]),
            )
            for f in filas
        ]

    def obtener_repuesto_id(self, repuesto_id: int) -> Optional[Repuesto]:
        """Busca un repuesto por su PK"""
        cursor = self.conexion.execute(
            "SELECT * FROM repuestos WHERE id = ?", (repuesto_id,)
        )
        f = cursor.fetchone()
        if not f:
            return None
        return Repuesto(
            id = f["id"],
            descripcion_normalizada = f["descripcion_normalizada"],
            marca_id = f["marca_id"],
            categoria_id = f["categoria_id"],
            especificaciones = f["especificaciones"],
            unidad_medida = f["unidad_medida"],
            stock_minimo = f["stock_minimo"],
            stock_maximo = f["stock_maximo"],
            punto_reorden = f["punto_reorden"],
            stock_actual = f["stock_actual"],
            activo = bool(f["activo"]),
            )

    def actualizar_repuesto(self, rep: Repuesto) -> None:
        """Actualiza la informacin de un repuesto"""
        self.conexion.execute(
            """UPDATE repuestos 
            SET descripcion_normalizada = ?, marca_id = ?, categoria_id = ?, especificaciones = ?, unidad_medida = ?, activo = ?""",
            (
            rep.descripcion_normalizada,
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
    def actualizar_parametros_stock(self, repuesto_id: int, stock_minimo: float, stock_maximo: Optional[float], punto_reorden: Optional[float],) -> None:
        """Permite ajustar los umbrales de reorden"""
        self.conexion.execute(
            """UPDATE repuestos SET stock_minimo = ?, stock_maximo = ?, punto_reorden = ? WHERE id = ?""", (stock_minimo, stock_maximo, punto_reorden, repuesto_id),
        )
        self.conexion.commit()


    def obtener_repuestos_bajo_reorden(self) -> List[Repuesto]:
        """Retorna repuestos cuyo stock actual cayo por debajo o es igual al punto de reorden"""
        cursor = self.conexion.execute(
            """SELECT * FROM repuestos WHERE stock_actual <= punto_reorden AND activo = 1"""
        )
        filas = cursor.fetchall()
        return [
            Repuesto(
                id=f["id"],
                descripcion_normalizada=f["descripcion_normalizada"],
                marca_id=f["marca_id"],
                categoria_id=f["categoria_id"],
                especificaciones=f["especificaciones"],
                unidad_medida=f["unidad_medida"],
                stock_minimo=f["stock_minimo"],
                stock_maximo=f["stock_maximo"],
                punto_reorden=f["punto_reorden"],
                stock_actual=f["stock_actual"],
                activo=bool(f["activo"]),
            )
            for f in filas
        ]

    