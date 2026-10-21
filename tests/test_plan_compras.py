"""Pruebas de PlanDeCompras (modules/plan_compras.py).

Se usa un gestor y un servicio de predicción simulados: así se prueba solo
cómo se arma la lista (filtrar, ordenar, completar datos), no la predicción.
unittest puro, patrón AAA (Arrange, Act, Assert).
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.modelos import Categoria, Marca, Repuesto
from modules.plan_compras import HorizonteInvalidoError, PlanDeCompras
from modules.predictivo import ResultadoPrediccion


def _resultado(rep_id, mensual, recompra30, recompra90, metodo="PrediccionDemandaRegular"):
    return ResultadoPrediccion(
        repuesto_id=rep_id, descripcion="", metodo_aplicado=metodo,
        demanda_mensual_estimada=mensual, proyeccion_por_mes=[mensual] * 3,
        demanda_acumulada_dias={"30d": mensual, "60d": 2 * mensual, "90d": 3 * mensual},
        sugerencia_recompra_dias={"30d": recompra30, "60d": recompra30, "90d": recompra90},
    )


class GestorSimulado:
    def __init__(self):
        self.repuestos = [
            Repuesto(id=1, codigo="6204 2RS", marca_id=1, categoria_id=1, stock_actual=2),
            Repuesto(id=2, codigo="5339 LX", marca_id=2, categoria_id=2, stock_actual=20),
            Repuesto(id=3, codigo="ANILLO 35", marca_id=1, categoria_id=1, stock_actual=1),
        ]

    def obtener_repuestos(self):
        return self.repuestos

    def obtener_marcas(self):
        return [Marca(1, "ZKL"), Marca(2, "SAV")]

    def obtener_categorias(self):
        return [Categoria(1, "RODAMIENTO"), Categoria(2, "RETEN")]

    def obtener_repuestos_contados(self):
        return [self.repuestos[0]]


class ServicioSimulado:
    def generar_predicciones_catalogo(self, meses_a_proyectar=3):
        return [
            _resultado(1, 5.0, 3.0, 13.0),
            _resultado(2, 2.0, 0.0, 0.0, "PrediccionEsporadica"),
            _resultado(3, 8.0, 7.0, 23.0),
        ]


class PruebaPlanDeCompras(unittest.TestCase):

    def setUp(self):
        self.plan = PlanDeCompras(GestorSimulado(), ServicioSimulado())

    def test_solo_los_que_hay_que_comprar_ordenados_por_cantidad(self):
        # Act
        filas = self.plan.filas(horizonte=30)

        # Assert: el 5339 no necesita compra; primero el que más hay que comprar
        self.assertEqual([f.repuesto.codigo for f in filas], ["ANILLO 35", "6204 2RS"])
        self.assertEqual(filas[0].a_comprar(30), 7.0)

    def test_completa_marca_categoria_y_si_esta_contado(self):
        fila = next(f for f in self.plan.filas(30) if f.repuesto.id == 1)
        self.assertEqual((fila.marca, fila.categoria, fila.contado), ("ZKL", "RODAMIENTO", True))

    def test_ver_todos_incluye_los_que_alcanzan(self):
        filas = self.plan.filas(horizonte=30, solo_a_comprar=False)
        self.assertEqual(len(filas), 3)
        self.assertEqual(filas[-1].metodo, "Uso esporádico")

    def test_el_horizonte_cambia_la_cantidad(self):
        self.assertEqual(self.plan.filas(horizonte=90)[0].a_comprar(90), 23.0)

    def test_por_unidad_redondea_a_enteros_sin_restos_de_redondeo(self):
        # Arrange: 6,67 por mes durante 90 días = 20,01 y hay 20 en stock;
        # 2,4 por mes en 30 días con 0 en stock -> hay que comprar 3 (no 2,4)
        gestor = GestorSimulado()
        gestor.repuestos = [Repuesto(id=1, codigo="A", marca_id=1, categoria_id=1, stock_actual=20),
                            Repuesto(id=2, codigo="B", marca_id=1, categoria_id=1, stock_actual=0)]

        class Servicio:
            def generar_predicciones_catalogo(self, meses_a_proyectar=3):
                return [_resultado(1, 6.67, 0.0, 0.01), _resultado(2, 2.4, 2.4, 7.2)]

        # Act
        filas = {f.repuesto.codigo: f for f in PlanDeCompras(gestor, Servicio()).filas(90, solo_a_comprar=False)}

        # Assert
        self.assertEqual(filas["A"].a_comprar(90), 0.0)
        self.assertEqual(filas["B"].a_comprar(30), 3.0)

    def test_horizonte_invalido(self):
        with self.assertRaises(HorizonteInvalidoError):
            self.plan.filas(horizonte=45)


if __name__ == "__main__":
    unittest.main()
