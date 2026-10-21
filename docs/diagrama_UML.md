# 📐 Diagrama de Clases UML — Gestor de Inventario

> Actualizado el 20/10/2026: modelo de repuestos con `codigo` (marca + código), categorías unificadas, `LineaNormalizada`, **módulo de alertas**, **conteo inicial** con planilla y **registro de movimientos**, **historial con descargas**, **catálogo**, **proveedores** y **dashboard**.
> La misma información está en `diagramaUML.puml` (PlantUML) y en la imagen `Diagrama_Clases_Gestor_Stock.png`.

**Notación** (Unidades 2 y 3 de POO): `+` público, `-` privado, `*` método abstracto, `<<abstract>>` clase abstracta (ABC).
Relaciones: `<|--` herencia ("es un"), `o--` agregación ("tiene un", la parte existe por fuera), `*--` composición (la parte vive y muere con el todo), `-->` asociación ("usa un"), `..>` dependencia ("depende de").

## 1. Modelo de dominio, persistencia y parsers

```mermaid
classDiagram
    %% ===== MODELO DE DOMINIO (modules/modelos.py) =====
    class Proveedor {
        +Optional~int~ id
        +str nombre
        +Optional~str~ contacto
        +Optional~str~ telefono
        +Optional~str~ email
        +bool activo
        +es_valido_para_orden() bool
    }

    class Marca {
        +Optional~int~ id
        +str nombre
    }

    class Categoria {
        +Optional~int~ id
        +str nombre
        +Optional~str~ descripcion
    }

    class Repuesto {
        +Optional~int~ id
        +str codigo
        +int marca_id
        +int categoria_id
        +Optional~str~ especificaciones
        +str unidad_medida
        +float stock_minimo
        +Optional~float~ stock_maximo
        +Optional~float~ punto_reorden
        +float stock_actual
        +bool activo
        +bool parametros_manuales
        +tiene_umbrales() bool
        +esta_agotado() bool
        +necesita_reabastecimiento() bool
        +esta_en_estado_critico() bool
        +tiene_sobrestock() bool
        +calcular_sugerencia_compra() float
        +estado() EstadoStock
        +stock_despues_de(mov: MovimientoStock) float
        +ajuste_por_conteo(cantidad_contada: float, fecha: str) MovimientoStock
    }
    note for Repuesto "inv: stock_actual >= 0 (si no, StockNegativoError: Operación inválida)"

    class EstadoStock {
        <<enumeration>>
        DISPONIBLE
        HAY_QUE_PEDIR
        URGENTE
        AGOTADO
        SOBRESTOCK
        SIN_DATOS
        INACTIVO
    }

    class MovimientoStock {
        +Optional~int~ id
        +int repuesto_id
        +str fecha
        +str tipo
        +float cantidad
        +Optional~int~ proveedor_id
        +Optional~str~ codigo_proveedor_raw
        +str origen
        +Optional~int~ anula_id
        +efecto_en_stock() float
    }

    class Alerta {
        +Optional~int~ id
        +int repuesto_id
        +str fecha
        +str tipo
        +str mensaje
        +bool atendida
    }

    %% ===== PERSISTENCIA (modules/crud.py) =====
    class GestorInventarioBD {
        -Connection conexion
        +crear_proveedor(prov: Proveedor) int
        +obtener_proveedores(solo_activos: bool) List~Proveedor~
        +actualizar_proveedor(prov: Proveedor) None
        +desactivar_proveedor(proveedor_id: int) None
        +crear_marca(marca: Marca) int
        +obtener_marcas() List~Marca~
        +crear_categoria(categoria: Categoria) int
        +obtener_categorias() List~Categoria~
        +crear_repuestos(rep: Repuesto) int
        +obtener_repuestos(solo_activos: bool) List~Repuesto~
        +obtener_repuesto_id(repuesto_id: int) Optional~Repuesto~
        +obtener_repuesto_por_codigo(marca_id: int, codigo: str) Optional~Repuesto~
        +actualizar_repuesto(rep: Repuesto) None
        +actualizar_parametros_stock(repuesto_id, stock_minimo, stock_maximo, punto_reorden, manual: bool) None
        +obtener_repuestos_bajo_reorden() List~Repuesto~
        +registrar_movimiento(mov: MovimientoStock) int
        +obtener_movimientos(repuesto_id: int) List~MovimientoStock~
        +obtener_movimiento(movimiento_id: int) Optional~MovimientoStock~
        +esta_anulado(movimiento_id: int) bool
        +registrar_conteo(repuesto_id: int, cantidad_contada: float, fecha: str) MovimientoStock
        +obtener_repuestos_contados() List~Repuesto~
    }

    class RepositorioAlertas {
        -Connection conexion
        +crear(alerta: Alerta) int
        +existe_abierta(repuesto_id: int, tipo: str) bool
        +obtener_abiertas(incluir_inactivos: bool) List~Alerta~
        +obtener_historial(repuesto_id: int) List~Alerta~
        +marcar_atendida(alerta_id: int) None
    }

    %% ===== PARSERS: STRATEGY + FACTORY (modules/parsers.py) =====
    class LineaNormalizada {
        +str proveedor
        +str codigo
        +str marca
        +Optional~str~ categoria
        +Optional~str~ especificaciones
        +str descripcion
        +float cantidad
        +str tipo_linea
    }

    class ParserProveedor {
        <<abstract>>
        +parsear(fila: dict)* LineaNormalizada
    }
    class ParserIriondo {
        +parsear(fila: dict) LineaNormalizada
    }
    class ParserEdMa {
        +parsear(fila: dict) LineaNormalizada
    }
    class ParserProdumat {
        +parsear(fila: dict) LineaNormalizada
    }
    class FabricaParsers {
        <<factory>>
        -dict _PARSERS_POR_PROVEEDOR
        +obtener_parser(nombre_proveedor: str) ParserProveedor
    }

    %% ===== RELACIONES =====
    Repuesto "0..*" --> "1" Marca : pertenece a
    Repuesto "0..*" --> "1" Categoria : pertenece a
    MovimientoStock "0..*" --> "1" Repuesto : impacta sobre
    MovimientoStock "0..*" --> "0..1" Proveedor : comprado a
    Alerta "0..*" --> "1" Repuesto : avisa sobre
    Repuesto ..> EstadoStock : calcula
    Repuesto ..> MovimientoStock : crea AJUSTE (conteo)

    GestorInventarioBD ..> Proveedor : manipula
    GestorInventarioBD ..> Repuesto : manipula
    GestorInventarioBD ..> MovimientoStock : registra
    RepositorioAlertas ..> Alerta : guarda / lee

    ParserProveedor <|-- ParserIriondo
    ParserProveedor <|-- ParserEdMa
    ParserProveedor <|-- ParserProdumat
    FabricaParsers --> "1..*" ParserProveedor : retorna
    ParserProveedor ..> LineaNormalizada : crea
```

