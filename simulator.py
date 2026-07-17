from assembler import assemble, REGISTERS, ICODES, FN

REGISTER_NAMES = {v: k for k, v in REGISTERS.items()}

# Pipeline stage names
STAGES = ['fetch', 'decode', 'execute', 'memory', 'writeback']

# Condition codes
ZF, SF, OF = 0, 0, 0


def check_condition(mnemonic, zf, sf, of):
    if mnemonic == 'jmp':  return True
    if mnemonic == 'jle':  return (sf ^ of) | zf
    if mnemonic == 'jl':   return sf ^ of
    if mnemonic == 'je':   return zf
    if mnemonic == 'jne':  return not zf
    if mnemonic == 'jge':  return not (sf ^ of)
    if mnemonic == 'jg':   return (not (sf ^ of)) and (not zf)
    if mnemonic == 'cmove': return (sf ^ of) | zf
    return False


class PipelineRegister:
    def __init__(self):
        self.reset()

    def reset(self):
        self.mnemonic = 'bubble'
        self.addr = None
        self.rA = 0xF
        self.rB = 0xF
        self.val_c = 0
        self.val_a = 0
        self.val_b = 0
        self.val_e = 0
        self.val_m = 0
        self.dst_e = 0xF
        self.dst_m = 0xF
        self.cnd = False
        self.is_bubble = True


