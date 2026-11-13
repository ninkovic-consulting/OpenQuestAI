"""Images the owner sends: what is accepted, the clean copy kept, the store and its routes."""

from __future__ import annotations

import stat
from pathlib import Path

import pytest
from settings_fakes import client
from image_fixtures import GIF_1PX, bomb, SECRET, WEBP_1PX, app_segments, jpeg, jpeg_with_location, png

from vision.app import Daemon
from vision.attachments import clean, imageio
from vision.attachments.clean import ImageRefused, sniff
from vision.attachments.store import ImageStore, NoSuchImage

# ---------------------------------------------------------------- what is accepted




@pytest.mark.parametrize(
    ("data", "kind"),
    [
        (png(2, 2), "image/png"),
        (jpeg(), "image/jpeg"),
        (GIF_1PX, "image/gif"),
        (WEBP_1PX, "image/webp"),
        (b"%PDF-1.7\n", None),
        (b"<html><script>alert(1)</script>", None),
        (b"RIFF\x00\x00\x00\x00WAVEfmt ", None),
        (b"", None),
    ],
)
def test_the_type_comes_from_the_first_bytes(data: bytes, kind: str | None) -> None:
    assert sniff(data) == kind


@pytest.mark.parametrize("data", [png(3, 2), jpeg(), GIF_1PX, WEBP_1PX])
def test_each_accepted_type_is_cleaned(data: bytes) -> None:
    out = clean.clean(data)
    assert out.media_type == ("image/jpeg" if sniff(data) == "image/jpeg" else "image/png")
    assert sniff(out.data) == out.media_type
    assert out.width >= 1 and out.height >= 1


def test_a_renamed_text_file_is_refused() -> None:
    with pytest.raises(ImageRefused, match="not a PNG, JPEG, GIF or WebP"):
        clean.clean(b"Dear diary, this file is called holiday.png but it is text.")


def test_an_image_type_that_is_not_accepted_is_refused() -> None:
    bmp = b"BM" + b"\x00" * 60
    with pytest.raises(ImageRefused, match="not a PNG, JPEG, GIF or WebP"):
        clean.clean(bmp)


def test_magic_bytes_on_garbage_are_refused_as_unreadable() -> None:
    with pytest.raises(ImageRefused, match="could not be read"):
        clean.clean(b"GIF89a<html><body>not a picture</body></html>")


def test_bytes_that_say_one_type_and_hold_another_are_refused() -> None:
    disguised = b"RIFF\x00\x00\x00\x00WEBP" + png(2, 2)
    with pytest.raises(ImageRefused):
        clean.clean(disguised)


def test_a_polyglot_keeps_only_its_pixels() -> None:
    payload = b"<script>alert('owned')</script>PK\x03\x04hidden.zip"
    out = clean.clean(png(8, 8) + payload)
    assert b"script" not in out.data and b"PK\x03\x04" not in out.data
    assert out.data.endswith(b"IEND\xaeB`\x82")


def test_an_empty_file_is_refused() -> None:
    with pytest.raises(ImageRefused, match="empty"):
        clean.clean(b"")


def test_a_file_over_the_size_cap_is_refused() -> None:
    with pytest.raises(ImageRefused, match="larger than 15 MB"):
        clean.clean(png(1, 1) + b"\x00" * clean.MAX_BYTES)


def test_too_many_pixels_is_refused_before_decoding() -> None:
    assert len(bomb()) < 200_000
    with pytest.raises(ImageRefused, match="more than 50 megapixels"):
        clean.clean(bomb())


def test_a_large_image_is_scaled_to_the_long_edge() -> None:
    out = clean.clean(png(3000, 200))
    assert (out.width, out.height) == (1568, 105)


def test_a_small_image_is_not_scaled_up() -> None:
    out = clean.clean(png(300, 120))
    assert (out.width, out.height) == (300, 120)


def test_location_and_other_metadata_are_stripped() -> None:
    original = jpeg_with_location()
    assert SECRET in original
    out = clean.clean(original)
    assert out.media_type == "image/jpeg"
    assert SECRET not in out.data
    for segment in app_segments(out.data):
        assert b"\x88\x25" not in segment, "a GPS IFD pointer survived"
    assert (out.width, out.height) == (40, 30)


def test_limits_for_the_window() -> None:
    assert clean.limits() == {
        "types": ["image/png", "image/jpeg", "image/gif", "image/webp"],
        "max_bytes": 15 * 1024 * 1024,
        "max_pixels": 50_000_000,
        "max_per_message": 6,
        "long_edge": 1568,
    }


