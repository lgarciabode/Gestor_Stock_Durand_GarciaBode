"""Pruebas del historial de movimientos y sus exportadores (Paso 10).

- FiltroMovimientos: invariante (fechas validas, desde <= hasta, tipo conocido).
- ConsultaMovimientos: base SQLite temporal.
- Exportadores (Strategy): Excel se relee con openpyxl; PDF se verifica por
  su firma y, si esta instalado fpdf2. Si no, esas pruebas se saltean.

unittest puro, patron AAA (Arrange, Act, Assert).
"""
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from openpyxl import load_workbook

from modules.base_datos import crear_esquema, obtener_conexion
from modules.crud import GestorInventarioBD
from modules.modelos import Categoria, Marca, MovimientoStock, Proveedor, Repuesto
from modules.reportes import (
    EXPORTADORES,
    ConsultaMovimientos,
    ExportadorExcel,
    ExportadorPDF,
    ExportadorReporte,
    FiltroInvalidoError,
    FiltroMovimientos,
    contar_por_tipo,
)

HAY_FPDF = importlib.util.find_spec("fpdf") is not None


class PruebaFiltro(unittest.TestCase):

    def test_filtro_valido_y_su_descripcion(self):
        filtro = FiltroMovimientos("2026-10-01", "2026-10-20", "EGRESO")
        self.assertEqual(filtro.descripcion(), "Del 01/10/2026 al 20/10/2026 · Quitar")

    def test_un_solo_dia_es_valido(self):
        FiltroMovimientos("2026-10-20", "2026-10-20")  # limite: no lanza

    def test_desde_posterior_a_hasta(self):
        with self.assertRaises(FiltroInvalidoError):
            FiltroMovimientos("2026-10-21", "2026-10-20")

    def test_fecha_invalida_o_tipo_desconocido(self):
        with self.assertRaises(FiltroInvalidoError):
            FiltroMovimientos("20/10/2026", "2026-10-20")
        with self.assertRaises(FiltroInvalidoError):
            FiltroMovimientos("2026-10-01", "2026-10-20", "VENTA")


class BaseReportes(unittest.TestCase):
    """Rodamiento ZKL y cadena en cm; compras, usos y un conteo en octubre, y una compra vieja."""

    def setUp(self):
        self.directorio = tempfile.TemporaryDirectory()
        self.conexion = obtener_conexion(str(Path(self.directorio.name) / "test.sqlite3"))
        crear_esquema(self.conexion)
        gestor = GestorInventarioBD(self.conexion)
        zkl = gestor.crear_marca(Marca(id=None, nombre="ZKL"))
        rod = gestor.crear_categoria(Categoria(id=None, nombre="RODAMIENTO"))
        cad = gestor.crear_categoria(Categoria(id=None, nombre="CADENA"))
        prov = gestor.crear_proveedor(Proveedor(id=None, nombre="Iriondo"))
        self.rod = gestor.crear_repuestos(Repuesto(id=None, codigo="6204 2RS", marca_id=zkl, categoria_id=rod))
        self.cad = gestor.crear_repuestos(Repuesto(id=None, codigo="CAD-40", marca_id=zkl, categoria_id=cad, unidad_medida="cm"))
        for rid, fecha, tipo, cantidad, proveedor in (
            (self.rod, "2026-02-13", "INGRESO", 10, prov),   # fuera del rango de octubre
            (self.rod, "2026-10-02", "INGRESO", 5, prov),
            (self.rod, "2026-10-05", "EGRESO", 3, None),
            (self.cad, "2026-10-06", "INGRESO", 300.5, None),
            (self.rod, "2026-10-10", "AJUSTE", -2, None),
        ):
            gestor.registrar_movimiento(MovimientoStock(id=None, repuesto_id=rid, fecha=fecha, tipo=tipo,
                                                        cantidad=cantidad, proveedor_id=proveedor))
        self.consulta = ConsultaMovimientos(self.conexion)
        self.octubre = FiltroMovimientos("2026-10-01", "2026-10-20")

    def tearDown(self):
        self.conexion.close()
        self.directorio.cleanup()


