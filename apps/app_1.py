"""Interfaz web (Flask) del Gestor de Stock.

Capa de presentación (patrón en capas / MVC): recibe los pedidos del
navegador, le pide los datos a las clases de modules/ y los muestra con un
template. No contiene reglas de negocio.

La autenticación la resuelve auth-module (biblioteca de la cátedra / LICA):
https://github.com/FIUNER-LICA/auth-module

Ejecutar desde la raíz del proyecto:
    flask --app apps.app_1 run --debug
"""
from collections import Counter
from datetime import date

from flask import Flask, flash, g, redirect, render_template, session, url_for

from auth_module.core.auth_manager import AuthManager
from auth_module.core.db.sqlite_repository import SQLiteUserRepository
from auth_module.core.mail.dispatchers import ConsoleMailDispatcher
from auth_module.flask_ext.decorators import login_required
from auth_module.flask_ext.extension import FlaskExtension

from config import (BASE_DIR, DATABASE_URL, RUTA_BD_USUARIOS,
                    RUTA_EXCEL_HISTORICO, SECRET_KEY)
from modules.alertas import (ETIQUETAS_ATENDER_ALERTA, ETIQUETAS_ESTADO,
                             ETIQUETAS_TIPO_ALERTA, MotorAlertas,
                             reglas_por_defecto)
from modules.base_datos import inicializar_si_hace_falta, obtener_conexion
from modules.crud import (AlertaNoEncontradaError, GestorInventarioBD,
                          RepositorioAlertas)
from modules.modelos import EstadoStock

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
