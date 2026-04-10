"""
Convenience functions for working with ODrives.

All members of :mod:`odrive.utils` are exposed directly in the
:code:`odrivetool` console but can also be used in user scripts.
"""

import asyncio
from contextlib import asynccontextmanager
import logging
import struct
import time
import traceback
import types
from typing import Callable, List, Literal, Optional, Tuple, Union

from odrive._internal_utils import run_sync_on_loop, transform_odrive_objects
from odrive._matplotlib_asyncio import patch_pyplot
from odrive.async_tree import AsyncObject, AsyncProperty
from odrive.codecs import decode_all
import odrive.database
from odrive.device_manager import get_device_manager
import odrive.enums
from odrive.enums import AxisState, ProcedureResult
from odrive.exceptions import DeviceStateException
import odrive.legacy
from odrive.legacy_config import backup_config, restore_config
from odrive.rich_text import RichText, Color, Style
from odrive.runtime_device import RuntimeDevice
from odrive.sync_tree import SyncObject

# used by Sphinx autodoc
__all__ = [
    'dump_errors', 'format_errors',
    'request_state',
    'run_state',
    'start_liveplotter', 'stop_liveplotter',
    'backup_config', 'restore_config',
    'to_sync', 'to_async',
]

# Undocumented but available in odrivetool
_undocumented = [
    'dump_interrupts', 'dump_threads', 'dump_dma', 'dump_timing',
    'ram_osci_config', 'ram_osci_trigger', 'ram_osci_download', 'ram_osci_run',
    #'step_and_plot',
    'calculate_thermistor_coeffs', 'set_motor_thermistor_coeffs', 'print_drv_regs']

logger = logging.getLogger("odrive")

def __dir__(): # used by IPython tab complete
    return __all__ + _undocumented


async def get_string(odrv: RuntimeDevice, addr: int):
    string = ""
    while True:
        c = await odrv.call_function('get_raw_8', addr) # TODO: check if function available
        if c == 0:
            break
        string += chr(c)
        addr += 1
    return string

async def get_issues(odrv: RuntimeDevice):
    issues_raw = [await odrv.call_function('issues.get', i) for i in range(await odrv.read('issues.length'))]
    issues = [f"{await get_string(odrv, addr)}:{line} ({arg0}, {arg1})" for addr, line, arg0, arg1 in issues_raw]
    return issues

async def format_errors(odrv: RuntimeDevice, clear: bool = False):
    """
    Returns a summary of the error status of the device formatted as
    :class:`RichText`.
    """
    is_legacy_firmware = odrv.fw_version < (0, 6, 0)
    if is_legacy_firmware:
        return await odrive.legacy.format_errors(odrv, clear)

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
            return [RichText(decode_drv_faults(axis_metadata['drv'], val), *STYLE_BAD)]

    async def dump_items(indent: str, path_prefix: str, items: List[Tuple[str, Callable]]):
        values = await odrv.try_read_multiple(
            [path_prefix + path for path, _ in items],
            fallback = [None] * len(items)
        )

        lines = []

        for i, (name, decoder) in enumerate(items):
            val = values[i]
            if val is None:
                continue # omit items that don't exist on the ODrive

            sublines = decoder(val)
            lines += [indent + name + ": " + sublines[0]] + [
                indent + "  " + line
                for line in sublines[1:]
            ]

        return lines

    lines += await dump_items("", "", [('error', lambda x: decode_flags(x, odrive.enums.ODriveError))])

    for name in odrv.axes:
        lines.append(name)
        lines += await dump_items(
            indent='  ', path_prefix='axis0.',
            items=[
                ('error', lambda x: decode_flags(x, odrive.enums.AxisError)), # this is 0.6.0 legacy
                ('active_errors', lambda x: decode_flags(x, odrive.enums.ODriveError)),
                ('disarm_reason', lambda x: decode_flags(x, odrive.enums.ODriveError)),
                ('procedure_result', lambda x: decode_enum(x, odrive.enums.ProcedureResult)),
                ('last_drv_fault', lambda x: decode_drv_fault(odrv.axis_metadata[name], x)),
            ]
        )

    if odrv.has_property('issues.length') and odrv.has_function('issues.get'):
        issues = await get_issues(odrv)
        if len(issues) == 0:
            lines.append("internal issues: " + RichText("none", *STYLE_GOOD))
        else:
            lines.append("internal issues: " + RichText(str(len(issues)), *STYLE_BAD))
            lines.append("details for bug report: " + RichText(str(issues), *STYLE_WARN))

    if clear:
        await odrv.call_function('clear_errors')

    return RichText('\n').join(lines)

@transform_odrive_objects
async def dump_errors(odrv: RuntimeDevice, clear: bool = False):
    """
    Prints a summary of the error status of the device on stdout.

    If you need the errors as a string instead, see :func:`format_errors()`.
    """
    odrive.rich_text.print_rich_text(await format_errors(odrv, clear))

