"""Tests de los parsers por proveedor y de la carga inicial completa."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.base_datos import (
    crear_esquema,
    inicializar_si_hace_falta,
    obtener_conexion,
)
from modules.importador import cargar_historico
from modules.parsers import ParserEdMa, ParserIriondo, ParserProdumat, obtener_parser

RUTA_EXCEL = Path(__file__).resolve().parent.parent / "data" / "base_stock_taller.xlsx"


def test_parser_iriondo_separa_marca_y_tipo():
    fila = {
        "Proveedor": "Rodamientos Iriondo S.R.L.",
        "Código": "32212 JR",
        "Descripción": "KOY - RODAMIENTO",
        "Cantidad": 2.0,
    }
    linea = ParserIriondo().parsear(fila)
    assert linea.marca == "KOY"
    assert linea.descripcion == "RODAMIENTO"
    assert linea.tipo_linea == "PRODUCTO"


def test_parser_iriondo_detecta_cargo_administrativo():
    fila = {
        "Proveedor": "Rodamientos Iriondo S.R.L.",
        "Código": "0007-SEGURO",
        "Descripción": "I.A - SEG. MERCADERIA",
        "Cantidad": 1.0,
    }
    linea = ParserIriondo().parsear(fila)
    assert linea.tipo_linea == "CARGO_ADMINISTRATIVO"


def test_parser_edma_separa_codigo_interno_y_fabricante():
    fila = {
        "Proveedor": "Metalúrgica ED-MA S.R.L.",
        "Código": 'H-8025/1 / HF1800300000010',
        "Descripción": 'HORQ K518 F DOBLE BUL 1 3/8" Z21',
        "Cantidad": 2.0,
    }
    linea = ParserEdMa().parsear(fila)
    assert linea.codigo_proveedor == "HF1800300000010"
    assert linea.codigo_interno_taller == "H-8025/1"
    assert linea.marca == "ED-MA"


def test_parser_produmat_marca_fija():
    fila = {
        "Proveedor": "Produmat S.A.",
        "Código": "2110300430",
        "Descripción": "TUBO TR D 44.7 X 3.9 -518 INT- X 6000",
        "Cantidad": 1.0,
    }
    linea = ParserProdumat().parsear(fila)
    assert linea.marca == "Produmat"
    assert linea.tipo_linea == "PRODUCTO"


def test_obtener_parser_desconocido_lanza_error():
    with pytest.raises(ValueError):
        obtener_parser("Proveedor Inexistente S.A.")


@pytest.mark.skipif(not RUTA_EXCEL.exists(), reason="No está el Excel histórico en data/")
def test_carga_historico_sobre_archivo_real(tmp_path):
    conexion = obtener_conexion(str(tmp_path / "test.sqlite3"))
    crear_esquema(conexion)
    cargar_historico(conexion, str(RUTA_EXCEL))
    conexion.commit()

    # Los cargos administrativos (39 líneas) se descartan en el parseo y
    # nunca llegan a la base: solo deben quedar movimientos de producto.
    total_movimientos = conexion.execute("SELECT COUNT(*) FROM movimientos_stock").fetchone()[0]
    total_repuestos = conexion.execute("SELECT COUNT(*) FROM repuestos").fetchone()[0]
    total_proveedores = conexion.execute("SELECT COUNT(*) FROM proveedores").fetchone()[0]

    assert total_movimientos == 213
    assert total_repuestos == 189
    assert total_proveedores == 3
    conexion.close()


@pytest.mark.skipif(not RUTA_EXCEL.exists(), reason="No está el Excel histórico en data/")
def test_trigger_mantiene_sincronizado_stock_actual(tmp_path):
    """El trigger trg_movimientos_actualiza_stock debe dejar stock_actual
    igual a la suma de los movimientos de cada repuesto, sin que el
    importador (ni ningún otro código) lo actualice a mano."""
    conexion = obtener_conexion(str(tmp_path / "test.sqlite3"))
    crear_esquema(conexion)
    cargar_historico(conexion, str(RUTA_EXCEL))
    conexion.commit()

    desincronizados = conexion.execute(
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

    assert desincronizados == []
    conexion.close()


def test_inicializar_si_hace_falta_reintenta_tras_una_carga_fallida(tmp_path, monkeypatch):
    """Si cargar_historico explota a mitad de camino, la base no debe
    quedar a medio poblar con la bandera en 'completo': el próximo arranque
    tiene que reintentar la carga desde cero."""
    ruta_bd = tmp_path / "test.sqlite3"

    llamadas = {"n": 0}
    original = cargar_historico

    def cargar_historico_falla_la_primera_vez(conexion, ruta_excel):
        llamadas["n"] += 1
        if llamadas["n"] == 1:
            # Simula una carga que alcanza a insertar algo y después explota.
            conexion.execute(
                "INSERT INTO proveedores (nombre) VALUES ('Proveedor a medio cargar')"
            )
            raise RuntimeError("fallo simulado a mitad de la carga")
        original(conexion, ruta_excel)

    monkeypatch.setattr(
        "modules.base_datos.cargar_historico", cargar_historico_falla_la_primera_vez
    )

    with pytest.raises(RuntimeError):
        inicializar_si_hace_falta(str(ruta_bd), str(RUTA_EXCEL))

    # Primer intento: el rollback tiene que haber deshecho el INSERT parcial.
    conexion = obtener_conexion(str(ruta_bd))
    assert conexion.execute("SELECT COUNT(*) FROM proveedores").fetchone()[0] == 0
    conexion.close()

    # Segundo intento: al no haber quedado marcada como completa, reintenta.
    inicializar_si_hace_falta(str(ruta_bd), str(RUTA_EXCEL))
    conexion = obtener_conexion(str(ruta_bd))
    assert conexion.execute("SELECT COUNT(*) FROM proveedores").fetchone()[0] == 3
    conexion.close()
    assert llamadas["n"] == 2
