# 🔔 Módulo de alertas — análisis y diseño

> Estado: **en desarrollo** (diseño aprobado el 14/10/2026; Pasos 1 a 4 de desarrollo — base de datos, modelos, cálculo y guardado de umbrales — hechos el 15/10/2026; Paso 5 — reglas, motor y repositorio de alertas — hecho el 16/10/2026).
> Diagrama de clases: `docs/diagrama_UML.md` (sección 2) y `docs/diagramaUML.puml`.

El módulo avisa cuándo hay que reponer un repuesto, cuándo está en riesgo de faltar y cuándo hay stock de más. Cada repuesto tiene **sus propios umbrales**, calculados a partir de cuánto se usa: un mismo stock mínimo para todos no sirve (lo mostró el EDA, `templates/eda_repuestos.ipynb`).

## 1. Análisis: qué es una alerta

| Tipo | Se dispara cuando… | Qué tiene que hacer el taller |
|---|---|---|
| `REORDEN` | stock mínimo < stock actual ≤ punto de reorden | Hacer el pedido |
| `CRITICO` | stock actual ≤ stock mínimo | Pedir con urgencia: se está usando el colchón |
| `SOBRESTOCK` | stock actual > stock máximo | No comprar más: dinero inmovilizado |
| `SIN_ROTACION` *(futuro)* | N días sin egresos | Revisar capital inmovilizado; requiere egresos registrados |

Reglas de negocio:

- **Cuándo se revisa:** después de cada movimiento (solo ese repuesto) y con un botón "revisar todo" cuando se cambian umbrales.
- **Cierre:** manual. Alguien marca la alerta como atendida (por ejemplo, al hacer el pedido).
- **Sin duplicados:** no puede haber dos alertas abiertas del mismo tipo para el mismo repuesto.
- **Repuestos sin umbrales:** no generan alertas; aparecen en un listado "sin configurar".
- **REORDEN y CRÍTICO no se superponen:** debajo del mínimo salta solo CRÍTICO. Si ya había una REORDEN abierta y el stock sigue bajando, se suma la CRÍTICA (escalada, no duplicado).
- **Repuestos inactivos** (`activo = 0`, baja lógica): no se revisan ni se recalculan, y sus alertas abiertas no se modifican; solo dejan de mostrarse. Si el repuesto se reactiva, vuelven a aparecer. Inactivar lo decide una persona (inactivar solo tras N días sin uso queda como mejora futura).
- **Repuesto sin compras:** no tiene umbrales ("sin datos todavía"); no genera alertas.
- Mientras no se registren egresos, el stock solo sube y las alertas no se disparan.

### Estado del repuesto (calculado, no se guarda en la base)

`Repuesto.estado()` lo deduce de sus datos, así no se sobreescribe información:

| Estado | Cuándo |
|---|---|
| Disponible | stock > punto de reorden |
| Hay que pedir | stock mínimo < stock ≤ punto de reorden |
| Urgente | 0 < stock ≤ stock mínimo |
| Agotado | stock = 0 (activo y visible, como en un e-commerce; la alerta es CRÍTICO) |
| Sobra stock | stock > stock máximo |
| Sin datos todavía | sin umbrales (sin compras) |
| Inactivo | `activo = 0` (no se muestra por defecto) |

"Agotado" **no** es inactivar: agotado = no hay stock ahora; inactivo = ya no se maneja.

### Palabras en la interfaz

En el código y la documentación se usan los términos técnicos (los que evalúa la materia). En la pantalla, palabras del taller, definidas en **un solo diccionario** en `modules/alertas.py` para que interfaz y mensajes coincidan. A validar con quien use la aplicación.

| En el código | En la pantalla |
|---|---|
| Punto de reorden | Pedir cuando queden |
| Stock mínimo | Mínimo de seguridad |
| Stock máximo | No tener más de |
| REORDEN | Hay que pedir |
| CRITICO | Urgente: queda muy poco (o "Agotado" si el stock es 0) |
| SOBRESTOCK | Sobra stock |
| Marcar como atendida | Ya lo pedí |

