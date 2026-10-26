from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .errors import ArchiveError
from .metadata import write_species_metadata
from .models import ArchiveSelection, ImageItem, NormalizedBox, Recognition

INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def _sanitize_component(name: str, fallback: str) -> str:
    cleaned = INVALID_CHARS.sub("_", name.strip()).rstrip(" .")[:120].rstrip(" .")
    cleaned = cleaned or fallback
    if cleaned.split(".", 1)[0].upper() in RESERVED_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned


def sanitize_species_directory(name: str, species_id: str = "unknown") -> str:
    return _sanitize_component(name, f"未命名物种_{species_id or 'unknown'}")


def _filename_prefix(
    area: str, species: str, observation_location: str, observation_time: str
) -> str:
    if observation_location.strip() and observation_time.strip():
        location = _sanitize_component(observation_location, "未知地点")
        observed_at = _sanitize_component(observation_time, "未知时间")
        return f"{location}_{observed_at}_{species}_"
    return f"{area}_{species}_"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class FileArchiver:
    def __init__(self, output_root: Path) -> None:
        self.output_root = output_root

    def plan_many(
        self,
        selections: list[ArchiveSelection],
        area_name: str,
        source_suffix: str = ".jpg",
        observation_location: str = "",
        observation_time: str = "",
    ) -> list[ArchiveSelection]:
        area = _sanitize_component(area_name, "全球")
        planned = []
        try:
            for selection in selections:
                candidate = selection.candidate
                species = sanitize_species_directory(candidate.name_cn, candidate.species_id)
                directory = self.output_root / species
                directory.mkdir(parents=True, exist_ok=True)
                prefix = _filename_prefix(
                    area, species, observation_location, observation_time
                )
                destination = (
                    self._saved_destination(selection.destination_path)
                    if selection.destination_path
                    else self._next_destination(directory, prefix, source_suffix)
                )
                planned.append(replace(
                    selection,
                    destination_path=destination.relative_to(self.output_root).as_posix(),
                ))
            return planned
        except OSError as exc:
            raise ArchiveError(f"规划多物种归档路径失败：{exc}") from exc

    def archive_many(
        self, item: ImageItem, selections: list[ArchiveSelection], area_name: str
    ) -> list[Path]:
        del area_name
        if not selections or any(not selection.destination_path for selection in selections):
            raise ArchiveError("多物种归档缺少已规划目标路径")
        source = item.absolute_path
        try:
            write_species_metadata(source, "、".join(
                selection.candidate.name_cn for selection in selections
            ))
            destinations = []
            for selection in selections:
                destination = self._saved_destination(selection.destination_path)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    if not _same_pixels(source, destination):
                        raise ArchiveError(f"目标文件已存在且内容不同：{destination.name}")
                else:
                    self._copy_atomic(item, destination)
                write_species_metadata(destination, selection.candidate.name_cn)
                destinations.append(destination)
            return destinations
        except ArchiveError:
            raise
        except OSError as exc:
            raise ArchiveError(f"复制多物种图片失败：{exc}") from exc

    def archive_pending(
        self,
        item: ImageItem,
        observation_location: str = "",
        observation_time: str = "",
    ) -> Path:
        destination, _ = self.archive_pending_with_preview(
            item, (), observation_location, observation_time
        )
        return destination

    def archive_pending_with_preview(
        self,
        item: ImageItem,
        boxes: tuple[tuple[int, NormalizedBox], ...] = (),
        observation_location: str = "",
        observation_time: str = "",
    ) -> tuple[Path, Path | None]:
        directory = self.output_root / "待复核"
        try:
            directory.mkdir(parents=True, exist_ok=True)
            destination = self._pending_destination(
                item, directory, observation_location, observation_time
            )
            annotated = self._annotate_pending(destination, boxes) if boxes else None
            return destination, annotated
        except ArchiveError:
            raise
        except OSError as exc:
            raise ArchiveError(f"复制待复核图片失败：{exc}") from exc

    def _pending_destination(
        self,
        item: ImageItem,
        directory: Path,
        observation_location: str = "",
        observation_time: str = "",
    ) -> Path:
        source = item.absolute_path
        prefix = ""
        if observation_location.strip() and observation_time.strip():
            prefix = (
                f"{_sanitize_component(observation_location, '未知地点')}_"
                f"{_sanitize_component(observation_time, '未知时间')}_"
            )
        number = 1
        while True:
            suffix = "" if number == 1 else f"_{number:03d}"
            destination = directory / f"{prefix}{source.stem}{suffix}{source.suffix}"
            if destination.exists():
                if _same_pixels(source, destination):
                    return destination
                number += 1
                continue
            self._copy_atomic(item, destination)
            return destination

    def _annotate_pending(
        self,
        original: Path,
        boxes: tuple[tuple[int, NormalizedBox], ...],
    ) -> Path | None:
        suffix = original.suffix
        base = f"{original.stem}_待确认框"
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=".birdclass-box-", suffix=suffix, dir=original.parent, delete=False
            ) as handle:
                temporary_path = Path(handle.name)
            _draw_pending_boxes(original, temporary_path, boxes)
            number = 1
            while True:
                sequence = "" if number == 1 else f"_{number:03d}"
                candidate = original.parent / f"{base}{sequence}{suffix}"
                if candidate.exists():
                    if _same_pixels(temporary_path, candidate):
                        temporary_path.unlink(missing_ok=True)
                        return candidate
                    number += 1
                    continue
                os.replace(temporary_path, candidate)
                return candidate
        except (OSError, TypeError, ValueError, ArchiveError):
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            return None

    def archive(
        self,
        item: ImageItem,
        recognition: Recognition,
        area_name: str = "全球",
        destination_path: str | None = None,
        observation_location: str = "",
        observation_time: str = "",
    ) -> Path:
        candidate = recognition.candidate
        species = sanitize_species_directory(candidate.name_cn, candidate.species_id)
        area = _sanitize_component(area_name, "全球")
        directory = self.output_root / species
        try:
            write_species_metadata(item.absolute_path, candidate.name_cn)
            directory.mkdir(parents=True, exist_ok=True)
            source = item.absolute_path
            destination = self._saved_destination(destination_path) if destination_path else None
            if destination is not None:
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists() and _same_content(source, destination):
                    return destination
            if destination is None or destination.exists():
                prefix = _filename_prefix(
                    area, species, observation_location, observation_time
                )
                destination = self._next_destination(directory, prefix, source.suffix)
            self._copy_atomic(item, destination)
            return destination
        except ArchiveError:
            raise
        except OSError as exc:
            raise ArchiveError(f"复制图片失败：{exc}") from exc

    def _saved_destination(self, relative: str) -> Path:
        root = self.output_root.resolve()
        destination = (self.output_root / relative).resolve()
        if not destination.is_relative_to(root):
            raise ArchiveError("CSV 中保存的目标路径超出分类目录")
        return destination

    @staticmethod
    def _next_destination(directory: Path, prefix: str, suffix: str) -> Path:
        pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
        numbers = []
        for path in directory.iterdir():
            match = pattern.match(path.stem)
            if match:
                numbers.append(int(match.group(1)))
        number = max(numbers, default=0) + 1
        return directory / f"{prefix}{number:03d}{suffix}"

    @staticmethod
    def _copy_atomic(item: ImageItem, destination: Path) -> None:
        source = item.absolute_path
        before = source.stat()
        temporary_name = None
        try:
            with tempfile.NamedTemporaryFile(prefix=".birdclass-", dir=destination.parent, delete=False) as handle:
                temporary_name = handle.name
            shutil.copy2(source, temporary_name)
            after = source.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ArchiveError("复制期间源图片发生变化，请稍后重试")
            os.replace(temporary_name, destination)
        except ArchiveError:
            if temporary_name:
                Path(temporary_name).unlink(missing_ok=True)
            raise
        except OSError as exc:
            if temporary_name:
                Path(temporary_name).unlink(missing_ok=True)
            raise ArchiveError(f"复制图片失败：{exc}") from exc


