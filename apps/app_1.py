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

from flask import Flask, g, render_template

from auth_module.core.auth_manager import AuthManager
from auth_module.core.db.sqlite_repository import SQLiteUserRepository
from auth_module.core.mail.dispatchers import ConsoleMailDispatcher
from auth_module.flask_ext.decorators import login_required
from auth_module.flask_ext.extension import FlaskExtension

from config import (BASE_DIR, DATABASE_URL, RUTA_BD_USUARIOS,
                    RUTA_EXCEL_HISTORICO, SECRET_KEY)
from modules.alertas import ETIQUETAS_ESTADO
from modules.base_datos import inicializar_si_hace_falta, obtener_conexion
from modules.crud import GestorInventarioBD
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
