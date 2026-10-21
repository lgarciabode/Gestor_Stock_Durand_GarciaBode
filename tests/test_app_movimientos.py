"""Pruebas de la pantalla "Registrar movimiento" (Paso 9).

Cliente de prueba de Flask sobre una base SQLite temporal. Si Flask o
auth-module no están instalados, se saltean.

unittest puro, patron AAA (Arrange, Act, Assert).
"""
import importlib.util
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

HAY_FLASK = all(importlib.util.find_spec(m) for m in ("flask", "auth_module"))

if HAY_FLASK:
    os.environ.setdefault("DATABASE_URL", "data/stock_taller.sqlite3")  # config.py lo exige al importarse
    from apps import app_1

from modules.base_datos import crear_esquema, obtener_conexion
from modules.crud import GestorInventarioBD, RepositorioAlertas
from modules.modelos import Categoria, Marca, MovimientoStock, Proveedor, Repuesto

HOY = date.today().isoformat()
OPCION_6204 = "6204 2RS · ZKL · RODAMIENTO"


@unittest.skipUnless(HAY_FLASK, "Flask / auth-module no instalados")
class PruebaPantallaMovimientos(unittest.TestCase):

    def setUp(self):
        self.directorio = tempfile.TemporaryDirectory()
        self.ruta_bd = str(Path(self.directorio.name) / "stock.sqlite3")
        conexion = obtener_conexion(self.ruta_bd)
        crear_esquema(conexion)
        conexion.execute("UPDATE estado_sistema SET carga_inicial_completa = 1 WHERE id = 1")
        gestor = GestorInventarioBD(conexion)
        zkl = gestor.crear_marca(Marca(id=None, nombre="ZKL"))
        rod = gestor.crear_categoria(Categoria(id=None, nombre="RODAMIENTO"))
        self.rod_id = gestor.crear_repuestos(Repuesto(id=None, codigo="6204 2RS", marca_id=zkl, categoria_id=rod))
        gestor.registrar_movimiento(MovimientoStock(id=None, repuesto_id=self.rod_id, fecha=HOY, tipo="INGRESO", cantidad=10))
        gestor.actualizar_parametros_stock(self.rod_id, stock_minimo=2, stock_maximo=18, punto_reorden=4)
        self.prov_id = gestor.crear_proveedor(Proveedor(id=None, nombre="Iriondo"))
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

    def enviar(self, **campos):
        datos = {"tipo": "egreso", "repuesto": OPCION_6204, "cantidad": "1", "fecha": HOY, "proveedor_id": ""}
        datos.update(campos)
        return self.cliente.post("/movimientos/nuevo", data=datos, follow_redirects=True)

    def repuesto(self):
        conexion = obtener_conexion(self.ruta_bd)
        try:
            return GestorInventarioBD(conexion).obtener_repuesto_id(self.rod_id)
        finally:
            conexion.close()

    def movimientos(self):
        conexion = obtener_conexion(self.ruta_bd)
        try:
            return GestorInventarioBD(conexion).obtener_movimientos(self.rod_id)
        finally:
            conexion.close()

    # ------------------------------------------------------------ formulario

    def test_el_formulario_ofrece_los_repuestos_para_reconocer(self):
        html = self.cliente.get("/movimientos/nuevo").get_data(as_text=True)
        self.assertIn(f'<option value="{OPCION_6204}">', html)
        self.assertIn("Quitar", html)
        self.assertIn("Stock disponible", html)
        self.assertNotIn("(se usó)", html)
        self.assertIn(f'max="{HOY}"', html)  # no deja elegir fechas futuras
        self.assertIn("Iriondo", html)

    # ------------------------------------------------------------ registrar

    def test_quitar_resta_y_confirma(self):
        # Act
        respuesta = self.enviar(tipo="egreso", cantidad="4")

        # Assert: vuelve al formulario limpio (POST -> redirect -> GET) con el mensaje
        html = respuesta.get_data(as_text=True)
        self.assertEqual(respuesta.request.path, "/movimientos/nuevo")
        self.assertIn("Se quitaron 4 unidades de 6204 2RS. Ahora hay 6 unidades.", html)
        self.assertEqual(self.repuesto().stock_actual, 6)

    def test_mensaje_en_singular(self):
        html = self.enviar(tipo="egreso", cantidad="1").get_data(as_text=True)
        self.assertIn("Se quitó 1 unidad de 6204 2RS. Ahora hay 9 unidades.", html)

    def test_quitar_hasta_el_reorden_avisa_y_crea_la_alerta(self):
        html = self.enviar(tipo="egreso", cantidad="7").get_data(as_text=True)

        self.assertIn("Nuevo aviso — Hay que pedir: 6204 2RS", html)
        self.assertIn('<span class="contador" title="Alertas sin atender">1</span>', html)

    def test_agregar_con_proveedor(self):
        self.enviar(tipo="ingreso", cantidad="5", proveedor_id=str(self.prov_id))

        ultimo = self.movimientos()[-1]
        self.assertEqual((ultimo.tipo, ultimo.cantidad, ultimo.proveedor_id), ("INGRESO", 5, self.prov_id))

    def test_conteo_desde_la_pantalla(self):
        html = self.enviar(tipo="conteo", cantidad="3").get_data(as_text=True)

        self.assertIn("Stock corregido: 6204 2RS quedó en 3 unidades.", html)
        self.assertEqual(self.repuesto().stock_actual, 3)

    def test_se_puede_escribir_solo_el_codigo(self):
        self.enviar(repuesto="6204 2RS", cantidad="1")
        self.assertEqual(self.repuesto().stock_actual, 9)

    def test_acepta_coma_decimal_en_cantidad_entera(self):
        self.enviar(cantidad="2,0")
        self.assertEqual(self.repuesto().stock_actual, 8)

    # ------------------------------------------------------------ errores

    def test_error_muestra_el_motivo_conserva_lo_cargado_y_no_guarda(self):
        # Act: se quieren quitar mas de los que hay
        respuesta = self.enviar(tipo="egreso", cantidad="50")

        # Assert
        html = respuesta.get_data(as_text=True)
        self.assertEqual(respuesta.status_code, 400)
        self.assertIn("No se pueden quitar 50: según el sistema hay 10.", html)
        self.assertIn(f'value="{OPCION_6204}"', html)  # no hay que volver a escribir todo
        self.assertEqual(len(self.movimientos()), 1)

    def test_repuesto_que_no_esta_en_la_lista(self):
        html = self.enviar(repuesto="no existe").get_data(as_text=True)
        self.assertIn("Elegí un repuesto de la lista.", html)

    def test_cantidad_que_no_es_un_numero(self):
        html = self.enviar(cantidad="dos").get_data(as_text=True)
        self.assertIn("Escribí la cantidad con números.", html)

    def test_fecha_futura(self):
        manana = (date.today() + timedelta(days=1)).isoformat()
        html = self.enviar(fecha=manana).get_data(as_text=True)
        self.assertIn("La fecha no puede ser futura.", html)


if __name__ == "__main__":
    unittest.main()
