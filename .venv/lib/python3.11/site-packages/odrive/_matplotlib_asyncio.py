"""
Utils to make matplotlib work on the same thread as an asyncio event loop.

matplotlib does not integrate natively with asyncio. When calling plt.show() in
an async function, it blocks the event loop. When calling plt.show(block=False)
in an async function, the figures won't show or be responsive, unless
fig.canvas.flush_events() is called periodically.

The fix in this file works by observing calls that create and destroy matplotlib
figure managers.
Whenever there's at least one figure manager, an asyncio task is started that
periodically flushes the events of each canvas.
Furthermore, `import` calls are observed to install the hooks when needed.

On some backends (e.g. macOS), resizing the windows can still block the asyncio
event loop.


Side Note
=========

Tighter integration is theoretically possible by implementing platform/backend-
specific low level functions ("input hooks") that can wait for matplotlib GUI
events _and_ one other file descriptor (e.g. os.pipe()). This is what IPython /
prompt_toolkit does (so figures can be open while IPython remains responsive).

IPython ships with several input hooks:
https://github.com/ipython/ipython/tree/main/IPython/terminal/pt_inputhooks

prompt_toolkit uses asyncio.SelectorEventLoop and a separate thread to funnel
asyncio events into a pipe that can wake up the input hook:
https://github.com/prompt-toolkit/python-prompt-toolkit/blob/master/src/prompt_toolkit/eventloop/inputhook.py

However due to the complexity and backend-dependence, we reject this approach
and use a polling loop instead.
"""

import asyncio
import atexit
import builtins
from contextlib import contextmanager
import functools
import signal
import sys

_figure_managers = set() # Set[matplotlib.backend_bases.FigureManagerBase]
_all_figure_managers = set() # Set[matplotlib.backend_bases.FigureManagerBase]
_pump_task = None
_pump_event: asyncio.Event() = None
_async_event_sources = []


# Asyncio update pump =========================================================#

# On older Python versions, we can't instantiate the event at global scope because that might
# attach it to the wrong event loop.
def _get_pump_event():
    global _pump_event
    if _pump_event is None:
        _pump_event = asyncio.Event()
    return _pump_event

async def _pump_canvas_events(refresh_rate = 0.01):
    global _pump_task
    #print("starting pump")
    while len(_figure_managers):
        # Refresh animations
        for evt in _async_event_sources:
            evt.step()

        # Must copy set because it can be modified during flush_events().
        figure_managers_copy = set(_figure_managers)
        for manager in figure_managers_copy:
            if manager in _figure_managers:
                # We must defer KeyboardInterrupts until after flushing events
                # because if one happens during an event callback, it is not
                # properly propagated up through the native stack.
                with shield_from_keyboard_interrupt():
                    manager.canvas.flush_events()

        await asyncio.sleep(refresh_rate)

async def wait_for_close(fig, anim):
    """
    Waits until the figure is closed or the animation is stopped.
    Only works when patch_pyplot() has been called.
    """
    while fig.canvas.manager in _figure_managers:
        if not anim.exception is None:
            raise anim.exception
        assert not _pump_task is None
        await _get_pump_event().wait()

def on_created_figure_manager(manager):
    #print("created figure manager")
    global _pump_task

    if not _pump_task is None and _pump_task.done():
        exc = _pump_task.exception() # must retrieve exception to prevent warning
        if not exc is None:
            print(f"matplotlib pump stopped with {exc}")
        _pump_task = None

    if _pump_task is None:
        _pump_task = asyncio.create_task(_pump_canvas_events())
    _figure_managers.add(manager)
    _all_figure_managers.add(manager)

def on_destroyed_figure_manager(manager):
    #print("destroyed figure manager")
    _figure_managers.discard(manager)

    evt = _get_pump_event()
    evt.set()
    evt.clear()

def collect_pump_task():
    # Collect task exception to prevent warning from being printed. This can be
    # just a KeyboardInterrupt and does usually not need to be shown.
    if not _pump_task is None and _pump_task.done():
        if not _pump_task.cancelled():
            _pump_task.exception()

atexit.register(collect_pump_task)


# Patching ====================================================================#

def wrap(original, hook):
    return functools.partial(hook, original)

def new_figure_manager_wrapper(inner, *args, **kwargs):
    manager = inner(*args, **kwargs)

    def destroy_wrapper(inner, *args, **kwargs):
        on_destroyed_figure_manager(manager)
        return inner(*args, **kwargs)

    manager.destroy = wrap(manager.destroy, destroy_wrapper)

    on_created_figure_manager(manager)

    return manager

