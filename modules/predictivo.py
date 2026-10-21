"""Modulo predictivo de demanda estacional y proyeccion de agotamiento.
Este modulo realiza el analisis cuantitativo sobre los movimientos de stock para predicciones de demanda futura y estimacion de necesidad de reabastecimiento utilizando patrones Strategy y Factory
Se realizan dos tipos de predicciones:
1. Agotamiento directo y tasa de uso estimada mediante series temporales
2. Proyeccion acumulada a 30, 60 y 90 dias con suguerencia de compra"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, List, Dict, Optional
import pandas as pd
import numpy as np


class EstrategiaPrediccion(ABC):
    """Interfaz abstracta para definir las estrategias de prediccion de demanda"""

    @abstractmethod
    def predecir (self, serie_historia: pd.Series, periodos_a_proyectar: int) -> List[float]:
        """Devuelve una lista con la demanda estimada para los proximos periodos"""
        pass


class PrediccionEsporadica(EstrategiaPrediccion):
    """Estrategia de prediccion esporadica, intermitente, basada en el algoritmo de Croston"""

    def __init__(self, alpha: float = 0.1):
        """Inicializa el parametro de suavizado exponencial"""
        self.alpha = alpha

    def predecir(self, serie_historica: pd.Series, periodos_a_proyectar: int) -> List[float]:
        """Aplica la formula de Croston sobre los valores no nulos de la serie historica"""
        
        valores = serie_historica.values
        nz = np.where(valores > 0)[0]

        if len(nz) == 0:
            return [0.0]*periodos_a_proyectar

        demandas = valores[nz]
        intervalos = np.diff(np.insert(nz, 0, -1))

        z = float(demandas[0])
        p = float(intervalos[0])

        for i in range(1, len(nz)):
            z = z + self.alpha * (demandas[i]-z)
            p = p + self.alpha * (intervalos[i]-p)

        prediccion_mensual = float(z/p) if p!=0 else 0.0
        return [round(prediccion_mensual, 2)] * periodos_a_proyectar


class PrediccionDemandaRegular(EstrategiaPrediccion):
    """Estrategia de prediccion basada en el promedio movil ponderado exponencial, para repuestos en rotacion constante, le otorga mayor peso a los consumos mas recientes."""
    
    def __init__(self, span: int = 3):
        """Tamaño de la ventana del suavizado"""
        self.span = span

    def predecir(self, serie_historia: pd.Series, periodos_a_proyectar: int) -> List[float]:
        if serie_historia.empty:
            return [0.0] * periodos_a_proyectar

        prom = serie_historia.ewm(span = self.span).mean().iloc[-1]
        return [round(float(prom),2)] * periodos_a_proyectar

#Selector de estrategia a tomar
class PredictorDemandaFactory:
    """Se encarga de seleccionar la estrategia segun el historial del repuesto"""

    @staticmethod
    def obtener_estrategia(serie_historica: pd.Series) -> EstrategiaPrediccion:
    #Si mas del 70% de los periodos son cero, entonces es demanda intermitente
        """Evalua la proporcion de ceros en el periodo activo de la serie"""
        primer_mov = serie_historica.ne(0).idxmax() if (serie_historica != 0).any() else None

        if primer_mov is not None:
            serie_activa = serie_historica.loc[primer_mov:]
            proporcion_ceros = (serie_activa == 0).mean()
        else:
            proporcion_ceros = 1.0 

        if proporcion_ceros > 0.7:
            return PrediccionEsporadica()
        else:
            return PrediccionDemandaRegular()


class PreprocesadorPredicciones:
    """Clase utilidad para estructurar y homogeneizar series temporales"""

    @staticmethod
    def preparar_serie_mensual(
        df_movimientos: pd.DataFrame, repuesto_id: str, meses_historicos: int = 12, tipos_demanda: tuple = ('INGRESO', ), fecha_referencia: Optional[pd.Timestamp] = None) -> pd.Series:
        """Filtra movimientos por repuestos y tipo de demanda, agrupa por mes y rellena vacios con cer"""
        if df_movimientos.empty:
            return pd.Series(dtype = float)
        
        df_repuesto = df_movimientos[(df_movimientos['repuesto_id'].astype(str) == str(repuesto_id)) & (df_movimientos['tipo'].isin(tipos_demanda))].copy()

        if df_repuesto.empty:
            return pd.Series(dtype = float)

        df_repuesto['fecha'] = pd.to_datetime(df_repuesto['fecha'])
        #Agrupar por mes
        serie_mensual = df_repuesto.set_index('fecha').resample('MS')['cantidad'].sum()

        #Ordenar para asegurar todos los periodos en le rango
        if fecha_referencia is None:
            fecha_fin = pd.Timestamp.now().to_period('M').to_timestamp()
        else:
            fecha_fin = pd.Timestamp(fecha_referencia).to_period('M').to_timestamp()

        fecha_inicio = fecha_fin - pd.DateOffset(months = meses_historicos - 1)

        idx_completo = pd.date_range(start = fecha_inicio, end = fecha_fin, freq = 'MS')
        serie_completa = serie_mensual.reindex(idx_completo, fill_value = 0.0)

        return serie_completa


@dataclass
class ResultadoPrediccion:
    """Contenedor de datos (DTO) para los resultados del modelo predictivo."""
    repuesto_id: Any
    descripcion: str
    metodo_aplicado: str
    demanda_mensual_estimada: float
    proyeccion_por_mes: List[float]
    demanda_acumulada_dias: Dict[str, float]      # {'30d': X, '60d': Y, '90d': Z}
    sugerencia_recompra_dias: Dict[str, float]    # {'30d': X, '60d': Y, '90d': Z}


class ServicioPrediccion:
    """Orquestador principal de las predicciones coordina lectura, prediccion y calculo de reabastecimiento."""

    def __init__(self, gestor_bd = None, repositorio_datos = None):
        """gestor_bd es instancia de GestorInventarioBD del crud.py"""
        self.gestor_bd = gestor_bd or repositorio_datos

    def generar_predicciones_catalogo(self, meses_a_proyectar: int = 3, fecha_referencia: Optional[str] = None) -> List[ResultadoPrediccion]:
        """Genera proyecciones y sugerencias para todo el catalogo activo"""

        #Lectura directa desde el CRUD 
        if hasattr(self.gestor_bd, 'obtener_todos_los_movimientos_df'):
            df_movimientos = self.gestor_bd.obtener_todos_los_movimientos_df()
            df_catalogos = self.gestor_bd.obtener_catalogo_repuestos_df()
        else:
            df_movimientos = self.gestor_bd.obtener_todos_los_movimientos()
            df_catalogos = self.gestor_bd.obtener_catalogo_repuestos()

        resultados = []

        for _, repuesto in df_catalogos.iterrows():
            # Convertir a int si es posible (como un "1" de SQLite), si no dejarlo como string ("REP-001"):
            r_id = int(repuesto['id']) if str(repuesto['id']).isdigit() else repuesto['id']
            descripcion = repuesto.get('descripcion_normalizada', repuesto.get('descripcion', ''))

            serie = PreprocesadorPredicciones.preparar_serie_mensual(df_movimientos, r_id, fecha_referencia=fecha_referencia)
            estrategia = PredictorDemandaFactory.obtener_estrategia(serie)
            proyeccion = estrategia.predecir(serie, meses_a_proyectar)
            
            demanda_promedio = round(sum(proyeccion) / len(proyeccion), 2) if proyeccion else 0.0
            stock_actual = float(repuesto.get('stock_actual', 0.0))

            #Acumulados
            demanda_30d = round(proyeccion[0], 2) if len(proyeccion) >= 1 else 0.0
            demanda_60d = round(sum(proyeccion[:2]), 2) if len(proyeccion) >= 2 else demanda_30d
            demanda_90d = round(sum(proyeccion[:3]), 2) if len(proyeccion) >= 3 else demanda_60d

            #Sugerencias de compra restando stock actual
            recompra_30d = max(0.0, round(demanda_30d - stock_actual, 2))
            recompra_60d = max(0.0, round(demanda_60d - stock_actual, 2))
            recompra_90d = max(0.0, round(demanda_90d - stock_actual, 2))

            resultados.append(ResultadoPrediccion(
                repuesto_id=r_id,
                descripcion=descripcion,
                metodo_aplicado=estrategia.__class__.__name__,
                demanda_mensual_estimada=demanda_promedio,
                proyeccion_por_mes=proyeccion,
                demanda_acumulada_dias={'30d': demanda_30d, '60d': demanda_60d, '90d': demanda_90d},
                sugerencia_recompra_dias={'30d': recompra_30d, '60d': recompra_60d, '90d': recompra_90d}
            ))

        return resultados