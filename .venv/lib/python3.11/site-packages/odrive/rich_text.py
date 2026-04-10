
import enum
from typing import Iterable, Union, Optional, List, Tuple, Sequence, cast

class Style(enum.IntEnum):
    NONE = 0x00
    BOLD = 0x01
    ITALIC = 0x02
    UNDERLINE = 0x04

class Color(enum.Enum):
    DEFAULT = enum.auto() # the terminal's default color
    COLOR_MASK = enum.auto()
    RED = enum.auto()
    YELLOW = enum.auto()
    GREEN = enum.auto()
    CYAN = enum.auto()
    BLUE = enum.auto()
    MAGENTA = enum.auto()
    GRAY = enum.auto()


class RichText():
    """
    Represents a text consisting of styled/colored string segments.
    """
    segments: List[Tuple[str, Color, Color, Style]]

    def __init__(self, val: Union[str, 'RichText', Sequence[Union[str, 'RichText']]], foreground: Optional[Color] = None, background: Optional[Color] = None, style: Optional[Style] = None):
        """
        val: A string, a RichText object or a list of strings or RichText
        objects.
        style: If specified, overrides the style of all segments in `val`.
        If not specified, uncolored strings are set to the default color.
        """

        if not (isinstance(val, tuple) or isinstance(val, list)):
            val = [cast(Union[str, 'RichText'], val)]

        self.segments = []
        for segment in val:
            if isinstance(segment, str):
                self.segments.append((segment, Color.DEFAULT, Color.DEFAULT, Style.NONE))
            elif isinstance(segment, RichText):
                self.segments.extend(segment.segments)
            else:
                raise Exception("unsupported argument")
        
        # Override attributes
        for i, (seg_str, seg_foreground, seg_background, seg_style) in enumerate(self.segments):
            if not style is None:
                seg_style = style
            if not foreground is None:
                seg_foreground = foreground
            if not background is None:
                seg_background = background
            self.segments[i] = (seg_str, seg_foreground, seg_background, seg_style)

        # Remove empty segments
        i = 0
        while i < len(self.segments):
            if self.segments[i][0] == '':
                self.segments.pop(i)
            else:
                i += 1

        # Coalesce segments with identical attributes
        i = 1
        while i < len(self.segments):
            if self.segments[i - 1][1:] == self.segments[i][1:]:
                self.segments[i - 1] = (self.segments[i - 1][0] + self.segments.pop(i)[0],) + self.segments[i - 1][1:]
            else:
                i += 1

    def __add__(self, other):
        if isinstance(other, str) or isinstance(other, RichText):
            return RichText([self, other])
        else:
            raise NotImplementedError(f"can only concatenate str and RichText (not {type(other).__name__}) to RichText.")

    def __radd__(self, other):
        if isinstance(other, str) or isinstance(other, RichText):
            return RichText([other, self])
        else:
            raise NotImplementedError(f"can only concatenate RichText to str and RichText (not {type(other).__name__}).")
    
    def __repr__(self):
        return ''.join([s[0] for s in self.segments])

    def join(self, others: Iterable[Union['RichText', str]]):
        """
        Analogous to str.join()
        """
        segments: List[Union[str, RichText]] = []
        for item in others:
            segments.append(self)
            segments.append(item)
        return RichText(segments[1:]) if len(segments) > 0 else RichText("")

    def replace(self, old: str, new: str):
        new_segments = [
            RichText(seg[0].replace(old, new), *seg[1:])
            for seg in self.segments
        ]
        return RichText(new_segments)

_VT100Colors = {
    Color.DEFAULT: 39,
    Color.GREEN: 92,
    Color.CYAN: 96,
    Color.YELLOW: 93,
    Color.RED: 91,
    Color.GRAY: 97,
}

def to_vt100(text: RichText) -> str:
    """
    Returns a pure string encoding of `text` by inserting the corresponding
    VT100 escape codes.
    """
    assert isinstance(text, RichText), type(text)
    output = ''
    for substr, foreground, background, style in text.segments:
        output += '\x1b[0' # reset all text attributes
        output +=  ';' + str(_VT100Colors[foreground])
        output +=  ';' + str(_VT100Colors[background] + 10)
        if style & Style.BOLD:
            output += ';1'
        if style & Style.UNDERLINE:
            output += ';4'
        output += 'm' + substr

    if len(text.segments) > 0:
        output += '\x1b[0m' # reset all attributes
    return output

def print_rich_text(text: RichText):
    print(to_vt100(text))
