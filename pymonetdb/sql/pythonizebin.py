# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0.  If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Copyright 1997 - July 2008 CWI, August 2008 - 2016 MonetDB B.V.

"""
functions for converting binary result sets to Python objects
"""

from abc import abstractmethod
import array
from decimal import Decimal
import json
from math import isnan
import sys
from typing import Any, Callable, List, Optional

from pymonetdb.sql import types
import pymonetdb.sql.cursors


INT_WIDTH_TO_ARRAY_TYPE = {}
for code in 'bhilq':
    bit_width = 8 * array.array(code).itemsize
    INT_WIDTH_TO_ARRAY_TYPE[bit_width] = code

FLOAT_WIDTH_TO_ARRAY_TYPE = {}
for code in 'fd':
    bit_width = 8 * array.array(code).itemsize
    FLOAT_WIDTH_TO_ARRAY_TYPE[bit_width] = code

# very unlikely but if we ever encounter a Python with highly unstandard
# float sizes we want to know
assert FLOAT_WIDTH_TO_ARRAY_TYPE[32] == 'f'
assert FLOAT_WIDTH_TO_ARRAY_TYPE[64] == 'd'


class BinaryDecoder:
    @abstractmethod
    def decode(self, server_endian: str, data: memoryview) -> List[Any]:
        """Interpret the given bytes as a list of Python objects"""
        pass


class IntegerDecoder(BinaryDecoder):
    array_letter: str
    null_value: int
    mapper: Optional[Callable[[int], Any]]

    def __init__(self,
                 width: int,
                 mapper: Optional[Callable[[int], Any]] = None):
        self.mapper = mapper
        self.array_letter = INT_WIDTH_TO_ARRAY_TYPE[width]
        self.null_value = -(1 << (width - 1))

    def decode(self, server_endian: str, data: memoryview) -> List[Any]:
        arr = array.array(self.array_letter)
        arr.frombytes(data)
        if server_endian != sys.byteorder:
            arr.byteswap()
        if self.mapper:
            m = self.mapper
            values = [v if v != self.null_value else None for v in arr]
            values = [m(v) if v != self.null_value else None for v in arr]
        else:
            values = [v if v != self.null_value else None for v in arr]
        return values


class HugeIntDecoder(BinaryDecoder):
    mapper: Optional[Callable[[int], Any]]

    def __init__(self, mapper: Optional[Callable[[int], Any]] = None):
        self.mapper = mapper

    def decode(self, server_endian: str, data: memoryview) -> List[Any]:
        # we want to know if the incoming data is big or little endian but we have
        # to reconstruct that from 'wrong_endian'
        # we cannot directly decode 128 bits but we can decode 32 bits
        letter = INT_WIDTH_TO_ARRAY_TYPE[64].upper()
        arr = array.array(letter)
        arr.frombytes(data)
        if server_endian != sys.byteorder:
            arr.byteswap()
        # maybe some day we can come up with something faster
        result: List[Optional[int]] = []
        high1 = 1 << 64
        null_value = 1 << 127
        wrap = 1 << 128
        (hi_idx, lo_idx) = (0, 1) if server_endian == 'big' else (1, 0)
        if self.mapper is None:
            for i in range(0, len(arr), 2):
                hi = arr[i + hi_idx]
                lo = arr[i + lo_idx]
                n = high1 * hi + lo
                if n == null_value:
                    result.append(None)
                elif n >= null_value:
                    result.append(n - wrap)
                else:
                    result.append(n)
        else:
            mapper = self.mapper
            for i in range(0, len(arr), 2):
                hi = arr[i + hi_idx]
                lo = arr[i + lo_idx]
                n = high1 * hi + lo
                if n == null_value:
                    result.append(None)
                elif n >= null_value:
                    result.append(mapper(n - wrap))
                else:
                    result.append(mapper(n))
        return result


class FloatDecoder(BinaryDecoder):
    array_letter: str

    def __init__(self, width: int):
        self.array_letter = FLOAT_WIDTH_TO_ARRAY_TYPE[width]

    def decode(self, server_endian: str, data: memoryview) -> List[Any]:
        arr = array.array(self.array_letter)
        arr.frombytes(data)
        if server_endian != sys.byteorder:
            arr.byteswap()
        values = [v if not isnan(v) else None for v in arr]
        return values


