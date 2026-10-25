# System Dark Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让羽栖主窗口和人工复核相关控件跟随系统浅色／深色外观，并在运行时自动切换。

**Architecture:** 新增独立主题模块，从当前 `QPalette` 生成应用级 Qt 样式；`SystemThemeController` 负责首次应用和响应 `colorSchemeChanged`。`MainWindow` 删除局部固定浅色样式，业务逻辑不变。

**Tech Stack:** Python 3.11 / 3.12、PySide6 6.7+、pytest、pytest-qt。

## Global Constraints

- 不修改识别、API、归档、元数据、CSV 或复核操作语义。
- 颜色来自系统调色板，不维护独立的固定深色主题。
- 图片预览底板和 `#ffb020` 检测框保持不变。
- 测试不访问真实懂鸟 API，不保存 API Key。

---

### Task 1: 系统调色板样式与运行时刷新

**Files:**
- Create: `src/birdclass/ui/theme.py`
- Create: `tests/unit/test_theme.py`
- Modify: `src/birdclass/app.py`
- Modify: `src/birdclass/ui/main_window.py`

**Interfaces:**
- Produces: `application_stylesheet(palette: QPalette) -> str`
- Produces: `SystemThemeController(app: QApplication)`，公开 `apply() -> None`
- Produces: `install_system_theme(app: QApplication) -> SystemThemeController`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_theme.py` 构造前景／背景已知的浅色和深色 `QPalette`，验证：

```python
assert window_color.name() in application_stylesheet(palette)
assert text_color.name() in application_stylesheet(palette)
assert contrast_ratio(window_color, text_color) >= 4.5
```

实例化 `SystemThemeController`，更换应用调色板并发出 `colorSchemeChanged`，断言新背景色进入 `app.styleSheet()`。在 `test_main_window.py` 断言 `window.styleSheet() == ""`，防止局部固定浅色规则回归。

- [ ] **Step 2: 运行测试并确认因缺少主题模块失败**

Run: `PYTHONPATH="$PWD/src" .venv/bin/python -m pytest tests/unit/test_theme.py -q`
Expected: 收集阶段因 `birdclass.ui.theme` 不存在而失败；不以此时的其他失败代替目标失败。

- [ ] **Step 3: 实现最小主题模块并接入应用**

`application_stylesheet` 使用以下颜色角色：

```python
window = palette.color(QPalette.ColorRole.Window).name()
text = palette.color(QPalette.ColorRole.Text).name()
base = palette.color(QPalette.ColorRole.Base).name()
alternate = palette.color(QPalette.ColorRole.AlternateBase).name()
mid = palette.color(QPalette.ColorRole.Mid).name()
highlight = palette.color(QPalette.ColorRole.Highlight).name()
highlighted = palette.color(QPalette.ColorRole.HighlightedText).name()
```

生成 `QMainWindow`、`QDialog`、`QGroupBox`、输入控件、`QComboBox QAbstractItemView`、`QListWidget` 和 `QPlainTextEdit` 规则。控制器实现：

```python
class SystemThemeController(QObject):
    def __init__(self, app: QApplication) -> None:
        super().__init__(app)
        self._app = app
        self.apply()
        app.styleHints().colorSchemeChanged.connect(self.apply)

    def apply(self) -> None:
        self._app.setStyleSheet(application_stylesheet(self._app.palette()))
```

`app.main()` 在创建主窗口前调用 `install_system_theme(app)`；删除 `MainWindow._build_ui()` 中的 `setStyleSheet` 块。

- [ ] **Step 4: 运行主题和 UI 测试**

Run: `PYTHONPATH="$PWD/src" .venv/bin/python -m pytest tests/unit/test_theme.py tests/unit/test_main_window.py tests/unit/test_review_dialog.py -q`
Expected: 全部通过，现有图片画框测试无回归。

- [ ] **Step 5: 提交功能实现**

```bash
git add src/birdclass/app.py src/birdclass/ui/main_window.py src/birdclass/ui/theme.py tests/unit/test_theme.py tests/unit/test_main_window.py
git commit -m "feat: follow system light and dark appearance"
```

### Task 2: 文档、视觉验证与完整回归

**Files:**
- Modify: `README.md`
- Modify: `docs/需求文档.md`
- Modify: `docs/开发手册.md`
- Modify: `docs/superpowers/plans/2026-10-25-system-dark-mode.md`

**Interfaces:**
- Consumes: Task 1 的 `SystemThemeController` 和 `application_stylesheet`。

- [ ] **Step 1: 更新说明**

README 主要功能增加“跟随系统浅色／深色外观，支持运行时切换”。需求文档在 UI 配置中增加相同验收要求。开发手册记录主题模块、调色板角色、信号和测试命令，并将测试数量更新为最终实测值。

- [ ] **Step 2: 生成并检查浅色／深色截图**

用 `QT_QPA_PLATFORM=offscreen`、隔离的 `QSettings`、已知浅深 `QPalette` 和 `SystemThemeController` 分别显示主窗口，保存到工作区 `validation/theme-light.png` 和 `validation/theme-dark.png`。检查窗口、分组框、输入框、按钮和日志的可读性；图片超过 3 MB 时先压缩再读取。

- [ ] **Step 3: 完整验证**

```bash
PYTHONPATH="$PWD/src" .venv/bin/python -m pytest -q
git diff --check
```

Expected: 所有测试通过，`git diff --check` 无输出。

- [ ] **Step 4: 提交文档并合并**

```bash
git add README.md docs/需求文档.md docs/开发手册.md
git add -f docs/superpowers/specs/2026-10-25-system-dark-mode-design.md docs/superpowers/plans/2026-10-25-system-dark-mode.md
git commit -m "docs: describe system appearance support"
git switch main
git merge --ff-only feature/system-dark-mode
```

合并后在主工作区再次运行完整测试，再同步 GitHub 并确认本地与远程一致。