## 2. Cálculo de los umbrales

| Parámetro | Fórmula |
|---|---|
| Uso diario (d) | unidades compradas ÷ días del período con datos (hoy, desde compras; luego, desde egresos) |
| Stock mínimo | d × S |
| Punto de reorden | d × L + stock mínimo |
| Stock máximo | punto de reorden + compra típica (unidades ÷ cantidad de compras) |

- **L = 7 días corridos** (los proveedores entregan en 3 a 5 días hábiles; se toma el peor caso).
- **S = 7 días** de seguridad.
- Todo se **redondea hacia arriba** y se expresa en la unidad del repuesto (`unidad` o `cm`).
- Los repuestos con una sola compra se calculan igual.
- Si un umbral se corrige a mano, `parametros_manuales = 1` y el recálculo no lo pisa.

Ejemplo, rodamiento 6204 2RS ZKL (55 unidades en 4 compras, 212 días): d = 0,26 → mínimo **2**, reorden **4**, máximo **18**.

Fundamento teórico: Silver, Pyke y Thomas (2017), *Inventory and Production Management in Supply Chains*, 4.ª ed., CRC Press (sistemas de revisión continua, punto de reorden y stock de seguridad); Bricker, D., *Reorder Point*, Universidad de Iowa.

## 3. Diseño: responsabilidades

Para cada tarea: *¿quién tiene la información necesaria? ¿quién debería ser responsable?* (Unidad 3, diseño dirigido por responsabilidades).

| Clase | Sabe | Hace |
|---|---|---|
| `Repuesto` | Su stock y sus umbrales | Responde sobre sí mismo: `tiene_umbrales()`, `necesita_reabastecimiento()`, `esta_en_estado_critico()`, `tiene_sobrestock()` |
| `Alerta` | Repuesto, fecha, tipo, mensaje, atendida | Representa una fila de la tabla `alertas` |
| `EstimadorDemanda` *(abstracta)* | — | Contrato: dados los movimientos, devolver uso diario y compra típica |
| `EstimadorPorCompras` | Días del período | Estima con los ingresos |
| `EstimadorPorEgresos` *(futuro)* | Días del período | Estima con los egresos |
| `CalculadoraParametros` | L y S | Convierte la estimación en mínimo, reorden y máximo |
| `ServicioParametrosStock` | El gestor y la calculadora | Recalcula y guarda los umbrales, salteando los manuales |
| `ReglaAlerta` *(abstracta)* | Su tipo | Contrato: `evaluar(repuesto)` y `mensaje(repuesto)` |
| `ReglaReorden`, `ReglaCritico`, `ReglaSobrestock` | — | Cada una, su condición |
| `MotorAlertas` | La lista de reglas y el repositorio | `revisar(repuesto)`: aplica las reglas y crea la alerta si no hay una abierta del mismo tipo |
| `RepositorioAlertas` | La conexión a la base | Guarda, consulta y marca alertas como atendidas |

## 4. Relación con la teoría de la materia

