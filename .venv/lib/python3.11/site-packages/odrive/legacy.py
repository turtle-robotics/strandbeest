"""
Functions to support legacy firmware
"""

from odrive.rich_text import RichText, Color, Style
import odrive.utils

async def format_errors(odrv, clear=False):
    """
    Returns a summary of the error status of the device as RichText.
    """
    lines = []

    STYLE_GOOD = (Color.GREEN, Color.DEFAULT, Style.BOLD)
    STYLE_WARN = (Color.YELLOW, Color.DEFAULT, Style.BOLD)
    STYLE_BAD = (Color.RED, Color.DEFAULT, Style.BOLD)

    def decode_flags(val, enum_type):
        errorcodes = {v.value: f"{enum_type.__name__}.{v.name}" for v in enum_type}
        if val == 0:
            return [RichText("no error", *STYLE_GOOD)]
        else:
            return [RichText("Error(s):", *STYLE_BAD)] + [
                RichText(errorcodes.get((1 << bit), 'UNKNOWN ERROR: 0x{:08X}'.format(1 << bit)), *STYLE_BAD)
                for bit in range(64) if val & (1 << bit) != 0]

    def decode_enum(val, enum_type):
        errorcodes = {v.value: f"{enum_type.__name__}.{v.name}" for v in enum_type}
        return [RichText(errorcodes.get(val, 'Unknown value: ' + str(val)), *(STYLE_GOOD if (val == 0) else STYLE_BAD))]

    def decode_drv_fault(axis_metadata, val):
        if val == 0:
            return [RichText("none", *STYLE_GOOD)]
        elif axis_metadata is None:
            return [RichText("metadata not loaded", *STYLE_WARN)]
        else:
            return [RichText(odrive.utils.decode_drv_faults(axis_metadata, val), *STYLE_BAD)]

    async def dump_item(indent, name, path, decoder):
        prefix = indent + name.strip('0123456789') + ": "

        val = await odrv.try_read(path, fallback=None)
        if val is None:
            return [prefix + RichText("not found", *STYLE_WARN)]

        lines = decoder(val)
        lines = [indent + name + ": " + lines[0]] + [
            indent + "  " + line
            for line in lines[1:]
        ]
        return lines

    lines += await dump_item("", "system", 'error', lambda x: decode_flags(x, odrive.enums.LegacyODriveError))

    for name in odrv.axes:
        lines.append(name)
        lines += await dump_item("  ", 'axis', f'{name}.error', lambda x: decode_flags(x, odrive.enums.AxisError))
        lines += await dump_item("  ", 'motor', f'{name}.motor.error', lambda x: decode_flags(x, odrive.enums.MotorError))
        lines += await dump_item("  ", 'DRV fault', f'{name}.last_drv_fault', lambda x: decode_drv_fault(odrv.axis_metadata[name], x))
        lines += await dump_item("  ", 'sensorless_estimator', f'{name}.sensorless_estimator.error', lambda x: decode_flags(x, odrive.enums.SensorlessEstimatorError))
        lines += await dump_item("  ", 'encoder', f'{name}.encoder.error', lambda x: decode_flags(x, odrive.enums.EncoderError))
        lines += await dump_item("  ", 'controller', f'{name}.controller.error', lambda x: decode_flags(x, odrive.enums.ControllerError))

    if clear:
        await odrv.call_function('clear_errors')

    return RichText('\n').join(lines)
