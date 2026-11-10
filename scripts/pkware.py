#!/usr/bin/env python3
"""PKWare DCL Implode/Explode, pure Python (port of node-pkware 6.0.0).

Multisim .ms14 / EW .ewprj wrap Electronics Workbench XML in this format:
    "MSMCompressedElectronicsWorkbenchXML" (36 bytes)
    uint64le total_xml_length
    repeat: uint32le block_raw_len, uint32le block_comp_len, block_comp_len bytes
Each block body is a raw PKWare DCL stream (2-byte header + bit stream).

No third-party deps. Verified against node-pkware 6.0.0 on a real .ms14.
"""

MAX_ALLOWED_LEN = 900000  # Multisim chunks at this boundary; encoder matches it

# --- tables (verbatim from node-pkware dist/constants.js) -------------------
DIST_CODE = [
    0x03, 0x0D, 0x05, 0x19, 0x09, 0x11, 0x01, 0x3E, 0x1E, 0x2E, 0x0E, 0x36, 0x16, 0x26, 0x06, 0x3A,
    0x1A, 0x2A, 0x0A, 0x32, 0x12, 0x22, 0x42, 0x02, 0x7C, 0x3C, 0x5C, 0x1C, 0x6C, 0x2C, 0x4C, 0x0C,
    0x74, 0x34, 0x54, 0x14, 0x64, 0x24, 0x44, 0x04, 0x78, 0x38, 0x58, 0x18, 0x68, 0x28, 0x48, 0x08,
    0xF0, 0x70, 0xB0, 0x30, 0xD0, 0x50, 0x90, 0x10, 0xE0, 0x60, 0xA0, 0x20, 0xC0, 0x40, 0x80, 0x00,
]
DIST_BITS = [
    2, 4, 4, 5, 5, 5, 5, 6, 6, 6, 6, 6, 6, 6, 6, 6,
    6, 6, 6, 6, 6, 6, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
    7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7, 7,
    8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8, 8,
]
LEN_BITS = [3, 2, 3, 3, 4, 4, 4, 5, 5, 5, 5, 6, 6, 6, 7, 7]
LEN_CODE = [0x05, 0x03, 0x01, 0x06, 0x0A, 0x02, 0x0C, 0x14, 0x04, 0x18, 0x08, 0x30, 0x10, 0x20, 0x40, 0x00]
EX_LEN_BITS = [0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8]
LEN_BASE = [0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07,
            0x08, 0x0A, 0x0E, 0x16, 0x26, 0x46, 0x86, 0x106]
