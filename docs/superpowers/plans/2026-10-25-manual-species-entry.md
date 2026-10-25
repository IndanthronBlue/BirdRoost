# 人工填写鸟名归档 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在人工复核弹窗中允许直接输入鸟种中文名，并通过现有归档与断点续跑流程复制到对应目录。

**Architecture:** 弹窗只返回新的 `CUSTOM` 决定和人工中文名，Service 将其转换为带稳定人工 ID 的候选。后续复用现有多目标聚合、归档、元数据和 CSV 状态机，不在 UI 中直接操作文件。

**Tech Stack:** Python 3.12、PySide6、pytest、pytest-qt、现有 BirdRoost Service 与 FileArchiver。

## Global Constraints

- 人工输入仅包含鸟种中文名，提交时去除首尾空白，空白值禁止提交。
- 人工物种 ID 为 `manual:<中文名>`，`confidence_raw="manual"`，内部数值置信度为 0，不声称 API 返回了 0%。
- 动物类别继承当前检测目标，英文名和拉丁名为空，选择方式为 `manual`。
- 目录清洗、文件名、编号、元数据、复制冲突与 CSV 恢复继续走现有实现。
- 同图相同人工鸟名只复制一次，不同鸟名分别归档；原候选确认、推迟和停止行为不变。
- 自动化测试不得调用真实懂鸟 API。

---

### Task 1: 人工决定模型与 Service 归档

**Files:**
- Modify: `src/birdclass/models.py`
- Modify: `src/birdclass/service.py`
- Test: `tests/integration/test_service.py`

**Interfaces:**
- Produces: `ReviewAction.CUSTOM`、`ReviewResult.custom_name_cn: str`。
- Consumes: 现有 `_selected_candidate(result, candidates)` 与多目标归档流程。
- Preserves: `CONFIRM`、`DEFER`、`STOP` 的既有语义。

- [ ] **Step 1: 写人工鸟名归档失败测试**

在集成测试中增加：低置信度结果返回 `ReviewResult(ReviewAction.CUSTOM, custom_name_cn="白鹡鸰")` 后，应生成 `output/白鹡鸰/全球_白鹡鸰_001.jpg`，CSV 最后记录 `species_cn="白鹡鸰"`、`species_id="manual:白鹡鸰"`、`selection_mode="manual"`，原图 EXIF 描述为“白鹡鸰”。

```python
summary = run_service(
    make_service(api), make_config(tmp_path),
    lambda _context: ReviewResult(ReviewAction.CUSTOM, custom_name_cn="白鹡鸰"),
)
assert summary.completed == 1
assert (tmp_path / "output" / "白鹡鸰" / "全球_白鹡鸰_001.jpg").is_file()
```

- [ ] **Step 2: 写多目标去重与恢复失败测试**

两个不确定目标都输入“白鹡鸰”时，只生成一个复制件。另设两个目标：第一个使用人工鸟名，第二个 `DEFER`；首轮同时存在人工鸟种副本和一份待复核副本，第二轮只恢复第二个目标且不增加上传次数，最终每个人工或 API 鸟种只有一个复制件。

- [ ] **Step 3: 运行测试确认失败**

Run: `PYTHONPATH="$PWD/src" "$PWD/.venv/bin/python" -m pytest tests/integration/test_service.py -k "custom_species"`

Expected: 因 `ReviewAction.CUSTOM` 或 `custom_name_cn` 尚不存在而失败。

- [ ] **Step 4: 扩展决定模型**

```python
class ReviewAction(Enum):
    CONFIRM = "confirm"
    CUSTOM = "custom"
    DEFER = "defer"
    STOP = "stop"

@dataclass(frozen=True)
class ReviewResult:
    action: ReviewAction
    candidate: RecognitionCandidate | None = None
    custom_name_cn: str = ""
```

- [ ] **Step 5: 在 `_selected_candidate` 构造人工候选**

在现有 `CONFIRM` 校验之前加入：

```python
if result.action == ReviewAction.CUSTOM:
    name = result.custom_name_cn.strip()
    if not name or not candidates:
        raise RecognitionFailedError("人工鸟名不能为空")
    return RecognitionCandidate(
        species_id=f"manual:{name}",
        animal_class=candidates[0].animal_class,
        name_cn=name,
        name_en="",
        name_latin="",
        confidence_raw="manual",
        confidence_percent=Decimal("0"),
        source_order=-1,
    )
```

