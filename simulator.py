from assembler import assemble, REGISTERS, ICODES, FN

REGISTER_NAMES = {v: k for k, v in REGISTERS.items()}

STAGES = ['fetch', 'decode', 'execute', 'memory', 'writeback']

JUMP_MNEMONICS  = ('jmp', 'jle', 'jl', 'je', 'jne', 'jge', 'jg')
ALU_MNEMONICS   = ('addq', 'subq', 'andq', 'xorq')
STACK_MNEMONICS = ('pushq', 'popq', 'call', 'ret')


def check_condition(mnemonic, zf, sf, of):
    if mnemonic == 'jmp':   return True
    if mnemonic == 'jle':   return bool((sf ^ of) | zf)
    if mnemonic == 'jl':    return bool(sf ^ of)
    if mnemonic == 'je':    return bool(zf)
    if mnemonic == 'jne':   return not bool(zf)
    if mnemonic == 'jge':   return not bool(sf ^ of)
    if mnemonic == 'jg':    return (not bool(sf ^ of)) and (not bool(zf))
    if mnemonic == 'cmove': return bool((sf ^ of) | zf)
    return False


class PipelineRegister:
    def __init__(self):
        self.mnemonic  = 'bubble'
        self.addr      = None
        self.rA        = 0xF
        self.rB        = 0xF
        self.val_c     = 0
        self.val_a     = 0
        self.val_b     = 0
        self.val_e     = 0
        self.val_m     = 0
        self.dst_e     = 0xF
        self.dst_m     = 0xF
        self.cnd       = False
        self.is_bubble = True
        self.is_halt   = False


def dst_e_of(mnemonic, rB):
    if mnemonic in ('rrmovq', 'cmove', 'irmovq', 'addq', 'subq', 'andq', 'xorq'):
        return rB
    if mnemonic in STACK_MNEMONICS:
        return 4
    return 0xF


def dst_m_of(mnemonic, rA):
    if mnemonic in ('mrmovq', 'popq'):
        return rA
    return 0xF