| Concepto (carpeta Teoría) | Dónde se aplica |
|---|---|
| Clases abstractas con `abc` (Unidad 2) | `EstimadorDemanda` y `ReglaAlerta` heredan de `ABC` y declaran métodos con `@abstractmethod` |
| Herencia y polimorfismo (Unidad 2) | Las reglas concretas heredan de `ReglaAlerta`; el motor llama a `evaluar()` sin saber cuál es |
| Agregación y dependencia (Unidad 2) | `MotorAlertas` *tiene* reglas creadas por fuera (agregación); las reglas *dependen* de `Repuesto` como parámetro |
| Responsabilidad única — SRP (Unidad 3) | Calcular umbrales, decidir alertas y guardar en la base están en clases distintas |
| Abierto/Cerrado — OCP (Unidad 3) | `SIN_ROTACION` se suma con una clase `ReglaSinRotacion`, sin tocar el motor |
| Sustitución de Liskov (Unidad 3) | Toda regla devuelve `bool` y no modifica el repuesto; todo estimador devuelve una `EstimacionDemanda` |
| Segregación de interfaces (Unidad 3) | Las abstracciones tienen solo los métodos que todas las implementaciones usan |
| Inversión de dependencias — DIP (Unidad 3) | El motor depende de `ReglaAlerta` y la calculadora de `EstimadorDemanda`, no de las clases concretas |
| Patrón Strategy (Unidad 3) | Dos veces: estimador de demanda y reglas de alerta (igual que los parsers) |
| Persistencia con `sqlite3` (Unidad 4) | `RepositorioAlertas` y la tabla `alertas` |
| Pruebas unitarias y dobles de prueba (Unidad 4) | Estimador, calculadora y reglas se prueban sin base de datos; el motor, con un repositorio falso en memoria (*fake*); el servicio de umbrales, con un `Mock` |

## 5. Contratos (diseño por contratos, Unidades 3 y 4)

| Clase / método | Contrato |
|---|---|
| `Repuesto` (invariante) | `unidad_medida` ∈ {unidad, cm}; umbrales ≥ 0; si tiene umbrales: mínimo ≤ reorden ≤ máximo |
| `Repuesto.tiene_umbrales()` | Post: `True` solo si tiene punto de reorden y máximo |
| `Repuesto.necesita_reabastecimiento()` y similares | Post: no modifican el repuesto; sin umbrales devuelven `False` |
| `Alerta` (invariante) | `tipo` ∈ {REORDEN, CRITICO, SOBRESTOCK}; `mensaje` no vacío |
| `EstimadorPorCompras(dias_periodo)` | Pre: `dias_periodo > 0`, si no `ValueError` |
| `EstimadorPorCompras.estimar(movs)` | Post: cuenta solo INGRESOS; uso diario y compra típica ≥ 0; sin ingresos → 0 y 0 |
| `CalculadoraParametros(L, S)` | Pre: L > 0 y S ≥ 0, si no `ParametrosInvalidosError` |
| `CalculadoraParametros.calcular(movs)` | Post: con ingresos, mínimo ≤ reorden ≤ máximo, enteros (mínimo ≥ 1 si S > 0); sin ingresos → `None` |
| `ServicioParametrosStock.recalcular(rep)` | Post: si `parametros_manuales = 1` o el repuesto está inactivo, no cambia nada; si no, guarda lo calculado |
| `ReglaAlerta.evaluar(rep)` | Post: devuelve `bool` y no modifica el repuesto (Liskov) |
| `MotorAlertas.revisar(rep)` | Post: inactivo o sin umbrales → `[]`; por cada regla que se cumple queda exactamente una alerta abierta de ese tipo |
| `MotorAlertas(reglas, …)` | Pre: al menos una regla, si no `ValueError` |
| `RepositorioAlertas` (invariante) | Nunca dos alertas abiertas con el mismo repuesto y tipo (índice único parcial en la base); si se intenta, `AlertaDuplicadaError` |
| `RepositorioAlertas.obtener_abiertas()` | Post: ordenadas de lo más urgente a lo menos (CRITICO, REORDEN, SOBRESTOCK); no muestra las de repuestos inactivos, pero tampoco las borra |
| `RepositorioAlertas.marcar_atendida(id)` | Pre: existe y está abierta, si no `AlertaNoEncontradaError`; post: `atendida = 1` |

## 6. Cambios en la base de datos (aplicados en el Paso 1 de desarrollo)

- `repuestos`: columna `parametros_manuales INTEGER NOT NULL DEFAULT 0 CHECK (parametros_manuales IN (0, 1))`.
- `alertas`: `CHECK` de `tipo` (REORDEN, CRITICO, SOBRESTOCK), de `mensaje` (no vacío) y de `atendida` (0 o 1).
- Índice único parcial `idx_alertas_abierta_unica ON alertas (repuesto_id, tipo) WHERE atendida = 0`: la base garantiza el invariante de "sin duplicados".
- Pruebas: `tests/test_esquema_alertas.py`.

