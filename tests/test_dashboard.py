"""Pruebas del dashboard (Paso 14).

ConsultaDashboard sobre una base SQLite temporal, con fecha fija.

unittest puro, patron AAA (Arrange, Act, Assert).
"""
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.base_datos import crear_esquema, obtener_conexion
from modules.crud import GestorInventarioBD
from modules.dashboard import ConsultaDashboard
from modules.modelos import Categoria, EstadoStock, Marca, MovimientoStock, Proveedor, Repuesto

HOY = date(2026, 10, 21)


class BaseDashboard(unittest.TestCase):
    """Periodo 01/01 -> 01/07 (181 dias).
    RAPIDO: 60 comprados (rota mucho). LENTO: 2 comprados. CADENA: en cm (no entra en la rotacion).
    QUIETO: 5 comprados el 01/01 y contado ese dia (sin movimiento hace mucho)."""

    def setUp(self):
        self.directorio = tempfile.TemporaryDirectory()
        self.conexion = obtener_conexion(str(Path(self.directorio.name) / "test.sqlite3"))
        crear_esquema(self.conexion)
        self.gestor = GestorInventarioBD(self.conexion)
        zkl = self.gestor.crear_marca(Marca(id=None, nombre="ZKL"))
        rod = self.gestor.crear_categoria(Categoria(id=None, nombre="RODAMIENTO"))
        prov = self.gestor.crear_proveedor(Proveedor(id=None, nombre="Iriondo"))
        self.ids = {}
        for codigo, unidad in (("RAPIDO", "unidad"), ("LENTO", "unidad"), ("CADENA", "cm"), ("QUIETO", "unidad")):
            self.ids[codigo] = self.gestor.crear_repuestos(Repuesto(id=None, codigo=codigo, marca_id=zkl,
                                                                    categoria_id=rod, unidad_medida=unidad))
        for codigo, fecha, cantidad in (("QUIETO", "2026-01-01", 5), ("RAPIDO", "2026-01-15", 30),
                                        ("RAPIDO", "2026-03-10", 30), ("LENTO", "2026-03-10", 2),
                                        ("CADENA", "2026-07-01", 600)):
            self.gestor.registrar_movimiento(MovimientoStock(id=None, repuesto_id=self.ids[codigo], fecha=fecha,
                                                             tipo="INGRESO", cantidad=cantidad, proveedor_id=prov))
        self.dashboard = ConsultaDashboard(self.conexion, self.gestor, hoy=lambda: HOY)

    def tearDown(self):
        self.conexion.close()
        self.directorio.cleanup()


class PruebaEstadoYConteo(BaseDashboard):

    def test_estados_de_los_activos(self):
        self.assertEqual(self.dashboard.estados()[EstadoStock.SIN_DATOS], 4)

    def test_avance_del_conteo(self):
        self.gestor.registrar_conteo(self.ids["LENTO"], 2, "2026-10-20")
        avance = self.dashboard.avance_conteo()
        self.assertEqual((avance.contados, avance.total, avance.porcentaje), (1, 4, 25))


class PruebaRotacion(BaseDashboard):

    def test_mas_y_menos_rotacion_sin_los_de_centimetros(self):
        # Act
        mas, menos = self.dashboard.rotacion()

        # Assert: 60 en 181 dias -> 9,9 por mes; los de cm no se comparan
        self.assertEqual([f.repuesto.codigo for f in mas], ["RAPIDO", "QUIETO", "LENTO"])
        self.assertEqual(mas[0].por_mes, 9.9)
        self.assertEqual(menos[0].repuesto.codigo, "LENTO")
        self.assertNotIn("CADENA", [f.repuesto.codigo for f in mas])

    def test_cantidad_limita_las_listas(self):
        mas, menos = self.dashboard.rotacion(cantidad=1)
        self.assertEqual((len(mas), len(menos)), (1, 1))

    def test_sin_movimientos_no_hay_rotacion(self):
        with tempfile.TemporaryDirectory() as d:
            conexion = obtener_conexion(str(Path(d) / "vacia.sqlite3"))
            crear_esquema(conexion)
            self.assertEqual(ConsultaDashboard(conexion, GestorInventarioBD(conexion)).rotacion(), ([], []))
            conexion.close()


class PruebaInmovilizado(BaseDashboard):

    def test_sin_contar_no_se_analiza(self):
        # Todos tienen stock "de carga historica": hasta contarlos no se sabe si sobra
        self.assertEqual(self.dashboard.inmovilizado(), [])

    def test_quieto_hace_mucho(self):
        # Arrange: se conto el 01/01 (coincidio)
        self.gestor.registrar_conteo(self.ids["QUIETO"], 5, "2026-01-01")

        # Act
        filas = self.dashboard.inmovilizado()

        # Assert
        self.assertEqual([f.repuesto.codigo for f in filas], ["QUIETO"])
        self.assertEqual(filas[0].motivos, ["Sin movimiento hace 293 días"])

    def test_sobra_stock_y_va_primero(self):
        # Arrange: RAPIDO contado hoy con maximo 20 (tiene 60) y QUIETO quieto
        self.gestor.registrar_conteo(self.ids["QUIETO"], 5, "2026-01-01")
        self.gestor.registrar_conteo(self.ids["RAPIDO"], 60, "2026-10-21")
        self.gestor.actualizar_parametros_stock(self.ids["RAPIDO"], stock_minimo=5, stock_maximo=20, punto_reorden=10)

        # Act
        filas = self.dashboard.inmovilizado()

        # Assert
        self.assertEqual([f.repuesto.codigo for f in filas], ["RAPIDO", "QUIETO"])
        self.assertEqual(filas[0].motivos, ["Sobran 40"])

    def test_contado_en_cero_no_es_inmovilizado(self):
        self.gestor.registrar_conteo(self.ids["QUIETO"], 0, "2026-01-02")
        self.assertEqual(self.dashboard.inmovilizado(), [])


class PruebaCompras(BaseDashboard):

    def test_compras_por_mes(self):
        meses = self.dashboard.compras_por_mes()
        self.assertEqual([(m.mes, m.compras, m.lineas, m.unidades) for m in meses],
                         [("2026-01", 2, 2, 35), ("2026-03", 1, 2, 32), ("2026-07", 1, 1, 0)])
        self.assertEqual(meses[0].nombre, "ene 2026")


if __name__ == "__main__":
    unittest.main()
