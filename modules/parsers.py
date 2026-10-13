"""Módulo de normalización de comprobantes de Proveedores.
Este módulo implementa el patron Strategy + Factory para procesar comprobantes heterogéneos y convertirlos en objetos estandarizados para la BD"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class LineaNormalizada:
    """Representa una línea de comprobante con datos limpios y estandarizados"""
    proveedor: str
    codigo: str  
    marca: str
    categoria: Optional[str]  
    especificaciones: Optional[str]  
    descripcion: str  
    cantidad: float
    tipo_linea: str  


CARGOS_CONOCIDOS = {
    ("Rodamientos Iriondo S.R.L.", "000247MARCELITO"): "Embalaje/flete",
    ("Rodamientos Iriondo S.R.L.", "0007-SEGURO"): "Seguro de mercadería",
}

CATEGORIAS_POR_ABREVIATURA = {
    "TUBO": "TUBO",
    "HOR": "HORQUILLA",
    "HORQ": "HORQUILLA",
    "BUJE MANCHON": "BUJE MANCHON",
    "REP KIT S/BOL": "REP KIT S/BOL",
    "PERNO DE AJUSTES DE ESTRIAS": "PERNO DE AJUSTES DE ESTRIAS",
    "RESORTE P/ZAFE": "RESORTE P/ZAFE",
    "RETEN": "RETEN",
    "RODAMIENTO": "RODAMIENTO",
    "J. DE AGUJAS": "J. DE AGUJAS",
    "CRUCETA": "CRUCETA",
    "DISCO DENTADO": "DISCO DENTADO",
    "CADENA REFORZ.": "CADENA REFORZADA",
    "CADENA": "CADENA",
    "UNION CADENA": "UNION CADENA",
    "SOPORTE": "SOPORTE",
    "ANILLO SEEGER": "ANILLO SEEGER",
    "PIÑON": "PIÑON",
    "CRAPODINA": "CRAPODINA",
}


class CategoriaDesconocidaError(ValueError):
    """La descripción trae una categoría que no está en CATEGORIAS_POR_ABREVIATURA."""


def traducir_categoria(abreviatura: str, descripcion_original: str) -> str:
    """Devuelve la categoría unificada para una abreviatura exacta (ej. "CADENA REFORZ.")."""
    try:
        return CATEGORIAS_POR_ABREVIATURA[abreviatura]
    except KeyError as exc:
        raise CategoriaDesconocidaError(
            f"Categoría desconocida '{abreviatura}' en la descripción '{descripcion_original}'. "
            "Agregala a CATEGORIAS_POR_ABREVIATURA en modules/parsers.py."
        ) from exc


def separar_categoria_al_inicio(descripcion: str) -> Tuple[str, Optional[str]]:
    """Para descripciones del tipo "CATEGORÍA especificaciones..." (ED-MA, Produmat).

    Compara palabras completas y prueba primero las abreviaturas más largas,
    para que "HORQ K518..." no se confunda con "HOR" ni "CADENA REFORZ." con
    "CADENA". Devuelve (categoría unificada, especificaciones).
    """
    palabras = descripcion.split()
    abreviaturas = sorted(CATEGORIAS_POR_ABREVIATURA, key=lambda a: len(a.split()), reverse=True)
    for abreviatura in abreviaturas:
        palabras_abreviatura = abreviatura.split()
        if palabras[: len(palabras_abreviatura)] == palabras_abreviatura:
            resto = " ".join(palabras[len(palabras_abreviatura):])
            return CATEGORIAS_POR_ABREVIATURA[abreviatura], (resto or None)
    raise CategoriaDesconocidaError(
        f"No se reconoce la categoría al inicio de la descripción '{descripcion}'. "
        "Agregá su abreviatura a CATEGORIAS_POR_ABREVIATURA en modules/parsers.py."
    )


class ParserProveedor(ABC):
    """Interfaz común: recibe una fila cruda del Excel/CSV (dict con las
    columnas Fecha, N° Remito, Proveedor, Código, Descripción, Cantidad) y
    devuelve una LineaNormalizada, sea repuesto o cargo administrativo."""

    @abstractmethod
    def parsear(self, fila: dict) -> LineaNormalizada:
        ...


class ParserIriondo(ParserProveedor):

    def parsear(self, fila: dict) -> LineaNormalizada:
        proveedor = fila["Proveedor"]
        codigo = str(fila["Código"]).strip()
        descripcion = str(fila["Descripción"]).strip()

        if (proveedor, codigo) in CARGOS_CONOCIDOS:
            return LineaNormalizada(
                proveedor=proveedor,
                codigo=codigo,
                marca="I.A",
                categoria=None,
                especificaciones=None,
                descripcion=descripcion,
                cantidad=float(fila["Cantidad"]),
                tipo_linea="CARGO_ADMINISTRATIVO",
            )

        marca, separador, categoria_cruda = descripcion.partition(" - ")
        if not separador:
            raise ValueError(
                f"La descripción de Iriondo '{descripcion}' no tiene el formato 'MARCA - CATEGORÍA'."
            )
        return LineaNormalizada(
            proveedor=proveedor,
            codigo=codigo,
            marca=marca.strip(),
            categoria=traducir_categoria(categoria_cruda.strip(), descripcion),
            especificaciones=None,
            descripcion=descripcion,
            cantidad=float(fila["Cantidad"]),
            tipo_linea="PRODUCTO",
        )


class ParserEdMa(ParserProveedor):

    def parsear(self, fila: dict) -> LineaNormalizada:
        descripcion = str(fila["Descripción"]).strip()
        categoria, especificaciones = separar_categoria_al_inicio(descripcion)
        return LineaNormalizada(
            proveedor=fila["Proveedor"],
            codigo=str(fila["Código"]).strip(),
            marca="ED-MA",
            categoria=categoria,
            especificaciones=especificaciones,
            descripcion=descripcion,
            cantidad=float(fila["Cantidad"]),
            tipo_linea="PRODUCTO",
        )


class ParserProdumat(ParserProveedor):

    def parsear(self, fila: dict) -> LineaNormalizada:
        descripcion = str(fila["Descripción"]).strip()
        categoria, especificaciones = separar_categoria_al_inicio(descripcion)
        return LineaNormalizada(
            proveedor=fila["Proveedor"],
            codigo=str(fila["Código"]).strip(),
            marca="Produmat",
            categoria=categoria,
            especificaciones=especificaciones,
            descripcion=descripcion,
            cantidad=float(fila["Cantidad"]),
            tipo_linea="PRODUCTO",
        )


_PARSERS_POR_PROVEEDOR: dict[str, ParserProveedor] = {
    "Rodamientos Iriondo S.R.L.": ParserIriondo(),
    "Metalúrgica ED-MA S.R.L.": ParserEdMa(),
    "Produmat S.A.": ParserProdumat(),
}


def obtener_parser(nombre_proveedor: str) -> ParserProveedor:

    try:
        return _PARSERS_POR_PROVEEDOR[nombre_proveedor]
    except KeyError as exc:
        raise ValueError(
            f"No hay un parser configurado para el proveedor '{nombre_proveedor}'. "
            "Agregalo a _PARSERS_POR_PROVEEDOR en modules/parsers.py."
        ) from exc