## 2. Módulo de alertas (`modules/alertas.py`) — diseño

```mermaid
classDiagram
    class EstimacionDemanda {
        +float uso_diario
        +float compra_tipica
    }
    class ParametrosStock {
        +float stock_minimo
        +float punto_reorden
        +float stock_maximo
    }

    class EstimadorDemanda {
        <<abstract>>
        +estimar(movimientos: List~MovimientoStock~)* EstimacionDemanda
    }
    class EstimadorPorCompras {
        -int dias_periodo
        +estimar(movimientos: List~MovimientoStock~) EstimacionDemanda
    }
    class EstimadorPorEgresos {
        <<futuro>>
        -int dias_periodo
        +estimar(movimientos: List~MovimientoStock~) EstimacionDemanda
    }

    class CalculadoraParametros {
        -EstimadorDemanda estimador
        -int dias_reposicion = 7
        -int dias_seguridad = 7
        +calcular(movimientos: List~MovimientoStock~) ParametrosStock
    }

    class ServicioParametrosStock {
        -GestorInventarioBD gestor
        -CalculadoraParametros calculadora
        +recalcular(repuesto: Repuesto) Optional~ParametrosStock~
        +recalcular_todos() int
    }

    class ReglaAlerta {
        <<abstract>>
        +str tipo
        +evaluar(repuesto: Repuesto)* bool
        +mensaje(repuesto: Repuesto)* str
    }
    class ReglaReorden {
        +evaluar(repuesto: Repuesto) bool
        +mensaje(repuesto: Repuesto) str
    }
    class ReglaCritico {
        +evaluar(repuesto: Repuesto) bool
        +mensaje(repuesto: Repuesto) str
    }
    class ReglaSobrestock {
        +evaluar(repuesto: Repuesto) bool
        +mensaje(repuesto: Repuesto) str
    }

    class MotorAlertas {
        -List~ReglaAlerta~ reglas
        -RepositorioAlertas repositorio
        -Callable hoy
        +revisar(repuesto: Repuesto) List~Alerta~
        +revisar_todos(repuestos: List~Repuesto~) List~Alerta~
    }

    %% Strategy 1: cómo se estima la demanda
    EstimadorDemanda <|-- EstimadorPorCompras
    EstimadorDemanda <|-- EstimadorPorEgresos
    EstimadorDemanda ..> MovimientoStock : lee
    EstimadorDemanda ..> EstimacionDemanda : crea
    CalculadoraParametros o-- "1" EstimadorDemanda : usa
    CalculadoraParametros ..> ParametrosStock : crea
    ServicioParametrosStock --> CalculadoraParametros
    ServicioParametrosStock --> GestorInventarioBD

    %% Strategy 2: qué condición dispara cada alerta
    ReglaAlerta <|-- ReglaReorden
    ReglaAlerta <|-- ReglaCritico
    ReglaAlerta <|-- ReglaSobrestock
    ReglaAlerta ..> Repuesto : evalúa
    MotorAlertas o-- "1..*" ReglaAlerta : aplica
    MotorAlertas --> RepositorioAlertas
    MotorAlertas ..> Alerta : crea
```

