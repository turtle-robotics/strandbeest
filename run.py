#!/usr/bin/env python3

#import statements
import odrive
from odrive.enums import *

import logging
import time

import threading

import os

import pygame
import RPi.GPIO as GPIO

from math import copysign, sqrt

# logging.basicConfig(level=logging.NOTSET)
# install sudo apt-get install python3-rpi.gpio on pi
enabled = True
controller_connected = False
x_axis = 0
y_axis = 0

vel_scale = 100

#jaw angle
current_angle = 90

# Servo pin setup (BCM mode)
SERVO_PIN = 26  # Use any PWM-capable GPIO pin, like 12, 13, 18, or 19
#try 18 first then 12 if 18 does not work

GPIO.setmode(GPIO.BCM)
GPIO.setup(SERVO_PIN, GPIO.OUT)

# 50Hz PWM frequency for SG90
pwm = GPIO.PWM(SERVO_PIN, 50)
pwm.start(7.5)



#cleanup command for GPIO pins
def cleanup():
    pwm.stop()
    GPIO.cleanup()
    print("GPIO cleaned up. Exiting.")

# Helper function to convert angle (0-180) to duty cycle
def angle_to_duty_cycle(angle):
    return 2.5 + (angle / 18.0)  # Rough mapping for SG90

def dead_band(left, right, left_dead, right_dead):
    if abs(left) <= left_dead:
        left = 0
    if abs(right) <= right_dead:
        right = 0

    return (left, right)

def scale(x):
    return copysign(sqrt(abs(x)), x)

def move_head(step=1, min_angle=0):
    pwm.start(50)
    time.sleep(1)

def move_head1(step=1, min_angle=0):
    global current_angle

    if current_angle - step >= min_angle:
        current_angle -= step
    else:
        current_angle = min_angle
    print("Head is moving")
    duty = angle_to_duty_cycle(current_angle)
    print("Duty: ", duty)
    pwm.ChangeDutyCycle(duty)
    try:
        time.sleep(0.1)  # Let the servo move
        pwm.ChangeDutyCycle(0)  # Avoid jitter
    except:
        print("pwm fail")




# def drive(odrv0, x_axis, y_axis):
def drive_0(odrv0):
    drive_axis(odrv0.axis0, 0)
    drive_axis(odrv0.axis1, 0)

#drive function
def drive(odrv0):
    global x_axis
    global y_axis
    left = copysign(min(abs(y_axis - x_axis), 1.0), y_axis - x_axis)
    right = copysign(min(abs(y_axis + x_axis), 1.0), y_axis + x_axis)
    left, right = dead_band(left, right, 0.01, 0.01)
    # if not enabled or not controller_connected:
    #     left = 0
    #     right = 0

    #print("X_AXIS ", x_axis)
    #print("Y_AXIS ", y_axis)
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

#try again (y/n)
#while loop for checking controller connection (INVESTIGATE THIS AS POSSIBLE CAUSE FOR CONTROLLER PROBLEM)
while (not controller_connected):
    try:
        js1 = pygame.joystick.Joystick(int(os.environ.get('CRONCH', '0')))
        js1.init()
        print('controller connected: ' + str(js1.get_name()))
        controller_connected = True
    except:
        print('No controller found')
        continue


def get_joy():
    #check for button press and update global "head" variable (default false)
    head = False
    print("reset")
    for event in pygame.event.get():
        if (event.type == pygame.JOYBUTTONDOWN):
            head = True
            #delete later
            print("Head button pressed")
        #delete later (just to check for joystick button capability)
    pygame.event.pump()
    x_axis = js1.get_axis(2) # right stick x
    y_axis = js1.get_axis(1) # left stick y

    estop = js1.get_button(0)

    return (x_axis, y_axis, estop, head)


if __name__ == '__main__':
    #check odrive connections
    try:
        odrv0 = odrive.find_any()
        print("Odrive Found")
    except:
        print("No odrive found :(")
    #check odrive errors
    try:
        odrv0.clear_errors() # could possibly be bad
        print("No errors Found :)")
    except:
        print("Error found :(")
        odrv0.dump_errors()

    config_axis(odrv0.axis0)
    config_axis(odrv0.axis1)

    #print(odrv0)

    #check time delays later good for now
    t0 = 1000 * time.monotonic()
    while True:
        x_axis, y_axis, estop, head = get_joy()
        t1 = 1000 * time.monotonic()

        # drive(odrv0, x_axis, y_axis)
        if enabled:
            if head:
                move_head(step = 5)
            drive(odrv0)
        else:
            drive_0(odrv0)

        # time.sleep(0.001 * max(0, 20-(t1-t0)))
        time.sleep(0.05)

        t0 = t1
    #cleans up GPIO pins on exit
    cleanup()



#exit 
