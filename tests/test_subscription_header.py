import base64
import json

import pytest

from l_toolkit import constants as C
from l_toolkit.errors import ValidationError
from l_toolkit.guard import ensure_no_state_in_files
from l_toolkit.links import render_subscription, split_subscription
from l_toolkit.pipeline import run
from l_toolkit.state import State

EXPECTED_HEADER = [
    "//profile-title: base64:8J+RvSBBbm9ueW1vdXMgTCDwn5qA",
    "//profile-update-interval: 1",
    "//subscription-userinfo: upload=0; download=0; total=10737418240000000; expire=2546249531",
    "//support-url: https://t.me/An0nymou3Bot",
    "//profile-web-page-url: https://github.com/4n0nymou3",
]
LINKS = ["ss://AAA@192.0.2.1:443#one", "vless://u@192.0.2.2:443?security=none#two"]


def test_the_header_is_exactly_the_requested_five_lines():
    assert list(C.SUBSCRIPTION_HEADER) == EXPECTED_HEADER


def test_the_profile_title_is_the_base64_of_the_profile_name():
    encoded = EXPECTED_HEADER[0].split("base64:", 1)[1]
    assert base64.b64decode(encoded).decode("utf-8") == C.PROFILE_NAME == "\U0001F47D Anonymous L \U0001F680"


def test_the_file_is_the_header_one_blank_line_and_then_the_links():
    text = render_subscription(LINKS).decode("utf-8")
    assert text == "\n".join(EXPECTED_HEADER) + "\n\n" + "\n".join(LINKS) + "\n"
    assert text.splitlines()[:5] == EXPECTED_HEADER
    assert text.splitlines()[5] == ""
    assert text.splitlines()[6:] == LINKS


def test_the_header_is_always_the_first_thing_in_the_file():
    for links in ([], LINKS[:1], LINKS):
        assert render_subscription(links).decode("utf-8").startswith(EXPECTED_HEADER[0] + "\n")


def test_without_links_the_file_is_the_header_only():
    text = render_subscription([]).decode("utf-8")
    assert text == "\n".join(EXPECTED_HEADER) + "\n"
    assert "\n\n" not in text


def test_the_output_uses_plain_newlines_and_ends_with_exactly_one():
    for links in ([], LINKS):
        data = render_subscription(links)
        assert b"\r" not in data and data.endswith(b"\n") and not data.endswith(b"\n\n")


def test_the_output_is_identical_every_time():
    assert render_subscription(LINKS) == render_subscription(list(LINKS))


def test_split_returns_the_header_and_the_links():
    assert split_subscription(render_subscription(LINKS)) == (EXPECTED_HEADER, LINKS)
    assert split_subscription(render_subscription([])) == (EXPECTED_HEADER, [])


@pytest.mark.parametrize(
    "content",
    [
        b"",
        b"ss://AAA@192.0.2.1:443#one\n",
        ("\n".join(EXPECTED_HEADER[1:]) + "\n\nss://a\n").encode(),
        ("\n".join(EXPECTED_HEADER) + "\nss://a\n").encode(),
        ("\n".join(EXPECTED_HEADER) + "\n\n\nss://a\n").encode(),
        ("\n".join(EXPECTED_HEADER) + "\n\nss://a\n\nvless://b\n").encode(),
        ("\n".join(EXPECTED_HEADER) + "\n\nss://a\n//extra: comment\n").encode(),
        ("\n".join(EXPECTED_HEADER) + "\n\nss://a").encode(),
        ("\r\n".join(EXPECTED_HEADER) + "\r\n\r\nss://a\r\n").encode(),
        ("\n".join(EXPECTED_HEADER[:-1] + ["//profile-web-page-url: https://example.com"]) + "\n\nss://a\n").encode(),
        ("\n".join(EXPECTED_HEADER + ["//extra-header: 1"]) + "\n\nss://a\n").encode(),
        b"\xff\xfe\n",
    ],
)
def test_a_file_that_deviates_from_the_format_is_rejected(content):
    with pytest.raises(ValidationError):
        split_subscription(content)


def test_the_header_lines_are_not_mistaken_for_account_data():
    state = State("6f1c1f0e-0b0a-4c63-9d2c-4a7d1f2f3a11", 1, "a-long-account-token")
    ensure_no_state_in_files({"sub.txt": render_subscription(LINKS)}, state)
    ensure_no_state_in_files({"sub.txt": render_subscription([])}, State(state.device_id, 10737418240000000, "x" * 12))


def test_the_published_file_of_a_real_run_has_the_header_first(make_session, make_client, tmp_path, key):
    run(
        make_client(make_session()),
        tmp_path / "state" / "s.enc",
        tmp_path / "out",
        key,
        bootstrap="create",
        hysteria2_links="include",
    )
    data = (tmp_path / "out" / "sub.txt").read_bytes()
    header, links = split_subscription(data)
    assert header == EXPECTED_HEADER
    assert [link.split("://")[0] for link in links] == ["ss", "vless", "hysteria2"]
    assert data.decode("utf-8").startswith("//profile-title: base64:")


def test_the_two_json_outputs_do_not_get_a_header(make_session, make_client, tmp_path, key):
    run(make_client(make_session()), tmp_path / "state" / "s.enc", tmp_path / "out", key, bootstrap="create")
    for name in ("singbox.json", "xray.json"):
        content = (tmp_path / "out" / name).read_text(encoding="utf-8")
        assert content.startswith("{") and "profile-title" not in content
        json.loads(content)
