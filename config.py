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

# --- Interfaz web (Flask) ---
# La exige solo la app web (se valida en apps/app_1.py), así main.py y los tests siguen andando sin ella.
SECRET_KEY = os.environ.get("SECRET_KEY", "").strip()

# Base de usuarios de auth-module: archivo SQLite separado del de stock.
RUTA_BD_USUARIOS = os.environ.get("RUTA_BD_USUARIOS", "").strip() or str(
    BASE_DIR / "data" / "usuarios.sqlite3"
)

