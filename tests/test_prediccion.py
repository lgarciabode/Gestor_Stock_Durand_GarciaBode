import pandas as pd
from modules.predictivo import ServicioPrediccion, PreprocesadorPredicciones


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
            {'repuesto_id': 'REP-001', 'fecha': '2026-01-15', 'cantidad': 8},
            {'repuesto_id': 'REP-001', 'fecha': '2026-02-10', 'cantidad': 7},
            {'repuesto_id': 'REP-001', 'fecha': '2026-03-05', 'cantidad': 10},
            {'repuesto_id': 'REP-001', 'fecha': '2026-04-12', 'cantidad': 6},

            # REP-002: Demanda esporádica
            {'repuesto_id': 'REP-002', 'fecha': '2026-01-20', 'cantidad': 5},
            {'repuesto_id': 'REP-002', 'fecha': '2026-04-18', 'cantidad': 4},
        ]
        return pd.DataFrame(datos)


if __name__ == '__main__':
    print("=== EJECUTANDO TEST DE PREDECIR ===\n")
    
    # Instanciamos el repositorio y el servicio
    repo = RepositorioSimulado()
    servicio = ServicioPrediccion(repositorio_datos=repo)
    
    # Ejecutamos la predicción
    resultados = servicio.generar_predicciones_catalogo(meses_a_proyectar=3)
    
    # Imprimimos los resultados
for r in resultados:
    print(f"ID: {r.repuesto_id} | {r.descripcion}")
    print(f"  - Método aplicado   : {r.metodo_aplicado}")
    print(f"  - Demanda mensual   : {r.demanda_mensual_estimada} u/mes")
    print(f"  - Proyección        : {r.proyeccion_por_mes}")
    print(f"  - Demanda acumulada : 30d: {r.demanda_acumulada_dias['30d']}u | 60d: {r.demanda_acumulada_dias['60d']}u | 90d: {r.demanda_acumulada_dias['90d']}u")
    print(f"  - Recompra sugerida : 30d: {r.sugerencia_recompra_dias['30d']}u | 60d: {r.sugerencia_recompra_dias['60d']}u | 90d: {r.sugerencia_recompra_dias['90d']}u")
    print("-" * 60)