class Simulator:
    def __init__(self, source):
        self.memory_bytes, self.symbols, self.decoded = assemble(source)
        self.registers = [0] * 15
        self.pc        = 0
        self.cycle     = 0
        self.halted    = False
        self.zf = self.sf = self.of = 0

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
        for i, byte in enumerate((value & 0xFFFFFFFFFFFFFFFF).to_bytes(8, 'little')):
            self.memory_bytes[addr + i] = byte

    def read_reg(self, rid):
        return 0 if rid == 0xF else self.registers[rid]

    def write_reg(self, rid, val):
        if rid != 0xF:
            self.registers[rid] = val & 0xFFFFFFFFFFFFFFFF

    def forward_val(self, rid, ex_mem, mem_wb):
        if rid == 0xF:
            return 0
        if not ex_mem.is_bubble and ex_mem.dst_e == rid:
            return ex_mem.val_e
        if not mem_wb.is_bubble and mem_wb.dst_m == rid:
            return mem_wb.val_m
        if not mem_wb.is_bubble and mem_wb.dst_e == rid:
            return mem_wb.val_e
        return self.read_reg(rid)

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
        elif mnemonic in JUMP_MNEMONICS + ('call',):
            pr.val_c = self.read_mem_int64(pc + 1)
            self.pc = pc + 9

        if mnemonic == 'halt':
            pr.is_halt = True

        return pr

    def decode(self, if_id):
        pr = PipelineRegister()
        if if_id.is_bubble:
            return pr

        pr.mnemonic  = if_id.mnemonic
        pr.addr      = if_id.addr
        pr.rA        = if_id.rA
        pr.rB        = if_id.rB
        pr.val_c     = if_id.val_c
        pr.is_bubble = False
        pr.is_halt   = if_id.is_halt

        pr.val_a = self.read_reg(if_id.rA)
        pr.val_b = self.read_reg(if_id.rB)

        pr.dst_e = dst_e_of(if_id.mnemonic, if_id.rB)
        pr.dst_m = dst_m_of(if_id.mnemonic, if_id.rA)

        return pr

    def execute(self, id_ex, ex_mem, mem_wb):
        pr = PipelineRegister()
        if id_ex.is_bubble:
            return pr

        pr.mnemonic  = id_ex.mnemonic
        pr.addr      = id_ex.addr
        pr.val_c     = id_ex.val_c
        pr.dst_e     = id_ex.dst_e
        pr.dst_m     = id_ex.dst_m
        pr.rA        = id_ex.rA
        pr.rB        = id_ex.rB
        pr.is_bubble = False
        pr.is_halt   = id_ex.is_halt

        m = id_ex.mnemonic

        a = self.forward_val(id_ex.rA, ex_mem, mem_wb)
        if m in STACK_MNEMONICS:
            b = self.forward_val(4, ex_mem, mem_wb)
        else:
            b = self.forward_val(id_ex.rB, ex_mem, mem_wb)

        c = id_ex.val_c
        pr.val_a = a

        if   m == 'addq':   result = a + b
        elif m == 'subq':   result = b - a
        elif m == 'andq':   result = a & b
        elif m == 'xorq':   result = a ^ b
        elif m == 'irmovq': result = c
        elif m in ('rrmovq', 'cmove'): result = a
        elif m in ('rmmovq', 'mrmovq'): result = b + c
        elif m in ('pushq', 'call'):    result = b - 8
        elif m in ('popq',  'ret'):     result = b + 8
        else:                            result = 0

        pr.val_e = result & 0xFFFFFFFFFFFFFFFF

        if m in ALU_MNEMONICS:
            signed = result if result < (1 << 63) else result - (1 << 64)
            self.zf = 1 if signed == 0 else 0
            self.sf = 1 if signed < 0  else 0
            self.of = 0

        pr.cnd = check_condition(m, self.zf, self.sf, self.of)
        return pr

    def memory_stage(self, ex_mem):
        pr = PipelineRegister()
        if ex_mem.is_bubble:
            return pr

        pr.mnemonic  = ex_mem.mnemonic
        pr.addr      = ex_mem.addr
        pr.val_e     = ex_mem.val_e
        pr.val_a     = ex_mem.val_a
        pr.dst_e     = ex_mem.dst_e
        pr.dst_m     = ex_mem.dst_m
        pr.cnd       = ex_mem.cnd
        pr.val_c     = ex_mem.val_c
        pr.is_bubble = False
        pr.is_halt   = ex_mem.is_halt

        m = ex_mem.mnemonic

        if m == 'rmmovq':
            self.write_mem_int64(ex_mem.val_e, ex_mem.val_a)
        elif m == 'pushq':
            self.write_mem_int64(ex_mem.val_e, ex_mem.val_a)
        elif m == 'call':
            return_addr = ex_mem.addr + 9
            self.write_mem_int64(ex_mem.val_e, return_addr)
        elif m == 'mrmovq':
            pr.val_m = self.read_mem_int64(ex_mem.val_e)
        elif m == 'popq':
            pr.val_m = self.read_mem_int64(ex_mem.val_e - 8)
        elif m == 'ret':
            pr.val_m = self.read_mem_int64(ex_mem.val_e - 8)

        return pr

    def writeback(self, mem_wb):
        if mem_wb.is_bubble:
            return

        if mem_wb.is_halt:
            self.halted = True
            return

        m = mem_wb.mnemonic

        if m in ('rrmovq', 'irmovq', 'addq', 'subq', 'andq', 'xorq'):
            self.write_reg(mem_wb.dst_e, mem_wb.val_e)
        elif m == 'cmove':
            if mem_wb.cnd:
                self.write_reg(mem_wb.dst_e, mem_wb.val_e)
        elif m == 'mrmovq':
            self.write_reg(mem_wb.dst_m, mem_wb.val_m)
        elif m == 'pushq':
            self.write_reg(4, mem_wb.val_e)
        elif m == 'call':
            self.write_reg(4, mem_wb.val_e)
        elif m == 'popq':
            self.write_reg(4, mem_wb.val_e)
            self.write_reg(mem_wb.dst_m, mem_wb.val_m)
        # ret is handled in step()

    def _forwarding_events(self, ex_mem, mem_wb):
        events = []
        if not ex_mem.is_bubble and ex_mem.dst_e != 0xF:
            name = REGISTER_NAMES.get(ex_mem.dst_e, f'r{ex_mem.dst_e}')
            events.append({'type': 'forward', 'msg': f'Forwarding {name} = {ex_mem.val_e} from EX/MEM'})
        if not mem_wb.is_bubble:
            if mem_wb.dst_e != 0xF:
                name = REGISTER_NAMES.get(mem_wb.dst_e, f'r{mem_wb.dst_e}')
                events.append({'type': 'forward', 'msg': f'Forwarding {name} = {mem_wb.val_e} from MEM/WB'})
            if mem_wb.dst_m != 0xF:
                name = REGISTER_NAMES.get(mem_wb.dst_m, f'r{mem_wb.dst_m}')
                events.append({'type': 'forward', 'msg': f'Forwarding {name} = {mem_wb.val_m} from MEM/WB load'})
        return events

    def step(self):
        done = (self.halted and
                self.if_id.is_bubble and self.id_ex.is_bubble and
                self.ex_mem.is_bubble and self.mem_wb.is_bubble)
        if done:
            return False

        events = []

        stall = False
        if not self.if_id.is_bubble and not self.id_ex.is_bubble:
            if self.id_ex.mnemonic in ('mrmovq', 'popq'):
                if self.id_ex.dst_m in (self.if_id.rA, self.if_id.rB):
                    stall = True
                    reg_name = REGISTER_NAMES.get(self.id_ex.dst_m, '?')
                    events.append({'type': 'stall', 'msg': f'Load-use hazard on {reg_name}'})

        events += self._forwarding_events(self.ex_mem, self.mem_wb)

        snapshot = {
            'cycle': self.cycle,
            'stages': {
                'fetch':     self._stage_info(self.if_id),
                'decode':    self._stage_info(self.id_ex),
                'execute':   self._stage_info(self.ex_mem),
                'memory':    self._stage_info(self.mem_wb),
                'writeback': self._stage_info(self.mem_wb),
            },
            'registers': self.registers[:],
            'events': events,
        }

        self.writeback(self.mem_wb)
        new_mem_wb = self.memory_stage(self.ex_mem)
        new_ex_mem = self.execute(self.id_ex, self.ex_mem, self.mem_wb)
        new_id_ex  = self.decode(self.if_id)
        new_if_id  = self.fetch()

        # Priority: ret > call > conditional jump
        if not new_mem_wb.is_bubble and new_mem_wb.mnemonic == 'ret':
            # Apply ret effects immediately and flush pipeline
            self.write_reg(4, new_mem_wb.val_e)
            ret_target = new_mem_wb.val_m
            # Fetch exactly the return target instruction then stop
            self.pc = ret_target
            self.halted = False
            ret_fetch = self.fetch()
            self.halted = True   # stop after this one instruction
            new_if_id  = ret_fetch
            new_id_ex  = PipelineRegister()
            new_ex_mem = PipelineRegister()
            new_mem_wb = PipelineRegister()
            events.append({'type': 'stall', 'msg': f'Return to 0x{ret_target:03x}'})

        elif not new_ex_mem.is_bubble and new_ex_mem.mnemonic == 'call':
            self.pc = new_ex_mem.val_c
            self.halted = False
            new_if_id = PipelineRegister()
            new_id_ex = PipelineRegister()
            events.append({'type': 'stall', 'msg': f'Call to 0x{new_ex_mem.val_c:03x}. Flushing pipeline'})

        elif not new_ex_mem.is_bubble and new_ex_mem.mnemonic in JUMP_MNEMONICS:
            if new_ex_mem.cnd:
                self.pc = new_ex_mem.val_c
                self.halted = False
                new_if_id = PipelineRegister()
                new_id_ex = PipelineRegister()
                events.append({'type': 'stall', 'msg': f'Branch taken. Jumping to 0x{new_ex_mem.val_c:03x}'})

        if stall:
            new_if_id  = self.if_id
            new_id_ex  = self.if_id
            new_ex_mem = PipelineRegister()

        self.if_id  = new_if_id
        self.id_ex  = new_id_ex
        self.ex_mem = new_ex_mem
        self.mem_wb = new_mem_wb

        snapshot['registers_after'] = self.registers[:]
        self.history.append(snapshot)
        self.cycle += 1
        return True

    def _stage_info(self, pr):
        return {
            'mnemonic':  pr.mnemonic,
            'addr':      pr.addr,
            'is_bubble': pr.is_bubble,
            'val_e':     pr.val_e,
            'val_m':     pr.val_m,
            'dst_e':     pr.dst_e,
            'dst_m':     pr.dst_m,
        }

    def run_all(self):
        while self.step():
            if self.cycle > 1000:
                break

    def get_state(self):
        return {
            'cycle':     self.cycle,
            'halted':    self.halted,
            'registers': self.registers[:],
            'pc':        self.pc,
            'zf': self.zf, 'sf': self.sf, 'of': self.of,
            'stages': {
                'fetch':     self._stage_info(self.if_id),
                'decode':    self._stage_info(self.id_ex),
                'execute':   self._stage_info(self.ex_mem),
                'memory':    self._stage_info(self.mem_wb),
                'writeback': self._stage_info(self.mem_wb),
            },
            'history': self.history,
            'memory':  {k: v for k, v in self.memory_bytes.items()},
        }


