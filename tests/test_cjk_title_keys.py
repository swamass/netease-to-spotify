from src import cjk_title_keys as keys


def converter(value):
    return value.replace("后", "後").replace("间", "間")


def test_simplified_traditional_title_is_cjk_equivalent():
    assert keys.title_status("最后の言い訳", "最後の言い訳", converter) == keys.CJK_EQUIVALENT


def test_original_and_nfkc_only_do_not_match_simplified_traditional_title():
    assert keys.title_status("最后の言い訳", "最後の言い訳") == keys.NO_MATCH


def test_different_japanese_titles_do_not_match():
    assert keys.title_status("皆既月食", "皆既月蝕", converter) == keys.NO_MATCH


def test_version_conflict_blocks_cjk_equivalence():
    assert keys.title_status(
        "最后の言い訳", "最後の言い訳 (Live)", converter,
        version_conflict=lambda _source, _candidate: True,
    ) == keys.NO_MATCH


def test_non_cjk_skeleton_difference_blocks_equivalence():
    assert keys.title_status("東京 Love", "东京 Song", converter) == keys.NO_MATCH


def test_converter_failure_falls_back_to_no_match():
    def broken(_value):
        raise RuntimeError("converter unavailable")

    assert keys.title_status("最后の言い訳", "最後の言い訳", broken) == keys.NO_MATCH


def test_nfkc_compatibility_key_preserves_title_baseline():
    comparison = keys.comparison_keys("神")

    assert comparison["original"] == comparison["nfkc"]
    assert keys.title_status("神", "神") == keys.EXACT


def test_opencc_key_is_auxiliary_only():
    comparison = keys.comparison_keys("最后の言い訳", converter)

    assert comparison["original"] == "最后の言い訳"
    assert comparison["original"] != comparison["cjk"]
