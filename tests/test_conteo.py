"""Pruebas del conteo fisico (Paso 6 del modulo de alertas).

Quien usa el sistema carga lo que CONTO en el estante; el sistema guarda la
diferencia como un movimiento de AJUSTE y el trigger de la base deja
stock_actual igual a lo contado.

- Repuesto.ajuste_por_conteo: sin base de datos (contrato pre/post).
- GestorInventarioBD.registrar_conteo: sobre una base SQLite temporal.
- Integracion con las alertas y con el calculo de umbrales (el AJUSTE no
  cuenta como compra ni como consumo).

unittest puro, patron AAA (Arrange, Act, Assert).
"""
import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.alertas import (
    CalculadoraParametros,
    EstimadorPorCompras,
    MotorAlertas,
    ServicioParametrosStock,
    reglas_por_defecto,
)
from modules.base_datos import crear_esquema, obtener_conexion
from modules.carga_historico_datos import cargar_historico
from modules.crud import GestorInventarioBD, RepositorioAlertas, RepuestoNoEncontradoError
from modules.modelos import (
    Categoria,
    ConteoInvalidoError,
    Marca,
    MovimientoStock,
    Repuesto,
    RepuestoInvalidoError,
)

RUTA_EXCEL = Path(__file__).resolve().parent.parent / "data" / "base_stock_taller.xlsx"
HOY = "2026-10-20"


def repuesto(stock, unidad="unidad", id=1):
    return Repuesto(id=id, codigo="6204 2RS", marca_id=1, categoria_id=1,
                    unidad_medida=unidad, stock_actual=stock)


# ================================================================ Modelo (sin base)

class PruebaAjustePorConteo(unittest.TestCase):

    def test_si_falta_stock_el_ajuste_es_negativo(self):
        # Arrange: el sistema dice 55, en el estante hay 3
        rep = repuesto(stock=55)

        # Act
        ajuste = rep.ajuste_por_conteo(3, HOY)

        # Assert
        self.assertEqual(ajuste, MovimientoStock(id=None, repuesto_id=1, fecha=HOY, tipo="AJUSTE", cantidad=-52))
        self.assertEqual(ajuste.origen, "manual")
        self.assertIsNone(ajuste.proveedor_id)

    def test_si_sobra_stock_el_ajuste_es_positivo(self):
        self.assertEqual(repuesto(stock=2).ajuste_por_conteo(5, HOY).cantidad, 3)

    def test_si_coincide_no_hay_nada_que_ajustar(self):
        self.assertIsNone(repuesto(stock=7).ajuste_por_conteo(7, HOY))

    def test_contar_cero_es_valido(self):
        # Limite: se acabo el repuesto
        self.assertEqual(repuesto(stock=4).ajuste_por_conteo(0, HOY).cantidad, -4)

    def test_no_modifica_el_repuesto(self):
        rep = repuesto(stock=55)
        antes = copy.deepcopy(rep)
        rep.ajuste_por_conteo(3, HOY)
        self.assertEqual(rep, antes)

    def test_cantidad_negativa_es_invalida(self):
        with self.assertRaises(ConteoInvalidoError):
            repuesto(stock=5).ajuste_por_conteo(-1, HOY)

    def test_por_unidad_no_acepta_decimales(self):
        with self.assertRaises(ConteoInvalidoError):
            repuesto(stock=5).ajuste_por_conteo(2.5, HOY)

    def test_en_centimetros_acepta_decimales(self):
        self.assertEqual(repuesto(stock=300, unidad="cm").ajuste_por_conteo(250.5, HOY).cantidad, -49.5)

    def test_sin_diferencias_fantasma_de_punto_flotante(self):
        # 0.1 + 0.2 da 0.30000000000000004: igual tiene que considerarse "coincide"
        self.assertIsNone(repuesto(stock=0.1 + 0.2, unidad="cm").ajuste_por_conteo(0.3, HOY))

    def test_repuesto_sin_guardar_no_se_puede_contar(self):
        with self.assertRaises(RepuestoInvalidoError):
            repuesto(stock=5, id=None).ajuste_por_conteo(3, HOY)


# ================================================================ Base de datos

class BaseTemporal(unittest.TestCase):

    def setUp(self):
        self.directorio_temporal = tempfile.TemporaryDirectory()
        self.conexion = obtener_conexion(str(Path(self.directorio_temporal.name) / "test.sqlite3"))
        crear_esquema(self.conexion)
        self.gestor = GestorInventarioBD(self.conexion)
        marca_id = self.gestor.crear_marca(Marca(id=None, nombre="ZKL"))
        categoria_id = self.gestor.crear_categoria(Categoria(id=None, nombre="RODAMIENTO"))
        self.repuesto_id = self.gestor.crear_repuestos(
            Repuesto(id=None, codigo="6204 2RS", marca_id=marca_id, categoria_id=categoria_id)
        )

    def tearDown(self):
        self.conexion.close()
        self.directorio_temporal.cleanup()

    def mover(self, tipo, cantidad, fecha=HOY):
        self.gestor.registrar_movimiento(
            MovimientoStock(id=None, repuesto_id=self.repuesto_id, fecha=fecha, tipo=tipo, cantidad=cantidad)
        )

    def stock(self):
        return self.gestor.obtener_repuesto_id(self.repuesto_id).stock_actual


