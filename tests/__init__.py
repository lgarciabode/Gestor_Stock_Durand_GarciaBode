"""Configuración común a todas las pruebas.

Las pruebas de la interfaz web inician sesión muchas veces. Flask guarda cada
sesión como un archivo; para no llenar la carpeta flask_session/ del proyecto
(y que todo se vuelva lento), durante las pruebas se usa una carpeta temporal.
"""
import os
import tempfile

os.environ.setdefault("CARPETA_SESIONES", tempfile.mkdtemp(prefix="sesiones_pruebas_"))
