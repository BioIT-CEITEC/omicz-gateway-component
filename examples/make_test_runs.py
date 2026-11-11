#!/usr/bin/env python3
"""Generate synthetic instrument runs for trying out and testing OmiCZ Gateway.

File contents are pseudo-random bytes; only the folder layouts and the completion
files imitate real instruments. The same seed always produces the same bytes, so
the SHA-256 digests of the generated files are reproducible.

Small example runs (the ones committed in examples/runs/):

    python3 examples/make_test_runs.py small examples/runs

A large run, for example 2 TB in files of 100 GB, in the layout of an Illumina run:

    python3 examples/make_test_runs.py large /path/to/instrument-folder \\
        --name 260101_LARGE_0001_AFAKE01 --size 2TB --file-size 100GB

Only the Python standard library is needed.
"""

import argparse
import os
import random
import sys

CHUNK = 16 * 1024 * 1024  # write large files in 16 MiB pieces
UNITS = {"B": 1, "KB": 10**3, "MB": 10**6, "GB": 10**9, "TB": 10**12,
         "KIB": 2**10, "MIB": 2**20, "GIB": 2**30, "TIB": 2**40}


def parse_size(text: str) -> int:
    """'2TB', '100GB', '512MiB' or a plain number of bytes."""
    t = text.strip().upper().replace(" ", "")
    for unit in sorted(UNITS, key=len, reverse=True):
        if t.endswith(unit):
            return int(float(t[: -len(unit)]) * UNITS[unit])
    return int(t)


def write_random(path: str, size: int, seed: str) -> None:
    """Write `size` pseudo-random bytes that depend only on `seed`."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rng = random.Random(seed)
    with open(path, "wb") as f:
        left = size
        while left > 0:
            n = min(CHUNK, left)
            f.write(rng.randbytes(n))
            left -= n


def write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


# ── small example runs ────────────────────────────────────────────────────────

def illumina_run(root: str) -> str:
    """Signal method, exact name: complete when RTAComplete.txt appears."""
    run = os.path.join(root, "illumina", "260101_DEMO_0001_AFAKE01")
    write_text(os.path.join(run, "RunInfo.xml"),
               '<?xml version="1.0"?>\n<RunInfo Version="6">\n'
               '  <Run Id="260101_DEMO_0001_AFAKE01" Number="1">\n'
               '    <Flowcell>AFAKE01</Flowcell>\n    <Instrument>DEMO</Instrument>\n'
               '    <Date>2026-01-01</Date>\n  </Run>\n</RunInfo>\n')
    for cycle in (1, 2):
        for tile in (1, 2):
            name = f"C{cycle}.1/s_1_110{tile}.bcl"
            write_random(os.path.join(run, "Data/Intensities/BaseCalls/L001", name),
                         256 * 1024, f"illumina/{name}")
    for tile in (1, 2):
        name = f"s_1_110{tile}_a.png"
        write_random(os.path.join(run, "Thumbnail_Images/L001/C1.1", name),
                     16 * 1024, f"illumina/thumb/{name}")
    # written last, as on the instrument
    write_text(os.path.join(run, "RTAComplete.txt"), "RTA 3.0 run complete\n")
    return run


def nanopore_run(root: str) -> str:
    """Signal method, prefix: complete when a file named final_summary_* appears."""
    run = os.path.join(root, "nanopore", "20260101_1200_DEMO_FAKE0001")
    for i in range(3):
        name = f"pod5/FAKE0001_pass_{i}.pod5"
        write_random(os.path.join(run, name), 256 * 1024, f"nanopore/{name}")
    for i in range(2):
        name = f"fastq_pass/FAKE0001_pass_{i}.fastq.gz"
        write_random(os.path.join(run, name), 128 * 1024, f"nanopore/{name}")
    write_text(os.path.join(run, "final_summary_FAKE0001.txt"),
               "instrument=DEMO\nflow_cell_id=FAKE0001\nprotocol_run_id=demo\n"
               "pod5_files_in_final_dest=3\nfastq_files_in_final_dest=2\n")
    return run


def proteomics_run(root: str) -> str:
    """File stability: complete once analysis.tdf exists and stops changing in size."""
    run = os.path.join(root, "proteomics", "DEMO_sample01.d")
    write_random(os.path.join(run, "analysis.tdf_bin"), 1024 * 1024, "proteomics/analysis.tdf_bin")
    write_random(os.path.join(run, "analysis.tdf"), 64 * 1024, "proteomics/analysis.tdf")
    return run


def make_small(root: str) -> None:
    for make in (illumina_run, nanopore_run, proteomics_run):
        run = make(root)
        print(f"{run}  {folder_size(run) / 2**20:.2f} MiB")


# ── large synthetic run ───────────────────────────────────────────────────────

def make_large(instrument_dir: str, name: str, size: int, file_size: int, signal: str) -> None:
    """Files of `file_size` bytes (the last one smaller) adding up to `size`,
    then the completion file `signal`."""
    run = os.path.join(instrument_dir, name)
    if os.path.exists(run):
        sys.exit(f"{run} already exists")
    i, left = 0, size
    while left > 0:
        n = min(file_size, left)
        path = os.path.join(run, "Data", f"part_{i:05d}.bin")
        write_random(path, n, f"{name}/{i}")
        print(f"{path}  {n / 2**30:.2f} GiB", flush=True)
        left -= n
        i += 1
    if signal:
        write_text(os.path.join(run, signal), "run complete\n")
    print(f"{run}: {i} files, {size / 2**30:.2f} GiB")


def folder_size(path: str) -> int:
    return sum(os.path.getsize(os.path.join(d, f)) for d, _, files in os.walk(path) for f in files)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("small", help="the small example runs (one per completion method)")
    s.add_argument("root", help="output folder, e.g. examples/runs")
    l = sub.add_parser("large", help="one large run of random files")
    l.add_argument("instrument_dir", help="instrument output folder to write the run into")
    l.add_argument("--name", required=True, help="run folder name; must not exist yet")
    l.add_argument("--size", required=True, help="total size, e.g. 2TB, 500GiB")
    l.add_argument("--file-size", default="10GB", help="size of each file (default 10GB)")
    l.add_argument("--signal", default="RTAComplete.txt",
                   help="completion file written last (default RTAComplete.txt; '' for none)")
    a = p.parse_args()
    if a.cmd == "small":
        make_small(a.root)
    else:
        make_large(a.instrument_dir, a.name, parse_size(a.size), parse_size(a.file_size), a.signal)


if __name__ == "__main__":
    main()
