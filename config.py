import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
if not DATABASE_URL:
    raise RuntimeError(
        "Falta configurar DATABASE_URL en .env (la variable existe pero está vacía, "
        "o no se cargó el .env). Completá la ruta del archivo SQLite, por ejemplo: "
        "DATABASE_URL=data/stock_taller.sqlite3"
    )
RUTA_EXCEL_HISTORICO = os.environ.get("RUTA_EXCEL_HISTORICO", "").strip() or str(
    BASE_DIR / "data" / "base_stock_taller.xlsx"
)