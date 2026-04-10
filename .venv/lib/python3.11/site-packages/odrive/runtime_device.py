import asyncio
from dataclasses import dataclass
import json
import logging
import re
from typing import Any, Dict, List, Optional, Union, Tuple

from odrive.hw_version import HwVersion
from odrive.libodrive import Device
from odrive.codecs import StructCodec, codecs, encode_all, decode_all
import odrive.database

logger = logging.getLogger("odrive")

class NamedAttributeError(AttributeError):
    # 3.10 added a ``name`` and ``obj`` keyword arguments, but they are not
    # included in the message.
    def __init__(self, name: str, **kwargs):
        super().__init__(f"attribute {name} not found", **kwargs)

@dataclass
class PropertyInfo():
    endpoint_id: int
    codec: StructCodec
    codec_name: str # for printing
    writable: bool

    def from_json(json):
        return PropertyInfo(
            endpoint_id=json['id'],
            codec=codecs[json['type']],
            codec_name=json['type'],
            writable='w' in json['access']
        )

@dataclass
class FunctionInfo():
    endpoint_id: int
    inputs: List[Tuple[str, str, StructCodec]]
    outputs: List[Tuple[str, str, StructCodec]]

    def from_json(json):
        return FunctionInfo(
            endpoint_id=json['id'],
            inputs=[(c['name'], c['type'], codecs[c['type']]) for c in json['inputs']],
            outputs=[(c['name'], c['type'], codecs[c['type']]) for c in json['outputs']]
        )

    def dump(self, name):
        print_arglist = lambda arglist: ", ".join("{}: {}".format(arg_name, codec_name) for arg_name, codec_name, codec in arglist)
        return "{}({}){}".format(name,
            print_arglist(self.inputs),
            "" if len(self.outputs) == 0 else
            " -> " + print_arglist(self.outputs) if len(self.outputs) == 1 else
            " -> (" + print_arglist(self.outputs) + ")")

