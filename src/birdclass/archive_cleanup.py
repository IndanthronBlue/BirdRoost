from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .archive_index import is_review_annotation
from .library import ArchiveLibrary, now_iso


@dataclass
class CleanupReport:
    groups_scanned: int = 0
    missing_copies: int = 0
    changed_groups: int = 0
    quarantined_groups: int = 0
    quarantine_dir: Path | None = None
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "groups_scanned": self.groups_scanned,
            "missing_copies": self.missing_copies,
            "changed_groups": self.changed_groups,
            "quarantined_groups": self.quarantined_groups,
            "quarantine_dir": str(self.quarantine_dir) if self.quarantine_dir else "",
            "errors": list(self.errors),
        }


def cleanup_missing_copies(
    library: ArchiveLibrary,
    *,
    dry_run: bool = False,
) -> CleanupReport:
    """Remove copies whose files are missing and quarantine empty groups.

    Group JSON remains the source of truth. Removed groups are moved under
    `.birdroost/quarantine/groups/<timestamp>/` rather than deleted.
    """
    report = CleanupReport()
    output = library.output_root.resolve()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    quarantine = library.root / "quarantine" / "groups" / stamp
    report.quarantine_dir = quarantine
    groups = library.load_groups()
    report.groups_scanned = len(groups)
    for group in groups:
        group_id = str(group.get("group_id", ""))
        copies = list(group.get("copies", []))
        if not copies:
            report.changed_groups += 1
            report.quarantined_groups += 1
            if not dry_run:
                group_path = library.groups_dir / f"{group_id}.json"
                try:
                    quarantine.mkdir(parents=True, exist_ok=True)
                    if group_path.exists():
                        shutil.move(str(group_path), str(quarantine / group_path.name))
                    library.append_correction({
                        "corrected_at": now_iso(),
                        "group_id": group_id,
                        "action": "cleanup_empty_group",
                        "removed_relative_paths": [],
                        "remaining_copies": 0,
                        "quarantined": True,
                    })
                except OSError as exc:
                    report.errors.append(f"{group_id}: {exc}")
            continue
        kept = []
        removed = []
        for copy in copies:
            relative = str(copy.get("relative_path", "") or "")
            path = (output / relative).resolve()
            try:
                path.relative_to(output)
            except ValueError:
                removed.append(copy)
                continue
            if path.is_file():
                kept.append(copy)
            else:
                removed.append(copy)
        if not removed:
            continue
        report.missing_copies += len(removed)
        report.changed_groups += 1
        group["copies"] = kept
        if dry_run:
            if not kept:
                report.quarantined_groups += 1
            continue
        try:
            if kept:
                library.write_group(group)
            else:
                group_path = library.groups_dir / f"{group_id}.json"
                quarantine.mkdir(parents=True, exist_ok=True)
                if group_path.exists():
                    shutil.move(str(group_path), str(quarantine / group_path.name))
                report.quarantined_groups += 1
            library.append_correction({
                "corrected_at": now_iso(),
                "group_id": group_id,
                "action": "cleanup_missing_copies",
                "removed_relative_paths": [str(c.get("relative_path", "")) for c in removed],
                "remaining_copies": len(kept),
                "quarantined": not kept,
            })
        except OSError as exc:
            report.errors.append(f"{group_id}: {exc}")
    return report



@dataclass
class AnnotationMigrationReport:
    groups_scanned: int = 0
    annotation_copies: int = 0
    annotation_files: int = 0
    flattened_copies: int = 0
    changed_groups: int = 0
    quarantined_groups: int = 0
    backup_dir: Path | None = None
    planned_moves: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "groups_scanned": self.groups_scanned,
            "annotation_copies": self.annotation_copies,
            "annotation_files": self.annotation_files,
            "flattened_copies": self.flattened_copies,
            "changed_groups": self.changed_groups,
            "quarantined_groups": self.quarantined_groups,
            "backup_dir": str(self.backup_dir) if self.backup_dir else "",
            "planned_moves": list(self.planned_moves),
            "errors": list(self.errors),
        }


_SPECIAL_FLAT_DIRS = ("风景", "非鸟动物", "无鸟")


