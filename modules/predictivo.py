"""Modulo predictivo de demanda estacional y proyeccion de agotamiento.
Este modulo realiza el analisis cuantitativo sobre los movimientos de stock para realizar dos tipos de predicciones:
1. Agotamiento directo: dias o fechas estimadas para la perdida del stock de acuerdo al ritmo de consumo actual.
2. Proyeccion estacional anticipada: deteccion de picos de uso futuros de consumo y calculo del deficit proyectado.
3. Sugerencia de cantidad a comparar para reabasteser el stock para la fecha de consumo maximo"""

import sqlite3
from dataclasses import dataclass
from datetime import datatime, timedelta
from typing import List, Optional

@dataclass
class PronosticoAgotamiento:
    "Proyeccion de agotamiento del stock de forma lineal en el tiempo"
    repuesto_id: int    
    descripcion: str
    stock_actual: int
    consumo_diario_promedio: int
    dias_restantes: float #stock_actual/consumo_diario_promedio
    fecha_estimada_agotamiento: Optional[str]
    se_agota: bool 