CH_BITS_ASC = [
    0x0B, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x08, 0x07, 0x0C, 0x0C, 0x07, 0x0C, 0x0C,
    0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0D, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C,
    0x04, 0x0A, 0x08, 0x0C, 0x0A, 0x0C, 0x0A, 0x08, 0x07, 0x07, 0x08, 0x09, 0x07, 0x06, 0x07, 0x08,
    0x07, 0x06, 0x07, 0x07, 0x07, 0x07, 0x08, 0x07, 0x07, 0x08, 0x08, 0x0C, 0x0B, 0x07, 0x09, 0x0B,
    0x0C, 0x06, 0x07, 0x06, 0x06, 0x05, 0x07, 0x08, 0x08, 0x06, 0x0B, 0x09, 0x06, 0x07, 0x06, 0x06,
    0x07, 0x0B, 0x06, 0x06, 0x06, 0x07, 0x09, 0x08, 0x09, 0x09, 0x0B, 0x08, 0x0B, 0x09, 0x0C, 0x08,
    0x0C, 0x05, 0x06, 0x06, 0x06, 0x05, 0x06, 0x06, 0x06, 0x05, 0x0B, 0x07, 0x05, 0x06, 0x05, 0x05,
    0x06, 0x0A, 0x05, 0x05, 0x05, 0x05, 0x08, 0x07, 0x08, 0x08, 0x0A, 0x0B, 0x0B, 0x0C, 0x0C, 0x0C,
    0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D,
    0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D,
    0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D,
    0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C,
    0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C,
    0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C, 0x0C,
    0x0D, 0x0C, 0x0D, 0x0D, 0x0D, 0x0C, 0x0D, 0x0D, 0x0D, 0x0C, 0x0D, 0x0D, 0x0D, 0x0D, 0x0C, 0x0D,
    0x0D, 0x0D, 0x0C, 0x0C, 0x0C, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D, 0x0D,
]
CH_CODE_ASC = [
    0x0490, 0x0FE0, 0x07E0, 0x0BE0, 0x03E0, 0x0DE0, 0x05E0, 0x09E0,
    0x01E0, 0x00B8, 0x0062, 0x0EE0, 0x06E0, 0x0022, 0x0AE0, 0x02E0,
    0x0CE0, 0x04E0, 0x08E0, 0x00E0, 0x0F60, 0x0760, 0x0B60, 0x0360,
    0x0D60, 0x0560, 0x1240, 0x0960, 0x0160, 0x0E60, 0x0660, 0x0A60,
    0x000F, 0x0250, 0x0038, 0x0260, 0x0050, 0x0C60, 0x0390, 0x00D8,
    0x0042, 0x0002, 0x0058, 0x01B0, 0x007C, 0x0029, 0x003C, 0x0098,
    0x005C, 0x0009, 0x001C, 0x006C, 0x002C, 0x004C, 0x0018, 0x000C,
    0x0074, 0x00E8, 0x0068, 0x0460, 0x0090, 0x0034, 0x00B0, 0x0710,
    0x0860, 0x0031, 0x0054, 0x0011, 0x0021, 0x0017, 0x0014, 0x00A8,
    0x0028, 0x0001, 0x0310, 0x0130, 0x003E, 0x0064, 0x001E, 0x002E,
    0x0024, 0x0510, 0x000E, 0x0036, 0x0016, 0x0044, 0x0030, 0x00C8,
    0x01D0, 0x00D0, 0x0110, 0x0048, 0x0610, 0x0150, 0x0060, 0x0088,
    0x0FA0, 0x0007, 0x0026, 0x0006, 0x003A, 0x001B, 0x001A, 0x002A,
    0x000A, 0x000B, 0x0210, 0x0004, 0x0013, 0x0032, 0x0003, 0x001D,
    0x0012, 0x0190, 0x000D, 0x0015, 0x0005, 0x0019, 0x0008, 0x0078,
    0x00F0, 0x0070, 0x0290, 0x0410, 0x0010, 0x07A0, 0x0BA0, 0x03A0,
    0x0240, 0x1C40, 0x0C40, 0x1440, 0x0440, 0x1840, 0x0840, 0x1040,
    0x0040, 0x1F80, 0x0F80, 0x1780, 0x0780, 0x1B80, 0x0B80, 0x1380,
    0x0380, 0x1D80, 0x0D80, 0x1580, 0x0580, 0x1980, 0x0980, 0x1180,
    0x0180, 0x1E80, 0x0E80, 0x1680, 0x0680, 0x1A80, 0x0A80, 0x1280,
    0x0280, 0x1C80, 0x0C80, 0x1480, 0x0480, 0x1880, 0x0880, 0x1080,
    0x0080, 0x1F00, 0x0F00, 0x1700, 0x0700, 0x1B00, 0x0B00, 0x1300,
    0x0DA0, 0x05A0, 0x09A0, 0x01A0, 0x0EA0, 0x06A0, 0x0AA0, 0x02A0,
    0x0CA0, 0x04A0, 0x08A0, 0x00A0, 0x0F20, 0x0720, 0x0B20, 0x0320,
    0x0D20, 0x0520, 0x0920, 0x0120, 0x0E20, 0x0620, 0x0A20, 0x0220,
    0x0C20, 0x0420, 0x0820, 0x0020, 0x0FC0, 0x07C0, 0x0BC0, 0x03C0,
    0x0DC0, 0x05C0, 0x09C0, 0x01C0, 0x0EC0, 0x06C0, 0x0AC0, 0x02C0,
    0x0CC0, 0x04C0, 0x08C0, 0x00C0, 0x0F40, 0x0740, 0x0B40, 0x0340,
    0x0300, 0x0D40, 0x1D00, 0x0D00, 0x1500, 0x0540, 0x0500, 0x1900,
    0x0900, 0x0940, 0x1100, 0x0100, 0x1E00, 0x0E00, 0x0140, 0x1600,
    0x0600, 0x1A00, 0x0E40, 0x0640, 0x0A40, 0x0A00, 0x1200, 0x0200,
    0x1C00, 0x0C00, 0x1400, 0x0400, 0x1800, 0x0800, 0x1000, 0x0000,
]

COMPRESSION_BINARY = 0
COMPRESSION_ASCII = 1
DICT_CODES = {4: 4, 5: 5, 6: 6}  # header code -> extra distance bits
LITERAL_END_STREAM = 0x305


class PkError(Exception):
    pass


def _mask(n):
    return (1 << n) - 1


