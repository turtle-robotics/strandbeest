#!/usr/bin/env python3

import odrive
from odrive.enums import *

import logging
import time

import threading

import os

from math import copysign, sqrt

import asyncio
import websockets

# logging.basicConfig(level=logging.NOTSET)

addr = os.environ.get('ADDR', 'lt6.local')
port = int(os.environ.get('PORT', '8000'))

enabled = False
controller_connected = False
x_axis = 0
y_axis = 0

vel_scale = 100

def diag_data():
    # volt = odrv0.vbus_voltage
    # l_vel = odrv0.axis0.encoder.vel_estimate
    # r_vel = odrv0.axis1.encoder.vel_estimate
    # return f'{volt}:{l_vel}:{r_vel}'
    return ''

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


async def phandler(websocket):
    while True:
        data = diag_data()
        await websocket.send(data)
        #resp = await websocket.recv()
        #print(resp)
        await asyncio.sleep(200/1000)

async def chandler(websocket):
    global x_axis
    global y_axis
    global enabled
    while True:
        resp = await websocket.recv()
        print(resp)
        vals = resp.split(':')
        enabled = (vals[0] == 'True')
        controller_connected = (vals[0] == 'True')
        x_axis = float(vals[2])
        y_axis = float(vals[3])
        await asyncio.sleep(20/1000)

async def handler(websocket):
    await asyncio.gather(
        chandler(websocket),
        phandler(websocket),
    )


async def start_server():
    async with websockets.serve(handler, addr, port):
        await asyncio.Future()


async def idk():
    await asyncio.gather(start_server())


def async_main():
    asyncio.run(idk())


th = threading.Thread(target=async_main)
th.start()

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
