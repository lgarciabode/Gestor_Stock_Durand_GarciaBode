"""Punto de entrada de la aplicación.
Uso:
    python main.py
"""
from config import DATABASE_URL, RUTA_EXCEL_HISTORICO
from modules.base_datos import inicializar_si_hace_falta, obtener_conexion
from modules.crud import GestorInventarioBD
from modules.modelos import Proveedor



def main() -> None:
    print("=" * 60)
    print("INICIALIZANDO SISTEMA Y VERIFICANDO CARGA HISTÓRICA")
    print("=" * 60)

    # 1. Autoinicialización (crea esquema y ejecuta ETL si no existía)
    inicializar_si_hace_falta(DATABASE_URL, RUTA_EXCEL_HISTORICO)
    print(f"\nBase de datos lista en: {DATABASE_URL}\n")

    conexion = obtener_conexion(DATABASE_URL)
    try:
        gestor = GestorInventarioBD(conexion)
        # 2. Lectura del Estado Inicial
        print("-" * 60)
        print("ESTADO GENERAL DEL INVENTARIO (DATOS HISTÓRICOS)")
        print("-" * 60)
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

        # 3. Demostración de Operaciones CRUD (Alta, Modificación, Baja)
        print("\n" + "-" * 60)
        print("DEMOSTRACIÓN DE OPERACIONES CRUD (GESTIÓN DE PROVEEDORES)")
        print("-" * 60)

        # Alta (Create)
        nuevo_prov = Proveedor(
            id=None,
            nombre="TornoSur Herramientas S.A.",
            contacto="Juan Pérez",
            telefono="343-4556677",
            email="ventas@tornosur.com",
            activo=True
        )
        id_creado = gestor.crear_proveedor(nuevo_prov)
        print(f"Proveedor 'TornoSur Herramientas S.A.' insertado con ID: {id_creado}")

        # Modificación (Update)
        nuevo_prov.id = id_creado
        nuevo_prov.contacto = "Juan Pérez (Gerente Ventas)"
        gestor.actualizar_proveedor(nuevo_prov)
        print(f"Contacto de Proveedor ID {id_creado} actualizado.")

        # Baja Lógica (Soft Delete)
        gestor.desactivar_proveedor(id_creado)
        print(f"Proveedor ID {id_creado} deshabilitado (activo = 0).")

        # 4. Demostración de Parámetros de Stock
        print("\n" + "-" * 60)
        print("CONFIGURACIÓN DE PARÁMETROS DE CONTROL DE STOCK")
        print("-" * 60)
        if repuestos:
            ejemplo_rep = repuestos[0]
            print(f"Repuesto seleccionado: '{ejemplo_rep.descripcion_normalizada}' (ID: {ejemplo_rep.id})")
            print(f" - Stock Actual: {ejemplo_rep.stock_actual}")
            
            # Seteamos umbrales de seguridad
            gestor.actualizar_parametros_stock(
                repuesto_id=ejemplo_rep.id,
                stock_minimo=5.0,
                stock_maximo=50.0,
                punto_reorden=ejemplo_rep.stock_actual + 1.0  # Forzamos que quede bajo reorden para probar alerta
            )
            print("Parámetros actualizados: Stock Mínimo=5.0, Máximo=50.0, Punto Reorden seteo dinámico.")

            alertas = gestor.obtener_repuestos_bajo_reorden()
            print(f"Repuestos detectados bajo punto de reorden: {len(alertas)}")

    finally:
        conexion.close()


if __name__ == "__main__":
    main()
