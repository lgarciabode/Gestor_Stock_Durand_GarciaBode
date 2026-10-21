"""Pruebas de las pantallas del catalogo (Paso 11).

Cliente de prueba de Flask sobre una base SQLite temporal. Si Flask o
auth-module no estan instalados, se saltean.

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

from modules.base_datos import crear_esquema, obtener_conexion
from modules.crud import GestorInventarioBD
from modules.modelos import Categoria, Marca, MovimientoStock, Repuesto


@unittest.skipUnless(HAY_FLASK, "Flask / auth-module no instalados")
class PruebaPantallasCatalogo(unittest.TestCase):

    def setUp(self):
        self.directorio = tempfile.TemporaryDirectory()
        self.ruta_bd = str(Path(self.directorio.name) / "stock.sqlite3")
        conexion = obtener_conexion(self.ruta_bd)
        crear_esquema(conexion)
        conexion.execute("UPDATE estado_sistema SET carga_inicial_completa = 1 WHERE id = 1")
        gestor = GestorInventarioBD(conexion)
        zkl = gestor.crear_marca(Marca(id=None, nombre="ZKL"))
        rod = gestor.crear_categoria(Categoria(id=None, nombre="RODAMIENTO"))
        self.con_stock = gestor.crear_repuestos(Repuesto(id=None, codigo="6204 2RS", marca_id=zkl, categoria_id=rod))
        self.sin_stock = gestor.crear_repuestos(Repuesto(id=None, codigo="6205 2RS", marca_id=zkl, categoria_id=rod))
        gestor.registrar_movimiento(MovimientoStock(id=None, repuesto_id=self.con_stock, fecha="2026-10-01",
                                                    tipo="INGRESO", cantidad=10))
        conexion.close()

        self.parches = [
            patch.object(app_1, "DATABASE_URL", self.ruta_bd),
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

    def tearDown(self):
        for p in self.parches:
            p.stop()
        self.directorio.cleanup()

    def html(self, url):
        return self.cliente.get(url).get_data(as_text=True)

    def rep(self, repuesto_id):
        conexion = obtener_conexion(self.ruta_bd)
        try:
            return GestorInventarioBD(conexion).obtener_repuesto_id(repuesto_id)
        finally:
            conexion.close()

    # ------------------------------------------------------------ lista y ficha

    def test_lista_con_stock_y_estado(self):
        html = self.html("/catalogo")
        self.assertIn("2 repuestos", html)
        self.assertIn("10 unidades", html)
        self.assertIn("Agotado", html)
        self.assertIn(f'href="/catalogo/{self.con_stock}"', html)

    def test_buscar_y_filtrar_por_estado(self):
        self.assertIn("1 repuesto<", self.html("/catalogo?texto=6205"))
        self.assertIn("1 repuesto<", self.html("/catalogo?estado=AGOTADO"))

    def test_ficha_y_ficha_inexistente(self):
        # Con compras: umbrales calculados al arrancar. Sin compras: "sin datos"
        self.assertIn("Calculado con las compras", self.html(f"/catalogo/{self.con_stock}"))
        self.assertIn("Sin datos todavía", self.html(f"/catalogo/{self.sin_stock}"))
        self.assertEqual(self.cliente.get("/catalogo/999").status_code, 404)

    def test_al_arrancar_se_calculan_los_umbrales(self):
        # El repuesto con compras ya tiene umbrales, sin haber hecho nada mas
        rep = self.rep(self.con_stock)
        self.assertTrue(rep.tiene_umbrales())
        self.assertFalse(rep.parametros_manuales)
        self.assertFalse(self.rep(self.sin_stock).tiene_umbrales())

    # ------------------------------------------------------------ acciones

    def test_crear_repuesto_y_ir_a_su_ficha(self):
        respuesta = self.cliente.post("/catalogo/nuevo", data={
            "codigo": "6206 2RS", "marca": "ZKL", "categoria": "RODAMIENTO", "especificaciones": "", "unidad": "unidad",
        }, follow_redirects=True)
        self.assertIn("6206 2RS quedó en el catálogo", respuesta.get_data(as_text=True))
        self.assertTrue(respuesta.request.path.startswith("/catalogo/"))

    def test_crear_repetido_muestra_el_motivo(self):
        respuesta = self.cliente.post("/catalogo/nuevo", data={
            "codigo": "6204 2RS", "marca": "zkl", "categoria": "RODAMIENTO", "unidad": "unidad",
        })
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("Ya existe el repuesto 6204 2RS", respuesta.get_data(as_text=True))

    def test_umbrales_a_mano_y_su_alerta(self):
        # Act: con 10 en stock y maximo 6 -> "Sobra stock"
        html = self.cliente.post(f"/catalogo/{self.con_stock}/umbrales", data={
            "punto_reorden": "3", "stock_minimo": "1", "stock_maximo": "6"}, follow_redirects=True).get_data(as_text=True)

        # Assert
        self.assertIn("umbrales guardados", html)
        self.assertIn("Nuevo aviso — Sobra stock: 6204 2RS", html)
        self.assertIn("Volver al cálculo automático", html)
        self.assertTrue(self.rep(self.con_stock).parametros_manuales)

    def test_umbrales_incoherentes_avisan_sin_guardar(self):
        html = self.cliente.post(f"/catalogo/{self.con_stock}/umbrales", data={
            "punto_reorden": "1", "stock_minimo": "5", "stock_maximo": "6"}, follow_redirects=True).get_data(as_text=True)
        self.assertIn("mínimo ≤ punto de reorden ≤ máximo", html)
        self.assertFalse(self.rep(self.con_stock).parametros_manuales)  # quedaron los calculados

    def test_inactivar_solo_sin_stock_y_volver_a_activar(self):
        # Con stock: no se puede
        html = self.cliente.post(f"/catalogo/{self.con_stock}/activo", data={"accion": "inactivar"},
                                 follow_redirects=True).get_data(as_text=True)
        self.assertIn("Solo se inactiva un repuesto sin stock", html)
        self.assertTrue(self.rep(self.con_stock).activo)

        # Sin stock: si
        self.cliente.post(f"/catalogo/{self.sin_stock}/activo", data={"accion": "inactivar"})
        self.assertFalse(self.rep(self.sin_stock).activo)
        self.assertIn("1 repuesto<", self.html("/catalogo"))

        # Y vuelve
        self.cliente.post(f"/catalogo/{self.sin_stock}/activo", data={"accion": "activar"})
        self.assertTrue(self.rep(self.sin_stock).activo)

    def test_corregir_datos(self):
        self.cliente.post(f"/catalogo/{self.con_stock}/datos", data={"categoria": "rodamiento", "especificaciones": "sellado"})
        self.assertEqual(self.rep(self.con_stock).especificaciones, "sellado")


if __name__ == "__main__":
    unittest.main()
