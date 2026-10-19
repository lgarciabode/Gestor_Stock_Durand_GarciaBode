
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.alertas import (
    CalculadoraParametros,
    EstimacionDemanda,
    EstimadorDemanda,
    EstimadorPorCompras,
    ParametrosInvalidosError,
    ParametrosStock,
)
from modules.base_datos import crear_esquema, obtener_conexion
from modules.carga_historico_datos import cargar_historico
from modules.modelos import MovimientoStock

RUTA_EXCEL = Path(__file__).resolve().parent.parent / "data" / "base_stock_taller.xlsx"
DIAS_PERIODO_HISTORICO = 212  # del 05/01/2026 al 05/08/2026


def ingreso(fecha, cantidad, repuesto_id=1):
    return MovimientoStock(id=None, repuesto_id=repuesto_id, fecha=fecha, tipo="INGRESO", cantidad=cantidad)


def compras_6204():
    """Las 4 compras reales del rodamiento 6204 2RS ZKL (55 unidades)."""
    return [ingreso("2026-02-13", 10), ingreso("2026-04-23", 15),
            ingreso("2026-06-30", 20), ingreso("2026-08-05", 10)]


class EstimadorFijo(EstimadorDemanda):
    """Doble de prueba (stub): devuelve siempre la misma estimacion."""

    def __init__(self, uso_diario, compra_tipica):
        self._estimacion = EstimacionDemanda(uso_diario, compra_tipica)

    def estimar(self, movimientos):
        return self._estimacion


class PruebaEstimadorPorCompras(unittest.TestCase):

    def test_estimador_abstracto_no_se_puede_instanciar(self):
        # Clase abstracta (Unidad 2): define el contrato, no se instancia
        with self.assertRaises(TypeError):
            EstimadorDemanda()

    def test_uso_diario_y_compra_tipica_del_6204(self):
        # Act
        estimacion = EstimadorPorCompras(DIAS_PERIODO_HISTORICO).estimar(compras_6204())

        # Assert: 55 / 212 = 0,259 por dia; 55 / 4 compras = 13,75
        self.assertAlmostEqual(estimacion.uso_diario, 55 / 212)
        self.assertAlmostEqual(estimacion.compra_tipica, 13.75)

    def test_solo_cuenta_ingresos(self):
        # Arrange: un egreso y un ajuste no son compras
        movimientos = compras_6204() + [
            MovimientoStock(id=None, repuesto_id=1, fecha="2026-09-01", tipo="EGRESO", cantidad=5),
            MovimientoStock(id=None, repuesto_id=1, fecha="2026-09-02", tipo="AJUSTE", cantidad=-1),
        ]

        # Act
        estimacion = EstimadorPorCompras(DIAS_PERIODO_HISTORICO).estimar(movimientos)

        # Assert
        self.assertAlmostEqual(estimacion.uso_diario, 55 / 212)

    def test_dos_renglones_del_mismo_dia_son_una_sola_compra(self):
        # Arrange
        movimientos = [ingreso("2026-05-05", 5), ingreso("2026-05-05", 5)]

        # Act
        estimacion = EstimadorPorCompras(DIAS_PERIODO_HISTORICO).estimar(movimientos)

        # Assert: 10 unidades en 1 compra
        self.assertEqual(estimacion.compra_tipica, 10)

    def test_sin_ingresos_devuelve_cero(self):
        # Excepcional: repuesto cargado a mano, todavia sin compras
        estimacion = EstimadorPorCompras(DIAS_PERIODO_HISTORICO).estimar([])
        self.assertEqual(estimacion, EstimacionDemanda(0.0, 0.0))

    def test_movimientos_de_distintos_repuestos_son_rechazados(self):
        # Pre: un solo repuesto
        with self.assertRaises(ValueError):
            EstimadorPorCompras(DIAS_PERIODO_HISTORICO).estimar(
                [ingreso("2026-01-05", 1, repuesto_id=1), ingreso("2026-01-06", 1, repuesto_id=2)]
            )

    def test_periodo_sin_dias_es_rechazado(self):
        with self.assertRaises(ValueError):
            EstimadorPorCompras(0)