def _decode_table(start_indexes, length_bits):
    codes = [0] * 256
    for i, lb in enumerate(length_bits):
        idx = start_indexes[i]
        while idx < 256:
            codes[idx] = i
            idx += 1 << lb
    return codes


def _populate_ascii_table(value, index, bits, limit):
    """Returns {code: char_index} for the codes this character owns."""
    step = value - bits
    seed = CH_CODE_ASC[index] >> bits
    table = {}
    n = seed
    while n < limit:
        table[n] = index
        n += 1 << step
    return table


def _generate_ascii_tables():
    ch_bits = [0] * 256
    t2c34 = [0] * 256
    t2d34 = [0] * 256
    t2e34 = [0] * 128
    t2eb4 = [0] * 256
    for index, value in enumerate(CH_BITS_ASC):
        if value <= 8:
            for k, v in _populate_ascii_table(value, index, 0, 256).items():
                t2c34[k] = v
            ch_bits[index] = value
            continue
        acc = CH_CODE_ASC[index] & 0xFF
        if acc == 0:
            for k, v in _populate_ascii_table(value, index, 8, 256).items():
                t2eb4[k] = v
            ch_bits[index] = value - 8
            continue
        t2c34[acc] = 0xFF
        if (acc & 0x3F) == 0:
            for k, v in _populate_ascii_table(value, index, 6, 0x80).items():
                t2e34[k] = v
            ch_bits[index] = value - 6
        else:
            for k, v in _populate_ascii_table(value, index, 4, 256).items():
                t2d34[k] = v
            ch_bits[index] = value - 4
    return ch_bits, t2c34, t2d34, t2e34, t2eb4


_ASCII = _generate_ascii_tables()
_LEN_CODES = _decode_table(LEN_CODE, LEN_BITS)
_DIST_CODES = _decode_table(DIST_CODE, DIST_BITS)


class _Exploder:
    def __init__(self, data):
        self.data = data
        self.pos = 0
        self.extra_bits = 0
        self.bit_buffer = 0
        self.compression = 0
        self.dict_bits = 0
        self.dict_mask = 0
        self.ch_bits, self.t2c34, self.t2d34, self.t2e34, self.t2eb4 = _ASCII

    # -- bit plumbing --------------------------------------------------------
    def _empty(self):
        return self.pos >= len(self.data)

    def _read_byte(self, offset=0):
        i = self.pos + offset
        if i >= len(self.data):
            raise PkError("unexpected end of input")
        return self.data[i]

    def _waste(self, n):
        if n > self.extra_bits and self._empty():
            raise PkError("unexpected end of input")
        if n <= self.extra_bits:
            self.bit_buffer >>= n
            self.extra_bits -= n
            return
        nxt = self._read_byte(0)
        self.pos += 1
        self.bit_buffer = ((self.bit_buffer >> self.extra_bits) | (nxt << 8)) >> (n - self.extra_bits)
        self.extra_bits = self.extra_bits + 8 - n

    def _parse_header(self):
        if len(self.data) - self.pos < 4:
            return False
        ctype = self._read_byte(0)
        dsize = self._read_byte(1)
        if ctype not in (COMPRESSION_BINARY, COMPRESSION_ASCII):
            raise PkError(f"unknown compression type {ctype}")
        if dsize not in DICT_CODES:
            raise PkError(f"unknown dictionary size code {dsize}")
        self.compression = ctype
        self.dict_bits = DICT_CODES[dsize]
        self.dict_mask = _mask(self.dict_bits)
        self.bit_buffer = self._read_byte(2)
        self.pos += 3
        return True

    # -- decoding ------------------------------------------------------------
    def _next_literal(self):
        is_repeat = self.bit_buffer & 1
        self._waste(1)
        if is_repeat:
            length_code = _LEN_CODES[self.bit_buffer & 0xFF]
            self._waste(LEN_BITS[length_code])
            extra_len_bits = EX_LEN_BITS[length_code]
            if extra_len_bits:
                extra_length = self.bit_buffer & _mask(extra_len_bits)
                try:
                    self._waste(extra_len_bits)
                except PkError:
                    if length_code + extra_length != 0x10E:
                        raise
                length_code = LEN_BASE[length_code] + extra_length
            return length_code + 0x100

        last_byte = self.bit_buffer & 0xFF
        if self.compression == COMPRESSION_BINARY:
            self._waste(8)
            return last_byte
        if last_byte > 0:
            value = self.t2c34[last_byte]
            if value == 0xFF:
                if (self.bit_buffer & 0x3F) == 0:
                    self._waste(6)
                    value = self.t2e34[self.bit_buffer & 0x7F]
                else:
                    self._waste(4)
                    value = self.t2d34[self.bit_buffer & 0xFF]
        else:
            self._waste(8)
            value = self.t2eb4[self.bit_buffer & 0xFF]
        self._waste(self.ch_bits[value])
        return value

    def _distance(self, repeat_length):
        dist_pos_code = _DIST_CODES[self.bit_buffer & 0xFF]
        self._waste(DIST_BITS[dist_pos_code])
        if repeat_length == 2:
            distance = (dist_pos_code << 2) | (self.bit_buffer & 3)
            self._waste(2)
        else:
            distance = (dist_pos_code << self.dict_bits) | (self.bit_buffer & self.dict_mask)
            self._waste(self.dict_bits)
        return distance + 1

    def run(self):
        if not self._parse_header() or self._empty():
            raise PkError("truncated stream")
        out = bytearray()
        lit = self._next_literal()
        while lit != LITERAL_END_STREAM:
            if lit < 0x100:
                out.append(lit)
                lit = self._next_literal()
                continue
            repeat_length = lit - 0xFE
            distance = self._distance(repeat_length)
            start = len(out) - distance
            if start < 0:
                raise PkError(f"distance {distance} before start of output")
            # byte-at-a-time copy handles overlapping repetitions correctly
            for _ in range(repeat_length):
                out.append(out[start])
                start += 1
            lit = self._next_literal()
        return bytes(out)


