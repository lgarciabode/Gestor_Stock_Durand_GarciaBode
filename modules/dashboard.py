"""Dashboard: el estado del stock de un vistazo (Paso 14).

ConsultaDashboard solo lee y arma los números; la pantalla los dibuja.
Secciones (pedidas por Cami, 21/10):
  - Estado del stock y avance del conteo inicial.
  - Rotación: qué repuestos se mueven más y cuáles menos.
  - Stock inmovilizado: lo que sobra o no se mueve hace mucho (solo repuestos
    ya contados: los demás tienen el stock "inflado" de la carga histórica,
    mismo criterio que "Revisar todo").
  - Compras por mes y por proveedor.

Rotación: todavía no hay usos (egresos) cargados, así que se estima con las
compras, igual que el cálculo de umbrales (EstimadorPorCompras). Se compara
solo entre repuestos que se cuentan por unidad: los de cm usan otra escala.
"""
import sqlite3
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Callable, Dict, List, Optional, Tuple

from modules.alertas import EstimadorPorCompras, dias_entre
from modules.modelos import EstadoStock, Repuesto

DIAS_SIN_MOVIMIENTO = 90  # a partir de cuántos días sin moverse un repuesto se considera quieto

_VIGENTES = """m.anula_id IS NULL
    AND m.id NOT IN (SELECT anula_id FROM movimientos_stock WHERE anula_id IS NOT NULL)"""


@dataclass(frozen=True)
class FilaRotacion:
    repuesto: Repuesto
    marca: str
    categoria: str
    por_mes: float          # unidades por mes (estimado con las compras)


@dataclass(frozen=True)
class FilaInmovilizado:
    repuesto: Repuesto
    marca: str
    categoria: str
    exceso: float                       # unidades por encima del máximo (0 si no sobra)
    dias_sin_movimiento: Optional[int]  # desde el último movimiento vigente

    @property
    def motivos(self) -> List[str]:
        motivos = []
        if self.exceso > 0:
            motivos.append(f"Sobran {self.exceso:g}")
        if self.dias_sin_movimiento is not None and self.dias_sin_movimiento >= DIAS_SIN_MOVIMIENTO:
            motivos.append(f"Sin movimiento hace {self.dias_sin_movimiento} días")
        return motivos


@dataclass(frozen=True)
class FilaMes:
    mes: str          # "2026-03"
    compras: int      # días con compra
    lineas: int
    unidades: float

    @property
    def nombre(self) -> str:
        meses = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
        return f"{meses[int(self.mes[5:7]) - 1]} {self.mes[:4]}"


@dataclass(frozen=True)
class AvanceConteo:
    contados: int
    total: int

    @property
    def porcentaje(self) -> int:
        return round(100 * self.contados / self.total) if self.total else 0


class ConsultaDashboard:
    """Arma los números del dashboard. Solo lee.

    Colaboradores: la conexión (consultas de agregados) y el gestor (repuestos y
    sus movimientos). `hoy` se recibe para que las pruebas sean deterministas.
    """

    def __init__(self, conexion: sqlite3.Connection, gestor, hoy: Callable[[], date] = date.today):
        self.conexion = conexion
        self._gestor = gestor
        self._hoy = hoy
        self._nombres = (
            {m.id: m.nombre for m in gestor.obtener_marcas()},
            {c.id: c.nombre for c in gestor.obtener_categorias()},
        )

    # ------------------------------------------------------------ estado y conteo

    def estados(self) -> Dict[EstadoStock, int]:
        """Cuántos repuestos activos hay en cada estado."""
        return Counter(r.estado() for r in self._gestor.obtener_repuestos())

    def avance_conteo(self) -> AvanceConteo:
        return AvanceConteo(len(self._gestor.obtener_repuestos_contados()), len(self._gestor.obtener_repuestos()))

    # ------------------------------------------------------------ rotación

    def rotacion(self, cantidad: int = 10) -> Tuple[List[FilaRotacion], List[FilaRotacion]]:
        """Devuelve (los que más se mueven, los que menos), entre los repuestos
        por unidad que tienen compras. Post: cada lista tiene a lo sumo `cantidad`."""
        periodo = self._gestor.obtener_periodo_movimientos()
        if periodo is None:
            return [], []
        estimador = EstimadorPorCompras(dias_entre(*periodo))
        filas = []
        for rep in self._gestor.obtener_repuestos():
            if rep.unidad_medida != "unidad":
                continue
            uso_diario = estimador.estimar(self._gestor.obtener_movimientos(rep.id)).uso_diario
            if uso_diario > 0:
                filas.append(self._fila_rotacion(rep, uso_diario * 30))
        mas = sorted(filas, key=lambda f: (-f.por_mes, f.repuesto.codigo))[:cantidad]
        menos = sorted(filas, key=lambda f: (f.por_mes, f.repuesto.codigo))[:cantidad]
        return mas, menos

    # ------------------------------------------------------------ inmovilizado

    def inmovilizado(self, dias: int = DIAS_SIN_MOVIMIENTO) -> List[FilaInmovilizado]:
        """Repuestos YA CONTADOS con stock que sobran (por encima del máximo) o
        que no se movieron en `dias` días; los que más sobran o más tiempo
        llevan quietos, primero."""
        ultimos = dict(self.conexion.execute(
            f"SELECT m.repuesto_id, MAX(m.fecha) FROM movimientos_stock m WHERE {_VIGENTES} GROUP BY m.repuesto_id"
        ).fetchall())
        hoy = self._hoy()
        filas = []
        for rep in self._gestor.obtener_repuestos_contados():
            if rep.stock_actual <= 0:
                continue
            exceso = rep.stock_actual - rep.stock_maximo if rep.tiene_sobrestock() else 0
            ultimo = ultimos.get(rep.id)
            quieto = (hoy - date.fromisoformat(ultimo)).days if ultimo else None
            if exceso > 0 or (quieto is not None and quieto >= dias):
                marca, categoria = self._nombre(rep)
                filas.append(FilaInmovilizado(rep, marca, categoria, exceso, quieto))
        return sorted(filas, key=lambda f: (-f.exceso, -(f.dias_sin_movimiento or 0)))

    # ------------------------------------------------------------ compras

    def compras_por_mes(self) -> List[FilaMes]:
        """Compras (ingresos vigentes) agrupadas por mes, del más viejo al más nuevo."""
        filas = self.conexion.execute(f"""
            SELECT substr(m.fecha, 1, 7) AS mes, COUNT(DISTINCT m.fecha || '-' || COALESCE(m.proveedor_id, 0)) AS compras,
                   COUNT(*) AS lineas,
                   COALESCE(SUM(CASE WHEN r.unidad_medida = 'unidad' THEN m.cantidad END), 0) AS unidades
            FROM movimientos_stock m JOIN repuestos r ON r.id = m.repuesto_id
            WHERE m.tipo = 'INGRESO' AND {_VIGENTES}
            GROUP BY mes ORDER BY mes""").fetchall()
        return [FilaMes(f["mes"], f["compras"], f["lineas"], f["unidades"]) for f in filas]

    # ------------------------------------------------------------ auxiliares

    def _nombre(self, rep: Repuesto) -> Tuple[str, str]:
        marcas, categorias = self._nombres
        return marcas.get(rep.marca_id, ""), categorias.get(rep.categoria_id, "")

    def _fila_rotacion(self, rep: Repuesto, por_mes: float) -> FilaRotacion:
        marca, categoria = self._nombre(rep)
        return FilaRotacion(rep, marca, categoria, round(por_mes, 1))