Las clases `Repuesto`, `MovimientoStock`, `Alerta`, `GestorInventarioBD` y `RepositorioAlertas` del segundo diagrama son las mismas del primero; se repiten solo como referencia de las relaciones.

## 3. Conteo inicial con planilla (modules/conteo.py)

`PlanillaConteo` solo conoce el formato del Excel; `ServicioConteoInicial` coordina el conteo (todo o nada), recalcula umbrales y revisa las alertas de los repuestos contados. `*--` es composición: las filas y los errores existen solo dentro de una lectura.

```mermaid
classDiagram
    class PlanillaConteo {
        +generar(ruta, repuestos, marcas, categorias) int
        +leer(ruta: str) LecturaPlanilla
    }
    class LecturaPlanilla {
        +List~FilaConteo~ filas
        +List~ErrorConteo~ errores
    }
    class FilaConteo {
        <<frozen>>
        +int fila
        +int repuesto_id
        +str codigo
        +Optional~float~ cantidad_contada
    }
    class ErrorConteo {
        <<frozen>>
        +int fila
        +str codigo
        +str mensaje
    }
    class ServicioConteoInicial {
        -GestorInventarioBD gestor
        -MotorAlertas motor
        -Callable fabrica_parametros
        +validar(filas, fecha: str) List~ErrorConteo~
        +aplicar(lectura: LecturaPlanilla, fecha: str) ResultadoConteo
    }
    class ResultadoConteo {
        +int ajustados
        +int sin_diferencia
        +int sin_contar
        +int umbrales_recalculados
        +List~Alerta~ alertas_nuevas
        +List~ErrorConteo~ errores
        +aplicado() bool
    }

    PlanillaConteo ..> Repuesto : lista
    PlanillaConteo ..> LecturaPlanilla : crea
    LecturaPlanilla *-- "0..*" FilaConteo
    LecturaPlanilla *-- "0..*" ErrorConteo
    ServicioConteoInicial --> GestorInventarioBD : registrar_conteo
    ServicioConteoInicial --> MotorAlertas : revisa contados
    ServicioConteoInicial ..> ServicioParametrosStock : crea (fábrica)
    ServicioConteoInicial ..> LecturaPlanilla : aplica
    ServicioConteoInicial ..> ResultadoConteo : crea
```

