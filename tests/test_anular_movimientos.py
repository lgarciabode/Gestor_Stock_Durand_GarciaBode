"""Pruebas de la anulacion de movimientos y de la migracion de la base (Paso 12).

- ServicioMovimientos.anular: contrato (pre/post) sobre una base temporal.
- El calculo de umbrales y "repuestos contados" ignoran lo anulado.
- _migrar: una base creada con el esquema viejo (sin anula_id) se actualiza sin perder datos.

unittest puro, patron AAA (Arrange, Act, Assert).
"""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.alertas import MotorAlertas, reglas_por_defecto
from modules.base_datos import crear_esquema, obtener_conexion
from modules.crud import GestorInventarioBD, RepositorioAlertas
from modules.modelos import Categoria, Marca, Repuesto
from modules.movimientos import MovimientoInvalidoError, ServicioMovimientos
from modules.reportes import ConsultaMovimientos, FiltroMovimientos, contar_por_tipo

HOY = "2026-10-20"


class BaseAnular(unittest.TestCase):
    """6204 con umbrales 2 / 4 / 18: compra de 10 el 01/10 y uso de 3 el 05/10 (quedan 7)."""

    def setUp(self):
        self.directorio = tempfile.TemporaryDirectory()
        self.conexion = obtener_conexion(str(Path(self.directorio.name) / "test.sqlite3"))
        crear_esquema(self.conexion)
        self.gestor = GestorInventarioBD(self.conexion)
        zkl = self.gestor.crear_marca(Marca(id=None, nombre="ZKL"))
        rod = self.gestor.crear_categoria(Categoria(id=None, nombre="RODAMIENTO"))
        self.rid = self.gestor.crear_repuestos(Repuesto(id=None, codigo="6204 2RS", marca_id=zkl, categoria_id=rod))
        self.gestor.actualizar_parametros_stock(self.rid, stock_minimo=2, stock_maximo=18, punto_reorden=4)
        self.repositorio = RepositorioAlertas(self.conexion)
        motor = MotorAlertas(reglas_por_defecto(), self.repositorio, hoy=lambda: HOY)
        self.servicio = ServicioMovimientos(self.gestor, motor, hoy=lambda: HOY)
        self.compra = self.servicio.registrar_ingreso(self.rid, 10, "2026-10-01").movimiento_id
        self.uso = self.servicio.registrar_egreso(self.rid, 3, "2026-10-05").movimiento_id

    def tearDown(self):
        self.conexion.close()
        self.directorio.cleanup()

    def stock(self):
        return self.gestor.obtener_repuesto_id(self.rid).stock_actual


class PruebaAnular(BaseAnular):

    def test_anular_un_uso_devuelve_las_unidades(self):
        # Act
        resultado = self.servicio.anular(self.uso)

        # Assert: AJUSTE +3 con fecha de hoy que referencia al uso
        self.assertEqual(self.stock(), 10)
        anulacion = self.gestor.obtener_movimiento(resultado.movimiento_id)
        self.assertEqual((anulacion.tipo, anulacion.cantidad, anulacion.fecha, anulacion.anula_id),
                         ("AJUSTE", 3, HOY, self.uso))

    def test_anular_una_compra_resta_lo_que_se_habia_sumado(self):
        # Arrange: llega otra compra de 2 (hay 9) y se carga por error una de 5 (hay 14)
        self.servicio.registrar_ingreso(self.rid, 2, "2026-10-06")
        compra_mal = self.servicio.registrar_ingreso(self.rid, 5, "2026-10-07").movimiento_id

        # Act: esa compra de 5 no existio
        resultado = self.servicio.anular(compra_mal)

        # Assert
        self.assertEqual(self.stock(), 9)
        self.assertEqual(resultado.alertas_nuevas, [])

    def test_no_se_borra_nada_quedan_los_dos_en_el_historial(self):
        self.servicio.anular(self.uso)

        filas = ConsultaMovimientos(self.conexion).buscar(FiltroMovimientos("2026-10-01", HOY))

        textos = [f.tipo_texto for f in filas]
        self.assertEqual(textos, ["Anulación", "Quitar · anulado", "Agregar"])
        self.assertEqual(contar_por_tipo(filas), {"INGRESO": 1, "EGRESO": 0, "AJUSTE": 0, "ANULADOS": 1})

    def test_el_calculo_de_umbrales_no_ve_lo_anulado(self):
        # Arrange: una compra extra cargada por error
        extra = self.servicio.registrar_ingreso(self.rid, 50, "2026-10-08").movimiento_id

        # Act
        self.servicio.anular(extra)

        # Assert: para el calculo solo existen la compra de 10 y el uso de 3
        vigentes = [(m.tipo, m.cantidad) for m in self.gestor.obtener_movimientos(self.rid)]
        self.assertEqual(vigentes, [("INGRESO", 10), ("EGRESO", 3)])

    def test_una_anulacion_no_marca_al_repuesto_como_contado(self):
        self.servicio.anular(self.uso)
        self.assertEqual(self.gestor.obtener_repuestos_contados(), [])


