"""Pruebas del esquema de la base para el modulo de alertas (Paso 1).

Verifican las reglas que la propia base de datos hace cumplir, sin pasar
todavia por las clases del modulo:
- `repuestos.parametros_manuales` arranca en 0 y solo acepta 0 o 1.
- `alertas.tipo` solo acepta REORDEN, CRITICO o SOBRESTOCK.
- `alertas.mensaje` no puede estar vacio.
- Invariante: nunca dos alertas ABIERTAS del mismo tipo para el mismo
  repuesto (indice unico parcial `idx_alertas_abierta_unica`).

Mismo estilo que el resto de la suite: unittest puro, una base SQLite
temporal por test (setUp/tearDown) y patron AAA (Arrange, Act, Assert).
"""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.base_datos import crear_esquema, obtener_conexion
from modules.crud import GestorInventarioBD
from modules.modelos import Categoria, Marca, Repuesto


class PruebaEsquemaAlertas(unittest.TestCase):
    def setUp(self):
        # Arrange comun: base temporal con el esquema real y un repuesto.
        self.directorio_temporal = tempfile.TemporaryDirectory()
        ruta_bd = str(Path(self.directorio_temporal.name) / "test.sqlite3")
        self.conexion = obtener_conexion(ruta_bd)
        crear_esquema(self.conexion)
        gestor = GestorInventarioBD(self.conexion)
        marca_id = gestor.crear_marca(Marca(id=None, nombre="ZKL"))
        categoria_id = gestor.crear_categoria(Categoria(id=None, nombre="RODAMIENTO"))
        self.repuesto_id = gestor.crear_repuestos(
            Repuesto(id=None, codigo="6204 2RS", marca_id=marca_id, categoria_id=categoria_id)
        )

    def tearDown(self):
        self.conexion.close()
        self.directorio_temporal.cleanup()

    def _insertar_alerta(self, tipo="REORDEN", mensaje="Hay que pedir", atendida=0):
        self.conexion.execute(
            "INSERT INTO alertas (repuesto_id, fecha, tipo, mensaje, atendida) VALUES (?, ?, ?, ?, ?)",
            (self.repuesto_id, "2026-10-15", tipo, mensaje, atendida),
        )

    # --- repuestos.parametros_manuales ------------------------------------

    def test_repuesto_nuevo_tiene_parametros_manuales_en_cero(self):
        # Act
        valor = self.conexion.execute(
            "SELECT parametros_manuales FROM repuestos WHERE id = ?", (self.repuesto_id,)
        ).fetchone()[0]

        # Assert
        self.assertEqual(valor, 0)

    def test_parametros_manuales_solo_acepta_cero_o_uno(self):
        # Act / Assert
        with self.assertRaises(sqlite3.IntegrityError):
            self.conexion.execute(
                "UPDATE repuestos SET parametros_manuales = 2 WHERE id = ?", (self.repuesto_id,)
            )

    # --- alertas: tipo y mensaje --------------------------------------------

    def test_alerta_con_tipo_invalido_es_rechazada(self):
        # Act / Assert
        with self.assertRaises(sqlite3.IntegrityError):
            self._insertar_alerta(tipo="AGOTADO")

    def test_alerta_con_mensaje_vacio_es_rechazada(self):
        # Act / Assert
        with self.assertRaises(sqlite3.IntegrityError):
            self._insertar_alerta(mensaje="   ")

    # --- invariante: una sola alerta abierta por repuesto y tipo ------------

    def test_no_permite_dos_alertas_abiertas_del_mismo_tipo(self):
        # Arrange
        self._insertar_alerta(tipo="REORDEN")

        # Act / Assert
        with self.assertRaises(sqlite3.IntegrityError):
            self._insertar_alerta(tipo="REORDEN")

    def test_permite_alertas_abiertas_de_distinto_tipo(self):
        # Act (escalada: primero REORDEN, despues CRITICO)
        self._insertar_alerta(tipo="REORDEN")
        self._insertar_alerta(tipo="CRITICO")

        # Assert
        abiertas = self.conexion.execute(
            "SELECT COUNT(*) FROM alertas WHERE atendida = 0"
        ).fetchone()[0]
        self.assertEqual(abiertas, 2)

    def test_permite_nueva_alerta_si_la_anterior_fue_atendida(self):
        # Arrange: una alerta REORDEN ya atendida queda en el historial
        self._insertar_alerta(tipo="REORDEN", atendida=1)

        # Act: el stock vuelve a bajar y aparece otra REORDEN abierta
        self._insertar_alerta(tipo="REORDEN", atendida=0)

        # Assert: el historial guarda las dos
        total = self.conexion.execute(
            "SELECT COUNT(*) FROM alertas WHERE tipo = 'REORDEN'"
        ).fetchone()[0]
        self.assertEqual(total, 2)


if __name__ == "__main__":
    unittest.main()
