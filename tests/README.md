# Pruebas unitarias (tests)

Este directorio contiene las pruebas unitarias del proyecto.

Los archivos incluidos definen distintos casos de prueba que permiten verificar el comportamiento de los diferentes módulos implementados en el proyecto.

Las pruebas deben pensarse para ejecutarse automáticamente y facilitar la validación del código ante cambios o nuevas implementaciones.

## Cómo correrlas

Desde la carpeta del proyecto, con el entorno virtual activado:

```
python tests/ver_pruebas.py                  # todas, mostrando qué prueba cada una
python tests/ver_pruebas.py movimientos      # solo un archivo (o parte del nombre)
python tests/ver_pruebas.py stock negativo   # solo las pruebas que contienen esas palabras
python -m unittest discover -s tests -v      # la forma estándar de unittest
```

`ver_pruebas.py` muestra cada prueba como una frase (`test_quitar_de_mas_es_operacion_invalida` →
"quitar de mas es operacion invalida") con ✔ si pasó, ✘ si falló (y el motivo) o "salteada".
