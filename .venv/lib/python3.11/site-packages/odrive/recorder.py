
import asyncio
from dataclasses import dataclass
import functools
import math
import time
import traceback
from typing import Callable, List, Optional, Tuple

import numpy as np
import numpy.ma as ma
from odrive.device_manager import DeviceManager, Subscription
from odrive.libodrive import DeviceLostException, DiscoveryDelegate
from odrive.runtime_device import PropertyInfo, RuntimeDevice

MAX_HISTORY_AGE = 10 * 60 # [s]
AUTO_PRUNE_INTERVAL = 10 # [s]

_codecs = {
    'int8': np.int8,
    'uint8': np.uint8,
    'int16': np.int16,
    'uint16': np.uint16,
    'int32': np.int32,
    'uint32': np.uint32,
    'int64': np.int64,
    'uint64': np.uint64,
    'bool': np.bool_,
    'float': np.float32,
}

async def _noop_fetcher(frame):
    pass

@dataclass
class _RecorderForDevice():
    serial_number: str
    properties: Tuple[str, str] # name, codec_name
    dt: np.dtype
    data: ma.masked_array
    fetcher: Callable
    active_fetch_task: Optional[asyncio.Task] = None

    @staticmethod
    def from_specs(serial_number: str, properties):
        assert isinstance(serial_number, str)
        dt = np.dtype(
            [('timestamp', 'uint64')] +
            [(name, _codecs[codec_name]) for name, codec_name in properties]
        )
        return _RecorderForDevice(
            serial_number=serial_number,
            properties=properties,
            dt=dt,
            data=ma.zeros(0, dtype=dt),
            fetcher=_noop_fetcher
        )

    async def _fetch(self, dev: RuntimeDevice, indices: List[int], props: List[PropertyInfo], timestamp: float):
        frame = ma.masked_all(1, dtype=self.dt)
        frame0 = frame[0]
        frame0[0] = timestamp

        try:
            vals = await dev.read_multiple(props)
            for i, val in enumerate(vals):
                frame0[indices[i]] = val
            self.data = ma.concatenate([self.data, frame])
        except DeviceLostException:
            pass # This should only happen once, after that the fetcher is replaced by _noop_fetcher

    def get_data(self, since: float) -> ma.masked_array:
        start_index = self.index_of_time(since)
        return self.data[start_index:]

    def get_data2(self, start_index: int, end_index: int) -> ma.masked_array:
        """
        :param start_index: Inclusive start index.
        :param end_index: Exclusive end index. Can be beyond the end of the
            data, in which case data up to the end is returned.
        """
        return self.data[start_index:end_index]

    def prune_by_index(self, index: int) -> ma.masked_array:
        self.data = self.data[index:].copy() # must copy to discard old buffer

    def prune_by_time(self, time: int) -> ma.masked_array:
        """
        :returns: Number of rows that were discarded
        """
        if len(self.data['timestamp']) == 0 or time < self.data['timestamp'][0]:
            return 0
        index = self.index_of_time(time)
        self.prune_by_index(index)
        return index

    def index_of_time(self, time: int):
        return np.searchsorted(self.data['timestamp'], time, side='right')


