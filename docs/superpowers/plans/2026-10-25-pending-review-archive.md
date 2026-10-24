# Pending Review Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在任一人工目标选择“稍后处理”时，将原图以幂等方式复制到输出目录的 `待复核/`，同时保持已确认鸟种的既有归档行为。

**Architecture:** `FileArchiver.archive_pending` 专门负责待复核文件命名、冲突检测和原子复制；`ClassificationService` 在单张图片的复核收尾时只调用一次。界面仅消费新增进度事件，CSV schema 不变。

**Tech Stack:** Python 3.11+、PySide6、Pillow、pytest、现有 `CsvHistory` 与 `FileArchiver`。

## Global Constraints

- 多个 `DEFER` 对同一图片只生成一个待复核副本；`STOP` 不生成副本。
- 保留原文件名和扩展名；同名同内容复用，同名不同内容从 `_002` 递增。
- 已确认鸟种仍按原规则复制；待复核副本不写未确认鸟种元数据。
- 不自动删除后续已完成图片的待复核副本。
- 不调用真实懂鸟 API，不提交 API Key、图库或个人 CSV。

---

### Task 1: 待复核归档器

**Files:**
- Modify: `src/birdclass/archiver.py`
- Test: `tests/unit/test_archiver.py`

**Interfaces:**
- Produces: `FileArchiver.archive_pending(item: ImageItem) -> Path`。
- Consumes: 既有 `_copy_atomic`、`_same_pixels` 和 `ImageItem.absolute_path`。

- [ ] **Step 1: 写失败测试**

新增测试，断言首次路径为 `待复核/bird.jpg`，重复调用返回同一路径且只有一份文件；再在另一源目录创建同名不同像素图片，断言结果为 `bird_002.jpg`，再次调用仍复用 `_002`。

```python
def test_archive_pending_is_idempotent_and_never_overwrites_name_collision(tmp_path):
    first_source = tmp_path / "first-source"
    second_source = tmp_path / "second-source"
    first_source.mkdir()
    second_source.mkdir()
    first_image = first_source / "bird.jpg"
    second_image = second_source / "bird.jpg"
    make_image(first_image, "green")
    make_image(second_image, "red")
    archiver = FileArchiver(tmp_path / "output")

    first = archiver.archive_pending(item(first_image, first_source))
    repeated = archiver.archive_pending(item(first_image, first_source))
    second = archiver.archive_pending(item(second_image, second_source))
    second_repeated = archiver.archive_pending(item(second_image, second_source))

    assert first == repeated == tmp_path / "output" / "待复核" / "bird.jpg"
    assert second == second_repeated == tmp_path / "output" / "待复核" / "bird_002.jpg"
    assert len(list(first.parent.glob("*.jpg"))) == 2
```

- [ ] **Step 2: 验证测试失败**

Run: `.venv/bin/python -m pytest tests/unit/test_archiver.py::test_archive_pending_is_idempotent_and_never_overwrites_name_collision -q`
Expected: FAIL，原因是 `FileArchiver` 没有 `archive_pending`。

- [ ] **Step 3: 实现最小归档方法**

```python
def archive_pending(self, item: ImageItem) -> Path:
    source = item.absolute_path
    directory = self.output_root / "待复核"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        number = 1
        while True:
            suffix = "" if number == 1 else f"_{number:03d}"
            destination = directory / f"{source.stem}{suffix}{source.suffix}"
            if destination.exists():
                if _same_pixels(source, destination):
                    return destination
                number += 1
                continue
            self._copy_atomic(item, destination)
            return destination
    except ArchiveError:
        raise
    except OSError as exc:
        raise ArchiveError(f"复制待复核图片失败：{exc}") from exc
```

- [ ] **Step 4: 验证归档器测试**

Run: `.venv/bin/python -m pytest tests/unit/test_archiver.py -q`
Expected: 全部通过。

### Task 2: 分类服务与界面进度

