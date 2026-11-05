"""Sidecar JSON metadata for media files processed by prep-media.

A sidecar sits next to the media file it describes and adds an explicit
``.star.json`` suffix, so it cannot be confused with real ``.json`` data files
in the media tree::

    media/logo.png
    media/logo.png.star.json
    media/settings.json          <- ordinary JSON data, copied as media
                                      (no ``settings.json.star.json`` is generated)

A sidecar looks like::

    {
      "type": "png",
      "source": "logo.png",
      "prep": "compress"
    }

``source`` is provenance: either the local filename the media originally came
from (normally the same as the sidecar's media filename) or an ``http``/
``https`` URL, in which case the file is downloaded to the sidecar's media
filename (once; later runs reuse the cached file). ``prep`` replaces the old
``.star_ignore_<stem>`` marker mechanism.

This module deliberately has no dependency on ``TextureEncoder`` or
``PrepareMedia``: the image-dependent defaulting (compress for images, copy
for everything else) lives in ``PrepareMedia``, which imports both. That keeps
the import graph acyclic, since ``TextureEncoder`` imports this module for
``Get_Prep``.
"""

import json
import os
import shutil
import tempfile
import urllib.parse
import urllib.request

PREP_COMPRESS = "compress"
PREP_COPY = "copy"

# Reserved suffix that distinguishes a sidecar from an ordinary .json file.
# The sidecar's media filename is its basename with this suffix removed:
# "logo.png.star.json" describes "logo.png".
SIDECAR_SUFFIX = ".star.json"

_KNOWN_KEYS = {"type", "source", "prep"}

# Absolute media path -> normalized sidecar info {"type", "source", "prep"}.
# Populated once per run by PrepareMedia.Resolve_Sidecars and queried by
# TextureCompressor.should_compress. Replaces the old per-file
# _should_compress_cache.
_registry = {}

# Count of download attempts that failed during this run; reported in the
# end-of-run summary so an incomplete build is visible even though the exit
# code is still 0.
_download_failures = 0


def Reset_Registry() -> None:
    """Clear per-run sidecar state. Call once at the start of a prep run."""
    global _download_failures
    _registry.clear()
    _download_failures = 0


def Register_Media(abs_media_path: str, info: dict) -> None:
    """Record how ``abs_media_path`` should be prepped for this run."""
    _registry[os.path.abspath(abs_media_path)] = info


def Get_Prep(abs_media_path: str) -> str:
    """Return the registered prep approach, defaulting to compress.

    The default matters for callers that run without a sidecar pre-pass: the
    routing layer still checks the extension (``Is_File_A_Image``), so a
    non-image ends up copied even though the raw default is "compress".
    """
    info = _registry.get(os.path.abspath(abs_media_path))
    if info is None:
        return PREP_COMPRESS
    return info.get("prep", PREP_COMPRESS)


def Is_Sidecar_File(path: str) -> bool:
    """True for sidecars: ``<media filename>.star.json`` (case-insensitive).

    Other ``.json`` files are ordinary media and are copied as-is.
    """
    base = os.path.basename(path)
    return base.lower().endswith(SIDECAR_SUFFIX) and len(base) > len(SIDECAR_SUFFIX)


def Is_Json_Data_File(path: str) -> bool:
    """True for an ordinary ``.json`` data file (not a ``.star.json`` sidecar).

    JSON files in the media tree are application data, not media assets: they
    are copied verbatim and never get an auto-generated sidecar, which would
    otherwise clutter every directory with ``<name>.json.star.json`` files.
    """
    if Is_Sidecar_File(path):
        return False
    return os.path.splitext(path)[1].lower() == ".json"


def Get_Media_Name_From_Sidecar(sidecar_path: str) -> str:
    """The media filename a sidecar describes (basename minus the suffix)."""
    base = os.path.basename(sidecar_path)
    return base[: -len(SIDECAR_SUFFIX)]


def Get_Sidecar_Path(media_path: str) -> str:
    """The sidecar path for a media file (adds ``.star.json``)."""
    return media_path + SIDECAR_SUFFIX


def Is_Hidden_File(path: str) -> bool:
    """True for dot-prefixed files (e.g. ``.star_ignore_*``, download temps)."""
    return os.path.basename(path).startswith(".")


def Is_URL_Source(source: str) -> bool:
    """True when ``source`` is an http/https URL rather than a local filename."""
    return source.lower().startswith(("http://", "https://"))


def _Read_Sidecar_Text(sidecar_path: str) -> str:
    """Decode a sidecar file, tolerating the BOMs Windows tools add.

    Sidecars are hand-edited, and PowerShell's ``Set-Content -Encoding utf8``
    writes a UTF-8 BOM while ``>``/``Out-File`` in PowerShell 5.1 write
    UTF-16LE. ``json.load`` on a plain utf-8 stream rejects both, so the file
    would otherwise be reported as malformed and silently ignored.
    """
    with open(sidecar_path, "rb") as f:
        raw = f.read()
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    return raw.decode("utf-8")


def Load_Sidecar(sidecar_path: str):
    """Read and parse a sidecar JSON file, returning None on any failure.

    A malformed sidecar is the user's file: warn and return None so callers
    fall back to in-memory defaults instead of overwriting it.
    """
    try:
        return json.loads(_Read_Sidecar_Text(sidecar_path))
    except (OSError, ValueError) as e:
        print(f"Warning: could not read sidecar {os.path.basename(sidecar_path)};")
        print(f"         using defaults for this run (file left unchanged).")
        print(f"         {e}")
        return None


