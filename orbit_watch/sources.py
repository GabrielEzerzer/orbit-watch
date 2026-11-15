# Where element sets come from: the source protocol and a local directory source.

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from orbit_watch.elements import ElementSet, parse_omm_csv, parse_omm_json, parse_tle

_PARSERS = {
    ".tle": parse_tle,
    ".3le": parse_tle,
    ".txt": parse_tle,
    ".json": parse_omm_json,
    ".csv": parse_omm_csv,
}


class ElementSource(Protocol):
    def load(self, norad_ids: Iterable[int]) -> list[ElementSet]:
        ...


class DirectorySource:
    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        if not self.directory.is_dir():
            raise NotADirectoryError(self.directory)

    def load(self, norad_ids: Iterable[int]) -> list[ElementSet]:
        wanted = set(norad_ids)
        records: list[ElementSet] = []
        for path in sorted(self.directory.iterdir()):
            parser = _PARSERS.get(path.suffix.lower())
            if parser is None or not path.is_file():
                continue
            try:
                parsed = parser(path.read_text(encoding="utf-8"))
            except ValueError as exc:
                raise ValueError(f"{path}: {exc}") from exc
            records.extend(r for r in parsed if r.norad_id in wanted)
        return records
