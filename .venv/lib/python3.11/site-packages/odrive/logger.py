
import sys
import threading

# TODO: avoid duplication with rich_text module.
# Should have a global Logger object that has a "verbosity" state and provides
# shortcuts to printing info/warnings/etc.

# TODO: Check out "logging" from Python standard library

class Logger():
    """
    Logs messages to stdout
    """

    COLOR_DEFAULT = 0
    COLOR_GREEN = 1
    COLOR_CYAN = 2
    COLOR_YELLOW = 3
    COLOR_RED = 4

    _VT100Colors = {
        COLOR_GREEN: '\x1b[92;1m',
        COLOR_CYAN: '\x1b[96;1m',
        COLOR_YELLOW: '\x1b[93;1m',
        COLOR_RED: '\x1b[91;1m',
        COLOR_DEFAULT: '\x1b[0m'
    }

    def __init__(self, verbose=True):
        self._prefix = ''
        self._skip_bottom_line = False # If true, messages are printed one line above the cursor
        self._verbose = verbose
        self._print_lock = threading.Lock()

    def indent(self, prefix='  '):
        indented_logger = Logger()
        indented_logger._prefix = self._prefix + prefix
        return indented_logger

    def print_colored(self, text, color):
        self._print_lock.acquire()
        sys.stdout.write(Logger._VT100Colors[color] + text + Logger._VT100Colors[Logger.COLOR_DEFAULT] + '\n')
        sys.stdout.flush()
        self._print_lock.release()

    def debug(self, text):
        if self._verbose:
            self.print_colored(self._prefix + text, Logger.COLOR_DEFAULT)
    def success(self, text):
        self.print_colored(self._prefix + text, Logger.COLOR_GREEN)
    def info(self, text):
        self.print_colored(self._prefix + text, Logger.COLOR_DEFAULT)
    def notify(self, text):
        self.print_colored(self._prefix + text, Logger.COLOR_CYAN)
    def warn(self, text):
        self.print_colored(self._prefix + text, Logger.COLOR_YELLOW)
    def error(self, text):
        # TODO: write to stderr
        self.print_colored(self._prefix + text, Logger.COLOR_RED)