def _safe_archive_path(output: Path, relative_path: str) -> Path | None:
    """Resolve a group path and refuse anything outside the archive root."""
    candidate = (output / relative_path).resolve()
    try:
        candidate.relative_to(output)
    except ValueError:
        return None
    return candidate


def _unique_destination(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    for index in range(2, 10_000):
        candidate = path.with_name(f"{stem}_{index:03d}{suffix}")
        if not candidate.exists():
            return candidate
    raise OSError(f"无法为 {path} 找到不冲突的文件名")


def _flatten_special_relative(relative_path: str) -> str | None:
    """Drop the review-only 待复核/ level under a special-photo folder."""
    parts = PurePosixPath(relative_path).parts
    if len(parts) < 4 or parts[0] not in _SPECIAL_FLAT_DIRS:
        return None
    for index in range(1, len(parts) - 1):
        if parts[index] == "待复核":
            flattened = parts[:index] + parts[index + 1:]
            return PurePosixPath(*flattened).as_posix()
    return None


def cleanup_review_annotations(
    library: ArchiveLibrary,
    *,
    dry_run: bool = True,
    backup_root: Path | None = None,
) -> AnnotationMigrationReport:
    """Remove generated box-preview files and flatten old special-photo paths.

    Safety rules:
    - Default is a dry run.
    - Before writing, every changed group JSON and every annotation file is copied
      under `.birdroost/backups/annotation-migration-<stamp>/`.
    - Images are only moved within the archive; nothing else is deleted.
    - Empty groups are quarantined, never discarded.
    """
    report = AnnotationMigrationReport()
    output = library.output_root.resolve()
    groups = library.load_groups()
    report.groups_scanned = len(groups)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    if backup_root is None:
        backup_root = library.root / "backups" / f"annotation-migration-{stamp}"
    report.backup_dir = backup_root

    plans: list[dict] = []
    annotation_relatives: set[str] = set()
    for group in groups:
        group_id = str(group.get("group_id", ""))
        copies = list(group.get("copies", []))
        annotations = []
        kept = []
        flatten = []
        for copy in copies:
            relative = str(copy.get("relative_path", "") or "").replace("\\", "/")
            if is_review_annotation(relative):
                annotations.append(copy)
                annotation_relatives.add(relative)
                continue
            kept.append(copy)
            flattened = _flatten_special_relative(relative)
            if flattened and flattened != relative:
                flatten.append((copy, relative, flattened))
        if not annotations and not flatten:
            continue
        report.annotation_copies += len(annotations)
        report.flattened_copies += len(flatten)
        report.changed_groups += 1
        plans.append({
            "group": group,
            "group_id": group_id,
            "annotations": annotations,
            "kept": kept,
            "flatten": flatten,
        })

    # Also catch orphaned helper files that are no longer referenced by a group.
    for path in output.rglob("*"):
        if not path.is_file() or is_review_annotation(path.name) is False:
            continue
        try:
            relative = path.relative_to(output)
        except ValueError:
            continue
        if any(part == ".birdroost" for part in relative.parts):
            continue
        annotation_relatives.add(relative.as_posix())

    report.annotation_files = sum(
        1 for relative in annotation_relatives if _safe_archive_path(output, relative) is not None
        and _safe_archive_path(output, relative).is_file()
    )
    if dry_run:
        report.quarantined_groups = sum(1 for plan in plans if not plan["kept"])
        return report

    if not plans and not annotation_relatives:
        return report

    backup_root.mkdir(parents=True, exist_ok=True)
    plan_path = backup_root / "plan.json"
    plan_path.write_text(
        json.dumps({
            "archive": str(output),
            "created_at": now_iso(),
            "groups": [
                {
                    "group_id": plan["group_id"],
                    "annotations": [str(c.get("relative_path", "")) for c in plan["annotations"]],
                    "flatten": [
                        {"from": old, "to": new} for _, old, new in plan["flatten"]
                    ],
                }
                for plan in plans
            ],
            "annotation_files": sorted(annotation_relatives),
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Preflight backups: abort before deleting/moving if any backup cannot be made.
    preflight_errors: list[str] = []
    for plan in plans:
        group_path = library.groups_dir / f"{plan['group_id']}.json"
        if group_path.is_file():
            destination = backup_root / "groups" / group_path.name
            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(group_path, destination)
            except OSError as exc:
                preflight_errors.append(f"{plan['group_id']}: 无法备份 group: {exc}")
    for relative in sorted(annotation_relatives):
        source = _safe_archive_path(output, relative)
        if source is None or not source.is_file():
            continue
        destination = backup_root / "removed" / relative
        try:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
        except OSError as exc:
            preflight_errors.append(f"{relative}: 无法备份辅助图: {exc}")
    if preflight_errors:
        report.errors.extend(preflight_errors)
        return report

    quarantine = library.root / "quarantine" / "groups" / stamp
    actual_moves: list[dict] = []
    for plan in plans:
        group = plan["group"]
        group_id = plan["group_id"]
        kept = list(plan["kept"])
        group_moves: list[dict] = []
        removed_annotations: list[str] = []
        for copy in plan["annotations"]:
            relative = str(copy.get("relative_path", "")).replace("\\", "/")
            source = _safe_archive_path(output, relative)
            if source is None:
                report.errors.append(f"{group_id}: 辅助图路径越界 {relative}")
                kept.append(copy)
                continue
            try:
                if source.is_file():
                    source.unlink()
                removed_annotations.append(relative)
            except OSError as exc:
                report.errors.append(f"{group_id}: 无法删除辅助图 {relative}: {exc}")
                kept.append(copy)

        for copy, old_relative, flattened_relative in plan["flatten"]:
            source = _safe_archive_path(output, old_relative)
            if source is None or not source.is_file():
                continue
            destination = _unique_destination(output / flattened_relative)
            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(source), str(destination))
            except OSError as exc:
                report.errors.append(f"{group_id}: 无法迁移 {old_relative}: {exc}")
                continue
            new_relative = destination.relative_to(output).as_posix()
            copy["relative_path"] = new_relative
            move = {"from": old_relative, "to": new_relative}
            group_moves.append(move)
            actual_moves.append(move)
            try:
                source.parent.rmdir()
            except OSError:
                pass

        group["copies"] = kept
        group_path = library.groups_dir / f"{group_id}.json"
        try:
            if kept:
                library.write_group(group)
            else:
                quarantine.mkdir(parents=True, exist_ok=True)
                if group_path.is_file():
                    shutil.move(str(group_path), str(quarantine / group_path.name))
                report.quarantined_groups += 1
            library.append_correction({
                "corrected_at": now_iso(),
                "group_id": group_id,
                "action": "cleanup_review_annotations",
                "removed_relative_paths": removed_annotations,
                "moved_relative_paths": group_moves,
                "remaining_copies": len(kept),
                "quarantined": not kept,
            })
        except OSError as exc:
            report.errors.append(f"{group_id}: 无法写入 group: {exc}")

    # Delete orphan annotation files that were not referenced by a group.
    for relative in sorted(annotation_relatives):
        if any(
            relative == str(copy.get("relative_path", ""))
            for plan in plans for copy in plan["annotations"]
        ):
            continue
        source = _safe_archive_path(output, relative)
        if source is None or not source.is_file():
            continue
        try:
            source.unlink()
        except OSError as exc:
            report.errors.append(f"{relative}: 无法删除孤立辅助图: {exc}")

    (backup_root / "applied.json").write_text(
        json.dumps({
            "moved": actual_moves,
            "removed_annotations": sorted(
                {
                    str(copy.get("relative_path", ""))
                    for plan in plans for copy in plan["annotations"]
                }
            ),
            "errors": report.errors,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return report


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="清理归档中的辅助图，或移除文件已丢失的 copy"
    )
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true", help="只打印计划，不修改文件")
    parser.add_argument(
        "--review-annotations",
        action="store_true",
        help="删除 _待确认框 辅助图，并把特殊照片从 待复核/ 下拍平",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="配合 --review-annotations 真正执行；不加时默认只做 dry-run",
    )
    parser.add_argument(
        "--backup-root",
        type=Path,
        help="辅助图迁移备份目录；默认放在 .birdroost/backups 下",
    )
    args = parser.parse_args(argv)
    library = ArchiveLibrary(args.archive)
    if args.review_annotations:
        report = cleanup_review_annotations(
            library,
            dry_run=not args.apply,
            backup_root=args.backup_root,
        )
    else:
        report = cleanup_missing_copies(library, dry_run=args.dry_run)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0 if not report.errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
