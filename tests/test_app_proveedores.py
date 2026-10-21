"""Pruebas de las pantallas de proveedores (Paso 13).

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
from modules.modelos import Categoria, Marca, MovimientoStock, Proveedor, Repuesto


@unittest.skipUnless(HAY_FLASK, "Flask / auth-module no instalados")
class PruebaPantallasProveedores(unittest.TestCase):

    def setUp(self):
        self.directorio = tempfile.TemporaryDirectory()
        self.ruta_bd = str(Path(self.directorio.name) / "stock.sqlite3")
        conexion = obtener_conexion(self.ruta_bd)
        crear_esquema(conexion)
        conexion.execute("UPDATE estado_sistema SET carga_inicial_completa = 1 WHERE id = 1")
        gestor = GestorInventarioBD(conexion)
        zkl = gestor.crear_marca(Marca(id=None, nombre="ZKL"))
        rod = gestor.crear_categoria(Categoria(id=None, nombre="RODAMIENTO"))
        rid = gestor.crear_repuestos(Repuesto(id=None, codigo="6204 2RS", marca_id=zkl, categoria_id=rod))
        self.iriondo = gestor.crear_proveedor(Proveedor(id=None, nombre="Iriondo"))
        self.edma = gestor.crear_proveedor(Proveedor(id=None, nombre="ED-MA"))
        for fecha in ("2026-08-01", "2026-09-01", "2026-10-01"):
            gestor.registrar_movimiento(MovimientoStock(id=None, repuesto_id=rid, fecha=fecha, tipo="INGRESO",
                                                        cantidad=5, proveedor_id=self.iriondo))
        gestor.registrar_movimiento(MovimientoStock(id=None, repuesto_id=rid, fecha="2026-09-10", tipo="INGRESO",
                                                    cantidad=2, proveedor_id=self.edma))
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

    def test_lista_ordenada_con_participacion(self):
        html = self.html("/proveedores")
        self.assertLess(html.index("Iriondo"), html.index("ED-MA"))
        self.assertIn("width: 75%", html)   # 3 de 4 compras
        self.assertIn("width: 25%", html)

    def test_ficha_con_lo_que_se_le_compra(self):
        html = self.html(f"/proveedores/{self.iriondo}")
        self.assertIn("Qué se le compra", html)
        self.assertIn("6204 2RS", html)
        self.assertIn(">15<", html)  # 3 compras de 5
        self.assertEqual(self.cliente.get("/proveedores/999").status_code, 404)

    def test_crear_proveedor(self):
        respuesta = self.cliente.post("/proveedores/nuevo", data={"nombre": "Rulemanes Paraná", "email": "a@b.com"},
                                      follow_redirects=True)
        self.assertIn("Rulemanes Paraná quedó cargado", respuesta.get_data(as_text=True))
        # y aparece al registrar una compra
        self.assertIn("Rulemanes Paraná", self.html("/movimientos/nuevo"))

    def test_crear_repetido_o_con_email_mal(self):
        r1 = self.cliente.post("/proveedores/nuevo", data={"nombre": "iriondo"})
        r2 = self.cliente.post("/proveedores/nuevo", data={"nombre": "Otro", "email": "sin-arroba"})
        self.assertEqual((r1.status_code, r2.status_code), (400, 400))
        self.assertIn("Ya existe el proveedor Iriondo", r1.get_data(as_text=True))

    def test_corregir_datos(self):
        self.cliente.post(f"/proveedores/{self.edma}/datos", data={"nombre": "ED-MA", "telefono": "0343 155"})
        self.assertIn('value="0343 155"', self.html(f"/proveedores/{self.edma}"))

    def test_desactivar_lo_saca_de_las_compras_pero_no_borra_su_historial(self):
        self.cliente.post(f"/proveedores/{self.edma}/activo", data={"accion": "desactivar"})

        self.assertNotIn("ED-MA", self.html("/movimientos/nuevo"))
        self.assertNotIn("ED-MA", self.html("/proveedores"))
        self.assertIn("ED-MA", self.html("/proveedores?inactivos=1"))
        self.assertIn("6204 2RS", self.html(f"/proveedores/{self.edma}"))


if __name__ == "__main__":
    unittest.main()
