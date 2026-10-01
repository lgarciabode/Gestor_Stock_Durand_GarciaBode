# 🛠️ Sistema de Gestión de Inventario y Predicción de Compras — Taller Durand & Jannon S.H.

Sistema de gestión de inventario, normalización de comprobantes y análisis predictivo de demanda desarrollado en Python (POO + SQLite) para el **Taller de Tornería Jannon y Durand S.H.**. 

El proyecto resuelve la digitalización de comprobantes heterogéneos de proveedores (facturas y remitos), automatiza el control de existencias en tiempo real mediante *triggers* relacionales y proporciona herramientas para la gestión de stock, alertas de reorden y proyecciones de compras.

---

## 🏗 Arquitectura General

El sistema está diseñado bajo una arquitectura modular y orientada a objetos (POO), separando las responsabilidades de dominio, la capa de persistencia en SQLite, las estrategias de normalización de datos y los puntos de entrada de la aplicación.

### Principales Componentes Técnicos
* **Dominio Puro (`modules/modelos.py`):** Clases orientadas a objetos (`Proveedor`, `Marca`, `Categoria`, `Repuesto`, `MovimientoStock`) utilizando `@dataclass` para representar las entidades clave y encapsular métodos con reglas del negocio.
* **Normalización de Insumos (`modules/parsers.py`):** Implementación de los patrones **Strategy** y **Factory** (`ParserProveedor`, `ParserIriondo`, `ParserEdMa`, `ParserProdumat`) para extraer, limpiar y estandarizar catálogos y comprobantes heterogéneos.
* **Persistencia e Integridad (`modules/base_datos.py` y `modules/crud.py`):** Esquema relacional en SQLite con soporte para *Foreign Keys*, la tabla intermedia de mapeo `repuesto_codigo_proveedor` y el disparador automático `trg_movimientos_actualiza_stock` que gestiona las existencias en tiempo real de forma atómica. Encapsulado en la clase de servicio `GestorInventarioBD`.
* **Migración Histórica (`modules/carga_historico_datos.py`):** Carga inicial transaccional (ACID) que procesa planillas históricas en Excel sin duplicar información ni cargar gastos administrativos al stock físico.

### Estructura de Directorios

```text
.
├── apps/                       # Puntos de entrada y scripts auxiliares
│   └── inicializar_bd.py       # Script de autoinicialización del esquema y carga inicial
├── data/                       # Archivos de datos históricos (.xlsx) y base SQLite (.sqlite3)
├── docs/                       # Especificaciones del proyecto, diagrama DFD y documentación
├── modules/                    # Módulos centrales de la lógica del sistema
│   ├── base_datos.py           # DDL, conexión SQLite y disparadores (triggers)
│   ├── carga_historico_datos.py# Migración de datos históricos desde Excel
│   ├── crud.py                 # GestorInventarioBD (Alta, Lectura, Modificación, Baja)
│   ├── modelos.py              # Entidades del dominio (dataclasses)
│   └── parsers.py              # Parsers por proveedor (Strategy + Factory)
├── tests/                      # Pruebas unitarias e integración de los módulos
├── .env                        # Variables de entorno locales
├── config.py                   # Configuración centralizada de rutas y variables de entorno
├── main.py                     # Ejecución principal de pruebas y demostración
└── README.md                   # Documentación general del repositorio
```

## ⚙️ Requisitos e Instalación

1. **Clonar el repositorio:**
   ```bash
   git clone [https://github.com/tu-usuario/Gestor_Stock_Durand_GarciaBode.git](https://github.com/tu-usuario/Gestor_Stock_Durand_GarciaBode.git)
   cd Gestor_Stock_Durand_GarciaBode
    ```

2. **Crear y activar un entorno virtual**
    ```bash
    python -m venv venv

    # En Windows:
    venv\Scripts\activate

    # En Linux/macOS:
    source venv/bin/activate
    ```

3. **Instalar dependencias**
    ```bash
    pip install openpyxl python-dotenv
    ```

4. **Configurar el archivo .env:**
    Crear un archivo .env en la raíz del proyecto definiendo las rutas locales:
    ```bash
    source venv/bin/activate
    ```

5. **Instalar dependencias**
    ```bash
    DATABASE_URL=data/stock_taller.sqlite3
    RUTA_EXCEL_HISTORICO=data/base_stock_taller.xlsx
    ```

6. **Inicializar base de datos**
    ```bash
    python apps/inicializar_bd.py
    ```

7. **Verificación y Evaluación del Hito 1:** ejecute el script principal desde la raíz del proyecto:
     ```bash
    python main.py
    ```

    El script main.py funciona como la suite de prueba integral del Hito 1 y realiza de forma secuencial las siguientes validaciones:

    * Autoinicialización e idempotencia: Invoca la creación del esquema DDL en SQLite y la migración transaccional de los comprobantes históricos desde la planilla Excel (data/base_stock_taller.xlsx), auditando cuántos movimientos fueron procesados y excluyendo los cargos administrativos que no forman parte del stock físico.
    * Lectura del estado del dominio: Instancia la clase de servicio GestorInventarioBD para consultar la carga inicial de proveedores, repuestos, marcas y movimientos registrados.
    * Prueba de operaciones CRUD:
       * CREATE: Alta de un nuevo proveedor (TornoSur Herramientas S.A.) utilizando objetos de la clase Proveedor.
       * UPDATE: Actualización de datos de contacto de la entidad.
       * DELETE (Baja Lógica): Desactivación controlada del proveedor (activo = 0) para preservar el historial de compras y la integridad referencial.
    * Gestión de parámetros de stock y alertas: Modificación de los umbrales operativos (stock_minimo, stock_maximo, punto_reorden) sobre repuestos del catálogo y ejecución de la consulta que detecta insumos que requieren reabastecimiento crítico.


## 🙎‍♀️🙎🙎‍♀️ Autoras
* Durand, Camila Ayelen
* García Bode, Lucía Araceli



## 📅 Cursado
2do Cuatrimestre de 2026 — Universidad Nacional de Entre Ríos (UNER)
