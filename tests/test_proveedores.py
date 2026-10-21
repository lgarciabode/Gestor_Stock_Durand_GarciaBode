"""Pruebas de proveedores (Paso 13).

ConsultaProveedores y ServicioProveedores sobre una base SQLite temporal, y
una prueba con el Excel historico real.

unittest puro, patron AAA (Arrange, Act, Assert).
"""
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.alertas import MotorAlertas, reglas_por_defecto
from modules.base_datos import crear_esquema, obtener_conexion
from modules.carga_historico_datos import cargar_historico
from modules.crud import GestorInventarioBD, RepositorioAlertas
from modules.modelos import Categoria, Marca, MovimientoStock, Proveedor, Repuesto
from modules.movimientos import ServicioMovimientos
from modules.proveedores import (
    ConsultaProveedores,
    ProveedorInvalidoError,
    ProveedorNoEncontradoError,
    ServicioProveedores,
)

RUTA_EXCEL = Path(__file__).resolve().parent.parent / "data" / "base_stock_taller.xlsx"


class BaseProveedores(unittest.TestCase):
    """Iriondo: 3 compras (2 dias) de rodamientos; ED-MA: 1 compra de cadena en cm; Nuevo: ninguna."""

    def setUp(self):
        self.directorio = tempfile.TemporaryDirectory()
        self.conexion = obtener_conexion(str(Path(self.directorio.name) / "test.sqlite3"))
        crear_esquema(self.conexion)
        self.gestor = GestorInventarioBD(self.conexion)
        zkl = self.gestor.crear_marca(Marca(id=None, nombre="ZKL"))
        rod = self.gestor.crear_categoria(Categoria(id=None, nombre="RODAMIENTO"))
        self.r6204 = self.gestor.crear_repuestos(Repuesto(id=None, codigo="6204 2RS", marca_id=zkl, categoria_id=rod))
        self.r6205 = self.gestor.crear_repuestos(Repuesto(id=None, codigo="6205 2RS", marca_id=zkl, categoria_id=rod))
        self.cadena = self.gestor.crear_repuestos(Repuesto(id=None, codigo="CAD-40", marca_id=zkl, categoria_id=rod,
                                                           unidad_medida="cm"))
        self.iriondo = self.gestor.crear_proveedor(Proveedor(id=None, nombre="Iriondo"))
        self.edma = self.gestor.crear_proveedor(Proveedor(id=None, nombre="ED-MA"))
        self.nuevo = self.gestor.crear_proveedor(Proveedor(id=None, nombre="Nuevo"))
        for rid, fecha, cantidad, prov in ((self.r6204, "2026-08-01", 10, self.iriondo),
                                           (self.r6205, "2026-08-01", 4, self.iriondo),
                                           (self.r6204, "2026-09-15", 5, self.iriondo),
                                           (self.cadena, "2026-09-20", 300.5, self.edma)):
            self.gestor.registrar_movimiento(MovimientoStock(id=None, repuesto_id=rid, fecha=fecha, tipo="INGRESO",
                                                             cantidad=cantidad, proveedor_id=prov))
        self.consulta = ConsultaProveedores(self.conexion)
        self.servicio = ServicioProveedores(self.gestor)

    def tearDown(self):
        self.conexion.close()
        self.directorio.cleanup()


