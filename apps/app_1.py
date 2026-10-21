"""Interfaz web (Flask) del Gestor de Stock.

Capa de presentación (patrón en capas / MVC): recibe los pedidos del
navegador, le pide los datos a las clases de modules/ y los muestra con un
template. No contiene reglas de negocio.

La autenticación la resuelve auth-module (biblioteca de la cátedra / LICA):
https://github.com/FIUNER-LICA/auth-module

Ejecutar desde la raíz del proyecto:
    flask --app apps.app_1 run --debug
"""
import io
import os
from collections import Counter
from datetime import date, timedelta

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   send_file, session, url_for)

from auth_module.core.auth_manager import AuthManager
from auth_module.core.db.sqlite_repository import SQLiteUserRepository
from auth_module.core.mail.dispatchers import ConsoleMailDispatcher
from auth_module.flask_ext.decorators import login_required
from auth_module.flask_ext.extension import FlaskExtension

from config import (BASE_DIR, DATABASE_URL, RUTA_BD_USUARIOS,
                    RUTA_EXCEL_HISTORICO, SECRET_KEY)
from modules.alertas import (ETIQUETAS_ATENDER_ALERTA, ETIQUETAS_ESTADO,
                             ETIQUETAS_UMBRALES,
                             ETIQUETAS_TIPO_ALERTA, MotorAlertas,
                             ServicioParametrosStock, reglas_por_defecto,
                             texto_cantidad)
from modules.base_datos import inicializar_si_hace_falta, obtener_conexion
from modules.catalogo import (CatalogoInvalidoError, FiltroCatalogo,
                              ServicioCatalogo)
from modules.dashboard import DIAS_SIN_MOVIMIENTO, ConsultaDashboard
from modules.crud import (AlertaNoEncontradaError, GestorInventarioBD,
                          RepositorioAlertas, RepuestoNoEncontradoError)
from modules.modelos import EstadoStock
from modules.movimientos import MovimientoInvalidoError, ServicioMovimientos
from modules.proveedores import (ConsultaProveedores, ProveedorInvalidoError,
                                 ProveedorNoEncontradoError, ServicioProveedores)
from modules.reportes import (ETIQUETAS_TIPO_MOVIMIENTO, EXPORTADORES,
                              ConsultaMovimientos, FiltroInvalidoError,
                              FiltroMovimientos, contar_por_tipo)

# Color de la etiqueta (badge) de cada estado. Es una decisión visual, por eso
# vive en la capa de presentación y no en el modelo.
CLASE_CSS_ESTADO = {
    EstadoStock.DISPONIBLE: "ok",
    EstadoStock.HAY_QUE_PEDIR: "reorden",
    EstadoStock.URGENTE: "critico",
    EstadoStock.AGOTADO: "critico",
    EstadoStock.SOBRESTOCK: "sobrestock",
    EstadoStock.SIN_DATOS: "neutro",
    EstadoStock.INACTIVO: "neutro",
}

# Mismo criterio para los tipos de alerta (reutiliza los colores de los estados).
CLASE_CSS_TIPO_ALERTA = {
    "CRITICO": "critico",
    "REORDEN": "reorden",
    "SOBRESTOCK": "sobrestock",
}


# ---------------------------------------------------------------- Base de stock
# Una conexión por pedido: SQLite no permite compartir una conexión entre los
# hilos con los que Flask atiende los pedidos.

def obtener_bd():
    """Devuelve la conexión del pedido actual; la crea la primera vez que se pide."""
    if "bd" not in g:
        g.bd = obtener_conexion(DATABASE_URL)
    return g.bd


def cerrar_bd(excepcion=None):
    """Flask la llama al terminar cada pedido: cierra la conexión si se abrió."""
    bd = g.pop("bd", None)
    if bd is not None:
        bd.close()


# ---------------------------------------------------------------- Autenticación

def configurar_autenticacion(app: Flask) -> None:
    """Arma las dependencias de auth-module y las inyecta (inyección de dependencias)."""
    repositorio_usuarios = SQLiteUserRepository(db_path=RUTA_BD_USUARIOS)
    despachador_correo = ConsoleMailDispatcher()  # desarrollo: los correos se imprimen en la terminal

    auth_manager = AuthManager(
        mail_dispatcher=despachador_correo,
        user_repository=repositorio_usuarios,
        base_url="http://localhost:5000/auth",
        secret_key=app.config["SECRET_KEY"],
    )
    # Registra /auth/login, /auth/register, /auth/logout, etc.
    # Después del login, redirige a la función "index" de esta app.
    FlaskExtension(app, auth_manager, login_redirect_endpoint="index")


