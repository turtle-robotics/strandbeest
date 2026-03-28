#!/usr/bin/env python3

#import statements
import odrive
from odrive.enums import *
from odrive.utils import dump_errors #added this - lorenzo 3/27

import logging
import time

import threading

import os

import numpy as np
import sounddevice as sd
#print(sd.query_devices())

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
    #servo cannot rotate a full 180, so we go based on the duty cycle
    # angle / 18.0 + 2.5 - original code
    return 2.5 + (angle / 18.0) # Rough mapping for SG90
        

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
        axis.requested_state = 1 #idle state
        axis.config.general_lockin.ramp_distance = 0
    else:
        axis.config.general_lockin.vel = vel_scale * scale(val)
        # requested_state = 3 = motor configuration; 4 = encoder configuration
        # 9 = commands motor to enter axis_state_closed_loop_control state
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

while not controller_connected:
    try:
        #refresh joystick detection each time through the loop
        pygame.joystick.quit()
        pygame.joystick.init()
        
        jcount = pygame.joystick.get_count()
        if jcount > 0:
            js1 = pygame.joystick.Joystick(0) #first joystick
            js1.init()
            print('controller connected: ' + str(js1.get_name()))
            controller_connected = True
        else:
            print('No controller found, retrying...')
    except Exception as e:
        print('Error checking controller:', e)
    time.sleep(1) #wait 1 second before retrying

"""
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
        continue"""

