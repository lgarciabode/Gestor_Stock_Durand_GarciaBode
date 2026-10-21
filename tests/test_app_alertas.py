"""Pruebas de la pantalla de alertas de la interfaz web (Paso 8).

Se usa el cliente de prueba de Flask: hace pedidos al servidor sin abrir un
navegador. La base es una SQLite temporal (no se toca la real) y la sesión se
simula escribiendo el email, que es lo que mira `login_required`.

Si Flask o auth-module no están instalados, estas pruebas se saltean.

unittest puro, patron AAA (Arrange, Act, Assert).
"""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

HAY_FLASK = all(importlib.util.find_spec(m) for m in ("flask", "auth_module"))

if HAY_FLASK:
    os.environ.setdefault("DATABASE_URL", "data/stock_taller.sqlite3")  # config.py lo exige al importarse
    from apps import app_1

from modules.alertas import MotorAlertas, reglas_por_defecto
from modules.base_datos import crear_esquema, obtener_conexion
from modules.crud import GestorInventarioBD, RepositorioAlertas
from modules.modelos import Categoria, Marca, MovimientoStock, Repuesto

HOY = "2026-10-20"


@unittest.skipUnless(HAY_FLASK, "Flask / auth-module no instalados")
class PruebaPantallaAlertas(unittest.TestCase):

    def setUp(self):
        # Base temporal con dos rodamientos: uno para pedir y uno con stock de más
        self.directorio = tempfile.TemporaryDirectory()
        ruta_bd = str(Path(self.directorio.name) / "stock.sqlite3")
        conexion = obtener_conexion(ruta_bd)
        crear_esquema(conexion)
        conexion.execute("UPDATE estado_sistema SET carga_inicial_completa = 1 WHERE id = 1")
        gestor = GestorInventarioBD(conexion)
        zkl = gestor.crear_marca(Marca(id=None, nombre="ZKL"))
        rod = gestor.crear_categoria(Categoria(id=None, nombre="RODAMIENTO"))
        self.ids = {}
        for codigo, stock in (("6204 2RS", 3), ("6207 2RS", 30)):
            rid = gestor.crear_repuestos(Repuesto(id=None, codigo=codigo, marca_id=zkl, categoria_id=rod))
            gestor.registrar_movimiento(MovimientoStock(id=None, repuesto_id=rid, fecha=HOY, tipo="INGRESO", cantidad=stock))
            gestor.actualizar_parametros_stock(rid, stock_minimo=2, stock_maximo=18, punto_reorden=4)
            self.ids[codigo] = rid
        gestor.crear_repuestos(Repuesto(id=None, codigo="NUEVO-1", marca_id=zkl, categoria_id=rod))  # sin umbrales
        conexion.close()

        # La app apunta a la base temporal
        self.parches = [
            patch.object(app_1, "DATABASE_URL", ruta_bd),
            patch.object(app_1, "SECRET_KEY", "clave-de-prueba"),
            patch.object(app_1, "RUTA_BD_USUARIOS", str(Path(self.directorio.name) / "usuarios.sqlite3")),
        ]
        for p in self.parches:
            p.start()
        app = app_1.create_app()
        app.config["TESTING"] = True
        self.cliente = app.test_client()
        with self.cliente.session_transaction() as sesion:
            sesion["email"] = "cami@taller.com"
        self.ruta_bd = ruta_bd

    def tearDown(self):
        for p in self.parches:
            p.stop()
        self.directorio.cleanup()

    def crear_alertas(self):
        conexion = obtener_conexion(self.ruta_bd)
        try:
            motor = MotorAlertas(reglas_por_defecto(), RepositorioAlertas(conexion), hoy=lambda: HOY)
            return motor.revisar_todos(GestorInventarioBD(conexion).obtener_repuestos())
        finally:
            conexion.close()

    def abiertas(self):
        conexion = obtener_conexion(self.ruta_bd)
        try:
            return RepositorioAlertas(conexion).obtener_abiertas()
        finally:
            conexion.close()

    # ------------------------------------------------------------ ver la lista

    def test_sin_sesion_redirige_al_login(self):
        with self.cliente.session_transaction() as sesion:
            sesion.clear()

        respuesta = self.cliente.get("/alertas")

        self.assertEqual(respuesta.status_code, 302)
        self.assertIn("/auth/login", respuesta.headers["Location"])

    def test_sin_alertas_muestra_que_esta_todo_en_orden(self):
        html = self.cliente.get("/alertas").get_data(as_text=True)
        self.assertIn("No hay alertas sin atender", html)

    def test_lista_las_alertas_abiertas_con_palabras_del_taller(self):
        # Arrange
        self.crear_alertas()

        # Act
        html = self.cliente.get("/alertas").get_data(as_text=True)

        # Assert: badge, codigo, detalle sin repetir el tipo, boton segun el tipo
        self.assertIn("2 sin atender", html)
        self.assertIn("Hay que pedir", html)
        self.assertIn("6204 2RS", html)
        self.assertIn("quedan 3 unidades (pedir cuando queden 4 unidades)", html)
        self.assertIn("Ya lo pedí", html)
        self.assertIn("Entendido", html)  # "Sobra stock" no se "pide"
        self.assertIn("20/10/2026", html)

    def test_lo_mas_urgente_aparece_primero(self):
        self.crear_alertas()
        html = self.cliente.get("/alertas").get_data(as_text=True)
        self.assertLess(html.index("Hay que pedir"), html.index("Sobra stock"))

    def test_muestra_los_repuestos_sin_datos(self):
        html = self.cliente.get("/alertas").get_data(as_text=True)
        self.assertIn("1 repuesto sin datos todavía", html)
        self.assertIn("NUEVO-1", html)

    def test_el_menu_muestra_cuantas_alertas_hay(self):
        self.crear_alertas()
        html = self.cliente.get("/").get_data(as_text=True)
        self.assertIn('<span class="contador" title="Alertas sin atender">2</span>', html)

    # ------------------------------------------------------------ acciones

    def test_ya_lo_pedi_cierra_la_alerta_y_vuelve_a_la_lista(self):
        # Arrange
        reorden = next(a for a in self.crear_alertas() if a.tipo == "REORDEN")

        # Act: POST y despues se sigue la redireccion (POST -> redirect -> GET)
        respuesta = self.cliente.post(f"/alertas/{reorden.id}/atendida", follow_redirects=True)

        # Assert
        self.assertEqual(respuesta.request.path, "/alertas")
        self.assertIn("la alerta quedó cerrada", respuesta.get_data(as_text=True))
        self.assertEqual([a.tipo for a in self.abiertas()], ["SOBRESTOCK"])

    def test_cerrar_dos_veces_avisa_sin_romper(self):
        alerta = self.crear_alertas()[0]
        self.cliente.post(f"/alertas/{alerta.id}/atendida")

        respuesta = self.cliente.post(f"/alertas/{alerta.id}/atendida", follow_redirects=True)

        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("ya estaba cerrada", respuesta.get_data(as_text=True))

    def test_cerrar_solo_acepta_post(self):
        # Un link (GET) no puede cerrar alertas por accidente
        alerta = self.crear_alertas()[0]
        self.assertEqual(self.cliente.get(f"/alertas/{alerta.id}/atendida").status_code, 405)

    def test_revisar_todo_crea_las_que_faltan_sin_duplicar(self):
        # Act
        primera = self.cliente.post("/alertas/revisar", follow_redirects=True).get_data(as_text=True)
        segunda = self.cliente.post("/alertas/revisar", follow_redirects=True).get_data(as_text=True)

        # Assert
        self.assertIn("Se encontraron 2 alertas nuevas", primera)
        self.assertIn("No hay alertas nuevas", segunda)
        self.assertEqual(len(self.abiertas()), 2)


if __name__ == "__main__":
    unittest.main()
