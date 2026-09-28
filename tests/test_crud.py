"""Pruebas unitarias de GestorInventarioBD (modules/crud.py).

Usan unicamente unittest (biblioteca estandar de Python), sin fixtures de
pytest ni monkeypatch: cada test crea su propia base SQLite temporal en
setUp y la descarta en tearDown, para que las pruebas sean independientes
entre si y no dependan de un orden de ejecucion.
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.base_datos import crear_esquema, obtener_conexion
from modules.crud import GestorInventarioBD
from modules.modelos import MovimientoStock, Proveedor, Repuesto


class PruebaGestorInventarioBD(unittest.TestCase):
    def setUp(self):
        self.directorio_temporal = tempfile.TemporaryDirectory()
        ruta_bd = str(Path(self.directorio_temporal.name) / "test.sqlite3")
        self.conexion = obtener_conexion(ruta_bd)
        crear_esquema(self.conexion)
        self.gestor = GestorInventarioBD(self.conexion)

    def tearDown(self):
        self.conexion.close()
        self.directorio_temporal.cleanup()

    # --- Proveedores ---------------------------------------------------

    def test_crear_proveedor_retorna_id_y_persiste(self):
        proveedor_id = self.gestor.crear_proveedor(
            Proveedor(id=None, nombre="Rodamientos Iriondo S.R.L.", contacto="Juan")
        )
        self.assertIsInstance(proveedor_id, int)
        proveedores = self.gestor.obtener_proveedores()
        self.assertEqual(len(proveedores), 1)
        self.assertEqual(proveedores[0].nombre, "Rodamientos Iriondo S.R.L.")
        self.assertEqual(proveedores[0].contacto, "Juan")

    def test_obtener_proveedores_filtra_por_activo(self):
        id_activo = self.gestor.crear_proveedor(Proveedor(id=None, nombre="Proveedor Activo"))
        id_inactivo = self.gestor.crear_proveedor(Proveedor(id=None, nombre="Proveedor Inactivo"))
        self.gestor.desactivar_proveedor(id_inactivo)

        self.assertEqual(len(self.gestor.obtener_proveedores(solo_activos=True)), 1)
        self.assertEqual(len(self.gestor.obtener_proveedores(solo_activos=False)), 2)
        self.assertEqual(self.gestor.obtener_proveedores(solo_activos=True)[0].id, id_activo)

    def test_actualizar_proveedor_modifica_datos(self):
        proveedor_id = self.gestor.crear_proveedor(Proveedor(id=None, nombre="Nombre Viejo"))
        proveedor = self.gestor.obtener_proveedores()[0]
        proveedor.nombre = "Nombre Nuevo"
        proveedor.telefono = "3435551234"
        proveedor.email = "contacto@proveedor.com"

        self.gestor.actualizar_proveedor(proveedor)

        actualizado = self.gestor.obtener_proveedores()[0]
        self.assertEqual(actualizado.id, proveedor_id)
        self.assertEqual(actualizado.nombre, "Nombre Nuevo")
        self.assertEqual(actualizado.telefono, "3435551234")
        self.assertEqual(actualizado.email, "contacto@proveedor.com")

    def test_desactivar_proveedor_marca_inactivo(self):
        proveedor_id = self.gestor.crear_proveedor(Proveedor(id=None, nombre="Proveedor X"))
        self.gestor.desactivar_proveedor(proveedor_id)
        self.assertEqual(self.gestor.obtener_proveedores(solo_activos=True), [])
        todos = self.gestor.obtener_proveedores(solo_activos=False)
        self.assertEqual(len(todos), 1)
        self.assertFalse(todos[0].activo)

    # --- Repuestos -------------------------------------------------------

    def test_crear_repuesto_retorna_id_y_persiste(self):
        repuesto_id = self.gestor.crear_repuestos(
            Repuesto(id=None, descripcion_normalizada="RODAMIENTO", stock_actual=5.0)
        )
        self.assertIsInstance(repuesto_id, int)
        repuesto = self.gestor.obtener_repuesto_id(repuesto_id)
        self.assertEqual(repuesto.descripcion_normalizada, "RODAMIENTO")
        self.assertEqual(repuesto.stock_actual, 5.0)

    def test_obtener_repuestos_filtra_por_activo(self):
        id_activo = self.gestor.crear_repuestos(Repuesto(id=None, descripcion_normalizada="A"))
        id_inactivo = self.gestor.crear_repuestos(Repuesto(id=None, descripcion_normalizada="B"))
        repuesto_inactivo = self.gestor.obtener_repuesto_id(id_inactivo)
        repuesto_inactivo.activo = False
        self.gestor.actualizar_repuesto(repuesto_inactivo)

        self.assertEqual(len(self.gestor.obtener_repuestos(solo_activos=True)), 1)
        self.assertEqual(len(self.gestor.obtener_repuestos(solo_activos=False)), 2)
        self.assertEqual(self.gestor.obtener_repuestos(solo_activos=True)[0].id, id_activo)

    def test_obtener_repuesto_id_existente_y_inexistente(self):
        repuesto_id = self.gestor.crear_repuestos(
            Repuesto(id=None, descripcion_normalizada="TUBO")
        )
        self.assertIsNotNone(self.gestor.obtener_repuesto_id(repuesto_id))
        self.assertIsNone(self.gestor.obtener_repuesto_id(repuesto_id + 999))

    def test_actualizar_repuesto_modifica_solo_el_indicado(self):
        """Regresion del bug: al UPDATE le faltaba WHERE id = ?, lo que
        hubiera modificado todas las filas de la tabla."""
        id_uno = self.gestor.crear_repuestos(Repuesto(id=None, descripcion_normalizada="Original A"))
        id_dos = self.gestor.crear_repuestos(Repuesto(id=None, descripcion_normalizada="Original B"))

        repuesto_uno = self.gestor.obtener_repuesto_id(id_uno)
        repuesto_uno.descripcion_normalizada = "Modificado A"
        self.gestor.actualizar_repuesto(repuesto_uno)

        self.assertEqual(self.gestor.obtener_repuesto_id(id_uno).descripcion_normalizada, "Modificado A")
        self.assertEqual(self.gestor.obtener_repuesto_id(id_dos).descripcion_normalizada, "Original B")

    def test_actualizar_parametros_stock(self):
        repuesto_id = self.gestor.crear_repuestos(Repuesto(id=None, descripcion_normalizada="C"))
        self.gestor.actualizar_parametros_stock(
            repuesto_id, stock_minimo=2.0, stock_maximo=50.0, punto_reorden=5.0
        )
        repuesto = self.gestor.obtener_repuesto_id(repuesto_id)
        self.assertEqual(repuesto.stock_minimo, 2.0)
        self.assertEqual(repuesto.stock_maximo, 50.0)
        self.assertEqual(repuesto.punto_reorden, 5.0)

    def test_obtener_repuestos_bajo_reorden(self):
        id_bajo = self.gestor.crear_repuestos(
            Repuesto(id=None, descripcion_normalizada="Bajo stock", stock_actual=1.0, punto_reorden=3.0)
        )
        self.gestor.crear_repuestos(
            Repuesto(id=None, descripcion_normalizada="Stock ok", stock_actual=10.0, punto_reorden=3.0)
        )
        bajo_reorden = self.gestor.obtener_repuestos_bajo_reorden()
        self.assertEqual(len(bajo_reorden), 1)
        self.assertEqual(bajo_reorden[0].id, id_bajo)

    # --- Movimientos de stock --------------------------------------------

    def test_registrar_movimiento_actualiza_stock_via_trigger(self):
        repuesto_id = self.gestor.crear_repuestos(
            Repuesto(id=None, descripcion_normalizada="Rodamiento 6205", stock_actual=0.0)
        )

        self.gestor.registrar_movimiento(
            MovimientoStock(id=None, repuesto_id=repuesto_id, fecha="2026-01-10", tipo="INGRESO", cantidad=10.0)
        )
        self.assertEqual(self.gestor.obtener_repuesto_id(repuesto_id).stock_actual, 10.0)

        self.gestor.registrar_movimiento(
            MovimientoStock(id=None, repuesto_id=repuesto_id, fecha="2026-01-15", tipo="EGRESO", cantidad=3.0)
        )
        self.assertEqual(self.gestor.obtener_repuesto_id(repuesto_id).stock_actual, 7.0)


if __name__ == "__main__":
    unittest.main()