def patch_pyplot(plt):
    """
    Patches matplotlib.pyplot.new_figure_manager.
    """
    if getattr(plt, '_patched_figure_manager', False):
        return # already patched
    plt._patched_figure_manager = True
    plt.new_figure_manager = wrap(plt.new_figure_manager, new_figure_manager_wrapper)

    # When matplotlib runs in IPython (or odrivetool), it tries to install a
    # display hook that is supposed to allow IPython to integrate with the
    # matplotlib event loop. However when we do this, IPython / prompt_toolkit
    # no longer runs the existing main event loop to wait for input, but instead
    # spawns a new one for each input. This would block the main event loop,
    # so we need to prevent this.
    plt.install_repl_displayhook = lambda: None

    #print("patched pyplot")

def patch_pyplot_if_imported():
    """
    Calls patch_pyplot(matplotlib.pyplot) if the module was (fully) imported and
    the patch was not applied yet.
    Returns True if the patch was applied.
    """
    plt = sys.modules.get("matplotlib.pyplot")
    # hasattr() makes sure we don't try to patch while the module is being loaded
    if not plt is None and hasattr(plt, 'new_figure_manager'):
        patch_pyplot(plt)
        return True
    return False


_patched_import = False

def patch_pyplot_once_imported():
    """
    Makes sure patch_pyplot() gets called once matplotlib.pyplot gets imported
    (or immediately).
    """
    global _patched_import
    if _patched_import:
        return
    _patched_import = True

    if patch_pyplot_if_imported():
        return # in case it was already imported

    def import_wrapper(inner, *args, **kwargs):
        global _patched_import
        result = inner(*args, **kwargs)
        if args[0].startswith("matplotlib"):
            if patch_pyplot_if_imported():
                # Once the patch was applied, remove wrap hook (if it's still the
                # same) because it's not needed anymore. This is only an optimization.
                if builtins.__import__ == wrapped:
                    builtins.__import__ = inner
                    _patched_import = False
        return result

    wrapped = wrap(builtins.__import__, import_wrapper)
    builtins.__import__ = wrapped


# Animations ==================================================================#

class AsyncEventSource():
    def __init__(self):
        self.callbacks = []

    def add_callback(self, callback):
        self.callbacks.append(callback)

    def remove_callback(self, callback):
        self.callbacks.remove(callback)
        if len(self.callbacks) == 0 and self in _async_event_sources:
            # TODO: this is a bit hacky cause we don't restart when a new callback is added
            _async_event_sources.remove(self)

    def start(self):
        _async_event_sources.append(self)

    def stop(self):
        _async_event_sources.remove(self)
    
    def step(self):
        for callback in self.callbacks:
            callback()

def make_animation(*args, **kwargs):
    # AsyncAnimation is encapsulated in a function to avoid eagerly depending
    # on matplotlib.

    from matplotlib import animation as manimation

    class AsyncAnimation(manimation.Animation):
        """
        Similar to matplotlib.animation.FuncAnimation but the frames are
        synchronized with the refresh loop in _pump_canvas_events() instead of
        a platform timer.
        FuncAnimation was causing problems on at least one platform (Linux,
        matplotlib 3.0.2, TkAgg backend), if the requested interval was too
        small (less than ~80ms). In that case, the whole thread would end up
        frozen (potentially because the timer events were arriving quicker than
        they were handled, or because of some other weird low-level stuff).
        """
        def __init__(self, fig, func, *args, **kwargs):
            self.event_source = AsyncEventSource()
            self._func = func
            self.exception = None # set when the plotting function throws an exception

            # custom super() call to avoid importing matplotlib eagerly
            super().__init__(fig, event_source=self.event_source, *args, **kwargs)

        def new_frame_seq(self):
            return iter(lambda: None, object()) # infinite sequence of None

        # Called by Animation base class
        def _draw_frame(self, framedata):
            # Result used by Animation base class
            try:
                self._drawn_artists = self._func(framedata)
            except Exception as ex:
                print("plotter failed with ", ex)
                self.exception = ex
                self._drawn_artists = None
                self._stop()
                _get_pump_event().set()

    return AsyncAnimation(*args, **kwargs)


# Utils =======================================================================#

@contextmanager
def shield_from_keyboard_interrupt():
    """
    Shields the inner block from KeyboardInterrupts. If a KeyboardInterrupt
    happens during the block, it is raised at the end of the block.
    """
    received_signals = []

    def deferring_signal_handler(sig, frame):
        received_signals.append((sig, frame))

    original_handler = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, deferring_signal_handler)

    try:
        yield
    finally:
        signal.signal(signal.SIGINT, original_handler)
        for sig, frame in received_signals:
            original_handler(sig, frame)
