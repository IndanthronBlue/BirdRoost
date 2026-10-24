from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import piexif
from PIL import Image, PngImagePlugin

from .errors import ArchiveError


def write_species_metadata(path: Path, species_cn: str) -> bool:
    """原子写入鸟种中文名；已写入相同值时不触碰文件。"""
    if not species_cn.strip():
        raise ArchiveError("鸟种中文名为空，无法写入元数据")
    suffix = path.suffix.lower()
    temporary_name: str | None = None
    try:
        if _metadata_matches(path, suffix, species_cn):
            return False
        with tempfile.NamedTemporaryFile(
            prefix=".birdclass-meta-", suffix=path.suffix, dir=path.parent, delete=False
        ) as handle:
            temporary_name = handle.name
        temporary = Path(temporary_name)
        if suffix in {".jpg", ".jpeg"}:
            shutil.copy2(path, temporary)
            exif = piexif.load(str(path))
            exif["0th"][piexif.ImageIFD.ImageDescription] = species_cn.encode("utf-8")
            exif["0th"][piexif.ImageIFD.XPKeywords] = tuple(species_cn.encode("utf-16le") + b"\x00\x00")
            piexif.insert(piexif.dump(exif), str(temporary))
        elif suffix == ".png":
            with Image.open(path) as image:
                info = PngImagePlugin.PngInfo()
                for key, value in image.text.items():
                    info.add_text(key, value)
                info.add_text("Description", species_cn)
                info.add_text("Keywords", species_cn)
                options = {"pnginfo": info}
                if image.info.get("exif"):
                    options["exif"] = image.info["exif"]
                if image.info.get("icc_profile"):
                    options["icc_profile"] = image.info["icc_profile"]
                image.save(temporary, format="PNG", **options)
        else:
            raise ArchiveError("仅支持为 JPEG 和 PNG 写入鸟种元数据")
        os.replace(temporary, path)
        return True
    except ArchiveError:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
        raise
    except (OSError, ValueError, piexif.InvalidImageDataError) as exc:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)
        raise ArchiveError(f"写入鸟种元数据失败：{exc}") from exc


def _metadata_matches(path: Path, suffix: str, species_cn: str) -> bool:
    if suffix in {".jpg", ".jpeg"}:
        exif = piexif.load(str(path))
        description = exif["0th"].get(piexif.ImageIFD.ImageDescription, b"").decode("utf-8")
        keywords = bytes(exif["0th"].get(piexif.ImageIFD.XPKeywords, ())).decode("utf-16le").rstrip("\x00")
        return description == species_cn and keywords == species_cn
    if suffix == ".png":
        with Image.open(path) as image:
            return image.text.get("Description") == species_cn and image.text.get("Keywords") == species_cn
    return False
