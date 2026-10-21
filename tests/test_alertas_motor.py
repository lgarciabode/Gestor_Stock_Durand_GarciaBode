"""Pruebas de las reglas, el motor y el repositorio de alertas (Paso 5).

- Reglas: sin base de datos. Una prueba recorre TODAS las reglas y verifica el
  contrato comun (Liskov): devuelven bool y no modifican el repuesto.
- MotorAlertas: con un repositorio falso en memoria (doble de prueba, Unidad 4)
  y una fecha fija, asi la prueba es determinista.
- RepositorioAlertas: sobre una base SQLite temporal real.
- Flujo completo: umbrales -> egresos -> alertas -> "Ya lo pedi" -> escalada.

unittest puro, patron AAA (Arrange, Act, Assert).
"""
import copy
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.alertas import (
    MotorAlertas,
    ReglaAlerta,
    ReglaCritico,
    ReglaReorden,
    ReglaSobrestock,
    reglas_por_defecto,
)
from modules.base_datos import crear_esquema, obtener_conexion
from modules.crud import (
    AlertaDuplicadaError,
    AlertaNoEncontradaError,
    GestorInventarioBD,
    RepositorioAlertas,
)
from modules.modelos import Alerta, Categoria, Marca, MovimientoStock, Repuesto

HOY = "2026-10-16"


def repuesto(stock, minimo=2.0, reorden=4.0, maximo=18.0, activo=True, unidad="unidad", id=1):
    return Repuesto(id=id, codigo="6204 2RS", marca_id=1, categoria_id=1, unidad_medida=unidad,
                    stock_minimo=minimo, punto_reorden=reorden, stock_maximo=maximo,
                    stock_actual=stock, activo=activo)


class RepositorioEnMemoria:
    """Doble de prueba (fake): se comporta como RepositorioAlertas pero guarda en una lista."""

    def __init__(self):
        self.alertas = []

    def existe_abierta(self, repuesto_id, tipo):
        return any(a.repuesto_id == repuesto_id and a.tipo == tipo and not a.atendida for a in self.alertas)

    def crear(self, alerta):
        self.alertas.append(alerta)
        return len(self.alertas)


# ================================================================ Reglas

class PruebaReglas(unittest.TestCase):

    def test_la_regla_abstracta_no_se_puede_instanciar(self):
        with self.assertRaises(TypeError):
            ReglaAlerta()

    def test_reorden_entre_minimo_y_punto_de_reorden(self):
        self.assertTrue(ReglaReorden().evaluar(repuesto(stock=3)))
        self.assertTrue(ReglaReorden().evaluar(repuesto(stock=4)))   # limite: justo en el reorden

    def test_reorden_no_salta_por_encima_ni_por_debajo_del_minimo(self):
        self.assertFalse(ReglaReorden().evaluar(repuesto(stock=5)))
        self.assertFalse(ReglaReorden().evaluar(repuesto(stock=2)))  # en el minimo corresponde CRITICO

    def test_critico_en_el_minimo_y_agotado(self):
        self.assertTrue(ReglaCritico().evaluar(repuesto(stock=2)))
        self.assertTrue(ReglaCritico().evaluar(repuesto(stock=0)))
        self.assertFalse(ReglaCritico().evaluar(repuesto(stock=3)))

    def test_sobrestock_solo_por_encima_del_maximo(self):
        self.assertTrue(ReglaSobrestock().evaluar(repuesto(stock=19)))
        self.assertFalse(ReglaSobrestock().evaluar(repuesto(stock=18)))  # limite: justo en el maximo

    def test_mensaje_de_reorden_con_palabras_del_taller(self):
        mensaje = ReglaReorden().mensaje(repuesto(stock=3))
        self.assertEqual(
            mensaje,
            "Hay que pedir — 6204 2RS: quedan 3 unidades (pedir cuando queden 4 unidades). "
            "Sugerencia: pedir 15 unidades.",
        )

    def test_mensaje_de_agotado(self):
        mensaje = ReglaCritico().mensaje(repuesto(stock=0))
        self.assertEqual(mensaje, "Agotado — 6204 2RS: no queda stock. Sugerencia: pedir 18 unidades.")

    def test_mensaje_en_centimetros_y_singular(self):
        en_cm = ReglaCritico().mensaje(repuesto(stock=30, minimo=50, reorden=80, maximo=300, unidad="cm"))
        una = ReglaReorden().mensaje(repuesto(stock=1, minimo=0, reorden=1, maximo=2))
        self.assertIn("quedan 30 cm", en_cm)
        self.assertIn("queda 1 unidad ", una)

    def test_todas_las_reglas_cumplen_el_mismo_contrato(self):
        # Liskov: cualquier regla se puede usar en lugar de otra
        for regla in reglas_por_defecto():
            for stock in (0, 2, 3, 10, 30):
                with self.subTest(regla=regla.tipo, stock=stock):
                    rep = repuesto(stock=stock)
                    antes = copy.deepcopy(rep)
                    resultado = regla.evaluar(rep)
                    self.assertIsInstance(resultado, bool)
                    self.assertEqual(rep, antes)  # no modifica el repuesto
                    self.assertTrue(regla.mensaje(rep).strip())


