"""Módulo de alertas de stock.

Diseño completo en `docs/modulo_alertas.md` y en el diagrama de clases
(`docs/diagrama_UML.md`, sección 2). Este archivo se construye por pasos:

- Paso 3: cálculo de umbrales a partir de la demanda.
    EstimadorDemanda (abstracta)  ->  EstimadorPorCompras
    CalculadoraParametros         ->  usa un EstimadorDemanda (patrón Strategy)
- Paso 4: ServicioParametrosStock (recalcula y guarda en la base).
- Paso 5: reglas de alerta, MotorAlertas y RepositorioAlertas.

Teoría aplicada (carpeta Teoría):
- Clases abstractas con `abc` y polimorfismo (Unidad 2).
- Patrón Strategy, Abierto/Cerrado e Inversión de dependencias (Unidad 3):
  la calculadora depende de la abstracción EstimadorDemanda, no de cómo se
  estima. Hoy se estima con compras; cuando haya egresos se agrega
  EstimadorPorEgresos sin tocar la calculadora.
- Diseño por contratos y excepciones propias (Unidades 3 y 4).

Fundamento de las fórmulas: Silver, Pyke y Thomas (2017), "Inventory and
Production Management in Supply Chains", 4.ª ed., CRC Press (punto de
reorden y stock de seguridad en sistemas de revisión continua).
"""
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import List, Optional

from modules.modelos import EstadoStock, MovimientoStock, Repuesto


# ---------------------------------------------------------------- Palabras para la interfaz
# En el código se usan los términos técnicos; en la pantalla, palabras del
# taller. Están en UN solo lugar para que la interfaz y los mensajes de las
# alertas digan siempre lo mismo. Para cambiar una frase, se cambia acá.

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


# ---------------------------------------------------------------- Resultados (objetos de valor)

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


# ---------------------------------------------------------------- Strategy: cómo se estima la demanda

class EstimadorDemanda(ABC):
    """Contrato común a todas las formas de estimar la demanda.

    Pre:  `movimientos` son todos del mismo repuesto.
    Post: devuelve una EstimacionDemanda con uso_diario >= 0 y compra_tipica >= 0.
    """

    @abstractmethod
    def estimar(self, movimientos: List[MovimientoStock]) -> EstimacionDemanda:
        ...

    @staticmethod
    def _verificar_mismo_repuesto(movimientos: List[MovimientoStock]) -> None:
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
        # Pre: el período tiene que tener al menos un día.
        if dias_periodo <= 0:
            raise ValueError(f"Los días del período tienen que ser mayores que 0 (se recibió {dias_periodo}).")
        self._dias_periodo = dias_periodo

    @property
    def dias_periodo(self) -> int:
        return self._dias_periodo

    def estimar(self, movimientos: List[MovimientoStock]) -> EstimacionDemanda:
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
        return self._dias_reposicion

    @property
    def dias_seguridad(self) -> int:
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


# ---------------------------------------------------------------- Guardado de umbrales

def dias_entre(fecha_desde: str, fecha_hasta: str) -> int:
    """Días entre dos fechas ISO (yyyy-mm-dd); como mínimo 1, para no dividir por cero."""
    return max(1, (date.fromisoformat(fecha_hasta) - date.fromisoformat(fecha_desde)).days)


class ServicioParametrosStock:
    """Recalcula los umbrales de los repuestos y los guarda en la base.

    Responsabilidad única: coordinar. El cálculo lo hace la CalculadoraParametros
    (que no conoce la base) y el guardado lo hace GestorInventarioBD.

    Contrato de recalcular(repuesto):
      - Si el repuesto está inactivo o sus umbrales se corrigieron a mano
        (parametros_manuales), NO cambia nada y devuelve None.
      - Si no hay datos para calcular (sin compras), NO cambia nada y devuelve None.
      - Si no, guarda los umbrales calculados (marcados como automáticos) y los devuelve.
    """

    def __init__(self, gestor, calculadora: CalculadoraParametros):
        self._gestor = gestor
        self._calculadora = calculadora

    @classmethod
    def desde_historial(cls, gestor, dias_reposicion: int = 7, dias_seguridad: int = 7) -> "ServicioParametrosStock":
        """Arma el servicio con el estimador por compras y el período real de los datos
        (del primer al último movimiento registrado)."""
        periodo = gestor.obtener_periodo_movimientos()
        dias = dias_entre(*periodo) if periodo else 1
        calculadora = CalculadoraParametros(EstimadorPorCompras(dias), dias_reposicion, dias_seguridad)
        return cls(gestor, calculadora)

    def recalcular(self, repuesto: Repuesto) -> Optional[ParametrosStock]:
        if not repuesto.activo or repuesto.parametros_manuales:
            return None
        parametros = self._calculadora.calcular(self._gestor.obtener_movimientos(repuesto.id))
        if parametros is None:
            return None
        self._gestor.actualizar_parametros_stock(
            repuesto.id,
            stock_minimo=parametros.stock_minimo,
            stock_maximo=parametros.stock_maximo,
            punto_reorden=parametros.punto_reorden,
            manual=False,
        )
        return parametros

    def recalcular_todos(self) -> int:
        """Recalcula todos los repuestos activos. Devuelve cuántos se actualizaron."""
        actualizados = 0
        for repuesto in self._gestor.obtener_repuestos(solo_activos=True):
            if self.recalcular(repuesto) is not None:
                actualizados += 1
        return actualizados
