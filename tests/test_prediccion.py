"""Pruebas del módulo predictivo (modules/predictivo.py).

Las clases de prueba usan unittest, patrón AAA (Arrange, Act, Assert), igual
que el resto de tests/. RepositorioSimulado reemplaza a la base de datos: el
servicio solo necesita que tenga los dos métodos de lectura.

Ejecutado como programa (python tests/test_prediccion.py --demo) imprime las
predicciones del repositorio simulado, como hacía la versión original.
"""
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.predictivo import (PrediccionDemandaRegular, PrediccionEsporadica,
                                PredictorDemandaFactory, PreprocesadorPredicciones,
                                ServicioPrediccion)

# Las series se arman hasta este mes, así las pruebas no dependen de la fecha de hoy.
FECHA_REFERENCIA = "2026-04-30"


class RepositorioSimulado:
    """Clase de prueba con los métodos que necesita ServicioPrediccion."""

    def obtener_catalogo_repuestos(self) -> pd.DataFrame:
        return pd.DataFrame([
            {'id': 'REP-001', 'descripcion': 'RODAMIENTO 6204 2RS', 'stock_actual': 2.0},
            {'id': 'REP-002', 'descripcion': 'ANILLO SEEGER 35', 'stock_actual': 10.0},
            {'id': 'REP-003', 'descripcion': 'SIN MOVIMIENTOS', 'stock_actual': 0.0}
        ])

    def obtener_todos_los_movimientos(self) -> pd.DataFrame:
        datos = [
            # REP-001: Demanda continua
            {'repuesto_id': 'REP-001', 'fecha': '2026-01-15', 'cantidad': 8, 'tipo': 'INGRESO'},
            {'repuesto_id': 'REP-001', 'fecha': '2026-02-10', 'cantidad': 7, 'tipo': 'INGRESO'},
            {'repuesto_id': 'REP-001', 'fecha': '2026-03-05', 'cantidad': 10, 'tipo': 'INGRESO'},
            {'repuesto_id': 'REP-001', 'fecha': '2026-04-12', 'cantidad': 6, 'tipo': 'INGRESO'},

            # REP-002: Demanda esporádica
            {'repuesto_id': 'REP-002', 'fecha': '2026-01-20', 'cantidad': 5, 'tipo': 'INGRESO'},
            {'repuesto_id': 'REP-002', 'fecha': '2026-04-18', 'cantidad': 4, 'tipo': 'INGRESO'},
        ]
        return pd.DataFrame(datos)


class PruebaEstrategias(unittest.TestCase):

    def test_esporadica_aplica_croston(self):
        # Arrange: se compran 6 cada 3 meses -> 2 por mes
        serie = pd.Series([0.0, 0.0, 6.0, 0.0, 0.0, 6.0])

        # Act
        proyeccion = PrediccionEsporadica().predecir(serie, 3)

        # Assert
        self.assertEqual(proyeccion, [2.0, 2.0, 2.0])

    def test_esporadica_sin_demanda_da_cero(self):
        self.assertEqual(PrediccionEsporadica().predecir(pd.Series([0.0, 0.0]), 2), [0.0, 0.0])

    def test_regular_con_demanda_constante_da_la_misma(self):
        proyeccion = PrediccionDemandaRegular().predecir(pd.Series([5.0, 5.0, 5.0, 5.0]), 3)
        self.assertEqual(proyeccion, [5.0, 5.0, 5.0])

    def test_regular_le_da_mas_peso_a_lo_reciente(self):
        prediccion = PrediccionDemandaRegular().predecir(pd.Series([1.0, 1.0, 1.0, 10.0]), 1)[0]
        self.assertGreater(prediccion, (1 + 1 + 1 + 10) / 4)   # más que el promedio simple

    def test_fabrica_elige_segun_la_proporcion_de_meses_sin_demanda(self):
        regular = pd.Series([3.0, 4.0, 0.0, 5.0])
        esporadica = pd.Series([3.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])
        self.assertIsInstance(PredictorDemandaFactory.obtener_estrategia(regular), PrediccionDemandaRegular)
        self.assertIsInstance(PredictorDemandaFactory.obtener_estrategia(esporadica), PrediccionEsporadica)


