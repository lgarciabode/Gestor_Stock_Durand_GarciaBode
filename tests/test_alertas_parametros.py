"""Pruebas del guardado de umbrales (Paso 4 del modulo de alertas).

- GestorInventarioBD.obtener_movimientos / obtener_periodo_movimientos.
- ServicioParametrosStock: con un gestor "mock" (unittest.mock) se verifica
  COMO usa a su colaborador (Unidad 4, dobles de prueba): por ejemplo, que no
  intente guardar nada si los umbrales son manuales o el repuesto esta inactivo.
- Integracion con la base real cargada desde el Excel historico.

unittest puro, patron AAA (Arrange, Act, Assert).
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.alertas import (
    CalculadoraParametros,
    EstimadorPorCompras,
    ParametrosStock,
    ServicioParametrosStock,
    dias_entre,
)
from modules.base_datos import crear_esquema, obtener_conexion
from modules.carga_historico_datos import cargar_historico
from modules.crud import GestorInventarioBD
from modules.modelos import Categoria, Marca, MovimientoStock, Repuesto

RUTA_EXCEL = Path(__file__).resolve().parent.parent / "data" / "base_stock_taller.xlsx"


def ingreso(fecha, cantidad, repuesto_id=1):
    return MovimientoStock(id=None, repuesto_id=repuesto_id, fecha=fecha, tipo="INGRESO", cantidad=cantidad)


def repuesto(activo=True, manual=False):
    return Repuesto(id=1, codigo="6204 2RS", marca_id=1, categoria_id=1, stock_actual=55,
                    activo=activo, parametros_manuales=manual)


class PruebaDiasEntre(unittest.TestCase):

    def test_periodo_historico(self):
        self.assertEqual(dias_entre("2026-01-05", "2026-08-05"), 212)

    def test_mismo_dia_cuenta_como_un_dia(self):
        # Limite: evita dividir por cero
        self.assertEqual(dias_entre("2026-01-05", "2026-01-05"), 1)


class PruebaServicioConMock(unittest.TestCase):
    """El gestor es un Mock: no hay base de datos, solo se observa como se lo usa."""

    def setUp(self):
        self.gestor = Mock()
        self.gestor.obtener_movimientos.return_value = [
            ingreso("2026-02-13", 10), ingreso("2026-04-23", 15),
            ingreso("2026-06-30", 20), ingreso("2026-08-05", 10),
        ]
        calculadora = CalculadoraParametros(EstimadorPorCompras(212))
        self.servicio = ServicioParametrosStock(self.gestor, calculadora)

    def test_guarda_los_umbrales_calculados_como_automaticos(self):
        # Act
        resultado = self.servicio.recalcular(repuesto())

        # Assert
        self.assertEqual(resultado, ParametrosStock(2, 4, 18))
        self.gestor.actualizar_parametros_stock.assert_called_once_with(
            1, stock_minimo=2, stock_maximo=18, punto_reorden=4, manual=False
        )

    def test_no_toca_umbrales_corregidos_a_mano(self):
        # Act
        resultado = self.servicio.recalcular(repuesto(manual=True))

        # Assert: ni siquiera intenta guardar
        self.assertIsNone(resultado)
        self.gestor.actualizar_parametros_stock.assert_not_called()

    def test_no_toca_repuestos_inactivos(self):
        resultado = self.servicio.recalcular(repuesto(activo=False))
        self.assertIsNone(resultado)
        self.gestor.actualizar_parametros_stock.assert_not_called()

    def test_sin_compras_no_cambia_nada(self):
        # Arrange: repuesto cargado a mano, sin movimientos
        self.gestor.obtener_movimientos.return_value = []

        # Act
        resultado = self.servicio.recalcular(repuesto())

        # Assert: queda "sin datos todavia"
        self.assertIsNone(resultado)
        self.gestor.actualizar_parametros_stock.assert_not_called()

    def test_recalcular_todos_cuenta_solo_los_actualizados(self):
        # Arrange: uno normal, uno manual
        self.gestor.obtener_repuestos.return_value = [repuesto(), repuesto(manual=True)]

        # Act
        actualizados = self.servicio.recalcular_todos()

        # Assert
        self.assertEqual(actualizados, 1)
        self.gestor.obtener_repuestos.assert_called_once_with(solo_activos=True)


class PruebaMovimientosEnBase(unittest.TestCase):
    """obtener_movimientos y obtener_periodo_movimientos sobre una base temporal."""

    def setUp(self):
        self.directorio_temporal = tempfile.TemporaryDirectory()
        self.conexion = obtener_conexion(str(Path(self.directorio_temporal.name) / "test.sqlite3"))
        crear_esquema(self.conexion)
        self.gestor = GestorInventarioBD(self.conexion)
        marca_id = self.gestor.crear_marca(Marca(id=None, nombre="ZKL"))
        categoria_id = self.gestor.crear_categoria(Categoria(id=None, nombre="RODAMIENTO"))
        self.id_a = self.gestor.crear_repuestos(Repuesto(id=None, codigo="A", marca_id=marca_id, categoria_id=categoria_id))
        self.id_b = self.gestor.crear_repuestos(Repuesto(id=None, codigo="B", marca_id=marca_id, categoria_id=categoria_id))

    def tearDown(self):
        self.conexion.close()
        self.directorio_temporal.cleanup()

    def test_sin_movimientos_no_hay_periodo(self):
        self.assertIsNone(self.gestor.obtener_periodo_movimientos())

    def test_obtener_movimientos_trae_solo_ese_repuesto_ordenado_por_fecha(self):
        # Arrange
        self.gestor.registrar_movimiento(ingreso("2026-03-01", 5, repuesto_id=self.id_a))
        self.gestor.registrar_movimiento(ingreso("2026-01-10", 2, repuesto_id=self.id_a))
        self.gestor.registrar_movimiento(ingreso("2026-02-01", 9, repuesto_id=self.id_b))

        # Act
        movimientos = self.gestor.obtener_movimientos(self.id_a)

        # Assert
        self.assertEqual([m.fecha for m in movimientos], ["2026-01-10", "2026-03-01"])
        self.assertEqual(self.gestor.obtener_periodo_movimientos(), ("2026-01-10", "2026-03-01"))


@unittest.skipUnless(RUTA_EXCEL.exists(), "No está el Excel histórico en data/")
class PruebaServicioSobreDatosReales(unittest.TestCase):

    def setUp(self):
        self.directorio_temporal = tempfile.TemporaryDirectory()
        self.conexion = obtener_conexion(str(Path(self.directorio_temporal.name) / "test.sqlite3"))
        crear_esquema(self.conexion)
        cargar_historico(self.conexion, str(RUTA_EXCEL))
        self.conexion.commit()
        self.gestor = GestorInventarioBD(self.conexion)
        self.servicio = ServicioParametrosStock.desde_historial(self.gestor)

    def tearDown(self):
        self.conexion.close()
        self.directorio_temporal.cleanup()

    def _repuesto_6204(self):
        return next(r for r in self.gestor.obtener_repuestos() if r.codigo == "6204 2RS")

    def test_recalcula_todos_los_repuestos_del_historico(self):
        # Act
        actualizados = self.servicio.recalcular_todos()

        # Assert: los 192 tienen compras; todos quedan con umbrales coherentes
        self.assertEqual(actualizados, 192)
        repuestos = self.gestor.obtener_repuestos()
        self.assertTrue(all(r.tiene_umbrales() for r in repuestos))
        self.assertTrue(all(r.stock_minimo <= r.punto_reorden <= r.stock_maximo for r in repuestos))
        rep = self._repuesto_6204()
        self.assertEqual((rep.stock_minimo, rep.punto_reorden, rep.stock_maximo), (2, 4, 18))

    def test_un_umbral_corregido_a_mano_sobrevive_al_recalculo(self):
        # Arrange: el duenio decide que del 6204 conviene tener mas
        rep = self._repuesto_6204()
        self.gestor.actualizar_parametros_stock(rep.id, stock_minimo=5, stock_maximo=30, punto_reorden=10)

        # Act
        self.servicio.recalcular_todos()

        # Assert
        rep = self._repuesto_6204()
        self.assertEqual((rep.stock_minimo, rep.punto_reorden, rep.stock_maximo), (5, 10, 30))
        self.assertTrue(rep.parametros_manuales)


if __name__ == "__main__":
    unittest.main()
