"""Plan de compras: junta la predicción de demanda con los datos del catálogo.

ServicioPrediccion (modules/predictivo.py) calcula, para cada repuesto, cuánto
se va a necesitar en 30, 60 y 90 días y cuánto habría que comprar. Esta clase
solo arma la lista para mostrar: le agrega marca, categoría y si el repuesto
ya se contó, filtra por horizonte y ordena.

Responsabilidades separadas (SRP, Unidad 3):
    - ServicioPrediccion: predecir (no sabe nada de la pantalla).
    - PlanDeCompras: preparar la lista que ve el usuario (no predice nada).

Aviso para quien lea los números: mientras no se termine el conteo inicial,
el stock de los repuestos sin contar es todo lo comprado desde enero, así
que la compra sugerida para ellos sale más baja de lo real.
"""
import math
from dataclasses import dataclass
from typing import List

from modules.modelos import Repuesto
from modules.predictivo import ResultadoPrediccion, ServicioPrediccion

HORIZONTES = (30, 60, 90)   # días que calcula ServicioPrediccion

# Nombre de cada estrategia en palabras del taller (lo muestra la pantalla).
NOMBRES_METODO = {
    "PrediccionDemandaRegular": "Uso regular",
    "PrediccionEsporadica": "Uso esporádico",
}


class HorizonteInvalidoError(ValueError):
    """Se pidió un horizonte que la predicción no calcula."""


@dataclass(frozen=True)
class FilaPlanCompras:
    repuesto: Repuesto
    marca: str
    categoria: str
    prediccion: ResultadoPrediccion
    contado: bool                     # True si su stock ya se corrigió con el conteo

    @property
    def metodo(self) -> str:
        return NOMBRES_METODO.get(self.prediccion.metodo_aplicado, self.prediccion.metodo_aplicado)

    def necesita(self, horizonte: int) -> float:
        """Demanda estimada para los próximos `horizonte` días.
        Por unidad se muestra con un decimal (ver a_comprar)."""
        demanda = self.prediccion.demanda_acumulada_dias[f"{horizonte}d"]
        return round(demanda, 1) if self.repuesto.unidad_medida == "unidad" else demanda

    def a_comprar(self, horizonte: int) -> float:
        """Compra sugerida para cubrir los próximos `horizonte` días.

        Los repuestos por unidad no se compran en fracciones: se redondea a
        unidades enteras. Antes se lleva la demanda a un decimal, porque la
        predicción redondea cada mes a 2 decimales y al sumarlos aparecen
        restos como 20,01 (= 3 x 6,67) que no son demanda real.
        Los repuestos por cm se devuelven tal como los calcula la predicción."""
        if self.repuesto.unidad_medida != "unidad":
            return self.prediccion.sugerencia_recompra_dias[f"{horizonte}d"]
        necesita = math.ceil(self.necesita(horizonte))
        return float(max(0, math.ceil(necesita - self.repuesto.stock_actual)))


class PlanDeCompras:

    def __init__(self, gestor, servicio: ServicioPrediccion):
        self._gestor = gestor
        self._servicio = servicio

    def filas(self, horizonte: int = 30, solo_a_comprar: bool = True) -> List[FilaPlanCompras]:
        """Pre: horizonte es 30, 60 o 90 (si no, HorizonteInvalidoError).
        Post: filas ordenadas por compra sugerida (mayor primero) y código.
        Con solo_a_comprar=True quedan solo las que tienen algo para comprar."""
        if horizonte not in HORIZONTES:
            raise HorizonteInvalidoError(f"El horizonte tiene que ser 30, 60 o 90 días (se pidió {horizonte}).")

        repuestos = {r.id: r for r in self._gestor.obtener_repuestos()}
        marcas = {m.id: m.nombre for m in self._gestor.obtener_marcas()}
        categorias = {c.id: c.nombre for c in self._gestor.obtener_categorias()}
        contados = {r.id for r in self._gestor.obtener_repuestos_contados()}

        filas = []
        for prediccion in self._servicio.generar_predicciones_catalogo(meses_a_proyectar=3):
            repuesto = repuestos.get(prediccion.repuesto_id)
            if repuesto is None:      # por si el catálogo cambió entre las dos lecturas
                continue
            fila = FilaPlanCompras(repuesto, marcas.get(repuesto.marca_id, ""),
                                   categorias.get(repuesto.categoria_id, ""), prediccion,
                                   repuesto.id in contados)
            if solo_a_comprar and fila.a_comprar(horizonte) <= 0:
                continue
            filas.append(fila)

        return sorted(filas, key=lambda f: (-f.a_comprar(horizonte), -f.necesita(horizonte), f.repuesto.codigo))
