"""Entidades de dominio del sistema de gestión de stock.

Son las clases que representan las filas de las tablas del esquema. Además
de sus datos, cada entidad conoce sus propias reglas (diseño dirigido por
responsabilidades, Unidad 3): por ejemplo, un Repuesto sabe si está por
debajo de su punto de reorden, porque es quien tiene esa información.

Contratos (diseño por contratos, Unidades 3 y 4): los invariantes se
verifican al crear el objeto (__post_init__); si no se cumplen se lanza una
excepción propia, para que el error se detecte en el momento y con un
mensaje claro.
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------- Excepciones

class RepuestoInvalidoError(ValueError):
    """El repuesto no cumple su invariante (unidad o umbrales incoherentes)."""


class AlertaInvalidaError(ValueError):
    """La alerta no cumple su invariante (tipo desconocido o mensaje vacío)."""


class ConteoInvalidoError(ValueError):
    """La cantidad contada en el estante no tiene sentido: es negativa, o tiene
    decimales en un repuesto que se cuenta por unidad."""


# ---------------------------------------------------------------- Constantes

UNIDADES_MEDIDA = ("unidad", "cm")
TIPOS_MOVIMIENTO = ("INGRESO", "EGRESO", "AJUSTE")
TIPOS_ALERTA = ("REORDEN", "CRITICO", "SOBRESTOCK")


class EstadoStock(Enum):
    """Estado de un repuesto, deducido de sus datos (no se guarda en la base).

    El texto que ve el usuario en la pantalla está en
    `modules/alertas.py` (ETIQUETAS_ESTADO), no acá.
    """
    DISPONIBLE = "DISPONIBLE"
    HAY_QUE_PEDIR = "HAY_QUE_PEDIR"
    URGENTE = "URGENTE"
    AGOTADO = "AGOTADO"
    SOBRESTOCK = "SOBRESTOCK"
    SIN_DATOS = "SIN_DATOS"
    INACTIVO = "INACTIVO"


# ---------------------------------------------------------------- Entidades

@dataclass
class Proveedor:
    id: Optional[int]
    nombre: str
    contacto: Optional[str] = None
    telefono: Optional[str] = None
    email: Optional[str] = None
    activo: bool = True


@dataclass
class Marca:
    id: Optional[int]
    nombre: str


@dataclass
class Categoria:
    id: Optional[int]
    nombre: str
    descripcion: Optional[str] = None


@dataclass
class Repuesto:
    """Un producto de una categoría y una marca. Se identifica por
    (marca_id, codigo): el código es el del fabricante, tal como viene.

    Invariante:
      - unidad_medida es "unidad" o "cm".
      - Ningún umbral es negativo.
      - Si tiene umbrales: stock_minimo <= punto_reorden <= stock_maximo.
    """

    id: Optional[int]
    codigo: str
    marca_id: int
    categoria_id: int
    especificaciones: Optional[str] = None
    unidad_medida: str = "unidad"  # "unidad" | "cm"
    stock_minimo: float = 0.0
    stock_maximo: Optional[float] = None
    punto_reorden: Optional[float] = None
    stock_actual: float = 0.0
    activo: bool = True
    parametros_manuales: bool = False  # True = umbrales corregidos a mano

    def __post_init__(self):
        validar_umbrales(self.stock_minimo, self.punto_reorden, self.stock_maximo)
        if self.unidad_medida not in UNIDADES_MEDIDA:
            raise RepuestoInvalidoError(
                f"Unidad de medida '{self.unidad_medida}' inválida: debe ser 'unidad' o 'cm'."
            )

    # --- Preguntas sobre sí mismo (no modifican el objeto) ---------------

    def tiene_umbrales(self) -> bool:
        """True si tiene punto de reorden y stock máximo (calculados o cargados)."""
        return self.punto_reorden is not None and self.stock_maximo is not None

    def esta_agotado(self) -> bool:
        """True si no queda stock."""
        return self.stock_actual <= 0

    def necesita_reabastecimiento(self) -> bool:
        """True si el stock llegó al punto de reorden (o está por debajo).
        Sin umbrales devuelve False: no hay con qué comparar."""
        return self.tiene_umbrales() and self.stock_actual <= self.punto_reorden

    def esta_en_estado_critico(self) -> bool:
        """True si el stock llegó al mínimo de seguridad (o está por debajo)."""
        return self.tiene_umbrales() and self.stock_actual <= self.stock_minimo

    def tiene_sobrestock(self) -> bool:
        """True si el stock supera el máximo."""
        return self.tiene_umbrales() and self.stock_actual > self.stock_maximo

    def calcular_sugerencia_compra(self) -> float:
        """Cuánto pedir para volver al stock máximo (0 si no hace falta o no hay umbrales)."""
        if not self.tiene_umbrales():
            return 0.0
        return max(0.0, self.stock_maximo - self.stock_actual)

    def estado(self) -> EstadoStock:
        """Estado actual, en orden de prioridad: inactivo, agotado, sin datos,
        urgente, hay que pedir, sobrestock, disponible."""
        if not self.activo:
            return EstadoStock.INACTIVO
        if self.esta_agotado():
            return EstadoStock.AGOTADO
        if not self.tiene_umbrales():
            return EstadoStock.SIN_DATOS
        if self.esta_en_estado_critico():
            return EstadoStock.URGENTE
        if self.necesita_reabastecimiento():
            return EstadoStock.HAY_QUE_PEDIR
        if self.tiene_sobrestock():
            return EstadoStock.SOBRESTOCK
        return EstadoStock.DISPONIBLE

    # --- Conteo físico ----------------------------------------------------

    def ajuste_por_conteo(self, cantidad_contada: float, fecha: str) -> Optional["MovimientoStock"]:
        """Arma el AJUSTE que deja el stock del sistema igual a lo contado en el estante.

        El Repuesto es quien conoce su stock_actual, por eso sabe calcular la
        diferencia (diseño dirigido por responsabilidades). No guarda nada:
        de eso se encarga GestorInventarioBD.

        Pre:  el repuesto ya está guardado (tiene id), si no RepuestoInvalidoError;
              cantidad_contada >= 0 y, si la unidad es "unidad", sin decimales;
              si no, ConteoInvalidoError.
        Post: si lo contado coincide con el stock devuelve None (no hay nada que corregir);
              si no, un MovimientoStock de tipo AJUSTE con
              cantidad = contado - stock_actual (negativa si falta, positiva si sobra).
              No modifica el repuesto: el stock lo actualiza la base al guardar el movimiento.
        """
        if self.id is None:
            raise RepuestoInvalidoError("El repuesto todavía no está guardado: no se le puede registrar un conteo.")
        if cantidad_contada < 0:
            raise ConteoInvalidoError(f"La cantidad contada no puede ser negativa (se recibió {cantidad_contada}).")
        if self.unidad_medida == "unidad" and cantidad_contada != int(cantidad_contada):
            raise ConteoInvalidoError(
                f"Este repuesto se cuenta por unidad: la cantidad no puede tener decimales (se recibió {cantidad_contada})."
            )
        # round(…, 6): evita diferencias fantasma de punto flotante (ej. 0.1 + 0.2 - 0.3)
        diferencia = round(cantidad_contada - self.stock_actual, 6)
        if diferencia == 0:
            return None
        return MovimientoStock(id=None, repuesto_id=self.id, fecha=fecha, tipo="AJUSTE", cantidad=diferencia)


def validar_umbrales(stock_minimo: float, punto_reorden: Optional[float],
                     stock_maximo: Optional[float]) -> None:
    """Verifica que los umbrales sean coherentes; si no, lanza RepuestoInvalidoError.

    La usan Repuesto (al crearse) y GestorInventarioBD (antes de guardar
    umbrales nuevos), para que la regla esté escrita en un solo lugar.
    """
    for nombre, valor in (("stock mínimo", stock_minimo),
                          ("punto de reorden", punto_reorden),
                          ("stock máximo", stock_maximo)):
        if valor is not None and valor < 0:
            raise RepuestoInvalidoError(f"El {nombre} no puede ser negativo ({valor}).")
    if punto_reorden is not None and stock_maximo is not None:
        if not (stock_minimo <= punto_reorden <= stock_maximo):
            raise RepuestoInvalidoError(
                "Los umbrales deben cumplir mínimo ≤ punto de reorden ≤ máximo "
                f"(se recibió {stock_minimo} / {punto_reorden} / {stock_maximo})."
            )


@dataclass
class MovimientoStock:
    """Un renglón de la tabla de hechos: un ingreso, egreso o ajuste de
    stock. No hay cabecera de remito -no se trackea esa información más
    allá de la carga inicial-; cada movimiento es autocontenido."""

    id: Optional[int]
    repuesto_id: int
    fecha: str  # formato ISO yyyy-mm-dd
    tipo: str  # "INGRESO" | "EGRESO" | "AJUSTE"
    cantidad: float
    proveedor_id: Optional[int] = None  # solo tiene sentido en INGRESO
    codigo_proveedor_raw: Optional[str] = None
    origen: str = "manual"  # "carga_inicial" | "manual"


@dataclass
class Alerta:
    """Una fila de la tabla `alertas`.

    Invariante: tipo es REORDEN, CRITICO o SOBRESTOCK; mensaje no vacío.
    Se cierra a mano (atendida = True) y nunca se borra: queda como historial.
    """

    id: Optional[int]
    repuesto_id: int
    fecha: str  # formato ISO yyyy-mm-dd
    tipo: str  # "REORDEN" | "CRITICO" | "SOBRESTOCK"
    mensaje: str
    atendida: bool = False

    def __post_init__(self):
        if self.tipo not in TIPOS_ALERTA:
            raise AlertaInvalidaError(
                f"Tipo de alerta '{self.tipo}' inválido: debe ser uno de {', '.join(TIPOS_ALERTA)}."
            )
        if not self.mensaje or not self.mensaje.strip():
            raise AlertaInvalidaError("La alerta tiene que tener un mensaje.")
