"""Corre las pruebas y muestra, en castellano, QUÉ se está probando.

Uso (desde la carpeta del proyecto):
    python tests/ver_pruebas.py                 -> todas las pruebas
    python tests/ver_pruebas.py movimientos     -> solo los archivos que contienen "movimientos"
    python tests/ver_pruebas.py stock negativo  -> solo las pruebas cuyo nombre contiene esas palabras

Para cada archivo muestra su descripción (la primera línea del docstring) y,
debajo, cada prueba con su nombre convertido en frase:
    test_quitar_de_mas_es_operacion_invalida  ->  "quitar de mas es operacion invalida"
    ✔ pasó    ✘ falló (con el motivo)    - salteada (con el motivo)

No cambia ninguna prueba: usa unittest igual que
`python -m unittest discover -s tests`, solo que muestra el resultado más claro.
Los print() que hacen los módulos durante las pruebas se ocultan (buffer) para
que no se mezclen con el listado.
"""
import sys
import time
import unittest
import warnings
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

try:  # en la consola de Windows, para que se vean ✔, ✘ y los acentos
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

VERDE, ROJO, GRIS, NEGRITA, FIN = "\033[32m", "\033[31m", "\033[90m", "\033[1m", "\033[0m"


def frase(nombre_test: str) -> str:
    """test_quitar_resta_y_confirma -> 'quitar resta y confirma'"""
    return nombre_test.removeprefix("test_").replace("_", " ")


def primera_linea(texto) -> str:
    return (texto or "").strip().splitlines()[0] if (texto or "").strip() else ""


def todas(suite):
    """Aplana la suite: devuelve cada prueba suelta."""
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from todas(item)
        else:
            yield item


class ResultadoLegible(unittest.TextTestResult):
    """Imprime cada prueba como una frase, agrupada por archivo y por clase."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._archivo = self._clase = None

    def startTest(self, test):
        super().startTest(test)
        modulo = sys.modules.get(type(test).__module__)
        if type(test).__module__ != self._archivo:
            self._archivo = type(test).__module__
            nombre = self._archivo.split(".")[-1] + ".py"
            descripcion = primera_linea(getattr(modulo, "__doc__", ""))
            self.stream.write(f"\n{NEGRITA}{nombre}{FIN}  {GRIS}{descripcion}{FIN}\n")
        if type(test).__name__ != self._clase:
            self._clase = type(test).__name__
            descripcion = primera_linea(type(test).__doc__)
            self.stream.write(f"  {self._clase}  {GRIS}{descripcion}{FIN}\n")

    def _linea(self, marca, color, test, detalle=""):
        texto = frase(test._testMethodName)
        doc = primera_linea(test._testMethodDoc)
        if doc:
            texto += f"  {GRIS}({doc}){FIN}"
        if detalle:
            texto += f"\n        {color}{detalle}{FIN}"
        self.stream.write(f"    {color}{marca}{FIN} {texto}\n")
        self.stream.flush()

    def addSuccess(self, test):
        unittest.TestResult.addSuccess(self, test)
        self._linea("✔", VERDE, test)

    def addFailure(self, test, err):
        unittest.TestResult.addFailure(self, test, err)
        self._linea("✘", ROJO, test, "FALLÓ: " + primera_linea(str(err[1])))

    def addError(self, test, err):
        unittest.TestResult.addError(self, test, err)
        self._linea("✘", ROJO, test, f"ERROR: {err[0].__name__}: {primera_linea(str(err[1]))}")

    def addSkip(self, test, reason):
        unittest.TestResult.addSkip(self, test, reason)
        self._linea("-", GRIS, test, "salteada: " + reason)

    def printErrors(self):  # el detalle completo de los errores, al final
        if self.errors or self.failures:
            self.stream.write(f"\n{ROJO}{NEGRITA}Detalle de lo que falló{FIN}\n")
            super().printErrors()


def main(filtros):
    suite = unittest.defaultTestLoader.discover(str(RAIZ / "tests"), top_level_dir=str(RAIZ))
    elegidas = [t for t in todas(suite)
                if all(f.lower() in t.id().lower() for f in filtros)]
    resultado = ResultadoLegible(unittest.runner._WritelnDecorator(sys.stdout), True, 0)
    resultado.buffer = True  # oculta los print() de los módulos mientras corre cada prueba
    inicio = time.perf_counter()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # avisos de librerías que no hacen al resultado
        unittest.TestSuite(elegidas).run(resultado)
    segundos = time.perf_counter() - inicio
    resultado.printErrors()

    malas = len(resultado.failures) + len(resultado.errors)
    salteadas = len(resultado.skipped)
    buenas = resultado.testsRun - malas - salteadas
    color = VERDE if malas == 0 else ROJO
    print(f"\n{color}{NEGRITA}{buenas} pasaron, {malas} fallaron, {salteadas} salteadas "
          f"({resultado.testsRun} pruebas en {segundos:.1f} s){FIN}")
    return 0 if malas == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