if __name__ == '__main__':
    tests = [
        ("pushq/popq", """
irmovq $42, %rax
irmovq $0x100, %rsp
pushq %rax
popq %rbx
halt
""", {'%rbx': 42, '%rsp': 256}),
        ("loop", """
irmovq $5, %rcx
irmovq $0, %rax
loop:
    addq %rcx, %rax
    irmovq $1, %rbx
    subq %rbx, %rcx
    jne loop
halt
""", {'%rax': 15}),
        ("addq forwarding", """
irmovq $10, %rax
irmovq $20, %rbx
addq %rax, %rbx
halt
""", {'%rax': 10, '%rbx': 30}),
        ("call/ret", """
irmovq $0x100, %rsp
call add
halt
add:
    irmovq $10, %rax
    irmovq $20, %rbx
    addq %rax, %rbx
    ret
""", {'%rax': 10, '%rbx': 30, '%rsp': 256}),
        ("call/ret double", """
irmovq $0x200, %rsp
call double
halt
double:
    irmovq $10, %rax
    addq %rax, %rax
    ret
""", {'%rax': 20, '%rsp': 0x200}),
    ]

    for name, source, expected in tests:
        sim = Simulator(source)
        sim.run_all()
        regs = {'%rax':0,'%rcx':1,'%rdx':2,'%rbx':3,'%rsp':4,'%rbp':5,'%rsi':6,'%rdi':7}
        ok = all(sim.registers[regs[k]] == v for k, v in expected.items())
        status = "PASS" if ok else "FAIL"
        print(f"{status}: {name} ({sim.cycle} cycles)")
        if not ok:
            for k, v in expected.items():
                actual = sim.registers[regs[k]]
                if actual != v:
                    print(f"  {k}: expected {v}, got {actual}")
