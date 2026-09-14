import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")

try:
    DATABASE_URL = os.environ["DATABASE_URL"]
except KeyError as exc:
    raise RuntimeError(
        "Falta configurar DATABASE_URL a .env y completá "
        "la ruta del archivo SQLite, por ejemplo: DATABASE_URL=data/stock_taller.sqlite3"
    ) from exc
RUTA_EXCEL_HISTORICO = os.environ.get(
    "RUTA_EXCEL_HISTORICO", str(BASE_DIR / "data" / "base_stock_taller.xlsx")
)