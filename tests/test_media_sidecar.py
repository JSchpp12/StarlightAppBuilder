"""Unit tests for MediaSidecar: parsing, validation, registry, writing."""

import json
import os

import pytest

from star_app_builder.utils import MediaSidecar as ms


@pytest.fixture(autouse=True)
def _clean_registry():
    ms.Reset_Registry()
    yield
    ms.Reset_Registry()


def _validate(tmp_path, payload, name="skybox.png.star.json"):
    sidecar = tmp_path / name
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    return ms.Validate_Sidecar(ms.Load_Sidecar(str(sidecar)), str(sidecar))


# --- filename classification -------------------------------------------------


def test_is_sidecar_file():
    assert ms.Is_Sidecar_File("skybox.png.star.json")
    assert ms.Is_Sidecar_File("SKYBOX.PNG.STAR.JSON")
    assert ms.Is_Sidecar_File("sub/dir/skybox.png.star.json")
    assert not ms.Is_Sidecar_File("skybox.json")
    assert not ms.Is_Sidecar_File("settings.json")
    assert not ms.Is_Sidecar_File(".star.json")
    assert not ms.Is_Sidecar_File("skybox.png")


def test_is_json_data_file():
    assert ms.Is_Json_Data_File("settings.json")
    assert ms.Is_Json_Data_File("SETTINGS.JSON")
    assert ms.Is_Json_Data_File("sub/dir/data.json")
    # Sidecars are metadata, not data files.
    assert not ms.Is_Json_Data_File("skybox.png.star.json")
    assert not ms.Is_Json_Data_File("settings.json.star.json")
    assert not ms.Is_Json_Data_File("skybox.png")
    assert not ms.Is_Json_Data_File("json")


def test_media_name_and_sidecar_path_round_trip():
    sidecar = os.path.join("media", "skybox.png.star.json")
    assert ms.Get_Media_Name_From_Sidecar(sidecar) == "skybox.png"
    media = os.path.join("media", "skybox.png")
    assert ms.Get_Sidecar_Path(media) == sidecar


def test_is_hidden_file():
    assert ms.Is_Hidden_File(".star_ignore_skybox")
    assert ms.Is_Hidden_File("sub/.download_abc")
    assert not ms.Is_Hidden_File("skybox.png")


# --- validation --------------------------------------------------------------


def test_valid_sidecar_normalizes_type(tmp_path):
    data = _validate(tmp_path, {"type": ".PNG", "source": "skybox.png", "prep": "copy"})
    assert data == {"type": "png", "source": "skybox.png", "prep": "copy"}


def test_defaults_apply_when_fields_omitted(tmp_path):
    data = _validate(tmp_path, {})
    assert data == {"type": "png", "source": "skybox.png", "prep": "compress"}


def test_type_comes_from_sidecar_media_filename(tmp_path):
    # The sidecar names the media file; 'source' is provenance and does not
    # change what is being described.
    data = _validate(tmp_path, {"source": "other.JPG"})
    assert data == {"type": "png", "source": "other.JPG", "prep": "compress"}


def test_explicit_type_is_lowercased_and_dot_stripped(tmp_path):
    data = _validate(tmp_path, {"type": ".WebP"})
    assert data["type"] == "webp"


def test_extensionless_media_name_is_allowed(tmp_path):
    data = _validate(tmp_path, {"prep": "copy"}, name="README.star.json")
    assert data == {"type": "", "source": "README", "prep": "copy"}


def test_non_string_type_falls_back_to_media_extension(tmp_path, capsys):
    data = _validate(tmp_path, {"type": 7})
    assert data["type"] == "png"
    assert "non-string 'type'" in capsys.readouterr().out


