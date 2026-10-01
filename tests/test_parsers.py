"""Tests de los parsers por proveedor y de la carga inicial completa.

Convertido a unittest puro (biblioteca estandar): TestCase, metodos
assert*, unittest.mock.patch en lugar de monkeypatch de pytest, y
unittest.skipUnless en lugar de pytest.mark.skipif. Cada test sigue el
patron AAA (Arrange, Act, Assert) que recomienda el apunte de la catedra.
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.base_datos import (
    crear_esquema,
    inicializar_si_hace_falta,
    obtener_conexion,
)
from modules.carga_historico_datos import cargar_historico
from modules.parsers import ParserEdMa, ParserIriondo, ParserProdumat, obtener_parser

RUTA_EXCEL = Path(__file__).resolve().parent.parent / "data" / "base_stock_taller.xlsx"


class PruebaParsersPorProveedor(unittest.TestCase):
    """Pruebas puras de cada ParserProveedor.parsear(): no tocan la base
    de datos, son las mas rapidas y aisladas de la suite."""

    def test_parser_iriondo_separa_marca_y_tipo(self):
        # Arrange
        fila = {
            "Proveedor": "Rodamientos Iriondo S.R.L.",
            "Código": "32212 JR",
            "Descripción": "KOY - RODAMIENTO",
            "Cantidad": 2.0,
        }

        # Act
        linea = ParserIriondo().parsear(fila)

        # Assert
        self.assertEqual(linea.marca, "KOY")
        self.assertEqual(linea.descripcion, "RODAMIENTO")
        self.assertEqual(linea.tipo_linea, "PRODUCTO")

    def test_parser_iriondo_detecta_cargo_administrativo(self):
        # Arrange
        fila = {
            "Proveedor": "Rodamientos Iriondo S.R.L.",
            "Código": "0007-SEGURO",
            "Descripción": "I.A - SEG. MERCADERIA",
            "Cantidad": 1.0,
        }

        # Act
        linea = ParserIriondo().parsear(fila)

        # Assert
        self.assertEqual(linea.tipo_linea, "CARGO_ADMINISTRATIVO")

    def test_parser_edma_separa_codigo_interno_y_fabricante(self):
        # Arrange
        fila = {
            "Proveedor": "Metalúrgica ED-MA S.R.L.",
            "Código": 'H-8025/1 / HF1800300000010',
            "Descripción": 'HORQ K518 F DOBLE BUL 1 3/8" Z21',
            "Cantidad": 2.0,
        }

        # Act
        linea = ParserEdMa().parsear(fila)

        # Assert
        self.assertEqual(linea.codigo_proveedor, "HF1800300000010")
        self.assertEqual(linea.codigo_interno_taller, "H-8025/1")
        self.assertEqual(linea.marca, "ED-MA")

    def test_parser_produmat_marca_fija(self):
        # Arrange
        fila = {
            "Proveedor": "Produmat S.A.",
            "Código": "2110300430",
            "Descripción": "TUBO TR D 44.7 X 3.9 -518 INT- X 6000",
            "Cantidad": 1.0,
        }

        # Act
        linea = ParserProdumat().parsear(fila)

        # Assert
        self.assertEqual(linea.marca, "Produmat")
        self.assertEqual(linea.tipo_linea, "PRODUCTO")

    def test_obtener_parser_desconocido_lanza_error(self):
        # Act / Assert
        with self.assertRaises(ValueError):
            obtener_parser("Proveedor Inexistente S.A.")


@unittest.skipUnless(RUTA_EXCEL.exists(), "No está el Excel histórico en data/")
class PruebaCargaHistoricaSobreArchivoReal(unittest.TestCase):
    """Pruebas de integracion: corren el importador completo contra el
    Excel real del taller. Se saltean automaticamente si ese archivo no
    esta presente (p. ej. en un checkout sin data/)."""

    def setUp(self):
        # Arrange (comun a los dos tests de esta clase)
        self.directorio_temporal = tempfile.TemporaryDirectory()
        ruta_bd = str(Path(self.directorio_temporal.name) / "test.sqlite3")
        self.conexion = obtener_conexion(ruta_bd)
        crear_esquema(self.conexion)
        cargar_historico(self.conexion, str(RUTA_EXCEL))
        self.conexion.commit()

    def tearDown(self):
        self.conexion.close()
        self.directorio_temporal.cleanup()

    def test_carga_historico_sobre_archivo_real(self):
        # Act
        total_movimientos = self.conexion.execute(
            "SELECT COUNT(*) FROM movimientos_stock"
        ).fetchone()[0]
        total_repuestos = self.conexion.execute("SELECT COUNT(*) FROM repuestos").fetchone()[0]
        total_proveedores = self.conexion.execute("SELECT COUNT(*) FROM proveedores").fetchone()[0]

        # Assert: los cargos administrativos (39 líneas) se descartan en el
        # parseo y nunca llegan a la base: solo quedan movimientos de producto.
        self.assertEqual(total_movimientos, 213)
        self.assertEqual(total_repuestos, 189)
        self.assertEqual(total_proveedores, 3)

    def test_trigger_mantiene_sincronizado_stock_actual(self):
        """El trigger trg_movimientos_actualiza_stock debe dejar stock_actual
        igual a la suma de los movimientos de cada repuesto, sin que el
        importador (ni ningún otro código) lo actualice a mano."""
        # Act
        desincronizados = self.conexion.execute(
            """
            SELECT r.id
            FROM repuestos r
            WHERE r.stock_actual != (
                SELECT COALESCE(SUM(
                    CASE m.tipo
                        WHEN 'INGRESO' THEN m.cantidad
                        WHEN 'EGRESO' THEN -m.cantidad
                        ELSE m.cantidad
                    END
                ), 0)
                FROM movimientos_stock m
                WHERE m.repuesto_id = r.id
            )
            """
        ).fetchall()

        # Assert
        self.assertEqual(desincronizados, [])


@unittest.skipUnless(RUTA_EXCEL.exists(), "No está el Excel histórico en data/")
class PruebaReintentoCargaInicial(unittest.TestCase):
    def setUp(self):
        self.directorio_temporal = tempfile.TemporaryDirectory()
        self.ruta_bd = str(Path(self.directorio_temporal.name) / "test.sqlite3")

    def tearDown(self):
        self.directorio_temporal.cleanup()

    def test_inicializar_si_hace_falta_reintenta_tras_una_carga_fallida(self):
        """Si cargar_historico explota a mitad de camino, la base no debe
        quedar a medio poblar con la bandera en 'completo': el próximo
        arranque tiene que reintentar la carga desde cero."""
        # Arrange
        llamadas = {"n": 0}
        original = cargar_historico

        def cargar_historico_falla_la_primera_vez(conexion, ruta_excel):
            llamadas["n"] += 1
            if llamadas["n"] == 1:
                # Simula una carga que alcanza a insertar algo y despues explota.
                conexion.execute(
                    "INSERT INTO proveedores (nombre) VALUES ('Proveedor a medio cargar')"
                )
                raise RuntimeError("fallo simulado a mitad de la carga")
            original(conexion, ruta_excel)

        with patch(
            "modules.base_datos.cargar_historico",
            new=cargar_historico_falla_la_primera_vez,
        ):
            # Act (primer intento) + Assert (tiene que explotar)
            with self.assertRaises(RuntimeError):
                inicializar_si_hace_falta(self.ruta_bd, str(RUTA_EXCEL))

            # Assert: el rollback tiene que haber deshecho el INSERT parcial.
            conexion = obtener_conexion(self.ruta_bd)
            self.assertEqual(
                conexion.execute("SELECT COUNT(*) FROM proveedores").fetchone()[0], 0
            )
            conexion.close()

            # Act (segundo intento): al no haber quedado marcada como
            # completa, reintenta.
            inicializar_si_hace_falta(self.ruta_bd, str(RUTA_EXCEL))

        # Assert
        conexion = obtener_conexion(self.ruta_bd)
        self.assertEqual(conexion.execute("SELECT COUNT(*) FROM proveedores").fetchone()[0], 3)
        conexion.close()
        self.assertEqual(llamadas["n"], 2)


if __name__ == "__main__":
    unittest.main()