@transform_odrive_objects
async def request_state(axis: AsyncObject, state: AxisState):
    """
    Requests an axis to enter the specified state.

    No effect if the axis is already in that state.
    """
    previous_state = await axis.current_state.read()
    if previous_state == state:
        return

    await axis.requested_state.write(state)

    start_time = asyncio.get_running_loop().time()
    timeout = 0.2

    while True:
        current_state = AxisState(await axis.current_state.read())
        if current_state != previous_state:
            break

        time_passed = asyncio.get_running_loop().time() - start_time
        if time_passed >= timeout:
            raise TimeoutError(f"Axis failed to enter {repr(state)} after {time_passed} s")
        await asyncio.sleep(0.01)

    # FULL_CALIBRATION_SEQUENCE is a special composite state where current_state
    # reports the current substate.
    if current_state != state and (state != AxisState.FULL_CALIBRATION_SEQUENCE):
        raise Exception(f"Axis failed to enter {repr(state)}: {await format_errors(axis._dev)}")

@transform_odrive_objects
async def run_state(axis: AsyncObject, state: AxisState):
    """
    Runs the requested state and waits until it finishes.

    Example::

        run_state(odrv0.axis0, AxisState.MOTOR_CALIBRATION)

    Upon entering, all pending errors are cleared (:func:`~ODrive.clear_errors()`).
    After entering the requested axis state, the function continuously polls the
    state and feeds the watchdog at 5Hz.
    If the state finishes successfully, the function returns normally.
    If the state finishes with an error, the function raises a
    :class:`odrive.exceptions.DeviceStateException`.
    If the function is cancelled, the ODrive axis is commanded to
    :attr:`~ODrive.Axis.AxisState.IDLE`.
    """
    await axis.watchdog_feed()
    await axis._dev.call_function('clear_errors')
    async with _run_state_context(axis, state):
        logger.debug(f"entered {repr(state)}")
        await _feed_and_monitor([axis], state, success_on_exit=True)

@asynccontextmanager
async def _run_state_context(axis: AsyncObject, state: AxisState = AxisState.CLOSED_LOOP_CONTROL):
    await request_state(axis, state)
    try:
        yield
    finally:
        if axis._dev.device._connected:
            await axis.requested_state.write(AxisState.IDLE)
            logger.debug(f"{axis} was put to IDLE")
        else:
            logger.warning(f"Warning: cannot put {axis} into IDLE because it's no longer connected")

async def _feed_and_monitor(axes: List[AsyncObject], expected_state: Union[AxisState, Literal["any_non_idle"]] = AxisState.CLOSED_LOOP_CONTROL, success_on_exit: bool = False, monitoring_interval: float = 0.2):
    """
    Monitors multiple axes (that they are in CLOSED_LOOP_CONTROL) while feeding
    the watchdog.
    Returns a list of ODrives that entered IDLE as soon as any ODrive enters IDLE.
    """

    # FULL_CALIBRATION_SEQUENCE is a special composite state where current_state
    # reports the current substate.
    if expected_state == AxisState.FULL_CALIBRATION_SEQUENCE:
        expected_state = "any_non_idle"

    while True:
        for axis in axes:
            await axis.watchdog_feed()

        # TODO: detect and report simultaneous errors
        for axis in axes:
            current_state = await axis.current_state.read()
            if current_state == AxisState.IDLE:
                procedure_result = await axis.procedure_result.read()
                if procedure_result == ProcedureResult.SUCCESS and success_on_exit:
                    return # TODO: check other devices too
                raise await DeviceStateException.load_with_procedure_result(axis, procedure_result)
            elif (expected_state == "any_non_idle") or (current_state == expected_state):
                pass # still in expected state
            else:
                raise DeviceStateException.from_msg(axis, f"Axis entered unexpected state {current_state} (expected {expected_state})")

        await asyncio.sleep(monitoring_interval)

@transform_odrive_objects
async def rate_test(odrv: RuntimeDevice, count: int = 10000, mode: str = 'sequential'):
    """
    Tests how many integers per second can be transmitted

    Supported modes:
     - all
     - sequential
     - pipelined
     - batch
    """
    if mode == 'all':
        await rate_test(odrv, count, 'sequential')
        await rate_test(odrv, count, 'pipelined')
        await rate_test(odrv, count, 'batch')
        return

    name = 'n_evt_control_loop'

    print(f"reading {count} values...")
    start_time = time.monotonic()
    
    if mode == 'sequential':
        for _  in range(count):
            await odrv.read(name)
    elif mode == 'pipelined':
        tasks = [
            asyncio.create_task(odrv.read(name))
            for _ in range(count)
        ]
        await asyncio.gather(*tasks)
    elif mode == 'batch':
        await odrv.read_multiple([name] * count)
    else:
        raise Exception(f"unknown mode {mode}")

    duration = time.monotonic() - start_time
    print(f"{mode} read of {count} values took {duration} s ({count / duration} values/s)")

