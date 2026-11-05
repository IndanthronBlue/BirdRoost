from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from PIL import Image, ImageOps, UnidentifiedImageError

from .archive_index import ArchiveIndex, ArchiveEntry, SPECIAL_DIRS
from .archiver import sha256_file
from .cloud_state import CloudState, prepare_export_state
from .taxonomy import TAXONOMY_VERSION

SCHEMA_VERSION = 2
COPY_NAMESPACE = uuid.UUID("8f3b7f9e-3a6e-4f2e-9c1b-4f2c7d6e1a02")


@dataclass
class ExportReport:
    export_root: Path
    manifest_path: Path
    photos: int = 0
    groups: int = 0
    copies: int = 0
    thumbnails: int = 0
    thumbnails_skipped: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "export_root": str(self.export_root),
            "manifest": str(self.manifest_path),
            "photos": self.photos,
            "groups": self.groups,
            "copies": self.copies,
            "thumbnails": self.thumbnails,
            "thumbnails_skipped": self.thumbnails_skipped,
            "skipped": self.skipped,
            "errors": list(self.errors),
        }


def copy_id(group_id: str, species: str, target_indices: Iterable[int]) -> str:
    key = f"{group_id}|{species}|{','.join(str(value) for value in sorted(target_indices))}"
    return str(uuid.uuid5(COPY_NAMESPACE, key))


def _special_for(relative: str) -> str:
    first = Path(relative).parts[0] if Path(relative).parts else ""
    return first if first in SPECIAL_DIRS else ""


def _image_info(path: Path) -> tuple[int, int, str]:
    with Image.open(path) as image:
        width, height = image.size
        mime = Image.MIME.get(image.format or "", "application/octet-stream")
    return width, height, mime


def _thumbnail(source: Path, destination: Path, size: int) -> tuple[tuple[int, int], bool] | None:
    if destination.is_file():
        try:
            with Image.open(destination) as existing:
                if existing.format == "WEBP":
                    return existing.size, False
        except (OSError, UnidentifiedImageError, ValueError):
            pass
    try:
        with Image.open(source) as opened:
            image = ImageOps.exif_transpose(opened)
            image = image.convert("RGB")
            image.thumbnail((size, size), Image.Resampling.LANCZOS)
            destination.parent.mkdir(parents=True, exist_ok=True)
            image.save(destination, format="WEBP", quality=82, method=6)
            return image.size, True
    except (OSError, UnidentifiedImageError, ValueError, Image.DecompressionBombError):
        return None