def test_a_noisy_png_too_heavy_as_png_is_kept_as_jpeg(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(clean, "MAX_PNG_BYTES", 10)
    out = clean.clean(png(50, 50))
    assert out.media_type == "image/jpeg" and sniff(out.data) == "image/jpeg"


def test_the_header_is_read_without_decoding() -> None:
    header = imageio.probe(bomb())
    assert (header.uti, header.width, header.height) == ("public.png", 10_000, 6_000)


# ---------------------------------------------------------------- the store


def test_the_store_keeps_a_private_clean_copy(tmp_path: Path) -> None:
    store = ImageStore(tmp_path / "images")
    picture = store.add(jpeg_with_location())
    folder = tmp_path / "images"
    (file,) = folder.iterdir()
    assert file.name == f"{picture.id}.jpg"
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700
    assert stat.S_IMODE(file.stat().st_mode) == 0o600
    assert SECRET not in file.read_bytes()
    again = store.get(picture.id)
    assert again == picture and again.ref.width == 40


def test_the_store_refuses_names_that_are_not_ids(tmp_path: Path) -> None:
    store = ImageStore(tmp_path / "images")
    store.add(png(2, 2))
    for bad in ("../token", "x" * 32, "", "A" * 32):
        with pytest.raises(NoSuchImage):
            store.get(bad)


def test_an_image_can_be_deleted(tmp_path: Path) -> None:
    store = ImageStore(tmp_path / "images")
    picture = store.add(png(2, 2))
    store.remove(picture.id)
    with pytest.raises(NoSuchImage):
        store.get(picture.id)
    with pytest.raises(NoSuchImage):
        store.remove(picture.id)


def test_a_refused_image_leaves_nothing_behind(tmp_path: Path) -> None:
    store = ImageStore(tmp_path / "images")
    with pytest.raises(ImageRefused):
        store.add(b"not an image")
    assert not (tmp_path / "images").exists() or not any((tmp_path / "images").iterdir())


# ---------------------------------------------------------------- the routes


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/images/limits"),
        ("POST", "/api/images"),
        ("GET", f"/api/images/{'a' * 32}"),
        ("DELETE", f"/api/images/{'a' * 32}"),
    ],
)
async def test_every_route_needs_the_token(daemon: Daemon, method: str, path: str) -> None:
    async with client(daemon, token=False) as http:
        assert (await http.request(method, path, content=png(2, 2) if method == "POST" else None)).status_code == 401
    assert not daemon.config.paths.images.exists()


async def test_upload_get_and_delete(daemon: Daemon) -> None:
    async with client(daemon) as http:
        sent = await http.post("/api/images", content=png(3000, 200), headers={"content-type": "text/plain"})
        assert sent.status_code == 200
        image = sent.json()["image"]
        assert image["media_type"] == "image/png" and (image["width"], image["height"]) == (1568, 105)
        assert (daemon.config.paths.images / f"{image['id']}.png").is_file()
        got = await http.get(f"/api/images/{image['id']}")
        assert got.status_code == 200 and got.headers["content-type"] == "image/png"
        assert got.headers["x-content-type-options"] == "nosniff"
        assert "sandbox" in got.headers["content-security-policy"]
        assert len(got.content) == image["bytes"]
        assert (await http.delete(f"/api/images/{image['id']}")).json() == {"removed": True}
        assert (await http.get(f"/api/images/{image['id']}")).status_code == 404
        assert (await http.delete(f"/api/images/{image['id']}")).status_code == 404


async def test_a_refusal_is_a_plain_400(daemon: Daemon) -> None:
    async with client(daemon) as http:
        answer = await http.post("/api/images", content=b"just words", headers={"content-type": "image/png"})
    assert answer.status_code == 400
    assert answer.json() == {"detail": "That file is not a PNG, JPEG, GIF or WebP image."}


async def test_a_body_over_the_cap_is_refused(daemon: Daemon) -> None:
    async with client(daemon) as http:
        answer = await http.post("/api/images", content=b"\x89PNG" + b"\x00" * (clean.MAX_BYTES + 1))
    assert answer.status_code == 400 and "15 MB" in answer.json()["detail"]


async def test_limits_route(daemon: Daemon) -> None:
    async with client(daemon) as http:
        assert (await http.get("/api/images/limits")).json() == {"limits": clean.limits()}
