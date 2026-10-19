
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional

from modules.modelos import EstadoStock, MovimientoStock


# ---------------------------------------------------------------- Palabras para la interfaz

ETIQUETAS_UMBRALES = {
    "punto_reorden": "Pedir cuando queden",
    "stock_minimo": "Mínimo de seguridad",
    "stock_maximo": "No tener más de",
}

ETIQUETAS_TIPO_ALERTA = {
    "REORDEN": "Hay que pedir",
    "CRITICO": "Urgente: queda muy poco",
    "SOBRESTOCK": "Sobra stock",
}

ETIQUETA_ATENDER_ALERTA = "Ya lo pedí"

ETIQUETAS_ESTADO = {
    EstadoStock.DISPONIBLE: "Disponible",
    EstadoStock.HAY_QUE_PEDIR: "Hay que pedir",
    EstadoStock.URGENTE: "Urgente: queda muy poco",
    EstadoStock.AGOTADO: "Agotado",
    EstadoStock.SOBRESTOCK: "Sobra stock",
    EstadoStock.SIN_DATOS: "Sin datos todavía",
    EstadoStock.INACTIVO: "Inactivo",
}


# ---------------------------------------------------------------- Excepciones

class ParametrosInvalidosError(ValueError):
    """Los días de reposición o de seguridad no tienen sentido (L <= 0 o S < 0)."""


# ---------------------------------------------------------------- Resultados 

@dataclass(frozen=True)
class EstimacionDemanda:
    """Cuánto se usa un repuesto: por día y cuánto se suele comprar de una vez."""
    uso_diario: float
    compra_tipica: float


@dataclass(frozen=True)
class ParametrosStock:
    """Umbrales calculados para un repuesto (en la unidad del repuesto)."""
    stock_minimo: float
    punto_reorden: float
    stock_maximo: float


# ---------------------------------------------------------------- cómo se estima la demanda

class EstimadorDemanda(ABC):
    """Contrato común a todas las formas de estimar la demanda.

    Pre:  `movimientos` son todos del mismo repuesto.
    Post: devuelve una EstimacionDemanda con uso_diario >= 0 y compra_tipica >= 0.
    """

    @abstractmethod
    def estimar(self, movimientos: List[MovimientoStock]) -> EstimacionDemanda:
        """Devuelve la estimación de demanda a partir de los movimientos de stock del repuesto."""
        pass

    @staticmethod
    def _verificar_mismo_repuesto(movimientos: List[MovimientoStock]) -> None:
        """Verifica que todos los movimientos sean del mismo repuesto; si no, lanza ValueError."""
        if len({m.repuesto_id for m in movimientos}) > 1:
            raise ValueError("Los movimientos a estimar tienen que ser de un solo repuesto.")


class EstimadorPorCompras(EstimadorDemanda):
    """Estima la demanda con las compras (INGRESOS), porque todavía no hay egresos.

    Supuesto: a largo plazo, lo que el taller compra es aproximadamente lo que usa.
      uso_diario    = unidades compradas / días del período con datos
      compra_tipica = unidades compradas / cantidad de compras
    Una "compra" = un día con ingresos (dos renglones del mismo día cuentan una vez).
    """

    def __init__(self, dias_periodo: int):
        if dias_periodo <= 0:
            raise ValueError(f"Los días del período tienen que ser mayores que 0 (se recibió {dias_periodo}).")
        self._dias_periodo = dias_periodo

    @property
    def dias_periodo(self) -> int:
        """Devuelve la cantidad de días del período que se está considerando para estimar la demanda."""
        return self._dias_periodo

    def estimar(self, movimientos: List[MovimientoStock]) -> EstimacionDemanda:
        """Post: uso_diario >= 0 y compra_tipica >= 0; si no hay ingresos, ambos = 0."""
        self._verificar_mismo_repuesto(movimientos)
        ingresos = [m for m in movimientos if m.tipo == "INGRESO"]
        if not ingresos:
            return EstimacionDemanda(uso_diario=0.0, compra_tipica=0.0)
        unidades = sum(m.cantidad for m in ingresos)
        cantidad_compras = len({m.fecha for m in ingresos})
        return EstimacionDemanda(
            uso_diario=unidades / self._dias_periodo,
            compra_tipica=unidades / cantidad_compras,
        )


# ---------------------------------------------------------------- Cálculo de umbrales

def _redondear_hacia_arriba(valor: float) -> float:
    """Redondea hacia arriba (no hay fracciones de repuesto y el colchón no se achica).
    Antes descarta errores de coma flotante: 4.0000000001 tiene que dar 4, no 5."""
    return float(math.ceil(round(valor, 6)))


class CalculadoraParametros:
    """Convierte la demanda estimada en los tres umbrales de un repuesto.

      stock_minimo  = d × S
      punto_reorden = d × L + stock_minimo
      stock_maximo  = punto_reorden + compra_tipica
    (d = uso diario, L = días de reposición, S = días de seguridad), cada uno
    redondeado hacia arriba.

    Depende de la abstracción EstimadorDemanda (inversión de dependencias): se le
    pasa la estrategia al crearla (agregación).
    """

    def __init__(self, estimador: EstimadorDemanda, dias_reposicion: int = 7, dias_seguridad: int = 7):
        # Pre: L > 0 y S >= 0.
        if dias_reposicion <= 0:
            raise ParametrosInvalidosError(
                f"Los días de reposición tienen que ser mayores que 0 (se recibió {dias_reposicion})."
            )
        if dias_seguridad < 0:
            raise ParametrosInvalidosError(
                f"Los días de seguridad no pueden ser negativos (se recibió {dias_seguridad})."
            )
        self._estimador = estimador
        self._dias_reposicion = dias_reposicion
        self._dias_seguridad = dias_seguridad

    @property
    def dias_reposicion(self) -> int:
        """Devuelve la cantidad de días de reposición que se está considerando para calcular los umbrales."""
        return self._dias_reposicion

    @property
    def dias_seguridad(self) -> int:
        """Devuelve la cantidad de días de seguridad que se está considerando para calcular los umbrales."""
        return self._dias_seguridad

    def calcular(self, movimientos: List[MovimientoStock]) -> Optional[ParametrosStock]:
        """Post: None si no hay uso (sin datos para calcular); si no,
        mínimo <= reorden <= máximo, todos enteros y no negativos
        (mínimo >= 1 cuando hay días de seguridad)."""
        estimacion = self._estimador.estimar(movimientos)
        d = estimacion.uso_diario
        if d <= 0:
            return None
        minimo = d * self._dias_seguridad
        reorden = d * self._dias_reposicion + minimo
        maximo = reorden + estimacion.compra_tipica
        return ParametrosStock(
            stock_minimo=_redondear_hacia_arriba(minimo),
            punto_reorden=_redondear_hacia_arriba(reorden),
            stock_maximo=_redondear_hacia_arriba(maximo),
        )
