"""Modulo de operaciones CRUD, gestion de inventario. 
Encapsula las operaciones de persistencia (alta, lectura, modificacion y baja) sobre la BD SQLite para las entidades Repuesto, Proveedor y Movimientos de Stock"""

import sqlite3
from typing import List, Opcional
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
            self.conexion.commit()
            return cursor.lastowid
        )

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