def test_malformed_json_returns_none_without_raising(tmp_path, capsys):
    sidecar = tmp_path / "broken.png.star.json"
    sidecar.write_text("{", encoding="utf-8")

    assert ms.Load_Sidecar(str(sidecar)) is None
    assert "could not read sidecar" in capsys.readouterr().out


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16"])
def test_bom_encoded_sidecar_is_read(tmp_path, encoding):
    # Windows editors/PowerShell commonly write a BOM; it must not make the
    # sidecar look malformed.
    sidecar = tmp_path / "skybox.png.star.json"
    payload = {
        "type": "exr",
        "source": "https://example.com/sky.exr",
        "prep": "copy",
    }
    sidecar.write_bytes(json.dumps(payload).encode(encoding))

    data = ms.Validate_Sidecar(ms.Load_Sidecar(str(sidecar)), str(sidecar))
    assert data == payload


def test_non_object_root_is_rejected(tmp_path, capsys):
    assert _validate(tmp_path, ["not", "a", "dict"]) is None
    assert "must contain a JSON object" in capsys.readouterr().out


def test_unknown_keys_warn_but_do_not_invalidate(tmp_path, capsys):
    data = _validate(
        tmp_path,
        {"type": "png", "source": "skybox.png", "prep": "copy", "future": 1},
    )
    assert data["prep"] == "copy"
    assert "unknown key 'future'" in capsys.readouterr().out


def test_invalid_prep_warns_and_defaults_to_compress(tmp_path, capsys):
    data = _validate(
        tmp_path, {"type": "png", "source": "skybox.png", "prep": "shrink"}
    )
    assert data["prep"] == "compress"
    assert "invalid prep" in capsys.readouterr().out


@pytest.mark.parametrize(
    "source",
    [
        "ftp://example.com/skybox.png",
        "file:///tmp/skybox.png",
        "../escape.png",
        "sub/dir/skybox.png",
        "sub\\dir\\skybox.png",
        "C:skybox.png",
        "..",
    ],
)
def test_bad_sources_are_rejected(tmp_path, source, capsys):
    assert _validate(tmp_path, {"type": "png", "source": source}) is None
    assert "Warning" in capsys.readouterr().out


def test_absolute_source_is_rejected(tmp_path, capsys):
    absolute = str(tmp_path / "elsewhere.png")
    assert _validate(tmp_path, {"type": "png", "source": absolute}) is None
    assert "Warning" in capsys.readouterr().out


# --- registry ----------------------------------------------------------------


def test_registry_default_is_compress(tmp_path):
    path = str(tmp_path / "unknown.png")
    assert ms.Get_Prep(path) == ms.PREP_COMPRESS

    ms.Register_Media(path, {"type": "png", "source": "a.png", "prep": "copy"})
    assert ms.Get_Prep(path) == ms.PREP_COPY
    # Lookup normalizes to absolute paths (here: an unnormalized-but-equal path).
    assert ms.Get_Prep(str(tmp_path) + os.sep + "." + os.sep + "unknown.png") == (
        ms.PREP_COPY
    )


def test_reset_registry_clears_entries_and_failure_count(tmp_path):
    path = str(tmp_path / "a.png")
    ms.Register_Media(path, {"type": "png", "source": "a.png", "prep": "copy"})
    ms.Download_Media_File("ftp://example.com/a.png", path)
    assert ms.Get_Prep(path) == ms.PREP_COPY
    assert ms.Get_Download_Failure_Count() == 1

    ms.Reset_Registry()
    assert ms.Get_Prep(path) == ms.PREP_COMPRESS
    assert ms.Get_Download_Failure_Count() == 0


# --- writing ----------------------------------------------------------------


def test_write_default_sidecar_round_trips(tmp_path):
    path = tmp_path / "skybox.png.star.json"
    assert ms.Write_Default_Sidecar(str(path), "png", "skybox.png", ms.PREP_COMPRESS)
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "type": "png",
        "source": "skybox.png",
        "prep": "compress",
    }


def test_unsupported_scheme_download_fails_without_network(tmp_path):
    target = tmp_path / "skybox.png"
    assert not ms.Download_Media_File("ftp://example.com/skybox.png", str(target))
    assert not target.exists()
    assert ms.Get_Download_Failure_Count() == 1
