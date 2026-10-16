"""Pruebas unitarias de los modelos de dominio (Paso 2 del modulo de alertas).

No tocan la base de datos: prueban las reglas que cada objeto conoce de si
mismo (diseno dirigido por responsabilidades) y sus contratos (invariantes).
Los casos siguen la guia de la Unidad 4: habituales, limites, invalidos y
excepcionales. Patron AAA (Arrange, Act, Assert), unittest puro.

Umbrales de ejemplo (rodamiento 6204 2RS ZKL): minimo 2, reorden 4, maximo 18.
"""
import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.modelos import (
    Alerta,
    AlertaInvalidaError,
    EstadoStock,
    Repuesto,
    RepuestoInvalidoError,
)


def repuesto(stock, minimo=2.0, reorden=4.0, maximo=18.0, activo=True):
    """Arma un repuesto de prueba con los umbrales del ejemplo."""
    return Repuesto(id=1, codigo="6204 2RS", marca_id=1, categoria_id=1,
                    stock_minimo=minimo, punto_reorden=reorden, stock_maximo=maximo,
                    stock_actual=stock, activo=activo)


def repuesto_sin_umbrales(stock=5.0):
    return Repuesto(id=2, codigo="UC 207", marca_id=1, categoria_id=1, stock_actual=stock)


class PruebaInvarianteRepuesto(unittest.TestCase):
    """Contrato: unidad valida, umbrales no negativos y minimo <= reorden <= maximo."""

    def test_repuesto_valido_se_crea(self):
        # Act
        rep = repuesto(stock=10)

        # Assert
        self.assertTrue(rep.tiene_umbrales())

    def test_repuesto_sin_umbrales_es_valido(self):
        # Act
        rep = repuesto_sin_umbrales()

        # Assert
        self.assertFalse(rep.tiene_umbrales())

    def test_umbrales_iguales_son_validos(self):
        # Limite: minimo = reorden = maximo
        rep = repuesto(stock=1, minimo=1, reorden=1, maximo=1)
        self.assertTrue(rep.tiene_umbrales())

    def test_reorden_menor_que_minimo_es_invalido(self):
        with self.assertRaises(RepuestoInvalidoError):
            repuesto(stock=10, minimo=5, reorden=2, maximo=50)

    def test_maximo_menor_que_reorden_es_invalido(self):
        with self.assertRaises(RepuestoInvalidoError):
            repuesto(stock=10, minimo=2, reorden=20, maximo=18)

    def test_umbral_negativo_es_invalido(self):
        with self.assertRaises(RepuestoInvalidoError):
            repuesto(stock=10, minimo=-1)

    def test_unidad_desconocida_es_invalida(self):
        with self.assertRaises(RepuestoInvalidoError):
            Repuesto(id=1, codigo="X", marca_id=1, categoria_id=1, unidad_medida="kg")


class PruebaPreguntasDelRepuesto(unittest.TestCase):
    """Cada pregunta responde sobre el propio repuesto y no lo modifica."""

    def test_justo_en_el_punto_de_reorden_necesita_reabastecimiento(self):
        # Limite: stock == reorden
        self.assertTrue(repuesto(stock=4).necesita_reabastecimiento())

    def test_por_encima_del_reorden_no_necesita_reabastecimiento(self):
        self.assertFalse(repuesto(stock=5).necesita_reabastecimiento())

    def test_justo_en_el_minimo_esta_en_estado_critico(self):
        # Limite: stock == minimo
        self.assertTrue(repuesto(stock=2).esta_en_estado_critico())

    def test_justo_en_el_maximo_no_tiene_sobrestock(self):
        # Limite: stock == maximo
        self.assertFalse(repuesto(stock=18).tiene_sobrestock())

    def test_por_encima_del_maximo_tiene_sobrestock(self):
        self.assertTrue(repuesto(stock=19).tiene_sobrestock())

    def test_sin_umbrales_ninguna_condicion_se_cumple(self):
        # Contrato: sin umbrales no hay con que comparar -> False
        rep = repuesto_sin_umbrales(stock=1)
        self.assertFalse(rep.necesita_reabastecimiento())
        self.assertFalse(rep.esta_en_estado_critico())
        self.assertFalse(rep.tiene_sobrestock())

    def test_sugerencia_de_compra_completa_hasta_el_maximo(self):
        self.assertEqual(repuesto(stock=3).calcular_sugerencia_compra(), 15.0)

    def test_sugerencia_de_compra_nunca_es_negativa(self):
        self.assertEqual(repuesto(stock=25).calcular_sugerencia_compra(), 0.0)

    def test_las_preguntas_no_modifican_el_repuesto(self):
        # Arrange
        rep = repuesto(stock=3)
        antes = copy.deepcopy(rep)

        # Act
        rep.necesita_reabastecimiento()
        rep.esta_en_estado_critico()
        rep.tiene_sobrestock()
        rep.calcular_sugerencia_compra()
        rep.estado()

        # Assert
        self.assertEqual(rep, antes)


class PruebaEstadoDelRepuesto(unittest.TestCase):
    """estado() deduce lo que se muestra en pantalla; no se guarda en la base."""

    def test_disponible(self):
        self.assertEqual(repuesto(stock=10).estado(), EstadoStock.DISPONIBLE)

    def test_hay_que_pedir_entre_minimo_y_reorden(self):
        self.assertEqual(repuesto(stock=3).estado(), EstadoStock.HAY_QUE_PEDIR)

    def test_urgente_en_el_minimo(self):
        self.assertEqual(repuesto(stock=2).estado(), EstadoStock.URGENTE)

    def test_agotado_con_stock_cero(self):
        self.assertEqual(repuesto(stock=0).estado(), EstadoStock.AGOTADO)

    def test_agotado_aunque_no_tenga_umbrales(self):
        # Excepcional: sin compras previas y sin stock sigue siendo "agotado"
        self.assertEqual(repuesto_sin_umbrales(stock=0).estado(), EstadoStock.AGOTADO)

    def test_sobrestock(self):
        self.assertEqual(repuesto(stock=30).estado(), EstadoStock.SOBRESTOCK)

    def test_sin_datos(self):
        self.assertEqual(repuesto_sin_umbrales(stock=5).estado(), EstadoStock.SIN_DATOS)

    def test_inactivo_tiene_prioridad_sobre_todo(self):
        # Un repuesto inactivo (baja logica) se ve como inactivo aunque este agotado
        self.assertEqual(repuesto(stock=0, activo=False).estado(), EstadoStock.INACTIVO)


class PruebaInvarianteAlerta(unittest.TestCase):
    """Contrato: tipo REORDEN, CRITICO o SOBRESTOCK y mensaje no vacio."""

    def test_alerta_valida_arranca_abierta(self):
        # Act
        alerta = Alerta(id=None, repuesto_id=1, fecha="2026-10-15", tipo="REORDEN",
                        mensaje="Hay que pedir")

        # Assert
        self.assertFalse(alerta.atendida)

    def test_tipo_desconocido_es_invalido(self):
        with self.assertRaises(AlertaInvalidaError):
            Alerta(id=None, repuesto_id=1, fecha="2026-10-15", tipo="AGOTADO", mensaje="x")

    def test_mensaje_vacio_es_invalido(self):
        with self.assertRaises(AlertaInvalidaError):
            Alerta(id=None, repuesto_id=1, fecha="2026-10-15", tipo="CRITICO", mensaje="  ")


if __name__ == "__main__":
    unittest.main()