class PruebaConsulta(BaseProveedores):

    def test_resumen_ordenado_de_al_que_mas_se_le_compra(self):
        resumen = self.consulta.resumen()
        self.assertEqual([r.proveedor.nombre for r in resumen], ["Iriondo", "ED-MA", "Nuevo"])

    def test_cuenta_compras_por_dia_y_no_mezcla_unidades_con_cm(self):
        iriondo, edma, nuevo = self.consulta.resumen()
        self.assertEqual((iriondo.compras, iriondo.lineas, iriondo.repuestos, iriondo.unidades), (2, 3, 2, 19))
        self.assertEqual((edma.unidades, edma.centimetros), (0, 300.5))
        self.assertEqual((nuevo.compras, nuevo.ultima), (0, None))

    def test_dias_desde_la_ultima_compra(self):
        iriondo = self.consulta.resumen()[0]
        self.assertEqual(iriondo.dias_desde_ultima(date(2026, 10, 15)), 30)
        self.assertIsNone(self.consulta.resumen()[2].dias_desde_ultima(date(2026, 10, 15)))

    def test_repuestos_comprados_a_un_proveedor(self):
        compras = self.consulta.repuestos_comprados(self.iriondo)
        self.assertEqual([(c.codigo, c.veces, c.cantidad, c.ultima) for c in compras],
                         [("6204 2RS", 2, 15, "2026-09-15"), ("6205 2RS", 1, 4, "2026-08-01")])

    def test_una_compra_anulada_no_cuenta(self):
        # Arrange: se anula la compra de 6205
        motor = MotorAlertas(reglas_por_defecto(), RepositorioAlertas(self.conexion))
        compra = self.conexion.execute("SELECT id FROM movimientos_stock WHERE repuesto_id = ?", (self.r6205,)).fetchone()[0]
        ServicioMovimientos(self.gestor, motor, hoy=lambda: "2026-10-01").anular(compra)

        # Act
        iriondo = self.consulta.resumen()[0]

        # Assert
        self.assertEqual((iriondo.lineas, iriondo.repuestos), (2, 1))

    def test_los_inactivos_solo_si_se_piden(self):
        self.servicio.desactivar(self.nuevo)
        self.assertEqual(len(self.consulta.resumen()), 2)
        self.assertEqual(len(self.consulta.resumen(incluir_inactivos=True)), 3)


class PruebaServicio(BaseProveedores):

    def test_crear_con_contacto(self):
        nuevo = self.servicio.crear("  Rulemanes Paraná ", "Juan", "343 4000000", "ventas@rulemanes.com.ar")
        p = self.servicio.obtener(nuevo)
        self.assertEqual((p.nombre, p.contacto, p.email, p.activo), ("Rulemanes Paraná", "Juan", "ventas@rulemanes.com.ar", True))

    def test_nombre_obligatorio_y_sin_repetir(self):
        with self.assertRaises(ProveedorInvalidoError):
            self.servicio.crear("   ")
        with self.assertRaises(ProveedorInvalidoError):
            self.servicio.crear("iriondo")  # ya existe "Iriondo"

    def test_email_mal_escrito(self):
        with self.assertRaises(ProveedorInvalidoError):
            self.servicio.crear("Otro", email="ventas.sin.arroba")

    def test_corregir_conserva_el_nombre_propio_y_el_estado(self):
        self.servicio.desactivar(self.edma)
        self.servicio.corregir(self.edma, "ED-MA", telefono="0343 155")  # mismo nombre: no es "repetido"
        p = self.servicio.obtener(self.edma)
        self.assertEqual((p.telefono, p.activo), ("0343 155", False))

    def test_desactivar_y_activar(self):
        self.servicio.desactivar(self.iriondo)
        self.assertNotIn(self.iriondo, [p.id for p in self.gestor.obtener_proveedores()])
        self.servicio.activar(self.iriondo)
        self.assertIn(self.iriondo, [p.id for p in self.gestor.obtener_proveedores()])

    def test_proveedor_inexistente(self):
        with self.assertRaises(ProveedorNoEncontradoError):
            self.servicio.obtener(999)


@unittest.skipUnless(RUTA_EXCEL.exists(), "No está el Excel histórico en data/")
class PruebaProveedoresReales(unittest.TestCase):

    def test_iriondo_es_el_proveedor_principal(self):
        with tempfile.TemporaryDirectory() as directorio:
            conexion = obtener_conexion(str(Path(directorio) / "test.sqlite3"))
            crear_esquema(conexion)
            cargar_historico(conexion, str(RUTA_EXCEL))
            conexion.commit()

            resumen = ConsultaProveedores(conexion).resumen()

            self.assertEqual(resumen[0].proveedor.nombre, "Rodamientos Iriondo S.R.L.")
            self.assertEqual((resumen[0].compras, resumen[0].lineas), (20, 193))
            self.assertEqual(sum(r.lineas for r in resumen), 213)
            conexion.close()


if __name__ == "__main__":
    unittest.main()
