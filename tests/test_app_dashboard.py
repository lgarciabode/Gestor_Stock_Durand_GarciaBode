"""Pruebas de la pantalla del dashboard (Paso 14).

Cliente de prueba de Flask sobre una base cargada con el Excel historico real
(se saltea si falta Flask, auth-module o el Excel).

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
RUTA_EXCEL = Path(__file__).resolve().parent.parent / "data" / "base_stock_taller.xlsx"

if HAY_FLASK:
    os.environ.setdefault("DATABASE_URL", "data/stock_taller.sqlite3")  # config.py lo exige al importarse
    from apps import app_1

from modules.base_datos import obtener_conexion
from modules.crud import GestorInventarioBD


@unittest.skipUnless(HAY_FLASK and RUTA_EXCEL.exists(), "Flask / auth-module o el Excel histórico no disponibles")
class PruebaPantallaDashboard(unittest.TestCase):

    def setUp(self):
        self.directorio = tempfile.TemporaryDirectory()
        self.ruta_bd = str(Path(self.directorio.name) / "stock.sqlite3")
        self.parches = [
            patch.object(app_1, "DATABASE_URL", self.ruta_bd),
            patch.object(app_1, "RUTA_EXCEL_HISTORICO", str(RUTA_EXCEL)),
            patch.object(app_1, "SECRET_KEY", "clave-de-prueba"),
            patch.object(app_1, "RUTA_BD_USUARIOS", str(Path(self.directorio.name) / "usuarios.sqlite3")),
        ]
        for p in self.parches:
            p.start()
        app = app_1.create_app()   # carga el historico y calcula los umbrales
        app.config["TESTING"] = True
        self.cliente = app.test_client()
        with self.cliente.session_transaction() as sesion:
            sesion["email"] = "cami@taller.com"

    def tearDown(self):
        for p in self.parches:
            p.stop()
        self.directorio.cleanup()

    def test_secciones_con_los_datos_historicos(self):
        html = self.cliente.get("/dashboard").get_data(as_text=True)
        self.assertIn(">192<", html)                          # repuestos activos
        self.assertIn("0 de 192 repuestos contados", html)
        self.assertIn("Faltan contar 192 repuestos", html)
        self.assertIn("Rodamientos Iriondo S.R.L.", html)     # proveedor principal
        self.assertIn("ene 2026", html)                       # compras por mes
        self.assertIn("6204 2RS", html)                       # de los que mas se mueven
        self.assertIn("Se va a poder ver cuando se cuenten", html)

    def test_al_contar_aparece_en_inmovilizado(self):
        # Arrange: se cuenta el 6204 con mucho mas que su maximo
        conexion = obtener_conexion(self.ruta_bd)
        gestor = GestorInventarioBD(conexion)
        rep = next(r for r in gestor.obtener_repuestos() if r.codigo == "6204 2RS")
        gestor.registrar_conteo(rep.id, 50, "2026-10-20")
        conexion.close()

        # Act
        html = self.cliente.get("/dashboard").get_data(as_text=True)

        # Assert
        self.assertIn("1 de 192 repuestos contados", html)
        self.assertIn("Sobran", html)

    def test_el_menu_ya_no_tiene_pantallas_pendientes(self):
        html = self.cliente.get("/dashboard").get_data(as_text=True)
        self.assertNotIn("Próximamente", html)


if __name__ == "__main__":
    unittest.main()
