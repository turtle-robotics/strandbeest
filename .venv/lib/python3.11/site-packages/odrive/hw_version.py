
import re
from typing import NamedTuple, Tuple

class HwVersion(NamedTuple):
    """
    Represents a hardware version triplet.
    See also hw_version.hpp and hw_version.dart.
    """
    product_line: int
    version: int
    variant: int

    @staticmethod
    def from_string(arg: str):
        """
        Constructs a HwVersion from a string of the form "4.4.58".
        """
        match = re.match(r'^([0-9]+)\.([0-9]+).([0-9]+)$', arg)
        if match is None:
            raise ValueError(f"{arg} is not a valid board triplet")
        return HwVersion(*(int(i) for i in match.groups()))

    @staticmethod
    def from_tuple(arg: Tuple[int, int, int]):
        """
        Constructs a HwVersion from a tuple or list of the form (4, 4, 58).
        """
        assert len(arg) == 3
        assert all([type(a) == int for a in arg])
        return HwVersion(*arg)

    @staticmethod
    def from_json(json):
        return HwVersion.from_tuple(json)

    @property
    def display_name(self):
        """
        Returns a display name such as "ODrive Pro" or "unknown device"
        corresponding to this board version.
        See also hw_version.hpp.
        """
        if self.product_line == 3:
            return f"ODrive v3.{self.version}-{self.variant}V"
        elif self.product_line == 4:
            return {
                0: "ODrive Pro v4.0",
                1: "ODrive Pro v4.1",
                2: "ODrive Pro v4.2",
                3: "ODrive Pro v4.3",
                4: "ODrive Pro",
            }.get(self.version, "unknown ODrive Pro")
        elif self.product_line == 5:
            return {
                0: "ODrive S1 X1",
                1: "ODrive S1 X3",
                2: "ODrive S1",
            }.get(self.version, "unknown ODrive S")
        elif self.product_line == 6:
            return {
                0: "ODrive Micro X1",
                1: "ODrive Micro X3",
                2: "ODrive Micro X4",
            }.get(self.version, "unknown ODrive Micro")
        elif self.product_line == 7:
            return {
                0: "ODrive N23 X1",
            }.get(self.version, "unknown ODrive N23")
        else:
            return "unknown device"

    @property
    def dot_string(self):
        return f"{self.product_line}.{self.version}.{self.variant}"

    def to_json(self):
        return [self.product_line, self.version, self.variant]

    def to_tuple(self):
        return (self.product_line, self.version, self.variant)