class PruebaCalculadoraParametros(unittest.TestCase):

    def setUp(self):
        # L = 7 dias de reposicion, S = 7 dias de seguridad (decision del taller)
        self.calculadora = CalculadoraParametros(EstimadorPorCompras(DIAS_PERIODO_HISTORICO))

    def test_ejemplo_del_6204(self):
        # Act
        parametros = self.calculadora.calcular(compras_6204())

        # Assert: el mismo resultado que el documento de fundamentos
        self.assertEqual(parametros, ParametrosStock(stock_minimo=2, punto_reorden=4, stock_maximo=18))

    def test_repuesto_con_una_sola_compra_de_una_unidad(self):
        # Limite: uso diario muy chico -> umbrales minimos 1 / 1 / 2
        parametros = self.calculadora.calcular([ingreso("2026-03-01", 1)])
        self.assertEqual(parametros, ParametrosStock(stock_minimo=1, punto_reorden=1, stock_maximo=2))

    def test_sin_compras_devuelve_none(self):
        # Contrato: sin datos para calcular -> "sin datos todavia"
        self.assertIsNone(self.calculadora.calcular([]))

    def test_siempre_cumple_minimo_reorden_maximo(self):
        # Post: minimo <= reorden <= maximo para distintos usos
        for uso_diario, compra in [(0.004, 1), (0.26, 13.75), (1.5, 30), (10, 100)]:
            with self.subTest(uso_diario=uso_diario):
                calculadora = CalculadoraParametros(EstimadorFijo(uso_diario, compra))
                p = calculadora.calcular([])
                self.assertLessEqual(p.stock_minimo, p.punto_reorden)
                self.assertLessEqual(p.punto_reorden, p.stock_maximo)
                self.assertGreaterEqual(p.stock_minimo, 1)

    def test_funciona_con_cualquier_estimador(self):
        # Strategy + inversion de dependencias: se cambia el estimador sin tocar la calculadora.
        # d = 1 por dia, Q = 10 -> minimo 7, reorden 14, maximo 24
        calculadora = CalculadoraParametros(EstimadorFijo(uso_diario=1.0, compra_tipica=10))
        self.assertEqual(calculadora.calcular([]), ParametrosStock(7, 14, 24))

    def test_sin_dias_de_seguridad_el_minimo_es_cero(self):
        # Limite: S = 0 -> sin colchon
        calculadora = CalculadoraParametros(EstimadorFijo(1.0, 10), dias_reposicion=7, dias_seguridad=0)
        self.assertEqual(calculadora.calcular([]), ParametrosStock(0, 7, 17))

    def test_redondeo_no_suma_uno_por_error_de_coma_flotante(self):
        # En Python 0.28 * 25 da 7.000000000000001: sin la correccion se redondearia a 8
        calculadora = CalculadoraParametros(EstimadorFijo(0.28, 3), dias_reposicion=7, dias_seguridad=25)
        self.assertEqual(calculadora.calcular([]).stock_minimo, 7)

    def test_dias_de_reposicion_invalidos(self):
        with self.assertRaises(ParametrosInvalidosError):
            CalculadoraParametros(EstimadorFijo(1, 1), dias_reposicion=0)

    def test_dias_de_seguridad_negativos(self):
        with self.assertRaises(ParametrosInvalidosError):
            CalculadoraParametros(EstimadorFijo(1, 1), dias_seguridad=-1)


@unittest.skipUnless(RUTA_EXCEL.exists(), "No está el Excel histórico en data/")
class PruebaCalculoSobreDatosReales(unittest.TestCase):
    """Integracion: carga el historico real y recalcula el ejemplo del 6204."""

    def setUp(self):
        self.directorio_temporal = tempfile.TemporaryDirectory()
        self.conexion = obtener_conexion(str(Path(self.directorio_temporal.name) / "test.sqlite3"))
        crear_esquema(self.conexion)
        cargar_historico(self.conexion, str(RUTA_EXCEL))
        self.conexion.commit()

    def tearDown(self):
        self.conexion.close()
        self.directorio_temporal.cleanup()

    def test_6204_con_datos_reales(self):
        # Arrange: los movimientos del rodamiento 6204 2RS marca ZKL
        filas = self.conexion.execute(
            """SELECT m.* FROM movimientos_stock m
               JOIN repuestos r ON r.id = m.repuesto_id
               JOIN marcas ma ON ma.id = r.marca_id
               WHERE r.codigo = '6204 2RS' AND ma.nombre = 'ZKL'"""
        ).fetchall()
        movimientos = [MovimientoStock(id=f["id"], repuesto_id=f["repuesto_id"], fecha=f["fecha"],
                                       tipo=f["tipo"], cantidad=f["cantidad"]) for f in filas]
        calculadora = CalculadoraParametros(EstimadorPorCompras(DIAS_PERIODO_HISTORICO))

        # Act
        parametros = calculadora.calcular(movimientos)

        # Assert
        self.assertEqual(parametros, ParametrosStock(stock_minimo=2, punto_reorden=4, stock_maximo=18))


if __name__ == "__main__":
    unittest.main()
