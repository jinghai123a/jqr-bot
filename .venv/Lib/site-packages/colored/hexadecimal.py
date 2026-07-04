#!/usr/bin/env python
# -*- coding: utf-8 -*-

from __future__ import annotations

from .exceptions import InvalidHexColor
from .library import Library


class Hex:
    """Provides methods for finding the nearest ANSI color code from a HEX color value."""

    def find(self, color: str) -> str:
        """ Contribution by Fredrik Klasson """

        if not color.startswith('#') or len(color) not in (4, 7):
            raise InvalidHexColor(f'InvalidHexColor: {color}')

        try:
            int(color[1:], 16)
        except ValueError as exc:
            raise InvalidHexColor(f'InvalidHexColor: {color}') from exc

        # Extend shorthand #ABC -> #AABBCC, like in CSS
        if len(color) == 4:
            color = '#' + color[1] * 2 + color[2] * 2 + color[3] * 2

        # Try an exact lookup, trying to favor lower numbers
        # (e.g. find 10 instead of 46 for #00FF00)
        for code, hex_color in Library.HEX_COLORS.items():
            if hex_color == color:
                return code

        # Try to find nearest match using a simple least squares fit.
        # We could try to factor in human perception bias by weighting
        # as suggested by <https://stackoverflow.com/a/1847112> but for
        # now lets just KISS and make upp our minds later, no?
        # (we do skip the sqrt since we just care for the relative value)

        # The reference color
        r, g, b = (int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16))

        min_cube_d: int = self.square(0xFFFFFF)
        nearest: str = '15'

        for code, hex_color in Library.HEX_COLORS.items():
            cube_d: int = self.fit(hex_color[1:3], r) + self.fit(hex_color[3:5], g) + self.fit(hex_color[5:7], b)
            if cube_d < min_cube_d:
                min_cube_d = cube_d
                nearest = code

        return nearest

    @staticmethod
    def square(x: int) -> int:
        """Calculates the square of a given integer.

        Args:
            x (int): The integer number.

        Returns:
            int: The square of the input number.
        """
        return x * x

    def fit(self, hex_val: str, ref: int) -> int:
        """Calculates a component of the color difference for nearest match.

        This method converts a hexadecimal color component string to an integer,
        calculates the difference with a reference integer, and then applies
        the 'square' method to this difference. It's typically used as part of
        a least squares fit to find the closest color match.

        Args:
            hex_val (str): A string representing a two-digit hexadecimal color component (e.g., 'FF', '00').
            ref (int): An integer representing the reference color component (0-255).

        Returns:
            int: The result of applying the 'square' method to the difference
                 between the integer value of `hex_val` and `ref`.
        """
        return self.square(int(hex_val, 16) - ref)
