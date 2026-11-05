"""Tests for the prep-media sidecar pre-pass and pipeline behavior."""

import io
import json
import os

import pytest

from star_app_builder.utils import MediaSidecar as ms
from star_app_builder.utils import PrepareMedia as pm
from star_app_builder.utils.TextureEncoder import TextureCompressor


@pytest.fixture(autouse=True)
def _clean_registry():
    ms.Reset_Registry()
    yield
    ms.Reset_Registry()


def _index(root):
    immediate, _ = pm.BuildDirectoryIndex(str(root))
    return immediate


def _write(path, content=b"data"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def _write_sidecar(path, payload):
    path.write_text(json.dumps(payload), encoding="utf-8")


class _FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()
        return False


# --- auto-generation ---------------------------------------------------------


def test_auto_generates_sidecars_for_every_media_file(tmp_path):
    _write(tmp_path / "plain.png")
    _write(tmp_path / "note.txt")
    _write(tmp_path / "nested" / "sub.png")
    in_immediate = _index(tmp_path)

    pm.Resolve_Sidecars(in_immediate)

    plain_sidecar = json.loads(
        (tmp_path / "plain.png.star.json").read_text("utf-8")
    )
    assert plain_sidecar == {
        "type": "png",
        "source": "plain.png",
        "prep": ms.PREP_COMPRESS,
    }
    note_sidecar = json.loads(
        (tmp_path / "note.txt.star.json").read_text("utf-8")
    )
    assert note_sidecar["prep"] == ms.PREP_COPY
    assert (tmp_path / "nested" / "sub.png.star.json").is_file()

    assert ms.Get_Prep(str(tmp_path / "plain.png")) == ms.PREP_COMPRESS
    assert ms.Get_Prep(str(tmp_path / "note.txt")) == ms.PREP_COPY
    assert ms.Get_Prep(str(tmp_path / "nested" / "sub.png")) == ms.PREP_COMPRESS


def test_existing_explicit_sidecar_controls_prep_and_is_not_overwritten(tmp_path):
    _write(tmp_path / "skybox.png")
    sidecar = tmp_path / "skybox.png.star.json"
    _write_sidecar(
        sidecar,
        {"type": "png", "source": "skybox.png", "prep": "copy"},
    )
    before = sidecar.read_bytes()

    pm.Resolve_Sidecars(_index(tmp_path))

    assert sidecar.read_bytes() == before
    assert ms.Get_Prep(str(tmp_path / "skybox.png")) == ms.PREP_COPY


def test_plain_json_data_file_is_media_not_a_sidecar(tmp_path):
    data_file = tmp_path / "settings.json"
    data_file.write_text('{"volume": 0.5}', encoding="utf-8")

    pm.Resolve_Sidecars(_index(tmp_path))

    # No sidecar is generated for a data JSON, and it is routed as copy-media.
    assert not (tmp_path / "settings.json.star.json").exists()
    assert ms.Get_Prep(str(data_file)) == ms.PREP_COPY


def test_json_extension_is_case_insensitive_and_nested_json_is_skipped(tmp_path):
    _write(tmp_path / "Top.JSON")
    _write(tmp_path / "nested" / "deep.json")

    pm.Resolve_Sidecars(_index(tmp_path))

    assert not (tmp_path / "Top.JSON.star.json").exists()
    assert not (tmp_path / "nested" / "deep.json.star.json").exists()
    assert ms.Get_Prep(str(tmp_path / "Top.JSON")) == ms.PREP_COPY
    assert ms.Get_Prep(str(tmp_path / "nested" / "deep.json")) == ms.PREP_COPY


def test_hidden_files_are_ignored_and_get_no_sidecar(tmp_path):
    _write(tmp_path / ".hidden.txt")

    pm.Resolve_Sidecars(_index(tmp_path))

    assert [p.name for p in sorted(tmp_path.iterdir())] == [".hidden.txt"]


# --- URL sources -------------------------------------------------------------


def test_url_source_downloads_once_and_joins_index(tmp_path, monkeypatch):
    sidecar = tmp_path / "skybox.mp4.star.json"
    _write_sidecar(
        sidecar,
        {
            "type": "mp4",
            "source": "https://cdn.example.com/assets/sky.mp4",
            "prep": "copy",
        },
    )
    calls = []

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        return _FakeResponse(b"video-bytes")

    monkeypatch.setattr(ms.urllib.request, "urlopen", fake_urlopen)

    in_immediate = _index(tmp_path)
    pm.Resolve_Sidecars(in_immediate)

    target = tmp_path / "skybox.mp4"
    assert target.read_bytes() == b"video-bytes"
    assert calls == ["https://cdn.example.com/assets/sky.mp4"]
    assert ms.Get_Prep(str(target)) == ms.PREP_COPY
    # Downloaded media must be visible to stale-output cleanup this run.
    assert str(target) in in_immediate[str(tmp_path)]

    # Second run: cached file means no download at all.
    pm.Reset_Registry()
    pm.Resolve_Sidecars(_index(tmp_path))
    assert calls == ["https://cdn.example.com/assets/sky.mp4"]


def test_url_sidecar_type_defaults_from_its_media_filename(tmp_path, monkeypatch):
    _write_sidecar(
        tmp_path / "sky.webp.star.json",
        {"source": "https://cdn.example.com/asset?id=7"},
    )

    monkeypatch.setattr(
        ms.urllib.request,
        "urlopen",
        lambda req, timeout=None: _FakeResponse(b"webp-bytes"),
    )

    pm.Resolve_Sidecars(_index(tmp_path))

    assert (tmp_path / "sky.webp").read_bytes() == b"webp-bytes"
    assert ms.Get_Prep(str(tmp_path / "sky.webp")) == ms.PREP_COMPRESS


def test_failed_download_skips_file_and_counts_failure(tmp_path, monkeypatch):
    _write_sidecar(
        tmp_path / "skybox.png.star.json",
        {
            "type": "png",
            "source": "https://cdn.example.com/sky.png",
            "prep": "copy",
        },
    )

    def failing_urlopen(req, timeout=None):
        raise OSError("network down")

    monkeypatch.setattr(ms.urllib.request, "urlopen", failing_urlopen)

    pm.Resolve_Sidecars(_index(tmp_path))

    assert not (tmp_path / "sky.png").exists()
    assert ms.Get_Download_Failure_Count() == 1
    # No leftover temp file from the aborted download.
    assert [p.name for p in tmp_path.iterdir()] == ["skybox.png.star.json"]


# --- routing rules -----------------------------------------------------------


def test_compress_on_non_image_downgrades_to_copy(tmp_path, capsys):
    _write(tmp_path / "video.mp4")
    _write_sidecar(
        tmp_path / "video.mp4.star.json",
        {"type": "mp4", "source": "video.mp4", "prep": "compress"},
    )

    pm.Resolve_Sidecars(_index(tmp_path))

    assert ms.Get_Prep(str(tmp_path / "video.mp4")) == ms.PREP_COPY
    assert "non-image" in capsys.readouterr().out


def test_type_mismatch_uses_actual_extension(tmp_path, capsys):
    _write(tmp_path / "badge.png")
    _write_sidecar(
        tmp_path / "badge.png.star.json",
        {"type": "jpg", "source": "badge.png", "prep": "copy"},
    )

    pm.Resolve_Sidecars(_index(tmp_path))

    assert ms.Get_Prep(str(tmp_path / "badge.png")) == ms.PREP_COPY
    assert "using the actual extension" in capsys.readouterr().out


def test_local_source_is_provenance_not_a_redirect(tmp_path):
    _write(tmp_path / "bar.png")
    _write_sidecar(
        tmp_path / "bar.png.star.json",
        {"type": "png", "source": "foo.png", "prep": "copy"},
    )

    pm.Resolve_Sidecars(_index(tmp_path))

    # The sidecar's filename decides the media; source is just provenance.
    assert ms.Get_Prep(str(tmp_path / "bar.png")) == ms.PREP_COPY
    assert not (tmp_path / "foo.png").exists()


def test_sidecar_describing_missing_media_warns_and_is_skipped(tmp_path, capsys):
    _write_sidecar(
        tmp_path / "ghost.png.star.json",
        {"type": "png", "source": "ghost.png", "prep": "copy"},
    )

    pm.Resolve_Sidecars(_index(tmp_path))

    assert "describes missing media" in capsys.readouterr().out


def test_same_stem_different_extensions_get_distinct_sidecars(tmp_path):
    _write(tmp_path / "skybox.png")
    _write(tmp_path / "skybox.mp4")

    pm.Resolve_Sidecars(_index(tmp_path))

    assert (tmp_path / "skybox.png.star.json").is_file()
    assert (tmp_path / "skybox.mp4.star.json").is_file()
    assert ms.Get_Prep(str(tmp_path / "skybox.png")) == ms.PREP_COMPRESS
    assert ms.Get_Prep(str(tmp_path / "skybox.mp4")) == ms.PREP_COPY


def test_malformed_sidecar_falls_back_to_defaults_and_is_preserved(tmp_path, capsys):
    _write(tmp_path / "badge.png")
    sidecar = tmp_path / "badge.png.star.json"
    sidecar.write_text("{", encoding="utf-8")
    before = sidecar.read_bytes()

    pm.Resolve_Sidecars(_index(tmp_path))

    assert sidecar.read_bytes() == before
    assert ms.Get_Prep(str(tmp_path / "badge.png")) == ms.PREP_COMPRESS
    assert "could not read sidecar" in capsys.readouterr().out


# --- pipeline ----------------------------------------------------------------


class _NoopCompressor:
    """Stand-in for TextureCompressor so the pipeline test needs no basisu."""

    instances = []

    def __init__(self):
        self.textures = []
        _NoopCompressor.instances.append(self)

    @staticmethod
    def should_compress(texture):
        return TextureCompressor.should_compress(texture)

    def add_texture(self, texture):
        self.textures.append(texture)

    def compress(self, *args, **kwargs):
        pass


def _copy_sidecar(directory, media_name):
    payload = {
        "type": os.path.splitext(media_name)[1].lstrip(".").lower(),
        "source": media_name,
        "prep": "copy",
    }
    (directory / (media_name + ms.SIDECAR_SUFFIX)).write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_pipeline_copies_media_and_never_emits_sidecars(tmp_path, monkeypatch):
    in_dir = tmp_path / "in"
    out_dir = tmp_path / "out"
    in_dir.mkdir()
    out_dir.mkdir()

    _write(in_dir / "plain.png", b"png-bytes")
    _copy_sidecar(in_dir, "plain.png")
    _write(in_dir / "note.txt", b"note-bytes")
    _copy_sidecar(in_dir, "note.txt")
    # A real data JSON with no sidecar: it must be copied, not swallowed.
    (in_dir / "settings.json").write_text('{"volume": 0.5}', encoding="utf-8")
    _write(in_dir / ".hidden.txt", b"secret")
    _write(in_dir / "nested" / "sub.png", b"sub-bytes")
    _copy_sidecar(in_dir / "nested", "sub.png")

    monkeypatch.setattr(pm, "TextureCompressor", _NoopCompressor)

    pm.main(str(in_dir), str(out_dir), None, False)

    assert (out_dir / "plain.png").read_bytes() == b"png-bytes"
    assert (out_dir / "note.txt").read_bytes() == b"note-bytes"
    assert (out_dir / "settings.json").read_text(encoding="utf-8") == (
        '{"volume": 0.5}'
    )
    assert (out_dir / "nested" / "sub.png").read_bytes() == b"sub-bytes"
    assert not (out_dir / ".hidden.txt").exists()

    for _, _, files in os.walk(out_dir):
        for f in files:
            assert not ms.Is_Sidecar_File(f), (
                f"sidecar leaked into output: {f}"
            )
            assert not f.startswith("."), f"dotfile leaked into output: {f}"

    # A second run is a no-op: same output tree, inputs untouched.
    snapshot = {
        str(p.relative_to(out_dir)): p.read_bytes()
        for p in out_dir.rglob("*")
        if p.is_file()
    }
    input_snapshot = {
        str(p.relative_to(in_dir)): p.read_bytes()
        for p in in_dir.rglob("*")
        if p.is_file()
    }

    pm.main(str(in_dir), str(out_dir), None, False)

    assert {
        str(p.relative_to(out_dir)): p.read_bytes()
        for p in out_dir.rglob("*")
        if p.is_file()
    } == snapshot
    assert {
        str(p.relative_to(in_dir)): p.read_bytes()
        for p in in_dir.rglob("*")
        if p.is_file()
    } == input_snapshot
