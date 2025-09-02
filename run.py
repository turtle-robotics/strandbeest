#!/usr/bin/env python3
#import statements
import odrive
from odrive.enums import *

import logging
import time

import threading

import os

import pygame

from math import copysign, sqrt

# logging.basicConfig(level=logging.NOTSET)

enabled = False
controller_connected = False
x_axis = 0
y_axis = 0

vel_scale = 100

#controller deadzones
def dead_band(left, right, left_dead, right_dead):
    if abs(left) <= left_dead:
        left = 0
    if abs(right) <= right_dead:
        right = 0

    return (left, right)

def scale(x):
    return copysign(sqrt(abs(x)), x)

# def drive(odrv0, x_axis, y_axis):
def drive_0(odrv0):
    drive_axis(odrv0.axis0, 0)
    drive_axis(odrv0.axis1, 0)

def drive(odrv0):
    global x_axis
    global y_axis
    left = copysign(min(abs(y_axis - x_axis), 1.0), y_axis - x_axis)
    right = copysign(min(abs(y_axis + x_axis), 1.0), y_axis + x_axis)
    left, right = dead_band(left, right, 0.01, 0.01)
    # if not enabled or not controller_connected:
    #     left = 0
    #     right = 0

    print("X_AXIS ", x_axis)
    print("Y_AXIS ", y_axis)
    drive_axis(odrv0.axis0, right)
    drive_axis(odrv0.axis1, -1 * left)
    print("DRIVE RIGHT ", right)
    print("DRIVE LEFT ", -1 * left)


def drive_axis(axis, val):
    if abs(val) < 0.001:
        # print("IDLE")
        axis.requested_state = 1
        axis.config.general_lockin.ramp_distance = 0
    else:
        axis.config.general_lockin.vel = vel_scale * scale(val)
        axis.requested_state = 9
        axis.config.general_lockin.ramp_distance = -1

def config_axis(axis):
    axis.config.general_lockin.accel = 700
    axis.config.general_lockin.ramp_time = 0.05
    axis.config.general_lockin.vel = 0
    axis.config.general_lockin.ramp_distance = 0

    axis.requested_state = 9

pygame.init()
pygame.joystick.init()


js1 = None

try:
    js1 = pygame.joystick.Joystick(int(os.environ.get('CRONCH', '0')))
    js1.init()
    print('joystick connected: ' + str(js1.get_name()))
except:
    pass


def get_joy():
    pygame.event.pump()
    x_axis = js1.get_axis(2) # right stick x
    y_axis = js1.get_axis(1) # left stick y

    estop = js1.get_button(0)

    return (x_axis, y_axis, estop)


if __name__ == '__main__':
    odrv0 = odrive.find_any()
    odrv0.clear_errors() # could possibly be bad

    config_axis(odrv0.axis0)
    config_axis(odrv0.axis1)


    t0 = 1000 * time.monotonic()
    while True:
        t1 = 1000 * time.monotonic()

        # drive(odrv0, x_axis, y_axis)
        if enabled:
            drive(odrv0)
        else:
            drive_0(odrv0)

        # time.sleep(0.001 * max(0, 20-(t1-t0)))
        time.sleep(0.05)

        t0 = t1