- [ ] **Step 6: 运行集成测试确认通过**

Run: `PYTHONPATH="$PWD/src" "$PWD/.venv/bin/python" -m pytest tests/integration/test_service.py`

Expected: 全部通过，新增人工鸟名、同名去重和部分恢复用例均通过。

- [ ] **Step 7: 提交 Task 1**

```bash
git add src/birdclass/models.py src/birdclass/service.py tests/integration/test_service.py
git commit -m "feat: archive manually entered species"
```

### Task 2: 复核弹窗人工输入

**Files:**
- Modify: `src/birdclass/ui/review_dialog.py`
- Test: `tests/unit/test_review_dialog.py`

**Interfaces:**
- Consumes: `ReviewAction.CUSTOM` 与 `ReviewResult.custom_name_cn`。
- Produces: `ReviewDialog.custom_name`、`ReviewDialog.custom_button`、`ReviewDialog.confirm_custom()`。

- [ ] **Step 1: 写弹窗失败测试**

创建低置信度复核弹窗，断言人工归档按钮初始禁用；输入 `"  白鹡鸰  "` 后启用；调用 `confirm_custom()` 后结果为 `CUSTOM`，`custom_name_cn == "白鹡鸰"`，候选字段为空。

- [ ] **Step 2: 运行弹窗测试确认失败**

Run: `PYTHONPATH="$PWD/src" "$PWD/.venv/bin/python" -m pytest tests/unit/test_review_dialog.py -k "custom"`

Expected: 因弹窗缺少 `custom_name` 或 `custom_button` 而失败。

- [ ] **Step 3: 增加文本框和按钮**

在候选面板列表下加入：

```python
candidate_layout.addWidget(QLabel("候选都不正确时，输入人工确认的鸟种中文名"))
self.custom_name = QLineEdit()
self.custom_name.setPlaceholderText("例如：白鹡鸰")
self.custom_button = QPushButton("按人工鸟名归档")
self.custom_button.setEnabled(False)
self.custom_name.textChanged.connect(
    lambda text: self.custom_button.setEnabled(bool(text.strip()))
)
self.custom_button.clicked.connect(self.confirm_custom)
candidate_layout.addWidget(self.custom_name)
candidate_layout.addWidget(self.custom_button)
```

同时从 `PySide6.QtWidgets` 导入 `QLineEdit`。

- [ ] **Step 4: 实现提交方法**

```python
def confirm_custom(self) -> None:
    name = self.custom_name.text().strip()
    if not name:
        return
    self.result = ReviewResult(ReviewAction.CUSTOM, custom_name_cn=name)
    self.accept()
```

- [ ] **Step 5: 运行弹窗与 UI 回归测试**

Run: `PYTHONPATH="$PWD/src" "$PWD/.venv/bin/python" -m pytest tests/unit/test_review_dialog.py tests/unit/test_main_window.py tests/unit/test_theme.py`

Expected: 全部通过，原检测框、高 DPI、深浅色和主窗口行为不回归。

- [ ] **Step 6: 提交 Task 2**

```bash
git add src/birdclass/ui/review_dialog.py tests/unit/test_review_dialog.py
git commit -m "feat: add manual species entry to review dialog"
```

### Task 3: 文档与完整验收

**Files:**
- Modify: `docs/需求文档.md`
- Modify: `docs/开发手册.md`

**Interfaces:**
- Documents: `CUSTOM`、人工输入按钮、`manual:` 物种 ID、归档和恢复行为。

- [ ] **Step 1: 更新需求与开发手册**

在 FR-API-006 增加人工输入交互、空白校验、同图去重、归档、元数据和恢复规则；在开发手册的复核弹窗及数据模型章节记录 `CUSTOM` 和 `custom_name_cn`，将测试数量更新为实际完整测试结果。

- [ ] **Step 2: 运行完整测试和格式检查**

Run: `PYTHONPATH="$PWD/src" "$PWD/.venv/bin/python" -m pytest && git diff --check`

Expected: 全部测试通过，`git diff --check` 无输出。

- [ ] **Step 3: 提交文档**

```bash
git add docs/需求文档.md docs/开发手册.md
git commit -m "docs: document manual species entry"
```

- [ ] **Step 4: 核对需求覆盖**

逐项验证：空白禁用、去空白、人工目录与文件名、原图及复制件元数据、相同鸟名去重、不同鸟名分别复制、部分推迟恢复不重新上传，以及原确认、推迟、停止和主题测试均通过。
