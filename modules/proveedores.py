"""Proveedores: datos de contacto y a quién se le compra (Paso 13).

    ConsultaProveedores  -> solo lee: resumen de compras por proveedor y qué
                            repuestos se le compraron (responde "a qué
                            proveedores se recurre con mayor frecuencia").
    ServicioProveedores  -> alta, corrección de datos y activar/desactivar,
                            con sus reglas (contratos).

Precios: la base no los guarda (decisión de Cami, 21/10: "no por ahora"), así
que la comparación es por frecuencia, no por precio.

Una "compra" es un día en que se le compró a ese proveedor: el número de
remito no se guarda, y en el histórico cada remito es de un solo día.
Solo cuentan los ingresos vigentes (los anulados no).
"""
import re
import sqlite3
from dataclasses import dataclass
from datetime import date
from typing import List, Optional

from modules.modelos import Proveedor

# Ingresos vigentes: ni anulados ni anulaciones (ver modules/crud.py)
_INGRESOS_VIGENTES = """m.tipo = 'INGRESO' AND m.anula_id IS NULL
    AND m.id NOT IN (SELECT anula_id FROM movimientos_stock WHERE anula_id IS NOT NULL)"""


class ProveedorInvalidoError(ValueError):
    """El dato del proveedor no es válido (nombre vacío o repetido, email mal escrito)."""


class ProveedorNoEncontradoError(LookupError):
    """No existe un proveedor con ese id."""


@dataclass(frozen=True)
class ResumenProveedor:
    """Un proveedor con lo que se le compró."""
    proveedor: Proveedor
    compras: int            # días con compra (≈ remitos)
    lineas: int             # renglones de compra
    repuestos: int          # repuestos distintos
    unidades: float         # suma de lo que se cuenta por unidad
    centimetros: float      # suma de lo que se cuenta en cm (no se mezcla con unidades)
    primera: Optional[str]
    ultima: Optional[str]

    def dias_desde_ultima(self, hoy: date) -> Optional[int]:
        return (hoy - date.fromisoformat(self.ultima)).days if self.ultima else None


@dataclass(frozen=True)
class CompraDeRepuesto:
    """Cuánto se le compró de un repuesto a un proveedor."""
    repuesto_id: int
    codigo: str
    marca: str
    categoria: str
    veces: int
    cantidad: float
    unidad_medida: str
    ultima: str


class ConsultaProveedores:
    """Consultas de solo lectura sobre proveedores y sus compras."""

    def __init__(self, conexion: sqlite3.Connection):
        self.conexion = conexion

    def resumen(self, incluir_inactivos: bool = False) -> List[ResumenProveedor]:
        """Post: un resumen por proveedor, de al que más se le compra al que menos
        (los que no tienen compras quedan al final, por nombre)."""
        filas = self.conexion.execute(f"""
            SELECT p.*,
                   COUNT(DISTINCT m.fecha) AS compras,
                   COUNT(m.id) AS lineas,
                   COUNT(DISTINCT m.repuesto_id) AS repuestos,
                   COALESCE(SUM(CASE WHEN r.unidad_medida = 'unidad' THEN m.cantidad END), 0) AS unidades,
                   COALESCE(SUM(CASE WHEN r.unidad_medida = 'cm' THEN m.cantidad END), 0) AS centimetros,
                   MIN(m.fecha) AS primera, MAX(m.fecha) AS ultima
            FROM proveedores p
            LEFT JOIN movimientos_stock m ON m.proveedor_id = p.id AND {_INGRESOS_VIGENTES}
            LEFT JOIN repuestos r ON r.id = m.repuesto_id
            {"" if incluir_inactivos else "WHERE p.activo = 1"}
            GROUP BY p.id
            ORDER BY compras DESC, lineas DESC, p.nombre""").fetchall()
        return [
            ResumenProveedor(
                proveedor=_fila_a_proveedor(f), compras=f["compras"], lineas=f["lineas"], repuestos=f["repuestos"],
                unidades=f["unidades"], centimetros=f["centimetros"], primera=f["primera"], ultima=f["ultima"],
            )
            for f in filas
        ]

    def repuestos_comprados(self, proveedor_id: int) -> List[CompraDeRepuesto]:
        """Post: qué repuestos se le compraron, del más pedido al menos pedido."""
        filas = self.conexion.execute(f"""
            SELECT r.id, r.codigo, r.unidad_medida, ma.nombre AS marca, c.nombre AS categoria,
                   COUNT(*) AS veces, SUM(m.cantidad) AS cantidad, MAX(m.fecha) AS ultima
            FROM movimientos_stock m
            JOIN repuestos r  ON r.id = m.repuesto_id
            JOIN marcas ma    ON ma.id = r.marca_id
            JOIN categorias c ON c.id = r.categoria_id
            WHERE m.proveedor_id = ? AND {_INGRESOS_VIGENTES}
            GROUP BY r.id
            ORDER BY veces DESC, cantidad DESC, r.codigo""", (proveedor_id,)).fetchall()
        return [
            CompraDeRepuesto(f["id"], f["codigo"], f["marca"], f["categoria"], f["veces"], f["cantidad"],
                             f["unidad_medida"], f["ultima"])
            for f in filas
        ]


