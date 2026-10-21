"""Conteo inicial del inventario con una planilla Excel.

Uso (desde la carpeta del proyecto):
    python apps/conteo_inicial.py generar            -> crea data/conteo_inicial.xlsx
    python apps/conteo_inicial.py aplicar            -> lee esa planilla y corrige el stock
    python apps/conteo_inicial.py aplicar otra.xlsx  -> lo mismo con otro archivo

"aplicar" es todo o nada: si una fila tiene un error, muestra la lista y no
guarda ningún cambio. Las filas sin "Cantidad contada" se saltean, así que se
puede contar de a partes y aplicar varias veces.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import BASE_DIR, DATABASE_URL, RUTA_EXCEL_HISTORICO
from modules.alertas import ETIQUETAS_TIPO_ALERTA, MotorAlertas, reglas_por_defecto
from modules.base_datos import inicializar_si_hace_falta, obtener_conexion
from modules.conteo import PlanillaConteo, ServicioConteoInicial
from modules.crud import GestorInventarioBD, RepositorioAlertas

RUTA_POR_DEFECTO = BASE_DIR / "data" / "conteo_inicial.xlsx"


def generar(gestor: GestorInventarioBD, ruta: Path) -> None:
    marcas = {m.id: m.nombre for m in gestor.obtener_marcas()}
    categorias = {c.id: c.nombre for c in gestor.obtener_categorias()}
    cantidad = PlanillaConteo().generar(ruta, gestor.obtener_repuestos(solo_activos=True), marcas, categorias)
    print(f"Planilla creada con {cantidad} repuestos: {ruta}")
    print('Completá la columna "Cantidad contada" y después corré: python apps/conteo_inicial.py aplicar')


def aplicar(gestor: GestorInventarioBD, conexion, ruta: Path) -> None:
    motor = MotorAlertas(reglas_por_defecto(), RepositorioAlertas(conexion))
    resultado = ServicioConteoInicial(gestor, motor).aplicar(PlanillaConteo().leer(ruta))
    if not resultado.aplicado:
        print("No se guardó nada. Corregí estas filas y volvé a aplicar:")
        for e in resultado.errores:
            print(f"  Fila {e.fila} ({e.codigo}): {e.mensaje}")
        return
    print(f"Stock corregido: {resultado.ajustados} | ya estaban bien: {resultado.sin_diferencia} "
          f"| sin contar: {resultado.sin_contar}")
    print(f"Umbrales recalculados: {resultado.umbrales_recalculados}")
    print(f"Alertas nuevas: {len(resultado.alertas_nuevas)}")
    for alerta in resultado.alertas_nuevas:
        print(f"  [{ETIQUETAS_TIPO_ALERTA[alerta.tipo]}] {alerta.mensaje}")


if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in ("generar", "aplicar"):
        print(__doc__)
        sys.exit(1)
    ruta = Path(sys.argv[2]) if len(sys.argv) > 2 else RUTA_POR_DEFECTO
    inicializar_si_hace_falta(DATABASE_URL, RUTA_EXCEL_HISTORICO)
    conexion = obtener_conexion(DATABASE_URL)
    try:
        gestor = GestorInventarioBD(conexion)
        if sys.argv[1] == "generar":
            generar(gestor, ruta)
        else:
            aplicar(gestor, conexion, ruta)
    finally:
        conexion.close()
