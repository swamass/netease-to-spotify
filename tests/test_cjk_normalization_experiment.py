from src import cjk_normalization_experiment as experiment
import pytest


def test_nfkc_handles_compatibility_kanji_without_changing_production_code():
    assert experiment.nfkc_key("神") == experiment.nfkc_key("神")


def test_simplified_and_traditional_keys_remain_distinct_without_optional_converter():
    result = experiment.compare("最后の言い訳", "最後の言い訳")
    assert not result["equivalent"]
    assert result["left_keys"]["original"] != result["right_keys"]["original"]


def test_optional_opencc_key_can_compare_simplified_and_traditional_titles():
    converter = lambda value: value.replace("后", "後").replace("间", "間")
    result = experiment.compare("最后の言い訳", "最後の言い訳", converter)
    assert result["equivalent"]
    assert result["left_keys"]["opencc_s2t"] == result["right_keys"]["opencc_s2t"]


def test_limited_cjk_conversion_does_not_merge_different_titles():
    converter = lambda value: value.replace("后", "後").replace("间", "間")
    result = experiment.compare("春の歌", "春の夜", converter)
    assert not result["equivalent"]


def test_mixed_chinese_japanese_title_preserves_non_cjk_text():
    converter = lambda value: value.replace("京", "京").replace("东", "東")
    left = experiment.comparison_keys("東京 / Love", converter)
    right = experiment.comparison_keys("东京 / Love", converter)
    assert left["opencc_s2t"] == right["opencc_s2t"]
    assert "love" in left["original"]


def test_cjk_variant_normalization_is_not_universally_fuzzy():
    result = experiment.compare("皆既月食", "皆既月蝕")
    assert not result["equivalent"]


def test_real_opencc_profiles_are_exposed_when_installed():
    converters = experiment.opencc_converters()
    if not converters:
        pytest.skip("OpenCC is optional for this standalone experiment")
    assert set(converters) == {"s2t", "s2tw", "s2hk"}
    for profile, converter in converters.items():
        assert experiment.original_key(converter("国学爱情会体気"))


def test_opencc_is_only_an_additional_key():
    converter = lambda value: value.replace("后", "後")
    keys = experiment.comparison_keys("最后の言い訳", converter)
    assert keys["original"] != keys["opencc_s2t"]
