"""Punto de entrada de la aplicación.
Uso:
    python main.py
"""
from config import DATABASE_URL, RUTA_EXCEL_HISTORICO
from modules.base_datos import inicializar_si_hace_falta, obtener_conexion
from modules.crud import GestorInventarioBD


def main() -> None:
    inicializar_si_hace_falta(DATABASE_URL, RUTA_EXCEL_HISTORICO)
    print(f"\nBase de datos lista en: {DATABASE_URL}\n")

    conexion = obtener_conexion(DATABASE_URL)
    try:
        gestor = GestorInventarioBD(conexion)

        proveedores = gestor.obtener_proveedores(solo_activos=False)
        repuestos = gestor.obtener_repuestos(solo_activos=False)
        bajo_reorden = gestor.obtener_repuestos_bajo_reorden()
        total_movimientos = conexion.execute(
            "SELECT COUNT(*) FROM movimientos_stock"
        ).fetchone()[0]

        print(f"Proveedores cargados ({len(proveedores)}):")
        for proveedor in proveedores:
            estado = "activo" if proveedor.activo else "inactivo"
            print(f"  - {proveedor.nombre} ({estado})")

        print(f"\nRepuestos en catálogo: {len(repuestos)}")
        print(f"Movimientos de stock registrados: {total_movimientos}")
        print(f"Repuestos bajo punto de reorden: {len(bajo_reorden)}")
    finally:
        conexion.close()


if __name__ == "__main__":
    main()
