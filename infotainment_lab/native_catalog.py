"""Read the selected firmware's exported CAN metadata without executing it.

This recognizes the x86-64 CANBusNode/MessageNode/SignalNode table layout, checks
symbol sizes and back pointers, and refuses a different layout. These tables
provide names and enums, not bit positions; decoding still needs a supplied DBC.
"""
from pathlib import Path
import struct


class Elf:
    def __init__(self, path):
        self.data = Path(path).read_bytes()
        if self.data[:6] != b'\x7fELF\x02\x01' or self.unpack('<H', 18)[0] != 62:
            raise ValueError('CAN metadata extraction requires an x86-64 little-endian ELF image.')
        offset, = self.unpack('<Q', 40)
        stride, count = self.unpack('<HH', 58)
        if stride != 64 or not 1 <= count < 65536:
            raise ValueError('Unsupported ELF section table.')
        self.sections = [self.unpack('<IIQQQQIIQQ', offset + i * stride) for i in range(count)]
        self.symbols, indexed = {}, {}
        for i, sec in enumerate(self.sections):
            if sec[1] != 11:
                continue
            strings = self.sections[sec[6]]
            entries = []
            for pos in range(sec[4], sec[4] + sec[5], 24):
                name, info, other, shndx, value, size = self.unpack('<IBBHQQ', pos)
                label = self.string_at(strings[4] + name)
                entries.append((value, size))
                if shndx and label:
                    self.symbols[label] = (value, size)
            indexed[i] = entries
        self.relocations = {}
        for sec in self.sections:
            if sec[1] != 4 or sec[6] not in indexed:
                continue
            for pos in range(sec[4], sec[4] + sec[5], 24):
                target, info, addend = self.unpack('<QQq', pos)
                kind, symbol = info & 0xffffffff, info >> 32
                if kind in (1, 6, 8):
                    self.relocations[target] = (0 if kind == 8 else indexed[sec[6]][symbol][0]) + addend

    def unpack(self, fmt, offset):
        try:
            return struct.unpack_from(fmt, self.data, offset)
        except (struct.error, OverflowError) as exc:
            raise ValueError('Truncated CAN metadata image.') from exc

    def offset(self, address, size=1):
        for sec in self.sections:
            if sec[1] != 8 and sec[3] <= address and address + size <= sec[3] + sec[5]:
                return sec[4] + address - sec[3]
        raise ValueError('CAN metadata pointer is outside the image.')

    def values(self, fmt, address):
        return self.unpack(fmt, self.offset(address, struct.calcsize(fmt)))

    def pointer(self, address):
        return self.relocations.get(address, self.values('<Q', address)[0])

    def string_at(self, offset):
        end = self.data.find(b'\0', offset, offset + 1024)
        if end < 0:
            raise ValueError('Invalid CAN metadata string.')
        return self.data[offset:end].decode('utf-8')

    def text(self, address):
        return self.string_at(self.offset(address)) if address else ''


def extract(path):
    elf = Elf(path)
    root, size = elf.symbols.get('CANData', (0, 0))
    buses, bus_size = elf.symbols.get('CANBusList', (0, 0))
    if size != 16 or bus_size % 24 or not 1 <= bus_size // 24 <= 64:
        raise ValueError('Unsupported CAN metadata root layout.')
    count, = elf.values('<I', root)
    if count != bus_size // 24 or elf.pointer(root + 8) != buses:
        raise ValueError('CAN metadata bus count does not match its exported table.')
    known_symbols = {address: (name, size) for name, (address, size) in elf.symbols.items()}
    output = []
    for index in range(count):
        bus = buses + index * 24
        name = elf.text(elf.pointer(bus))
        bus_id, message_count = elf.values('<II', bus + 8)
        messages = elf.pointer(bus + 16)
        if not 0 < message_count <= 10000 or known_symbols.get(messages, ('', 0))[1] != message_count * 48:
            raise ValueError('Unsupported CAN message table layout.')
        for n in range(message_count):
            message = messages + n * 48
            identifier, length, period, signal_count = elf.values('<IIII', message + 8)
            signals = elf.pointer(message + 32)
            if (length > 64 or signal_count > 10000 or elf.pointer(message + 40) != bus
                    or known_symbols.get(signals, ('', 0))[1] != signal_count * 40):
                raise ValueError('Unsupported CAN signal table layout.')
            fields = []
            for s in range(signal_count):
                signal = signals + s * 40
                if elf.pointer(signal + 24) != message:
                    raise ValueError('CAN signal parent mismatch.')
                choices = {}
                enum = elf.pointer(signal + 32)
                enum_size = known_symbols.get(enum, ('', 0))[1]
                if enum and 0 < enum_size <= 65536 and enum_size % 16 == 0:
                    for row in range(enum_size // 16):
                        entry = enum + row * 16
                        label = elf.pointer(entry + 8)
                        if not label:
                            break
                        value, = elf.values('<i', entry)
                        text = elf.text(label)
                        if value == -1 and not text:
                            break
                        choices[str(value)] = text
                fields.append({'name': elf.text(elf.pointer(signal)),
                               'unit': elf.text(elf.pointer(signal + 16)), 'choices': choices})
            output.append({'bus': name, 'bus_id': bus_id, 'id': identifier,
                           'name': elf.text(elf.pointer(message)), 'length': length,
                           'period_ms': period, 'signals': fields})
    return output