# ---------------------------------------------------------------- Alertas (datos para la pantalla)

def filas_de_alertas(gestor: GestorInventarioBD, alertas) -> list:
    """Arma lo que muestra cada renglón de la tabla de alertas.

    Junta la alerta con los datos del repuesto (código, marca, categoría).
    Es preparación de datos para la vista: no decide nada del negocio.
    """
    marcas = {m.id: m.nombre for m in gestor.obtener_marcas()}
    categorias = {c.id: c.nombre for c in gestor.obtener_categorias()}
    filas = []
    for alerta in alertas:
        rep = gestor.obtener_repuesto_id(alerta.repuesto_id)
        filas.append({
            "id": alerta.id,
            "tipo": ETIQUETAS_TIPO_ALERTA[alerta.tipo],
            "clase_css": CLASE_CSS_TIPO_ALERTA[alerta.tipo],
            "codigo": rep.codigo,
            "marca": marcas.get(rep.marca_id, ""),
            "categoria": categorias.get(rep.categoria_id, ""),
            # El mensaje empieza con "<tipo> — <código>: ..."; eso ya está en
            # otras columnas, así que se muestra solo el detalle.
            "detalle": alerta.mensaje.split(" — ", 1)[-1].split(": ", 1)[-1],
            "desde": date.fromisoformat(alerta.fecha).strftime("%d/%m/%Y"),
            "boton": ETIQUETAS_ATENDER_ALERTA[alerta.tipo],
        })
    return filas


# ---------------------------------------------------------------- Movimientos (datos para el formulario)

# Opciones del formulario "Registrar movimiento". Las palabras son las del
# taller; el valor es lo que viaja al servidor.
# "Stock disponible" es solo una consulta: muestra cuánto hay y no guarda nada.
# (Corregir el stock con lo que hay en el estante se hace con la planilla de conteo.)
TIPOS_MOVIMIENTO_FORMULARIO = {
    "ingreso": "Agregar",
    "egreso": "Quitar",
    "stock": "Stock disponible",
}


def opciones_de_repuestos(gestor: GestorInventarioBD) -> dict:
    """Texto que se ve en el buscador -> repuesto.

    El buscador muestra "código · marca · categoría", así se elige
    reconociendo el repuesto en vez de tener que recordar el código exacto.
    """
    marcas = {m.id: m.nombre for m in gestor.obtener_marcas()}
    categorias = {c.id: c.nombre for c in gestor.obtener_categorias()}
    return {
        f"{r.codigo} · {marcas.get(r.marca_id, '')} · {categorias.get(r.categoria_id, '')}": r
        for r in gestor.obtener_repuestos()
    }


def buscar_repuesto_elegido(opciones: dict, texto: str):
    """Devuelve el repuesto elegido, o None si el texto no corresponde a uno solo.
    Acepta la opción completa de la lista o el código solo, si no se repite."""
    texto = (texto or "").strip()
    if texto in opciones:
        return opciones[texto]
    por_codigo = [r for r in opciones.values() if r.codigo == texto]
    return por_codigo[0] if len(por_codigo) == 1 else None


def stock_por_texto(opciones: dict) -> dict:
    """Texto del buscador (y código solo, si no se repite) -> stock según el sistema.

    Lo usa el formulario para mostrar "Según el sistema hay …" apenas se elige
    un repuesto, antes de guardar nada.
    """
    stocks = {texto: texto_cantidad(rep, rep.stock_actual) for texto, rep in opciones.items()}
    codigos = Counter(rep.codigo for rep in opciones.values())
    for rep in opciones.values():
        if codigos[rep.codigo] == 1:
            stocks[rep.codigo] = texto_cantidad(rep, rep.stock_actual)
    return stocks


class _SoloConsulta(Exception):
    """Corta el registro cuando se eligió "Stock disponible": se muestra el stock y no se guarda nada."""


