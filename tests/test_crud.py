
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.base_datos import crear_esquema, obtener_conexion
from modules.crud import GestorInventarioBD
import sqlite3

from modules.modelos import (Categoria, Marca, MovimientoStock, Proveedor, Repuesto, RepuestoInvalidoError,
                             StockNegativoError)


class PruebaGestorInventarioBD(unittest.TestCase):
    def setUp(self):
        # Arrange (comun a todos los tests): SUT sobre una base SQLite
        # temporal y aislada, con el esquema real ya creado.
        self.directorio_temporal = tempfile.TemporaryDirectory()
        ruta_bd = str(Path(self.directorio_temporal.name) / "test.sqlite3")
        self.conexion = obtener_conexion(ruta_bd)
        crear_esquema(self.conexion)
        self.gestor = GestorInventarioBD(self.conexion)
        # Todo repuesto necesita una marca y una categoria (NOT NULL)
        self.marca_id = self.gestor.crear_marca(Marca(id=None, nombre="ZKL"))
        self.categoria_id = self.gestor.crear_categoria(Categoria(id=None, nombre="RODAMIENTO"))

    def tearDown(self):
        self.conexion.close()
        self.directorio_temporal.cleanup()

    # --- Proveedores ---------------------------------------------------

    def test_crear_proveedor_retorna_id_y_persiste(self):
        # Arrange
        proveedor = Proveedor(id=None, nombre="Rodamientos Iriondo S.R.L.", contacto="Juan")

        # Act
        proveedor_id = self.gestor.crear_proveedor(proveedor)

        # Assert
        self.assertIsInstance(proveedor_id, int)
        proveedores = self.gestor.obtener_proveedores()
        self.assertEqual(len(proveedores), 1)
        self.assertEqual(proveedores[0].nombre, "Rodamientos Iriondo S.R.L.")
        self.assertEqual(proveedores[0].contacto, "Juan")

    def test_obtener_proveedores_filtra_por_activo(self):
        # Arrange
        id_activo = self.gestor.crear_proveedor(Proveedor(id=None, nombre="Proveedor Activo"))
        id_inactivo = self.gestor.crear_proveedor(Proveedor(id=None, nombre="Proveedor Inactivo"))
        self.gestor.desactivar_proveedor(id_inactivo)

        # Act
        solo_activos = self.gestor.obtener_proveedores(solo_activos=True)
        todos = self.gestor.obtener_proveedores(solo_activos=False)

        # Assert
        self.assertEqual(len(solo_activos), 1)
        self.assertEqual(len(todos), 2)
        self.assertEqual(solo_activos[0].id, id_activo)

    def test_actualizar_proveedor_modifica_datos(self):
        # Arrange
        proveedor_id = self.gestor.crear_proveedor(Proveedor(id=None, nombre="Nombre Viejo"))
        proveedor = self.gestor.obtener_proveedores()[0]
        proveedor.nombre = "Nombre Nuevo"
        proveedor.telefono = "3435551234"
        proveedor.email = "contacto@proveedor.com"

        # Act
        self.gestor.actualizar_proveedor(proveedor)

        # Assert
        actualizado = self.gestor.obtener_proveedores()[0]
        self.assertEqual(actualizado.id, proveedor_id)
        self.assertEqual(actualizado.nombre, "Nombre Nuevo")
        self.assertEqual(actualizado.telefono, "3435551234")
        self.assertEqual(actualizado.email, "contacto@proveedor.com")

    def test_desactivar_proveedor_marca_inactivo(self):
        # Arrange
        proveedor_id = self.gestor.crear_proveedor(Proveedor(id=None, nombre="Proveedor X"))

        # Act
        self.gestor.desactivar_proveedor(proveedor_id)

        # Assert
        self.assertEqual(self.gestor.obtener_proveedores(solo_activos=True), [])
        todos = self.gestor.obtener_proveedores(solo_activos=False)
        self.assertEqual(len(todos), 1)
        self.assertFalse(todos[0].activo)

    # --- Repuestos -------------------------------------------------------

    def test_crear_repuesto_retorna_id_y_persiste(self):
        # Arrange
        repuesto = Repuesto(id=None, marca_id=self.marca_id, categoria_id=self.categoria_id, codigo="RODAMIENTO", stock_actual=5.0)

        # Act
        repuesto_id = self.gestor.crear_repuestos(repuesto)

        # Assert
        self.assertIsInstance(repuesto_id, int)
        guardado = self.gestor.obtener_repuesto_id(repuesto_id)
        self.assertEqual(guardado.codigo, "RODAMIENTO")
        self.assertEqual(guardado.stock_actual, 5.0)

    def test_obtener_repuestos_filtra_por_activo(self):
        # Arrange
        id_activo = self.gestor.crear_repuestos(Repuesto(id=None, marca_id=self.marca_id, categoria_id=self.categoria_id, codigo="A"))
        id_inactivo = self.gestor.crear_repuestos(Repuesto(id=None, marca_id=self.marca_id, categoria_id=self.categoria_id, codigo="B"))
        repuesto_inactivo = self.gestor.obtener_repuesto_id(id_inactivo)
        repuesto_inactivo.activo = False
        self.gestor.actualizar_repuesto(repuesto_inactivo)

        # Act
        solo_activos = self.gestor.obtener_repuestos(solo_activos=True)
        todos = self.gestor.obtener_repuestos(solo_activos=False)

        # Assert
        self.assertEqual(len(solo_activos), 1)
        self.assertEqual(len(todos), 2)
        self.assertEqual(solo_activos[0].id, id_activo)

    def test_obtener_repuesto_id_existente_y_inexistente(self):
        # Arrange
        repuesto_id = self.gestor.crear_repuestos(Repuesto(id=None, marca_id=self.marca_id, categoria_id=self.categoria_id, codigo="TUBO"))

        # Act
        encontrado = self.gestor.obtener_repuesto_id(repuesto_id)
        no_encontrado = self.gestor.obtener_repuesto_id(repuesto_id + 999)

        # Assert
        self.assertIsNotNone(encontrado)
        self.assertIsNone(no_encontrado)

    def test_actualizar_repuesto_modifica_solo_el_indicado(self):
        """Regresion del bug: al UPDATE le faltaba WHERE id = ?, lo que
        hubiera modificado todas las filas de la tabla."""
        # Arrange
        id_uno = self.gestor.crear_repuestos(Repuesto(id=None, marca_id=self.marca_id, categoria_id=self.categoria_id, codigo="Original A"))
        id_dos = self.gestor.crear_repuestos(Repuesto(id=None, marca_id=self.marca_id, categoria_id=self.categoria_id, codigo="Original B"))
        repuesto_uno = self.gestor.obtener_repuesto_id(id_uno)
        repuesto_uno.codigo = "Modificado A"

        # Act
        self.gestor.actualizar_repuesto(repuesto_uno)

        # Assert
        self.assertEqual(self.gestor.obtener_repuesto_id(id_uno).codigo, "Modificado A")
        self.assertEqual(self.gestor.obtener_repuesto_id(id_dos).codigo, "Original B")

    def test_actualizar_parametros_stock(self):
        # Arrange
        repuesto_id = self.gestor.crear_repuestos(Repuesto(id=None, marca_id=self.marca_id, categoria_id=self.categoria_id, codigo="C"))

        # Act
        self.gestor.actualizar_parametros_stock(
            repuesto_id, stock_minimo=2.0, stock_maximo=50.0, punto_reorden=5.0
        )

        # Assert
        repuesto = self.gestor.obtener_repuesto_id(repuesto_id)
        self.assertEqual(repuesto.stock_minimo, 2.0)
        self.assertEqual(repuesto.stock_maximo, 50.0)
        self.assertEqual(repuesto.punto_reorden, 5.0)

    def test_obtener_repuestos_bajo_reorden(self):
        # Arrange
        id_bajo = self.gestor.crear_repuestos(
            Repuesto(id=None, marca_id=self.marca_id, categoria_id=self.categoria_id, codigo="Bajo stock", stock_actual=1.0, punto_reorden=3.0)
        )
        self.gestor.crear_repuestos(
            Repuesto(id=None, marca_id=self.marca_id, categoria_id=self.categoria_id, codigo="Stock ok", stock_actual=10.0, punto_reorden=3.0)
        )

        # Act
        bajo_reorden = self.gestor.obtener_repuestos_bajo_reorden()

        # Assert
        self.assertEqual(len(bajo_reorden), 1)
        self.assertEqual(bajo_reorden[0].id, id_bajo)

    # --- Marcas y categorias ---------------------------------------------

    def test_crear_y_obtener_categorias(self):
        # Act
        self.gestor.crear_categoria(Categoria(id=None, nombre="HORQUILLA"))

        # Assert (la de setUp + la nueva, ordenadas por nombre)
        nombres = [c.nombre for c in self.gestor.obtener_categorias()]
        self.assertEqual(nombres, ["HORQUILLA", "RODAMIENTO"])

    def test_crear_categoria_repetida_falla(self):
        # Act / Assert: la lista es cerrada, no puede haber dos con el mismo nombre
        with self.assertRaises(sqlite3.IntegrityError):
            self.gestor.crear_categoria(Categoria(id=None, nombre="RODAMIENTO"))

    # --- Identidad del repuesto (marca + codigo) ---------------------------

    def test_no_permite_repetir_marca_y_codigo(self):
        # Arrange
        self.gestor.crear_repuestos(
            Repuesto(id=None, marca_id=self.marca_id, categoria_id=self.categoria_id, codigo="6204 2RS")
        )

        # Act / Assert
        with self.assertRaises(sqlite3.IntegrityError):
            self.gestor.crear_repuestos(
                Repuesto(id=None, marca_id=self.marca_id, categoria_id=self.categoria_id, codigo="6204 2RS")
            )

    def test_mismo_codigo_de_otra_marca_es_otro_repuesto(self):
        # Arrange
        otra_marca_id = self.gestor.crear_marca(Marca(id=None, nombre="GKL"))

        # Act
        id_zkl = self.gestor.crear_repuestos(
            Repuesto(id=None, marca_id=self.marca_id, categoria_id=self.categoria_id, codigo="UC 207")
        )
        id_gkl = self.gestor.crear_repuestos(
            Repuesto(id=None, marca_id=otra_marca_id, categoria_id=self.categoria_id, codigo="UC 207")
        )

        # Assert
        self.assertNotEqual(id_zkl, id_gkl)
        self.assertEqual(self.gestor.obtener_repuesto_por_codigo(otra_marca_id, "UC 207").id, id_gkl)

    def test_unidad_de_medida_solo_unidad_o_cm(self):
        # Arrange
        en_cm = Repuesto(id=None, marca_id=self.marca_id, categoria_id=self.categoria_id,
                         codigo="CADENA-1", unidad_medida="cm")

        # Act
        id_cm = self.gestor.crear_repuestos(en_cm)

        # Assert: "cm" se guarda; "kg" lo rechaza el propio Repuesto al crearse
        # (invariante), antes de llegar a la base.
        self.assertEqual(self.gestor.obtener_repuesto_id(id_cm).unidad_medida, "cm")
        with self.assertRaises(RepuestoInvalidoError):
            Repuesto(id=None, marca_id=self.marca_id, categoria_id=self.categoria_id,
                     codigo="CADENA-2", unidad_medida="kg")

    def test_actualizar_parametros_rechaza_umbrales_incoherentes(self):
        # Arrange
        repuesto_id = self.gestor.crear_repuestos(
            Repuesto(id=None, marca_id=self.marca_id, categoria_id=self.categoria_id, codigo="X1")
        )

        # Act / Assert: reorden (2) menor que el minimo (5) -> error y no se guarda nada
        with self.assertRaises(RepuestoInvalidoError):
            self.gestor.actualizar_parametros_stock(repuesto_id, stock_minimo=5.0,
                                                    stock_maximo=50.0, punto_reorden=2.0)
        self.assertIsNone(self.gestor.obtener_repuesto_id(repuesto_id).punto_reorden)

    def test_actualizar_parametros_marca_si_son_manuales(self):
        # Arrange
        repuesto_id = self.gestor.crear_repuestos(
            Repuesto(id=None, marca_id=self.marca_id, categoria_id=self.categoria_id, codigo="X2")
        )

        # Act: la interfaz (por defecto) los marca como manuales; el calculo automatico no
        self.gestor.actualizar_parametros_stock(repuesto_id, 2.0, 18.0, 4.0)
        manual = self.gestor.obtener_repuesto_id(repuesto_id).parametros_manuales
        self.gestor.actualizar_parametros_stock(repuesto_id, 2.0, 18.0, 4.0, manual=False)
        automatico = self.gestor.obtener_repuesto_id(repuesto_id).parametros_manuales

        # Assert
        self.assertTrue(manual)
        self.assertFalse(automatico)

    # --- Movimientos de stock --------------------------------------------

    def test_registrar_movimiento_actualiza_stock_via_trigger(self):
        # Arrange
        repuesto_id = self.gestor.crear_repuestos(
            Repuesto(id=None, marca_id=self.marca_id, categoria_id=self.categoria_id, codigo="Rodamiento 6205", stock_actual=0.0)
        )

        # Act
        self.gestor.registrar_movimiento(
            MovimientoStock(id=None, repuesto_id=repuesto_id, fecha="2026-01-10", tipo="INGRESO", cantidad=10.0)
        )
        self.gestor.registrar_movimiento(
            MovimientoStock(id=None, repuesto_id=repuesto_id, fecha="2026-01-15", tipo="EGRESO", cantidad=3.0)
        )

        # Assert
        self.assertEqual(self.gestor.obtener_repuesto_id(repuesto_id).stock_actual, 7.0)

    # --- Regla: el stock nunca queda negativo ------------------------------

    def repuesto_con_stock(self, cantidad):
        repuesto_id = self.gestor.crear_repuestos(
            Repuesto(id=None, marca_id=self.marca_id, categoria_id=self.categoria_id, codigo="6206")
        )
        self.gestor.registrar_movimiento(
            MovimientoStock(id=None, repuesto_id=repuesto_id, fecha="2026-01-10", tipo="INGRESO", cantidad=cantidad)
        )
        return repuesto_id

    def test_el_gestor_rechaza_un_egreso_que_deja_stock_negativo(self):
        # Arrange
        repuesto_id = self.repuesto_con_stock(2)

        # Act / Assert
        with self.assertRaises(StockNegativoError) as contexto:
            self.gestor.registrar_movimiento(
                MovimientoStock(id=None, repuesto_id=repuesto_id, fecha="2026-01-15", tipo="EGRESO", cantidad=3)
            )
        self.assertIn("Operación inválida", str(contexto.exception))
        self.assertEqual(self.gestor.obtener_repuesto_id(repuesto_id).stock_actual, 2)  # no se guardó nada
        self.assertEqual(len(self.gestor.obtener_movimientos(repuesto_id)), 1)

    def test_la_base_rechaza_un_insert_directo_que_deja_stock_negativo(self):
        # Arrange: alguien se saltea el código y escribe directo en la base
        repuesto_id = self.repuesto_con_stock(2)

        # Act / Assert: el trigger de SQLite lo frena igual
        with self.assertRaises(sqlite3.IntegrityError) as contexto:
            self.conexion.execute(
                "INSERT INTO movimientos_stock (repuesto_id, fecha, tipo, cantidad) VALUES (?, '2026-01-15', 'AJUSTE', -5)",
                (repuesto_id,),
            )
        self.assertIn("Operación inválida", str(contexto.exception))
        self.assertEqual(self.gestor.obtener_repuesto_id(repuesto_id).stock_actual, 2)


if __name__ == "__main__":
    unittest.main()
