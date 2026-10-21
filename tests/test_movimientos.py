"""Pruebas del registro de movimientos (Paso 9 del modulo de alertas).

ServicioMovimientos valida (precondiciones), guarda y revisa las alertas del
repuesto movido. Base SQLite temporal y fecha fija ("hoy") para que las
pruebas sean deterministas.

unittest puro, patron AAA (Arrange, Act, Assert).
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.alertas import MotorAlertas, reglas_por_defecto
from modules.base_datos import crear_esquema, obtener_conexion
from modules.crud import GestorInventarioBD, RepositorioAlertas
from modules.modelos import Categoria, Marca, Proveedor, Repuesto
from modules.movimientos import MovimientoInvalidoError, ServicioMovimientos

HOY = "2026-10-20"


class BaseMovimientos(unittest.TestCase):
    """Un rodamiento con umbrales 2 / 4 / 18 y 10 en stock; una cadena en cm."""

    def setUp(self):
        self.directorio = tempfile.TemporaryDirectory()
        self.conexion = obtener_conexion(str(Path(self.directorio.name) / "test.sqlite3"))
        crear_esquema(self.conexion)
        self.gestor = GestorInventarioBD(self.conexion)
        zkl = self.gestor.crear_marca(Marca(id=None, nombre="ZKL"))
        rod = self.gestor.crear_categoria(Categoria(id=None, nombre="RODAMIENTO"))
        self.rod_id = self.gestor.crear_repuestos(Repuesto(id=None, codigo="6204 2RS", marca_id=zkl, categoria_id=rod))
        self.cadena_id = self.gestor.crear_repuestos(
            Repuesto(id=None, codigo="CAD-40", marca_id=zkl, categoria_id=rod, unidad_medida="cm"))
        self.gestor.actualizar_parametros_stock(self.rod_id, stock_minimo=2, stock_maximo=18, punto_reorden=4)
        self.prov_id = self.gestor.crear_proveedor(Proveedor(id=None, nombre="Iriondo"))
        self.prov_inactivo = self.gestor.crear_proveedor(Proveedor(id=None, nombre="Viejo", activo=False))
        self.repositorio = RepositorioAlertas(self.conexion)
        motor = MotorAlertas(reglas_por_defecto(), self.repositorio, hoy=lambda: HOY)
        self.servicio = ServicioMovimientos(self.gestor, motor, hoy=lambda: HOY)
        self.servicio.registrar_ingreso(self.rod_id, 10, HOY, self.prov_id)

    def tearDown(self):
        self.conexion.close()
        self.directorio.cleanup()

    def stock(self, repuesto_id=None):
        return self.gestor.obtener_repuesto_id(repuesto_id or self.rod_id).stock_actual


class PruebaRegistrarMovimientos(BaseMovimientos):

    def test_ingreso_suma_y_guarda_el_proveedor(self):
        resultado = self.servicio.registrar_ingreso(self.rod_id, 5, HOY, self.prov_id)

        self.assertEqual(resultado.repuesto.stock_actual, 15)
        ultimo = self.gestor.obtener_movimientos(self.rod_id)[-1]
        self.assertEqual((ultimo.tipo, ultimo.proveedor_id), ("INGRESO", self.prov_id))

    def test_egreso_resta(self):
        resultado = self.servicio.registrar_egreso(self.rod_id, 4, HOY)
        self.assertEqual(resultado.repuesto.stock_actual, 6)

    def test_egreso_que_llega_al_punto_de_reorden_crea_la_alerta(self):
        # Act: quedan 3 (reorden 4)
        resultado = self.servicio.registrar_egreso(self.rod_id, 7, HOY)

        # Assert: la alerta aparece sola, sin "Revisar todo"
        self.assertEqual([a.tipo for a in resultado.alertas_nuevas], ["REORDEN"])
        self.assertEqual(len(self.repositorio.obtener_abiertas()), 1)

    def test_quitar_todo_lo_que_hay_es_valido(self):
        # Limite: deja el stock en 0 -> "Agotado"
        resultado = self.servicio.registrar_egreso(self.rod_id, 10, HOY)
        self.assertEqual(resultado.repuesto.stock_actual, 0)
        self.assertTrue(resultado.alertas_nuevas[0].mensaje.startswith("Agotado"))

    def test_conteo_corrige_y_revisa(self):
        resultado = self.servicio.registrar_conteo(self.rod_id, 1, HOY)
        self.assertEqual(resultado.repuesto.stock_actual, 1)
        self.assertEqual([a.tipo for a in resultado.alertas_nuevas], ["CRITICO"])

    def test_conteo_que_coincide_queda_registrado_con_diferencia_cero(self):
        resultado = self.servicio.registrar_conteo(self.rod_id, 10, HOY)
        self.assertIsNotNone(resultado.movimiento_id)
        self.assertEqual(resultado.diferencia, 0)

    def test_en_centimetros_acepta_decimales(self):
        resultado = self.servicio.registrar_ingreso(self.cadena_id, 30.5, HOY)
        self.assertEqual(resultado.repuesto.stock_actual, 30.5)


class PruebaMovimientosInvalidos(BaseMovimientos):
    """Precondiciones: con cualquier error no se guarda nada."""

    def assertNoSeGuarda(self, operacion, *argumentos):
        movimientos_antes = len(self.gestor.obtener_movimientos(self.rod_id))
        with self.assertRaises(MovimientoInvalidoError):
            operacion(*argumentos)
        self.assertEqual(len(self.gestor.obtener_movimientos(self.rod_id)), movimientos_antes)
        self.assertEqual(self.stock(), 10)

    def test_no_se_puede_quitar_mas_de_lo_que_hay(self):
        self.assertNoSeGuarda(self.servicio.registrar_egreso, self.rod_id, 11, HOY)

    def test_quitar_de_mas_dice_que_es_operacion_invalida(self):
        with self.assertRaises(MovimientoInvalidoError) as contexto:
            self.servicio.registrar_egreso(self.rod_id, 11, HOY)
        self.assertIn("Operación inválida", str(contexto.exception))
        self.assertIn("no puede quedar negativo", str(contexto.exception))

    def test_cantidad_cero_o_negativa(self):
        self.assertNoSeGuarda(self.servicio.registrar_ingreso, self.rod_id, 0, HOY)
        self.assertNoSeGuarda(self.servicio.registrar_egreso, self.rod_id, -2, HOY)

    def test_decimales_en_un_repuesto_por_unidad(self):
        self.assertNoSeGuarda(self.servicio.registrar_ingreso, self.rod_id, 1.5, HOY)

    def test_fecha_futura_o_invalida(self):
        self.assertNoSeGuarda(self.servicio.registrar_egreso, self.rod_id, 1, "2026-10-21")
        self.assertNoSeGuarda(self.servicio.registrar_egreso, self.rod_id, 1, "20/10/2026")

    def test_proveedor_inexistente_o_inactivo(self):
        self.assertNoSeGuarda(self.servicio.registrar_ingreso, self.rod_id, 1, HOY, 999)
        self.assertNoSeGuarda(self.servicio.registrar_ingreso, self.rod_id, 1, HOY, self.prov_inactivo)

    def test_repuesto_inexistente(self):
        with self.assertRaises(MovimientoInvalidoError):
            self.servicio.registrar_egreso(999, 1, HOY)

    def test_repuesto_inactivo(self):
        rep = self.gestor.obtener_repuesto_id(self.rod_id)
        rep.activo = False
        self.gestor.actualizar_repuesto(rep)
        self.assertNoSeGuarda(self.servicio.registrar_egreso, self.rod_id, 1, HOY)

    def test_conteo_invalido(self):
        self.assertNoSeGuarda(self.servicio.registrar_conteo, self.rod_id, -1, HOY)


if __name__ == "__main__":
    unittest.main()
