from __future__ import annotations

import csv
from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from typing import Iterable

TAXONOMY_VERSION = "IOC 15.2"
TAXONOMY_RESOURCE = "assets/taxonomy/ioc_15_2_birds.csv"
ALIASES_RESOURCE = "assets/taxonomy/taxonomy_aliases.csv"

KINGDOM_ZH = "动物界"
KINGDOM_LATIN = "Animalia"
PHYLUM_ZH = "脊索动物门"
PHYLUM_LATIN = "Chordata"
CLASS_ZH = "鸟纲"
CLASS_LATIN = "Aves"
RANKS = ("界", "门", "纲", "目", "科", "属", "种")


@dataclass(frozen=True)
class Taxon:
    taxonomy_key: str
    scientific_name: str
    name_zh: str
    name_zh_trad: str
    name_en: str
    genus: str
    family: str
    order: str
    animal_class: str
    phylum: str
    kingdom: str
    order_zh: str = ""
    family_zh: str = ""
    version: str = ""
    source: str = ""

    @property
    def display_name(self) -> str:
        return self.name_zh or self.name_en or self.scientific_name

    @property
    def order_label(self) -> str:
        return self.order_zh or self.order

    @property
    def family_label(self) -> str:
        return self.family_zh or self.family

    @property
    def genus_label(self) -> str:
        return self.genus

    def tree_path(self) -> tuple[str, ...]:
        return (
            self.kingdom,
            self.phylum,
            self.animal_class,
            self.order,
            self.family,
            self.genus,
            self.scientific_name,
        )

    def hierarchy(self) -> tuple[tuple[str, str, str], ...]:
        """Return (rank, Chinese label, scientific label) from kingdom to species."""
        return (
            ("界", KINGDOM_ZH, KINGDOM_LATIN),
            ("门", PHYLUM_ZH, PHYLUM_LATIN),
            ("纲", CLASS_ZH, CLASS_LATIN),
            ("目", self.order_label, self.order),
            ("科", self.family_label, self.family),
            ("属", self.genus_label, self.genus),
            ("种", self.display_name, self.scientific_name),
        )


@dataclass(frozen=True)
class _Loaded:
    taxa: tuple[Taxon, ...]
    by_scientific: dict[str, Taxon]
    by_chinese: dict[str, Taxon | None]
    by_english: dict[str, Taxon | None]
    aliases: dict[str, str]


def _fold(value: str) -> str:
    return " ".join(value.strip().split()).casefold()


def _scientific_key(value: str) -> str:
    folded = _fold(value)
    if not folded:
        return ""
    parts = folded.split()
    if len(parts) >= 2:
        return " ".join(parts[:2])
    return folded


def _read_rows(resource_name: str) -> list[dict[str, str]]:
    resource = files("birdclass").joinpath(resource_name)
    with resource.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


@lru_cache(maxsize=1)
def load_taxonomy() -> "Taxonomy":
    rows = _read_rows(TAXONOMY_RESOURCE)
    taxa = tuple(
        Taxon(
            taxonomy_key=row["taxonomy_key"],
            scientific_name=row["scientific_name"],
            name_zh=row.get("name_zh", ""),
            name_zh_trad=row.get("name_zh_trad", ""),
            name_en=row.get("name_en", ""),
            genus=row["genus"],
            family=row["family"],
            order=row["order"],
            animal_class=row["class"],
            phylum=row["phylum"],
            kingdom=row["kingdom"],
            order_zh=row.get("order_zh", ""),
            family_zh=row.get("family_zh", ""),
            version=row.get("version", ""),
            source=row.get("source", ""),
        )
        for row in rows
    )
    by_scientific = {taxon.taxonomy_key: taxon for taxon in taxa}

    by_chinese: dict[str, Taxon | None] = {}
    by_english: dict[str, Taxon | None] = {}
    for taxon in taxa:
        for key, mapping in (
            (_fold(taxon.name_zh), by_chinese),
            (_fold(taxon.name_zh_trad), by_chinese),
            (_fold(taxon.name_en), by_english),
        ):
            if not key:
                continue
            if key in mapping and mapping[key] is not taxon:
                mapping[key] = None
            else:
                mapping.setdefault(key, taxon)

    aliases: dict[str, str] = {}
    for row in _read_rows(ALIASES_RESOURCE):
        aliases[_fold(row["alias"])] = _scientific_key(row["scientific_name"])

    return Taxonomy(_Loaded(taxa, by_scientific, by_chinese, by_english, aliases))


class Taxonomy:
    def __init__(self, loaded: _Loaded) -> None:
        self._loaded = loaded

    def __len__(self) -> int:
        return len(self._loaded.taxa)

    @property
    def version(self) -> str:
        return self._loaded.taxa[0].version if self._loaded.taxa else ""

    def all_taxa(self) -> Iterable[Taxon]:
        return iter(self._loaded.taxa)

    def resolve(
        self,
        *,
        scientific_name: str | None = None,
        name_zh: str | None = None,
        name_en: str | None = None,
    ) -> Taxon | None:
        key = _scientific_key(scientific_name or "")
        taxon = self._loaded.by_scientific.get(key)
        if taxon is not None:
            return taxon

        chinese_key = _fold(name_zh or "")
        if chinese_key:
            taxon = self._loaded.by_chinese.get(chinese_key)
            if taxon is not None:
                return taxon
            alias_target = self._loaded.aliases.get(chinese_key)
            if alias_target:
                taxon = self._loaded.by_scientific.get(alias_target)
                if taxon is not None:
                    return taxon

        english_key = _fold(name_en or "")
        if english_key:
            taxon = self._loaded.by_english.get(english_key)
            if taxon is not None:
                return taxon
        return None
