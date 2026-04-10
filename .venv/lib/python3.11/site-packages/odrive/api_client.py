import datetime
import json
import os
from typing import Union

import odrive.crypto as crypto
from odrive.crypto import b64encode, b64decode

API_BASE_ADDR = 'https://api.odriverobotics.com'

class ApiClient():
    def __init__(self, session, api_base_addr: str = API_BASE_ADDR, key: Union[str, bytes, None] = None):
        self._session = session
        self._api_base_addr = api_base_addr
        if key is None and 'ODRIVE_API_KEY' in os.environ:
            key = os.environ['ODRIVE_API_KEY']
        self._key = None if key is None else crypto.load_private_key(key if isinstance(key, bytes) else b64decode(key))

    async def call(self, method: str, endpoint: str, inputs=None):
        url = self._api_base_addr + endpoint
        content = json.dumps(inputs or {}).encode('utf-8')
        headers = {
            'content-type': 'application/json; charset=utf-8'
        }

        if not self._key is None:
            url_bytes = endpoint.encode('utf-8')
            timestamp_bytes = int(datetime.datetime.now().timestamp()).to_bytes(8, 'little', signed=False)
            message = url_bytes + b':' + timestamp_bytes + b':' + content
            signature = crypto.sign(self._key, message)
            headers['Authorization'] = 'hmacauth ' + ':'.join([
                b64encode(crypto.get_public_bytes(self._key.public_key())),
                b64encode(timestamp_bytes),
                b64encode(signature)
            ])

        async with self._session.request(method, url, headers=headers, data=content, ) as response:
            if response.status != 200:
                try:
                    ex_data = await response.json()
                except:
                    ex_raw = await response.read()
                    raise Exception(f"Server failed with {response.status} ({response.reason}): {ex_raw}")
                else:
                    tb = ''.join(ex_data['traceback'])
                    raise Exception(f"Server side traceback:\n{tb}\nServer failed with {response.status} ({response.reason}): {ex_data['message']}")

            return await response.json()

    async def download(self, url: str):
        async with self._session.get(url) as response:
            if response.status != 200:
                raise Exception(f"Server failed with {response.status} ({response.reason})")
            return await response.read()
