"""Entidades de dominio del sistema de gestión de stock.

Son las clases que representan las filas de las tablas núcleo del esquema
(ver docs/modelo_datos_y_limpieza.md). Por ahora son contenedores de datos;
a medida que se implementen los casos de uso (RF01-RF05) van a ir sumando
comportamiento propio (validaciones, cálculo de punto de reorden, etc.).
"""
from dataclasses import dataclass
from typing import Optional


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
    id: Optional[int]
    descripcion_normalizada: str
    marca_id: Optional[int] = None
    categoria_id: Optional[int] = None
    especificaciones: Optional[str] = None
    unidad_medida: str = "unidad"
    stock_minimo: float = 0.0
    stock_maximo: Optional[float] = None
    punto_reorden: Optional[float] = None
    stock_actual: float = 0.0
    activo: bool = True


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
