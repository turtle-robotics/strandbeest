"""
Wrappers to allow for pythonic asynchronous usage of libodrive.Device objects.

`AsyncObject` wrappers are not thread-safe.
"""

from typing import List
from odrive.codecs import codecs
from odrive.libodrive import Device
from odrive.runtime_device import FunctionInfo, PropertyInfo, RuntimeDevice

class AsyncObject():
    __sealed__ = False

    def __init__(self, dev: RuntimeDevice, path: str):
        self._dev = dev
        self._path = path

    def __repr__(self) -> str:
        return f"AsyncObject({self._dev}, {self._path})"

    def __setattr__(self, key, value):
        if self.__sealed__:
            oldval = getattr(self, key, None)
            if isinstance(oldval, AsyncProperty):
                raise AttributeError(f"Property {key} cannot be assigned to directly. Try `await {key}.write(val)`.")
            elif oldval is not None:
                raise AttributeError(f"Attribute {key} cannot be overwritten.")
            else:
                raise AttributeError(f"Attribute {key} not found.")
        object.__setattr__(self, key, value)

    @staticmethod
    def from_json(device: RuntimeDevice, json: list, prefix: List[str] = []):
        generated_type = type('anonymous_interface', (AsyncObject,), {})
        obj = generated_type(device, '.'.join(prefix))

        for child in json:
            codec_name = child['type']
            if codec_name == 'json':
                pass # ignore first endpoint
            elif codec_name == 'function':
                func = AsyncFunction(device, FunctionInfo.from_json(child))
                setattr(obj, child['name'], func)
            elif codec_name == 'object':
                child_obj = AsyncObject.from_json(device, child['members'], prefix + [child['name']])
                setattr(obj, child['name'], child_obj)
            else:
                codec = codecs.get(child['type'], None)
                if codec is None:
                    raise Exception("unsupported codec {}".format(codec_name))
                setattr(obj, child['name'], AsyncProperty(device, PropertyInfo.from_json(child)))

        obj.__sealed__ = True
        return obj

class AsyncProperty():
    def __init__(self, device: RuntimeDevice, info: PropertyInfo):
        self._dev = device
        self._info = info

    def read(self):
        return self._dev.read(self._info)

    def write(self, val):
        return self._dev.write(self._info, val)

class AsyncFunction():
    def __init__(self, device: RuntimeDevice, info: FunctionInfo):
        self._dev = device
        self._info = info

    def __call__(self, *args):
        return self._dev.call_function(self._info, *args)

# TODO: move to RuntimeDevice and use same implementation for both AsyncObject
# and SyncObject
# This should build a list of endpoint IDs and then fetch all at once.
async def _dump_tree(obj: AsyncObject, indent="", depth=2):
    if obj._dev is None:
        return "[object lost]"

    try:
        if depth <= 0:
            return "{...}"
        lines = []
        for key in dir(obj):
            #class_member = getattr(obj.__class__, key, None)
            child = getattr(obj, key)
            if isinstance(child, AsyncProperty):
                val = await child.read()
                lines.append(indent + key + ": " + str(val) + " (" + child._info.codec_name + ")")
            elif isinstance(child, AsyncFunction):
                lines.append(indent + child._info.dump(key))
            elif isinstance(child, AsyncObject):
                subtree = await _dump_tree(child, indent + "  ", depth - 1)
                lines.append(indent + key + (": " if depth == 1 else ":\n") + subtree)
    except Exception as ex:
        return f"[failed to dump object: {ex}]"

    return "\n".join(lines)
