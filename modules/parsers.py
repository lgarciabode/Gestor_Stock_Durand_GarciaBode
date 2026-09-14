from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class LineaNormalizada:
    proveedor: str
    codigo_proveedor: str
    codigo_interno_taller: Optional[str]
    marca: str
    descripcion: str
    cantidad: float
    tipo_linea: str  # "PRODUCTO" | "CARGO_ADMINISTRATIVO"

CARGOS_CONOCIDOS = {
    ("Rodamientos Iriondo S.R.L.", "000247MARCELITO"): "Embalaje/flete",
    ("Rodamientos Iriondo S.R.L.", "0007-SEGURO"): "Seguro de mercadería",
}


class ParserProveedor(ABC):
    """Interfaz común: recibe una fila cruda del Excel/CSV (dict con las
    columnas Fecha, N° Remito, Proveedor, Código, Descripción, Cantidad) y
    devuelve una LineaNormalizada, sea repuesto o cargo administrativo."""

    @abstractmethod
    def parsear(self, fila: dict) -> LineaNormalizada:
        ...


class ParserIriondo(ParserProveedor):
    """Rodamientos Iriondo S.R.L.

    `Código` ya es un identificador de fabricante razonablemente
    estandarizado (ej. "32212 JR"), se conserva tal cual.
    `Descripción` viene como "MARCA - TIPO" (ej. "SAV - RETEN"), salvo las
    filas de flete/seguro que traen el prefijo "I.A" en vez de una marca.
    """

    def parsear(self, fila: dict) -> LineaNormalizada:
        proveedor = fila["Proveedor"]
        codigo = str(fila["Código"]).strip()
        descripcion = str(fila["Descripción"]).strip()

        if (proveedor, codigo) in CARGOS_CONOCIDOS:
            return LineaNormalizada(
                proveedor=proveedor,
                codigo_proveedor=codigo,
                codigo_interno_taller=None,
                marca="I.A",
                descripcion=descripcion,
                cantidad=float(fila["Cantidad"]),
                tipo_linea="CARGO_ADMINISTRATIVO",
            )

        marca, separador, tipo = descripcion.partition(" - ")
        return LineaNormalizada(
            proveedor=proveedor,
            codigo_proveedor=codigo,
            codigo_interno_taller=None,
            marca=marca.strip() if separador else "SIN MARCA",
            descripcion=tipo.strip() if separador else descripcion,
            cantidad=float(fila["Cantidad"]),
            tipo_linea="PRODUCTO",
        )


class ParserEdMa(ParserProveedor):
    """Metalúrgica ED-MA S.R.L.

    `Código` viene compuesto: "código interno del taller / código de
    fabricante" (ej. "H-8025/1 / HF1800300000010"). ED-MA es la propia
    marca del ítem, por eso no hay separador de marca en `Descripción`.
    """

    def parsear(self, fila: dict) -> LineaNormalizada:
        crudo = str(fila["Código"]).strip()
        interno, separador, fabricante = crudo.partition(" / ")
        codigo_proveedor = fabricante.strip() if separador else interno.strip()
        codigo_interno = interno.strip() if separador else None

        return LineaNormalizada(
            proveedor=fila["Proveedor"],
            codigo_proveedor=codigo_proveedor,
            codigo_interno_taller=codigo_interno,
            marca="ED-MA",
            descripcion=str(fila["Descripción"]).strip(),
            cantidad=float(fila["Cantidad"]),
            tipo_linea="PRODUCTO",
        )


class ParserProdumat(ParserProveedor):
    """Produmat S.A.

    `Código` es un código propio numérico. Produmat es la propia marca,
    igual que ED-MA: no hay separador de marca en `Descripción`.
    """

    def parsear(self, fila: dict) -> LineaNormalizada:
        return LineaNormalizada(
            proveedor=fila["Proveedor"],
            codigo_proveedor=str(fila["Código"]).strip(),
            codigo_interno_taller=None,
            marca="Produmat",
            descripcion=str(fila["Descripción"]).strip(),
            cantidad=float(fila["Cantidad"]),
            tipo_linea="PRODUCTO",
        )


_PARSERS_POR_PROVEEDOR: dict[str, ParserProveedor] = {
    "Rodamientos Iriondo S.R.L.": ParserIriondo(),
    "Metalúrgica ED-MA S.R.L.": ParserEdMa(),
    "Produmat S.A.": ParserProdumat(),
}


def obtener_parser(nombre_proveedor: str) -> ParserProveedor:
    """Factory: devuelve el parser correspondiente al proveedor.

    Para sumar un proveedor nuevo: crear su clase ParserXxx(ParserProveedor)
    en este archivo y agregarla acá. Si el proveedor no está registrado,
    falla explícitamente en vez de adivinar un formato.
    """
    try:
        return _PARSERS_POR_PROVEEDOR[nombre_proveedor]
    except KeyError as exc:
        raise ValueError(
            f"No hay un parser configurado para el proveedor '{nombre_proveedor}'. "
            "Agregalo a _PARSERS_POR_PROVEEDOR en modules/parsers.py."
        ) from exc
