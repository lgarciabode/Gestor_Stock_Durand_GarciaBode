"""Catálogo de repuestos: ver, crear, corregir, activar/inactivar y umbrales a mano (Paso 11).

ServicioCatalogo coordina al gestor (base), al cálculo de umbrales y al motor
de alertas. La interfaz web solo arma los pedidos y muestra los resultados.

Reglas del taller (contratos):
  - Un repuesto se identifica por marca + código: no puede haber dos iguales.
    Por eso código y marca no se editan; si están mal, se crea otro.
  - Solo se inactiva un repuesto sin stock (cuando quedó en 0). Inactivar no
    borra nada: se puede volver a activar.
  - Umbrales a mano: tienen que cumplir mínimo <= punto de reorden <= máximo.
    Quedan marcados como manuales y el recálculo automático no los pisa,
    hasta que se elige "volver al cálculo automático".
  - Después de cambiar umbrales o activar, se revisan las alertas del repuesto.
"""
from dataclasses import dataclass
from typing import Callable, List, Optional

from modules.alertas import MotorAlertas, ParametrosStock, ServicioParametrosStock
from modules.crud import RepuestoNoEncontradoError
from modules.modelos import (UNIDADES_MEDIDA, Alerta, Categoria, EstadoStock, Marca,
                             Repuesto, RepuestoInvalidoError)


class CatalogoInvalidoError(ValueError):
    """El cambio pedido no se puede hacer (dato inválido o regla del taller)."""


@dataclass(frozen=True)
class FiltroCatalogo:
    texto: str = ""                       # busca en código, marca, categoría y especificaciones
    categoria_id: Optional[int] = None
    estado: Optional[EstadoStock] = None
    incluir_inactivos: bool = False


@dataclass(frozen=True)
class FichaRepuesto:
    """Un repuesto con los nombres de su marca y categoría (para mostrar)."""
    repuesto: Repuesto
    marca: str
    categoria: str

    @property
    def estado(self) -> EstadoStock:
        return self.repuesto.estado()

    def coincide(self, texto: str) -> bool:
        texto = texto.strip().lower()
        if not texto:
            return True
        donde = " ".join((self.repuesto.codigo, self.marca, self.categoria, self.repuesto.especificaciones or ""))
        return texto in donde.lower()


