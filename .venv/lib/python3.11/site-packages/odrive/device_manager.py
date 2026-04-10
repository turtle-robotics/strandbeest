import asyncio
import atexit
import concurrent.futures
import inspect
import logging
import os
import sys
import threading
from typing import Callable, Dict, Optional, List, Sequence, Set, Tuple, Type, TypeVar, Union
from odrive._internal_utils import get_current_loop
from odrive.async_tree import AsyncObject
from odrive.libodrive import CouldNotClaimInterfaceException, Device, DeviceType, DiscoveryDelegate, Interface, LibODrive
from odrive.runtime_device import RuntimeDevice
from odrive.sync_tree import SyncObject

__all__ = ['DeviceManager', 'Subscription', 'get_device_manager', 'close_device_manager']

logger = logging.getLogger("odrive")

def _call_string(frame):
    args, _, _, values = inspect.getargvalues(frame)
    arg_str = ', '.join(f"{arg}={values[arg]!r}" for arg in args)
    return f"{frame.f_code.co_name}({arg_str})"

class _DeviceStub():
    def __init__(self) -> None:
        self._connect_lock = asyncio.Lock()
        self._runtime_device = None
        self._sync_wrapper = None
        self._async_wrapper = None

    async def ensure_connected(self, device: Device):
        async with self._connect_lock:
            if self._runtime_device is None:
                self._runtime_device, self._sync_wrapper, self._async_wrapper = await RuntimeDevice.from_device(device)
        return self._runtime_device, self._sync_wrapper, self._async_wrapper

class Subscription():
    """
    Subscription to be used with :func:`DeviceManager.subscribe()`.

    :param on_found: Called when a device is found. The serial number is already
        available before the device is connected, so the application can use this
        callback to decide if the device shall be connected.
        The handler shall return :code:`True` to request connection and :code:`False` to ignore the device.
        If connection is requested, :code:`on_connected` is called later.
        If multiple subscriptions are active, a connection is opened if any
        subscription accepts the device.
        Otherwise, if no subscription requests a connection, the device can be
        used by other applications.
    :param on_lost: Called when a device is lost.
    :param on_connected: Called when a connection with the device is established.
    :param on_disconnected: Called when a device that was previously announced via :code:`on_connected` is disconnected.
    """

    def __init__(self, on_found: Callable[[Device], bool], on_lost: Callable[[Device], None], on_connected: Callable[[RuntimeDevice], None], on_disconnected: Callable[[RuntimeDevice], None], debug_name: str):
        self._on_found_cb = on_found
        self._on_lost_cb = on_lost
        self._on_connected_cb = on_connected
        self._on_disconnected_cb = on_disconnected
        self._awaiting_connect: Set[Device] = set()
        self.debug_name = debug_name

    @staticmethod
    def for_serno(serial_number: Union[Sequence[str], str, None], on_connected: Callable[[RuntimeDevice], None], on_disconnected: Callable[[RuntimeDevice], None], debug_name: str):
        serial_numbers = None if serial_number is None else [serial_number] if isinstance(serial_number, str) else serial_number
        def _filter(dev: Device):
            if dev.info.device_type != DeviceType.RUNTIME:
                return False
            return serial_number is None or dev.info.serial_number in serial_numbers
        return Subscription(_filter, lambda x: 0, on_connected, on_disconnected, debug_name)

    def _on_found(self, dev: Device):
        try:
            should_connect = self._on_found_cb(dev)
        except Exception as ex:
            logger.warning(f"Subscription's on_found handler failed: {ex}", exc_info=True)
            should_connect = False
        if should_connect:
            self._awaiting_connect.add(dev)
        return should_connect

    def _on_lost(self, runtime_device: RuntimeDevice, dev: Device):
        try:
            if not self._on_disconnected_cb is None and not runtime_device is None:
                self._on_disconnected_cb(runtime_device)
            self._on_lost_cb(dev)
        except Exception as ex:
            logger.warning(f"Subscription's on_lost handler failed: {ex}", exc_info=True)

    def _on_connected(self, dev: RuntimeDevice):
        self._awaiting_connect.discard(dev.device)
        try:
            self._on_connected_cb(dev)
        except Exception as ex:
            logger.warning(f"Subscription's on_connected handler failed: {ex}", exc_info=True)


