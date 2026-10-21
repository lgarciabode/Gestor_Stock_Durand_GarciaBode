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
                             ETIQUETAS_TIPO_ALERTA, MotorAlertas,
                             reglas_por_defecto, texto_cantidad)
from modules.base_datos import inicializar_si_hace_falta, obtener_conexion
from modules.crud import (AlertaNoEncontradaError, GestorInventarioBD,
                          RepositorioAlertas)
from modules.modelos import EstadoStock
from modules.movimientos import MovimientoInvalidoError, ServicioMovimientos
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
TIPOS_MOVIMIENTO_FORMULARIO = {
    "egreso": "Quitar (se usó)",
    "ingreso": "Agregar (llegó una compra)",
    "conteo": "Hay en el estante (conteo)",
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


def mensaje_de_resultado(tipo: str, cantidad: float, resultado) -> str:
    rep = resultado.repuesto
    if tipo == "conteo" and resultado.movimiento_id is None:
        return f"Listo: {rep.codigo} ya tenía {texto_cantidad(rep, rep.stock_actual)}, no hubo que corregir nada."
    accion = {"ingreso": "Se agregaron", "egreso": "Se quitaron", "conteo": "Stock corregido:"}[tipo]
    if tipo == "conteo":
        return f"Listo. {accion} {rep.codigo} quedó en {texto_cantidad(rep, rep.stock_actual)}."
    return f"Listo. {accion} {texto_cantidad(rep, cantidad)} de {rep.codigo}. Ahora hay {texto_cantidad(rep, rep.stock_actual)}."


# ---------------------------------------------------------------- Historial (filtro desde la URL)

DIAS_POR_DEFECTO = 30


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
        """Botón "Revisar todo": aplica las reglas a todos los repuestos activos."""
        conexion = obtener_bd()
        motor = MotorAlertas(reglas_por_defecto(), RepositorioAlertas(conexion))
        nuevas = motor.revisar_todos(GestorInventarioBD(conexion).obtener_repuestos())
        if nuevas:
            flash(f"Se encontraron {len(nuevas)} alertas nuevas.", "success")
        else:
            flash("No hay alertas nuevas.", "success")
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

        if request.method == "POST":
            datos.update({k: request.form.get(k, "").strip() for k in datos})
            try:
                rep = buscar_repuesto_elegido(opciones, datos["repuesto"])
                if rep is None:
                    raise MovimientoInvalidoError("Elegí un repuesto de la lista.")
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
                elif datos["tipo"] == "conteo":
                    resultado = servicio.registrar_conteo(rep.id, cantidad, datos["fecha"])
                else:
                    raise MovimientoInvalidoError("Elegí qué querés registrar.")
            except MovimientoInvalidoError as e:
                error = str(e)
            else:
                flash(mensaje_de_resultado(datos["tipo"], cantidad, resultado), "success")
                for alerta in resultado.alertas_nuevas:
                    flash(f"Nuevo aviso — {ETIQUETAS_TIPO_ALERTA[alerta.tipo]}: {rep.codigo}. "
                          "Lo ves en Alertas.", "alerta")
                # POST -> redirect -> GET: queda el formulario limpio para cargar otro
                return redirect(url_for("registrar_movimiento"))

        return render_template(
            "registrar_movimiento.html",
            datos=datos,
            error=error,
            tipos=TIPOS_MOVIMIENTO_FORMULARIO,
            opciones=opciones,
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
        return render_template(
            "movimientos.html",
            datos=datos,
            filas=filas,
            error=error,
            conteo=contar_por_tipo(filas),
            tipos=ETIQUETAS_TIPO_MOVIMIENTO,
            opciones=opciones,
            hoy=date.today().isoformat(),
            # Los links de descarga repiten el mismo filtro de la pantalla
            parametros_filtro={k: v for k, v in datos.items() if v},
        ), (400 if error else 200)

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

    @app.context_processor
    def datos_del_menu():
        """Cantidad de alertas abiertas para el contador del menú lateral."""
        if "email" not in session:
            return {}
        return {"alertas_abiertas": len(RepositorioAlertas(obtener_bd()).obtener_abiertas())}


# ---------------------------------------------------------------- Fábrica

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

    inicializar_si_hace_falta(DATABASE_URL, RUTA_EXCEL_HISTORICO)
    app.teardown_appcontext(cerrar_bd)
    configurar_autenticacion(app)
    registrar_rutas(app)
    return app
