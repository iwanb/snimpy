##############################################################################
##                                                                          ##
## snimpy -- Interactive SNMP tool                                          ##
##                                                                          ##
## Copyright (C) Vincent Bernat <bernat@luffy.cx>                           ##
##                                                                          ##
## Permission to use, copy, modify, and distribute this software for any    ##
## purpose with or without fee is hereby granted, provided that the above   ##
## copyright notice and this permission notice appear in all copies.        ##
##                                                                          ##
## THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES ##
## WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF         ##
## MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR  ##
## ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES   ##
## WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN    ##
## ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF  ##
## OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.           ##
##                                                                          ##
##############################################################################

"""
Snimpy will use the types defined in this module to make a bridge
between the MIB and SNMP.
"""

import struct
import socket
from datetime import timedelta
from pysnmp.proto import rfc1902

from snimpy import mib, snmp
try: long(1)
except NameError: long = int

class Type(object):
    """Base class for all types"""

    consume = 0                 # Consume all suboid if built from OID

    def __new__(cls, entity, value):
        """Create a new typed value

        @param entity: L{mib.Entity} instance
        @param value: value to set
        @return: an instance of the new typed value
        """
        if not isinstance(entity, mib.Entity):
            raise TypeError("{0} not a mib.Entity instance".format(entity))
        if entity.type != cls:
            raise ValueError("MIB node is {0}. We are {1}".format(entity.type,
                                                                  cls))

        if not isinstance(value, Type):
            value = cls._internal(entity, value)
        else:
            value = cls._internal(entity, value._value)
        if issubclass(cls, str):
            self = str.__new__(cls, value)
        elif issubclass(cls, long):
            self = long.__new__(cls, value)
        else:
            self = object.__new__(cls)
        self._value = value
        self.entity = entity
        self.fmt = entity.fmt
        return self

    @classmethod
    def _internal(cls, entity, value):
        """Get internal value for a given value."""
        raise NotImplementedError # pragma: no cover

    def pack(self):
        raise NotImplementedError # pragma: no cover

    def toOid(self):
        """Convert to an OID.

        If this function is implemented, then class function fromOid
        should also be implemented as the "invert" function of this one.

        This function only works if the entity is used as an index!
        Otherwise, it should raises NotImplementedError.

        @return: OID that can be used as index
        """
        raise NotImplementedError # pragma: no cover

    @classmethod
    def fromOid(cls, entity, oid):
        """Create instance from an OID.

        This is the sister function of toOid.

        @param oid: OID to use to create an instance
        @param entity: MIB entity we want to instantiate
        @return: a couple C{(l, v)} with C{l} the number of suboid
           needed to create the instance and v the instance created from
           the OID
        """
        raise NotImplementedError # pragma: no cover

    @classmethod
    def _fixedOrImplied(cls, entity):
        """Determine if the given entity is fixed-len or implied.

        This function is an helper that is used for String and
        Oid. When converting a variable-length type to an OID, we need
        to prefix it by its len or not depending of what the MIB say.

        @param entity: entity to check
        @return: C{fixed} if it is fixed-len, C{implied} if implied var-len,
           C{False} otherwise
        """
        if entity.ranges and type(entity.ranges) is not tuple and type(entity.ranges) is not list:
            # Fixed length
            return "fixed"

        # We have a variable-len string/oid. We need to know if it is implied.
        try:
            table = entity.table
        except:
            raise NotImplementedError("{0} is not an index of a table".format(entity))
        indexes = [str(a) for a in table.index]
        if str(entity) not in indexes:
            raise NotImplementedError("{0} is not an index of a table".format(entity))
        if str(entity) != indexes[-1] or not table.implied:
            # This index is not implied
            return False
        return "implied"

    def display(self):
        return str(self)

    def __str__(self):
        return str(self._value)

    def __repr__(self):
        try:
            return '<{0}: {1}>'.format(self.__class__.__name__,
                                       self.display())
        except:
            return '<{0} ????>'.format(self.__class__.__name__)

