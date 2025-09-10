#!/usr/bin/env python3

import string
import asyncio
import pygame
import pygame_gui
import websockets
import time
import threading
import logging
from multiprocessing import Process


# from turbojpeg import TurboJPEG, TJPF_GRAY, TJSAMP_GRAY, TJFLAG_PROGRESSIVE, TJFLAG_FASTUPSAMPLE, TJFLAG_FASTDCT
# import cv2
# import numpy as np
import os



pygame.init()
pygame.joystick.init()

pygame.display.set_caption('Quick Start')
window_surface = pygame.display.set_mode((800, 600))

background = pygame.Surface((800, 600))
background.fill(pygame.Color('#000000'))

manager = pygame_gui.UIManager((800, 600))

left_pad = 25

enable_button = pygame_gui.elements.UIButton(relative_rect=pygame.Rect((left_pad, 75), (100, 50)),
                                            text='ENABLE',
                                            manager=manager)

disable_button = pygame_gui.elements.UIButton(relative_rect=pygame.Rect((left_pad, 125), (100, 50)),
                                            text='DISABLE',
                                            manager=manager)

addr_entry = pygame_gui.elements.ui_text_entry_line.UITextEntryLine(relative_rect=pygame.Rect((left_pad, 175), (100, 50)), manager=manager)
addr_entry.set_allowed_characters([*(string.ascii_lowercase + string.digits + '.')])

connect_button = pygame_gui.elements.UIButton(relative_rect=pygame.Rect((left_pad + 100, 175), (100, 50)), text='CONNECT', manager=manager)

status_line = 'status: {}\nping: {}\ncontroller status: {}'
status_box = pygame_gui.elements.ui_text_box.UITextBox(relative_rect=pygame.Rect((left_pad, 250), (300, 100)), html_text=status_line.format('not connected', 'N/A', 'not connected'), manager=manager)

console_box = pygame_gui.elements.ui_text_box.UITextBox(relative_rect=pygame.Rect((400, 100), (350, 400)), html_text='', manager=manager)

clock = pygame.time.Clock()

class LogStream(object):
    def __init__(self):
        self.logs = ''

    def write(self, str):
        console_box.append_html_text(str)
        self.logs += str

    def flush(self):
        pass

    def __str__(self):
        return self.logs

log_stream = LogStream()
logging.basicConfig(stream=log_stream, level=logging.INFO)

port = int(os.environ.get('PORT', '8000'))

addr = '127.0.0.1'


enabled = False

connected = False
controller_connected = True

js1 = None

try:
    js1 = pygame.joystick.Joystick(int(os.environ.get('CRONCH', '0')))
    js1.init()
    logging.info('joystick connected: ' + str(js1.get_name()))
except:
    pass

def format_status():
    str1 = 'connected' if connected else 'not connected'
    str2 = 'N/A'
    str3 = 'connected' if controller_connected else 'not connected'
    return status_line.format(str1, str2, str3)

async def get_joy():
    pygame.event.pump()
    x_axis = js1.get_axis(3) # right stick x
    y_axis = js1.get_axis(1) # left stick y

    estop = js1.get_button(0)

    return (x_axis, y_axis, estop)

def format_ws_data(x_axis, y_axis):
    return '{enabled}:{controller_connected}:{x_axis}:{y_axis}'.format(enabled=enabled, controller_connected=True, x_axis=x_axis, y_axis=y_axis)

async def async_send(websocket):
    global controller_connected

    while True:
        x_axis, y_axis = (0, 0)
        if controller_connected:
            x_axis, y_axis, estop = await get_joy()

        ws_data = format_ws_data(x_axis, y_axis)
        # print("WS_DATA: ", ws_data)

        await websocket.send(ws_data)
        await asyncio.sleep(60/1000)

async def async_recv(websocket):
    while True:
        response = await websocket.recv()
        logging.debug('response ' + response)

        await asyncio.sleep(200/1000)

async def test():
    async for websocket in websockets.connect('ws://' + addr + ':' + str(port), max_queue=1024):
        try:
            connected = True
            await asyncio.gather(async_recv(websocket), async_send(websocket))
        except websockets.ConnectionClosed:
            connected = False
            break


if __name__ == '__main__':
    is_running = True

    disable_button.disable()

    p = threading.Thread(target=lambda: asyncio.run(test()))
    p.start()

    while is_running:
        time_delta = clock.tick(60) / 1000.0

        status_box.html_text = format_status()

        if not controller_connected and pygame.joystick.get_count() != 0:
            js1 = pygame.joystick.Joystick(int(os.environ.get('CRONCH', '0')))
            js1.init()
            logging.info('joystick connected: ' + str(js1.get_name()))
            controller_connected = True

        if controller_connected and pygame.joystick.get_count() == 0:
            controller_connected = False

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                is_running = False


            if event.type == pygame_gui.UI_BUTTON_PRESSED:
                if event.ui_element == enable_button and not enabled:
                    logging.info('Enabling')
                    enabled = True
                    enable_button.disable()
                    disable_button.enable()

                if event.ui_element == disable_button and enabled:
                    logging.info('Disabling')
                    enabled = False
                    disable_button.disable()
                    enable_button.enable()

                if event.ui_element == connect_button:
                    addr = addr_entry.get_text()
                    logging.info('Setting addr to {}'.format(addr))
                    logging.info('Restarting connection')
                    #p.kill()
                    p = threading.Thread(target=lambda: asyncio.run(test()))
                    p.start()


            if event.type == pygame.KEYDOWN:
                if not enabled and pygame.key.get_pressed()[pygame.K_BACKSLASH] and pygame.key.get_pressed()[pygame.K_LEFTBRACKET] and pygame.key.get_pressed()[pygame.K_RIGHTBRACKET]:
                    logging.info('Enabling')
                    enabled = True
                    enable_button.disable()
                    disable_button.enable()
                if event.key == pygame.K_SPACE and enabled:
                    logging.info('Disabling')
                    enabled = False
                    enable_button.enable()
                    disable_button.disable()
                if event.key == pygame.K_q:
                    is_running = False


            manager.process_events(event)

        manager.update(time_delta)

        window_surface.blit(background, (0, 0))
        manager.draw_ui(window_surface)

        pygame.display.update()

    os._exit(0)