## 7. Próximos pasos

1. ~~Análisis: tipos de alerta y reglas de negocio.~~
2. ~~Diseño: responsabilidades y clases.~~
3. ~~Diagrama UML.~~
4. ~~Contratos.~~
5. Desarrollo, cada paso con sus pruebas:
    1. ~~Base de datos~~ (15/10).
    2. ~~Modelos~~ (15/10): métodos y `estado()` de `Repuesto`, enumerado `EstadoStock`, dataclass `Alerta`, invariantes con excepciones propias (`RepuestoInvalidoError`, `AlertaInvalidaError`) y validación de umbrales al guardarlos. Pruebas: `tests/test_modelos.py`.
    3. ~~Cálculo~~ (15/10): `EstimadorDemanda` (abstracta), `EstimadorPorCompras`, `CalculadoraParametros`, `ParametrosInvalidosError` y los diccionarios de palabras para la interfaz (`ETIQUETAS_*`) en `modules/alertas.py`. Pruebas: `tests/test_alertas_calculo.py` (incluye el 6204 con datos reales → 2 / 4 / 18).
    4. ~~Guardado de umbrales~~ (15/10): `GestorInventarioBD.obtener_movimientos` y `obtener_periodo_movimientos`; `ServicioParametrosStock` (con `desde_historial`, que toma el período del primer al último movimiento). Pruebas: `tests/test_alertas_parametros.py` (incluye un `Mock` del gestor y el recálculo de los 192 repuestos reales).

    > **Hallazgo:** `stock_actual` hoy es la **suma de todas las compras desde enero**, porque nunca se registraron egresos; no es el stock real del estante. Con umbrales calculados, 16 repuestos aparecen con "Sobra stock" (ej. 6204: 55 comprados, máximo 18) y 18 como "Urgente" (repuestos comprados una vez de a 1 unidad). Antes de usar las alertas hace falta un **conteo físico** y registrarlo como movimientos de AJUSTE.
    5. ~~Alertas~~ (16/10): `ReglaAlerta` (abstracta), `ReglaReorden`, `ReglaCritico`, `ReglaSobrestock`, `MotorAlertas` y `reglas_por_defecto()` en `modules/alertas.py`; `RepositorioAlertas`, `AlertaNoEncontradaError` y `AlertaDuplicadaError` en `modules/crud.py`. Pruebas: `tests/test_alertas_motor.py` (26 pruebas: reglas solas, motor con repositorio falso, repositorio con base real y un flujo completo "hay que pedir → ya lo pedí → agotado").

    Cómo se usa (lo que hará la interfaz cada vez que se registra un movimiento):

    ```python
    from modules.alertas import MotorAlertas, reglas_por_defecto
    from modules.crud import GestorInventarioBD, RepositorioAlertas

    gestor = GestorInventarioBD(conexion)
    repositorio = RepositorioAlertas(conexion)
    motor = MotorAlertas(reglas_por_defecto(), repositorio)

    gestor.registrar_movimiento(mov)                              # 1. se guarda el egreso/ingreso
    nuevas = motor.revisar(gestor.obtener_repuesto_id(mov.repuesto_id))  # 2. se revisa ese repuesto
    pendientes = repositorio.obtener_abiertas()                   # 3. lo que se muestra en pantalla
    repositorio.marcar_atendida(alerta_id)                        # 4. botón "Ya lo pedí"
    ```

    Las reglas son excluyentes en su condición: con stock en el mínimo o por debajo salta **CRITICO** (no REORDEN); entre el mínimo y el punto de reorden, **REORDEN**. Si una REORDEN quedó abierta y el stock sigue bajando, se suma la CRITICO (escalada).

6. Pendiente antes de usarlo con la base real: conteo físico y registro como AJUSTE (ver hallazgo). Después: la pantalla de alertas en la interfaz.
