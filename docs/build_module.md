# Phase 3: Building Custom BBR Kernel Modules

**CSE 534 — BBR Under Mixed Workloads**
Authors: Adri Katyayan, Mehtaab Naazneen Mohammed

This document explains how to compile `tcp_bbr.c` as a loadable `.ko` module with a
modified `pacing_gain[]` probe-up entry. Three variants are needed: 1.10, 1.15, 1.20.

---

## Why a Loadable Module (not a Full Kernel Rebuild)

Rebuilding the Linux kernel takes 30+ minutes and risks breaking WSL2 entirely.
A loadable module compiles in under 2 minutes and can be loaded/unloaded with `insmod`/`rmmod`
without rebooting. This is the standard approach for in-tree TCP CCA modifications.

---

## Step 0: Identify Your Exact Kernel Version

```bash
uname -r
# Expected on Adri's machine: 6.6.87.2-microsoft-standard-WSL2
```

The module MUST be built against this exact kernel version. A module built for 6.6.86 will
refuse to load on 6.6.87. The kernel is picky and has no apologies about it.

---

## Step 1: Install Build Dependencies

```bash
sudo apt-get update
sudo apt-get install -y build-essential linux-headers-$(uname -r) bc kmod
```

If `linux-headers-$(uname -r)` is not available (common for Microsoft WSL2 kernels), you
need to obtain the kernel source manually. See Step 1b.

### Step 1b: WSL2-Specific Header Workaround

Microsoft's WSL2 kernels are not always packaged with headers in the standard Ubuntu repos.
Clone the WSL2 kernel source at the correct tag:

```bash
# Check your kernel version first
uname -r   # e.g. 6.6.87.2-microsoft-standard-WSL2

# Clone Microsoft's WSL2 kernel repo
git clone --depth=1 --branch linux-msft-wsl-6.6.87.2 \
    https://github.com/microsoft/WSL2-Linux-Kernel.git \
    ~/wsl2-kernel

cd ~/wsl2-kernel

# Copy the running kernel's config into the source tree
zcat /proc/config.gz > .config    # WSL2 exposes config via /proc/config.gz
# If /proc/config.gz doesn't exist: sudo modprobe configs  then try again

# Prepare the source tree for external module building
make KCONFIG_CONFIG=.config oldconfig
make KCONFIG_CONFIG=.config prepare
make KCONFIG_CONFIG=.config modules_prepare

# The headers dir you'll reference in the Makefile:
export KDIR=~/wsl2-kernel
```

---

## Step 2: Get the tcp_bbr.c Source

The source must match your running kernel. Options (in order of preference):

**Option A: Extract from the WSL2 kernel source (recommended)**

```bash
# If you cloned in Step 1b:
cp ~/wsl2-kernel/net/ipv4/tcp_bbr.c ~/BBR\ congestion\ ctrl/BBR-congestion-control-study/modules/tcp_bbr_base.c
```

**Option B: Copy from the running system (if available)**

```bash
# Some systems ship the kernel source under /usr/src
ls /usr/src/linux-source-*/net/ipv4/tcp_bbr.c
```

**Option C: Download from kernel.org**

```bash
# Match the version prefix (6.6.x):
wget https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.6.87.tar.xz
tar xf linux-6.6.87.tar.xz linux-6.6.87/net/ipv4/tcp_bbr.c
cp linux-6.6.87/net/ipv4/tcp_bbr.c ~/BBR\ congestion\ ctrl/BBR-congestion-control-study/modules/tcp_bbr_base.c
```

---

## Step 3: Edit pacing_gain[] for Each Variant

The probe-up gain lives in the `pacing_gain[]` array in `tcp_bbr.c`.
In BBRv1, it looks roughly like:

```c
static const int bbr_pacing_gain[] = {
    BBR_UNIT * 5 / 4,   /* probe for more available bw */   // <-- index 1, this is 1.25
    BBR_UNIT * 3 / 4,   /* drain queue and/or yield bw */
    BBR_UNIT, BBR_UNIT, BBR_UNIT, BBR_UNIT, BBR_UNIT, BBR_UNIT, /* cruise */
};
```

`BBR_UNIT` is 256 (a fixed-point scaling factor). So:
- 1.25 = `256 * 5 / 4` = 320
- 1.20 = `256 * 6 / 5` = 307 (or just hardcode 307)
- 1.15 = `256 * 23 / 20` = 294
- 1.10 = `256 * 11 / 10` = 281

**For each variant, make a separate copy of `tcp_bbr_base.c` and edit index 1:**

```bash
cd ~/BBR\ congestion\ ctrl/BBR-congestion-control-study/modules

# Variant 1.20
cp tcp_bbr_base.c tcp_bbr_gain120.c
# Edit: change BBR_UNIT * 5 / 4  →  307   at the probe-up line
# Also rename the module: change .name = "bbr"  →  .name = "bbr_mod"
# Also rename the struct:  tcp_bbr → tcp_bbr_mod (to avoid symbol conflicts with stock tcp_bbr)

# Variant 1.15
cp tcp_bbr_base.c tcp_bbr_gain115.c
# Edit: change probe-up to 294, rename to bbr_mod

# Variant 1.10
cp tcp_bbr_base.c tcp_bbr_gain110.c
# Edit: change probe-up to 281, rename to bbr_mod
```

