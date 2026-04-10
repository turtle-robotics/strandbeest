import struct
from typing import List
import odrive.async_tree

class StructCodec():
    def __init__(self, struct_format, target_type):
        self.struct_format = struct_format
        self.target_type = target_type
        self.size = struct.calcsize(self.struct_format)

    def to_wire(self, val):
        return self.target_type(val)

    def from_wire(self, val, device):
        return val

class ObjectPtrCodec(StructCodec):
    def __init__(self):
        super().__init__('I', int)

    def to_wire(self, value):
        if value is None:
            return 0
        elif isinstance(value, odrive.async_tree.AsyncProperty):
            return value._info.endpoint_id | (value._dev.json_crc << 16)
        else:
            raise TypeError("Expected value of type AsyncProperty or None but got '{}'. An example for a RemoteObject is this expression: odrv0.axis0.controller._input_pos_property".format(type(value).__name__))

    def from_wire(self, value, device: 'odrive.runtime_device.RuntimeDevice'):
        return None if value == 0 else device.id_to_property(value & 0xffff)

codecs = {
    'int8': StructCodec("b", int),
    'uint8': StructCodec("B", int),
    'int16': StructCodec("h", int),
    'uint16': StructCodec("H", int),
    'int32': StructCodec("i", int),
    'uint32': StructCodec("I", int),
    'int64': StructCodec("q", int),
    'uint64': StructCodec("Q", int),
    'bool': StructCodec("?", bool),
    'float': StructCodec("f", float),
    'endpoint_ref': ObjectPtrCodec(),
}

def encode_all(codecs: List[StructCodec], vals: List):
    assert len(codecs) == len(vals)
    vals = [codec.to_wire(val) for codec, val in zip(codecs, vals)]
    fmt = '<' + ''.join(c.struct_format for c in codecs)
    return struct.pack(fmt, *vals)

def decode_all(codecs: List[StructCodec], buf: bytes, device: 'odrive.runtime_device.RuntimeDevice') -> tuple:
    fmt = '<' + ''.join(c.struct_format for c in codecs)
    vals = struct.unpack(fmt, buf)
    assert len(codecs) == len(vals)
    return tuple(codec.from_wire(val, device) for codec, val in zip(codecs, vals))

import odrive.runtime_device