class IpAddress(Type):
    """Class for IP address"""

    @classmethod
    def _internal(cls, entity, value):
        if isinstance(value, list) or isinstance(value, tuple):
            value = ".".join([str(a) for a in value])
        try:
            value = socket.inet_ntoa(value)
        except:
            try:
                value = socket.inet_ntoa(socket.inet_aton(value))
            except:
                raise ValueError("{0!r} is not a valid IP".format(value))
        return [int(a) for a in value.split(".")]

    def pack(self):
        return rfc1902.IpAddress(str(".".join(["{0:d}".format(x) for x in self._value])))

    def toOid(self):
        return tuple(self._value)

    @classmethod
    def fromOid(cls, entity, oid):
        if len(oid) < 4:
            raise ValueError("{0!r} is too short for an IP address".format(oid))
        return (4, cls(entity, oid[:4]))

    def __str__(self):
        return ".".join([str(a) for a in self._value])

    def __cmp__(self, other):
        if not isinstance(other, IpAddress):
            try:
                other = IpAddress(self.entity, other)
            except:
                raise NotImplementedError # pragma: no cover
        if self._value == other._value:
            return 0
        if self._value < other._value:
            return -1
        return 1

    def __getitem__(self, nb):
        return self._value[nb]

class String(Type, str):
    """Class for any string"""

    @classmethod
    def _internal(cls, entity, value):
        return str(value)

    def pack(self):
        return rfc1902.OctetString(self._value)

    def toOid(self):
        # To convert properly to OID, we need to know if it is a
        # fixed-len string, an implied string or a variable-len
        # string.
        if self._fixedOrImplied(self.entity):
            return tuple(ord(a) for a in self._value)
        return tuple([len(self._value)] + [ord(a) for a in self._value])

    @classmethod
    def fromOid(cls, entity, oid):
        type = cls._fixedOrImplied(entity)
        if type == "implied":
            # Eat everything
            return (len(oid), cls(entity,"".join([chr(x) for x in oid])))
        if type == "fixed":
            l = entity.ranges
            if len(oid) < l:
                raise ValueError(
                    "{0} is too short for wanted fixed string (need at least {1:d})".format(oid, l))
            return (l, cls(entity,b"".join([chr(x) for x in oid[:l]])))
        # This is var-len
        if not oid:
            raise ValueError("empty OID while waiting for var-len string")
        l = oid[0]
        if len(oid) < l + 1:
            raise ValueError(
                "{0} is too short for variable-len string (need at least {1:d})".format(oid, l))
        return (l+1, cls(entity,b"".join([chr(x) for x in oid[1:(l+1)]])))

    def _display(self, fmt):
        i = 0               # Position in self._value
        j = 0               # Position in fmt
        result = ""
        while i < len(self._value):
            if j < len(fmt):
                # repeater
                if fmt[j] == "*":
                    repeat = ord(self._value[i])
                    j += 1
                    i += 1
                else:
                    repeat = 1
                # length
                length = ""
                while fmt[j].isdigit():
                    length += fmt[j]
                    j += 1
                length = int(length)
                # format
                format = fmt[j]
                j += 1
                # seperator
                if j < len(fmt) and \
                        fmt[j] != "*" and not fmt[j].isdigit():
                    sep = fmt[j]
                    j += 1
                else:
                    sep = ""
                # terminator
                if j < len(fmt) and \
                        fmt[j] != "*" and not fmt[j].isdigit():
                    term = fmt[j]
                    j += 1
                else:
                    term = ""
            # building
            for r in range(repeat):
                bytes = self._value[i:i+length]
                i += length
                if format in ['o', 'x', 'd']:
                    if length > 8:
                        raise ValueError(
                            "don't know how to handle integers more than 4 bytes long")
                    bytes = b"\x00"*(4-length) + bytes
                    number = struct.unpack(b"!l", bytes)[0]
                    if format == "o":
                        result += oct(number)
                    elif format == "x":
                        result += hex(number)[2:]
                    else:       # format == "d":
                        result += str(number)
                else: # should be a, but can be something else like t
                    result += bytes
                result += sep
            if sep and term:
                result = result[:-1]
            result += term
        if term or sep:
            result = result[:-1]
        return result

    def display(self):
        if self.fmt:
            return self._display(self.fmt)
        if "\\x" not in repr(self._value):
            return self._value
        return "0x" + " ".join([("0{0}".format(hex(ord(a))[2:]))[-2:] for a in self._value])

    def __eq__(self, other):
        if self.display() == other:
            return True
        if str(self) == other:
            return True
        return False

    def __ne__(self, other):
        return not(self.__eq__(other))

    def __ior__(self, value):
        nvalue = [ord(u) for u in self._value]
        if not isinstance(value, tuple) and not isinstance(value, list):
            value = [value]
        for v in value:
            if not isinstance(v, int) and not isinstance(v, long):
                raise NotImplementedError(
                    "on string, bit-operation are limited to integers")
            if len(nvalue) < v/8 + 1:
                nvalue.extend([0] * (v/8 + 1 - len(self._value)))
            nvalue[v/8] |= 1 << (7-v%8)
        return self.__class__(self.entity, b"".join([chr(i) for i in nvalue]))

    def __isub__(self, value):
        nvalue = [ord(u) for u in self._value]
        if not isinstance(value, tuple) and not isinstance(value, list):
            value = [value]
        for v in value:
            if not isinstance(v, int) and not isinstance(v, long):
                raise NotImplementedError(
                    "on string, bit-operation are limited to integers")
            if len(nvalue) < v/8 + 1:
                continue
            nvalue[v/8] &= ~(1 << (7-v%8))
        return self.__class__(self.entity, b"".join([chr(i) for i in nvalue]))
        return self

    def __and__(self, value):
        nvalue = [ord(u) for u in self._value]
        if not isinstance(value, tuple) and not isinstance(value, list):
            value = [value]
        for v in value:
            if not isinstance(v, int) and not isinstance(v, long):
                raise NotImplementedError(
                    "on string, bit-operation are limited to integers")
            if len(nvalue) < v/8 + 1:
                return False
            if not(nvalue[v/8] & (1 << (7-v%8))):
                return False
        return True


