from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

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


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description="移除文件已丢失的 copy，并把空 group 移入 quarantine"
    )
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    report = cleanup_missing_copies(
        ArchiveLibrary(args.archive), dry_run=args.dry_run
    )
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    return 0 if not report.errors else 2


if __name__ == "__main__":
    raise SystemExit(main())
