from config import DATABASE_URL, RUTA_EXCEL_HISTORICO
from modules.base_datos import inicializar_si_hace_falta, obtener_conexion
from modules.crud import GestorInventarioBD
from modules.modelos import Proveedor


def menu_proveedores(gestor: GestorInventarioBD) -> None:
    while True:
        print("\n" + "=" * 50)
        print("GESTIÓN DE PROVEEDORES")
        print("=" * 50)
        print("1. Listar todos los proveedores")
        print("2. Registrar nuevo proveedor")
        print("3. Modificar datos de un proveedor")
        print("4. Desactivar proveedor")
        print("0. Volver al Menú Principal")
        
        opcion = input("\nSeleccione una opción: ").strip()

        if opcion == "1":
            provs = gestor.obtener_proveedores(solo_activos=False)
            print("\n--- LISTADO DE PROVEEDORES ---")
            for p in provs:
                estado = "Activo" if p.activo else "Inactivo"
                print(f"ID {p.id}: {p.nombre} | Contacto: {p.contacto or 'N/A'} | Tel: {p.telefono or 'N/A'} | [{estado}]")

        elif opcion == "2":
            print("\n--- NUEVO PROVEEDOR ---")
            nombre = input("Nombre de la empresa: ").strip()
            if not nombre:
                print("El nombre no puede estar vacío.")
                continue
            contacto = input("Nombre de contacto (opcional): ").strip() or None
            telefono = input("Teléfono (opcional): ").strip() or None
            email = input("Email (opcional): ").strip() or None
            
            nuevo = Proveedor(id=None, nombre=nombre, contacto=contacto, telefono=telefono, email=email, activo=True)
            new_id = gestor.crear_proveedor(nuevo)
            print(f"Proveedor '{nombre}' registrado exitosamente con ID: {new_id}")

        elif opcion == "3":
            print("\n--- MODIFICAR PROVEEDOR ---")
            prov_id = input("Ingrese el ID del proveedor a modificar: ").strip()
            if prov_id.isdigit():
                p_id = int(prov_id)
                provs = [p for p in gestor.obtener_proveedores(solo_activos=False) if p.id == p_id]
                if provs:
                    p = provs[0]
                    print(f"Editando: {p.nombre}")
                    p.contacto = input(f"Nuevo contacto [{p.contacto}]: ").strip() or p.contacto
                    p.telefono = input(f"Nuevo teléfono [{p.telefono}]: ").strip() or p.telefono
                    p.email = input(f"Nuevo email [{p.email}]: ").strip() or p.email
                    gestor.actualizar_proveedor(p)
                    print("Proveedor actualizado correctamente.")
                else:
                    print("No se encontró ningún proveedor con ese ID.")

        elif opcion == "4":
            print("\n--- BAJA LÓGICA DE PROVEEDOR ---")
            prov_id = input("Ingrese el ID del proveedor a desactivar: ").strip()
            if prov_id.isdigit():
                gestor.desactivar_proveedor(int(prov_id))
                print(f"Proveedor ID {prov_id} desactivado correctamente (activo = 0).")

        elif opcion == "0":
            break


def menu_stock_parametros(gestor: GestorInventarioBD) -> None:
    while True:
        print("\n" + "=" * 50)
        print("GESTIÓN DE STOCK Y PARÁMETROS")
        print("=" * 50)
        print("1. Listar repuestos en catálogo")
        print("2. Ver repuestos bajo Punto de Reorden")
        print("3. Actualizar parámetros de stock (Min, Max, Reorden)")
        print("0. Volver al Menú Principal")

        opcion = input("\nSeleccione una opción: ").strip()

        if opcion == "1":
            repuestos = gestor.obtener_repuestos(solo_activos=False)
            print("\n--- CATÁLOGO DE REPUESTOS ---")
            for r in repuestos:
                print(f"ID {r.id}: {r.descripcion_normalizada} | Stock: {r.stock_actual} {r.unidad_medida} | Mín: {r.stock_minimo} | Reorden: {r.punto_reorden}")

        elif opcion == "2":
            alertas = gestor.obtener_repuestos_bajo_reorden()
            print(f"\n--- REPUESTOS BAJO REORDEN ({len(alertas)}) ---")
            for r in alertas:
                print(f"ID {r.id}: {r.descripcion_normalizada} | Stock Actual: {r.stock_actual} | Punto Reorden: {r.punto_reorden}")

        elif opcion == "3":
            rep_id = input("Ingrese el ID del repuesto a configurar: ").strip()
            if rep_id.isdigit():
                r_id = int(rep_id)
                s_min = float(input("Ingrese nuevo Stock Mínimo: ") or 0)
                s_max = float(input("Ingrese nuevo Stock Máximo: ") or 0)
                p_reorden = float(input("Ingrese nuevo Punto de Reorden: ") or 0)
                
                gestor.actualizar_parametros_stock(r_id, s_min, s_max, p_reorden)
                print(f"Umbrales de stock actualizados para el Repuesto ID {r_id}.")

        elif opcion == "0":
            break


def main() -> None:
    # 1. Autoinicialización (crea esquema y ejecuta ETL si no existía)
    inicializar_si_hace_falta(DATABASE_URL, RUTA_EXCEL_HISTORICO)
    conexion = obtener_conexion(DATABASE_URL)

    try:
        gestor = GestorInventarioBD(conexion)

        while True:
            print("\n" + "=" * 60)
            print("SISTEMA DE GESTIÓN DE STOCK — TALLER DURAND & JANNON S.H.")
            print("=" * 60)
            print("1. Menú de Proveedores")
            print("2. Menú de Stock y Parámetros")
            print("0. Salir")

            opcion = input("\nIngrese una opción para continuar: ").strip()

            if opcion == "1":
                menu_proveedores(gestor)
            elif opcion == "2":
                menu_stock_parametros(gestor)
            elif opcion == "0":
                print("\n¡Gracias por utilizar el sistema! Cerrando sesión...\n")
                break
            else:
                print("Opción no válida. Intente nuevamente.")

    finally:
        conexion.close()


if __name__ == "__main__":
    main()