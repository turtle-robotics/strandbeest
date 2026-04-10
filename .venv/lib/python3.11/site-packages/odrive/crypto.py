"""
Provides cryptographic methods for client/server authentication and device
provisioning and authentication.

The following algorithms and encodings are used:

Signature algorithm: NIST P-256 (aka SECP256R1)
Hashing algorithm: SHA-256

Private key: 32 bytes private value (big endian)
Public key: 32 bytes X coordinate (big endian) + 32 bytes Y coordinate (big endian)
Signature: 32 bytes R (big endian) + 32 bytes S (big endian)

These match the algorithms/encodings in ODrive hardware and must therefore not
be changed.

The following copyright applies to all core cryptographic code in this file:
################################################################################
# Copyright (c) 2022 Anirudha Bose                                             #
# Adapted from https://onyb.gitbook.io/secp256k1-python under the MIT license. #
################################################################################
"""

import base64
import hashlib
from random import randint
from typing import Optional, NamedTuple

class InvalidSignature(Exception):
    pass

def _gcd_extended(a, b):
    """Extended Euclidean algorithm"""
    if a == 0:
        return b, 0, 1
    gcd, x, y = _gcd_extended(b % a, a)
    return (gcd, y - (b//a) * x, x)

def _mod_pow(a, b, z):
    # This function is only needed for Python <3.8. For 3.8+ the built-in
    # function does all we need.
    if b > 0:
        return pow(a, b, z)
    elif b == -1:
        return _gcd_extended(a, z)[1]
    else:
        raise Exception("not implemented")

class PrimeGaloisField(NamedTuple):
    prime: int

    def __contains__(self, field_value: "FieldElement") -> bool:
        # called whenever you do: <FieldElement> in <PrimeGaloisField>
        return 0 <= field_value.value < self.prime

class FieldElement(NamedTuple):
    value: int
    field: PrimeGaloisField

    def __repr__(self):
        return "0x" + f"{self.value:x}".zfill(64)
        
    @property
    def P(self) -> int:
        return self.field.prime
    
    def __add__(self, other: "FieldElement") -> "FieldElement":
        return FieldElement(
            value=(self.value + other.value) % self.P,
            field=self.field
        )
    
    def __sub__(self, other: "FieldElement") -> "FieldElement":
        return FieldElement(
            value=(self.value - other.value) % self.P,
            field=self.field
        )

    def __rmul__(self, scalar: int) -> "FieldElement":
        return FieldElement(
            value=(self.value * scalar) % self.P,
            field=self.field
        )

    def __mul__(self, other: "FieldElement") -> "FieldElement":
        return FieldElement(
            value=(self.value * other.value) % self.P,
            field=self.field
        )
        
    def __pow__(self, exponent: int) -> "FieldElement":
        return FieldElement(
            value=_mod_pow(self.value, exponent, self.P),
            field=self.field
        )

    def __truediv__(self, other: "FieldElement") -> "FieldElement":
        other_inv = other ** -1
        return self * other_inv

class EllipticCurve(NamedTuple):
    a: FieldElement
    b: FieldElement

    @property
    def field(self):
        assert self.a.field == self.b.field
        return self.a.field
    
    def __contains__(self, point: "Point") -> bool:
        x, y = point.x, point.y
        return y ** 2 == x ** 3 + self.a * x + self.b

class Point():
    def __init__(self, x: int, y: int, curve: EllipticCurve):
        # Encapsulate int coordinates in FieldElement
        self.x = None if x is None else FieldElement(x, curve.field)
        self.y = None if y is None else FieldElement(y, curve.field)
        self.curve = curve

        # Ignore validation for I
        if self.x is None and self.y is None:
            return

        # Verify if the point satisfies the curve equation
        if self not in self.curve:
            raise ValueError

    def __eq__(self, other):
        return isinstance(other, Point) and (self.x, self.y, self.curve) == (other.x, other.y, other.curve)

    def __hash__(self):
        return hash((self.x, self.y, self.curve))

    def __add__(self, other):
        #################################################################
        # Point Addition for P₁ or P₂ = I   (identity)                  #
        #                                                               #
        # Formula:                                                      #
        #     P + I = P                                                 #
        #     I + P = P                                                 #
        #################################################################
        if self == secp256r1_I:
            return other

        if other == secp256r1_I:
            return self

        #################################################################
        # Point Addition for X₁ = X₂   (additive inverse)               #
        #                                                               #
        # Formula:                                                      #
        #     P + (-P) = I                                              #
        #     (-P) + P = I                                              #
        #################################################################
        if self.x == other.x and self.y == (-1 * other.y):
            return secp256r1_I

        #################################################################
        # Point Addition for X₁ ≠ X₂   (line with slope)                #
        #                                                               #
        # Formula:                                                      #
        #     S = (Y₂ - Y₁) / (X₂ - X₁)                                 #
        #     X₃ = S² - X₁ - X₂                                         #
        #     Y₃ = S(X₁ - X₃) - Y₁                                      #
        #################################################################
        if self.x != other.x:
            x1, x2 = self.x, other.x
            y1, y2 = self.y, other.y

            s = (y2 - y1) / (x2 - x1)
            x3 = s ** 2 - x1 - x2
            y3 = s * (x1 - x3) - y1

            return self.__class__(
                x=x3.value,
                y=y3.value,
                curve=secp256r1
            )

        #################################################################
        # Point Addition for P₁ = P₂   (vertical tangent)               #
        #                                                               #
        # Formula:                                                      #
        #     S = ∞                                                     #
        #     (X₃, Y₃) = I                                              #
        #################################################################
        if self == other and self.y == float("inf"):
            return secp256r1_I

        #################################################################
        # Point Addition for P₁ = P₂   (tangent with slope)             #
        #                                                               #
        # Formula:                                                      #
        #     S = (3X₁² + a) / 2Y₁         .. ∂(Y²) = ∂(X² + aX + b)    #
        #     X₃ = S² - 2X₁                                             #
        #     Y₃ = S(X₁ - X₃) - Y₁                                      #
        #################################################################
        if self == other:
            x1, y1, a = self.x, self.y, self.curve.a

            s = (3 * x1 ** 2 + a) / (2 * y1)
            x3 = s ** 2 - 2 * x1
            y3 = s * (x1 - x3) - y1

            return self.__class__(
                x=x3.value,
                y=y3.value,
                curve=secp256r1
            )

        assert False

    def __rmul__(self, scalar: int) -> "Point":
        # Naive approach:
        #
        # result = I
        # for _ in range(scalar):  # or range(scalar % N)
        #     result = result + self
        # return result
        
        # Optimized approach using binary expansion
        current = self
        result = secp256r1_I
        while scalar:
            if scalar & 1:  # same as scalar % 2
                result = result + current
            current = current + current  # point doubling
            scalar >>= 1  # same as scalar / 2
        return result

class PrivateKey(NamedTuple):
    secret: int
    
    def public_key(self):
        return self.secret * secp256r1_G

PublicKey = Point

secp256r1_field = PrimeGaloisField(prime=0xffffffff00000001000000000000000000000000ffffffffffffffffffffffff)
secp256r1 = EllipticCurve(
    a=FieldElement(0xffffffff00000001000000000000000000000000fffffffffffffffffffffffc, secp256r1_field),
    b=FieldElement(0x5ac635d8aa3a93e7b3ebbd55769886bc651d06b0cc53b0f63bce3c3e27d2604b, secp256r1_field)
)

secp256r1_G = Point(
    x=0x6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296,
    y=0x4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5,
    curve=secp256r1
)

secp256r1_I = Point(x=None, y=None, curve=secp256r1)

# Order of the group generated by G, such that nG = I
secp256r1_N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551

def gen_key() -> PrivateKey:
    """
    Creates a new private key. The public key can be derived from this.
    """
    return PrivateKey(randint(0, secp256r1_N))

def get_private_bytes(private_key: PrivateKey) -> bytes:
    """
    Returns the raw byte representation of `private_key`.
    See file header for encoding details.
    """
    return private_key.secret.to_bytes(32, 'big')

def get_public_bytes(public_key: Point) -> bytes:
    """
    Returns the raw byte representation of `public_key`.
    See file header for encoding details.
    """
    return public_key.x.value.to_bytes(32, 'big') + public_key.y.value.to_bytes(32, 'big')

def load_private_key(private_bytes: bytes) -> PrivateKey:
    """
    Loads a private key object from the raw representation in `private_bytes`.
    See file header for encoding details.
    """
    assert len(private_bytes) == 32
    private_value = int.from_bytes(private_bytes, 'big')
    return PrivateKey(private_value)

def load_public_key(public_bytes: bytes) -> PublicKey:
    """
    Loads a public key object from the raw representation in `public_bytes`.
    See file header for encoding details.
    """
    assert len(public_bytes) == 64
    x_int = int.from_bytes(public_bytes[:32], 'big')
    y_int = int.from_bytes(public_bytes[32:], 'big')
    return Point(x_int, y_int, secp256r1)

def _sha256(data: bytes):
    alg = hashlib.sha256()
    alg.update(data)
    return int.from_bytes(alg.digest(), 'big')

def sign(private_key: PrivateKey, data: bytes) -> bytes:
    z = _sha256(data)

    e = private_key.secret
    k = randint(0, secp256r1_N)
    R = k * secp256r1_G
    r = R.x.value
    k_inv = _mod_pow(k, -1, secp256r1_N)
    s = ((z + r*e) * k_inv) % secp256r1_N
    
    return r.to_bytes(32, 'big') + s.to_bytes(32, 'big')
    
def verify(public_key: Point, signature: bytes, data: bytes) -> bool:
    z = _sha256(data)
    r = int.from_bytes(signature[:32], 'big')
    s = int.from_bytes(signature[32:], 'big')

    s_inv = _mod_pow(s, -1, secp256r1_N)
    u = (z * s_inv) % secp256r1_N
    v = (r * s_inv) % secp256r1_N
    
    if (u*secp256r1_G + v*public_key).x.value != r:
        raise InvalidSignature()

def verify_cert(certificate: bytes, device_public_key: Point, test_mode: bool = False):
    """
    Verifies the device certificate cryptographically against the ODrive master
    key.
    Format of `certificate` documented at ../README.md#device-certificate
    """
    assert len(certificate) == 272, len(certificate)

    message = certificate[:80] + get_public_bytes(device_public_key)
    verify(load_public_key(certificate[144:208]), certificate[80:144], message)

    message = b'ODrive batch key'.ljust(32, b'\0') + certificate[144:208]
    verify(test_master_key if test_mode else master_key, certificate[208:272], message)

def b64encode(buf: bytes) -> str:
    return base64.b64encode(buf).decode('utf-8')

def b64decode(buf: str) -> bytes:
    return base64.b64decode(buf.encode('utf-8'))

def safe_b64encode(buf: bytes) -> str:
    return base64.urlsafe_b64encode(buf).decode('utf-8').rstrip('=')

def safe_b64decode(buf: str) -> bytes:
    return base64.urlsafe_b64decode((buf + "=" * (-len(buf) % 4)).encode('utf-8'))

master_key = load_public_key(bytes([
    0x60, 0xea, 0x3e, 0x6d, 0xc1, 0x18, 0xa2, 0x1f,
    0x3a, 0x61, 0x99, 0x0c, 0x61, 0x6e, 0xe4, 0x4a,
    0x02, 0x68, 0x80, 0xa2, 0x5c, 0x70, 0x21, 0xac,
    0x6c, 0x63, 0x0b, 0x75, 0x39, 0x9b, 0x1b, 0xe2,
    0x7c, 0xd1, 0x34, 0xc5, 0xd4, 0xf2, 0xa9, 0x1e,
    0x0b, 0x23, 0x3a, 0x18, 0xb6, 0x43, 0xd5, 0x49,
    0x7a, 0xd9, 0xe9, 0x3b, 0x8a, 0x52, 0xfe, 0x92,
    0x95, 0x06, 0xcd, 0x46, 0x18, 0xcf, 0x4c, 0x59
]))

test_master_key_private = load_private_key(bytes([
    0xa9, 0x6a, 0x76, 0xd7, 0x54, 0x53, 0x2e, 0x2a,
    0x38, 0x7a, 0xc5, 0x54, 0x16, 0x53, 0x70, 0xf3,
    0x48, 0x84, 0x9a, 0xf1, 0x82, 0x11, 0xbf, 0xd2,
    0x1f, 0x3c, 0x05, 0xf7, 0xf3, 0xeb, 0xef, 0x08
]))

test_master_key = test_master_key_private.public_key()