def calculate_thermistor_coeffs(degree, Rload, R_25, Beta, Tmin, Tmax, thermistor_bottom = False, plot = False):
    import numpy as np
    T_25 = 25 + 273.15 #Kelvin
    temps = np.linspace(Tmin, Tmax, 1000)
    tempsK = temps + 273.15

    # https://en.wikipedia.org/wiki/Thermistor#B_or_%CE%B2_parameter_equation
    r_inf = R_25 * np.exp(-Beta/T_25)
    R_temps = r_inf * np.exp(Beta/tempsK)
    if thermistor_bottom:
        V = R_temps / (Rload + R_temps)
    else:
        V = Rload / (Rload + R_temps)

    fit = np.polyfit(V, temps, degree)
    p1 = np.poly1d(fit)
    fit_temps = p1(V)

    if plot:
        import matplotlib.pyplot as plt
        print(fit)
        plt.plot(V, temps, label='actual')
        plt.plot(V, fit_temps, label='fit')
        plt.xlabel('normalized voltage')
        plt.ylabel('Temp [C]')
        plt.legend(loc=0)
        plt.show()

    return p1

@transform_odrive_objects
async def set_motor_thermistor_coeffs(axis: AsyncObject, Rload, R_25, Beta, Tmin, Tmax, thermistor_bottom = True):
    coeffs = calculate_thermistor_coeffs(3, Rload, R_25, Beta, Tmin, Tmax, thermistor_bottom)
    await axis.motor.motor_thermistor.config.poly_coefficient_0.write(float(coeffs[3]))
    await axis.motor.motor_thermistor.config.poly_coefficient_1.write(float(coeffs[2]))
    await axis.motor.motor_thermistor.config.poly_coefficient_2.write(float(coeffs[1]))
    await axis.motor.motor_thermistor.config.poly_coefficient_3.write(float(coeffs[0]))

def decode_drv_faults(metadata, code):
    active_flags = []
    i = 0
    for bit, name in metadata['faults']:
        if code & (1 << bit):
            active_flags.append(name)
            code ^= (1 << bit)
    assert(code == 0)

    if len(active_flags) == len(metadata['faults']):
        return "unpowered"
    if any(active_flags):
        return ", ".join(active_flags)
    else:
        return "None"


_global_liveplotter = None

async def _run_liveplotter(awaitable):
    global _global_liveplotter
    try:
        await awaitable
    except Exception as ex:
        print(f"liveplotter failed: {ex}")
        traceback.print_exc()
    finally:
        print("stopped liveplotter")
        _global_liveplotter = None

def _start_liveplotter(*args):
    global _global_liveplotter
    if not _global_liveplotter is None:
        raise Exception("Liveplotter already running. Close the window or call stop_liveplotter().")

    import odrive.plotting
    awaitable = odrive.plotting.start_liveplotter(*args)
    _global_liveplotter = asyncio.create_task(_run_liveplotter(awaitable))

def stop_liveplotter():
    """
    Stops the currently running liveplotter.
    """
    global _global_liveplotter
    if not _global_liveplotter is None:
        _global_liveplotter.cancel()
        _global_liveplotter = None

def start_liveplotter(properties: List[AsyncProperty], layout: Optional[List[List[str]]] = None, window_size: float = 5.0):
    """
    Starts the liveplotter. See also :ref:`liveplotter`.

    This function returns immediately, it does not block until the plot is closed.
    The liveplotter can be stopped by closing the figure or calling :func:`stop_liveplotter()`.

    Raises an exception if a liveplotter is already open.

    :param properties: A list of ODrive properties that shall be read.
    :param layout: An optional nested list of keys that defines the subplots and
        the ordering of data within each subplot.
        Each string is a name of a plotted property, e.g. "axis0.pos_estimate".
        If multiple ODrives are plotted, prepend the ODrive name.
        Each list of strings correspond to one subplot.
        If omitted, all properties are shown on a single subplot.
    :param window_size: The size of the x-axis in number of samples.
    """
    if isinstance(properties, types.FunctionType):
        raise TypeError("start_liveplotter() no longer takes a function as an argument. See https://docs.odriverobotics.com/v/devel/interfaces/odrivetool.html#liveplotter.")
    if (not isinstance(properties, list)) or (not all(isinstance(p, AsyncProperty) for p in properties)):
        raise TypeError("`properties` argument must be a list of properties.")
    run_sync_on_loop(lambda: _start_liveplotter(properties, layout, window_size), get_device_manager().loop)


# TODO: this needs to be ported to the Recorder and async design
#def step_and_plot(  axis,
#                    step_size=100.0,
#                    settle_time=0.5,
#                    data_rate=500.0,
#                    ctrl_mode=ControlMode.POSITION_CONTROL):
#    
#    if ctrl_mode == ControlMode.POSITION_CONTROL:
#        get_var_callback = lambda :[axis.encoder.pos_estimate, axis.controller.pos_setpoint]
#        initial_setpoint = axis.encoder.pos_estimate
#        def set_setpoint(setpoint):
#            axis.controller.pos_setpoint = setpoint
#    elif ctrl_mode == ControlMode.VELOCITY_CONTROL:
#        get_var_callback = lambda :[axis.encoder.vel_estimate, axis.controller.vel_setpoint]
#        initial_setpoint = 0
#        def set_setpoint(setpoint):
#            axis.controller.vel_setpoint = setpoint
#    else:
#        print("Invalid control mode")
#        return
#    
#    initial_settle_time = 0.5
#    initial_control_mode = axis.controller.config.control_mode # Set it back afterwards
#    print(initial_control_mode)
#    axis.controller.config.control_mode = ctrl_mode
#    axis.requested_state = AxisState.CLOSED_LOOP_CONTROL
#    
#    capture = BulkCapture(get_var_callback,
#                          data_rate=data_rate,
#                          duration=initial_settle_time + settle_time)
#
#    set_setpoint(initial_setpoint)
#    time.sleep(initial_settle_time)
#    set_setpoint(initial_setpoint + step_size) # relative/incremental movement
#
#    capture.event.wait() # wait for Bulk Capture to be complete
#
#    axis.requested_state = AxisState.IDLE
#    axis.controller.config.control_mode = initial_control_mode
#    capture.plot()


