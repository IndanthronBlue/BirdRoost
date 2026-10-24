from __future__ import annotations

import csv
from functools import lru_cache
from importlib.resources import files


def load_areas() -> list[tuple[str, str]]:
    resource = files("birdclass").joinpath("assets/areas.csv")
    with resource.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    areas = []
    for row in rows:
        label_parts = [row["are_name_cn"], row["sub_area_name"] or row["area_name"]]
        label = " — ".join(dict.fromkeys(part for part in label_parts if part))
        areas.append((row["area_code"], f"{label} [{row['area_code']}]"))
    return areas


@lru_cache(maxsize=1)
def _area_names() -> dict[str, str]:
    resource = files("birdclass").joinpath("assets/areas.csv")
    with resource.open("r", encoding="utf-8", newline="") as handle:
        return {row["area_code"]: row["are_name_cn"] for row in csv.DictReader(handle)}


def area_name_for_code(code: str) -> str:
    if code == "WORLD":
        return "全球"
    return _area_names().get(code, "全球")