class MacAddress(String):

    @classmethod
    def _internal(cls, entity, value):
        return str(value)

    def display(self):
        return ":".join(["{0:02x}".format(ord(a)) for a in self._value])


class Integer(Type, long):
    """Class for any integer"""

    @classmethod
    def _internal(cls, entity, value):
        return long(value)

    def pack(self):
        if self._value >= (1 << 64):
            raise OverflowError("too large to be packed")
        if self._value >= (1 << 32):
            return rfc1902.Counter64(self._value)
        if self._value >= 0:
            return rfc1902.Integer(self._value)
        if self._value >= -(1 << 31):
            return rfc1902.Integer(self._value)
        raise OverflowError("too small to be packed")

    def toOid(self):
        return (self._value,)

    @classmethod
    def fromOid(cls, entity, oid):
        if len(oid) < 1:
            raise ValueError("{0} is too short for an integer".format(oid))
        return (1, cls(entity, oid[0]))

    def display(self):
        if self.fmt:
            if self.fmt[0] == "x":
                return hex(self._value)
            if self.fmt[0] == "o":
                return oct(self._value)
            if self.fmt[0] == "b":
                if self._value == 0:
                    return "0"
                if self._value > 0:
                    v = self._value
                    r = ""
                    while v > 0:
                        r = str(v%2) + r
                        v = v>>1
                    return r
            elif self.fmt[0] == "d" and \
                    len(self.fmt) > 2 and \
                    self.fmt[1] == "-":
                dec = int(self.fmt[2:])
                result = str(self._value)
                if len(result) < dec + 1:
                    result = "0"*(dec + 1 - len(result)) + result
                return "{0}.{1}".format(result[:-2], result[-2:])
        return self._value

    def __eq__(self, other):
        if isinstance(other, str):
            if self.display() == other:
                return True
        return self._value == other

    def __ne__(self, other):
        return not(self.__eq__(other))