def print_drv_regs(name, motor):
    """
    Dumps the current gate driver regisers for the specified motor
    """
    fault = motor.gate_driver.drv_fault
    status_reg_1 = motor.gate_driver.status_reg_1
    status_reg_2 = motor.gate_driver.status_reg_2
    ctrl_reg_1 = motor.gate_driver.ctrl_reg_1
    ctrl_reg_2 = motor.gate_driver.ctrl_reg_2
    print(name + ": " + str(fault))
    print("DRV Fault Code: " + str(fault))
    print("Status Reg 1: " + str(status_reg_1) + " (" + format(status_reg_1, '#010b') + ")")
    print("Status Reg 2: " + str(status_reg_2) + " (" + format(status_reg_2, '#010b') + ")")
    print("Control Reg 1: " + str(ctrl_reg_1) + " (" + format(ctrl_reg_1, '#013b') + ")")
    print("Control Reg 2: " + str(ctrl_reg_2) + " (" + format(ctrl_reg_2, '#09b') + ")")


@transform_odrive_objects
async def dump_interrupts(odrv: RuntimeDevice):
    interrupts = [
        (-12, "MemoryManagement_IRQn"),
        (-11, "BusFault_IRQn"),
        (-10, "UsageFault_IRQn"),
        (-5, "SVCall_IRQn"),
        (-4, "DebugMonitor_IRQn"),
        (-2, "PendSV_IRQn"),
        (-1, "SysTick_IRQn"),
        (0, "WWDG_IRQn"),
        (1, "PVD_IRQn"),
        (2, "TAMP_STAMP_IRQn"),
        (3, "RTC_WKUP_IRQn"),
        (4, "FLASH_IRQn"),
        (5, "RCC_IRQn"),
        (6, "EXTI0_IRQn"),
        (7, "EXTI1_IRQn"),
        (8, "EXTI2_IRQn"),
        (9, "EXTI3_IRQn"),
        (10, "EXTI4_IRQn"),
        (11, "DMA1_Stream0_IRQn"),
        (12, "DMA1_Stream1_IRQn"),
        (13, "DMA1_Stream2_IRQn"),
        (14, "DMA1_Stream3_IRQn"),
        (15, "DMA1_Stream4_IRQn"),
        (16, "DMA1_Stream5_IRQn"),
        (17, "DMA1_Stream6_IRQn"),
        (18, "ADC_IRQn"),
        (19, "CAN1_TX_IRQn"),
        (20, "CAN1_RX0_IRQn"),
        (21, "CAN1_RX1_IRQn"),
        (22, "CAN1_SCE_IRQn"),
        (23, "EXTI9_5_IRQn"),
        (24, "TIM1_BRK_TIM9_IRQn"),
        (25, "TIM1_UP_TIM10_IRQn"),
        (26, "TIM1_TRG_COM_TIM11_IRQn"),
        (27, "TIM1_CC_IRQn"),
        (28, "TIM2_IRQn"),
        (29, "TIM3_IRQn"),
        (30, "TIM4_IRQn"),
        (31, "I2C1_EV_IRQn"),
        (32, "I2C1_ER_IRQn"),
        (33, "I2C2_EV_IRQn"),
        (34, "I2C2_ER_IRQn"),
        (35, "SPI1_IRQn"),
        (36, "SPI2_IRQn"),
        (37, "USART1_IRQn"),
        (38, "USART2_IRQn"),
        (39, "USART3_IRQn"),
        (40, "EXTI15_10_IRQn"),
        (41, "RTC_Alarm_IRQn"),
        (42, "OTG_FS_WKUP_IRQn"),
        (43, "TIM8_BRK_TIM12_IRQn"),
        (44, "TIM8_UP_TIM13_IRQn"),
        (45, "TIM8_TRG_COM_TIM14_IRQn"),
        (46, "TIM8_CC_IRQn"),
        (47, "DMA1_Stream7_IRQn"),
        (48, "FMC_IRQn"),
        (49, "SDMMC1_IRQn"),
        (50, "TIM5_IRQn"),
        (51, "SPI3_IRQn"),
        (52, "UART4_IRQn"),
        (53, "UART5_IRQn"),
        (54, "TIM6_DAC_IRQn"),
        (55, "TIM7_IRQn"),
        (56, "DMA2_Stream0_IRQn"),
        (57, "DMA2_Stream1_IRQn"),
        (58, "DMA2_Stream2_IRQn"),
        (59, "DMA2_Stream3_IRQn"),
        (60, "DMA2_Stream4_IRQn"),
        (61, "ETH_IRQn"),
        (62, "ETH_WKUP_IRQn"),
        (63, "CAN2_TX_IRQn"),
        (64, "CAN2_RX0_IRQn"),
        (65, "CAN2_RX1_IRQn"),
        (66, "CAN2_SCE_IRQn"),
        (67, "OTG_FS_IRQn"),
        (68, "DMA2_Stream5_IRQn"),
        (69, "DMA2_Stream6_IRQn"),
        (70, "DMA2_Stream7_IRQn"),
        (71, "USART6_IRQn"),
        (72, "I2C3_EV_IRQn"),
        (73, "I2C3_ER_IRQn"),
        (74, "OTG_HS_EP1_OUT_IRQn"),
        (75, "OTG_HS_EP1_IN_IRQn"),
        (76, "OTG_HS_WKUP_IRQn"),
        (77, "OTG_HS_IRQn"),
        # gap
        (80, "RNG_IRQn"),
        (81, "FPU_IRQn"),
        (82, "UART7_IRQn"),
        (83, "UART8_IRQn"),
        (84, "SPI4_IRQn"),
        (85, "SPI5_IRQn"),
        # gap
        (87, "SAI1_IRQn"),
        # gap
        (91, "SAI2_IRQn"),
        (92, "QUADSPI_IRQn"),
        (93, "LPTIM1_IRQn"),
        # gap
        (103, "SDMMC2_IRQn"),
        (117, "TIM16_IRQn")
    ]

    print("|   # | Name                    | Prio | En |   Count |")
    print("|-----|-------------------------|------|----|---------|")
    for irqn, irq_name in interrupts:
        status = (await odrv.call_function('get_interrupt_status', irqn))
        if (status != 0):
            print("| {} | {} | {} | {} | {} |".format(
                    str(irqn).rjust(3),
                    irq_name.ljust(23),
                    str(status & 0xff).rjust(4),
                    " *" if (status & 0x80000000) else "  ",
                    str((status >> 8) & 0x7fffff).rjust(7)))

