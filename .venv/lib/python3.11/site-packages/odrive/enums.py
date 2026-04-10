
# TODO: This file is dangerous because the enums could potentially change between API versions. Should transmit as part of the JSON.
# To regenerate this file, nagivate to the top level of the ODrive repository and run:
#   python Firmware/interface_generator_stub.py --definitions Firmware/odrive-interface.yaml --template tools/enums_template.j2 --output tools/odrive/enums.py

import enum

class GpioMode(enum.IntEnum):
    DIGITAL                                  = 0
    DIGITAL_PULL_UP                          = 1
    DIGITAL_PULL_DOWN                        = 2
    ANALOG_IN                                = 3
    UART_A                                   = 4
    UART_B                                   = 5
    UART_C                                   = 6
    CAN_A                                    = 7
    I2C_A                                    = 8
    SPI_A                                    = 9
    PWM                                      = 10
    ENC0                                     = 11
    ENC1                                     = 12
    ENC2                                     = 13
    MECH_BRAKE                               = 14
    STATUS                                   = 15
    BRAKE_RES                                = 16
    AUTO                                     = 17

class StreamProtocolType(enum.IntEnum):
    FIBRE                                    = 0
    ASCII                                    = 1
    STDOUT                                   = 2
    ASCII_AND_STDOUT                         = 3
    OTHER                                    = 4

class Protocol(enum.IntFlag):
    NONE                                     = 0x00000000
    SIMPLE                                   = 0x00000001

class AxisState(enum.IntEnum):
    UNDEFINED                                = 0
    IDLE                                     = 1
    STARTUP_SEQUENCE                         = 2
    FULL_CALIBRATION_SEQUENCE                = 3
    MOTOR_CALIBRATION                        = 4
    ENCODER_INDEX_SEARCH                     = 6
    ENCODER_OFFSET_CALIBRATION               = 7
    CLOSED_LOOP_CONTROL                      = 8
    LOCKIN_SPIN                              = 9
    ENCODER_DIR_FIND                         = 10
    HOMING                                   = 11
    ENCODER_HALL_POLARITY_CALIBRATION        = 12
    ENCODER_HALL_PHASE_CALIBRATION           = 13
    ANTICOGGING_CALIBRATION                  = 14
    HARMONIC_CALIBRATION                     = 15
    HARMONIC_CALIBRATION_COMMUTATION         = 16

class ControlMode(enum.IntEnum):
    VOLTAGE_CONTROL                          = 0
    TORQUE_CONTROL                           = 1
    VELOCITY_CONTROL                         = 2
    POSITION_CONTROL                         = 3

class ComponentStatus(enum.IntEnum):
    NOMINAL                                  = 0
    NO_RESPONSE                              = 1
    INVALID_RESPONSE_LENGTH                  = 2
    PARITY_MISMATCH                          = 3
    ILLEGAL_HALL_STATE                       = 4
    POLARITY_NOT_CALIBRATED                  = 5
    PHASES_NOT_CALIBRATED                    = 6
    NUMERICAL_ERROR                          = 7
    MISSING_INPUT                            = 8
    RELATIVE_MODE                            = 9
    UNCONFIGURED                             = 10
    OVERSPEED                                = 11
    INDEX_NOT_FOUND                          = 12
    BAD_CONFIG                               = 13
    NOT_ENABLED                              = 14
    SPINOUT_DETECTED                         = 15

class ODriveError(enum.IntFlag):
    NONE                                     = 0x00000000
    INITIALIZING                             = 0x00000001
    SYSTEM_LEVEL                             = 0x00000002
    TIMING_ERROR                             = 0x00000004
    MISSING_ESTIMATE                         = 0x00000008
    BAD_CONFIG                               = 0x00000010
    DRV_FAULT                                = 0x00000020
    MISSING_INPUT                            = 0x00000040
    DC_BUS_OVER_VOLTAGE                      = 0x00000100
    DC_BUS_UNDER_VOLTAGE                     = 0x00000200
    DC_BUS_OVER_CURRENT                      = 0x00000400
    DC_BUS_OVER_REGEN_CURRENT                = 0x00000800
    CURRENT_LIMIT_VIOLATION                  = 0x00001000
    MOTOR_OVER_TEMP                          = 0x00002000
    INVERTER_OVER_TEMP                       = 0x00004000
    VELOCITY_LIMIT_VIOLATION                 = 0x00008000
    POSITION_LIMIT_VIOLATION                 = 0x00010000
    WATCHDOG_TIMER_EXPIRED                   = 0x01000000
    ESTOP_REQUESTED                          = 0x02000000
    SPINOUT_DETECTED                         = 0x04000000
    BRAKE_RESISTOR_DISARMED                  = 0x08000000
    THERMISTOR_DISCONNECTED                  = 0x10000000
    CALIBRATION_ERROR                        = 0x40000000