def export_archive(
    archive_root: Path,
    export_root: Path,
    *,
    thumbnail_sizes: tuple[int, ...] = (256, 512),
    create_thumbnails: bool = True,
) -> ExportReport:
    """Export a local archive into a cloud-uploadable manifest + thumbnails.

    This is the M0, no-network step: it does not upload anything and does not
    modify the source archive.
    """
    archive_root = archive_root.expanduser().resolve()
    export_root = export_root.expanduser().resolve()
    export_root.mkdir(parents=True, exist_ok=True)
    (export_root / "originals").mkdir(exist_ok=True)
    (export_root / "thumbs").mkdir(exist_ok=True)
    manifest_path = export_root / "manifest.json"
    cloud_state = prepare_export_state(archive_root)

    index = ArchiveIndex(archive_root)
    index.refresh()
    photos: dict[str, dict] = {}
    groups: list[dict] = []
    copies: list[dict] = []
    errors: list[str] = []
    skipped = 0
    thumbnail_count = 0
    thumbnail_skipped = 0

    for group in sorted(index.groups.values(), key=lambda value: str(value.get("group_id", ""))):
        group_id = str(group.get("group_id", ""))
        observation = group.get("observation") or {}
        group_record = {
            "group_id": group_id,
            "batch_id": str(group.get("batch_id", "")),
            "status": str(group.get("status", "")),
            "source_relative_path": str(group.get("source_relative_path", "")),
            "observation": {
                "country": str(observation.get("country", "")),
                "region": str(observation.get("region", "")),
                "location": str(observation.get("location", "")),
                "time": str(observation.get("time", "")),
                "legacy_location": str(observation.get("legacy_location", "")),
                "legacy_time": str(observation.get("legacy_time", "")),
            },
            "targets": group.get("targets", []),
            "copy_ids": [],
        }
        for copy_index, copy in enumerate(group.get("copies", [])):
            relative = str(copy.get("relative_path", "") or "").replace("\\", "/")
            if not relative:
                skipped += 1
                continue
            source = (archive_root / relative).resolve()
            try:
                source.relative_to(archive_root)
            except ValueError:
                errors.append(f"路径越界：{relative}")
                continue
            if not source.is_file():
                errors.append(f"文件不存在：{relative}")
                continue
            try:
                digest = sha256_file(source)
                width, height, mime = _image_info(source)
            except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
                errors.append(f"无法读取：{relative}：{exc}")
                continue

            photo = photos.get(digest)
            if photo is None:
                suffix = source.suffix.lower() or ".jpg"
                photo = {
                    "photo_id": digest,
                    "sha256": digest,
                    "width": width,
                    "height": height,
                    "mime_type": mime,
                    "bytes": source.stat().st_size,
                    "original_object_key": f"originals/{digest}{suffix}",
                    "variants": [],
                }
                photos[digest] = photo
                if create_thumbnails:
                    for size in thumbnail_sizes:
                        thumb = export_root / "thumbs" / f"{digest}_{size}.webp"
                        result = _thumbnail(source, thumb, size)
                        if result is None:
                            errors.append(f"缩略图失败：{relative}@{size}")
                            continue
                        dimensions, created = result
                        if created:
                            thumbnail_count += 1
                        else:
                            thumbnail_skipped += 1
                        photo["variants"].append({
                            "kind": f"thumb_{size}",
                            "object_key": f"thumbs/{digest}_{size}.webp",
                            "width": dimensions[0],
                            "height": dimensions[1],
                            "bytes": thumb.stat().st_size,
                            "content_type": "image/webp",
                        })

            copy_identifier = copy_id(
                group_id,
                str(copy.get("species_cn", "")),
                (int(value) for value in copy.get("target_indices", [])),
            )
            copy_record = {
                "copy_id": copy_identifier,
                "group_id": group_id,
                "photo_id": digest,
                "species_cn": str(copy.get("species_cn", "")),
                "species_latin": str(copy.get("species_latin", "")),
                "target_indices": [int(value) for value in copy.get("target_indices", [])],
                "local_relative_path": relative,
                "pending": bool(copy.get("pending")),
                "special": _special_for(relative),
                "copy_index": copy_index,
            }
            copies.append(copy_record)
            group_record["copy_ids"].append(copy_identifier)

        if group_record["copy_ids"]:
            groups.append(group_record)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "library_id": cloud_state.library_id,
        "device_id": cloud_state.device_id,
        "revision": cloud_state.revision,
        "base_revision": cloud_state.base_revision,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "taxonomy_version": TAXONOMY_VERSION,
        "source_root": str(archive_root),
        "thumbnail_sizes": list(thumbnail_sizes),
        "counts": {
            "photos": len(photos),
            "groups": len(groups),
            "copies": len(copies),
            "thumbnails": thumbnail_count,
            "thumbnails_skipped": thumbnail_skipped,
            "errors": len(errors),
        },
        "photos": sorted(photos.values(), key=lambda value: value["photo_id"]),
        "groups": groups,
        "copies": copies,
        "tombstones": cloud_state.tombstones,
        "errors": errors,
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return ExportReport(
        export_root=export_root,
        manifest_path=manifest_path,
        photos=len(photos),
        groups=len(groups),
        copies=len(copies),
        thumbnails=thumbnail_count,
        thumbnails_skipped=thumbnail_skipped,
        skipped=skipped,
        errors=errors,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export a BirdRoost archive for cloud upload (M0, no network).")
    parser.add_argument("--archive", required=True, type=Path, help="归档目录，例如 /Users/.../鸟")
    parser.add_argument("--output", required=True, type=Path, help="导出目录，manifest 和缩略图会写在这里")
    parser.add_argument("--no-thumbnails", action="store_true", help="只生成 manifest，不生成缩略图")
    args = parser.parse_args(argv)
    report = export_archive(
        args.archive, args.output, create_thumbnails=not args.no_thumbnails
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0 if not report.errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
