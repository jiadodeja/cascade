# Cascade

A visual Y86-64 PIPE simulator. Write assembly, step through it cycle by cycle, and watch each instruction move through the five pipeline stages in real time. Forwarding, stalls, branch flushes, and call/ret are all shown as they happen.

## Why

I struggled to understand pipelining when I took computer architecture. The textbook diagrams are static and it's hard to see how instructions actually flow through the hardware. I built this so you can write real Y86-64 assembly and watch it execute one clock cycle at a time.

## How it works

There are three parts.

**Assembler** (`assembler.py`) takes Y86-64 assembly and converts it to machine bytes. Two passes: first pass collects label addresses, second pass encodes each instruction into its binary form based on the Y86-64 instruction set.

**Simulator** (`simulator.py`) implements the full 5-stage PIPE pipeline from CS:APP (Bryant and O'Hallaron). Each call to `step()` advances the pipeline by one clock cycle. It handles data forwarding from EX/MEM and MEM/WB pipeline registers back to execute, load-use hazard detection and stalling, branch resolution with predict not-taken flushing, and call/ret with pipeline redirect.

**Frontend** (`index.html` + `api.py`) is a Flask API that exposes the assembler and simulator over HTTP. The browser renders three views: a live pipeline diagram showing which instruction is in each stage, a register file that highlights changes each cycle, and an instruction timeline that builds up so you can see the full execution history.

## Supported instructions

Full Y86-64 instruction set: `halt`, `nop`, `rrmovq`, `irmovq`, `rmmovq`, `mrmovq`, `addq`, `subq`, `andq`, `xorq`, `jmp`, `jle`, `jl`, `je`, `jne`, `jge`, `jg`, `call`, `ret`, `pushq`, `popq`, `cmove`. Labels are supported.

## Running it

```bash
pip install flask flask-cors
python api.py
```

Then open `index.html` in your browser. Write some assembly, click Load, then step through it or run it all at once.

## Example programs

Simple arithmetic:
```
irmovq $10, %rax
irmovq $20, %rbx
addq %rax, %rbx
halt
```

Loop summing 1 to 5 (watch the branch flush on each iteration):
```
irmovq $5, %rcx
irmovq $0, %rax
loop:
    addq %rcx, %rax
    irmovq $1, %rbx
    subq %rbx, %rcx
    jne loop
halt
```

Function call with ret:
```
irmovq $0x100, %rsp
call add
halt
add:
    irmovq $10, %rax
    irmovq $20, %rbx
    addq %rax, %rbx
    ret
```

Fibonacci (8th term = 21):
```
irmovq $0, %rax
irmovq $1, %rbx
irmovq $7, %rcx
loop:
    rrmovq %rbx, %rdx
    addq %rax, %rbx
    rrmovq %rdx, %rax
    irmovq $1, %rsi
    subq %rsi, %rcx
    jne loop
halt
```
