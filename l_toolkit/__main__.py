import argparse
import logging
import os
import re
import sys

from . import constants as C
from . import upstream as U
from .client import UpstreamClient
from .errors import ExporterError
from .pipeline import run
from .state import generate_key_text, parse_key


TIME_ZONE_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9_+-]*(/[A-Za-z0-9_+-]+)*$")


def _env(name, default):
    value = os.environ.get(name, "")
    return value if value else default


def _parser():
    parser = argparse.ArgumentParser(prog="l_toolkit")
    parser.add_argument("--output-dir", default=_env("L_OUTPUT_DIR", C.DEFAULT_OUTPUT_DIR))
    parser.add_argument("--state-file", default=_env("L_STATE_FILE", C.DEFAULT_STATE_FILE))
    parser.add_argument("--bootstrap", choices=C.BOOTSTRAP_MODES, default=_env("L_BOOTSTRAP", "none"))
    parser.add_argument(
        "--hysteria2-links", choices=C.HYSTERIA2_LINK_MODES, default=_env("L_HYSTERIA2_LINKS", C.DEFAULT_HYSTERIA2_LINKS)
    )
    parser.add_argument("--country", default=os.environ.get("L_CLIENT_COUNTRY", C.DEFAULT_COUNTRY))
    parser.add_argument("--time-zone", default=os.environ.get("L_CLIENT_TIME_ZONE", U.DEFAULT_TIME_ZONE))
    parser.add_argument("--min-configs", type=int, default=int(_env("L_MIN_CONFIGS", C.MIN_CONFIGS)))
    parser.add_argument("--app-version", default=_env("L_UPSTREAM_APP_VERSION", U.DEFAULT_APP_VERSION))
    parser.add_argument("--singbox-version", default=_env("L_UPSTREAM_SINGBOX_VERSION", U.DEFAULT_SINGBOX_VERSION))
    parser.add_argument("--generate-key", action="store_true")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    if args.generate_key:
        print(generate_key_text())
        return 0
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stdout, force=True)
    log = logging.getLogger("l_toolkit")
    if args.min_configs < 1:
        print("--min-configs must be at least 1", file=sys.stderr)
        return 2
    time_zone = args.time_zone.strip()
    if time_zone and not TIME_ZONE_PATTERN.match(time_zone):
        print("--time-zone must be an IANA zone name such as Asia/Tehran, or empty", file=sys.stderr)
        return 2
    try:
        key = parse_key(os.environ.get(C.STATE_KEY_ENV, ""))
    except ExporterError as exc:
        log.error("update failed, previous output kept: %s", exc)
        return 1
    client = UpstreamClient(
        country=args.country.strip().upper(),
        time_zone=time_zone,
        app_version=args.app_version,
        singbox_version=args.singbox_version,
    )
    try:
        result = run(
            client,
            args.state_file,
            args.output_dir,
            key,
            bootstrap=args.bootstrap,
            min_configs=args.min_configs,
            hysteria2_links=args.hysteria2_links,
        )
    except ExporterError as exc:
        log.error("update failed, previous output kept: %s", exc)
        return 1
    log.info("usable configs: %d (share links: %d)", result.count, result.link_count)
    if result.link_count == 0:
        log.info("sub.txt holds only its header because every usable config is Hysteria2 and its share links are disabled")
    if result.links_omitted:
        log.info("%d Hysteria2 config(s) were left out of sub.txt for security, see README", result.links_omitted)
    if result.junk_not_expressible:
        log.info(
            "%d Hysteria2 config(s) request pre_initial_junk, which only xray.json can express",
            result.junk_not_expressible,
        )
    if result.state_written:
        log.info("the encrypted state file was written and must be committed")
    log.info("files changed: %s", result.changed or "none")
    return 0


if __name__ == "__main__":
    sys.exit(main())