## 4. Movimientos del día a día (modules/movimientos.py)

`ServicioMovimientos` valida cada ingreso, egreso o conteo (precondiciones), lo guarda y revisa las alertas **solo del repuesto movido**. La pantalla "Registrar movimiento" (`apps/app_1.py`) lo usa sin agregar reglas propias.

```mermaid
classDiagram
    class ServicioMovimientos {
        -GestorInventarioBD gestor
        -MotorAlertas motor
        -Callable hoy
        +registrar_ingreso(repuesto_id, cantidad, fecha, proveedor_id) ResultadoMovimiento
        +registrar_egreso(repuesto_id, cantidad, fecha) ResultadoMovimiento
        +registrar_conteo(repuesto_id, cantidad_contada, fecha) ResultadoMovimiento
        +anular(movimiento_id) ResultadoMovimiento
    }
    class ResultadoMovimiento {
        +int movimiento_id
        +Repuesto repuesto
        +List~Alerta~ alertas_nuevas
        +Optional~float~ diferencia
    }

    ServicioMovimientos --> GestorInventarioBD : registra
    ServicioMovimientos --> MotorAlertas : revisa el repuesto movido
    ServicioMovimientos ..> MovimientoStock : crea
    ServicioMovimientos ..> ResultadoMovimiento : crea
```

## 5. Historial y descargas (modules/reportes.py)

`ConsultaMovimientos` solo lee. Los exportadores son otra vez el patrón **Strategy**: la pantalla elige `EXPORTADORES["excel"]` o `EXPORTADORES["pdf"]` y llama a `exportar()` sin saber cuál es. Un formato nuevo (CSV) sería una clase más.

```mermaid
classDiagram
    class FiltroMovimientos {
        <<frozen>>
        +str desde
        +str hasta
        +Optional~str~ tipo
        +Optional~int~ repuesto_id
        +descripcion() str
    }
    class FilaReporte {
        <<frozen>>
        +str fecha
        +str tipo
        +str codigo
        +str marca
        +str categoria
        +float cantidad
        +str unidad_medida
        +str proveedor
        +Optional~int~ anula_id
        +bool anulado
        +vigente() bool
        +como_tupla() tuple
    }
    class ConsultaMovimientos {
        -Connection conexion
        +buscar(filtro: FiltroMovimientos) List~FilaReporte~
    }
    class ExportadorReporte {
        <<abstract>>
        +str extension
        +str tipo_mime
        +exportar(filas, filtro)* bytes
    }
    class ExportadorExcel {
        +exportar(filas, filtro) bytes
    }
    class ExportadorPDF {
        +exportar(filas, filtro) bytes
    }

    ConsultaMovimientos ..> FiltroMovimientos : usa
    ConsultaMovimientos ..> FilaReporte : crea
    ExportadorReporte <|-- ExportadorExcel
    ExportadorReporte <|-- ExportadorPDF
    ExportadorReporte ..> FilaReporte : exporta
```

## 6. Catálogo (modules/catalogo.py)

`ServicioCatalogo` coordina el alta y la corrección de repuestos, activar/inactivar (solo sin stock) y los umbrales a mano. Después de cada cambio que puede afectar el estado, revisa las alertas de ese repuesto.

