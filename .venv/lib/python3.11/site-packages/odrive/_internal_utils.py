import asyncio
import functools
import inspect
import traceback
from typing import Callable, Union, get_type_hints

def transform_odrive_objects(func):
    """
    Decorator for ODrive util functions.

    Each input argument that is annotated with `RuntimeDevice` is transformed
    such that it accepts a `RuntimeDevice`, `AsyncObject` or `SyncObject`.
    If a `SyncObject` is passed in, the function furthermore completes
    synchronously.
    """
    annotations = get_type_hints(func)
    sig = inspect.signature(func)

    def transform_root(arg: Union[RuntimeDevice, AsyncObject, SyncObject], name, syncify_on_loop):
        if isinstance(arg, RuntimeDevice):
            return arg
        elif isinstance(arg, AsyncObject):
            return arg._dev
        elif isinstance(arg, SyncObject):
            syncify_on_loop.add(arg._loop)
            return arg._dev
        else:
            raise Exception(f"unsupported type {type(arg)} for argument {name}")

    def transform_child(arg: Union[AsyncObject, SyncObject], name, syncify_on_loop):
        if isinstance(arg, AsyncObject):
            return arg
        elif isinstance(arg, SyncObject):
            syncify_on_loop.add(arg._loop)
            return arg._dev.sync_to_async(arg)
        else:
            raise Exception(f"unsupported type {type(arg)} for argument {name}")

    transforms = {
        name: transform_child if hint == AsyncObject else transform_root
        for name, hint in annotations.items()
        if name != 'return' and (hint == AsyncObject or hint == RuntimeDevice)
    }

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        bound_args = sig.bind(*args, **kwargs)
        bound_args.apply_defaults()

        syncify_on_loop = set()

        for name, transform in transforms.items():
            bound_args.arguments[name] = transform(bound_args.arguments[name], name, syncify_on_loop)

        coro = func(*bound_args.args, **bound_args.kwargs)
        if len(syncify_on_loop) == 0:
            return coro
        elif len(syncify_on_loop) == 1:
            return run_on_loop(coro, loop=next(iter(syncify_on_loop)))
        else:
            raise Exception("All SyncObject arguments must be bound to the same event loop.")        

    # Update wrapper annotations
    wrapper.__annotations__ = {
        k: transforms[k].__annotations__['arg'] if k in transforms else v
        for k, v in annotations.items()
    }

    return wrapper

def get_current_loop():
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None

def run_sync_on_loop(func: Callable, loop):
    if loop == get_current_loop():
        return func()
    else:
        async def _wrapper():
            func()
        return asyncio.run_coroutine_threadsafe(_wrapper, loop=loop).result()

def run_on_loop(awaitable, loop):
    if loop == get_current_loop():
        return asyncio.run(awaitable)
    else:
        return asyncio.run_coroutine_threadsafe(awaitable, loop=loop).result()

async def await_first(*awaitables):
    """
    Awaits the first of several tasks or futures and cancels the others.

    If any task completes normally or raises an exception (including
    CancelledError), the remaining tasks are cancelled immediately. An exception
    in a child task is propagated up to this coroutine.

    If this coroutine itself is cancelled, all child tasks are cancelled as
    well.

    If awaitables contains any items other than asyncio.Task, they are scheduled
    as tasks first.

    See also:
    - asyncio.gather() if all results are relevant and should be awaited
      collectively.
    - asyncio.wait(): lower level function which does not "finalize" unfinished
      tasks.
    - asyncio.TaskGroup: Similar purpose to this function, added in Python 3.11
    """
    tasks = [aw if isinstance(aw, asyncio.Task) else asyncio.create_task(aw) for aw in awaitables]

    first_to_complete = next(asyncio.as_completed(tasks))
    try:
        result = await first_to_complete
    finally:
        for t in tasks:
            t.cancel()
        for t in tasks:
            if not t.done():
                try:
                    await t
                except asyncio.CancelledError:
                    # Edge case: if the outer task is cancelled while we're already exiting,
                    # some remaining tasks may not be awaited correctly
                    if asyncio.current_task().cancelled():
                        raise
                except Exception as ex:
                    print(f"After the first task finished, cancelling secondary task {t} failed: {ex}")
                    traceback.print_exc()
    return result

from odrive.async_tree import AsyncObject
from odrive.runtime_device import RuntimeDevice
from odrive.sync_tree import SyncObject
