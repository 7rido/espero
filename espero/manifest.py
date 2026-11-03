"""A hash manifest for the folders that cannot be recorded again.

`data/hlcollect/`, `data/hlbook/`, `data/book/`, `data/aggr/forward/` and `data/aggr/forward5m/`
hold the only copy of what was recorded: Hyperliquid serves no history, and aggr deletes its bars
after days. They are ignored by git, so nothing in the repo says what they held. This writes
`MANIFEST.sha256` into such a folder, one line per file in `shasum -c` format, and checks a folder
against it. The publish script writes it before the weekly release; the fetch script checks it
after extracting.

    python -m espero.manifest write data/hlcollect data/hlbook
    python -m espero.manifest check data/hlcollect

It reads files and writes only the manifest. A `check` that finds a missing file exits 1; a file that
differs or an extra file is reported and exits 0, because a local recording that kept its own copy
of a day is allowed to differ from the release's.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import os
import zipfile
from pathlib import Path
from typing import Callable, Dict, List, Optional

NAME = "MANIFEST.sha256"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def hashes(folder: Path) -> Dict[str, str]:
    """Every file under `folder`, relative POSIX path -> sha256, the manifest itself left out."""
    out = {}
    for p in sorted(folder.rglob("*")):
        if p.is_file() and p.name != NAME:
            out[p.relative_to(folder).as_posix()] = sha256(p)
    return out


def write_atomic(path: Path, data: bytes, check: Optional[Callable[[bytes], None]] = None) -> Path:
    """Write `data` to `path` so a reader, or the next run, sees the whole file or none of it: a temporary file
    beside it, flushed to disk, read back through `check` (which raises on a bad file), then renamed into place.
    A crash or a failed check leaves the old file, or no file, never half of one: the recorders skip a day whose
    file exists, so a truncated one used to stop every later run until someone deleted it by hand."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        if check is not None:
            check(tmp.read_bytes())
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return path


def gzip_whole(blob: bytes) -> None:
    """A `check` for write_atomic: the gzip stream decompresses to its end."""
    gzip.decompress(blob)


def zip_whole(blob: bytes) -> None:
    """A `check` for write_atomic: every member of the zip reads back with its CRC."""
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        bad = z.testzip()
    if bad is not None:
        raise zipfile.BadZipFile(f"member {bad} fails its CRC")


def write(folder: Path) -> Path:
    """Write `folder/MANIFEST.sha256` and return its path. Lines are `<sha256>  <path>`, sorted."""
    folder = Path(folder)
    lines = [f"{h}  {rel}\n" for rel, h in sorted(hashes(folder).items())]
    return write_atomic(folder / NAME, "".join(lines).encode())


def read(path: Path) -> Dict[str, str]:
    out = {}
    for line in Path(path).read_text().splitlines():
        if not line.strip():
            continue
        h, _, rel = line.partition("  ")
        out[rel] = h
    return out


def check(folder: Path) -> Dict[str, List[str]]:
    """Compare `folder` with its manifest: {"ok": n, "missing": [...], "differs": [...], "extra": [...]}."""
    folder = Path(folder)
    want = read(folder / NAME)
    have = hashes(folder)
    missing = sorted(rel for rel in want if rel not in have)
    differs = sorted(rel for rel in want if rel in have and have[rel] != want[rel])
    extra = sorted(rel for rel in have if rel not in want)
    ok = len(want) - len(missing) - len(differs)
    return {"ok": ok, "missing": missing, "differs": differs, "extra": extra}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m espero.manifest", description=__doc__.split("\n\n")[0])
    ap.add_argument("action", choices=["write", "check"])
    ap.add_argument("folders", nargs="+", type=Path)
    args = ap.parse_args(argv)
    rc = 0
    for folder in args.folders:
        if not folder.is_dir():
            print(f"{folder}: not a folder")
            rc = 1
            continue
        if args.action == "write":
            path = write(folder)
            print(f"{folder}: {len(read(path))} files -> {path}")
            continue
        if not (folder / NAME).is_file():
            print(f"{folder}: no {NAME}")
            rc = 1
            continue
        r = check(folder)
        print(f"{folder}: {r['ok']} ok, {len(r['missing'])} missing, {len(r['differs'])} differ, "
              f"{len(r['extra'])} extra")
        for kind in ("missing", "differs", "extra"):
            for rel in r[kind]:
                print(f"  {kind}: {rel}")
        if r["missing"]:
            rc = 1
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