# ================================================================ Motor (con repositorio falso)

class PruebaMotorAlertas(unittest.TestCase):

    def setUp(self):
        self.repositorio = RepositorioEnMemoria()
        self.motor = MotorAlertas(reglas_por_defecto(), self.repositorio, hoy=lambda: HOY)

    def test_crea_la_alerta_que_corresponde(self):
        # Act
        nuevas = self.motor.revisar(repuesto(stock=3))

        # Assert
        self.assertEqual([a.tipo for a in nuevas], ["REORDEN"])
        self.assertEqual(nuevas[0].fecha, HOY)
        self.assertFalse(nuevas[0].atendida)

    def test_no_duplica_si_ya_hay_una_abierta(self):
        # Arrange
        self.motor.revisar(repuesto(stock=3))

        # Act: se vuelve a revisar el mismo repuesto (ej. otro egreso)
        nuevas = self.motor.revisar(repuesto(stock=3))

        # Assert
        self.assertEqual(nuevas, [])
        self.assertEqual(len(self.repositorio.alertas), 1)

    def test_escalada_de_reorden_a_critico(self):
        # Arrange: primero "hay que pedir"
        self.motor.revisar(repuesto(stock=3))

        # Act: el stock sigue bajando hasta el minimo
        nuevas = self.motor.revisar(repuesto(stock=1))

        # Assert: se suma la CRITICA; la REORDEN queda abierta
        self.assertEqual([a.tipo for a in nuevas], ["CRITICO"])
        self.assertEqual(len(self.repositorio.alertas), 2)

    def test_disponible_no_genera_alertas(self):
        self.assertEqual(self.motor.revisar(repuesto(stock=10)), [])

    def test_repuesto_inactivo_no_se_revisa(self):
        self.assertEqual(self.motor.revisar(repuesto(stock=0, activo=False)), [])

    def test_repuesto_sin_umbrales_no_se_revisa(self):
        sin_umbrales = Repuesto(id=1, codigo="X", marca_id=1, categoria_id=1, stock_actual=0)
        self.assertEqual(self.motor.revisar(sin_umbrales), [])

    def test_revisar_todos(self):
        # Arrange
        repuestos = [repuesto(stock=3, id=1), repuesto(stock=10, id=2), repuesto(stock=30, id=3)]

        # Act
        nuevas = self.motor.revisar_todos(repuestos)

        # Assert
        self.assertEqual(sorted((a.repuesto_id, a.tipo) for a in nuevas),
                         [(1, "REORDEN"), (3, "SOBRESTOCK")])

    def test_un_motor_sin_reglas_no_tiene_sentido(self):
        with self.assertRaises(ValueError):
            MotorAlertas([], self.repositorio)

    def test_acepta_cualquier_regla_nueva(self):
        # Abierto/Cerrado: una regla nueva se suma sin tocar el motor
        class ReglaSiempre(ReglaAlerta):
            tipo = "REORDEN"

            def evaluar(self, repuesto):
                return True

            def mensaje(self, repuesto):
                return "regla de prueba"

        motor = MotorAlertas([ReglaSiempre()], self.repositorio, hoy=lambda: HOY)
        self.assertEqual(len(motor.revisar(repuesto(stock=10))), 1)


# ================================================================ Repositorio (base real)

class BaseTemporal(unittest.TestCase):

    def setUp(self):
        self.directorio_temporal = tempfile.TemporaryDirectory()
        self.conexion = obtener_conexion(str(Path(self.directorio_temporal.name) / "test.sqlite3"))
        crear_esquema(self.conexion)
        self.gestor = GestorInventarioBD(self.conexion)
        self.repositorio = RepositorioAlertas(self.conexion)
        marca_id = self.gestor.crear_marca(Marca(id=None, nombre="ZKL"))
        categoria_id = self.gestor.crear_categoria(Categoria(id=None, nombre="RODAMIENTO"))
        self.repuesto_id = self.gestor.crear_repuestos(
            Repuesto(id=None, codigo="6204 2RS", marca_id=marca_id, categoria_id=categoria_id)
        )

    def tearDown(self):
        self.conexion.close()
        self.directorio_temporal.cleanup()

    def alerta(self, tipo="REORDEN"):
        return Alerta(id=None, repuesto_id=self.repuesto_id, fecha=HOY, tipo=tipo, mensaje="Hay que pedir")