class PruebaPreprocesador(unittest.TestCase):

    def test_agrupa_por_mes_y_completa_con_ceros(self):
        # Act
        serie = PreprocesadorPredicciones.preparar_serie_mensual(
            RepositorioSimulado().obtener_todos_los_movimientos(), "REP-002",
            meses_historicos=4, fecha_referencia=FECHA_REFERENCIA)

        # Assert: enero 5, febrero y marzo sin compras, abril 4
        self.assertEqual(list(serie.values), [5.0, 0.0, 0.0, 4.0])

    def test_repuesto_sin_movimientos_da_serie_vacia(self):
        serie = PreprocesadorPredicciones.preparar_serie_mensual(
            RepositorioSimulado().obtener_todos_los_movimientos(), "REP-003")
        self.assertTrue(serie.empty)


class PruebaServicioPrediccion(unittest.TestCase):

    def setUp(self):
        servicio = ServicioPrediccion(RepositorioSimulado(), fecha_referencia=FECHA_REFERENCIA)
        self.resultados = {r.repuesto_id: r for r in servicio.generar_predicciones_catalogo(3)}

    def test_un_resultado_por_repuesto_con_su_descripcion(self):
        self.assertEqual(set(self.resultados), {"REP-001", "REP-002", "REP-003"})
        self.assertEqual(self.resultados["REP-001"].descripcion, "RODAMIENTO 6204 2RS")

    def test_acumulados_y_recompra_restan_el_stock(self):
        r = self.resultados["REP-001"]
        mensual = r.proyeccion_por_mes[0]
        self.assertAlmostEqual(r.demanda_acumulada_dias["90d"], round(3 * mensual, 2))
        self.assertAlmostEqual(r.sugerencia_recompra_dias["30d"], max(0.0, round(mensual - 2.0, 2)))

    def test_sin_movimientos_no_sugiere_comprar(self):
        r = self.resultados["REP-003"]
        self.assertEqual(r.demanda_mensual_estimada, 0.0)
        self.assertEqual(r.sugerencia_recompra_dias, {"30d": 0.0, "60d": 0.0, "90d": 0.0})

    def test_los_ajustes_del_conteo_no_cuentan_como_demanda(self):
        # Arrange: el mismo historial, más un AJUSTE grande que no es demanda
        class RepositorioConAjuste(RepositorioSimulado):
            def obtener_todos_los_movimientos(self):
                df = super().obtener_todos_los_movimientos().assign(tipo="INGRESO")
                ajuste = pd.DataFrame([{"repuesto_id": "REP-001", "fecha": "2026-04-20", "cantidad": -50, "tipo": "AJUSTE"}])
                return pd.concat([df, ajuste], ignore_index=True)

        # Act
        con_ajuste = ServicioPrediccion(RepositorioConAjuste(), fecha_referencia=FECHA_REFERENCIA)
        r = {x.repuesto_id: x for x in con_ajuste.generar_predicciones_catalogo(3)}["REP-001"]

        # Assert: da lo mismo que sin el ajuste
        self.assertEqual(r.proyeccion_por_mes, self.resultados["REP-001"].proyeccion_por_mes)


def mostrar_demo():
    print("=== EJECUTANDO TEST DE PREDECIR ===\n")

    # Instanciamos el repositorio y el servicio
    repo = RepositorioSimulado()
    servicio = ServicioPrediccion(gestor_bd=repo)

    # Ejecutamos la predicción
    resultados = servicio.generar_predicciones_catalogo(meses_a_proyectar=3, fecha_referencia = "2026-10-01")
    
    # Imprimimos los resultados
    for r in resultados:
        print(f"ID: {r.repuesto_id} | {r.descripcion}")
        print(f"  - Método aplicado   : {r.metodo_aplicado}")
        print(f"  - Demanda mensual   : {r.demanda_mensual_estimada} u/mes")
        print(f"  - Proyección        : {r.proyeccion_por_mes}")
        print(f"  - Demanda acumulada : 30d: {r.demanda_acumulada_dias['30d']}u | 60d: {r.demanda_acumulada_dias['60d']}u | 90d: {r.demanda_acumulada_dias['90d']}u")
        print(f"  - Recompra sugerida : 30d: {r.sugerencia_recompra_dias['30d']}u | 60d: {r.sugerencia_recompra_dias['60d']}u | 90d: {r.sugerencia_recompra_dias['90d']}u")
        print("-" * 60)


if __name__ == '__main__':
    if "--demo" in sys.argv:
        mostrar_demo()
    else:
        unittest.main()
