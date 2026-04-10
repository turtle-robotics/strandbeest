

import enum
from typing import Optional, cast
from odrive.async_tree import AsyncObject
from odrive.enums import ODriveError, ProcedureResult
from odrive.runtime_device import RuntimeDevice

__all__ = [
    'DeviceException',
    'DeviceStateException',
]

class DeviceException(Exception):
    def __init__(self, device: RuntimeDevice, msg: str) -> None:
        self.device = device
        super().__init__(msg)

class DeviceStateException(DeviceException):
    def __init__(self, msg: str, axis: AsyncObject, procedure_result: Optional[ProcedureResult], disarm_reason: Optional[ODriveError], drv_fault: Optional[enum.IntFlag]):
        super().__init__(axis._dev, msg)
        self.procedure_result = procedure_result
        self.disarm_reason = disarm_reason
        self.drv_fault = drv_fault

    async def load_with_procedure_result(axis: AsyncObject, procedure_result: int):
        disarm_reason = None
        result = ProcedureResult(procedure_result)
        if result == ProcedureResult.DISARMED:
            disarm_reason = ODriveError(await axis.disarm_reason.read())
            msg = f"Device failed with {repr(ODriveError(disarm_reason))}."
        elif result != ProcedureResult.SUCCESS:
            msg = f"Device returned {repr(ProcedureResult(result))}."
        else:
            msg = "Device entered IDLE for an unknown reason."

        if (not disarm_reason is None) and (disarm_reason & ODriveError.DRV_FAULT):
            drv_fault_int: int = await axis.last_drv_fault.read()
            axis_metadata = axis._dev.axis_metadata[axis._path]
            if axis_metadata is None:
                drv_fault = drv_fault_int
                msg += f" last_drv_fault: 0x{drv_fault:X}."
            else:
                from odrive_private.drv_enums import drv_error_enums
                drv_error_type = drv_error_enums[axis_metadata['drv_ref']]
                drv_fault = cast(enum.IntFlag, drv_error_type(drv_fault_int))
                msg += f" last_drv_fault: {repr(drv_fault)}."
        else:
            drv_fault = None

        return DeviceStateException(msg, axis, result, disarm_reason, drv_fault)

    def from_msg(axis: AsyncObject, msg: str):
        return DeviceStateException(msg, axis, None, None, None)
