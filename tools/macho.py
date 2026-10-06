"""The limited Mach-O operations required by the pinned ARM64 game build."""
import hashlib
import struct

from .common import UserError

MH_MAGIC_64 = 0xFEEDFACF
CPU_TYPE_ARM64 = 0x0100000C
MH_DYLIB = 6
LC_SEGMENT_64 = 0x19
LC_BUILD_VERSION = 0x32


def arm64_slice(data):
    """Extract a generic ARM64 slice without lipo (thin, fat32 or fat64)."""
    if len(data) < 8:
        raise UserError("Truncated Mach-O header.")
    magic = bytes(data[:4])
    if magic == b"\xcf\xfa\xed\xfe":
        if len(data) < 32 or struct.unpack_from("<I", data, 4)[0] != CPU_TYPE_ARM64:
            raise UserError("This binary has no ARM64 slice.")
        return bytes(data)
    formats = {b"\xca\xfe\xba\xbe": (">", False),
               b"\xbe\xba\xfe\xca": ("<", False),
               b"\xca\xfe\xba\xbf": (">", True),
               b"\xbf\xba\xfe\xca": ("<", True)}
    if magic not in formats:
        raise UserError("Expected a thin or universal Mach-O binary.")
    endian, wide = formats[magic]
    count = struct.unpack_from(endian + "I", data, 4)[0]
    entry_size = 32 if wide else 20
    table_end = 8 + count * entry_size
    if not count or table_end > len(data):
        raise UserError("Invalid universal Mach-O architecture table.")
    selected, ranges = [], []
    for index in range(count):
        entry = struct.unpack_from(endian + ("IIQQII" if wide else "IIIII"),
                                   data, 8 + index * entry_size)
        cpu, subtype, offset, size, alignment = entry[:5]
        if wide and entry[5] != 0:
            raise UserError("Invalid universal Mach-O reserved field.")
        if offset < table_end or size < 4 or offset + size > len(data) or alignment > 63:
            raise UserError("Universal Mach-O slice exceeds its file or table.")
        if offset % (1 << alignment):
            raise UserError("Misaligned universal Mach-O slice.")
        ranges.append((offset, offset + size))
        if cpu == CPU_TYPE_ARM64 and subtype & 0x00FFFFFF == 0:
            selected.append((offset, size))
    ranges.sort()
    if any(left[1] > right[0] for left, right in zip(ranges, ranges[1:])):
        raise UserError("Overlapping universal Mach-O slices.")
    if len(selected) != 1:
        raise UserError("Expected exactly one generic ARM64 slice.")
    offset, size = selected[0]
    result = data[offset:offset + size]
    if len(result) < 32 or result[:4] != b"\xcf\xfa\xed\xfe" or struct.unpack_from("<I", result, 4)[0] != CPU_TYPE_ARM64:
        raise UserError("Universal ARM64 entry does not contain an ARM64 Mach-O header.")
    return bytes(result)


def commands(data):
    if len(data) < 32 or struct.unpack_from("<I", data)[0] != MH_MAGIC_64:
        raise UserError("Expected a little-endian 64-bit Mach-O file.")
    count, total = struct.unpack_from("<II", data, 16)
    end = 32 + total
    if end > len(data) or count > total // 8:
        raise UserError("Invalid Mach-O load-command table.")
    offset = 32
    for _ in range(count):
        if offset + 8 > end:
            raise UserError("Truncated Mach-O load command.")
        kind, size = struct.unpack_from("<II", data, offset)
        if size < 8 or size % 8 or offset + size > end:
            raise UserError("Invalid Mach-O load-command size.")
        yield kind, offset, bytearray(data[offset:offset + size])
        offset += size
    if offset != end:
        raise UserError("Mach-O command count/size mismatch.")


def validate_dylib(data):
    list(commands(data))
    if struct.unpack_from("<I", data, 4)[0] != CPU_TYPE_ARM64:
        raise UserError("This tool requires an ARM64 binary.")
    if struct.unpack_from("<I", data, 12)[0] != MH_DYLIB:
        raise UserError("Expected the game's dynamic library, not its launcher.")
    for kind, _, command in commands(data):
        if kind in (0x21, 0x2C) and struct.unpack_from("<I", command, 16)[0]:
            raise UserError("Encrypted binaries are not supported.")