class Simulator:
    def __init__(self, source):
        self.memory_bytes, self.symbols, self.decoded = assemble(source)
        self.registers = [0] * 15
        self.pc = 0
        self.cycle = 0
        self.halted = False
        self.zf = 0
        self.sf = 0
        self.of = 0

        # Pipeline registers between stages
        self.if_id  = PipelineRegister()
        self.id_ex  = PipelineRegister()
        self.ex_mem = PipelineRegister()
        self.mem_wb = PipelineRegister()

        self.history = []

    def read_mem_byte(self, addr):
        return self.memory_bytes.get(addr, 0)

    def read_mem_int64(self, addr):
        b = [self.read_mem_byte(addr + i) for i in range(8)]
        return int.from_bytes(bytes(b), 'little', signed=True)

    def write_mem_int64(self, addr, value):
        b = list((value & 0xFFFFFFFFFFFFFFFF).to_bytes(8, 'little'))
        for i, byte in enumerate(b):
            self.memory_bytes[addr + i] = byte

    def read_register(self, reg_id):
        if reg_id == 0xF:
            return 0
        return self.registers[reg_id]

    def write_register(self, reg_id, value):
        if reg_id != 0xF:
            self.registers[reg_id] = value & 0xFFFFFFFFFFFFFFFF

    def fetch(self):
        if self.halted:
            return PipelineRegister()

        pc = self.pc
        icode_byte = self.read_mem_byte(pc)
        icode = (icode_byte >> 4) & 0xF
        fn    = icode_byte & 0xF

        pr = PipelineRegister()
        pr.is_bubble = False
        pr.addr = pc

        mnemonic = None
        for name, code in ICODES.items():
            if code == icode and FN.get(name, 0) == fn:
                mnemonic = name
                break

        if mnemonic is None:
            mnemonic = 'halt'

        pr.mnemonic = mnemonic

        if mnemonic in ('halt', 'nop', 'ret'):
            self.pc = pc + 1

        elif mnemonic in ('rrmovq', 'cmove', 'addq', 'subq', 'andq', 'xorq', 'pushq', 'popq'):
            reg_byte = self.read_mem_byte(pc + 1)
            pr.rA = (reg_byte >> 4) & 0xF
            pr.rB = reg_byte & 0xF
            self.pc = pc + 2

        elif mnemonic == 'irmovq':
            reg_byte = self.read_mem_byte(pc + 1)
            pr.rA = 0xF
            pr.rB = reg_byte & 0xF
            pr.val_c = self.read_mem_int64(pc + 2)
            self.pc = pc + 10

        elif mnemonic in ('rmmovq', 'mrmovq'):
            reg_byte = self.read_mem_byte(pc + 1)
            pr.rA = (reg_byte >> 4) & 0xF
            pr.rB = reg_byte & 0xF
            pr.val_c = self.read_mem_int64(pc + 2)
            self.pc = pc + 10

        elif mnemonic in ('jmp', 'jle', 'jl', 'je', 'jne', 'jge', 'jg', 'call'):
            pr.val_c = self.read_mem_int64(pc + 1)
            self.pc = pc + 9

        if mnemonic == 'halt':
            self.halted = True

        return pr

    def decode(self, if_id):
        pr = PipelineRegister()
        if if_id.is_bubble:
            return pr

        pr.mnemonic = if_id.mnemonic
        pr.addr     = if_id.addr
        pr.rA       = if_id.rA
        pr.rB       = if_id.rB
        pr.val_c    = if_id.val_c
        pr.is_bubble = False

        # Read register values
        pr.val_a = self.read_register(if_id.rA)
        pr.val_b = self.read_register(if_id.rB)

        # Forwarding from EX/MEM/WB stages
        for fwd_reg, fwd_val in self._get_forwarding_sources():
            if if_id.rA == fwd_reg and if_id.rA != 0xF:
                pr.val_a = fwd_val
            if if_id.rB == fwd_reg and if_id.rB != 0xF:
                pr.val_b = fwd_val

        # Destination registers
        m = if_id.mnemonic
        if m in ('rrmovq', 'cmove', 'irmovq', 'addq', 'subq', 'andq', 'xorq'):
            pr.dst_e = if_id.rB
        elif m == 'mrmovq':
            pr.dst_m = if_id.rA
        elif m == 'popq':
            pr.dst_m = if_id.rA
            pr.dst_e = 4  # %rsp

        return pr

    def _get_forwarding_sources(self):
        sources = []
        if not self.ex_mem.is_bubble and self.ex_mem.dst_e != 0xF:
            sources.append((self.ex_mem.dst_e, self.ex_mem.val_e))
        if not self.mem_wb.is_bubble:
            if self.mem_wb.dst_e != 0xF:
                sources.append((self.mem_wb.dst_e, self.mem_wb.val_e))
            if self.mem_wb.dst_m != 0xF:
                sources.append((self.mem_wb.dst_m, self.mem_wb.val_m))
        return sources

    def execute(self, id_ex):
        pr = PipelineRegister()
        if id_ex.is_bubble:
            return pr

        pr.mnemonic = id_ex.mnemonic
        pr.addr     = id_ex.addr
        pr.val_c    = id_ex.val_c
        pr.dst_e    = id_ex.dst_e
        pr.dst_m    = id_ex.dst_m
        pr.rA       = id_ex.rA
        pr.rB       = id_ex.rB
        pr.is_bubble = False

        m = id_ex.mnemonic
        a = id_ex.val_a
        b = id_ex.val_b
        c = id_ex.val_c

        if m == 'addq':
            result = a + b
        elif m == 'subq':
            result = b - a
        elif m == 'andq':
            result = a & b
        elif m == 'xorq':
            result = a ^ b
        elif m in ('irmovq', 'rrmovq', 'cmove'):
            result = c if m == 'irmovq' else a
        elif m == 'rmmovq':
            result = b + c
        elif m == 'mrmovq':
            result = b + c
        elif m == 'pushq':
            result = b - 8
        elif m == 'popq':
            result = b + 8
        elif m == 'call':
            result = b - 8
        elif m == 'ret':
            result = b + 8
        else:
            result = 0

        pr.val_e = result & 0xFFFFFFFFFFFFFFFF

        # Set condition codes for ALU ops
        if m in ('addq', 'subq', 'andq', 'xorq'):
            self.zf = 1 if result == 0 else 0
            self.sf = 1 if (result >> 63) & 1 else 0
            self.of = 0  # simplified

        # Evaluate condition for jumps/cmove
        pr.cnd = check_condition(m, self.zf, self.sf, self.of)

        return pr

    def memory_stage(self, ex_mem):
        pr = PipelineRegister()
        if ex_mem.is_bubble:
            return pr

        pr.mnemonic = ex_mem.mnemonic
        pr.addr     = ex_mem.addr
        pr.val_e    = ex_mem.val_e
        pr.dst_e    = ex_mem.dst_e
        pr.dst_m    = ex_mem.dst_m
        pr.cnd      = ex_mem.cnd
        pr.val_c    = ex_mem.val_c
        pr.is_bubble = False

        m = ex_mem.mnemonic

        if m == 'rmmovq':
            self.write_mem_int64(ex_mem.val_e, ex_mem.val_a if hasattr(ex_mem, 'val_a') else 0)
        elif m in ('mrmovq', 'popq'):
            pr.val_m = self.read_mem_int64(ex_mem.val_e)
        elif m == 'pushq':
            self.write_mem_int64(ex_mem.val_e, ex_mem.val_a if hasattr(ex_mem, 'val_a') else 0)
        elif m == 'call':
            self.write_mem_int64(ex_mem.val_e, self.pc)
        elif m == 'ret':
            pr.val_m = self.read_mem_int64(ex_mem.val_e - 8)

        return pr

    def writeback(self, mem_wb):
        if mem_wb.is_bubble:
            return

        m = mem_wb.mnemonic

        if m in ('rrmovq', 'irmovq', 'addq', 'subq', 'andq', 'xorq'):
            self.write_register(mem_wb.dst_e, mem_wb.val_e)
        elif m == 'cmove':
            if mem_wb.cnd:
                self.write_register(mem_wb.dst_e, mem_wb.val_e)
        elif m == 'mrmovq':
            self.write_register(mem_wb.dst_m, mem_wb.val_m)
        elif m in ('pushq', 'call'):
            self.write_register(4, mem_wb.val_e)  # update %rsp
        elif m in ('popq', 'ret'):
            self.write_register(4, mem_wb.val_e)  # update %rsp
            if m == 'popq':
                self.write_register(mem_wb.dst_m, mem_wb.val_m)
            elif m == 'ret':
                self.pc = mem_wb.val_m

        # Handle jumps
        if m in ('jmp', 'jle', 'jl', 'je', 'jne', 'jge', 'jg'):
            if mem_wb.cnd:
                self.pc = mem_wb.val_c

    def step(self):
        if self.halted and self.mem_wb.is_bubble and self.ex_mem.is_bubble and self.id_ex.is_bubble and self.if_id.is_bubble:
            return False

        # Capture stage snapshot before advancing
        snapshot = {
            'cycle': self.cycle,
            'stages': {
                'fetch':     self._stage_info(self.if_id,  'fetch'),
                'decode':    self._stage_info(self.id_ex,  'decode'),
                'execute':   self._stage_info(self.ex_mem, 'execute'),
                'memory':    self._stage_info(self.mem_wb, 'memory'),
                'writeback': {'mnemonic': 'bubble', 'addr': None, 'is_bubble': True},
            },
            'registers': self.registers[:],
            'pc': self.pc,
            'zf': self.zf, 'sf': self.sf, 'of': self.of,
            'events': []
        }

        # Run pipeline stages in reverse order (writeback first)
        self.writeback(self.mem_wb)
        new_mem_wb  = self.memory_stage(self.ex_mem)
        new_ex_mem  = self.execute(self.id_ex)
        new_id_ex   = self.decode(self.if_id)
        new_if_id   = self.fetch()

        # Detect load-use hazard (stall)
        stall = False
        if not self.if_id.is_bubble and not self.id_ex.is_bubble:
            if self.id_ex.mnemonic in ('mrmovq', 'popq'):
                if self.id_ex.dst_m in (self.if_id.rA, self.if_id.rB):
                    stall = True
                    snapshot['events'].append({
                        'type': 'stall',
                        'msg': f'Load-use hazard: {self.id_ex.mnemonic} result needed by {self.if_id.mnemonic}'
                    })

        if stall:
            # Hold fetch and decode, insert bubble into execute
            new_if_id  = self.if_id
            new_id_ex  = self.if_id
            new_ex_mem = PipelineRegister()  # bubble
            self.pc -= (self.if_id.addr - self.pc) if self.if_id.addr else 0

        # Check for forwarding events
        for fwd_reg, fwd_val in self._get_forwarding_sources():
            if fwd_reg != 0xF:
                reg_name = REGISTER_NAMES.get(fwd_reg, f'r{fwd_reg}')
                snapshot['events'].append({
                    'type': 'forward',
                    'msg': f'Forwarding {reg_name} = {fwd_val}'
                })

        self.if_id  = new_if_id
        self.id_ex  = new_id_ex
        self.ex_mem = new_ex_mem
        self.mem_wb = new_mem_wb

        snapshot['stages']['writeback'] = self._stage_info(self.mem_wb, 'writeback')
        snapshot['registers_after'] = self.registers[:]
        self.history.append(snapshot)
        self.cycle += 1
        return True

    def _stage_info(self, pr, stage_name):
        return {
            'mnemonic': pr.mnemonic,
            'addr': pr.addr,
            'is_bubble': pr.is_bubble,
            'val_e': getattr(pr, 'val_e', 0),
            'val_m': getattr(pr, 'val_m', 0),
            'dst_e': getattr(pr, 'dst_e', 0xF),
            'dst_m': getattr(pr, 'dst_m', 0xF),
        }

    def run_all(self):
        while self.step():
            if self.cycle > 1000:
                break

    def get_state(self):
        return {
            'cycle': self.cycle,
            'halted': self.halted,
            'registers': self.registers[:],
            'pc': self.pc,
            'zf': self.zf, 'sf': self.sf, 'of': self.of,
            'stages': {
                'fetch':     self._stage_info(self.if_id,  'fetch'),
                'decode':    self._stage_info(self.id_ex,  'decode'),
                'execute':   self._stage_info(self.ex_mem, 'execute'),
                'memory':    self._stage_info(self.mem_wb, 'memory'),
                'writeback': self._stage_info(self.mem_wb, 'writeback'),
            },
            'history': self.history,
            'memory': {k: v for k, v in self.memory_bytes.items()}
        }


if __name__ == '__main__':
    source = """
irmovq $10, %rax
irmovq $20, %rbx
addq %rax, %rbx
halt
"""
    sim = Simulator(source)
    sim.run_all()

    state = sim.get_state()
    print(f"Completed in {sim.cycle} cycles")
    print("Registers:")
    names = ['%rax','%rcx','%rdx','%rbx','%rsp','%rbp','%rsi','%rdi']
    for i, name in enumerate(names):
        if state['registers'][i] != 0:
            print(f"  {name} = {state['registers'][i]}")

    print("\nCycle log:")
    for snap in sim.history:
        stages = snap['stages']
        parts = []
        for s in STAGES:
            m = stages[s]['mnemonic']
            parts.append(f"{s[:2].upper()}:{m}")
        print(f"  Cycle {snap['cycle']}: {' | '.join(parts)}")
        for ev in snap['events']:
            print(f"    [{ev['type'].upper()}] {ev['msg']}")