class RuntimeDevice:
    def __init__(self, device: Device, flat_json: Dict[str, Any], json_crc: int) -> None:
        self.device = device
        self.flat_json = flat_json
        self.json_crc = json_crc
        self.properties = {
            k: PropertyInfo.from_json(v)
            for k, v in flat_json.items() if v['type'] != 'json' and v['type'] != 'function'
        }
        self.functions = {
            k: FunctionInfo.from_json(v)
            for k, v in flat_json.items() if v['type'] == 'function'
        }
        self.serial_number = device.info.serial_number
        self.axes = sorted(list(set([name.split('.')[0] for name in flat_json.keys() if re.match(r"^axis[0-9]*\.", name)])))
        self.async_wrapper: odrive.async_tree.AsyncObject
        self.sync_wrapper: odrive.sync_tree.SyncObject

    def __repr__(self) -> str:
        return f"RuntimeDevice({self.serial_number})"

    async def attach_metadata(self):
        """
        Attaches the following metadata:
        board: HwVersion
        fw_version: (int, int, int)
        metadata: db info about this board
        """
        if self.has_property('hw_version_major') and self.has_property('hw_version_minor') and self.has_property('hw_version_variant'):
            self.board = HwVersion(
                await self.read('hw_version_major'),
                await self.read('hw_version_minor'),
                await self.read('hw_version_variant')
            )
        else:
            self.board = None
            print('Device has no hw_version properties')

        if self.has_property('fw_version_major') and self.has_property('fw_version_minor') and self.has_property('fw_version_revision'):
            self.fw_version = (
                await self.read('fw_version_major'),
                await self.read('fw_version_minor'),
                await self.read('fw_version_revision')
            )
        else:
            self.fw_version = None
            print('Device has no fw_version properties')

        build_id_short_int = await self.try_read('commit_hash', fallback=None)
        self.build_id_short = None if build_id_short_int is None else f"{build_id_short_int:08x}"

        try:
            self.metadata = None if self.board is None else odrive.database.instance.get_product(self.board)
        except odrive.database.NotFoundError:
            self.metadata = None

        if not self.metadata is None:
            self.axis_metadata = {
                name: self.metadata['inverters'][int(name[4:])]
                for name in self.axes
            }
        else:
            self.axis_metadata = {name: None for name in self.axes}

        self.verified = await self.try_read('otp_valid', fallback=True)

    @staticmethod
    def _flatten_json(prefix: List[str], nonflat: List[Any], result: Dict[str, Any]):
        for item in nonflat:
            path = [*prefix, item['name']]
            if item['type'] == 'object':
                RuntimeDevice._flatten_json(path, item['members'], result)
            else:
                result['.'.join(path)] = item

    @staticmethod
    async def from_device(device: Device):
        #print("connecting...")
        await device.connect()
        #print("getting json...")
        js_raw, json_crc = await device.get_json()
        js = json.loads(js_raw)
        flat_json = {}
        RuntimeDevice._flatten_json([], js, flat_json)
        #print("loading metadata...")

        runtime_device = RuntimeDevice(device, flat_json, json_crc)
        await runtime_device.attach_metadata()
        #print("loaded")

        sync_wrapper = odrive.sync_tree.SyncObject.from_json(runtime_device, asyncio.get_event_loop(), js)
        async_wrapper = odrive.async_tree.AsyncObject.from_json(runtime_device, js)
        runtime_device.sync_wrapper = sync_wrapper
        runtime_device.async_wrapper = async_wrapper

        return runtime_device, sync_wrapper, async_wrapper

    def has_property(self, property: str):
        return property in self.properties

    def try_get_prop_info(self, property: str) -> Optional[PropertyInfo]:
        prop_info = self.properties.get(property, None)
        if prop_info is None:
            raise Exception(f"property {property} not found")
        return prop_info

    def get_prop_info(self, property: str, codec_name: str) -> Optional[PropertyInfo]:
        prop_info = self.properties.get(property, None)
        if prop_info is None or prop_info.codec_name != codec_name:
            return None
        return prop_info

    def has_function(self, func: str):
        return func in self.functions

    async def read(self, property: Union[str, PropertyInfo]):
        if isinstance(property, str):
            prop_info = self.properties.get(property, None)
            if prop_info is None:
                raise AttributeError(f"{getattr(self, '__name__', 'device')} has no property '{property}'")
        else:
            prop_info = property

        buf = await self.device.read_endpoints([prop_info.endpoint_id], [prop_info.codec.size])
        return decode_all([prop_info.codec], buf, self)[0]

    async def read_multiple(self, properties: List[Union[str, PropertyInfo]]):
        if len(properties) == 0:
            return []

        def get_prop(p: Union[str, PropertyInfo]):
            if isinstance(p, str):
                prop_info = self.properties.get(p, None)
                if prop_info is None:
                    raise NamedAttributeError(name=p)
                return prop_info
            elif isinstance(p, PropertyInfo):
                return p
            else:
                raise TypeError()

        prop_infos = [get_prop(p) for p in properties]
        buf = await self.device.read_endpoints([p.endpoint_id for p in prop_infos], [p.codec.size for p in prop_infos])
        return decode_all([p.codec for p in prop_infos], buf, self)

    async def call_function(self, func: Union[str, FunctionInfo], *args):
        if isinstance(func, str):
            func_info = self.functions.get(func, None)
            if func_info is None:
                raise NamedAttributeError(name=func)
        else:
            func_info = func

        if len(args) != len(func_info.inputs):
            raise ValueError(f"expected {len(func_info.inputs)} arguments but got {len(args)}")
        
        results = await self.device.call_function(
            func_info.endpoint_id,
            '<' + ''.join(c.struct_format for _, __, c in func_info.inputs),
            '<' + ''.join(c.struct_format for _, __, c in func_info.outputs),
            args
        )
        n_out = len(func_info.outputs) 
        return None if n_out == 0 else results[0] if n_out == 1 else results

    async def write(self, property: Union[str, PropertyInfo], val):
        if isinstance(property, str):
            prop_info = self.properties.get(property, None)
            if prop_info is None:
                raise NamedAttributeError(name=property)
        else:
            prop_info = property

        if not prop_info.writable:
            raise AttributeError("This property cannot be written to.")

        buf = encode_all([prop_info.codec], [val])
        await self.device.write_endpoints([prop_info.endpoint_id], [prop_info.codec.size], buf)

    async def try_read(self, property: str, fallback):
        prop_info = self.properties.get(property, None)
        if prop_info is None:
            return fallback
        return await self.read(prop_info)

    async def try_read_multiple(self, properties: List[str], fallback: List):
        assert len(properties) == len(fallback)
        prop_infos = [self.properties.get(p, None) for p in properties]

        non_null_prop_infos = [(i, p) for i, p in enumerate(prop_infos) if not p is None]
        non_null_results = await self.read_multiple([p for _, p in non_null_prop_infos])

        results = list(fallback)
        for i, (original_idx, _) in enumerate(non_null_prop_infos):
            results[original_idx] = non_null_results[i]
        return results
    
    def id_to_property(self, id: int):
        for p in self.properties.values():
            if p.endpoint_id == id:
                return odrive.async_tree.AsyncProperty(self, p)
        raise Exception(f"property ID {id} not found")

    def path_of(self, prop_info: PropertyInfo):
        for n, p in self.properties.items():
            if p == prop_info:
                return n
        raise Exception(f"{prop_info} not found")

    def sync_to_async(self, obj: 'odrive.sync_tree.SyncObject'):
        path = obj._path.split('.')
        result = self.async_wrapper
        for p in path:
            result = getattr(result, p)
        return result

    def get_async_property(self, name: str):
        return odrive.async_tree.AsyncProperty(self, self.properties[name])

# Must be at the end to avoid cyclic import
import odrive.async_tree
import odrive.sync_tree