**Critical rename: the module name in the source.**
You MUST change `.name = "bbr"` to `.name = "bbr_mod"` in the `tcp_congestion_ops` struct.
Otherwise the module conflicts with the already-loaded stock `tcp_bbr` module.

Also rename the struct itself (`tcp_bbr_ops` → `tcp_bbr_mod_ops`) and all functions
that have `tcp_bbr_` prefix to `tcp_bbr_mod_` to avoid linker symbol conflicts.

A sed one-liner to handle the easy renames (verify afterwards):

```bash
sed -i 's/\.name = "bbr"/.name = "bbr_mod"/g; s/tcp_bbr_ops/tcp_bbr_mod_ops/g' tcp_bbr_gain110.c
```

---

## Step 4: Write the Makefile

Create `modules/Makefile`:

```makefile
# Makefile for Phase 3 BBR gain variant modules
# One target per gain variant. Building all three at once is efficient and satisfying.

KDIR ?= /lib/modules/$(shell uname -r)/build

obj-m += tcp_bbr_gain110.o
obj-m += tcp_bbr_gain115.o
obj-m += tcp_bbr_gain120.o

all:
	$(MAKE) -C $(KDIR) M=$(PWD) modules

clean:
	$(MAKE) -C $(KDIR) M=$(PWD) clean
```

If you used the WSL2 kernel source from Step 1b, override KDIR:

```bash
make KDIR=~/wsl2-kernel
```

---

## Step 5: Compile

```bash
cd ~/BBR\ congestion\ ctrl/BBR-congestion-control-study/modules

# Standard case (headers available via apt):
make

# WSL2 case with custom kernel source:
make KDIR=~/wsl2-kernel
```

Success looks like three `.ko` files:

```
tcp_bbr_gain110.ko
tcp_bbr_gain115.ko
tcp_bbr_gain120.ko
```

Failure usually looks like a wall of red text about undefined symbols.
The most common cause is a kernel version mismatch between your headers and running kernel.
Run `uname -r` and `ls /lib/modules/` and verify they match.

---

## Step 6: Verify the Modules (Before Running Phase 3)

```bash
# Check module metadata and dependencies
modinfo tcp_bbr_gain110.ko

# Test load/unload cycle:
sudo rmmod tcp_bbr       # unload stock BBR first (it conflicts)
sudo insmod tcp_bbr_gain110.ko

# Verify CCA is now registered:
sysctl net.ipv4.tcp_available_congestion_control
# Should include "bbr_mod"

# Test that iperf3 can actually use it:
iperf3 -s -D
iperf3 -c 127.0.0.1 -C bbr_mod -t 3 -J | python3 -c "import sys,json; d=json.load(sys.stdin); print('OK:', d['end']['sum_sent']['bits_per_second']/1e6, 'Mbps')"

# Clean up:
sudo rmmod tcp_bbr_gain110
sudo modprobe tcp_bbr    # reload stock BBR
```

If `insmod` fails with `Operation not permitted` — Secure Boot may be blocking unsigned modules.
Disable Secure Boot in BIOS or sign the module. In WSL2 this is usually not an issue.

If `insmod` fails with `Invalid module format` — the `.ko` was built for a different kernel.
Rebuild with the correct KDIR.

---

## Step 7: Run phase3_experiment.py

Once all three `.ko` files are verified:

```bash
cd ~/BBR\ congestion\ ctrl/BBR-congestion-control-study
source bbrenv/bin/activate
sudo python3 scripts/phase3_experiment.py
```

The script handles module loading/unloading between gain variants automatically.
Do not manually load modules before running the script — it does that for you.

---

## Mehtaab's Role for Phase 3

Phase 3 is Adri's primary deliverable. Mehtaab's Phase 3 contributions are:

1. **Run `phase3_analysis.py`** once Adri has pushed Phase 3 result JSONs to the repo.
   The analysis script needs no kernel module access — it only reads JSON files.

2. **Write the Phase 3 results section** of the paper based on the figures.

3. **Replicate the 10KB/40ms config** on her WSL2 machine as an independent data point,
   if time permits. This requires building the modules on her machine using this guide.

---

## Troubleshooting Cheatsheet

| Symptom | Likely Cause | Fix |
|---|---|---|
| `insmod: ERROR: could not insert module: Invalid module format` | Kernel version mismatch | Rebuild with correct KDIR |
| `insmod: ERROR: could not insert module: Operation not permitted` | Secure Boot | Disable in BIOS or sign module |
| `bbr_mod` not in `tcp_available_congestion_control` | Module load failed silently | Check `dmesg` for symbol errors |
| Linker error: `multiple definition of tcp_bbr_...` | Stock tcp_bbr still loaded | `sudo rmmod tcp_bbr` before `insmod` |
| `make: *** No rule to make target` | KDIR points to wrong location | Verify `ls $KDIR/Makefile` exists |
| WSL2 headers not found via apt | Microsoft custom kernel | Follow Step 1b (clone WSL2 kernel) |