**Files:**
- Modify: `src/birdclass/service.py`
- Modify: `src/birdclass/ui/main_window.py`
- Test: `tests/integration/test_service.py`
- Test: `tests/unit/test_main_window.py`

**Interfaces:**
- Consumes: `FileArchiver.archive_pending(item) -> Path`。
- Produces: 进度事件 `deferred`，数据包含 `destination: Path` 和 `deferred_targets: list[int]`。

- [ ] **Step 1: 写服务失败测试**

扩展多目标推迟测试，断言 `待复核/birds.jpg` 存在、斑鸠和家燕仍各有一份、麻雀目录不存在；第二次恢复并确认后待复核仍只有一份。新增“全部目标均推迟”测试，两个目标均返回 `DEFER`，断言待复核目录只有一个文件且无鸟种目录。

```python
pending = tmp_path / "output" / "待复核" / "birds.jpg"
assert pending.is_file()
assert len(list(pending.parent.glob("*.jpg"))) == 1
```

- [ ] **Step 2: 验证服务测试失败**

Run: `.venv/bin/python -m pytest tests/integration/test_service.py -q`
Expected: 新增待复核路径断言失败，既有其他断言不应被破坏。

- [ ] **Step 3: 接入复核收尾**

在 `_finish_multi_review` 的 `deferred_targets` 分支中，先按需调用 `_archive_partial_and_keep_pending`，随后只调用一次：

```python
pending_destination = archiver.archive_pending(item)
self._progress(
    progress_callback, "deferred", item,
    destination=pending_destination,
    deferred_targets=deferred_targets,
)
```

在 schema 1 的 `ReviewAction.DEFER` 分支同样调用 `archive_pending`，发出 `deferred` 进度，再更新计数并继续。不要修改 `STOP` 分支。

- [ ] **Step 4: 增加界面日志**

在 `_on_progress` 的消息表加入：

```python
"deferred": f"待复核：{path} → {destination_text}",
```

新增界面测试，触发 `deferred` 并断言日志包含 `待复核` 和目标路径。

- [ ] **Step 5: 运行服务与界面测试**

Run: `.venv/bin/python -m pytest tests/integration/test_service.py tests/unit/test_main_window.py -q`
Expected: 全部通过。

### Task 3: 文档、完整验证与发布

**Files:**
- Modify: `README.md`
- Modify: `docs/需求文档.md`
- Modify: `docs/开发手册.md`
- Create: `docs/superpowers/specs/2026-10-25-pending-review-archive-design.md`
- Create: `docs/superpowers/plans/2026-10-25-pending-review-archive.md`

**Interfaces:**
- Consumes: Task 1 和 Task 2 的最终行为。
- Produces: 可公开的用户说明和可复现开发记录。

- [ ] **Step 1: 更新公开文档**

在人工复核功能说明中写明：任一目标点击“稍后处理”会复制原图到 `待复核/`；同图多个目标只复制一份；已确认物种仍归档；待复核副本在后续完成后保留。输出结构加入 `待复核/` 示例。

- [ ] **Step 2: 运行完整验证**

Run: `.venv/bin/python -m pytest -q`
Expected: 0 失败，所有测试通过。

Run: `git diff --check`
Expected: 无输出，退出码 0。

- [ ] **Step 3: 安全审查并提交**

Run: `git status --short`，确认只有本功能源码、测试和文档。
Run: `git add src tests README.md docs && git commit -m "Add pending review photo archive"`
Expected: 创建一个本地提交；忽略目录中的设计文档若未被加入，使用明确路径 `git add -f docs/superpowers/specs/2026-10-25-pending-review-archive-design.md docs/superpowers/plans/2026-10-25-pending-review-archive.md` 后纳入同一提交。

- [ ] **Step 4: 同步 GitHub**

通过已登录的 GitHub 网页按原目录上传变更文件，或使用已配置的 Git 凭据推送。核对远程文件内容、最新提交和 About 简介不受影响，本地 `main` 与 `origin/main` 对齐。