@transform_odrive_objects
async def dump_threads(odrv: RuntimeDevice):
    prefixes = ["max_stack_usage_", "stack_size_", "prio_"]
    keys = [k[len(prefix)+13:] for k in odrv.properties.keys() for prefix in prefixes if k.startswith(f"system_stats.{prefix}")]
    good_keys = set([k for k in set(keys) if keys.count(k) == len(prefixes)])
    if len(good_keys) > len(set(keys)):
        print("Warning: incomplete thread information for threads {}".format(set(keys) - good_keys))

    print("| Name    | Stack Size [B] | Max Ever Stack Usage [B] | Prio |")
    print("|---------|----------------|--------------------------|------|")
    for k in sorted(good_keys):
        sz = await odrv.read(f"system_stats.stack_size_{k}")
        use = await odrv.read(f"system_stats.max_stack_usage_{k}")
        print("| {} | {} | {} | {} |".format(
            k.ljust(7),
            str(sz).rjust(14),
            "{} ({:.1f}%)".format(use, use / sz * 100).rjust(24),
            str(await odrv.read(f"system_stats.prio_{k}")).rjust(4)
        ))

@transform_odrive_objects
async def dump_dma(odrv: RuntimeDevice):
    if odrv.board.product_line == 3:
        dma_functions = [[
            # https://www.st.com/content/ccc/resource/technical/document/reference_manual/3d/6d/5a/66/b4/99/40/d4/DM00031020.pdf/files/DM00031020.pdf/jcr:content/translations/en.DM00031020.pdf Table 42
            ["SPI3_RX",          "-",                  "SPI3_RX",           "SPI2_RX",            "SPI2_TX",            "SPI3_TX",     "-",                  "SPI3_TX"],
            ["I2C1_RX",          "-",                  "TIM7_UP",           "-",                  "TIM7_UP",            "I2C1_RX",     "I2C1_TX",            "I2C1_TX"],
            ["TIM4_CH1",         "-",                  "I2S3_EXT_RX",       "TIM4_CH2",           "I2S2_EXT_TX",        "I2S3_EXT_TX", "TIM4_UP",            "TIM4_CH3"],
            ["I2S3_EXT_RX",      "TIM2_UP/TIM2_CH3",   "I2C3_RX",           "I2S2_EXT_RX",        "I2C3_TX",            "TIM2_CH1",    "TIM2_CH2/TIM2_CH4",  "TIM2_UP/TIM2_CH4"],
            ["UART5_RX",         "USART3_RX",          "UART4_RX",          "USART3_TX",          "UART4_TX",           "USART2_RX",   "USART2_TX",          "UART5_TX"],
            ["UART8_TX",         "UART7_TX",           "TIM3_CH4/TIM3_UP",  "UART7_RX",           "TIM3_CH1/TIM3_TRIG", "TIM3_CH2",    "UART8_RX",           "TIM3_CH3"],
            ["TIM5_CH3/TIM5_UP", "TIM5_CH4/TIM5_TRIG", "TIM5_CH1",          "TIM5_CH4/TIM5_TRIG", "TIM5_CH2",           "-",           "TIM5_UP",            "-"],
            ["-",                "TIM6_UP",            "I2C2_RX",           "I2C2_RX",            "USART3_TX",          "DAC1",        "DAC2",               "I2C2_TX"],
        ], [
            # https://www.st.com/content/ccc/resource/technical/document/reference_manual/3d/6d/5a/66/b4/99/40/d4/DM00031020.pdf/files/DM00031020.pdf/jcr:content/translations/en.DM00031020.pdf Table 43
            ["ADC1",      "SAI1_A",      "TIM8_CH1/TIM8_CH2/TIM8_CH3",    "SAI1_A",      "ADC1",                          "SAI1_B",      "TIM1_CH1/TIM1_CH2/TIM1_CH3",    "-"],
            ["-",         "DCMI",        "ADC2",                          "ADC2",        "SAI1_B",                        "SPI6_TX",     "SPI6_RX",                       "DCMI"],
            ["ADC3",      "ADC3",        "-",                             "SPI5_RX",     "SPI5_TX",                       "CRYP_OUT",    "CRYP_IN",                       "HASH_IN"],
            ["SPI1_RX",   "-",           "SPI1_RX",                       "SPI1_TX",     "-",                             "SPI1_TX",     "-",                             "-"],
            ["SPI4_RX",   "SPI4_TX",     "USART1_RX",                     "SDIO",        "-",                             "USART1_RX",   "SDIO",                          "USART1_TX"],
            ["-",         "USART6_RX",   "USART6_RX",                     "SPI4_RX",     "SPI4_TX",                       "-",           "USART6_TX",                     "USART6_TX"],
            ["TIM1_TRIG", "TIM1_CH1",    "TIM1_CH2",                      "TIM1_CH1",    "TIM1_CH4/TIM1_TRIG/TIM1_COM",   "TIM1_UP",     "TIM1_CH3",                      "-"],
            ["-",         "TIM8_UP",     "TIM8_CH1",                      "TIM8_CH2",    "TIM8_CH3",                      "SPI5_RX",     "SPI5_TX",                       "TIM8_CH4/TIM8_TRIG/TIM8_COM"],
        ]]
    elif odrv.board.product_line == 4 or odrv.board.product_line == 5 or odrv.board.product_line == 6:
        dma_functions = [[
            # https://www.st.com/resource/en/reference_manual/dm00305990-stm32f72xxx-and-stm32f73xxx-advanced-armbased-32bit-mcus-stmicroelectronics.pdf Table 26
            ["SPI3_RX",          "-",                  "SPI3_RX",           "SPI2_RX",            "SPI2_TX",            "SPI3_TX",     "-",                  "SPI3_TX"],
            ["I2C1_RX",          "I2C3_RX",            "TIM7_UP",           "-",                  "TIM7_UP",            "I2C1_RX",     "I2C1_TX",            "I2C1_TX"],
            ["TIM4_CH1",         "-",                  "-",                 "TIM4_CH2",           "-",                  "-",           "TIM4_UP",            "TIM4_CH3"],
            ["-",                "TIM2_UP/TIM2_CH3",   "I2C3_RX",           "-",                  "I2C3_TX",            "TIM2_CH1",    "TIM2_CH2/TIM2_CH4",  "TIM2_UP/TIM2_CH4"],
            ["UART5_RX",         "USART3_RX",          "UART4_RX",          "USART3_TX",          "UART4_TX",           "USART2_RX",   "USART2_TX",          "UART5_TX"],
            ["UART8_TX",         "UART7_TX",           "TIM3_CH4/TIM3_UP",  "UART7_RX",           "TIM3_CH1/TIM3_TRIG", "TIM3_CH2",    "UART8_RX",           "TIM3_CH3"],
            ["TIM5_CH3/TIM5_UP", "TIM5_CH4/TIM5_TRIG", "TIM5_CH1",          "TIM5_CH4/TIM5_TRIG", "TIM5_CH2",           "-",           "TIM5_UP",            "-"],
            ["-",                "TIM6_UP",            "I2C2_RX",           "I2C2_RX",            "USART3_TX",          "DAC1",        "DAC2",               "I2C2_TX"],
        ], [
            # https://www.st.com/resource/en/reference_manual/dm00305990-stm32f72xxx-and-stm32f73xxx-advanced-armbased-32bit-mcus-stmicroelectronics.pdf Table 27
            ["ADC1",      "SAI1_A",      "TIM8_CH1/TIM8_CH2/TIM8_CH3",    "SAI1_A",      "ADC1",                          "SAI1_B",      "TIM1_CH1/TIM1_CH2/TIM1_CH3",    "SAI2_B"],
            ["-",         "-",           "ADC2",                          "ADC2",        "SAI1_B",                        "-",           "-",                             "-"],
            ["ADC3",      "ADC3",        "-",                             "SPI5_RX",     "SPI5_TX",                       "AES_OUT",     "AES_IN",                        "-"],
            ["SPI1_RX",   "-",           "SPI1_RX",                       "SPI1_TX",     "SAI2_A",                        "SPI1_TX",     "SAI2_B",                        "QUADSPI"],
            ["SPI4_RX",   "SPI4_TX",     "USART1_RX",                     "SDMMC1",      "-",                             "USART1_RX",   "SDMMC1",                        "USART1_TX"],
            ["-",         "USART6_RX",   "USART6_RX",                     "SPI4_RX",     "SPI4_TX",                       "-",           "USART6_TX",                     "USART6_TX"],
            ["TIM1_TRIG", "TIM1_CH1",    "TIM1_CH2",                      "TIM1_CH1",    "TIM1_CH4/TIM1_TRIG/TIM1_COM",   "TIM1_UP",     "TIM1_CH3",                      "-"],
            ["-",         "TIM8_UP",     "TIM8_CH1",                      "TIM8_CH2",    "TIM8_CH3",                      "SPI5_RX",     "SPI5_TX",                       "TIM8_CH4/TIM8_TRIG/TIM8_COM"],
            None,
            None,
            None,
            ["SDMMC2",    "-",           "-",                             "-",           "-",                             "SDMMC2",      "-",                             "-"],
        ]]

    print("| Name         | Prio | Channel                          | Configured |")
    print("|--------------|------|----------------------------------|------------|")
    for stream_num in range(16):
        status = (await odrv.call_function('get_dma_status', stream_num))
        if (status != 0):
            channel = (status >> 2) & 0x7
            ch_name = dma_functions[stream_num >> 3][channel][stream_num & 0x7]
            print("| DMA{}_Stream{} |    {} | {} {} |          {} |".format(
                     (stream_num >> 3) + 1,
                     (stream_num & 0x7),
                     (status & 0x3),
                     channel,
                     ("(" + ch_name + ")").ljust(30),
                     "*" if (status & 0x80000000) else " "))