def _draw_pending_boxes(
    source: Path,
    destination: Path,
    boxes: tuple[tuple[int, NormalizedBox], ...],
) -> None:
    with Image.open(source) as opened:
        transposed = ImageOps.exif_transpose(opened)
        image = transposed.copy()
        exif = transposed.info.get("exif")
        icc_profile = transposed.info.get("icc_profile") or opened.info.get("icc_profile")

    suffix = destination.suffix.lower()
    if suffix == ".png" and image.mode not in ("RGB", "RGBA"):
        image = image.convert("RGBA")

    width, height = image.size
    draw = ImageDraw.Draw(image)
    line_width = max(3, min(width, height) // 300)
    font_size = max(14, min(64, min(width, height) // 40))
    try:
        font = ImageFont.load_default(size=font_size)
    except TypeError:
        font = ImageFont.load_default()
    for target_index, box in boxes:
        left, top, right, bottom = box
        x0 = max(0, min(width - 1, round(left * width)))
        y0 = max(0, min(height - 1, round(top * height)))
        x1 = max(0, min(width - 1, round(right * width)))
        y1 = max(0, min(height - 1, round(bottom * height)))
        if x1 <= x0 or y1 <= y0:
            continue
        draw.rectangle((x0, y0, x1, y1), outline=(255, 176, 32), width=line_width)
        label = str(target_index + 1)
        text_box = draw.textbbox((0, 0), label, font=font)
        label_width = text_box[2] - text_box[0]
        label_height = text_box[3] - text_box[1]
        draw.rectangle(
            (x0, y0, x0 + label_width + 8, y0 + label_height + 6),
            fill=(255, 176, 32),
        )
        draw.text((x0 + 4, y0 + 3), label, fill=(0, 0, 0), font=font)

    if suffix == ".png":
        options: dict[str, object] = {}
        if icc_profile:
            options["icc_profile"] = icc_profile
        if exif:
            options["exif"] = exif
        image.save(destination, format="PNG", **options)
    else:
        options = {"quality": 95, "subsampling": 0}
        if icc_profile:
            options["icc_profile"] = icc_profile
        if exif:
            options["exif"] = exif
        image.convert("RGB").save(destination, format="JPEG", **options)


def _same_content(first: Path, second: Path) -> bool:
    if first.stat().st_size != second.stat().st_size:
        return False
    return sha256_file(first) == sha256_file(second)


def _same_pixels(first: Path, second: Path) -> bool:
    try:
        with Image.open(first) as left, Image.open(second) as right:
            return left.size == right.size and left.convert("RGB").tobytes() == right.convert("RGB").tobytes()
    except OSError as exc:
        raise ArchiveError(f"无法比较目标图片内容：{exc}") from exc