def explode(block: bytes) -> bytes:
    """Decompress one PKWare DCL Implode block (without any container header)."""
    return _Exploder(block).run()


# --- implode (encoder) ------------------------------------------------------
LONGEST_ALLOWED_REPETITION = 0x204
_BLOCK_BYTES = {4: 0x400, 5: 0x800, 6: 0x1000}


def _clamp(n, lo, hi):
    return lo if n < lo else (hi if n > hi else n)


class _BitWriter:
    """Bit packer matching node-pkware outputBits: a trailing partial byte is
    always present and gets OR-ed into by the next write."""

    def __init__(self):
        self.buf = bytearray()
        self.out_bits = 0

    def append(self, b):
        self.buf.append(b & 0xFF)

    def write(self, nbits, bits):
        if nbits > 8:
            self.write(8, bits)
            bits >>= 8
            nbits -= 8
        old = self.out_bits
        self.buf[-1] |= (bits << old) & 0xFF
        total = old + nbits
        if total > 8:
            carry = (bits >> (8 - old)) & 0xFF
            self.out_bits = total & 7
            self.append(carry)
            return
        self.out_bits = total & 7
        if self.out_bits == 0:
            self.append(0)


def _implode_tables(compression):
    n_ch_bits = [0] * 0x306
    n_ch_codes = [0] * 0x306
    if compression == COMPRESSION_ASCII:
        for i in range(256):
            n_ch_bits[i] = CH_BITS_ASC[i] + 1
            n_ch_codes[i] = CH_CODE_ASC[i] * 2
    else:
        code = 0
        for i in range(256):
            n_ch_bits[i] = 9
            n_ch_codes[i] = code
            code = (code & 0xFFFF) + 2
    k = 0x100
    for i in range(0x10):
        for j in range(1 << EX_LEN_BITS[i]):
            n_ch_bits[k] = EX_LEN_BITS[i] + LEN_BITS[i] + 1
            n_ch_codes[k] = (j << (LEN_BITS[i] + 1)) | (LEN_CODE[i] * 2) | 1
            k += 1
    return n_ch_bits, n_ch_codes


def _size_of_matching(view, a, b):
    # capped at b-a (no match longer than its own distance) and at the buffer end
    max_len = min(_clamp(b - a, 2, LONGEST_ALLOWED_REPETITION), len(view) - b - 1)
    if max_len < 2:
        return 2  # the two-needle already matched, staying inside the data is enough
    i = 2
    while i <= max_len:
        if view[a + i] != view[b + i]:
            return i
        i += 1
    return max_len