@transform_odrive_objects
async def dump_timing(odrv: RuntimeDevice, n_samples=100, path='/tmp/timings.png', reset_timings=False):
    import matplotlib.pyplot as plt
    import numpy as np

    names = []
    for name in odrv.properties.keys():
        if name.startswith('task_times.') and name.endswith('.start_time'):
            name = name[11:-11]
            if not name in names:
                names.append(name)
    
    timings = [(name, [], []) for name in names] # (name, start_times, lengths)

    # reset max-timings
    if reset_timings:
        for name, obj, start_times, lengths in timings:
            obj.max_length = 0

    # Take a couple of samples
    print("sampling...")
    for i in range(n_samples):
        await odrv.write('task_timers_armed', True) # Trigger sample and wait for it to finish
        while await odrv.read('task_timers_armed'): pass
        for name, start_times, lengths in timings:
            start_times.append(await odrv.read(f"task_times.{name}.start_time"))
            lengths.append(await odrv.read(f"task_times.{name}.length"))
    print("done")

    # sort by start time
    timings = sorted(timings, key = lambda x: np.mean(x[1]))

    patch_pyplot(plt)
    plt.rcParams['figure.figsize'] = 21, 9
    plt.figure()
    plt.grid(True)
    plt.barh(
        [-i for i in range(len(timings))], # y positions
        [np.mean(lengths) for name, start_times, lengths in timings], # lengths
        left = [np.mean(start_times) for name, start_times, lengths in timings], # starts
        xerr = (
            [np.std(lengths) for name, start_times, lengths in timings], # error bars to the left side
            [(min(await odrv.read(f"task_times.{name}.max_length"), 20100) - np.mean(lengths)) for name, start_times, lengths in timings], # error bars to the right side  - TODO: remove artificial min()
        ),
        tick_label = [name for name, start_times, lengths in timings], # labels
    )
    plt.savefig(path, bbox_inches='tight')
    print(f"saved to {path}")