def _decode_utf8(x: bytes) -> str:
    return str(x, 'utf-8')


class ZeroDelimitedDecoder(BinaryDecoder):
    converter: Callable[[bytes], Any]

    def __init__(self, converter: Callable[[bytes], Any]):
        self.converter = converter

    def decode(self, _wrong_endian, data: memoryview) -> List[Any]:
        null_value = b'\x80'
        # tobytes causes a copy but I don't see how that can be avoided
        parts = data.tobytes().split(b'\x00')
        parts.pop()  # empty tail element caused by trailing \x00
        conv = self.converter
        values = [conv(v) if v != null_value else None for v in parts]
        return values


def get_decoder(cursor: 'pymonetdb.sql.cursors.Cursor', colno: int) -> Optional[BinaryDecoder]:
    assert cursor.description
    description = cursor.description[colno]
    type_code = description.type_code
    mapper = mapping.get(type_code)
    if not mapper:
        return None
    decoder = mapper(cursor, colno)
    return decoder


def make_decimal_decoder(cursor: 'pymonetdb.sql.cursors.Cursor', colno: int) -> BinaryDecoder:
    assert cursor.description
    description: 'pymonetdb.sql.cursors.Description' = cursor.description[colno]
    scale = 10 ** description.scale
    precision = description.precision

    def mapper(n):
        return Decimal(n) / scale

    if precision <= 2:
        bit_width = 8
    elif precision <= 4:
        bit_width = 16
    elif precision <= 9:
        bit_width = 32
    elif precision <= 18:
        bit_width = 64
    elif precision <= 38:
        # IntegerDecoder doesn't support 128
        return HugeIntDecoder(mapper=mapper)
        bit_width = 128
    else:
        # as far as we know MonetDB only supports up to 38
        assert precision <= 38

    return IntegerDecoder(bit_width, mapper=mapper)


mapping = {
    types.TINYINT: lambda cursor, colno: IntegerDecoder(8),
    types.SMALLINT: lambda cursor, colno: IntegerDecoder(16),
    types.INT: lambda cursor, colno: IntegerDecoder(32),
    types.BIGINT: lambda cursor, colno: IntegerDecoder(64),
    types.HUGEINT: lambda cursor, colno: HugeIntDecoder(),

    types.BOOLEAN: lambda cursor, colno: IntegerDecoder(8, mapper=bool),

    types.CHAR: lambda cursor, colno: ZeroDelimitedDecoder(_decode_utf8),
    types.VARCHAR: lambda cursor, colno: ZeroDelimitedDecoder(_decode_utf8),
    types.CLOB: lambda cursor, colno: ZeroDelimitedDecoder(_decode_utf8),
    types.URL: lambda cursor, colno: ZeroDelimitedDecoder(_decode_utf8),
    types.JSON: lambda cursor, colno: ZeroDelimitedDecoder(json.loads),

    types.DECIMAL: make_decimal_decoder,

    types.REAL: lambda cursor, colno: FloatDecoder(32),
    types.FLOAT: lambda cursor, colno: FloatDecoder(64),  # MonetDB defines FLOAT to be 64 bits
    types.DOUBLE: lambda cursor, colno: FloatDecoder(64),

    # types.DATE: py_date,
    # types.TIME: py_time,
    # types.TIMESTAMP: py_timestamp,
    # types.TIMETZ: py_timetz,
    # types.TIMESTAMPTZ: py_timestamptz,

    # types.MONTH_INTERVAL: int,
    # types.SEC_INTERVAL: py_sec_interval,
    # types.DAY_INTERVAL: py_day_interval,


    # types.INET: str,
    # types.UUID: uuid.UUID,
    # types.XML: str,

    # Not supported in COPY BINARY or the binary protocol
    # types.BLOB: py_bytes,
    # types.GEOMETRY: strip,
    # types.GEOMETRYA: strip,
    # types.MBR: strip,
    # types.OID: oid,

    # These are mentioned in pythonize.py but as far as I know the server never
    # produces them
    #
    # types.SERIAL: int,
    # types.SHORTINT: int,
    # types.MEDIUMINT: int,
    # types.LONGINT: int,
    # types.WRD: int,


}
