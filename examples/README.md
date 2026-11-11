# Test data

Small synthetic runs for trying out OmiCZ Gateway without an instrument. The file
contents are pseudo-random bytes; only the folder layouts and the completion files
imitate real instruments. All three runs are already complete, so the gateway
registers each one as soon as its instrument is added.

| Folder | Run | Imitates | Size |
| --- | --- | --- | --- |
| `runs/illumina/` | `260101_DEMO_0001_AFAKE01` | Illumina sequencer run folder | 1.0 MiB, 8 files |
| `runs/nanopore/` | `20260101_1200_DEMO_FAKE0001` | Oxford Nanopore run folder | 1.0 MiB, 6 files |
| `runs/proteomics/` | `DEMO_sample01.d` | Bruker timsTOF `.d` folder | 1.1 MiB, 2 files |

## Instrument models to use

| Run | Completion method | Settings | Exclusion patterns (on the instrument) |
| --- | --- | --- | --- |
| Illumina | Signal | `RTAComplete.txt`, match **exact** | `Thumbnail_Images`, `*.png` |
| Nanopore | Signal | `final_summary_`, match **prefix** | none |
| Proteomics | File stability | file `analysis.tdf`, threshold 1 min | none |

With these exclusion patterns, the two thumbnail images of the Illumina run are
not checksummed or uploaded, so its manifest lists 6 digests, not 8.

## Generating runs

The runs above are made by `make_test_runs.py`, which needs only Python 3.9 or later:

```bash
python3 examples/make_test_runs.py small examples/runs
```

The same seed always gives the same bytes, so the files and their SHA-256 digests
are identical on every computer.

The script also writes large runs for throughput tests, for example 2 TB in
files of 100 GB, followed by an `RTAComplete.txt`:

```bash
python3 examples/make_test_runs.py large /path/to/instrument-folder \
    --name 260101_LARGE_0001_AFAKE01 --size 2TB --file-size 100GB
```

Write a large run into a folder that is mounted as an instrument (see the main
README); the gateway picks it up when the completion file appears.
