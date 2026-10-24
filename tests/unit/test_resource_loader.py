from birdclass.resource_loader import area_name_for_code


def test_area_name_uses_chinese_label_and_global_fallback():
    assert area_name_for_code("CN") == "中国"
    assert area_name_for_code("WORLD") == "全球"
    assert area_name_for_code("NOT-A-CODE") == "全球"
