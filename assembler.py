REGISTERS = {
    '%rax': 0x0, '%rcx': 0x1, '%rdx': 0x2, '%rbx': 0x3,
    '%rsp': 0x4, '%rbp': 0x5, '%rsi': 0x6, '%rdi': 0x7,
    '%r8':  0x8, '%r9':  0x9, '%r10': 0xA, '%r11': 0xB,
    '%r12': 0xC, '%r13': 0xD, '%r14': 0xE, 'noreg': 0xF
}

ICODES = {
    'halt':   0x0, 'nop':    0x1,
    'rrmovq': 0x2, 'cmove':  0x2,
    'irmovq': 0x3, 'rmmovq': 0x4, 'mrmovq': 0x5,
    'addq':   0x6, 'subq':   0x6, 'andq':   0x6, 'xorq':   0x6,
    'jmp':    0x7, 'jle':    0x7, 'jl':     0x7, 'je':     0x7,
    'jne':    0x7, 'jge':    0x7, 'jg':     0x7,
    'call':   0x8, 'ret':    0x9,
    'pushq':  0xA, 'popq':   0xB,
}

FN = {
    'halt': 0, 'nop': 0,
    'rrmovq': 0, 'cmove': 3,
    'irmovq': 0, 'rmmovq': 0, 'mrmovq': 0,
    'addq': 0, 'subq': 1, 'andq': 2, 'xorq': 3,
    'jmp': 0, 'jle': 1, 'jl': 2, 'je': 3,
    'jne': 4, 'jge': 5, 'jg': 6,
    'call': 0, 'ret': 0, 'pushq': 0, 'popq': 0,
}

INSTR_SIZE = {
    'halt': 1, 'nop': 1, 'ret': 1,
    'rrmovq': 2, 'cmove': 2,
    'addq': 2, 'subq': 2, 'andq': 2, 'xorq': 2,
    'pushq': 2, 'popq': 2,
    'irmovq': 10, 'rmmovq': 10, 'mrmovq': 10,
    'jmp': 9, 'jle': 9, 'jl': 9, 'je': 9,
    'jne': 9, 'jge': 9, 'jg': 9,
    'call': 9,
}


def encode_int64(value):
    return list((value & 0xFFFFFFFFFFFFFFFF).to_bytes(8, 'little'))


def parse_immediate(token):
    token = token.strip().lstrip('$')
    return int(token, 0)


def parse_mem_operand(token):
    token = token.strip()
    if '(' in token:
        parts = token.split('(')
        offset = int(parts[0]) if parts[0] else 0
        reg = parts[1].rstrip(')')
        return offset, reg
    return 0, 'noreg'


def assemble(source):
    lines = source.strip().split('\n')
    symbols = {}
    instructions = []
    pc = 0

    # First pass: collect labels and compute addresses
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith('#'):
            continue
        if line.endswith(':'):
            symbols[line[:-1]] = pc
            continue
        if ':' in line.split()[0]:
            label, rest = line.split(':', 1)
            symbols[label.strip()] = pc
            line = rest.strip()
            if not line:
                continue
        mnemonic = line.split()[0].lower()
        if mnemonic not in INSTR_SIZE:
            raise ValueError(f"Unknown instruction: {mnemonic}")
        instructions.append((pc, line))
        pc += INSTR_SIZE[mnemonic]

    # Second pass: encode bytes
    memory = {}
    decoded = []

    for addr, line in instructions:
        parts = line.split(None, 1)
        mnemonic = parts[0].lower()
        args = parts[1].split(',') if len(parts) > 1 else []
        args = [a.strip() for a in args]

        icode = ICODES[mnemonic]
        fn = FN[mnemonic]
        byte0 = (icode << 4) | fn
        bytes_out = [byte0]

        if mnemonic in ('halt', 'nop', 'ret'):
            pass

        elif mnemonic in ('rrmovq', 'cmove'):
            rA = REGISTERS[args[0]]
            rB = REGISTERS[args[1]]
            bytes_out.append((rA << 4) | rB)

        elif mnemonic == 'irmovq':
            val = parse_immediate(args[0])
            rB = REGISTERS[args[1]]
            bytes_out.append((0xF << 4) | rB)
            bytes_out.extend(encode_int64(val))

        elif mnemonic == 'rmmovq':
            rA = REGISTERS[args[0]]
            offset, base = parse_mem_operand(args[1])
            rB = REGISTERS.get(base, 0xF)
            bytes_out.append((rA << 4) | rB)
            bytes_out.extend(encode_int64(offset))

        elif mnemonic == 'mrmovq':
            offset, base = parse_mem_operand(args[0])
            rA = REGISTERS[args[1]]
            rB = REGISTERS.get(base, 0xF)
            bytes_out.append((rA << 4) | rB)
            bytes_out.extend(encode_int64(offset))

        elif mnemonic in ('addq', 'subq', 'andq', 'xorq'):
            rA = REGISTERS[args[0]]
            rB = REGISTERS[args[1]]
            bytes_out.append((rA << 4) | rB)

        elif mnemonic in ('jmp', 'jle', 'jl', 'je', 'jne', 'jge', 'jg', 'call'):
            dest = args[0]
            target = symbols.get(dest, parse_immediate(dest))
            bytes_out.extend(encode_int64(target))

        elif mnemonic == 'pushq':
            rA = REGISTERS[args[0]]
            bytes_out.append((rA << 4) | 0xF)

        elif mnemonic == 'popq':
            rA = REGISTERS[args[0]]
            bytes_out.append((rA << 4) | 0xF)

        for i, b in enumerate(bytes_out):
            memory[addr + i] = b

        decoded.append({
            'addr': addr,
            'mnemonic': mnemonic,
            'args': args,
            'bytes': bytes_out,
            'size': INSTR_SIZE[mnemonic]
        })

    return memory, symbols, decoded


if __name__ == '__main__':
    source = """
irmovq $10, %rax
irmovq $20, %rbx
addq %rax, %rbx
halt
"""
    memory, symbols, decoded = assemble(source)
    print("Symbols:", symbols)
    for instr in decoded:
        hex_bytes = ' '.join(f'{b:02x}' for b in instr['bytes'])
        print(f"0x{instr['addr']:03x}: {instr['mnemonic']:<8} {hex_bytes}")
