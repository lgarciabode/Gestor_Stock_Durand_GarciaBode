import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Callable, List, Optional

from modules.modelos import Alerta, EstadoStock, MovimientoStock, Repuesto


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


# ---------------------------------------------------------------- qué condición dispara cada alerta

def _cantidad(repuesto: Repuesto, valor: float) -> str:
    """Formatea una cantidad con su unidad: "3 unidades", "1 unidad", "120 cm", "3,05 cm"."""
    numero = f"{valor:g}".replace(".", ",")
    if repuesto.unidad_medida == "cm":
        return f"{numero} cm"
    return f"{numero} unidad" if valor == 1 else f"{numero} unidades"


class ReglaAlerta(ABC):
    """Contrato común a todas las reglas (Liskov: todas se usan igual).

    evaluar(repuesto) -> bool: True si corresponde la alerta. No modifica el repuesto.
    mensaje(repuesto) -> str:  texto para el usuario, con palabras del taller.
    """

    tipo: str = ""

    @abstractmethod
    def evaluar(self, repuesto: Repuesto) -> bool:
        ...

    @abstractmethod
    def mensaje(self, repuesto: Repuesto) -> str:
        ...


class ReglaReorden(ReglaAlerta):
    """Hay que pedir: el stock llegó al punto de reorden, pero todavía no al mínimo.
    (Debajo del mínimo corresponde CRITICO, para no avisar dos veces lo mismo.)"""

    tipo = "REORDEN"

    def evaluar(self, repuesto: Repuesto) -> bool:
        return repuesto.necesita_reabastecimiento() and not repuesto.esta_en_estado_critico()

    def mensaje(self, repuesto: Repuesto) -> str:
        return (
            f"{ETIQUETAS_TIPO_ALERTA[self.tipo]} — {repuesto.codigo}: "
            f"quedan {_cantidad(repuesto, repuesto.stock_actual)} "
            f"({ETIQUETAS_UMBRALES['punto_reorden'].lower()} {_cantidad(repuesto, repuesto.punto_reorden)}). "
            f"Sugerencia: pedir {_cantidad(repuesto, repuesto.calcular_sugerencia_compra())}."
        )


class ReglaCritico(ReglaAlerta):
    """Urgente: el stock llegó al mínimo de seguridad (o se agotó)."""

    tipo = "CRITICO"

    def evaluar(self, repuesto: Repuesto) -> bool:
        return repuesto.esta_en_estado_critico()

    def mensaje(self, repuesto: Repuesto) -> str:
        sugerencia = f"Sugerencia: pedir {_cantidad(repuesto, repuesto.calcular_sugerencia_compra())}."
        if repuesto.esta_agotado():
            return f"{ETIQUETAS_ESTADO[EstadoStock.AGOTADO]} — {repuesto.codigo}: no queda stock. {sugerencia}"
        return (
            f"{ETIQUETAS_TIPO_ALERTA[self.tipo]} — {repuesto.codigo}: "
            f"quedan {_cantidad(repuesto, repuesto.stock_actual)} "
            f"({ETIQUETAS_UMBRALES['stock_minimo'].lower()}: {_cantidad(repuesto, repuesto.stock_minimo)}). "
            f"{sugerencia}"
        )


class ReglaSobrestock(ReglaAlerta):
    """Sobra stock: hay más que el máximo (dinero inmovilizado)."""

    tipo = "SOBRESTOCK"

    def evaluar(self, repuesto: Repuesto) -> bool:
        return repuesto.tiene_sobrestock()

    def mensaje(self, repuesto: Repuesto) -> str:
        return (
            f"{ETIQUETAS_TIPO_ALERTA[self.tipo]} — {repuesto.codigo}: "
            f"hay {_cantidad(repuesto, repuesto.stock_actual)} "
            f"({ETIQUETAS_UMBRALES['stock_maximo'].lower()} {_cantidad(repuesto, repuesto.stock_maximo)}). "
            f"No hace falta comprar."
        )


# ---------------------------------------------------------------- Motor de alertas

class MotorAlertas:
    """Aplica las reglas a un repuesto y crea las alertas que correspondan.

    Depende de la abstracción ReglaAlerta (no sabe qué reglas hay) y de un
    repositorio con los métodos existe_abierta(repuesto_id, tipo) y crear(alerta).
    Las reglas se crean afuera y se le pasan (agregación). Para sumar una
    alerta nueva (ej. SIN_ROTACION) alcanza con pasarle otra regla (Abierto/Cerrado).

    Contrato de revisar(repuesto):
      - Repuesto inactivo o sin umbrales -> [] (no se revisa).
      - Por cada regla que se cumple queda exactamente UNA alerta abierta de ese
        tipo: si ya había una, no se crea otra.
      - Devuelve solo las alertas NUEVAS.

    Uso típico, después de registrar un movimiento:
        gestor.registrar_movimiento(mov)
        motor.revisar(gestor.obtener_repuesto_id(mov.repuesto_id))
    """

    def __init__(self, reglas: List[ReglaAlerta], repositorio,
                 hoy: Callable[[], str] = lambda: date.today().isoformat()):
        if not reglas:
            raise ValueError("El motor necesita al menos una regla.")
        self._reglas = list(reglas)
        self._repositorio = repositorio
        self._hoy = hoy  # se puede reemplazar en las pruebas para tener una fecha fija

    def revisar(self, repuesto: Repuesto) -> List[Alerta]:
        if not repuesto.activo or not repuesto.tiene_umbrales():
            return []
        nuevas = []
        for regla in self._reglas:
            if regla.evaluar(repuesto) and not self._repositorio.existe_abierta(repuesto.id, regla.tipo):
                alerta = Alerta(id=None, repuesto_id=repuesto.id, fecha=self._hoy(),
                                tipo=regla.tipo, mensaje=regla.mensaje(repuesto))
                alerta.id = self._repositorio.crear(alerta)
                nuevas.append(alerta)
        return nuevas

    def revisar_todos(self, repuestos: List[Repuesto]) -> List[Alerta]:
        """Botón "revisar todo": revisa cada repuesto y devuelve todas las alertas nuevas."""
        nuevas = []
        for repuesto in repuestos:
            nuevas.extend(self.revisar(repuesto))
        return nuevas


def reglas_por_defecto() -> List[ReglaAlerta]:
    """Las tres reglas acordadas, de la más urgente a la menos urgente."""
    return [ReglaCritico(), ReglaReorden(), ReglaSobrestock()]