class Unsigned32(Integer):
    def pack(self):
        if self._value >= (1 << 32):
            raise OverflowError("too large to be packed")
        if self._value < 0:
            raise OverflowError("too small to be packed")
        return rfc1902.Unsigned32(self._value)

class Unsigned64(Integer):
    def pack(self):
        if self._value >= (1 << 64):
            raise OverflowError("too large to be packed")
        if self._value < 0:
            raise OverflowError("too small to be packed")
        return rfc1902.Counter64(self._value)

class Enum(Integer):
    """Class for enumeration"""

    @classmethod
    def _internal(cls, entity, value):
        if value in entity.enum:
            return value
        for (k, v) in entity.enum.iteritems():
            if (v == value):
                return k
        try:
            return long(value)
        except:
            raise ValueError("{0!r} is not a valid value for {1}".format(value,
                                                                       entity))

    def pack(self):
        return rfc1902.Integer(self._value)

    @classmethod
    def fromOid(cls, entity, oid):
        if len(oid) < 1:
            raise ValueError("{0!r} is too short for an enumeration".format(oid))
        return (1, cls(entity, oid[0]))

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            try:
                other = self.__class__(self.entity, other)
            except:
                raise NotImplementedError # pragma: no cover
        return self._value == other._value

    def __ne__(self, other):
        return not(self.__eq__(other))

    def __str__(self):
        if self._value in self.entity.enum:
            return "{0}({1:d})".format(self.entity.enum[self._value], self._value)
        else:
            return str(self._value)

    def display(self):
        return str(self)

class Oid(Type):
    """Class for OID"""

    @classmethod
    def _internal(cls, entity, value):
        if isinstance(value, list) or isinstance(value, tuple):
            return tuple([int(v) for v in value])
        elif isinstance(value, str):
            return tuple([int(i) for i in value.split(".") if i])
        elif isinstance(value, mib.Entity):
            return tuple(value.oid)
        else:
            raise TypeError("don't know how to convert {0!r} to OID".format(value))

    def pack(self):
        return rfc1902.univ.ObjectIdentifier(self._value)

    def toOid(self):
        if self._fixedOrImplied(self.entity):
            return self._value
        return tuple([len(self._value)] + list(self._value))

    @classmethod
    def fromOid(cls, entity, oid):
        if cls._fixedOrImplied(entity) == "fixed":
            # A fixed OID? We don't like this. Provide a real example.
            raise ValueError("{0!r} seems to be a fixed-len OID index. Odd.".format(entity))
        if not cls._fixedOrImplied(entity):
            # This index is not implied. We need the len
            if len(oid) < 1:
                raise ValueError("{0!r} is too short for a not implied index".format(entity))
            l = oid[0]
            if len(oid) < l + 1:
                raise ValueError("{0!r} has an incorrect size (needs at least {1:d})".format(oid, l))
            return (l+1, cls(entity, oid[1:(l+1)]))
        else:
            # Eat everything
            return (len(oid), cls(entity, oid))

    def __str__(self):
        return ".".join([str(x) for x in self._value])

    def __cmp__(self, other):
        if not isinstance(other, Oid):
            other = Oid(self.entity, other)
        if tuple(self._value) == tuple(other._value):
            return 0
        if self._value > other._value:
            return 1
        return -1

    def __contains__(self, item):
        """Test if item is a sub-oid of this OID"""
        if not isinstance(item, Oid):
            item = Oid(self.entity, item)
        return tuple(item._value[:len(self._value)]) == \
            tuple(self._value[:len(self._value)])


class Boolean(Enum):
    """Class for boolean"""

    @classmethod
    def _internal(cls, entity, value):
        if type(value) is bool:
            if value:
                return Enum._internal(entity, "true")
            else:
                return Enum._internal(entity, "false")
        else:
            return Enum._internal(entity, value)

    def __nonzero__(self):
        if self._value == 1:
            return True
        else:
            return False