#this code is for head movement
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
    # initial print statements
    print("ROBOT CONTROL STARTING")
    print("-" * 40) # barrier
    #check odrive connections
    try:
        print("Searching for ODrive...")
        odrv0 = odrive.find_any()
        print("Odrive Found")
        print("Serial Number:", odrv0.serial_number)
        print("Firmware version:", odrv0.fw_version_major, ".", odrv0.fw_version_minor)
    except:
        print("No odrive found :(")
        # might add this just to see what happens
        # cleanup()
        # exit(1)
    #check odrive errors
    # check for existing errors before clearing
        print("\nChecking for existing errors...")
        print("Axis 0 error:", hex(odrv0.axis0.error))
        print("Axis 1 error:", hex(odrv0.axis1.error))
        # if errors, show details
        if (odrv0.axis.error !=0):
            print("Axis 0 error details")
            dump_errors(odrv0) #had to change this for debug, will fix later. dump_errors(odrv0) doesnt take an axis as an object. lorenzo - 3/27
        if (odrv0.axis.error !=0):
            print("Axis 1 error details")
            dump_errors(odrv0) #had to change this for debug, will fix later. dump_errors(odrv0) doesnt take an axis as an object. lorenzo - 3/27

    #added the above stuff ^^
    try:
        odrv0.clear_errors() # could possibly be bad
        print("No errors Found :)")
    except:
        print("Error found :(")
        dump_errors(odrv0) #had to change this for debug, will fix later. lorenzo - 3/27

    # added this config stuff
    config_axis(odrv0.axis0)
    config_axis(odrv0.axis1)

    print("\nConfiguration:")
    print("Bus Voltage:", odrv0.vbus_voltage, "V")
    print("Axis 0 Current Limit:", odrv0.axis0.motor.config.current_lim, "A")
    print("Axis 1 Current Limit:", odrv0.axis1.motor.config.current_lim, "A")
    print("Velocity Scale:", vel_scale)
    print("Acceleration:", odrv0.axis0.config.general_lockin.accel)
    print("\nStarting main loop.....")

    #print(odrv0)

    # added this
    loop_count = 0
    last_error_check = time.time()
    last_status_print = time.time()
    error_count = 0

    #check time delays later good for now
    t0 = 1000 * time.monotonic()

    #added this try, except except, finally
    try:
        while True:
            #added this
            loop_count += 1
            current_time = time.time()

            x_axis, y_axis, estop, head = get_joy()
            t1 = 1000 * time.monotonic()

            # added this: print status every 3 seconds
            if current_time - last_status_print > 3.0:
                print("Status -> Loop:", loop_count, "| Voltage:", odrv0.vbus_voltage,
                  "|Errors:", error_count)
                last_status_print = current_time
            # added this: checks for errors every 0.5 sec
            if current_time - last_error_check > 0.5:
                axis0_err = odrv0.axis0.error
                axis1_err = odrv0.axis1.error
                if axis0_err != 0 or axis1_err != 0:
                    error_count += 1
                    print("\nError detected at", time.strftime('%H:%M:%S'))
                    print("\n")
                    if axis0_err != 0:
                        print("\nAXIS 0 ERROR")
                        print("Error Code:", hex(axis0_err))
                        print("Motor Error:", hex(odrv0.axis0.motor.error))
                        print("Encoder Error:", hex(odrv0.axis0.encoder.error))
                        print("Current State:", odrv0.axis0.current_state)
                        print("Requested Velocity:", odrv0.axis0.config.general_lockin.vel)
                        print("Bus Voltage:", odrv0.vbus_voltage, "V")

                        # added this - decoding common errors
                        if axis0_err & 0x00000008:
                            print("  -> MISSING_ESTIMATE (LOCKIN lost sync)")
                        if axis0_err & 0x00000800:
                            print("  -> CURRENT_LIMIT_VIOLATION")
                        if axis0_err & 0x00000200:
                            print("  -> DC_BUS_OVER_CURRENT")
                        if axis0_err & 0x00000100:
                            print("  -> DC_BUS_UNDER_VOLTAGE")
                        if axis0_err & 0x00004000:
                            print("  -> VELOCITY_LIMIT_VIOLATION")
                        
                        print("\nFull error dump:")
                        dump_errors(odrv0) #had to change this for debug, will fix later. dump_errors(odrv0) doesnt take an axis as an object. lorenzo - 3/27
                    if axis1_err != 0:
                        print("\nAXIS 1 ERROR")
                        print("Error Code:", hex(axis1_err))
                        print("Motor Error:", hex(odrv0.axis1.motor.error))
                        print("Encoder Error:", hex(odrv0.axis1.encoder.error))
                        print("Current State:", odrv0.axis1.current_state)
                        print("Requested Velocity:", odrv0.axis1.config.general_lockin.vel)
                        print("Bus Voltage:", odrv0.vbus_voltage, "V")
                        
                        # Decode common errors
                        if axis1_err & 0x00000008:
                            print("  -> MISSING_ESTIMATE (LOCKIN lost sync)")
                        if axis1_err & 0x00000800:
                            print("  -> CURRENT_LIMIT_VIOLATION")
                        if axis1_err & 0x00000200:
                            print("  -> DC_BUS_OVER_CURRENT")
                        if axis1_err & 0x00000100:
                            print("  -> DC_BUS_UNDER_VOLTAGE")
                        if axis1_err & 0x00004000:
                            print("  -> VELOCITY_LIMIT_VIOLATION")
                        
                        print("\nFull error dump:")
                        dump_errors(odrv0) #had to change this for debug, will fix later. dump_errors(odrv0) doesnt take an axis as an object. lorenzo - 3/27
                        # added this too
                        print("Clearing errors and continuing...")

                        # stop motors before clearing
                        drive_0(odrv0)
                        time.sleep(0.2)
                        odrv0.clear_errors()
                        config_axis(odrv0.axis0)
                        config_axis(odrv0.axis1)
                    last_error_check = current_time
            # drive(odrv0, x_axis, y_axis)
            if enabled:
                if head:
                    # wrong head? change to head1 if it persists
                    move_head(step = 5)
                drive(odrv0)
            else:
                drive_0(odrv0)

            # time.sleep(0.001 * max(0, 20-(t1-t0)))
            time.sleep(0.05)

            t0 = t1
    #added all this
    except KeyboardInterrupt:
        print("\n\nCtrl C pressed - shutting down")
        print("Total errors enountered:", error_count)
    except Exception as e:
        print("\n\nFatal error", e)
        import traceback
        traceback.print_exc()
    finally:
        print("\nStopping motors...")
        drive_0(odrv0)
        time.sleep(0.1)
        #cleans up GPIO pins on exit - kept
        cleanup()
        print("Shutdown complete")






#exit 