class ProcedureResult(enum.IntEnum):
    SUCCESS                                  = 0
    BUSY                                     = 1
    CANCELLED                                = 2
    DISARMED                                 = 3
    NO_RESPONSE                              = 4
    POLE_PAIR_CPR_MISMATCH                   = 5
    PHASE_RESISTANCE_OUT_OF_RANGE            = 6
    PHASE_INDUCTANCE_OUT_OF_RANGE            = 7
    UNBALANCED_PHASES                        = 8
    INVALID_MOTOR_TYPE                       = 9
    ILLEGAL_HALL_STATE                       = 10
    TIMEOUT                                  = 11
    HOMING_WITHOUT_ENDSTOP                   = 12
    INVALID_STATE                            = 13
    NOT_CALIBRATED                           = 14
    NOT_CONVERGING                           = 15

class EncoderId(enum.IntEnum):
    NONE                                     = 0
    INC_ENCODER0                             = 1
    INC_ENCODER1                             = 2
    INC_ENCODER2                             = 3
    SENSORLESS_ESTIMATOR                     = 4
    SPI_ENCODER0                             = 5
    SPI_ENCODER1                             = 6
    SPI_ENCODER2                             = 7
    HALL_ENCODER0                            = 8
    HALL_ENCODER1                            = 9
    RS485_ENCODER0                           = 10
    RS485_ENCODER1                           = 11
    RS485_ENCODER2                           = 12
    ONBOARD_ENCODER0                         = 13
    ONBOARD_ENCODER1                         = 14

class SpiEncoderMode(enum.IntEnum):
    DISABLED                                 = 0
    RLS                                      = 1
    AMS                                      = 2
    CUI                                      = 3
    AEAT                                     = 4
    MA732                                    = 5
    TLE                                      = 6
    BISSC                                    = 7
    NOVOHALL                                 = 8

class IncrementalEncoderFilter(enum.IntEnum):
    SPEED_10M                                = 0
    SPEED_20M                                = 1

class Rs485EncoderMode(enum.IntEnum):
    DISABLED                                 = 0
    AMT21_POLLING                            = 1
    AMT21_EVENT_DRIVEN                       = 2
    MBS                                      = 3
    ODRIVE_OA1                               = 4

class InputMode(enum.IntEnum):
    INACTIVE                                 = 0
    PASSTHROUGH                              = 1
    VEL_RAMP                                 = 2
    POS_FILTER                               = 3
    MIX_CHANNELS                             = 4
    TRAP_TRAJ                                = 5
    TORQUE_RAMP                              = 6
    MIRROR                                   = 7
    TUNING                                   = 8

class MotorType(enum.IntEnum):
    PMSM_CURRENT_CONTROL                     = 0
    PMSM_VOLTAGE_CONTROL                     = 2
    ACIM                                     = 3

class ThermistorMode(enum.IntEnum):
    NTC                                      = 1
    QUADRATIC                                = 2
    PT1000                                   = 3
    KTY84                                    = 4
    KTY83_122                                = 5

class CanError(enum.IntFlag):
    NONE                                     = 0x00000000
    DUPLICATE_CAN_IDS                        = 0x00000001
    BUS_OFF                                  = 0x00000002
    LOW_LEVEL                                = 0x00000004
    PROTOCOL_INIT                            = 0x00000008


def _extend_enum(t, new_vals):
    all = {
        e.name: e.value for e in t
    }
    all.update(new_vals)
    if issubclass(t, enum.IntFlag):
        return enum.IntFlag(t.__name__, all)
    else:
        return enum.IntEnum(t.__name__, all)

### Legacy enums (not autogenerated) ###

# Renamed during 0.6.9 => 0.6.10

MotorType = _extend_enum(MotorType, {
    'HIGH_CURRENT': 0,
    'GIMBAL': 2,
})

# Renamed during 0.6.7 => 0.6.8

EncoderId = _extend_enum(EncoderId, {
    'AMT21_ENCODER0': 10,
    'AMT21_ENCODER1': 11,
    'AMT21_ENCODER2': 12,
})

# Removed during 0.6.0 => 0.6.1

class LegacyODriveError(enum.IntFlag):
    NONE                                     = 0x00000000
    CONTROL_ITERATION_MISSED                 = 0x00000001
    DC_BUS_UNDER_VOLTAGE                     = 0x00000002
    DC_BUS_OVER_VOLTAGE                      = 0x00000004
    DC_BUS_OVER_REGEN_CURRENT                = 0x00000008
    DC_BUS_OVER_CURRENT                      = 0x00000010
    BRAKE_DEADTIME_VIOLATION                 = 0x00000020
    BRAKE_DUTY_CYCLE_NAN                     = 0x00000040
    INVALID_BRAKE_RESISTANCE                 = 0x00000080