class PruebaConsulta(BaseReportes):

    def test_filtra_por_fechas_y_ordena_del_mas_nuevo_al_mas_viejo(self):
        filas = self.consulta.buscar(self.octubre)
        self.assertEqual([f.fecha for f in filas], ["2026-10-10", "2026-10-06", "2026-10-05", "2026-10-02"])

    def test_las_fechas_limite_se_incluyen(self):
        filas = self.consulta.buscar(FiltroMovimientos("2026-10-02", "2026-10-05"))
        self.assertEqual(len(filas), 2)

    def test_filtra_por_tipo_y_por_repuesto(self):
        self.assertEqual(len(self.consulta.buscar(FiltroMovimientos("2026-01-01", "2026-10-20", "INGRESO"))), 3)
        self.assertEqual(len(self.consulta.buscar(FiltroMovimientos("2026-10-01", "2026-10-20", repuesto_id=self.cad))), 1)

    def test_trae_nombres_y_textos_para_mostrar(self):
        compra = self.consulta.buscar(FiltroMovimientos("2026-10-02", "2026-10-02"))[0]
        self.assertEqual(compra.como_tupla(),
                         ("02/10/2026", "Agregar", "6204 2RS", "ZKL", "RODAMIENTO", "+5", "unidad", "Iriondo"))

    def test_signo_de_la_cantidad(self):
        textos = {f.tipo: f.cantidad_texto for f in self.consulta.buscar(self.octubre) if f.codigo == "6204 2RS"}
        self.assertEqual(textos, {"INGRESO": "+5", "EGRESO": "-3", "AJUSTE": "-2"})

    def test_contar_por_tipo(self):
        self.assertEqual(contar_por_tipo(self.consulta.buscar(self.octubre)), {"INGRESO": 2, "EGRESO": 1, "AJUSTE": 1, "ANULADOS": 0})


class PruebaExportadores(BaseReportes):

    def test_es_una_estrategia_abstracta(self):
        with self.assertRaises(TypeError):
            ExportadorReporte()
        self.assertTrue(all(isinstance(e, ExportadorReporte) for e in EXPORTADORES.values()))

    def test_excel_con_encabezado_y_cantidades_numericas(self):
        # Act
        contenido = ExportadorExcel().exportar(self.consulta.buscar(self.octubre), self.octubre)

        # Assert
        hoja = load_workbook(io.BytesIO(contenido)).active
        self.assertEqual(hoja["A2"].value, "Del 01/10/2026 al 20/10/2026")
        self.assertEqual(hoja["A4"].value, "Fecha")
        self.assertEqual(hoja.max_row, 4 + 4)
        cantidades = [hoja.cell(row=r, column=6).value for r in range(5, 9)]
        self.assertEqual(cantidades, [-2, 300.5, -3, 5])  # numeros: se pueden sumar en Excel

    def test_excel_sin_movimientos_tiene_solo_el_encabezado(self):
        filtro = FiltroMovimientos("2025-01-01", "2025-01-31")
        hoja = load_workbook(io.BytesIO(ExportadorExcel().exportar([], filtro))).active
        self.assertEqual(hoja.max_row, 4)

    @unittest.skipUnless(HAY_FPDF, "fpdf2 no instalado")
    def test_pdf_valido_aun_con_muchas_filas_y_acentos(self):
        # Arrange: 150 filas (varias paginas)
        filas = self.consulta.buscar(self.octubre) * 40

        # Act
        contenido = ExportadorPDF().exportar(filas, self.octubre)

        # Assert
        self.assertTrue(contenido.startswith(b"%PDF"))
        self.assertGreater(contenido.count(b"/Type /Page\n") + contenido.count(b"/Type /Page "), 1)

    @unittest.skipUnless(HAY_FPDF, "fpdf2 no instalado")
    def test_pdf_sin_movimientos(self):
        self.assertTrue(ExportadorPDF().exportar([], self.octubre).startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
