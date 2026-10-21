"""Registro de movimientos del día a día (Paso 9 del módulo de alertas).

Cada vez que se compra, se usa o se cuenta un repuesto:
    1. se valida el movimiento (contrato: precondiciones),
    2. se guarda (el trigger de la base actualiza stock_actual),
    3. se revisan las alertas de ESE repuesto (MotorAlertas.revisar).

Así las alertas aparecen solas, sin que nadie apriete "Revisar todo".

La interfaz web (apps/app_1.py) solo arma el pedido y muestra el resultado:
las reglas están acá (arquitectura en capas).
"""
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

from modules.alertas import MotorAlertas
from modules.modelos import Alerta, MovimientoStock, Repuesto


class MovimientoInvalidoError(ValueError):
    """El movimiento no se puede registrar (cantidad, fecha, repuesto o proveedor inválidos)."""


@dataclass
class ResultadoMovimiento:
    """Lo que pasó al registrar: el movimiento (None si un conteo coincidía),
    cómo quedó el repuesto y qué alertas nuevas aparecieron."""
    movimiento_id: Optional[int]
    repuesto: Repuesto
    alertas_nuevas: List[Alerta] = field(default_factory=list)


class ServicioMovimientos:
    """Valida y registra ingresos, egresos y conteos, y revisa las alertas.

    Colaboradores recibidos desde afuera (inversión de dependencias, Unidad 3):
      - gestor: GestorInventarioBD
      - motor: MotorAlertas
      - hoy: función que devuelve la fecha de hoy (se reemplaza en las pruebas)
    """

    def __init__(self, gestor, motor: MotorAlertas, hoy=lambda: date.today().isoformat()):
        self._gestor = gestor
        self._motor = motor
        self._hoy = hoy

    # ------------------------------------------------------------ operaciones

    def registrar_ingreso(self, repuesto_id: int, cantidad: float, fecha: str,
                          proveedor_id: Optional[int] = None) -> ResultadoMovimiento:
        """Una compra que llegó al taller ("Agregar").

        Pre: repuesto activo; cantidad > 0 (entera si se cuenta por unidad);
             fecha válida y no futura; proveedor, si se indica, existente y activo.
        Post: stock_actual aumenta en `cantidad`; se revisan sus alertas.
        """
        rep = self._repuesto_activo(repuesto_id)
        self._validar_cantidad(rep, cantidad)
        self._validar_fecha(fecha)
        if proveedor_id is not None:
            self._validar_proveedor(proveedor_id)
        mov = MovimientoStock(id=None, repuesto_id=repuesto_id, fecha=fecha, tipo="INGRESO",
                              cantidad=cantidad, proveedor_id=proveedor_id)
        return self._guardar_y_revisar(mov)

    def registrar_egreso(self, repuesto_id: int, cantidad: float, fecha: str) -> ResultadoMovimiento:
        """Un repuesto que se usó en el taller ("Quitar").

        Pre: lo mismo que el ingreso y, además, cantidad <= stock_actual
             (no se puede sacar lo que no hay: para corregir, se registra un conteo).
        Post: stock_actual disminuye en `cantidad`; se revisan sus alertas.
        """
        rep = self._repuesto_activo(repuesto_id)
        self._validar_cantidad(rep, cantidad)
        self._validar_fecha(fecha)
        if cantidad > rep.stock_actual:
            raise MovimientoInvalidoError(
                f"No se pueden quitar {cantidad:g}: según el sistema hay {rep.stock_actual:g}. "
                "Si en el estante hay más, registrá primero un conteo."
            )
        mov = MovimientoStock(id=None, repuesto_id=repuesto_id, fecha=fecha, tipo="EGRESO", cantidad=cantidad)
        return self._guardar_y_revisar(mov)

    def registrar_conteo(self, repuesto_id: int, cantidad_contada: float, fecha: str) -> ResultadoMovimiento:
        """Corregir el stock con lo que hay en el estante ("Hay en el estante").

        Pre: repuesto activo; fecha válida y no futura; cantidad válida
             (la valida Repuesto.ajuste_por_conteo).
        Post: stock_actual == cantidad_contada; se revisan sus alertas.
        """
        self._repuesto_activo(repuesto_id)
        self._validar_fecha(fecha)
        try:
            movimiento_id = self._gestor.registrar_conteo(repuesto_id, cantidad_contada, fecha)
        except ValueError as error:  # ConteoInvalidoError
            raise MovimientoInvalidoError(str(error)) from error
        return self._resultado(movimiento_id, repuesto_id)

    # ------------------------------------------------------------ validaciones

    def _repuesto_activo(self, repuesto_id: int) -> Repuesto:
        rep = self._gestor.obtener_repuesto_id(repuesto_id)
        if rep is None:
            raise MovimientoInvalidoError("Elegí un repuesto de la lista.")
        if not rep.activo:
            raise MovimientoInvalidoError(f"El repuesto {rep.codigo} está inactivo: activalo antes de moverlo.")
        return rep

    @staticmethod
    def _validar_cantidad(rep: Repuesto, cantidad: float) -> None:
        if cantidad <= 0:
            raise MovimientoInvalidoError("La cantidad tiene que ser mayor que 0.")
        if rep.unidad_medida == "unidad" and cantidad != int(cantidad):
            raise MovimientoInvalidoError(f"{rep.codigo} se cuenta por unidad: la cantidad no puede tener decimales.")

    def _validar_fecha(self, fecha: str) -> None:
        try:
            dia = date.fromisoformat(fecha)
        except (TypeError, ValueError):
            raise MovimientoInvalidoError("La fecha no es válida.") from None
        if dia > date.fromisoformat(self._hoy()):
            raise MovimientoInvalidoError("La fecha no puede ser futura.")

    def _validar_proveedor(self, proveedor_id: int) -> None:
        activos = {p.id for p in self._gestor.obtener_proveedores(solo_activos=True)}
        if proveedor_id not in activos:
            raise MovimientoInvalidoError("Elegí un proveedor de la lista.")

    # ------------------------------------------------------------ guardar

    def _guardar_y_revisar(self, mov: MovimientoStock) -> ResultadoMovimiento:
        movimiento_id = self._gestor.registrar_movimiento(mov)
        return self._resultado(movimiento_id, mov.repuesto_id)

    def _resultado(self, movimiento_id: Optional[int], repuesto_id: int) -> ResultadoMovimiento:
        # Se vuelve a leer: el stock lo actualizó el trigger de la base
        rep = self._gestor.obtener_repuesto_id(repuesto_id)
        return ResultadoMovimiento(movimiento_id, rep, self._motor.revisar(rep))