class AxisError(enum.IntFlag):
    NONE                                     = 0x00000000
    INVALID_STATE                            = 0x00000001
    WATCHDOG_TIMER_EXPIRED                   = 0x00000800
    MIN_ENDSTOP_PRESSED                      = 0x00001000
    MAX_ENDSTOP_PRESSED                      = 0x00002000
    ESTOP_REQUESTED                          = 0x00004000
    HOMING_WITHOUT_ENDSTOP                   = 0x00020000
    OVER_TEMP                                = 0x00040000
    UNKNOWN_POSITION                         = 0x00080000

class MotorError(enum.IntFlag):
    NONE                                     = 0x00000000
    DRV_FAULT                                = 0x00000008
    CONTROL_DEADLINE_MISSED                  = 0x00000010
    MODULATION_MAGNITUDE                     = 0x00000080
    CURRENT_SENSE_SATURATION                 = 0x00000400
    CURRENT_LIMIT_VIOLATION                  = 0x00001000
    MODULATION_IS_NAN                        = 0x00010000
    MOTOR_THERMISTOR_OVER_TEMP               = 0x00020000
    FET_THERMISTOR_OVER_TEMP                 = 0x00040000
    TIMER_UPDATE_MISSED                      = 0x00080000
    CURRENT_MEASUREMENT_UNAVAILABLE          = 0x00100000
    CONTROLLER_FAILED                        = 0x00200000
    I_BUS_OUT_OF_RANGE                       = 0x00400000
    BRAKE_RESISTOR_DISARMED                  = 0x00800000
    SYSTEM_LEVEL                             = 0x01000000
    BAD_TIMING                               = 0x02000000
    UNKNOWN_PHASE_ESTIMATE                   = 0x04000000
    UNKNOWN_PHASE_VEL                        = 0x08000000
    UNKNOWN_TORQUE                           = 0x10000000
    UNKNOWN_CURRENT_COMMAND                  = 0x20000000
    UNKNOWN_CURRENT_MEASUREMENT              = 0x40000000
    UNKNOWN_VBUS_VOLTAGE                     = 0x80000000
    UNKNOWN_VOLTAGE_COMMAND                  = 0x100000000
    UNKNOWN_GAINS                            = 0x200000000
    CONTROLLER_INITIALIZING                  = 0x400000000

class SensorlessEstimatorError(enum.IntFlag):
    NONE                                     = 0x00000000
    UNSTABLE_GAIN                            = 0x00000001
    UNKNOWN_CURRENT_MEASUREMENT              = 0x00000002

# Removed during 0.5.4 => 0.6.0:

class EncoderMode(enum.IntEnum):
    INCREMENTAL                 = 0
    HALL                        = 1
    SINCOS                      = 2
    SPI_ABS_CUI                 = 256
    SPI_ABS_AMS                 = 257
    SPI_ABS_AEAT                = 258
    SPI_ABS_RLS                 = 259
    SPI_ABS_MA732               = 260

MotorError = _extend_enum(MotorError, {
    'PHASE_RESISTANCE_OUT_OF_RANGE': 0x00000001,
    'PHASE_INDUCTANCE_OUT_OF_RANGE': 0x00000002,
    'UNBALANCED_PHASES': 0x800000000
})

class ControllerError(enum.IntFlag):
    NONE                    = 0x00000000
    OVERSPEED               = 0x00000001
    INVALID_INPUT_MODE      = 0x00000002
    UNSTABLE_GAIN           = 0x00000004
    INVALID_MIRROR_AXIS     = 0x00000008
    INVALID_LOAD_ENCODER    = 0x00000010
    INVALID_ESTIMATE        = 0x00000020
    INVALID_CIRCULAR_RANGE  = 0x00000040
    SPINOUT_DETECTED        = 0x00000080

class EncoderError(enum.IntFlag):
    NONE                       = 0x00000000
    UNSTABLE_GAIN              = 0x00000001
    CPR_POLEPAIRS_MISMATCH     = 0x00000002
    NO_RESPONSE                = 0x00000004
    UNSUPPORTED_ENCODER_MODE   = 0x00000008
    ILLEGAL_HALL_STATE         = 0x00000010
    INDEX_NOT_FOUND_YET        = 0x00000020
    ABS_SPI_TIMEOUT            = 0x00000040
    ABS_SPI_COM_FAIL           = 0x00000080
    ABS_SPI_NOT_READY          = 0x00000100
    HALL_NOT_CALIBRATED_YET    = 0x00000200