class ServicioCatalogo:

    def __init__(self, gestor, motor: MotorAlertas,
                 fabrica_parametros: Callable[..., ServicioParametrosStock] = ServicioParametrosStock.desde_historial):
        self._gestor = gestor
        self._motor = motor
        self._fabrica_parametros = fabrica_parametros

    # ------------------------------------------------------------ consultar

    def listar(self, filtro: FiltroCatalogo = FiltroCatalogo()) -> List[FichaRepuesto]:
        """Post: fichas que cumplen el filtro, ordenadas por categoría, marca y código."""
        marcas, categorias = self._nombres()
        fichas = [self._ficha(r, marcas, categorias)
                  for r in self._gestor.obtener_repuestos(solo_activos=not filtro.incluir_inactivos)]
        fichas = [
            f for f in fichas
            if f.coincide(filtro.texto)
            and (filtro.categoria_id is None or f.repuesto.categoria_id == filtro.categoria_id)
            and (filtro.estado is None or f.estado == filtro.estado)
        ]
        return sorted(fichas, key=lambda f: (f.categoria, f.marca, f.repuesto.codigo))

    def ficha(self, repuesto_id: int) -> FichaRepuesto:
        """Pre: el repuesto existe, si no RepuestoNoEncontradoError."""
        return self._ficha(self._repuesto(repuesto_id))

    # ------------------------------------------------------------ crear y corregir

    def crear(self, codigo: str, marca: str, categoria: str, especificaciones: str = "",
              unidad_medida: str = "unidad") -> int:
        """Da de alta un repuesto nuevo (stock 0, sin umbrales: "sin datos todavía").

        Marca y categoría se eligen por nombre; si no existen se crean (la
        categoría en mayúsculas, como las del histórico).
        Pre: código, marca y categoría no vacíos; unidad "unidad" o "cm";
             no existe otro repuesto con la misma marca y código.
        """
        codigo, marca, categoria = codigo.strip(), marca.strip(), categoria.strip().upper()
        if not codigo or not marca or not categoria:
            raise CatalogoInvalidoError("Completá el código, la marca y la categoría.")
        if unidad_medida not in UNIDADES_MEDIDA:
            raise CatalogoInvalidoError('La unidad tiene que ser "unidad" o "cm".')
        marca_id = self._buscar_o_crear_marca(marca)
        if self._gestor.obtener_repuesto_por_codigo(marca_id, codigo) is not None:
            raise CatalogoInvalidoError(f"Ya existe el repuesto {codigo} de la marca {marca}.")
        categoria_id = self._buscar_o_crear_categoria(categoria)
        return self._gestor.crear_repuestos(Repuesto(
            id=None, codigo=codigo, marca_id=marca_id, categoria_id=categoria_id,
            especificaciones=especificaciones.strip() or None, unidad_medida=unidad_medida,
        ))

    def corregir_datos(self, repuesto_id: int, categoria: str, especificaciones: str) -> None:
        """Corrige categoría y especificaciones (código y marca no: son su identidad)."""
        rep = self._repuesto(repuesto_id)
        if not categoria.strip():
            raise CatalogoInvalidoError("La categoría no puede quedar vacía.")
        rep.categoria_id = self._buscar_o_crear_categoria(categoria.strip().upper())
        rep.especificaciones = especificaciones.strip() or None
        self._gestor.actualizar_repuesto(rep)

    # ------------------------------------------------------------ activar / inactivar

    def inactivar(self, repuesto_id: int) -> None:
        """Pre: stock en 0 (regla del taller). Post: activo = False; no se borra nada."""
        rep = self._repuesto(repuesto_id)
        if rep.stock_actual != 0:
            raise CatalogoInvalidoError(
                f"Solo se inactiva un repuesto sin stock: {rep.codigo} todavía tiene {rep.stock_actual:g}. "
                "Si en el estante no hay, corregí primero el stock a 0 con la planilla de conteo."
            )
        rep.activo = False
        self._gestor.actualizar_repuesto(rep)

    def activar(self, repuesto_id: int) -> List[Alerta]:
        """Post: activo = True; se revisan sus alertas (puede volver con "Agotado")."""
        rep = self._repuesto(repuesto_id)
        rep.activo = True
        self._gestor.actualizar_repuesto(rep)
        return self._motor.revisar(self._repuesto(repuesto_id))

    # ------------------------------------------------------------ umbrales

    def fijar_umbrales(self, repuesto_id: int, minimo: float, reorden: float, maximo: float) -> List[Alerta]:
        """Umbrales elegidos por el taller.

        Pre: mínimo <= reorden <= máximo y ninguno negativo; si no, CatalogoInvalidoError.
        Post: quedan como manuales (el recálculo no los pisa); se revisan sus alertas.
        """
        self._repuesto(repuesto_id)
        try:
            self._gestor.actualizar_parametros_stock(repuesto_id, stock_minimo=minimo, stock_maximo=maximo,
                                                     punto_reorden=reorden, manual=True)
        except RepuestoInvalidoError as error:
            raise CatalogoInvalidoError(str(error)) from error
        return self._motor.revisar(self._repuesto(repuesto_id))

    def volver_a_automatico(self, repuesto_id: int) -> Optional[ParametrosStock]:
        """Saca la marca de "a mano" y recalcula con el historial de compras.

        Post: parametros_manuales = False. Devuelve los umbrales calculados, o
        None si no hay compras para calcular (quedan los que tenía).
        """
        rep = self._repuesto(repuesto_id)
        self._gestor.actualizar_parametros_stock(repuesto_id, stock_minimo=rep.stock_minimo,
                                                 stock_maximo=rep.stock_maximo,
                                                 punto_reorden=rep.punto_reorden, manual=False)
        parametros = self._fabrica_parametros(self._gestor).recalcular(self._repuesto(repuesto_id))
        self._motor.revisar(self._repuesto(repuesto_id))
        return parametros

    # ------------------------------------------------------------ auxiliares

    def _repuesto(self, repuesto_id: int) -> Repuesto:
        rep = self._gestor.obtener_repuesto_id(repuesto_id)
        if rep is None:
            raise RepuestoNoEncontradoError(f"No existe el repuesto con id {repuesto_id}.")
        return rep

    def _nombres(self) -> tuple:
        """id -> nombre de marcas y categorías (se consultan una sola vez)."""
        return ({m.id: m.nombre for m in self._gestor.obtener_marcas()},
                {c.id: c.nombre for c in self._gestor.obtener_categorias()})

    def _ficha(self, rep: Repuesto, marcas: Optional[dict] = None, categorias: Optional[dict] = None) -> FichaRepuesto:
        if marcas is None or categorias is None:
            marcas, categorias = self._nombres()
        return FichaRepuesto(rep, marcas.get(rep.marca_id, ""), categorias.get(rep.categoria_id, ""))

    def _buscar_o_crear_marca(self, nombre: str) -> int:
        for m in self._gestor.obtener_marcas():
            if m.nombre.lower() == nombre.lower():
                return m.id
        return self._gestor.crear_marca(Marca(id=None, nombre=nombre))

    def _buscar_o_crear_categoria(self, nombre: str) -> int:
        for c in self._gestor.obtener_categorias():
            if c.nombre.upper() == nombre:
                return c.id
        return self._gestor.crear_categoria(Categoria(id=None, nombre=nombre))
