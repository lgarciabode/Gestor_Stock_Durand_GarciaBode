"""Pruebas del catalogo de repuestos (Paso 11).

ServicioCatalogo sobre una base SQLite temporal. Un Mock de la fabrica de
parametros verifica como se usa ese colaborador al volver al calculo automatico.

unittest puro, patron AAA (Arrange, Act, Assert).
"""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.alertas import MotorAlertas, ParametrosStock, ServicioParametrosStock, reglas_por_defecto
from modules.base_datos import crear_esquema, obtener_conexion
from modules.catalogo import CatalogoInvalidoError, FiltroCatalogo, ServicioCatalogo
from modules.crud import GestorInventarioBD, RepositorioAlertas, RepuestoNoEncontradoError
from modules.modelos import Categoria, EstadoStock, Marca, MovimientoStock, Repuesto

HOY = "2026-10-20"


class BaseCatalogo(unittest.TestCase):
    """6204 ZKL (10 en stock, 4 compras), 6205 ZKL (sin stock) y un reten SAV."""

    def setUp(self):
        self.directorio = tempfile.TemporaryDirectory()
        self.conexion = obtener_conexion(str(Path(self.directorio.name) / "test.sqlite3"))
        crear_esquema(self.conexion)
        self.gestor = GestorInventarioBD(self.conexion)
        zkl = self.gestor.crear_marca(Marca(id=None, nombre="ZKL"))
        sav = self.gestor.crear_marca(Marca(id=None, nombre="SAV"))
        rod = self.gestor.crear_categoria(Categoria(id=None, nombre="RODAMIENTO"))
        ret = self.gestor.crear_categoria(Categoria(id=None, nombre="RETEN"))
        self.r6204 = self.gestor.crear_repuestos(Repuesto(id=None, codigo="6204 2RS", marca_id=zkl, categoria_id=rod,
                                                          especificaciones="sellado"))
        self.r6205 = self.gestor.crear_repuestos(Repuesto(id=None, codigo="6205 2RS", marca_id=zkl, categoria_id=rod))
        self.reten = self.gestor.crear_repuestos(Repuesto(id=None, codigo="5279 LX", marca_id=sav, categoria_id=ret))
        for fecha, cantidad in (("2026-02-13", 1), ("2026-04-23", 2), ("2026-06-30", 3), ("2026-08-05", 4)):
            self.gestor.registrar_movimiento(MovimientoStock(id=None, repuesto_id=self.r6204, fecha=fecha,
                                                             tipo="INGRESO", cantidad=cantidad))
        self.repositorio = RepositorioAlertas(self.conexion)
        self.motor = MotorAlertas(reglas_por_defecto(), self.repositorio, hoy=lambda: HOY)
        self.servicio = ServicioCatalogo(self.gestor, self.motor)

    def tearDown(self):
        self.conexion.close()
        self.directorio.cleanup()

    def rep(self, repuesto_id):
        return self.gestor.obtener_repuesto_id(repuesto_id)


class PruebaListar(BaseCatalogo):

    def test_ordenado_por_categoria_marca_y_codigo(self):
        codigos = [f.repuesto.codigo for f in self.servicio.listar()]
        self.assertEqual(codigos, ["5279 LX", "6204 2RS", "6205 2RS"])  # RETEN antes que RODAMIENTO

    def test_busca_en_codigo_marca_categoria_y_especificaciones(self):
        self.assertEqual(len(self.servicio.listar(FiltroCatalogo(texto="zkl"))), 2)
        self.assertEqual(len(self.servicio.listar(FiltroCatalogo(texto="reten"))), 1)
        self.assertEqual([f.repuesto.codigo for f in self.servicio.listar(FiltroCatalogo(texto="sellado"))], ["6204 2RS"])

    def test_filtra_por_estado(self):
        agotados = self.servicio.listar(FiltroCatalogo(estado=EstadoStock.AGOTADO))
        self.assertEqual({f.repuesto.codigo for f in agotados}, {"6205 2RS", "5279 LX"})

    def test_los_inactivos_se_ven_solo_si_se_piden(self):
        self.servicio.inactivar(self.r6205)
        self.assertEqual(len(self.servicio.listar()), 2)
        self.assertEqual(len(self.servicio.listar(FiltroCatalogo(incluir_inactivos=True))), 3)

    def test_ficha_inexistente(self):
        with self.assertRaises(RepuestoNoEncontradoError):
            self.servicio.ficha(999)