def sections(data):
    for kind, _, command in commands(data):
        if kind != LC_SEGMENT_64:
            continue
        if len(command) < 72:
            raise UserError("Truncated Mach-O segment.")
        count = struct.unpack_from("<I", command, 64)[0]
        if 72 + count * 80 > len(command):
            raise UserError("Truncated Mach-O section table.")
        for i in range(count):
            at = 72 + i * 80
            name = command[at:at + 16].split(b"\0")[0].decode()
            size, offset = struct.unpack_from("<QI", command, at + 40)
            if offset and offset + size > len(data):
                raise UserError("Section {} exceeds the file.".format(name))
            yield name, offset, size


def code_hash(data):
    for name, offset, size in sections(data):
        if name == "__text":
            return hashlib.sha256(data[offset:offset + size]).hexdigest()
    raise UserError("Missing __text section.")


def remove_signature(data):
    """Remove a terminal LC_CODE_SIGNATURE without Apple's codesign executable.

    Matches codesign_allocate's removal layout: discard signature alignment
    after the string table, shrink __LINKEDIT.filesize, preserve its vmsize.
    Callers must validate the original AND final pinned file fingerprints.
    """
    data = bytearray(data)
    table = list(commands(data))
    signatures = [command for kind, _, command in table if kind == 0x1D]
    if not signatures:
        return data
    if len(signatures) != 1 or len(signatures[0]) != 16:
        raise UserError("Unsupported Mach-O code signature command.")
    offset, size = struct.unpack_from("<II", signatures[0], 8)
    command_end = 32 + struct.unpack_from("<I", data, 20)[0]
    if not size or offset < command_end or not len(data) - 7 <= offset + size <= len(data):
        raise UserError("Code signature is not at the end of the binary.")
    new_size = offset
    for kind, _, command in table:
        if kind == 0x2:
            if len(command) != 24:
                raise UserError("Invalid Mach-O symbol table command.")
            string_offset, string_size = struct.unpack_from("<II", command, 16)
            string_end = string_offset + string_size
            if command_end <= string_end <= new_size and new_size - string_end <= 12:
                new_size = string_end
    updated, linkedit_count = [], 0
    for kind, _, command in table:
        if kind == 0x1D:
            continue
        if kind == LC_SEGMENT_64 and command[8:24].rstrip(b"\0") == b"__LINKEDIT":
            if len(command) < 72:
                raise UserError("Truncated __LINKEDIT segment.")
            file_offset, file_size = struct.unpack_from("<QQ", command, 40)
            if file_offset > new_size or file_offset + file_size < offset + size:
                raise UserError("Signature is outside __LINKEDIT.")
            struct.pack_into("<Q", command, 48, new_size - file_offset)
            linkedit_count += 1
        updated.append(command)
    if linkedit_count != 1:
        raise UserError("Expected one __LINKEDIT segment for signature removal.")
    header = b"".join(updated)
    data[32:command_end] = header.ljust(command_end - 32, b"\0")
    struct.pack_into("<II", data, 16, len(updated), len(header))
    return data[:new_size]


def string_command(kind, prefix, value):
    data = struct.pack("<II", kind, 0) + prefix + value.encode() + b"\0"
    data = bytearray(data.ljust((len(data) + 7) & ~7, b"\0"))
    struct.pack_into("<I", data, 4, len(data))
    return data


def replace_commands(data, updated):
    header = b"".join(updated)
    old_size = struct.unpack_from("<I", data, 20)[0]
    first = min(offset for _, offset, size in sections(data) if offset and size)
    if 32 + len(header) > first:
        raise UserError("The new load commands do not fit before the first section.")
    length = max(old_size, len(header))
    data[32:32 + length] = header.ljust(length, b"\0")
    struct.pack_into("<II", data, 16, len(updated), len(header))


def verify_fingerprint(data, expected, name):
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise UserError("Unsupported {} ARM64 binary.\nExpected SHA-256: {}\nFound: {}\n"
                        "Only the game build in data/supported-game.json is supported. No patches were applied."
                        .format(name, expected, actual))


def patch_instructions(data, patches):
    # Validate every original word before changing any of them.
    for patch in patches:
        offset = int(patch["offset"], 0)
        if offset < 0 or offset + 4 > len(data):
            raise UserError("Instruction patch is outside the binary.")
        old = struct.unpack_from("<I", data, offset)[0]
        if old != int(patch["old_word"], 0):
            raise UserError("Unexpected instruction at {}. No instruction patches were applied.".format(patch["offset"]))
    for patch in patches:
        struct.pack_into("<I", data, int(patch["offset"], 0), int(patch["new_word"], 0))