def mensaje_de_resultado(tipo: str, cantidad: float, resultado) -> str:
    rep = resultado.repuesto
    una = rep.unidad_medida == "unidad" and cantidad == 1  # "Se quitó 1 unidad" / "Se quitaron 4 unidades"
    accion = {"ingreso": ("Se agregaron", "Se agregó"), "egreso": ("Se quitaron", "Se quitó")}[tipo][una]
    return f"Listo. {accion} {texto_cantidad(rep, cantidad)} de {rep.codigo}. Ahora hay {texto_cantidad(rep, rep.stock_actual)}."


# ---------------------------------------------------------------- Historial (filtro desde la URL)

DIAS_POR_DEFECTO = 30
POR_PAGINA = 50


def filtro_desde_pedido(opciones: dict) -> tuple:
    """Arma el FiltroMovimientos con lo que vino en la URL (?desde=&hasta=&tipo=&repuesto=).

    Sin fechas se muestran los últimos 30 días. Devuelve (datos_del_formulario, filtro);
    si algo no es válido lanza FiltroInvalidoError con un mensaje para el usuario.
    """
    hoy = date.today()
    datos = {
        "desde": request.args.get("desde", "").strip() or (hoy - timedelta(days=DIAS_POR_DEFECTO)).isoformat(),
        "hasta": request.args.get("hasta", "").strip() or hoy.isoformat(),
        "tipo": request.args.get("tipo", "").strip(),
        "repuesto": request.args.get("repuesto", "").strip(),
    }
    repuesto_id = None
    if datos["repuesto"]:
        rep = buscar_repuesto_elegido(opciones, datos["repuesto"])
        if rep is None:
            raise FiltroInvalidoError("Elegí un repuesto de la lista (o dejalo vacío para ver todos).")
        repuesto_id = rep.id
    filtro = FiltroMovimientos(datos["desde"], datos["hasta"], datos["tipo"] or None, repuesto_id)
    return datos, filtro


# ---------------------------------------------------------------- Catálogo (ayudas)

def servicio_catalogo() -> ServicioCatalogo:
    conexion = obtener_bd()
    motor = MotorAlertas(reglas_por_defecto(), RepositorioAlertas(conexion))
    return ServicioCatalogo(GestorInventarioBD(conexion), motor)


def avisar_alertas_nuevas(alertas, codigo: str) -> None:
    for alerta in alertas:
        flash(f"Nuevo aviso — {ETIQUETAS_TIPO_ALERTA[alerta.tipo]}: {codigo}. Lo ves en Alertas.", "alerta")


def leer_numero(texto: str, nombre: str) -> float:
    try:
        return float((texto or "").strip().replace(",", "."))
    except ValueError:
        raise CatalogoInvalidoError(f"Escribí {nombre} con números.") from None


# ---------------------------------------------------------------- Rutas