class PruebaCrearYCorregir(BaseCatalogo):

    def test_crear_con_marca_y_categoria_existentes(self):
        # Act: la marca se reconoce aunque se escriba en minusculas
        nuevo = self.servicio.crear("6206 2RS", "zkl", "rodamiento", "  sellado ", "unidad")

        # Assert: queda "sin datos todavia" (sin umbrales) y sin stock
        rep = self.rep(nuevo)
        self.assertEqual((rep.marca_id, rep.categoria_id), (self.rep(self.r6204).marca_id, self.rep(self.r6204).categoria_id))
        self.assertEqual(rep.especificaciones, "sellado")
        self.assertFalse(rep.tiene_umbrales())

    def test_crear_con_marca_y_categoria_nuevas(self):
        marcas_antes = len(self.gestor.obtener_marcas())
        nuevo = self.servicio.crear("C-80", "Renold", "cadena", unidad_medida="cm")
        self.assertEqual(len(self.gestor.obtener_marcas()), marcas_antes + 1)
        self.assertEqual(self.servicio.ficha(nuevo).categoria, "CADENA")
        self.assertEqual(self.rep(nuevo).unidad_medida, "cm")

    def test_no_se_repite_marca_y_codigo(self):
        with self.assertRaises(CatalogoInvalidoError):
            self.servicio.crear("6204 2RS", "ZKL", "RODAMIENTO")

    def test_el_mismo_codigo_de_otra_marca_es_otro_repuesto(self):
        self.servicio.crear("6204 2RS", "SKF", "RODAMIENTO")  # no lanza

    def test_datos_obligatorios_y_unidad_valida(self):
        with self.assertRaises(CatalogoInvalidoError):
            self.servicio.crear("  ", "ZKL", "RODAMIENTO")
        with self.assertRaises(CatalogoInvalidoError):
            self.servicio.crear("X-1", "ZKL", "RODAMIENTO", unidad_medida="kg")

    def test_corregir_categoria_y_especificaciones(self):
        self.servicio.corregir_datos(self.reten, "reten", "doble labio")
        ficha = self.servicio.ficha(self.reten)
        self.assertEqual((ficha.categoria, ficha.repuesto.especificaciones), ("RETEN", "doble labio"))


class PruebaActivarInactivar(BaseCatalogo):

    def test_inactivar_sin_stock(self):
        self.servicio.inactivar(self.r6205)
        self.assertFalse(self.rep(self.r6205).activo)

    def test_no_se_inactiva_con_stock(self):
        with self.assertRaises(CatalogoInvalidoError):
            self.servicio.inactivar(self.r6204)
        self.assertTrue(self.rep(self.r6204).activo)

    def test_reactivar_revisa_sus_alertas(self):
        # Arrange: 6205 con umbrales y sin stock, inactivo
        self.gestor.actualizar_parametros_stock(self.r6205, stock_minimo=1, stock_maximo=5, punto_reorden=2)
        self.servicio.inactivar(self.r6205)

        # Act
        nuevas = self.servicio.activar(self.r6205)

        # Assert: vuelve y avisa que esta agotado
        self.assertTrue(self.rep(self.r6205).activo)
        self.assertEqual([a.tipo for a in nuevas], ["CRITICO"])


class PruebaUmbrales(BaseCatalogo):

    def test_fijar_umbrales_a_mano_y_revisar(self):
        # Act: con 10 en stock, maximo 8 -> sobra
        nuevas = self.servicio.fijar_umbrales(self.r6204, minimo=2, reorden=4, maximo=8)

        # Assert
        rep = self.rep(self.r6204)
        self.assertEqual((rep.stock_minimo, rep.punto_reorden, rep.stock_maximo), (2, 4, 8))
        self.assertTrue(rep.parametros_manuales)
        self.assertEqual([a.tipo for a in nuevas], ["SOBRESTOCK"])

    def test_umbrales_incoherentes_no_se_guardan(self):
        with self.assertRaises(CatalogoInvalidoError):
            self.servicio.fijar_umbrales(self.r6204, minimo=5, reorden=4, maximo=8)
        self.assertFalse(self.rep(self.r6204).tiene_umbrales())

    def test_volver_a_automatico_recalcula_con_el_historial(self):
        # Arrange
        self.servicio.fijar_umbrales(self.r6204, minimo=1, reorden=1, maximo=100)

        # Act
        parametros = self.servicio.volver_a_automatico(self.r6204)

        # Assert: ya no es manual y los umbrales salen de las compras
        rep = self.rep(self.r6204)
        self.assertFalse(rep.parametros_manuales)
        self.assertEqual((rep.stock_minimo, rep.punto_reorden, rep.stock_maximo),
                         (parametros.stock_minimo, parametros.punto_reorden, parametros.stock_maximo))
        self.assertNotEqual(rep.stock_maximo, 100)

    def test_volver_a_automatico_usa_la_fabrica_despues_de_sacar_la_marca(self):
        # Mock: se verifica que se recalcula con el repuesto ya marcado como automatico
        fabrica = Mock()
        fabrica.return_value.recalcular.return_value = ParametrosStock(1, 2, 3)
        servicio = ServicioCatalogo(self.gestor, self.motor, fabrica_parametros=fabrica)
        servicio.fijar_umbrales(self.r6204, minimo=1, reorden=1, maximo=100)

        servicio.volver_a_automatico(self.r6204)

        fabrica.assert_called_once_with(self.gestor)
        repuesto_recalculado = fabrica.return_value.recalcular.call_args.args[0]
        self.assertFalse(repuesto_recalculado.parametros_manuales)

    def test_volver_a_automatico_sin_compras_deja_los_que_tenia(self):
        self.servicio.fijar_umbrales(self.reten, minimo=1, reorden=2, maximo=5)

        self.assertIsNone(self.servicio.volver_a_automatico(self.reten))

        rep = self.rep(self.reten)
        self.assertEqual((rep.punto_reorden, rep.parametros_manuales), (2, False))


if __name__ == "__main__":
    unittest.main()
