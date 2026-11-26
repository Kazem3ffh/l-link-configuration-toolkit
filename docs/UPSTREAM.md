# Upstream service notes

This document describes the one external service the toolkit depends on. It is kept separate from the README on purpose: the README describes the toolkit, this file records the technical facts and the legal position of the dependency.

## What the upstream is

The toolkit obtains its source configuration from a public service operated by the **Lantern** project (https://lantern.io). Lantern publishes a client application whose open-source backend asks this service for a list of free proxies.

- This project is **not affiliated with, endorsed by or sponsored by** the Lantern project or its operators.
- The service is used the way its own client uses it, with an anonymous free account. No paid or private features are used.
- The service is not a documented public API. The interface described below was learned from the public client source code (read for interface facts only, no code was copied) and from observing real responses. It can change without notice and the toolkit can stop working when it does.
- The service's terms of service were not reviewed for this project. Whoever runs the toolkit is responsible for checking that their use is allowed.

## Endpoints

| Purpose | Request |
| --- | --- |
| Create an anonymous account | `POST https://api.getiantem.org/user-create`, headers only, no body |
| Fetch the proxy configuration | `POST https://df.iantem.io/api/v1/config-new`, JSON body |

The account request returns a JSON object with `userId` and `token`. The configuration response is a JSON object whose `options.outbounds` list holds the proxies (sing-box outbound objects), `outbound_locations` maps an outbound tag to its country and city, and `country` is the country the server answered for.

## What the toolkit sends

Headers on both requests:

| Header | Value |
| --- | --- |
| `X-Lantern-App` | `lantern` |
| `X-Lantern-App-Version` and `X-Lantern-Version` | the app version set in `l_toolkit/upstream.py` |
| `X-Lantern-Platform` | `linux` |
| `X-Lantern-Time-Zone` | an IANA zone name (default `Asia/Tehran`, can be disabled), sent by the official client as well |
| `X-Lantern-Device-Id` | a random UUID created once per installation |
| `X-Lantern-Rand` | random lowercase letters, up to 299 characters, as the official client does |
| `X-Lantern-Client-Country` | `IR` (can be disabled) |
| `X-Lantern-User-Id` | only on the configuration request |

JSON body of the configuration request: `device_id`, `singbox_version` (set in `l_toolkit/upstream.py`), `platform`, `app_name`, `user_id`, `pro_token`, `backend` (`sing-box`), `locale` (`en-US`) `protocols` (`shadowsocks`, `vless`, `hysteria2x`) and, only when the list in `l_toolkit/upstream.py` is not empty, `capabilities`.

Where the values come from:

- Every value that identifies the toolkit to the upstream lives in one file, `l_toolkit/upstream.py`: the app version, the sing-box version, the platform, the locale, the time zone, the protocol list and the capability list. A version change is a one-line edit there. The app version follows the latest official release and the sing-box version is what the official client reports for its sing-box dependency. They can also be changed for a single run with `L_UPSTREAM_APP_VERSION` and `L_UPSTREAM_SINGBOX_VERSION`.
- `protocols` lists only what the toolkit can publish. The official client also sends only the protocols it supports, and the server leaves out entries a client does not support.
- No `preferred_location` is ever sent. In the official client that field is the exit country a user chooses; it is unrelated to the client country.
- The capability list is empty on purpose. A capability tells the server that the client can handle an extra feature, and the toolkit implements none of them, so none is claimed. The official client sends several; adding one is a one-line edit of `ADVERTISED_CAPABILITIES` in `l_toolkit/upstream.py`.
- `X-Lantern-Client-Country` is, in the official client, a developer override and not a documented production feature. The server has accepted it so far (its answers report the country that was requested), but that can change. Setting `L_CLIENT_COUNTRY` to an empty value stops the header from being sent.

## Request behaviour

- The configuration request is read-only in the official client and may be retried; the toolkit retries it up to three times with growing waits and honours `Retry-After` (a value above 120 seconds stops the run).
- Account creation is never retried, because a repeated request could create a second account.
- The toolkit never creates an account by itself after a rejection; an operator must start that step manually.

## Data the toolkit keeps

Only the device id, the user id and the token of the anonymous account, in one encrypted file (AES-256-GCM, key in a repository secret). They are never written to the published files or to logs.

## Where the upstream name appears in this repository

Only here, in `l_toolkit/upstream.py` (the wire constants), in `THIRD_PARTY_NOTICES.md` and in `tests/test_upstream_wire.py` (tests that pin the wire format). A repository test enforces this.