# Enums in 0.5.2, 0.5.3 and 0.5.4 are identical

# Removed during 0.5.1 => 0.5.2:

AxisState = _extend_enum(AxisState, {
    'SENSORLESS_CONTROL': 5
})

class ThermistorCurrentLimiterError(enum.IntFlag):
    NONE    = 0x00000000
    OVER_TEMP = 0x00000001

AxisError = _extend_enum(AxisError, {
    'DC_BUS_UNDER_VOLTAGE': 0x00000002,
    'DC_BUS_OVER_VOLTAGE': 0x00000004,
    'CURRENT_MEASUREMENT_TIMEOUT': 0x00000008,
    'BRAKE_RESISTOR_DISARMED': 0x00000010,
    'MOTOR_DISARMED': 0x00000020,
    'MOTOR_FAILED': 0x00000040,
    'SENSORLESS_ESTIMATOR_FAILED': 0x00000080,
    'ENCODER_FAILED': 0x00000100,
    'CONTROLLER_FAILED': 0x00000200,
    'POS_CTRL_DURING_SENSORLESS': 0x00000400
})

class LockinState(enum.IntEnum):
    INACTIVE                    = 0
    RAMP                        = 1
    ACCELERATE                  = 2
    CONST_VEL                   = 3

MotorError = _extend_enum(MotorError, {
    'ADC_FAILED': 0x00000004,
    'NOT_IMPLEMENTED_MOTOR_TYPE': 0x00000020,
    'BRAKE_CURRENT_OUT_OF_RANGE': 0x00000040,
    'BRAKE_DEADTIME_VIOLATION': 0x00000100,
    'UNEXPECTED_TIMER_CALLBACK': 0x00000200,
    'BRAKE_DUTY_CYCLE_NAN': 0x00002000,
    'DC_BUS_OVER_REGEN_CURRENT': 0x00004000,
    'DC_BUS_OVER_CURRENT': 0x00008000
})

class ArmedState(enum.IntEnum):
    DISARMED                     = 0
    WAITING_FOR_TIMINGS          = 1
    WAITING_FOR_UPDATE           = 2
    ARMED                        = 3

class DrvFault(enum.IntFlag):
    NO_FAULT                       = 0x00000000
    FET_LOW_C_OVERCURRENT          = 0x00000001
    FET_HIGH_C_OVERCURRENT         = 0x00000002
    FET_LOW_B_OVERCURRENT          = 0x00000004
    FET_HIGH_B_OVERCURRENT         = 0x00000008
    FET_LOW_A_OVERCURRENT          = 0x00000010
    FET_HIGH_A_OVERCURRENT         = 0x00000020
    OVERTEMPERATURE_WARNING        = 0x00000040
    OVERTEMPERATURE_SHUTDOWN       = 0x00000080
    P_VDD_UNDERVOLTAGE             = 0x00000100
    G_VDD_UNDERVOLTAGE             = 0x00000200
    G_VDD_OVERVOLTAGE              = 0x00000400

# Changed during 0.5.1 => 0.5.2:
# PROTOCOL_SIMPLE                          = 0
# changed to
# PROTOCOL_SIMPLE                          = 0x00000001

# MotorError.ERROR_CURRENT_UNSTABLE renamed to MotorError.CURRENT_LIMIT_VIOLATION


def _load_legacy_names():
    """
    Loads legacy names for all enumerators.
    e.g. AxisState.IDLE => AXIS_STATE_IDLE

    This was introduced in odrive package version 0.6.0.

    This will be removed in future versions of the odrive package and is only
    included for a transition period until we have updated the legacy
    documentation.
    """
    import sys
    module = sys.modules[__name__]

    def to_macro_case(s):
        return ''.join([('_' + c) if c.isupper() else (c.upper()) for c in s]).lstrip('_')

    legacy_enum_names = [
        'StreamProtocolType',
        'Protocol',
        'AxisState',
        'ControlMode',
        'ComponentStatus',
        'ProcedureResult',
        'EncoderId',
        'SpiEncoderMode',
        'InputMode',
        'MotorType',
        'LegacyODriveError',
        'CanError',
        'AxisError',
        'MotorError',
        'SensorlessEstimatorError',
        'GpioMode',
        'EncoderError',
        'ControllerError',
        'ThermistorCurrentLimiterError',
        'LockinState',
        'EncoderMode',
        'ArmedState',
        'DrvFault',
    ]
    for var in legacy_enum_names:
        t = getattr(module, var)
        for item in t:
            setattr(module, ('LEGACY_ODRIVE_ERROR' if var == 'LegacyODriveError' else to_macro_case(var)) + '_' + item.name, item.value)

_load_legacy_names()