T = TypeVar('T')

class DeviceManager(DiscoveryDelegate):
    def __init__(self, loop: asyncio.AbstractEventLoop, lib: LibODrive):
        self.loop = loop # loop on which this device manager can be used
        self.lib = lib
        self.devices: List[Device] = []
        self.event = asyncio.Event()
        self._subscribers: List[Subscription] = []
        self._device_stubs: Dict[Device, _DeviceStub] = {}
    
    def subscribe(self, subscription: Subscription):
        """
        Adds a subscription to this device manager that will be notified when
        a matching device appears / disappears.
        
        The subscription is also notified for all matching devices already
        present.
        """
        self._subscribers.append(subscription)

        for dev in self.devices:
            if subscription._on_found(dev):
                self._connect_and_announce(dev, [subscription])
    
    def unsubscribe(self, subscription: Subscription):
        self._subscribers.remove(subscription)

    def on_found_device(self, intf: Interface, dev: Device):
        self.devices.append(dev)

        # signal all waiting tasks and recycle event for next round
        self.event.set()
        self.event = asyncio.Event()

        connect_requested_by = []
        for sub in self._subscribers:
            if sub._on_found(dev):
                connect_requested_by.append(sub)

        if len(connect_requested_by):
            self._connect_and_announce(dev, connect_requested_by)
        else:
            logger.debug("found device but no subscription requested to connect to it")

    def _connect_and_announce(self, dev: Device, connect_requested_by: List[Subscription]):
        asyncio.create_task(self._connect_and_announce_async(dev, connect_requested_by))

    async def _connect_and_announce_async(self, device: Device, connect_requested_by: List[Subscription]):
        try:
            runtime_device, _, _ = await self.ensure_connected(device)
            for sub in self._subscribers:
                if device in sub._awaiting_connect:
                    sub._on_connected(runtime_device)
        except Exception as ex:
            program = os.path.basename(sys.modules['__main__'].__file__)
            if isinstance(ex, CouldNotClaimInterfaceException):
                logger.warning(
                    f"Found ODrive {device.info.serial_number} but {program} could not connect to it. "
                    "Looks like this ODrive is in use by another program. "
                    "Close the Web GUI and other scripts that may be accessing the ODrive and then re-plug the ODrive to try again."
                )
                logger.debug("Details: ", exc_info=True)
            else:
                subs = ', '.join(sub.debug_name for sub in connect_requested_by)
                logger.warning(f"Found ODrive {device.info.serial_number} but {program} could not connect to it (requested by {subs}): {ex}", exc_info=True)
            for sub in self._subscribers:
                sub._awaiting_connect.discard(device)


    def on_lost_device(self, intf: Interface, dev: Device):
        #print("lost device")
        self.devices.remove(dev)
        if not dev in self._device_stubs:
            return
        stub = self._device_stubs.pop(dev)
        runtime_device = stub._runtime_device

        for sub in self._subscribers:
            sub._on_lost(runtime_device, dev)

    def get_device(self, serial_number: Optional[str], device_type: Optional[DeviceType]):
        for dev in self.devices:
            if not serial_number is None and dev.info.serial_number != serial_number:
                continue
            if not device_type is None and dev.info.device_type != device_type:
                continue
            return dev
        return None

    async def ensure_connected(self, dev: Device):
        stub = self._device_stubs.get(dev, None)
        if stub is None:
            stub = _DeviceStub()
            self._device_stubs[dev] = stub
        return await stub.ensure_connected(dev)

    async def wait_for(self, serial_number: Union[Sequence[str], str, None] = None, count: Optional[int] = None, return_type: Type[T] = RuntimeDevice, device_type: DeviceType = None) -> T:
        """
        Waits until one or multiple ODrives are found and connected.

        If no arguments are given, the function waits for a single ODrive.

        Specific ODrives can be selected by specifying their serial number.
        If the serial numbers are not known, ``count`` can be specified to wait for
        a certain number of ODrives.

        The return type is either a single ODrive object (if no arguments are given
        or ``serial_number`` is given as a string) or a tuple of ODrives otherwise.

        The ODrives that this function connects to are claimed for exclusive use by
        the current Python process and cannot be used by any other programs. Other
        ODrives are not claimed and can still be used by other programs.

        Can be called multiple times, including simultaneously, from multiple async
        tasks on the same thread. Calls from multiple threads are not allowed. The
        returned ODrive object must not be used from any other thread than the one
        it was retrieved on (exception: if ``return_type`` is :class:`SyncObject`).

        See also: :ref:`python-discovery`, :func:`get_device_manager()`, :func:`odrive.find_sync()`, :func:`odrive.find_async()`.
        
        :param serial_number: Single serial number or sequence (e.g. tuple or list)
            of multiple serial numbers. None to accept any serial number.
            If a sequence is specified, the returned tuple is in the same order.
        :param count: Number of ODrives to wait for. Must be None if ``serial_number``
            is specified.
        """
        assert return_type in set({RuntimeDevice, SyncObject, AsyncObject, Device})

        should_connect = return_type != Device

        if device_type is None and return_type != Device:
            device_type = DeviceType.RUNTIME

        if serial_number is None and count is None:
            count = 1
            return_as_single = True
        elif (not serial_number is None) and (not count is None):
            raise Exception("serial_numbers and count cannot be specified at the same time")
        elif isinstance(serial_number, str):
            serial_numbers = [serial_number]
            return_as_single = True
        else:
            serial_numbers = serial_number
            return_as_single = False

        n_slots = len(serial_numbers) if count is None else count

        devices = [None] * n_slots
        results = [None] * n_slots

        def _on_found(dev: Device):
            if (not device_type is None) and dev.info.device_type != device_type:
                return False # don't connect

            if count is None:
                try:
                    idx = serial_numbers.index(dev.info.serial_number)
                except ValueError:
                    return False # don't connect
            else:
                try:
                    idx = devices.index(None)
                except ValueError:
                    return False # don't connect

            devices[idx] = dev

            if should_connect:
                return True # connect
            else:
                results[idx] = dev
                if not None in results:
                    done.set()
                return False # don't connect

            
        def _on_lost(dev: Device):
            try:
                idx = devices.index(dev)
            except ValueError:
                return # lost one of the ignored ODrives
            devices[idx] = None
            results[idx] = None

        def _on_connected(dev: RuntimeDevice):
            if return_type == RuntimeDevice:
                obj = dev
            elif return_type == SyncObject:
                obj = dev.sync_wrapper
            elif return_type == AsyncObject:
                obj = dev.async_wrapper

            results[devices.index(dev.device)] = obj

            if not None in results:
                done.set()

        done = asyncio.Event()
        subscription = Subscription(_on_found, _on_lost, _on_connected, None, f"DeviceManager.{_call_string(inspect.currentframe())}")

        try:
            self.subscribe(subscription)
            await done.wait()
        finally:
            self.unsubscribe(subscription)

        return results[0] if return_as_single else tuple(results)


