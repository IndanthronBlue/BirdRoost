from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QCompleter

COUNTRIES = [
    "中国", "西班牙", "葡萄牙", "法国", "荷兰", "塞浦路斯", "格鲁吉亚",
    "英国", "爱尔兰", "德国", "奥地利", "瑞士", "意大利", "希腊", "克罗地亚",
    "斯洛文尼亚", "捷克", "波兰", "匈牙利", "罗马尼亚", "保加利亚", "塞尔维亚",
    "阿尔巴尼亚", "比利时", "卢森堡", "马耳他", "丹麦", "瑞典", "挪威", "芬兰",
    "冰岛", "爱沙尼亚", "拉脱维亚", "立陶宛", "乌克兰", "俄罗斯", "土耳其",
    "以色列", "约旦", "阿联酋", "摩洛哥", "埃及", "肯尼亚", "坦桑尼亚", "乌干达",
    "卢旺达", "埃塞俄比亚", "南非", "纳米比亚", "博茨瓦纳", "印度", "斯里兰卡",
    "尼泊尔", "不丹", "孟加拉国", "缅甸", "泰国", "老挝", "柬埔寨", "越南",
    "马来西亚", "新加坡", "印度尼西亚", "菲律宾", "日本", "韩国", "蒙古",
    "哈萨克斯坦", "美国", "加拿大", "墨西哥", "哥斯达黎加", "巴西", "阿根廷",
    "智利", "秘鲁", "厄瓜多尔", "哥伦比亚", "澳大利亚", "新西兰",
]

CHINA_REGIONS = [
    "北京", "天津", "上海", "重庆", "河北", "山西", "辽宁", "吉林", "黑龙江",
    "江苏", "浙江", "安徽", "福建", "江西", "山东", "河南", "湖北", "湖南",
    "广东", "海南", "四川", "贵州", "云南", "陕西", "甘肃", "青海", "台湾",
    "内蒙古", "广西", "西藏", "宁夏", "新疆", "香港", "澳门",
]


def configure_geo_combo(combo: QComboBox, values: list[str], placeholder: str) -> None:
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    combo.setMaxVisibleItems(16)
    combo.addItems(values)
    combo.setCurrentIndex(-1)
    combo.setCurrentText("")
    combo.lineEdit().setPlaceholderText(placeholder)
    completer = QCompleter(combo.model(), combo)
    completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    combo.setCompleter(completer)


def is_china(country: str) -> bool:
    return country.strip() == "中国"
