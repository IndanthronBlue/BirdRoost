from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QMenu, QToolButton, QWidget

LocationKey = tuple[str, str, str]


class LocationFilterButton(QToolButton):
    """A compact country drawer for hierarchical observation filters."""

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.setMinimumWidth(180)
        self._current: LocationKey = ("", "", "")
        self._nodes: list[tuple[LocationKey, str, int]] = []
        self.setMenu(QMenu(self))
        self._update_text()

    def currentData(self) -> LocationKey:
        return self._current

    def setCurrentData(self, key: LocationKey, *, emit: bool = True) -> None:
        self._current = key if key in {node[0] for node in self._nodes} else ("", "", "")
        self._update_text()
        if emit:
            self.changed.emit()

    def set_nodes(
        self,
        nodes: list[tuple[LocationKey, str, int]],
        current: LocationKey | None = None,
    ) -> None:
        self._nodes = list(nodes)
        if current is not None:
            self._current = current if current in {node[0] for node in self._nodes} else ("", "", "")
        elif self._current not in {node[0] for node in self._nodes}:
            self._current = ("", "", "")
        self._build_menu()
        self._update_text()

    def _label_for(self, key: LocationKey) -> str:
        for node_key, label, _count in self._nodes:
            if node_key == key:
                return label.strip()
        return ""

    def _update_text(self) -> None:
        if self._current == ("", "", ""):
            text = "全部观测地"
        else:
            parts = [part for part in self._current if part]
            text = " / ".join(parts)
        self.setText(text)
        self.setToolTip(f"观测地筛选：{text}")

    def _action(self, menu: QMenu, label: str, key: LocationKey):
        action = menu.addAction(label)
        action.setCheckable(True)
        action.setChecked(key == self._current)
        action.triggered.connect(lambda _checked=False, value=key: self._activate(value))
        return action

    def _activate(self, key: LocationKey) -> None:
        self._current = key
        self._update_text()
        self.changed.emit()

    def _build_menu(self) -> None:
        menu = self.menu()
        if menu is None:
            menu = QMenu(self)
            self.setMenu(menu)
        menu.clear()
        self._action(menu, "全部观测地", ("", "", ""))

        countries: dict[str, int] = {}
        regions: dict[tuple[str, str], int] = {}
        places: dict[tuple[str, str, str], int] = {}
        for key, _label, count in self._nodes:
            country, region, place = key
            if not country:
                continue
            if not region and not place:
                countries[country] = count
            if region and not place:
                regions[(country, region)] = count
            if place:
                places[key] = count

        for country in sorted(countries):
            country_menu = menu.addMenu(f"{country}  ({countries[country]})")
            self._action(country_menu, f"全部 {country}", (country, "", ""))
            country_regions = sorted(
                region for c, region in regions if c == country
            )
            if not country_regions:
                for key in sorted(k for k in places if k[0] == country and not k[1]):
                    self._action(
                        country_menu, f"{key[2]}  ({places[key]})", key
                    )
                continue
            for region in country_regions:
                region_menu = country_menu.addMenu(
                    f"{region}  ({regions[(country, region)]})"
                )
                self._action(region_menu, f"全部 {region}", (country, region, ""))
                for key in sorted(
                    k for k in places if k[0] == country and k[1] == region
                ):
                    self._action(region_menu, f"{key[2]}  ({places[key]})", key)
            for key in sorted(k for k in places if k[0] == country and not k[1]):
                self._action(country_menu, f"{key[2]}  ({places[key]})", key)