_global_device_manager_lock = threading.Lock()
_global_device_manager: Optional[DeviceManager] = None
_global_event_loop_thread: Optional[threading.Thread] = None
_global_event_loop_close_signal: Optional[asyncio.Event] = None

def _runner(loop_future: concurrent.futures.Future):
    async def _runner():
        global _global_event_loop_close_signal
        _global_event_loop_close_signal = asyncio.Event()
        loop_future.set_result(asyncio.get_running_loop())
        await _global_event_loop_close_signal.wait()
    asyncio.run(_runner())

def _start_device_manager_on_current_thread(current_loop: asyncio.AbstractEventLoop):
    libodrive = LibODrive(loop=current_loop)
    device_manager = DeviceManager(current_loop, lib=libodrive)
    intf = libodrive.start_usb_discovery(device_manager)
    libodrive._worker_thread.start() # TODO: remove (starting USB discovery is not thread-safe in this libodrive version)
    return device_manager

def get_device_manager() -> DeviceManager:
    """
    Returns the global :attr:`DeviceManager` object. The first call to this
    function instantiates the device manager, initializes the backend and starts
    USB discovery.

    The first call also defines which thread and asyncio event loop the device
    manager is bound to:

    - If the current thread has an event loop, the device manager is bound to
      the current thread and event loop.
    - If the current thread has no event loop, a background thread with an
      event loop is started.
    
    Subsequent calls return the same device manager, until :func:`close_device_manager()`
    is called.

    The device manager and devices returned by it must only be used on the 
    thread that it is bound to. An exception are the thread safe wrapper objects
    returned by :func:`odrive.find_sync()` and :func:`odrive.utils.to_sync()`.
    """
    global _global_device_manager
    global _global_event_loop_thread

    with _global_device_manager_lock:
        if not _global_device_manager is None:
            return _global_device_manager
        
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            running_loop = None

        current_thread = not running_loop is None

        if running_loop is None:
            _loop_future = concurrent.futures.Future()
            _global_event_loop_thread = threading.Thread(target=_runner, args=(_loop_future,), daemon=True).start()
            running_loop: asyncio.AbstractEventLoop = _loop_future.result()

        if current_thread:
            _global_device_manager = _start_device_manager_on_current_thread(running_loop)
        else:
            async def _wrap_sync():
                return _start_device_manager_on_current_thread(running_loop)
            _global_device_manager = asyncio.run_coroutine_threadsafe(_wrap_sync(), loop=running_loop).result()

        return _global_device_manager

