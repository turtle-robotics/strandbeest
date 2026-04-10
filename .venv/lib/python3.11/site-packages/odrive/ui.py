
from contextlib import contextmanager
import functools
from typing import TextIO

from odrive.rich_text import Color, RichText, Style, print_rich_text

STYLE_GOOD = (Color.GREEN, Color.DEFAULT, Style.BOLD)
STYLE_NOTIFY = (Color.CYAN, Color.DEFAULT, Style.BOLD)
STYLE_WARN = (Color.YELLOW, Color.DEFAULT, Style.BOLD)
STYLE_BAD = (Color.RED, Color.DEFAULT, Style.BOLD)

class OperationAbortedException(Exception):
    pass

class RichTextPrinter():
    def __init__(self):
        pass

    def info(self, text):
        print_rich_text(RichText(text))

    def success(self, text):
        print_rich_text(RichText(text, *STYLE_GOOD))

    def notify(self, text):
        print_rich_text(RichText(text, *STYLE_NOTIFY))

    def warn(self, text):
        print_rich_text(RichText(text, *STYLE_WARN))

    def error(self, text):
        print_rich_text(RichText(text, *STYLE_BAD))

def yes_no_prompt(question, default=None):
    if default is None:
        question += " [y/n] "
    elif default == True:
        question += " [Y/n] "
    elif default == False:
        question += " [y/N] "

    while True:
        print(question, end='')

        choice = input().lower()
        if choice in {'yes', 'y'}:
            return True
        elif choice in {'no', 'n'}:
            return False
        elif choice == '' and default is not None:
            return default

def multiple_choice(prompt, choices):
    while True:
        for i, c in enumerate(choices):
            print(f"  ({i+1}) {c}")
        print(f"{prompt} (1...{len(choices)}): ", end='')
        try:
            choice = int(input().lower())
        except ValueError:
            choice = -1
        if choice > 0 and choice < len(choices):
            return choice - 1
        print("invalid input")

def _print_on_second_last_line_impl(inner_write, inner_flush, text):
    """
    Prints a text on the second last line.

    This can be used to print a message above the command prompt. If the command
    prompt spans multiple lines there will be glitches.

    If the printed text spans multiple lines there will also be glitches (though
    this could be fixed).

    Only works on a VT100 compatible terminal (Windows 10+ or Unix).
    """

    # This is slightly hacky: The print() commands ends with a single write() for the
    # trailing end-of-line, however the way we use the viewport means that
    # a trailing new line is not desired because it would leave an empty
    # line.
    if text.endswith('\n'):
        text = text[:-1]
    if text == '':
        return

    # Escape character sequence:
    #   ESC 7: store cursor position
    #   ESC 1A: move cursor up by one
    #   ESC 1S: scroll entire viewport by one
    #   ESC 1L: insert 1 line at cursor position
    #   (print text)
    #   ESC 8: restore old cursor position

    # TODO: acquire lock
    #inner_write('\x1b7\x1b[1A\x1b[1S\x1b[1L\r')
    inner_write('\x1b7\x1b[1A\x1b[1S\x1b[1L\r')
    inner_write(text)
    inner_write('\x1b8')
    inner_flush()

@contextmanager
def dont_print_on_last_line(stream: TextIO):
    """
    Ensures that print() does not print on the last line but the second last line.

    This is useful if the last line is used for an interactive input prompt.
    """
    inner_write = stream.write
    stream.write = functools.partial(_print_on_second_last_line_impl, inner_write, stream.flush)
    try:
        yield inner_write
    finally:
        stream.write = inner_write
