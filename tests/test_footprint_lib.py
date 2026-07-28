from pathlib import Path

from circuit_weaver.footprint_lib import (
    KiCadFootprintLibrary,
    curated_footprint_alternatives,
    custom_footprint_suggestion,
    official_kicad_footprint_url,
)


def test_footprint_exists_for_local_pretty_library(tmp_path: Path):
    pretty = tmp_path / "Battery.pretty"
    pretty.mkdir()
    (pretty / "BatteryHolder_Keystone_2462_2xAA.kicad_mod").write_text("(footprint \"x\")", encoding="utf-8")

    lib = KiCadFootprintLibrary(tmp_path)

    assert lib.footprint_exists("Battery:BatteryHolder_Keystone_2462_2xAA")
    assert not lib.footprint_exists("Battery:Missing")
    assert not lib.footprint_exists("not-a-footprint-ref")


def test_find_returns_kicad_footprint_refs(tmp_path: Path):
    pretty = tmp_path / "Package_TO_SOT_SMD.pretty"
    pretty.mkdir()
    (pretty / "SC-70-5.kicad_mod").write_text("(footprint \"x\")", encoding="utf-8")

    lib = KiCadFootprintLibrary(tmp_path)

    assert "Package_TO_SOT_SMD:SC-70-5" in lib.find("sc-70")


def test_geometry_cache_invalidates_when_resolved_content_changes(tmp_path: Path):
    pretty = tmp_path / "Test.pretty"
    pretty.mkdir()
    path = pretty / "BOX.kicad_mod"
    path.write_text(
        '(footprint "BOX" (fp_rect (start -2 -1) (end 2 1) (layer "F.CrtYd")))',
        encoding="utf-8",
    )
    lib = KiCadFootprintLibrary(tmp_path)

    first = lib.geometry("Test:BOX")
    path.write_text(
        '(footprint "BOX" (fp_rect (start -3 -2) (end 3 2) (layer "F.CrtYd")))',
        encoding="utf-8",
    )
    second = lib.geometry("Test:BOX")

    assert (first.width_mm, first.height_mm) == (4.0, 2.0)
    assert (second.width_mm, second.height_mm) == (6.0, 4.0)
    assert first.content_hash != second.content_hash
    assert (first.evidence_kind, first.confidence) == ("footprint_lib", "verified")


def test_missing_footprint_geometry_fallback_is_explicitly_heuristic(tmp_path: Path):
    geometry = KiCadFootprintLibrary(tmp_path).geometry("Package:Widget_6x4mm")

    assert (geometry.width_mm, geometry.height_mm) == (6.0, 4.0)
    assert geometry.source == "heuristic"
    assert (geometry.evidence_kind, geometry.confidence) == ("heuristic", "heuristic")


def test_geometry_cache_invalidates_when_unresolved_footprint_becomes_resolved(tmp_path: Path):
    lib = KiCadFootprintLibrary(tmp_path)
    first = lib.geometry("Test:BOX")
    pretty = tmp_path / "Test.pretty"
    pretty.mkdir()
    (pretty / "BOX.kicad_mod").write_text(
        '(footprint "BOX" (fp_rect (start -2 -1) (end 2 1) (layer "F.CrtYd")))',
        encoding="utf-8",
    )

    second = lib.geometry("Test:BOX")

    assert first.confidence == "heuristic"
    assert second.confidence == "verified"
    assert second.source == "courtyard"
    assert (second.width_mm, second.height_mm) == (4.0, 2.0)


def test_official_kicad_footprint_url_points_to_library_browser():
    url = official_kicad_footprint_url("Battery:BatteryHolder_Keystone_2462_2xAA")

    assert url == (
        "https://gitlab.com/kicad/libraries/kicad-footprints/-/blob/master/"
        "Battery.pretty/BatteryHolder_Keystone_2462_2xAA.kicad_mod"
    )


def test_curated_alternatives_only_include_available_footprints(tmp_path: Path):
    pretty = tmp_path / "RF_Module.pretty"
    pretty.mkdir()
    (pretty / "ESP32-C6-MINI-1.kicad_mod").write_text("(footprint \"x\")", encoding="utf-8")

    alts = curated_footprint_alternatives("E72-2G4M20S1E", KiCadFootprintLibrary(tmp_path))

    assert "ESP32-C6-MINI-1" in {alt["mpn"] for alt in alts}
    assert all(KiCadFootprintLibrary(tmp_path).footprint_exists(alt["footprint"]) for alt in alts)


def test_custom_footprint_suggestion_uses_advanced_mode_caveat(tmp_path: Path):
    lib = KiCadFootprintLibrary(tmp_path)

    suggestion = custom_footprint_suggestion("EKMB1303111", "Sensor:Panasonic_EKM_THT", lib)

    assert "advanced/custom-footprint mode" in suggestion
    assert "trusted vendor or project .pretty" in suggestion