def implode(data: bytes, compression: str = "ascii", dictionary_size: str = "large") -> bytes:
    """Compress one block with PKWare DCL Implode (ASCII or binary literals)."""
    ctype = COMPRESSION_ASCII if compression == "ascii" else COMPRESSION_BINARY
    dcode = 6 if dictionary_size == "large" else (5 if dictionary_size == "medium" else 4)
    dict_bits = DICT_CODES[dcode]
    n_ch_bits, n_ch_codes = _implode_tables(ctype)

    w = _BitWriter()
    w.append(ctype)
    w.append(dcode)
    w.append(0)

    n = len(data)
    if n:
        head = min(2, n)
        for i in range(head):
            w.write(n_ch_bits[data[i]], n_ch_codes[data[i]])
        cursor = head
        base = 0
        block = _BLOCK_BYTES[dcode]
        last = {}
        while cursor < n:
            rel = cursor - base
            size = distance = 0
            if rel >= 2 and cursor + 2 <= n:
                needle = (data[cursor] << 8) | data[cursor + 1]
                matched = last.get(needle, -1)
                last[needle] = rel
                if 0 <= matched < rel:
                    if matched == rel - 2:
                        size, distance = 2, 1
                    else:
                        distance = rel - matched - 1
                        size = _size_of_matching(data[base:], matched, rel)

            if size == 0 or (size == 2 and distance >= 0x100):
                flushable = False
            elif size >= 8 or n - cursor < 2:
                flushable = True
            else:
                flushable = None  # can flush, but a longer match may start here

            if flushable is False:
                w.write(n_ch_bits[data[cursor]], n_ch_codes[data[cursor]])
                cursor += 1
            else:
                w.write(n_ch_bits[size + 0xFE], n_ch_codes[size + 0xFE])
                if size == 2:
                    hi = distance >> 2
                    w.write(DIST_BITS[hi], DIST_CODE[hi])
                    w.write(2, distance & 3)
                else:
                    hi = distance >> dict_bits
                    if hi >= 64:
                        raise PkError(f"distance {distance} too large for {dictionary_size} dictionary")
                    w.write(DIST_BITS[hi], DIST_CODE[hi])
                    w.write(dict_bits, distance & _mask(dict_bits))
                cursor += size
            if cursor - base >= block:
                base += block
                last.clear()
    w.write(n_ch_bits[0x305], n_ch_codes[0x305])
    return bytes(w.buf)


def pack_bytes(xml: bytes, magic: bytes = None, block_size: int = MAX_ALLOWED_LEN) -> bytes:
    """Wrap raw XML into a compressed EW container."""
    if magic is None:
        magic = MS14_MAGIC
    parts = [magic, len(xml).to_bytes(8, "little")]
    for off in range(0, len(xml), block_size):
        chunk = xml[off:off + block_size]
        comp = implode(chunk)
        parts.append(len(chunk).to_bytes(4, "little"))
        parts.append(len(comp).to_bytes(4, "little"))
        parts.append(comp)
    return b"".join(parts)


def pack_file(xml_path: str, out_path: str, magic: bytes = None) -> int:
    with open(xml_path, "rb") as f:
        xml = f.read()
    data = pack_bytes(xml, magic)
    with open(out_path, "wb") as f:
        f.write(data)
    return len(data)


# --- .ms14 / .ewprj container ----------------------------------------------
MS14_MAGIC = b"MSMCompressedElectronicsWorkbenchXML"
EWPRJ_MAGIC = b"CompressedElectronicsWorkbenchXML"


def unpack_bytes(data: bytes) -> bytes:
    """Return the XML from a compressed EW container."""
    if data.startswith(MS14_MAGIC):
        magic, pos = MS14_MAGIC, len(MS14_MAGIC)
    elif data.startswith(EWPRJ_MAGIC):
        magic, pos = EWPRJ_MAGIC, len(EWPRJ_MAGIC)
    else:
        raise PkError("not a compressed Electronics Workbench file")

    if len(data) < pos + 8:
        raise PkError("truncated header")
    total = int.from_bytes(data[pos:pos + 8], "little")
    pos += 8

    blocks = []
    got = 0
    while got < total:
        if pos + 8 > len(data):
            raise PkError("truncated block table")
        raw_len = int.from_bytes(data[pos:pos + 4], "little")
        comp_len = int.from_bytes(data[pos + 4:pos + 8], "little")
        pos += 8
        chunk = data[pos:pos + comp_len]
        if len(chunk) != comp_len:
            raise PkError("truncated block")
        pos += comp_len
        block = explode(chunk)
        if len(block) != raw_len:
            raise PkError(f"block length mismatch: got {len(block)} expected {raw_len}")
        blocks.append(block)
        got += raw_len
    if got != total:
        raise PkError(f"total length mismatch: got {got} expected {total}")
    return b"".join(blocks)


def unpack_file(path: str) -> bytes:
    with open(path, "rb") as f:
        return unpack_bytes(f.read())