class ServicioProveedores:
    """Alta y corrección de proveedores. Nunca se borran: se desactivan."""

    def __init__(self, gestor):
        self._gestor = gestor

    def obtener(self, proveedor_id: int) -> Proveedor:
        """Pre: existe, si no ProveedorNoEncontradoError."""
        for p in self._gestor.obtener_proveedores(solo_activos=False):
            if p.id == proveedor_id:
                return p
        raise ProveedorNoEncontradoError(f"No existe el proveedor con id {proveedor_id}.")

    def crear(self, nombre: str, contacto: str = "", telefono: str = "", email: str = "") -> int:
        """Pre: nombre no vacío y que no exista otro igual (sin importar mayúsculas);
        email, si se escribe, con forma de email. Post: proveedor activo."""
        proveedor = self._validar(None, nombre, contacto, telefono, email)
        return self._gestor.crear_proveedor(proveedor)

    def corregir(self, proveedor_id: int, nombre: str, contacto: str = "", telefono: str = "", email: str = "") -> None:
        """Mismo contrato que crear; conserva si está activo o no."""
        actual = self.obtener(proveedor_id)
        proveedor = self._validar(proveedor_id, nombre, contacto, telefono, email)
        proveedor.activo = actual.activo
        self._gestor.actualizar_proveedor(proveedor)

    def desactivar(self, proveedor_id: int) -> None:
        """Deja de aparecer al cargar compras. Su historial no se toca."""
        self.obtener(proveedor_id)
        self._gestor.desactivar_proveedor(proveedor_id)

    def activar(self, proveedor_id: int) -> None:
        proveedor = self.obtener(proveedor_id)
        proveedor.activo = True
        self._gestor.actualizar_proveedor(proveedor)

    def _validar(self, proveedor_id: Optional[int], nombre: str, contacto: str, telefono: str, email: str) -> Proveedor:
        nombre, email = nombre.strip(), email.strip()
        if not nombre:
            raise ProveedorInvalidoError("El nombre del proveedor no puede quedar vacío.")
        for otro in self._gestor.obtener_proveedores(solo_activos=False):
            if otro.id != proveedor_id and otro.nombre.lower() == nombre.lower():
                raise ProveedorInvalidoError(f"Ya existe el proveedor {otro.nombre}.")
        if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
            raise ProveedorInvalidoError(f'"{email}" no parece un email (falta la @ o el dominio).')
        return Proveedor(id=proveedor_id, nombre=nombre, contacto=contacto.strip() or None,
                         telefono=telefono.strip() or None, email=email or None)


def _fila_a_proveedor(f: sqlite3.Row) -> Proveedor:
    return Proveedor(id=f["id"], nombre=f["nombre"], contacto=f["contacto"], telefono=f["telefono"],
                     email=f["email"], activo=bool(f["activo"]))