def registrar_rutas(app: Flask) -> None:
    """Define las pantallas de la aplicación. Todas requieren sesión iniciada."""

    @app.route("/")
    @login_required
    def index():
        gestor = GestorInventarioBD(obtener_bd())
        repuestos = gestor.obtener_repuestos()
        # Cada Repuesto sabe calcular su propio estado (modules/modelos.py).
        cantidad_por_estado = Counter(r.estado() for r in repuestos)

        return render_template(
            "index.html",
            hoy=date.today().strftime("%d/%m/%Y"),
            total_repuestos=len(repuestos),
            total_categorias=len(gestor.obtener_categorias()),
            total_marcas=len(gestor.obtener_marcas()),
            cantidad_por_estado=cantidad_por_estado,
            etiquetas=ETIQUETAS_ESTADO,
            clases_css=CLASE_CSS_ESTADO,
            Estado=EstadoStock,
        )

    @app.route("/alertas")
    @login_required
    def alertas():
        """Lista de alertas abiertas, lo más urgente primero."""
        gestor = GestorInventarioBD(obtener_bd())
        abiertas = RepositorioAlertas(obtener_bd()).obtener_abiertas()
        # Sin umbrales no se puede avisar nada (con stock 0 su estado es "Agotado", igual van acá)
        sin_datos = [r for r in gestor.obtener_repuestos() if not r.tiene_umbrales()]
        return render_template(
            "alertas.html",
            filas=filas_de_alertas(gestor, abiertas),
            sin_datos=sin_datos,
        )

    @app.route("/alertas/<int:alerta_id>/atendida", methods=["POST"])
    @login_required
    def atender_alerta(alerta_id: int):
        """Botón "Ya lo pedí" / "Entendido": cierra la alerta (queda en el historial)."""
        try:
            RepositorioAlertas(obtener_bd()).marcar_atendida(alerta_id)
            flash("Listo: la alerta quedó cerrada.", "success")
        except AlertaNoEncontradaError:
            flash("Esa alerta ya estaba cerrada o no existe.", "warning")
        # POST -> redirect -> GET: recargar la página no repite la acción.
        return redirect(url_for("alertas"))

    @app.route("/alertas/revisar", methods=["POST"])
    @login_required
    def revisar_alertas():
        """Botón "Revisar todo": aplica las reglas a los repuestos YA CONTADOS.

        Decisión del equipo (20/10): los repuestos que todavía no se contaron
        tienen el stock "inflado" de la carga histórica y darían alertas falsas,
        así que no se revisan hasta que se cuenten.
        """
        conexion = obtener_bd()
        gestor = GestorInventarioBD(conexion)
        motor = MotorAlertas(reglas_por_defecto(), RepositorioAlertas(conexion))
        contados = gestor.obtener_repuestos_contados()
        nuevas = motor.revisar_todos(contados)
        faltan = len(gestor.obtener_repuestos()) - len(contados)
        resumen = (f"Se encontraron {len(nuevas)} alertas nuevas" if len(nuevas) > 1
                   else "Se encontró 1 alerta nueva" if nuevas else "No hay alertas nuevas")
        donde = "en el repuesto ya contado" if len(contados) == 1 else f"en los {len(contados)} repuestos ya contados"
        flash(f"{resumen} {donde}.", "success")
        if faltan:
            cuantos = "Falta contar 1 repuesto" if faltan == 1 else f"Faltan contar {faltan} repuestos"
            flash(f"{cuantos}: no se revisan hasta que se cuenten, "
                  "porque su stock todavía no es el del estante.", "alerta")
        return redirect(url_for("alertas"))

    @app.route("/movimientos/nuevo", methods=["GET", "POST"])
    @login_required
    def registrar_movimiento():
        """Formulario para cargar un uso, una compra o un conteo de un repuesto."""
        conexion = obtener_bd()
        gestor = GestorInventarioBD(conexion)
        opciones = opciones_de_repuestos(gestor)
        hoy = date.today().isoformat()
        datos = {"tipo": "egreso", "fecha": hoy, "repuesto": "", "cantidad": "", "proveedor_id": ""}
        error = None
        consulta = None  # texto de "Stock disponible" cuando se consulta sin JavaScript

        if request.method == "POST":
            datos.update({k: request.form.get(k, "").strip() for k in datos})
            try:
                rep = buscar_repuesto_elegido(opciones, datos["repuesto"])
                if rep is None:
                    raise MovimientoInvalidoError("Elegí un repuesto de la lista.")
                if datos["tipo"] == "stock":
                    # Solo consulta: no se guarda ningún movimiento.
                    consulta = f"Stock disponible de {rep.codigo}: {texto_cantidad(rep, rep.stock_actual)}."
                    raise _SoloConsulta
                if not datos["cantidad"]:
                    raise MovimientoInvalidoError("Falta la cantidad.")
                try:
                    cantidad = float(datos["cantidad"].replace(",", "."))
                except ValueError:
                    raise MovimientoInvalidoError("Escribí la cantidad con números.") from None
                motor = MotorAlertas(reglas_por_defecto(), RepositorioAlertas(conexion))
                servicio = ServicioMovimientos(gestor, motor)
                if datos["tipo"] == "ingreso":
                    proveedor_id = int(datos["proveedor_id"]) if datos["proveedor_id"] else None
                    resultado = servicio.registrar_ingreso(rep.id, cantidad, datos["fecha"], proveedor_id)
                elif datos["tipo"] == "egreso":
                    resultado = servicio.registrar_egreso(rep.id, cantidad, datos["fecha"])
                else:
                    raise MovimientoInvalidoError("Elegí qué querés registrar.")
            except _SoloConsulta:
                pass
            except MovimientoInvalidoError as e:
                error = str(e)
            else:
                flash(mensaje_de_resultado(datos["tipo"], cantidad, resultado), "success")
                avisar_alertas_nuevas(resultado.alertas_nuevas, rep.codigo)
                # POST -> redirect -> GET: queda el formulario limpio para cargar otro
                return redirect(url_for("registrar_movimiento"))

        return render_template(
            "registrar_movimiento.html",
            datos=datos,
            error=error,
            consulta=consulta,
            tipos=TIPOS_MOVIMIENTO_FORMULARIO,
            opciones=opciones,
            stock_por_texto=stock_por_texto(opciones),
            proveedores=gestor.obtener_proveedores(solo_activos=True),
            hoy=hoy,
        ), (400 if error else 200)

    @app.route("/movimientos")
    @login_required
    def movimientos():
        """Historial de movimientos con filtros por fecha, tipo y repuesto."""
        conexion = obtener_bd()
        opciones = opciones_de_repuestos(GestorInventarioBD(conexion))
        filas, error = [], None
        try:
            datos, filtro = filtro_desde_pedido(opciones)
            filas = ConsultaMovimientos(conexion).buscar(filtro)
        except FiltroInvalidoError as e:
            error = str(e)
            datos = {k: request.args.get(k, "") for k in ("desde", "hasta", "tipo", "repuesto")}
        # Paginación: se muestran 50 por página (las descargas llevan todo lo filtrado)
        paginas = max(1, -(-len(filas) // POR_PAGINA))
        pagina = min(max(request.args.get("pagina", 1, type=int), 1), paginas)
        return render_template(
            "movimientos.html",
            datos=datos,
            filas=filas[(pagina - 1) * POR_PAGINA: pagina * POR_PAGINA],
            total=len(filas),
            pagina=pagina,
            paginas=paginas,
            error=error,
            conteo=contar_por_tipo(filas),
            tipos=ETIQUETAS_TIPO_MOVIMIENTO,
            opciones=opciones,
            hoy=date.today().isoformat(),
            # Los links de descarga repiten el mismo filtro de la pantalla
            parametros_filtro={k: v for k, v in datos.items() if v},
        ), (400 if error else 200)

    @app.route("/movimientos/<int:movimiento_id>/anular", methods=["GET", "POST"])
    @login_required
    def anular_movimiento(movimiento_id: int):
        """Corregir un movimiento cargado por error.

        GET muestra qué se va a anular y pide confirmación; POST lo anula.
        La confirmación es una pantalla propia (no un cartel del navegador):
        así se ve exactamente qué movimiento es antes de tocar nada.
        """
        conexion = obtener_bd()
        gestor = GestorInventarioBD(conexion)
        original = gestor.obtener_movimiento(movimiento_id)
        if original is None:
            abort(404)
        rep = gestor.obtener_repuesto_id(original.repuesto_id)
        if request.method == "POST":
            motor = MotorAlertas(reglas_por_defecto(), RepositorioAlertas(conexion))
            try:
                resultado = ServicioMovimientos(gestor, motor).anular(movimiento_id)
            except MovimientoInvalidoError as e:
                flash(str(e), "warning")
            else:
                flash(f"Listo: movimiento anulado. {rep.codigo} quedó con "
                      f"{texto_cantidad(rep, resultado.repuesto.stock_actual)}.", "success")
                avisar_alertas_nuevas(resultado.alertas_nuevas, rep.codigo)
            return redirect(url_for("movimientos", **{k: v for k, v in request.args.items()}))
        filtro = FiltroMovimientos(original.fecha, original.fecha, repuesto_id=original.repuesto_id)
        fila = next(f for f in ConsultaMovimientos(conexion).buscar(filtro) if f.id == movimiento_id)
        return render_template("anular_movimiento.html", fila=fila, volver=request.args)

    @app.route("/movimientos/descargar/<formato>")
    @login_required
    def descargar_movimientos(formato: str):
        """Descarga lo que se ve en la pantalla, en Excel o PDF."""
        exportador = EXPORTADORES.get(formato)
        if exportador is None:
            abort(404)
        conexion = obtener_bd()
        try:
            _, filtro = filtro_desde_pedido(opciones_de_repuestos(GestorInventarioBD(conexion)))
        except FiltroInvalidoError as e:
            flash(str(e), "warning")
            return redirect(url_for("movimientos"))
        contenido = exportador.exportar(ConsultaMovimientos(conexion).buscar(filtro), filtro)
        return send_file(
            io.BytesIO(contenido),
            mimetype=exportador.tipo_mime,
            as_attachment=True,
            download_name=f"movimientos_{filtro.desde}_{filtro.hasta}.{exportador.extension}",
        )

    @app.route("/catalogo")
    @login_required
    def catalogo():
        """Lista de repuestos con buscador y filtros por categoría y estado."""
        gestor = GestorInventarioBD(obtener_bd())
        datos = {k: request.args.get(k, "").strip() for k in ("texto", "categoria", "estado", "inactivos")}
        estado = EstadoStock[datos["estado"]] if datos["estado"] in EstadoStock.__members__ else None
        filtro = FiltroCatalogo(
            texto=datos["texto"],
            categoria_id=int(datos["categoria"]) if datos["categoria"].isdigit() else None,
            estado=estado,
            incluir_inactivos=datos["inactivos"] == "1",
        )
        return render_template(
            "catalogo.html",
            fichas=servicio_catalogo().listar(filtro),
            datos=datos,
            categorias=gestor.obtener_categorias(),
            etiquetas=ETIQUETAS_ESTADO,
            clases_css=CLASE_CSS_ESTADO,
            texto_cantidad=texto_cantidad,
        )

    @app.route("/catalogo/nuevo", methods=["GET", "POST"])
    @login_required
    def nuevo_repuesto():
        """Alta de un repuesto que no estaba en el catálogo."""
        gestor = GestorInventarioBD(obtener_bd())
        datos = {k: request.form.get(k, "").strip() for k in ("codigo", "marca", "categoria", "especificaciones", "unidad")}
        error = None
        if request.method == "POST":
            try:
                nuevo_id = servicio_catalogo().crear(datos["codigo"], datos["marca"], datos["categoria"],
                                                     datos["especificaciones"], datos["unidad"] or "unidad")
            except CatalogoInvalidoError as e:
                error = str(e)
            else:
                flash(f"Listo: {datos['codigo']} quedó en el catálogo. Cargale una compra o un conteo.", "success")
                return redirect(url_for("ficha_repuesto", repuesto_id=nuevo_id))
        return render_template(
            "nuevo_repuesto.html",
            datos=datos,
            error=error,
            marcas=gestor.obtener_marcas(),
            categorias=gestor.obtener_categorias(),
        ), (400 if error else 200)

    @app.route("/catalogo/<int:repuesto_id>")
    @login_required
    def ficha_repuesto(repuesto_id: int):
        """Ficha de un repuesto: datos, stock, estado, umbrales y acciones."""
        try:
            ficha = servicio_catalogo().ficha(repuesto_id)
        except RepuestoNoEncontradoError:
            abort(404)
        return render_template(
            "ficha_repuesto.html",
            ficha=ficha,
            rep=ficha.repuesto,
            etiquetas=ETIQUETAS_ESTADO,
            clases_css=CLASE_CSS_ESTADO,
            umbrales=ETIQUETAS_UMBRALES,
            texto_cantidad=texto_cantidad,
            categorias=GestorInventarioBD(obtener_bd()).obtener_categorias(),
            Estado=EstadoStock,
        )

    def _accion_en_ficha(repuesto_id: int, accion):
        """Ejecuta una acción de la ficha y vuelve a ella (POST -> redirect -> GET)."""
        try:
            accion()
        except CatalogoInvalidoError as e:
            flash(str(e), "warning")
        except RepuestoNoEncontradoError:
            abort(404)
        return redirect(url_for("ficha_repuesto", repuesto_id=repuesto_id))

    @app.route("/catalogo/<int:repuesto_id>/datos", methods=["POST"])
    @login_required
    def corregir_repuesto(repuesto_id: int):
        def accion():
            servicio_catalogo().corregir_datos(repuesto_id, request.form.get("categoria", ""),
                                               request.form.get("especificaciones", ""))
            flash("Listo: datos guardados.", "success")
        return _accion_en_ficha(repuesto_id, accion)

    @app.route("/catalogo/<int:repuesto_id>/umbrales", methods=["POST"])
    @login_required
    def umbrales_repuesto(repuesto_id: int):
        def accion():
            servicio = servicio_catalogo()
            nuevas = servicio.fijar_umbrales(
                repuesto_id,
                minimo=leer_numero(request.form.get("stock_minimo"), "el mínimo"),
                reorden=leer_numero(request.form.get("punto_reorden"), "cuándo pedir"),
                maximo=leer_numero(request.form.get("stock_maximo"), "el máximo"),
            )
            flash("Listo: umbrales guardados. El cálculo automático ya no los va a cambiar.", "success")
            avisar_alertas_nuevas(nuevas, servicio.ficha(repuesto_id).repuesto.codigo)
        return _accion_en_ficha(repuesto_id, accion)

    @app.route("/catalogo/<int:repuesto_id>/automatico", methods=["POST"])
    @login_required
    def automatico_repuesto(repuesto_id: int):
        def accion():
            if servicio_catalogo().volver_a_automatico(repuesto_id) is None:
                flash("Volvió al cálculo automático, pero todavía no tiene compras para calcular: "
                      "quedan los umbrales que tenía.", "warning")
            else:
                flash("Listo: umbrales recalculados con el historial de compras.", "success")
        return _accion_en_ficha(repuesto_id, accion)

    @app.route("/catalogo/<int:repuesto_id>/activo", methods=["POST"])
    @login_required
    def activo_repuesto(repuesto_id: int):
        def accion():
            servicio = servicio_catalogo()
            if request.form.get("accion") == "activar":
                nuevas = servicio.activar(repuesto_id)
                flash("Listo: el repuesto está activo otra vez.", "success")
                avisar_alertas_nuevas(nuevas, servicio.ficha(repuesto_id).repuesto.codigo)
            else:
                servicio.inactivar(repuesto_id)
                flash("Listo: el repuesto quedó inactivo. No se borró nada; se puede volver a activar.", "success")
        return _accion_en_ficha(repuesto_id, accion)

    # ------------------------------------------------------------ Dashboard

    @app.route("/dashboard")
    @login_required
    def dashboard():
        """El estado del stock de un vistazo: estados, conteo, rotación, inmovilizado y compras."""
        conexion = obtener_bd()
        gestor = GestorInventarioBD(conexion)
        consulta = ConsultaDashboard(conexion, gestor)
        mas, menos = consulta.rotacion()
        meses = consulta.compras_por_mes()
        proveedores_resumen = [r for r in ConsultaProveedores(conexion).resumen() if r.compras]
        return render_template(
            "dashboard.html",
            estados=consulta.estados(),
            avance=consulta.avance_conteo(),
            mas=mas,
            menos=menos,
            inmovilizado=consulta.inmovilizado(),
            dias_quieto=DIAS_SIN_MOVIMIENTO,
            meses=meses,
            max_lineas_mes=max((m.lineas for m in meses), default=1),
            proveedores=proveedores_resumen,
            total_compras=sum(r.compras for r in proveedores_resumen) or 1,
            alertas_abiertas_total=len(RepositorioAlertas(conexion).obtener_abiertas()),
            etiquetas=ETIQUETAS_ESTADO,
            clases_css=CLASE_CSS_ESTADO,
            Estado=EstadoStock,
            texto_cantidad=texto_cantidad,
        )

    # ------------------------------------------------------------ Proveedores

    def _datos_proveedor() -> dict:
        return {k: request.form.get(k, "").strip() for k in ("nombre", "contacto", "telefono", "email")}

    @app.route("/proveedores")
    @login_required
    def proveedores():
        """A quién se le compra: compras, repuestos, unidades y última compra por proveedor."""
        incluir_inactivos = request.args.get("inactivos") == "1"
        resumen = ConsultaProveedores(obtener_bd()).resumen(incluir_inactivos)
        total_compras = sum(r.compras for r in resumen) or 1
        return render_template(
            "proveedores.html",
            resumen=resumen,
            total_compras=total_compras,
            hoy=date.today(),
            incluir_inactivos=incluir_inactivos,
        )

    @app.route("/proveedores/nuevo", methods=["GET", "POST"])
    @login_required
    def nuevo_proveedor():
        datos, error = _datos_proveedor(), None
        if request.method == "POST":
            try:
                nuevo_id = ServicioProveedores(GestorInventarioBD(obtener_bd())).crear(**datos)
            except ProveedorInvalidoError as e:
                error = str(e)
            else:
                flash(f"Listo: {datos['nombre']} quedó cargado. Ya se puede elegir al registrar una compra.", "success")
                return redirect(url_for("ficha_proveedor", proveedor_id=nuevo_id))
        return render_template("nuevo_proveedor.html", datos=datos, error=error), (400 if error else 200)

    @app.route("/proveedores/<int:proveedor_id>")
    @login_required
    def ficha_proveedor(proveedor_id: int):
        conexion = obtener_bd()
        try:
            proveedor = ServicioProveedores(GestorInventarioBD(conexion)).obtener(proveedor_id)
        except ProveedorNoEncontradoError:
            abort(404)
        consulta = ConsultaProveedores(conexion)
        resumen = next(r for r in consulta.resumen(incluir_inactivos=True) if r.proveedor.id == proveedor_id)
        return render_template(
            "ficha_proveedor.html",
            p=proveedor,
            resumen=resumen,
            compras=consulta.repuestos_comprados(proveedor_id),
            hoy=date.today(),
        )

    @app.route("/proveedores/<int:proveedor_id>/datos", methods=["POST"])
    @login_required
    def corregir_proveedor(proveedor_id: int):
        try:
            ServicioProveedores(GestorInventarioBD(obtener_bd())).corregir(proveedor_id, **_datos_proveedor())
            flash("Listo: datos guardados.", "success")
        except ProveedorInvalidoError as e:
            flash(str(e), "warning")
        except ProveedorNoEncontradoError:
            abort(404)
        return redirect(url_for("ficha_proveedor", proveedor_id=proveedor_id))

    @app.route("/proveedores/<int:proveedor_id>/activo", methods=["POST"])
    @login_required
    def activo_proveedor(proveedor_id: int):
        servicio = ServicioProveedores(GestorInventarioBD(obtener_bd()))
        try:
            if request.form.get("accion") == "activar":
                servicio.activar(proveedor_id)
                flash("Listo: el proveedor está activo otra vez.", "success")
            else:
                servicio.desactivar(proveedor_id)
                flash("Listo: el proveedor quedó inactivo. Su historial de compras no se borra.", "success")
        except ProveedorNoEncontradoError:
            abort(404)
        return redirect(url_for("ficha_proveedor", proveedor_id=proveedor_id))

    @app.context_processor
    def datos_del_menu():
        """Cantidad de alertas abiertas para el contador del menú lateral."""
        if "email" not in session:
            return {}
        return {"alertas_abiertas": len(RepositorioAlertas(obtener_bd()).obtener_abiertas())}


# ---------------------------------------------------------------- Fábrica

def actualizar_umbrales() -> int:
    """Recalcula los umbrales de todos los repuestos con el historial de compras.

    Se hace al arrancar la app: así nunca quedan repuestos "sin datos" que ya
    tienen compras, y los umbrales acompañan las compras nuevas. Los corregidos
    a mano no se tocan (ServicioParametrosStock los saltea).
    Devuelve cuántos repuestos se actualizaron.
    """
    conexion = obtener_conexion(DATABASE_URL)
    try:
        return ServicioParametrosStock.desde_historial(GestorInventarioBD(conexion)).recalcular_todos()
    finally:
        conexion.close()


def create_app() -> Flask:
    """Crea y configura la aplicación (patrón fábrica, como el ejemplo de la cátedra)."""
    if not SECRET_KEY:
        raise RuntimeError("Falta SECRET_KEY en el archivo .env.")

    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static"),
    )
    app.config["SECRET_KEY"] = SECRET_KEY
    app.config["SESSION_TYPE"] = "filesystem"
    # Dónde se guardan las sesiones. Las pruebas usan una carpeta temporal
    # (ver tests/__init__.py) para no llenar flask_session/ del proyecto.
    app.config["SESSION_FILE_DIR"] = os.environ.get("CARPETA_SESIONES", str(BASE_DIR / "flask_session"))

    inicializar_si_hace_falta(DATABASE_URL, RUTA_EXCEL_HISTORICO)
    actualizar_umbrales()
    app.teardown_appcontext(cerrar_bd)
    configurar_autenticacion(app)
    registrar_rutas(app)
    return app