def _ensure_debug_info(odrv: RuntimeDevice):
    try:
        import odrive_private.debug_utils
    except ImportError:
        raise NotImplementedError()
    odrive_private.debug_utils.ensure_debug_info(odrv)

@transform_odrive_objects
async def ram_osci_config(odrv: RuntimeDevice, expressions: List[Union[str, int]]):
    max_addresses = len(odrv.functions['oscilloscope.config'].inputs)
    assert len(expressions) > 0
    assert len(expressions) <= max_addresses

    addresses = [0] * len(expressions)
    for i in range(len(expressions)):
        if isinstance(expressions[i], int):
            addresses[i] = expressions[i]
        elif isinstance(expressions[i], str) and expressions[i].startswith("raw:"):
            expr = expressions[i][4:]
            _ensure_debug_info(odrv)
            addresses[i], _ = await odrv._dbg_info.resolve_symbol(expr)
        elif isinstance(expressions[i], str):
            prop_info = odrv.try_get_prop_info(expressions[i])
            addresses[i] = (0xffff << 16) | prop_info.endpoint_id
        else:
            TypeError("expressions must be int or str type")

    print(f"Recording from " + ", ".join(['0x{:08x}'.format(addr) for addr in addresses]) + "...")
    
    await odrv.call_function('oscilloscope.config', *addresses, *([0] * (max_addresses - len(expressions))))