def _get_device_manager_for_local_thread():
    device_manager = get_device_manager()
    if device_manager.loop != asyncio.get_running_loop():
        raise Exception("The ODrive device manager was already instantiated on a different event loop.")
    return device_manager

def close_device_manager():
    """
    Closes the global :class:`DeviceManager` object (if it is open).
    All devices associated with it must be considered invalid after calling
    this.

    This is called automatically upon exit of the program.
    """
    global _global_device_manager
    global _global_event_loop_thread
    global _global_event_loop_close_signal

    if not _global_event_loop_thread is None:
        _global_device_manager.loop.call_soon_threadsafe(_global_event_loop_close_signal.set)
        _global_event_loop_thread.join()
        _global_event_loop_thread = None
        _global_event_loop_close_signal = None

    if not _global_device_manager is None:
        _global_device_manager.lib.deinit()
        _global_device_manager = None

async def find_async(serial_number: Union[Sequence[str], str, None] = None, count: Optional[int] = None, return_type: Type[T] = AsyncObject, device_type: Optional[DeviceType] = None) -> T:
    """
    Waits until one or multiple ODrives are found and connected.

    This is a wrapper around :func:`odrive.device_manager.DeviceManager.wait_for()`.

    If the device manager was not initialized yet, it is initialized and bound to the current thread and event loop.

    If a timeout is needed, consider wrapping this in ``asyncio.wait_for(find_any(...), timeout)``.

    For a blocking, thread-safe wrapper, see :func:`find_sync()`.
    """
    return await _get_device_manager_for_local_thread().wait_for(serial_number, count, return_type, device_type)

async def with_timeout(coro, timeout):
    try:
        return await asyncio.wait_for(coro, timeout)
    except asyncio.TimeoutError:
        raise TimeoutError

def find_sync(serial_number: Union[Sequence[str], str, None] = None, count: Optional[int] = None, return_type: Type[T] = SyncObject, timeout: float = None) -> T:
    """
    Waits until one or multiple ODrives are found and connected.

    This is a blocking, thread-safe wrapper around :func:`odrive.device_manager.DeviceManager.wait_for()`.
    
    If the device manager was not initialized yet, this starts a background thread to run the backend.

    For use with async/await, see :func:`find_async()`.
    """

    # TODO: the timeout parameter was removed. May want to re-add.

    device_manager = get_device_manager()

    running_loop = get_current_loop()

    coro = device_manager.wait_for(serial_number, count, return_type)

    if not timeout is None:
        coro = with_timeout(coro, timeout)

    if running_loop == device_manager.loop:
        return asyncio.run(coro) # loop must be re-entrant
    else:
        return asyncio.run_coroutine_threadsafe(coro, device_manager.loop).result()

def find_any(*args, **kwargs):
    """
    Alias for :func:`find_sync()`.
    """
    return find_sync(*args, **kwargs)


atexit.register(close_device_manager)
