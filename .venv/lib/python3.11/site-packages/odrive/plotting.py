import asyncio
import time
import matplotlib.pyplot as plt
import numpy as np
from typing import Callable, List, Optional, Tuple

from odrive._internal_utils import await_first
from odrive._matplotlib_asyncio import patch_pyplot, wait_for_close, make_animation
from odrive.async_tree import AsyncProperty
from odrive.recorder import Recorder
from odrive.device_manager import get_device_manager

patch_pyplot(plt) # make plt.show(block=False) work on asyncio threads

class LivePlotter():
    """
    Utility for showing a live plot of ODrive properties.
    """
    def __init__(self, layout: List[List[int]], labels: List[str], getter: Callable, window_size: float = 5.0):
        """
        Must only be called on the main thread.

        :param layout: A nested list of numbers. Each number represents an index
            into the date returned by getter(). Each list represents a subplot.
        :param labels: A list of labels, containing one lable for each line
            returned by ``getter``.
            Must have the same length as the data returned by ``getter``.
        :param getter: A callable that is invoked at each timestep to get the
            data for plotting.
            The output must have the form ``[(xs_0, ys_0), (xs_1, ys_1), ...]``
            and is arranged according to ``layout``.
        :param window_size: The x-axis window size (in number of samples) of the plotter.
        """
        self.layout = layout
        self.getter = getter
        self.window_size = window_size

        n_subplots = len(layout)
        self._fig, axes = plt.subplots(n_subplots, 1, sharex=True)
        self._axes = [axes] if n_subplots == 1 else axes
        
        self._lines = [
            [ax.plot([], label=labels[idx])[0] for idx in layout[i]]
            for i, ax in enumerate(self._axes)
        ]

        # We're not using matplotlib.animation.FuncAnimation because it was
        # causing freezes on some platforms. See notes in function below.
        self._anim = make_animation(self._fig, self._animate, blit=False)

    async def show(self):
        """
        Shows the liveplotter. The figure can be closed by cancelling this
        coroutine.
        """
        plt.show(block=False)
        try:
            await wait_for_close(self._fig, self._anim)
        finally:
            plt.close(self._fig)

    def _animate(self, *fargs):
        data = self.getter()

        for line_handles, data_indices in zip(self._lines, self.layout):
            for line_handle, data_index in zip(line_handles, data_indices):
                (x, y) = data[data_index]
                line_handle.set_data(x, y)

        # TODO: improve efficiency by not passing same x multiple times
        x_max = max([0 if len(x) == 0 else np.max(x) for x, _ in data])
        for ax in self._axes:
            ax.set_xlim(x_max - self.window_size, x_max)
            ax.relim()
            ax.autoscale_view()
            if len(ax.get_legend_handles_labels()[0]):
                ax.legend(loc='upper left')

def start_liveplotter(properties: List[AsyncProperty], layout: Optional[List[List[str]]], window_size: float = 5.0):
    """
    Starts the liveplotter.

    Returns an awaitable that completes when the plotting window is closed or
    plotting is interrupted by a KeyboardInterrupt.

    The liveplotter can be closed by cancelling the awaitable.

    Parameters documented on odrive.utils.start_liveplotter().
    """

    t_start = time.monotonic_ns()

    # Transform list of properties into list of unique keys that will be used to
    # reference data from the recorder.
    single_device = len(set((p._dev for p in properties))) == 1
    if single_device:
        def get_label(p: AsyncProperty): return p._dev.path_of(p._info)
    else:
        def get_label(p: AsyncProperty): return p._dev.sync_wrapper.__name__ + "." + p._dev.path_of(p._info)
    names = [get_label(p) for p in properties]

    if layout is None:
        layout_int = [list(range(len(names)))]
    else:
        layout_int = [[names.index(key) for key in subplot_layout] for subplot_layout in layout]

    devices = list(set(prop._dev for prop in properties))
    grouped_properties = [
        (dev.serial_number, [(p._dev.path_of(p._info), p._info.codec_name) for p in properties if p._dev == dev])
        for dev in devices
    ]

    recorder = Recorder(
        grouped_properties
    )

    def getter():
        data = recorder.get_data(window_size)
        flat_data = [
            ((ts['timestamp'] - t_start) / 1e9, ts[column_name])
            for ts in data for column_name in ts.dtype.names[1:]
        ]
        return flat_data

    plotter = LivePlotter(layout_int, names, getter, window_size=window_size)

    return await_first(
        asyncio.create_task(recorder.run(get_device_manager())),
        asyncio.create_task(plotter.show())
    )

async def run_liveplotter(properties: List[AsyncProperty], layout: Optional[List[List[str]]] = None):
    await start_liveplotter(properties, layout)