class Timeticks(Type):
    """Class for timeticks"""

    @classmethod
    def _internal(cls, entity, value):
        if isinstance(value, int) or isinstance(value, long):
            # Value in centiseconds
            return timedelta(0, value/100.)
        elif isinstance(value, timedelta):
            return value
        else:
            raise TypeError("dunno how to handle {0!r} ({1})".format(value, type(value)))

    def __int__(self):
        return self._value.days*3600*24*100 + self._value.seconds*100 + \
            self._value.microseconds/10000

    def toOid(self):
        return (int(self),)

    @classmethod
    def fromOid(cls, entity, oid):
        if len(oid) < 1:
            raise ValueError("{0!r} is too short for a timetick".format(oid))
        return (1, cls(entity, oid[0]))

    def pack(self):
        return rfc1902.TimeTicks(int(self))

    def __str__(self):
        return str(self._value)

    def __cmp__(self, other):
        if isinstance(other, Timeticks):
            other = other._value
        elif isinstance(other, int) or isinstance(other, long):
            other = timedelta(0, other/100.)
        elif not isinstance(other, timedelta):
            raise NotImplementedError("only compare to int or timedelta, not {0}".format(type(other)))
        if self._value == other:
            return 0
        if self._value < other:
            return -1
        return 1

    def __eq__(self, other):
        return self.__cmp__(other) == 0
    def __ne__(self, other):
        return self.__cmp__(other) != 0
    def __lt__(self, other):
        return self.__cmp__(other) < 0
    def __gt__(self, other):
        return self.__cmp__(other) > 0

class Bits(Type):
    """Class for bits"""

    @classmethod
    def _internal(cls, entity, value):
        bits = set()
        tryalternate = False
        if isinstance(value, str):
            for i,x in enumerate(value):
                if ord(x) == 0:
                    continue
                for j in range(8):
                    if ord(x) & (1 << (7-j)):
                        if j not in entity.enum:
                            tryalternate = True
                            break
                        bits.add(j)
                if tryalternate:
                    break
            if not tryalternate:
                return bits
            else:
                bits = set()
        elif not isinstance(value, (tuple, list, set, frozenset)):
            value = set([value])
        for v in value:
            found = False
            if v in entity.enum:
                bits.add(v)
                found = True
            else:
                for (k, t) in entity.enum.iteritems():
                    if (t == v):
                        bits.add(k)
                        found = True
                        break
            if not found:
                raise ValueError("{0!r} is not a valid bit value".format(v))
        return bits

    def pack(self):
        string = []
        for b in self._value:
            if len(string) < b/16 + 1:
                string.extend([0]*(b/16 - len(string)+1))
            string[b/16] |= 1 << (7 - b%16)
        return rfc1902.Bits(b"".join([chr(x) for x in string]))

    def __eq__(self, other):
        if isinstance(other, str):
            other = [other]
        if not isinstance(other, Bits):
            other = Bits(self.entity, other)
        return self._value == other._value

    def __str__(self):
        result = []
        for b in sorted(self._value):
            result.append("{0}({1:d})".format(self.entity.enum[b], b))
        return ", ".join(result)

    def __and__(self, other):
        if isinstance(other, str):
            other = [other]
        if not isinstance(other, Bits):
            other = Bits(self.entity, other)
        print self._value & other._value, self._value, other._value
        return len(self._value & other._value) > 0

    def __ior__(self, other):
        if isinstance(other, str):
            other = [other]
        if not isinstance(other, Bits):
            other = Bits(self.entity, other)
        self._value |= other._value
        return self

    def __isub__(self, other):
        if isinstance(other, str):
            other = [other]
        if not isinstance(other, Bits):
            other = Bits(self.entity, other)
        self._value -= other._value
        return self

def build(mibname, entity, value):
    """Build a new basic type with the given value.

    @param mibname: MIB to use to locate the entity
    @param entity: entity that will be attached to this type
    @param value: initial value to set for the type
    @return: a Type instance
    """
    m = mib.get(mibname, entity)
    t = m.type(m, value)
    return t