def _Is_Valid_Local_Source(source: str) -> bool:
    """A local sidecar source must be a bare filename inside the sidecar's dir."""
    if not source or source in (".", ".."):
        return False
    # Reject both separators explicitly: on Windows "\" is a separator while on
    # POSIX the path helpers would not see it, so check both regardless.
    if "/" in source or "\\" in source:
        return False
    if os.path.isabs(source):
        return False
    # Windows drive-relative paths ("C:foo.png") and other colon forms.
    if len(source) >= 2 and source[1] == ":":
        return False
    return source == os.path.basename(source)


def Validate_Sidecar(data, sidecar_path: str):
    """Normalize a parsed sidecar dict, or return None if unusable.

    The media filename is taken from the sidecar's own name (the basename minus
    ``.star.json``). Applies the documented defaults (``source`` -> the media
    filename, ``prep`` -> compress), warns on unknown keys for forward
    compatibility, and rejects sidecars that could escape their directory or
    use a non-http(s) scheme.
    """
    name = os.path.basename(sidecar_path)
    media_name = Get_Media_Name_From_Sidecar(sidecar_path)
    if not isinstance(data, dict):
        print(f"Warning: sidecar {name} must contain a JSON object; using defaults.")
        return None

    for key in sorted(data.keys()):
        if key not in _KNOWN_KEYS:
            print(f"Warning: sidecar {name} has unknown key '{key}'; ignoring it.")

    media_ext = os.path.splitext(media_name)[1].lstrip(".").lower()

    raw_type = data.get("type")
    media_type = media_ext
    if raw_type is not None:
        if not isinstance(raw_type, str):
            print(
                f"Warning: sidecar {name} has a non-string 'type'; using the "
                f"media filename's extension."
            )
        else:
            stripped = raw_type.strip().lstrip(".").lower()
            if stripped:
                media_type = stripped

    raw_source = data.get("source")
    source = None
    if raw_source is not None:
        if not isinstance(raw_source, str):
            print(f"Warning: sidecar {name} has a non-string 'source'; using defaults.")
            return None
        stripped = raw_source.strip()
        if stripped:
            source = stripped

    if source is not None:
        if Is_URL_Source(source):
            scheme = urllib.parse.urlsplit(source).scheme.lower()
            if scheme not in ("http", "https"):
                print(
                    f"Warning: sidecar {name} uses unsupported URL scheme "
                    f"'{scheme}'; ignoring sidecar."
                )
                return None
        elif "://" in source:
            print(
                f"Warning: sidecar {name} uses an unsupported URL scheme "
                f"'{source}'; ignoring sidecar."
            )
            return None
        elif not _Is_Valid_Local_Source(source):
            print(
                f"Warning: sidecar {name} source must be a bare filename in the "
                f"same directory, got '{source}'; ignoring sidecar."
            )
            return None

    if source is None:
        source = media_name

    raw_prep = data.get("prep")
    if raw_prep is None:
        prep = PREP_COMPRESS
    elif isinstance(raw_prep, str) and raw_prep.strip().lower() in (
        PREP_COMPRESS,
        PREP_COPY,
    ):
        prep = raw_prep.strip().lower()
    else:
        print(
            f"Warning: sidecar {name} has invalid prep {raw_prep!r}; "
            f"defaulting to '{PREP_COMPRESS}'."
        )
        prep = PREP_COMPRESS

    return {"type": media_type, "source": source, "prep": prep}


def Write_Default_Sidecar(path: str, type: str, source: str, prep: str) -> bool:
    """Write a default sidecar next to a media file. Returns success."""
    payload = {"type": type, "source": source, "prep": prep}
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
            f.write("\n")
    except OSError as e:
        print(f"Warning: could not write sidecar {os.path.basename(path)}:")
        print(e)
        return False
    print(f"Generated sidecar: {os.path.basename(path)}")
    return True


def Get_Download_Failure_Count() -> int:
    return _download_failures


def Download_Media_File(url: str, target_path: str, timeout: int = 60) -> bool:
    """Download ``url`` to ``target_path`` atomically. Returns success.

    The body is streamed into a dot-prefixed temp file in the target directory
    (invisible to the media walker) and only renamed into place after the
    transfer completes, so an interrupted download never leaves a partial
    file that looks like real media.
    """
    global _download_failures

    scheme = urllib.parse.urlsplit(url).scheme.lower()
    if scheme not in ("http", "https"):
        print(f"Warning: unsupported URL scheme, skipping download: {url}")
        _download_failures += 1
        return False

    target_dir = os.path.dirname(os.path.abspath(target_path))
    tmp_fd = None
    tmp_path = None
    try:
        os.makedirs(target_dir, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "StarlightAppBuilder"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            tmp_fd, tmp_path = tempfile.mkstemp(prefix=".download_", dir=target_dir)
            try:
                out = os.fdopen(tmp_fd, "wb")
            except Exception:
                os.close(tmp_fd)
                tmp_fd = None
                raise
            tmp_fd = None
            with out:
                shutil.copyfileobj(resp, out)
        os.replace(tmp_path, target_path)
        tmp_path = None
        return True
    except Exception as e:
        if tmp_fd is not None:
            try:
                os.close(tmp_fd)
            except OSError:
                pass
        if tmp_path is not None:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        print(f"Warning: download failed for {target_path} from {url}")
        print(e)
        _download_failures += 1
        return False
