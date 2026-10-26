from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from .geo_fields import CHINA_REGIONS, COUNTRIES, configure_geo_combo, is_china


class ObservationDialog(QDialog):
    def __init__(
        self,
        *,
        country: str = "",
        region: str = "",
        location: str = "",
        time: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("修改观测信息")
        self.resize(440, 260)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("双击修改当前照片所属 group 的观测信息。"))
        form = QFormLayout()
        self.country = QComboBox()
        configure_geo_combo(self.country, COUNTRIES, "输入或选择国家")
        self.country.setCurrentText(country)
        form.addRow("国家", self.country)
        self.region = QComboBox()
        configure_geo_combo(self.region, CHINA_REGIONS, "选择省份/直辖市")
        self.region.setCurrentText(region)
        form.addRow("省份/地区", self.region)
        self.region_label = form.labelForField(self.region)
        self.location = QLineEdit(location)
        self.location.setPlaceholderText("例如：南汇、多尼亚那")
        form.addRow("地点", self.location)
        self.time = QLineEdit(time)
        self.time.setPlaceholderText("例如：2026-05")
        form.addRow("观测时间", self.time)
        layout.addLayout(form)
        self.country.currentTextChanged.connect(self._on_country_changed)
        self._on_country_changed(self.country.currentText())
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_country_changed(self, text: str) -> None:
        china = is_china(text)
        self.region.setVisible(china)
        if self.region_label is not None:
            self.region_label.setVisible(china)
        if not china:
            self.region.setCurrentText("")

    @property
    def country_text(self) -> str:
        return self.country.currentText().strip()

    @property
    def region_text(self) -> str:
        return self.region.currentText().strip() if is_china(self.country_text) else ""

    @property
    def location_text(self) -> str:
        return self.location.text().strip()

    @property
    def time_text(self) -> str:
        return self.time.text().strip()