class PruebaRegistrarConteo(BaseTemporal):

    def test_el_stock_queda_igual_a_lo_contado(self):
        # Arrange: se compraron 55 y nunca se cargaron egresos
        self.mover("INGRESO", 55)

        # Act: en el estante hay 3
        movimiento_id = self.gestor.registrar_conteo(self.repuesto_id, 3, HOY)

        # Assert
        self.assertIsNotNone(movimiento_id)
        self.assertEqual(self.stock(), 3)

    def test_queda_guardado_como_ajuste_sin_tocar_los_movimientos_anteriores(self):
        self.mover("INGRESO", 55, fecha="2026-02-13")
        self.gestor.registrar_conteo(self.repuesto_id, 3, HOY)

        movimientos = self.gestor.obtener_movimientos(self.repuesto_id)

        self.assertEqual([(m.tipo, m.cantidad) for m in movimientos], [("INGRESO", 55), ("AJUSTE", -52)])

    def test_si_coincide_no_guarda_nada(self):
        self.mover("INGRESO", 10)

        resultado = self.gestor.registrar_conteo(self.repuesto_id, 10, HOY)

        self.assertIsNone(resultado)
        self.assertEqual(len(self.gestor.obtener_movimientos(self.repuesto_id)), 1)

    def test_repuesto_inexistente(self):
        with self.assertRaises(RepuestoNoEncontradoError):
            self.gestor.registrar_conteo(999, 3, HOY)

    def test_un_conteo_invalido_no_guarda_nada(self):
        self.mover("INGRESO", 10)

        with self.assertRaises(ConteoInvalidoError):
            self.gestor.registrar_conteo(self.repuesto_id, -2, HOY)

        self.assertEqual(self.stock(), 10)
        self.assertEqual(len(self.gestor.obtener_movimientos(self.repuesto_id)), 1)


# ================================================================ Integracion con alertas

class PruebaConteoYAlertas(BaseTemporal):
    """El caso real del 6204: 55 comprados, umbrales 2 / 4 / 18, en el estante hay 3."""

    def setUp(self):
        super().setUp()
        self.gestor.actualizar_parametros_stock(self.repuesto_id, stock_minimo=2, stock_maximo=18,
                                                punto_reorden=4, manual=False)
        self.repositorio = RepositorioAlertas(self.conexion)
        self.motor = MotorAlertas(reglas_por_defecto(), self.repositorio, hoy=lambda: HOY)
        self.mover("INGRESO", 55)

    def revisar(self):
        return self.motor.revisar(self.gestor.obtener_repuesto_id(self.repuesto_id))

    def test_sin_conteo_la_alerta_es_falsa(self):
        # Con el stock "inflado" el sistema cree que sobra
        self.assertEqual([a.tipo for a in self.revisar()], ["SOBRESTOCK"])

    def test_despues_del_conteo_aparece_la_alerta_real(self):
        # Arrange: la alerta falsa ya estaba abierta; el usuario la cierra
        falsa = self.revisar()[0]
        self.repositorio.marcar_atendida(falsa.id)

        # Act: se registra el conteo y se revisa ese repuesto
        self.gestor.registrar_conteo(self.repuesto_id, 3, HOY)
        nuevas = self.revisar()

        # Assert: quedan 3 -> "Hay que pedir"
        self.assertEqual([a.tipo for a in nuevas], ["REORDEN"])

    def test_el_ajuste_no_cambia_los_umbrales_calculados(self):
        # El AJUSTE no es una compra: el estimador solo cuenta INGRESOS
        calculadora = CalculadoraParametros(EstimadorPorCompras(dias_periodo=212))
        antes = calculadora.calcular(self.gestor.obtener_movimientos(self.repuesto_id))

        self.gestor.registrar_conteo(self.repuesto_id, 3, HOY)
        despues = calculadora.calcular(self.gestor.obtener_movimientos(self.repuesto_id))

        self.assertEqual(antes, despues)


@unittest.skipUnless(RUTA_EXCEL.exists(), "No está el Excel histórico en data/")
class PruebaConteoSobreDatosReales(unittest.TestCase):

    def setUp(self):
        self.directorio_temporal = tempfile.TemporaryDirectory()
        self.conexion = obtener_conexion(str(Path(self.directorio_temporal.name) / "test.sqlite3"))
        crear_esquema(self.conexion)
        cargar_historico(self.conexion, str(RUTA_EXCEL))
        self.conexion.commit()
        self.gestor = GestorInventarioBD(self.conexion)

    def tearDown(self):
        self.conexion.close()
        self.directorio_temporal.cleanup()

    def test_conteo_del_6204_con_el_historico(self):
        # Arrange
        rep = next(r for r in self.gestor.obtener_repuestos() if r.codigo == "6204 2RS")
        self.assertEqual(rep.stock_actual, 55)  # todo lo comprado desde enero

        # Act
        self.gestor.registrar_conteo(rep.id, 3, HOY)
        ServicioParametrosStock.desde_historial(self.gestor).recalcular_todos()

        # Assert: stock real
        rep = self.gestor.obtener_repuesto_id(rep.id)
        self.assertEqual(rep.stock_actual, 3)
        # Los umbrales pasan de 2 / 4 / 18 a 2 / 3 / 17. No por la cantidad del
        # AJUSTE (no es compra), sino porque el periodo ahora llega hasta el dia
        # del conteo: 05/01 -> 20/10 = 289 dias en vez de 212. Las mismas 55
        # unidades repartidas en mas dias = uso diario menor (55 / 289 = 0,19).
        self.assertEqual(self.gestor.obtener_periodo_movimientos(), ("2026-01-05", HOY))
        self.assertEqual((rep.stock_minimo, rep.punto_reorden, rep.stock_maximo), (2, 3, 17))


if __name__ == "__main__":
    unittest.main()