class PruebaRepositorioAlertas(BaseTemporal):

    def test_crear_y_listar_abiertas_lo_mas_urgente_primero(self):
        # Arrange
        self.repositorio.crear(self.alerta("SOBRESTOCK"))
        self.repositorio.crear(self.alerta("CRITICO"))
        self.repositorio.crear(self.alerta("REORDEN"))

        # Act
        abiertas = self.repositorio.obtener_abiertas()

        # Assert
        self.assertEqual([a.tipo for a in abiertas], ["CRITICO", "REORDEN", "SOBRESTOCK"])

    def test_existe_abierta(self):
        self.repositorio.crear(self.alerta("REORDEN"))
        self.assertTrue(self.repositorio.existe_abierta(self.repuesto_id, "REORDEN"))
        self.assertFalse(self.repositorio.existe_abierta(self.repuesto_id, "CRITICO"))

    def test_duplicada_abierta_es_rechazada(self):
        self.repositorio.crear(self.alerta("REORDEN"))
        with self.assertRaises(AlertaDuplicadaError):
            self.repositorio.crear(self.alerta("REORDEN"))

    def test_marcar_atendida_la_cierra_pero_queda_en_el_historial(self):
        # Arrange
        alerta_id = self.repositorio.crear(self.alerta("REORDEN"))

        # Act
        self.repositorio.marcar_atendida(alerta_id)

        # Assert
        self.assertEqual(self.repositorio.obtener_abiertas(), [])
        historial = self.repositorio.obtener_historial(self.repuesto_id)
        self.assertEqual(len(historial), 1)
        self.assertTrue(historial[0].atendida)

    def test_marcar_atendida_dos_veces_es_un_error(self):
        alerta_id = self.repositorio.crear(self.alerta())
        self.repositorio.marcar_atendida(alerta_id)
        with self.assertRaises(AlertaNoEncontradaError):
            self.repositorio.marcar_atendida(alerta_id)

    def test_marcar_atendida_inexistente_es_un_error(self):
        with self.assertRaises(AlertaNoEncontradaError):
            self.repositorio.marcar_atendida(999)

    def test_alertas_de_repuestos_inactivos_no_se_muestran_pero_no_se_borran(self):
        # Arrange
        self.repositorio.crear(self.alerta("REORDEN"))
        rep = self.gestor.obtener_repuesto_id(self.repuesto_id)
        rep.activo = False
        self.gestor.actualizar_repuesto(rep)

        # Act / Assert
        self.assertEqual(self.repositorio.obtener_abiertas(), [])
        self.assertEqual(len(self.repositorio.obtener_abiertas(incluir_inactivos=True)), 1)


# ================================================================ Flujo completo

class PruebaFlujoCompleto(BaseTemporal):
    """Umbrales 2 / 4 / 18, se compran 10 y se van usando."""

    def setUp(self):
        super().setUp()
        self.gestor.actualizar_parametros_stock(self.repuesto_id, stock_minimo=2, stock_maximo=18, punto_reorden=4)
        self.motor = MotorAlertas(reglas_por_defecto(), self.repositorio, hoy=lambda: HOY)
        self._mover("INGRESO", 10)

    def _mover(self, tipo, cantidad):
        # Lo que haria la interfaz: registrar el movimiento y revisar ese repuesto
        self.gestor.registrar_movimiento(
            MovimientoStock(id=None, repuesto_id=self.repuesto_id, fecha=HOY, tipo=tipo, cantidad=cantidad)
        )
        return self.motor.revisar(self.gestor.obtener_repuesto_id(self.repuesto_id))

    def test_de_disponible_a_hay_que_pedir_a_agotado(self):
        # Con 10 en stock no hay alertas
        self.assertEqual(self.repositorio.obtener_abiertas(), [])

        # Se usan 7 -> quedan 3 -> "Hay que pedir"
        self.assertEqual([a.tipo for a in self._mover("EGRESO", 7)], ["REORDEN"])

        # El usuario aprieta "Ya lo pedi"
        reorden = self.repositorio.obtener_abiertas()[0]
        self.repositorio.marcar_atendida(reorden.id)

        # Se usan 3 mas -> quedan 0 -> "Agotado" (CRITICO)
        nuevas = self._mover("EGRESO", 3)
        self.assertEqual([a.tipo for a in nuevas], ["CRITICO"])
        self.assertTrue(nuevas[0].mensaje.startswith("Agotado"))

        # Historial: la REORDEN atendida y la CRITICA abierta
        historial = self.repositorio.obtener_historial(self.repuesto_id)
        self.assertEqual(sorted((a.tipo, a.atendida) for a in historial),
                         [("CRITICO", False), ("REORDEN", True)])


if __name__ == "__main__":
    unittest.main()
