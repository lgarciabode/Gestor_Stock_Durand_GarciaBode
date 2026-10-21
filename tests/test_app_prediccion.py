"""Pruebas de la pantalla de predicción de compras.

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
class PruebaPantallaPrediccion(unittest.TestCase):

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

    def test_muestra_la_prediccion_de_todos_los_repuestos(self):
        html = self.cliente.get("/prediccion?todos=1").get_data(as_text=True)
        self.assertIn("Predicción de compras", html)
        self.assertIn("6204 2RS", html)
        self.assertIn("Sin contar", html)                   # todavía no se contó nada
        self.assertIn("05/08/2026", html)                   # último movimiento cargado

    def test_al_contar_poco_stock_aparece_para_comprar(self):
        # Arrange: se cuenta el 6204 y quedan 0 en el estante
        conexion = obtener_conexion(self.ruta_bd)
        gestor = GestorInventarioBD(conexion)
        rep = next(r for r in gestor.obtener_repuestos() if r.codigo == "6204 2RS")
        gestor.registrar_conteo(rep.id, 0, "2026-10-20")
        conexion.close()

        # Act
        html = self.cliente.get("/prediccion?horizonte=90").get_data(as_text=True)

        # Assert
        self.assertIn("Qué comprar", html)
        self.assertIn("6204 2RS", html)
        self.assertIn("1 de 192 repuestos contados", html)

    def test_horizonte_invalido_usa_30_dias(self):
        html = self.cliente.get("/prediccion?horizonte=45").get_data(as_text=True)
        self.assertIn("para los próximos 30 días", html)

    def test_el_menu_tiene_prediccion(self):
        html = self.cliente.get("/").get_data(as_text=True)
        self.assertIn('href="/prediccion"', html)


if __name__ == "__main__":
    unittest.main()

