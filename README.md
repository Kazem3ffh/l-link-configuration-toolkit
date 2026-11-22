# L — Link Configuration Toolkit

[![Tests](https://github.com/4n0nymou3/l-link-configuration-toolkit/actions/workflows/tests.yml/badge.svg)](https://github.com/4n0nymou3/l-link-configuration-toolkit/actions/workflows/tests.yml)

L is a small Python toolkit that fetches a free proxy configuration from an upstream service, keeps only the entries that mainstream clients can use, and publishes them as three ready-to-import files from a GitHub repository. It runs on GitHub Actions once an hour and commits only when something changed.

Maintained by [4n0nymou3](https://github.com/4n0nymou3).

## Overview

The toolkit asks the upstream service (described in [docs/UPSTREAM.md](docs/UPSTREAM.md)) for its current proxy list, validates every entry strictly, removes exact duplicates and writes:

- a plain share-link list for link based clients,
- a complete sing-box client profile,
- a complete Xray-core client configuration.

If anything goes wrong, the previously published files stay exactly as they were.

## Features

- Strict validation: malformed, unsupported or unsafe entries are skipped with a reason, never silently rewritten.
- Exact duplicate detection that compares every parameter that affects a connection.
- Account data stored in one encrypted file (AES-256-GCM); the key lives only in a repository secret.
- Atomic publishing: all three files are staged first and replaced together, with rollback.
- Hysteria2 certificates parsed, checked and pinned; Hysteria2 links are opt-in because some clients ignore the pin.
- Iranian traffic routed directly in the sing-box and Xray outputs.
- Tests that run the real Xray-core, sing-box and Hiddify core in CI, with pinned, checksum-verified downloads.
- Pinned GitHub Actions (full commit hashes) and least-privilege workflow permissions.

## How It Works

1. A device id and an anonymous account are created once (manually, see [Fork and Setup](#fork-and-setup)) and stored encrypted in `state/upstream-account.enc`.
2. Every hour the workflow decrypts the state in memory, asks the upstream service for the configuration (read-only request, retried safely) and parses the response.
3. Each outbound is normalised and validated. Unsupported types, unknown options, expired certificates, plain-text VLESS on public addresses and exact duplicates are skipped with a counted reason.
4. Share links, the sing-box profile and the Xray configuration are built and checked against each other (links are decoded back and compared with the source data).
5. A guard refuses to publish if any account data would end up in a file.
6. The three files are written atomically; the workflow commits them only if the content changed.

## Supported Protocols and Formats

| Protocol | `sub.txt` | `singbox.json` | `xray.json` |
| --- | --- | --- | --- |
| Shadowsocks (2022 and AEAD ciphers) | yes | yes | yes |
| VLESS over TCP with TLS or Reality, including `xtls-rprx-vision` | yes | yes | yes |
| Hysteria2 | no, unless enabled (see [Security](#security)) | yes, certificate verified | yes, certificate pinned |

Entries of any other type, and entries with options the toolkit cannot express faithfully, are skipped. Every run prints how many entries were extracted, duplicated, invalid, unsupported or ignored; the counts add up to the total.

## Repository Structure

```
.
├── .github/workflows/
│   ├── update-subscription.yml   hourly update and manual start
│   └── tests.yml                 offline tests and real-core tests
├── docs/
│   └── UPSTREAM.md               technical notes about the upstream service
├── l_toolkit/
│   ├── upstream.py               every upstream-specific constant (URLs, headers, versions)
│   ├── client.py                 HTTP client with the retry rules
│   ├── state.py                  AES-256-GCM encrypted account state
│   ├── extract.py                parsing, validation, normalisation, duplicate detection
│   ├── links.py                  share links and their validation
│   ├── singbox.py                sing-box profile builder
│   ├── xray.py                   Xray configuration builder
│   ├── guard.py                  refuses to publish account data
│   ├── output.py                 atomic multi-file writer with rollback
│   ├── pipeline.py               the update procedure
│   ├── constants.py, errors.py, __main__.py, __init__.py
├── tests/                        offline tests, wire-format tests, real-core tests
├── tools/
│   ├── cores.lock.json           pinned versions and SHA-256 hashes of the test tools
│   └── fetch_cores.py            checksum-verifying downloader
├── LICENSE
├── THIRD_PARTY_NOTICES.md
├── requirements.txt
├── requirements-dev.txt
└── pytest.ini
```

The folders `state/` and `subscription/` are created by the first successful run.

## Requirements

- A GitHub account (Actions enabled).
- Python 3.12 (used by the workflows); the packages in `requirements.txt` (`requests`, `cryptography`).
- Only for running the real-core tests locally: the Xray-core, sing-box and Hiddify core binaries (the test workflow downloads them for you).

## Running Locally

```
python -m pip install -r requirements.txt
python -m l_toolkit --generate-key                      # prints a new encryption key
export L_STATE_ENCRYPTION_KEY="<the printed key>"
python -m l_toolkit --bootstrap create                  # first run: creates the account, writes state/ and subscription/
python -m l_toolkit                                     # later runs
python -m l_toolkit --help                              # every flag
```

A local run contacts the upstream service for real and writes `state/upstream-account.enc` and `subscription/` in the current directory. Use a different key and state file for local experiments than for the repository. The tests do not need any of this; see [Testing](#testing).

## Fork and Setup

1. **Fork** the repository, or create your own copy. In a fork, open the **Actions** tab and enable workflows (GitHub keeps scheduled workflows off in forks until you do).
2. **Create the encryption key** on any computer that has Python: install the requirements, then run `python -m l_toolkit --generate-key`. It prints one line; copy it. `openssl rand -base64 32` works too. Never commit it or share it.
3. **Add the secret**: *Settings → Secrets and variables → Actions → New repository secret*. Name it exactly `L_STATE_ENCRYPTION_KEY` and paste the key.
4. **Allow the workflow to save files**: *Settings → Actions → General → Workflow permissions → Read and write permissions → Save*.
5. **First start**: open *Actions → Update Subscription → Run workflow*, choose `create`, and run it. This creates one anonymous account and stores it encrypted.
6. **Check**: the run is green; the repository now contains `state/upstream-account.enc` and `subscription/sub.txt`, `subscription/singbox.json` and `subscription/xray.json`. After that the hourly schedule needs no attention.
7. **Optional**: to also publish Hysteria2 links in `sub.txt`, add a repository **variable** (not a secret) named `L_HYSTERIA2_LINKS` with the value `include`, and read the security note first.

Recovery options of the manual run (*Run workflow → bootstrap*):

| Value | Meaning |
| --- | --- |
| `none` | Normal run (the default, also used by the schedule). |
| `create` | First setup. Refuses to run if an encrypted state already exists. |
| `recreate` | Replaces the account on purpose, for example after the upstream rejected it or after you changed the key. |

## GitHub Actions

| Workflow | File | Runs on | Purpose |
| --- | --- | --- | --- |
| Update Subscription | `.github/workflows/update-subscription.yml` | schedule and manual start | Builds the outputs and commits them. |
| Tests | `.github/workflows/tests.yml` | push to `main`, pull requests, manual start | Offline tests and real-core tests. |

**Schedule.** The update runs every hour at minute 23 (UTC) (`cron: "23 * * * *"`). GitHub may start a scheduled run late, or skip one under load. Runs never overlap and a running update is never cancelled by a newer one. A failed run does not start another one.

**Manual run.** *Actions → Update Subscription → Run workflow*. The `bootstrap` input is `none` for a normal run, `create` for the first setup and `recreate` to replace the account on purpose.

**Permissions.** The update job has `contents: write` (to commit the outputs) and nothing else; the workflow default is no permissions. The test workflow has `contents: read` only. Pull request workflows get no secrets, and the test workflow does not reference any.

**Secrets and variables.**

| Name | Kind | Needed | Meaning |
| --- | --- | --- | --- |
| `L_STATE_ENCRYPTION_KEY` | repository secret | yes | The key that encrypts the account state. The value is never printed. |
| `L_HYSTERIA2_LINKS` | repository variable | no | `include` adds Hysteria2 links to `sub.txt` (see [Security](#security)). |

No other secret is needed; the commit uses the workflow's own temporary token.

## Configuration

Only the first three are passed by the workflow; the rest are for local runs.

| Variable | Flag | Default | Meaning |
| --- | --- | --- | --- |
| `L_STATE_ENCRYPTION_KEY` (secret) | none | none, required | Base64 key of exactly 32 random bytes. |
| `L_BOOTSTRAP` | `--bootstrap` | `none` | `none`, `create` or `recreate`. |
| `L_HYSTERIA2_LINKS` (variable) | `--hysteria2-links` | `omit` | `include` adds Hysteria2 to `sub.txt`. |
| `L_CLIENT_COUNTRY` | `--country` | `IR` | Client country sent to the upstream, empty disables it. |
| `L_MIN_CONFIGS` | `--min-configs` | `1` | Minimum usable configs required to publish. |
| `L_UPSTREAM_APP_VERSION` | `--app-version` | see `l_toolkit/upstream.py` | App version reported to the upstream. |
| `L_UPSTREAM_SINGBOX_VERSION` | `--singbox-version` | see `l_toolkit/upstream.py` | sing-box version reported to the upstream. |
| `L_OUTPUT_DIR` | `--output-dir` | `subscription` | Output directory. |
| `L_STATE_FILE` | `--state-file` | `state/upstream-account.enc` | Encrypted state file. |

## Usage

The files are published at:

```
https://raw.githubusercontent.com/4n0nymou3/l-link-configuration-toolkit/main/subscription/sub.txt
https://raw.githubusercontent.com/4n0nymou3/l-link-configuration-toolkit/main/subscription/singbox.json
https://raw.githubusercontent.com/4n0nymou3/l-link-configuration-toolkit/main/subscription/xray.json
```

In a fork replace the user and repository name with yours. Add the address as a subscription or remote profile in your client:

- `sub.txt`: link based clients and Hiddify (Shadowsocks and VLESS).
- `singbox.json`: sing-box apps and Hiddify (JSON profile).
- `xray.json`: Xray-core and clients that accept a full Xray configuration.

Names inside the files follow the TCB style: the Xray `remarks` and the sing-box selector are `👽 Anonymous L 🚀`, the automatic latency group is `👽 Anonymous L 🌐`, and every link carries its own name such as `🇩🇪 Germany · Frankfurt · SS`. Hiddify names a remote profile from its URL, so add `#👽 Anonymous L 🚀` to the end of the address there.

## Output Files

| File | Content |
| --- | --- |
| `subscription/sub.txt` | A fixed profile header, one blank line, then one share link per line (`ss://`, `vless://`, and `hysteria2://` only if enabled). |
| `subscription/singbox.json` | Complete sing-box client profile: TUN inbound, DNS, routing rules, a selector and an automatic latency group. |
| `subscription/xray.json` | Complete Xray client configuration: SOCKS (10808) and HTTP (10809) inbounds, a latency based balancer. |
| `state/upstream-account.enc` | Encrypted account state. Not a client file. |

**The `sub.txt` header.** The file always starts with the same five lines, then one blank line, then the links:
```
//profile-title: base64:8J+RvSBBbm9ueW1vdXMgTCDwn5qA
//profile-update-interval: 1
//subscription-userinfo: upload=0; download=0; total=10737418240000000; expire=2546249531
//support-url: https://t.me/An0nymou3Bot
//profile-web-page-url: https://github.com/4n0nymou3

ss://...
vless://...
```

The title is the base64 of `👽 Anonymous L 🚀`, the update interval is in hours, and the `subscription-userinfo` values are static presentation data, not a real quota. The header is built from constants, so it is identical on every run. A strict check refuses to publish a file whose header, blank line or links deviate from this format.

How clients treat it (read from their source code): Hiddify core reads lines that start with `//` or `#` among the first 30 lines of a subscription as profile metadata (title, update interval, subscription info; the support and web page addresses are only used together with `subscription-userinfo`), and v2rayNG skips every line that is not a known link. Tested with the real Hiddify core 5.9.8: the links are parsed identically with and without the header. The metadata display inside the Hiddify app itself was not run here.

If Hysteria2 is the only protocol in a response and its links are off, `sub.txt` holds only the header (no configs) while the two JSON files are still published, so that old links do not linger. A client cannot import configs from a header-only file (Hiddify core rejects it). No output file is ever written empty.

## Compatibility

**Minimum versions**

- Xray-core **26.3.27 or newer** (stable). The first release that works is 26.3.23, but it is marked as a pre-release; every release between 26.1.13 and 26.3.23 was tried and fails. CI tests 26.3.27 and 26.11.9.
- sing-box **1.14.0 or newer**: the rule sets use the `http_client` option, which the sing-box documentation marks as new in 1.14.0. Tested with 1.14.4.
- Hiddify core 5.9.8 was used to test how Hiddify imports the files.
- `xray.json` needs the usual `geoip.dat` and `geosite.dat` files because it uses the standard `geosite:category-ir` and `geoip:ir` tags. Bare Xray-core without them refuses to load the file.
- `singbox.json` downloads two rule sets from `raw.githubusercontent.com` on its first start and caches them; if that host is unreachable at the very first start, sing-box refuses to start.

**What each output can and cannot express**

A field that a core does not know is ignored silently (Xray) or rejected, so nothing is ever invented. Where a setting cannot be carried, it is listed here.

| Setting from the source | `sub.txt` | `singbox.json` | `xray.json` |
| --- | --- | --- | --- |
| VLESS `packet_encoding` (`xudp`) | yes (`packetEncoding=xudp`) | yes | **no field exists.** Xray's VLESS outbound has no packet encoding option (checked in the source of 26.3.23 and 26.11.9). Xray carries VLESS UDP as XUDP when the flow is `xtls-rprx-vision`, and by default otherwise (except ports 53 and 443). So `xudp` is what Xray does anyway; a plain packet encoding cannot be requested from the JSON file. |
| VLESS explicit `network: tcp` (UDP disabled) | no | yes | no |
| Hysteria2 `pre_initial_junk` | no | no | yes |
| Hysteria2 certificate | pin, only when links are enabled | embedded and verified | pinned |
| VLESS TLS without a server name | accepted, no `sni` parameter | accepted | accepted, no `serverName` |
| VLESS Reality without a server name | rejected | rejected | rejected |

Hiddify adds `xudp` to every VLESS link, with or without the `packetEncoding` parameter (tested), so a plain packet encoding cannot be requested there either.

**Hysteria2 and `pre_initial_junk`.** The upstream's Hysteria2 variant is a stock Hysteria2 server plus a client-side evasion: before the QUIC handshake the client sends one random 8 to 64 byte UDP datagram. The documented default is `false`, and so is a missing or `null` value. Only `xray.json` can reproduce it (a `finalmask` UDP `noise` mask, resent every 30 to 60 seconds; the official client sends it on each new UDP flow). Stock sing-box and share links cannot, so those entries work as plain Hysteria2.

**VLESS without transport security.** A VLESS entry with neither TLS nor Reality has no encryption. Xray 26.11.9 refuses to load a whole configuration that contains one for a public address (Xray 26.3.x does not check this). Such an entry is therefore rejected with the reason `vless_without_security` unless its server is a private, loopback or link-local IP address.

## Security

**Account state.** The state is one JSON envelope with `version`, `algorithm`, `nonce` and `ciphertext`; it contains no readable field. AES-256-GCM, a fresh random 12 byte nonce for every encryption, and the format version is part of the authenticated data. The key is only in the secret. The decrypted state exists in memory only, never on disk, in Git, in a cache, in an artifact or in a log. It is rewritten only when the account changes.

**Failure rules.** A missing state, a wrong key or a damaged file stops the run; no account is ever created on its own. A rejected account (HTTP 401 or 403) also stops the run, because account creation is not safe to repeat and a 403 can mean a block rather than a bad account. Account creation is never retried.

**Leak guard.** Before publishing, every file is checked for the device id and the token (as text) and for the user id under identifying names such as `user_id`, `userId` or the upstream's user-id header, in JSON and in text. The user id is never searched as a bare number, so the same digits in a port or an address cause no false alarm.

**Hysteria2 certificates.** The servers use a self-signed certificate. It is parsed, must be a single valid certificate (not expired, no private key), and its SHA-256 fingerprint is the format of the official Hysteria `pinSHA256`. `xray.json` pins it and `singbox.json` embeds it as the only trust anchor; a server with another certificate is rejected (tested). A share link can only say `insecure=1&pinSHA256=...`: v2rayNG applies the pin (read from its source), **Hiddify ignores it** (tested), which turns TLS verification off for that connection. For this reason Hysteria2 links are left out of `sub.txt` by default; Hiddify users should import `singbox.json`.

**Repository and workflows.** If the repository is public, anyone can read the published files and the Git history; they contain shared proxy details, never your account data. Workflows use least privilege (`contents: write` only in the update job, read-only in the test workflow, no secrets in tests), every action is pinned to a full commit hash, user input is never interpolated into shell scripts, and the commit step stages exactly four paths and refuses anything else.

**Limits.** The encrypted file stays in Git history; if the key ever leaks, every old version can be decrypted, so replace the key and run `recreate`. Anyone with write access to the repository can read the secret through a workflow, so keep write access small. Secrets are not given to workflows triggered from forks.

## Testing

```
python -m pip install -r requirements-dev.txt
python -m pytest -q
```

The offline tests need no network and no account: state encryption (wrong keys, tampering), parsing, certificates, duplicate detection, link validation, retry rules, atomic writes, the leak guard, the exact wire format sent to the upstream, and the workflow security rules (including a real execution of the commit script against a local Git repository).

Tests that need real binaries are skipped when the binaries are missing, and the skip reason is printed. In GitHub Actions the **Tests** workflow downloads the stable releases listed in `tools/cores.lock.json`, verifies their SHA-256 hashes and runs everything, including loopback tests where real servers and clients exchange traffic. To do the same locally:

```
python tools/fetch_cores.py --xray v26.3.27
```

then export the printed `XRAY_BIN`, `SING_BOX_BIN`, `HIDDIFY_BIN` and `XRAY_ASSET_DIR` and run the tests again. One test is an expected failure that passes with some versions: with Xray 26.11.9 as the server, the sing-box 1.14.4 client is rejected by its Reality server, while Xray 26.3.27 accepts it.

## Troubleshooting

| Symptom | Cause and action |
| --- | --- |
| "no encrypted state file exists yet" | First run. Start the update manually with `create`. |
| "wrong key or the file was changed" | The secret does not match the file. Restore the original key, or run `recreate` if it is lost. |
| "rejected the saved account" | The upstream rejected the account. Run `recreate`. |
| "only 0 usable configs found" | The response held no supported type this time. The previous files stay; the next run usually differs. |
| `sub.txt` is empty | Every usable config was Hysteria2 and its links are off. Use `singbox.json` or `xray.json`, or enable the links knowingly. |
| Xray refuses to load `xray.json` | Xray older than 26.3.27, or missing `geoip.dat` and `geosite.dat`. |
| sing-box does not start | sing-box older than 1.14.0, or the rule-set host was unreachable at the first start. |
| HTTP 429 in the log | The upstream asks you to slow down; the run stops and the next hour tries again. |
| Nothing runs in a fork | Enable workflows in the **Actions** tab of the fork. |

## Limitations

- The upstream decides which protocol types a request receives and changes them between requests. A run can contain no usable type; that run fails and the previous files stay.
- Proxies are handed out per client and network location and rotate. An entry can stop working at any time, and one that works on a network may not work on another.
- A public subscription sends many users to the same few servers, so expect them to be slower or blocked sooner than a personal one.
- The toolkit depends on an unofficial use of the upstream service and can stop working if it changes (see [docs/UPSTREAM.md](docs/UPSTREAM.md)).
- Real-traffic tests cover Shadowsocks, VLESS (plain and Reality) and Hysteria2 on loopback; VLESS with ordinary TLS was only checked by configuration loading.

## Disclaimer

This project is not affiliated with, endorsed by or sponsored by the upstream service, its operators or any client mentioned in the documentation. The software is provided as is, without warranty. You are responsible for complying with the laws that apply to you and with the terms of every service you use, including the upstream service, whose terms were not reviewed for this project.

## Third-Party Notices and License

Third-party software, data and the licenses declared by their authors are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). No third-party source code is included in this repository. This project is released under the [MIT License](LICENSE), Copyright (c) 2026 4n0nymou3.

This project is intended for educational and research purposes only.