class PruebaAnularInvalido(BaseAnular):

    def test_no_se_anula_dos_veces(self):
        self.servicio.anular(self.uso)
        with self.assertRaises(MovimientoInvalidoError):
            self.servicio.anular(self.uso)
        self.assertEqual(self.stock(), 10)

    def test_la_base_tambien_impide_anular_dos_veces(self):
        # Invariante en la base (indice unico): aunque alguien se saltee el servicio
        self.servicio.anular(self.uso)
        with self.assertRaises(sqlite3.IntegrityError):
            self.conexion.execute(
                "INSERT INTO movimientos_stock (repuesto_id, fecha, tipo, cantidad, anula_id) VALUES (?, ?, 'AJUSTE', 3, ?)",
                (self.rid, HOY, self.uso))

    def test_una_anulacion_no_se_anula(self):
        anulacion = self.servicio.anular(self.uso).movimiento_id
        with self.assertRaises(MovimientoInvalidoError):
            self.servicio.anular(anulacion)

    def test_no_se_anula_si_el_stock_quedaria_negativo(self):
        # La compra de 10 no se puede anular: ya se usaron 3 (quedaria en -3)
        with self.assertRaises(MovimientoInvalidoError):
            self.servicio.anular(self.compra)
        self.assertEqual(self.stock(), 7)

    def test_movimiento_inexistente(self):
        with self.assertRaises(MovimientoInvalidoError):
            self.servicio.anular(999)


class PruebaMigracion(unittest.TestCase):

    def test_una_base_vieja_recibe_la_columna_sin_perder_datos(self):
        with tempfile.TemporaryDirectory() as directorio:
            ruta = str(Path(directorio) / "vieja.sqlite3")
            # Arrange: tabla de movimientos como era antes del Paso 12 (sin anula_id)
            vieja = sqlite3.connect(ruta)
            vieja.executescript("""
                CREATE TABLE movimientos_stock (
                    id INTEGER PRIMARY KEY, repuesto_id INTEGER NOT NULL, proveedor_id INTEGER,
                    fecha DATE NOT NULL, tipo TEXT NOT NULL, cantidad REAL NOT NULL,
                    codigo_proveedor_raw TEXT, origen TEXT NOT NULL DEFAULT 'manual');
                INSERT INTO movimientos_stock (repuesto_id, fecha, tipo, cantidad) VALUES (1, '2026-01-05', 'INGRESO', 10);
            """)
            vieja.commit()
            vieja.close()

            # Act: se abre con el codigo nuevo (dos veces: tiene que poder repetirse)
            conexion = obtener_conexion(ruta)
            crear_esquema(conexion)
            crear_esquema(conexion)

            # Assert
            columnas = {f[1] for f in conexion.execute("PRAGMA table_info(movimientos_stock)")}
            self.assertIn("anula_id", columnas)
            self.assertEqual(conexion.execute("SELECT COUNT(*) FROM movimientos_stock").fetchone()[0], 1)
            conexion.close()


if __name__ == "__main__":
    unittest.main()
