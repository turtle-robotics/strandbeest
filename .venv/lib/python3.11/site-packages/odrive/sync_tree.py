"""
Wrappers to allow for pythonic synchronous usage of libodrive.Device objects.

`SyncObject` objects are thread-safe, however if they are used on the same
thread as the associated event loop, the event loop must be re-entrant.
"""

import asyncio
from typing import List
from odrive._internal_utils import run_on_loop
from odrive.codecs import codecs
from odrive.runtime_device import FunctionInfo, PropertyInfo, RuntimeDevice
import odrive.async_tree

class SyncObject():
    __sealed__ = False

    def __init__(self, dev: RuntimeDevice, loop: asyncio.AbstractEventLoop, path: str):
        self._dev = dev
        self._loop = loop
        self._path = path

    def __setattr__(self, key, value):
        if self.__sealed__:
            # Prevent adding new attributes to the object if it's already sealed
            exists = (key in self.__class__.__dict__) or (key in self.__dict__)
            if not exists:
                raise AttributeError(f"Attribute {key} not found.")
        object.__setattr__(self, key, value)

    # TODO: use same implementation as AyncObject. See async_tree._dump_tree.
    def _dump(self, indent, depth):
        if self._dev is None:
            return "[object lost]"

        try:
            if depth <= 0:
                return "{...}"
            lines = []
            for key in dir(self):
                class_member = getattr(self.__class__, key, None)
                val = getattr(self, key)
                if isinstance(class_member, SyncPropertyAttribute):
                    lines.append(indent + key + ": " + str(val) + " (" + class_member._info.codec_name + ")")
                elif isinstance(val, SyncFunction):
                    lines.append(indent + val._info.dump(key))
                elif isinstance(val, SyncObject):
                    lines.append(indent + key + (": " if depth == 1 else ":\n") + val._dump(indent + "  ", depth - 1))
        except Exception as ex:
            return f"[failed to dump object: {ex}]"

        return "\n".join(lines)

    def __str__(self):
        return self._dump("", depth=2)

    def __repr__(self):
        return self.__str__()

    @staticmethod
    def from_json(device: RuntimeDevice, loop: asyncio.AbstractEventLoop, json: list, prefix: List[str] = []):
        type_attributes = {}

        for child in json:
            codec_name = child['type']
            if codec_name == 'json':
                continue # assigned on object rather than on type
            elif codec_name == 'function':
                continue # assigned on object rather than on type
            elif codec_name == 'object':
                continue # assigned on object rather than on type
            else:
                codec = codecs.get(child['type'], None)
                if codec is None:
                    raise Exception("unsupported codec {}".format(codec_name))
                type_attributes[child['name']] = SyncPropertyAttribute(PropertyInfo.from_json(child))

        generated_type = type('anonymous_interface', (SyncObject,), type_attributes)
        obj = generated_type(device, loop, '.'.join(prefix))

        for child in json:
            child_name = child['name']
            codec_name = child['type']
            if codec_name == 'json':
                continue # ignore first endpoint
            elif codec_name == 'function':
                val = SyncFunction(device, loop, FunctionInfo.from_json(child))
            elif codec_name == 'object':
                val = SyncObject.from_json(device, loop, child['members'], prefix + [child_name])
            else: # Endpoint is a property
                # Properties are encoded in the type itself, but we add an async
                # copy of the property for when the property itself is needed.
                val = odrive.async_tree.AsyncProperty(device, PropertyInfo.from_json(child))
                child_name = f"_{child_name}_property"
            setattr(obj, child_name, val)

        obj.__sealed__ = True
        return obj

class SyncPropertyAttribute(object):
    """
    Python attribute that allows access to an ODrive property using synchronous
    assignments.
    """
    def __init__(self, info: PropertyInfo):
        self._info = info

    def __get__(self, instance: SyncObject, owner):
        if not instance:
            return self
        return run_on_loop(instance._dev.read(self._info), loop=instance._loop)

    def __set__(self, instance, val):
        run_on_loop(instance._dev.write(self._info, val), loop=instance._loop)

class SyncFunction():
    def __init__(self, device: RuntimeDevice, loop: asyncio.AbstractEventLoop, info: FunctionInfo):
        self._dev = device
        self._loop = loop
        self._info = info

    def __call__(self, *args):
        return run_on_loop(self._dev.call_function(self._info, *args), loop=self._loop)