@transform_odrive_objects
async def ram_osci_trigger(odrv: RuntimeDevice, trigger_point: float):
    assert trigger_point >= 0 and trigger_point <= 1
    await odrv.call_function('oscilloscope.trigger', trigger_point)

@transform_odrive_objects
async def ram_osci_download(odrv: RuntimeDevice, expressions: List[Union[str, int]]):
    while await odrv.read('oscilloscope.recording'):
        await asyncio.sleep(0.1)

    type_infos = [None] * len(expressions) # (byte_size, bytes_to_val)
    for i in range(len(expressions)):
        if isinstance(expressions[i], int):
            type_infos[i] = (4, (lambda b: int.from_bytes(b, 'little')))
        elif isinstance(expressions[i], str) and expressions[i].startswith("raw:"):
            expr = expressions[i][4:]
            _ensure_debug_info(odrv)
            _, type_info = await odrv._dbg_info.resolve_symbol(expr)
            type_infos[i] = type_info.byte_size, type_info.bytes_to_val
        elif isinstance(expressions[i], str):
            prop_info = odrv.try_get_prop_info(expressions[i])
            def bytes_to_val(val, codec=prop_info.codec):
                return decode_all([codec], val, odrv)[0]
            type_infos[i] = prop_info.codec.size, bytes_to_val
        else:
            TypeError("expressions must be int or str type")

    print(f"Fetching buffer...")

    buf = b''
    for i in range(0, await odrv.read('oscilloscope.size'), 32):
        raw_ints = await odrv.call_function('oscilloscope.get_raw', i)
        buf += struct.pack('<QQQQ', *raw_ints)
    
    outputs = []
    offset = 0
    sample_size = sum(4 for _ in type_infos)
    while True:
        elem = ()
        for byte_size, bytes_to_val in type_infos:
            if offset + byte_size > len(buf):
                elem = None
                print(f"break {elem} at {offset}, {byte_size}, {len(buf)}")
                break
            elem += (bytes_to_val(buf[offset:(offset+byte_size)]),)
            assert byte_size <= 4
            offset += max(byte_size, 4)
        if elem is None:
            break
        outputs.append(elem)

    # Rotate
    pos = int(await odrv.read('oscilloscope.pos') / sample_size)
    outputs_part0 = outputs[:pos]
    outputs_part1 = outputs[pos:]
    if await odrv.read('oscilloscope.rollover'):
        outputs = outputs_part1 + outputs_part0
    else:
        outputs = outputs_part0

    sampling_freq = 8000
    print(f"Collected {len(outputs)} samples, which corresponds to {len(outputs)/sampling_freq*1000:.2f} ms of data (assuming a sampling frequency of {sampling_freq})")

    # transpose output
    return [[outputs[i][j] for i in range(len(outputs))] for j in range(len(outputs[0]))]

@transform_odrive_objects
async def ram_osci_run(odrv: RuntimeDevice, expressions, trigger_point=0.0):
    """
    Configures the RAM oscilloscope with the specified expressions, optionally
    triggers it and waits for it to finish before downloading the data.

    trigger_point: A number in [0.0, 1.0] or None.
        If None, it is expected that a custom trigger in firmware is used after
        configuring the osci.
    """
    await ram_osci_config(odrv, expressions)
    if not trigger_point is None:
        await ram_osci_trigger(odrv, trigger_point)
    else:
        print("waiting for in-firmware trigger...")
    return await ram_osci_download(odrv, expressions)

def to_sync(odrv: Union[RuntimeDevice, AsyncObject, SyncObject]):
    """
    Converts an ODrive object that was obtained for asynchronous usage (:func:`~odrive.find_async`)
    to an ODrive object that is suitable for synchronous usage (see :ref:`python-async`).

    The returned object is thread-safe.
    """
    if isinstance(odrv, RuntimeDevice):
        return odrv.sync_wrapper
    elif isinstance(odrv, AsyncObject):
        return odrv._dev.sync_wrapper
    elif isinstance(odrv, SyncObject):
        return odrv
    else:
        raise TypeError(f"unsupported type {type(odrv)}")

def to_async(odrv: Union[RuntimeDevice, AsyncObject, SyncObject]):
    """
    Converts an ODrive object that was obtained for synchronous usage (:func:`~odrive.find_sync`)
    to an object that is suitable for asynchronous usage (see :ref:`python-async`).

    The returned object must only be used on the same thread as the device manager
    (:func:`~odrive.device_manager.get_device_manager`).
    """
    if isinstance(odrv, RuntimeDevice):
        return odrv.async_wrapper
    elif isinstance(odrv, AsyncObject):
        return odrv
    elif isinstance(odrv, SyncObject):
        return odrv._dev.async_wrapper
    else:
        raise TypeError(f"unsupported type {type(odrv)}")
