import json

import pytest

from l_toolkit import upstream as U

from helpers import fresh_state

DEVICE = "6f1c1f0e-0b0a-4c63-9d2c-4a7d1f2f3a11"


def user_state():
    return fresh_state().with_user(9, "tok-value")


def test_account_creation_request_matches_the_upstream_wire_format(make_session, make_client):
    session = make_session()
    make_client(session, country="IR").create_account(DEVICE)
    call = session.calls[0]
    assert call["url"] == "https://api.getiantem.org/user-create"
    assert call["data"] is None
    headers = call["headers"]
    assert headers["X-Lantern-Device-Id"] == DEVICE
    assert headers["X-Lantern-App"] == "lantern"
    assert headers["X-Lantern-App-Version"] == U.DEFAULT_APP_VERSION
    assert headers["X-Lantern-Version"] == U.DEFAULT_APP_VERSION
    assert headers["X-Lantern-Platform"] == "linux"
    assert headers["X-Lantern-Time-Zone"] == U.DEFAULT_TIME_ZONE
    assert headers["X-Lantern-Client-Country"] == "IR"
    assert len(headers["X-Lantern-Rand"]) < 300
    assert "X-Lantern-User-Id" not in headers and "X-Lantern-Pro-Token" not in headers
    assert headers["User-Agent"].startswith("l-link-configuration-toolkit/")


def test_configuration_request_matches_the_upstream_wire_format(make_session, make_client):
    session = make_session()
    state = user_state()
    make_client(session, country="IR").fetch_config(state)
    call = session.calls[0]
    assert call["url"] == "https://df.iantem.io/api/v1/config-new"
    headers = call["headers"]
    assert headers["X-Lantern-User-Id"] == "9"
    assert headers["X-Lantern-Device-Id"] == state.device_id
    assert headers["X-Lantern-Time-Zone"] == U.DEFAULT_TIME_ZONE
    assert headers["X-Lantern-Client-Country"] == "IR"
    assert headers["Content-Type"] == "application/json"
    assert "X-Lantern-Pro-Token" not in headers
    body = json.loads(call["data"])
    assert body == {
        "device_id": state.device_id,
        "singbox_version": U.DEFAULT_SINGBOX_VERSION,
        "platform": "linux",
        "app_name": "lantern",
        "user_id": "9",
        "pro_token": "tok-value",
        "backend": "sing-box",
        "locale": "en-US",
        "protocols": list(U.ADVERTISED_PROTOCOLS),
    }
    assert call["timeout"] == (15, 45)


def test_no_preferred_location_is_ever_sent(make_session, make_client):
    session = make_session()
    make_client(session).fetch_config(user_state())
    body = json.loads(session.calls[0]["data"])
    assert "preferred_location" not in body


def test_capabilities_are_sent_only_when_the_central_list_is_not_empty(make_session, make_client, monkeypatch):
    session = make_session()
    make_client(session).fetch_config(user_state())
    assert ("capabilities" in json.loads(session.calls[0]["data"])) == bool(U.ADVERTISED_CAPABILITIES)
    monkeypatch.setattr(U, "ADVERTISED_CAPABILITIES", ("alpha", "beta"))
    session = make_session()
    make_client(session).fetch_config(user_state())
    assert json.loads(session.calls[0]["data"])["capabilities"] == ["alpha", "beta"]
    monkeypatch.setattr(U, "ADVERTISED_CAPABILITIES", ())
    session = make_session()
    make_client(session).fetch_config(user_state())
    assert "capabilities" not in json.loads(session.calls[0]["data"])


def test_time_zone_header_can_be_disabled_or_changed(make_session, make_client):
    session = make_session()
    make_client(session, time_zone="").create_account(DEVICE)
    assert "X-Lantern-Time-Zone" not in session.calls[0]["headers"]
    session = make_session()
    make_client(session, time_zone="Europe/Berlin").create_account(DEVICE)
    assert session.calls[0]["headers"]["X-Lantern-Time-Zone"] == "Europe/Berlin"


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"userId": 7, "token": "abc"}, (7, "abc")),
        ({"userId": 7, "token": "abc", "userLevel": "free"}, (7, "abc")),
    ],
)
def test_the_account_response_fields_are_user_id_and_token(make_session, make_client, payload, expected):
    assert make_client(make_session(user=payload)).create_account(DEVICE) == expected


@pytest.mark.parametrize("payload", [{"user_id": 7, "token": "abc"}, {"userId": 7, "pro_token": "abc"}])
def test_other_spellings_of_the_account_fields_are_not_accepted(make_session, make_client, payload):
    from l_toolkit.errors import ApiError

    with pytest.raises(ApiError):
        make_client(make_session(user=payload)).create_account(DEVICE)