class Recorder(DiscoveryDelegate):
    """
    Utility for continuous recording of data from one or multiple ODrives.
    Takes care of disappearing and reappearing ODrives.

    All timestamps are in nanoseconds and with respect to time.monotonic_ns().

    properties: [(serial_number, [(property_name, codec_name)])]
        name is used as column name in the numpy array
        serial_number and property_name are used to identify the property across reboots
        codec_name defines the data type of the numpy array
    """
    def __init__(self, grouped_properties: List[Tuple[str, List[Tuple[str, str]]]], interval: float = 0.01):
        #self.properties = properties
        self.interval = interval

        all_properties = [p for _, properties in grouped_properties for p in properties]

        for path, codec_name in all_properties:
            if not codec_name in _codecs:
                raise Exception(f"Cannot plot property {path} of type {codec_name}")

        self._device_recorders = [
            _RecorderForDevice.from_specs(*specs) for specs in grouped_properties
        ]

    def on_connected(self, dev: RuntimeDevice):
        rec = [d for d in self._device_recorders if d.serial_number == dev.serial_number][0]
        indices_and_props = [
            (i, dev.get_prop_info(path, codec_name))
            for i, (path, codec_name) in enumerate(rec.properties)
        ]
        indices = [i+1 for i, p in indices_and_props if not p is None] # +1 to account for timestamp column
        props = [p for i, p in indices_and_props if not p is None]
        rec.fetcher = functools.partial(rec._fetch, dev, indices, props)

    def on_disconnected(self, dev: RuntimeDevice):
        rec = [d for d in self._device_recorders if d.serial_number == dev.serial_number][0]
        rec.fetcher = _noop_fetcher

    def get_data(self, window_size: float):
        t_max = max(rec.data['timestamp'][-1] for rec in self._device_recorders)
        t_min = t_max - window_size * 1e9
        return [
            rec.get_data(since=t_min)
            for rec in self._device_recorders
        ]

    def get_range(self, t_min: float, max_samples_per_column: int):
        """
        max_samples_per_column defines a cutoff point in time that will then
        be applied to all other time series too, even if they are below the limit.
        """
        start_indices = [dev.index_of_time(t_min) for dev in self._device_recorders]

        cutoff_timestamp = math.inf
        for i, d in enumerate(self._device_recorders):
            start_index = start_indices[i]
            timestamps = d.data['timestamp']
            if start_index + max_samples_per_column < len(timestamps):
                cutoff_timestamp = min(cutoff_timestamp, timestamps[start_index + max_samples_per_column])

        end_indices = [dev.index_of_time(cutoff_timestamp) for dev in self._device_recorders]

        if cutoff_timestamp == math.inf:
            t_max = max(max(d.data['timestamp'], default=t_min) for d in self._device_recorders)
        else:
            t_max = cutoff_timestamp

        data = {
            self._device_recorders[i].serial_number: self._device_recorders[i].get_data2(start_indices[i], end_indices[i])
            for i in range(len(self._device_recorders))
        }

        return data, t_max

    def get_range2(self, serial_number: str, t_min: int, max_rows: int):
        dev = next(d for d in self._device_recorders if d.serial_number == serial_number)
        start_index = dev.index_of_time(t_min)
        #end_index = min(start_index + max_rows, dev.end_index())
        return dev.get_data2(start_index, start_index + max_rows)

    def prune_from_for_dev(self, serial_number: str, t_min: int):
        """
        Discards data for the specified device up to t_min.

        :param t_min: timestamp in ns
        """
        # TODO: transform to dict?
        dev = next(d for d in self._device_recorders if d.serial_number == serial_number)
        dev.prune_by_index(dev.index_of_time(t_min))

    async def _prune_loop(self):
        try:
            while True:
                timestamp = time.monotonic_ns()

                #print(f"running prune task...")
                for dev in self._device_recorders:
                    n_discarded = dev.prune_by_time(timestamp - MAX_HISTORY_AGE * 1e9)
                    if n_discarded:
                        print(f"discarded {n_discarded} old rows for {dev.serial_number}")
                #print(f"ran prune task")

                await asyncio.sleep(AUTO_PRUNE_INTERVAL)
        except Exception as ex:
            traceback.print_exc()

    async def run(self, device_manager: DeviceManager):
        """
        Runs the recorder until the coroutine is cancelled.
        """
        #start_time = time.monotonic()
        serial_numbers = [dev.serial_number for dev in self._device_recorders]
        subscription = Subscription.for_serno(serial_numbers, self.on_connected, self.on_disconnected, debug_name="Recorder.run()")
        device_manager.subscribe(subscription)
        prune_task = asyncio.create_task(self._prune_loop())

        try:
            while True:
                timestamp = time.monotonic_ns()

                for dev in self._device_recorders:
                    if dev.active_fetch_task is None or dev.active_fetch_task.done():
                        dev.active_fetch_task = asyncio.create_task(dev.fetcher(timestamp))

                await asyncio.sleep(self.interval)

        finally:
            prune_task.cancel()
            device_manager.unsubscribe(subscription)
