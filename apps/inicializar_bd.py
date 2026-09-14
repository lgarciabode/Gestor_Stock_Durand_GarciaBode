"""Punto de entrada: inicializa la base de datos si todavía no existe.

Uso:
    python apps/inicializar_bd.py

Esto mismo conviene llamarlo al arrancar la aplicación Flask (por ejemplo,
al principio de `main.py` o del factory de la app), para que el sistema se
auto-inicialice en cualquier clon nuevo del repositorio: la base SQLite no
se trackea en git (ver `data/README.md`), así que sin este paso el sistema
no tendría ni esquema ni datos la primera vez que se levanta.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from modules.base_datos import inicializar_si_hace_falta
from modules.config import DATABASE_URL, RUTA_EXCEL_HISTORICO

if __name__ == "__main__":
    inicializar_si_hace_falta(DATABASE_URL, RUTA_EXCEL_HISTORICO)
    print(f"Base de datos lista en: {DATABASE_URL}")