```mermaid
classDiagram
    class FiltroCatalogo {
        <<frozen>>
        +str texto
        +Optional~int~ categoria_id
        +Optional~EstadoStock~ estado
        +bool incluir_inactivos
    }
    class FichaRepuesto {
        <<frozen>>
        +Repuesto repuesto
        +str marca
        +str categoria
        +estado() EstadoStock
        +coincide(texto: str) bool
    }
    class ServicioCatalogo {
        -GestorInventarioBD gestor
        -MotorAlertas motor
        -Callable fabrica_parametros
        +listar(filtro) List~FichaRepuesto~
        +ficha(repuesto_id) FichaRepuesto
        +crear(codigo, marca, categoria, especificaciones, unidad_medida) int
        +corregir_datos(repuesto_id, categoria, especificaciones) None
        +inactivar(repuesto_id) None
        +activar(repuesto_id) List~Alerta~
        +fijar_umbrales(repuesto_id, minimo, reorden, maximo) List~Alerta~
        +volver_a_automatico(repuesto_id) Optional~ParametrosStock~
    }

    ServicioCatalogo --> GestorInventarioBD
    ServicioCatalogo --> MotorAlertas : revisa el repuesto cambiado
    ServicioCatalogo ..> ServicioParametrosStock : crea (fábrica)
    ServicioCatalogo ..> FiltroCatalogo : usa
    ServicioCatalogo ..> FichaRepuesto : crea
    FichaRepuesto --> Repuesto
```

## 7. Proveedores (modules/proveedores.py)

`ConsultaProveedores` solo lee (a quién se le compra y qué); `ServicioProveedores` da de alta, corrige y activa/desactiva con sus reglas. No hay precios todavía: la comparación es por frecuencia.

```mermaid
classDiagram
    class ResumenProveedor {
        <<frozen>>
        +Proveedor proveedor
        +int compras
        +int lineas
        +int repuestos
        +float unidades
        +float centimetros
        +Optional~str~ primera
        +Optional~str~ ultima
        +dias_desde_ultima(hoy) Optional~int~
    }
    class CompraDeRepuesto {
        <<frozen>>
        +int repuesto_id
        +str codigo
        +int veces
        +float cantidad
        +str ultima
    }
    class ConsultaProveedores {
        -Connection conexion
        +resumen(incluir_inactivos) List~ResumenProveedor~
        +repuestos_comprados(proveedor_id) List~CompraDeRepuesto~
    }
    class ServicioProveedores {
        -GestorInventarioBD gestor
        +obtener(proveedor_id) Proveedor
        +crear(nombre, contacto, telefono, email) int
        +corregir(proveedor_id, nombre, contacto, telefono, email) None
        +desactivar(proveedor_id) None
        +activar(proveedor_id) None
    }
    ConsultaProveedores ..> ResumenProveedor : crea
    ConsultaProveedores ..> CompraDeRepuesto : crea
    ResumenProveedor --> Proveedor
    ServicioProveedores --> GestorInventarioBD
```

## 8. Dashboard (modules/dashboard.py)

`ConsultaDashboard` arma los números (solo lee); la pantalla los dibuja con barras en HTML/CSS. La rotación reutiliza `EstimadorPorCompras` del módulo de alertas.

```mermaid
classDiagram
    class ConsultaDashboard {
        -Connection conexion
        -GestorInventarioBD gestor
        -Callable hoy
        +estados() Dict
        +avance_conteo() AvanceConteo
        +rotacion(cantidad) Tuple
        +inmovilizado(dias) List~FilaInmovilizado~
        +compras_por_mes() List~FilaMes~
    }
    class AvanceConteo {
        <<frozen>>
        +int contados
        +int total
        +porcentaje() int
    }
    class FilaRotacion {
        <<frozen>>
        +Repuesto repuesto
        +float por_mes
    }
    class FilaInmovilizado {
        <<frozen>>
        +Repuesto repuesto
        +float exceso
        +Optional~int~ dias_sin_movimiento
        +motivos() List~str~
    }
    class FilaMes {
        <<frozen>>
        +str mes
        +int compras
        +int lineas
        +float unidades
        +nombre() str
    }
    ConsultaDashboard --> GestorInventarioBD
    ConsultaDashboard ..> EstimadorPorCompras : usa (rotación)
    ConsultaDashboard ..> AvanceConteo : crea
    ConsultaDashboard ..> FilaRotacion : crea
    ConsultaDashboard ..> FilaInmovilizado : crea
    ConsultaDashboard ..> FilaMes : crea
```
