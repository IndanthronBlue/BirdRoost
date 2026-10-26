from birdclass.taxonomy import load_taxonomy


def test_taxonomy_loads_ioc_snapshot():
    taxonomy = load_taxonomy()

    assert len(taxonomy) == 11227
    assert taxonomy.version == "IOC 15.2"


def test_resolve_by_scientific_chinese_and_english():
    taxonomy = load_taxonomy()

    by_latin = taxonomy.resolve(scientific_name="Calidris alba")
    by_chinese = taxonomy.resolve(name_zh="三趾滨鹬")
    by_english = taxonomy.resolve(name_en="Eurasian Wryneck")

    assert by_latin is not None
    assert by_latin.name_zh == "三趾滨鹬"
    assert by_latin.family == "Scolopacidae"
    assert by_latin.order == "CHARADRIIFORMES"
    assert by_chinese == by_latin
    assert by_english is not None
    assert by_english.scientific_name == "Jynx torquilla"


def test_archived_name_variants_resolve_through_aliases():
    taxonomy = load_taxonomy()

    assert taxonomy.resolve(name_zh="北灰鶲").scientific_name == "Muscicapa dauurica"
    assert taxonomy.resolve(name_zh="斑鶲").scientific_name == "Muscicapa striata"
    assert taxonomy.resolve(name_zh="蚁鴷").scientific_name == "Jynx torquilla"


def test_unknown_species_returns_none():
    taxonomy = load_taxonomy()

    assert taxonomy.resolve(scientific_name="Not A Bird") is None
    assert taxonomy.resolve(name_zh="不存在的鸟") is None
    assert taxonomy.resolve() is None


def test_hierarchy_and_label_fallbacks():
    taxonomy = load_taxonomy()
    taxon = taxonomy.resolve(scientific_name="Calidris alba")

    assert taxon is not None
    hierarchy = taxon.hierarchy()
    assert [rank for rank, _, _ in hierarchy] == ["界", "门", "纲", "目", "科", "属", "种"]
    assert hierarchy[0][1:] == ("动物界", "Animalia")
    assert hierarchy[3][1] == "鸻形目"
    assert hierarchy[4][1] == "鹬科"
    assert hierarchy[5][1] == "滨鹬属"
    assert hierarchy[6][1] == "三趾滨鹬"


def test_some_species_have_no_chinese_name():
    taxonomy = load_taxonomy()

    missing = [taxon for taxon in taxonomy.all_taxa() if not taxon.name_zh]
    assert len(missing) == 23
    assert all(taxon.scientific_name for taxon in missing)
