
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
    """Un producto de una categoría y una marca. Se identifica por
    (marca_id, codigo): el código es el del fabricante, tal como viene."""

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


@dataclass
class MovimientoStock:
    """Un renglón de la tabla de hechos: un ingreso, egreso o ajuste de
    stock. No hay cabecera de remito -no se trackea esa información más
    allá de la carga inicial-; cada movimiento es autocontenido."""

    id: Optional[int]
    repuesto_id: int
    fecha: str  
    tipo: str  
    cantidad: float
    proveedor_id: Optional[int] = None  
    codigo_proveedor_raw: Optional[str] = None
    origen: str = "manual"  
