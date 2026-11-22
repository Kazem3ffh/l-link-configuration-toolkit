import json
import re
import subprocess
from pathlib import Path

import pytest
import yaml

import factories
from l_toolkit import constants as C
from l_toolkit import upstream

ROOT = Path(__file__).resolve().parent.parent
UPDATE = ROOT / ".github" / "workflows" / "update-subscription.yml"
TESTS = ROOT / ".github" / "workflows" / "tests.yml"
README = ROOT / "README.md"
NOTICES = ROOT / "THIRD_PARTY_NOTICES.md"
USES = re.compile(r"^[\w.-]+/[\w.-]+(/[\w./-]+)?@[0-9a-f]{40}$")
SKIPPED_PARTS = {".git", "__pycache__", ".pytest_cache", ".cores", ".venv", "venv"}
UPSTREAM_NAME_ALLOWED = {
    "l_toolkit/upstream.py",
    "docs/UPSTREAM.md",
    "THIRD_PARTY_NOTICES.md",
    "tests/test_upstream_wire.py",
}
README_SECTIONS = [
    "Overview",
    "Features",
    "How It Works",
    "Supported Protocols and Formats",
    "Repository Structure",
    "Requirements",
    "Running Locally",
    "Fork and Setup",
    "GitHub Actions",
    "Configuration",
    "Usage",
    "Output Files",
    "Compatibility",
    "Security",
    "Testing",
    "Troubleshooting",
    "Limitations",
    "Disclaimer",
    "Third-Party Notices and License",
]


def load(path):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if "on" not in data and True in data:
        data["on"] = data.pop(True)
    return data


def all_steps(workflow):
    for job in workflow["jobs"].values():
        for step in job["steps"]:
            yield step


def project_files():
    for path in sorted(ROOT.rglob("*")):
        if path.is_file() and not (set(path.relative_to(ROOT).parts) & SKIPPED_PARTS):
            yield path


def text_files():
    for path in project_files():
        if path == Path(__file__).resolve():
            continue
        try:
            yield path.relative_to(ROOT).as_posix(), path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue


@pytest.fixture(scope="module")
def update():
    return load(UPDATE)


@pytest.fixture(scope="module")
def tests_workflow():
    return load(TESTS)


def test_the_hourly_schedule_is_unchanged_and_there_is_exactly_one(update):
    assert update["on"]["schedule"] == [{"cron": "23 * * * *"}]


def test_manual_runs_offer_a_closed_set_of_bootstrap_choices(update):
    inputs = update["on"]["workflow_dispatch"]["inputs"]["bootstrap"]
    assert inputs["type"] == "choice" and inputs["default"] == "none"
    assert inputs["options"] == ["none", "create", "recreate"]
    assert tuple(inputs["options"]) == C.BOOTSTRAP_MODES


def test_updates_never_run_concurrently_and_are_never_cancelled(update):
    assert update["concurrency"]["group"] == "update-subscription"
    assert update["concurrency"]["cancel-in-progress"] is False


def test_update_workflow_has_least_privilege(update):
    assert update["permissions"] == {}
    assert update["jobs"]["update"]["permissions"] == {"contents": "write"}


def test_tests_workflow_is_read_only_and_has_no_secrets(tests_workflow):
    assert tests_workflow["permissions"] == {"contents": "read"}
    text = TESTS.read_text(encoding="utf-8")
    assert "secrets." not in text and "GITHUB_TOKEN" not in text


@pytest.mark.parametrize("path", [UPDATE, TESTS])
def test_no_dangerous_triggers(path):
    text = path.read_text(encoding="utf-8")
    for trigger in ("pull_request_target", "workflow_run", "repository_dispatch"):
        assert trigger not in text


@pytest.mark.parametrize("path", [UPDATE, TESTS])
def test_every_action_is_pinned_to_a_full_commit_sha(path):
    uses = [step["uses"] for step in all_steps(load(path)) if "uses" in step]
    assert uses
    for reference in uses:
        assert USES.match(reference), reference


def test_pull_request_checkouts_do_not_keep_credentials(tests_workflow):
    for step in all_steps(tests_workflow):
        if step.get("uses", "").startswith("actions/checkout"):
            assert step["with"]["persist-credentials"] is False


def test_the_secret_is_used_in_exactly_one_step_of_the_update_workflow(update):
    carriers = [s for s in all_steps(update) if "secrets." in json.dumps(s)]
    assert len(carriers) == 1
    assert "secrets.%s" % C.STATE_KEY_ENV in json.dumps(carriers[0])
    assert list(carriers[0]["env"]) == [C.STATE_KEY_ENV, "L_BOOTSTRAP", "L_HYSTERIA2_LINKS"]
    assert "secrets." not in TESTS.read_text(encoding="utf-8")


def test_no_cache_action_is_used_for_account_data(update):
    assert not [s for s in all_steps(update) if "actions/cache" in s.get("uses", "")]
    assert "actions/cache" not in UPDATE.read_text(encoding="utf-8")


def test_user_input_is_not_interpolated_into_shell_scripts(update):
    for step in all_steps(update):
        assert "${{" not in step.get("run", "")


def test_the_commit_step_only_stages_the_four_allowed_files(update):
    step = next(s for s in all_steps(update) if s.get("name") == "Commit changes")
    assert step["if"].replace(" ", "") == "${{always()}}"
    script = step["run"]
    assert "state/upstream-account.enc subscription/sub.txt subscription/singbox.json subscription/xray.json" in script
    for forbidden in ("git add -A", "git add .", "git add --all", "set -x"):
        assert forbidden not in script
    assert "Unexpected files are staged" in script


def test_secrets_are_never_echoed(update):
    text = UPDATE.read_text(encoding="utf-8")
    cleaned = text.replace('echo "No changes to commit"', "").replace(
        'echo "Unexpected files are staged, refusing to commit"', ""
    )
    assert "echo" not in cleaned


def test_python_dependencies_are_pinned_exactly():
    for name in ("requirements.txt", "requirements-dev.txt"):
        for line in (ROOT / name).read_text(encoding="utf-8").splitlines():
            if line and not line.startswith("-r"):
                assert "==" in line, line


def test_pip_caching_never_involves_account_data(update):
    setup = next(s for s in all_steps(update) if s.get("uses", "").startswith("actions/setup-python"))
    assert setup["with"]["cache"] == "pip"
    assert setup["with"]["cache-dependency-path"] == "requirements.txt"


def test_secret_bearing_files_are_ignored_by_git():
    ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for entry in (".state/", ".cores/", ".env", ".env.*", "*.key", "venv/", ".venv/", "__pycache__/"):
        assert entry in ignored, entry


def test_the_core_lock_file_is_complete_checksummed_and_stable_only():
    lock = json.loads((ROOT / "tools" / "cores.lock.json").read_text(encoding="utf-8"))
    assert {"xray", "sing-box", "hiddify-core", "geoip", "geosite"} <= set(lock)
    for versions in lock.values():
        for entry in versions.values():
            assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
            assert entry["url"].startswith("https://github.com/")
            assert "pre" not in entry["url"].lower()
    assert set(lock["xray"]) == {"v26.3.27", "v26.11.9"}


def test_ci_matrix_matches_the_lock_file():
    lock = json.loads((ROOT / "tools" / "cores.lock.json").read_text(encoding="utf-8"))
    matrix = load(TESTS)["jobs"]["cores"]["strategy"]["matrix"]["xray"]
    assert sorted(matrix) == sorted(lock["xray"])


def test_every_pinned_tool_is_named_with_its_version_in_the_third_party_notices():
    lock = json.loads((ROOT / "tools" / "cores.lock.json").read_text(encoding="utf-8"))
    notices = NOTICES.read_text(encoding="utf-8")
    for tool in ("xray", "sing-box", "hiddify-core"):
        for version in lock[tool]:
            assert version in notices, (tool, version)
    for tool in ("geoip", "geosite"):
        for version in lock[tool]:
            assert version in notices, (tool, version)


def test_direct_dependency_versions_in_the_notices_match_the_requirements():
    notices = NOTICES.read_text(encoding="utf-8")
    pins = {}
    for name in ("requirements.txt", "requirements-dev.txt"):
        for line in (ROOT / name).read_text(encoding="utf-8").splitlines():
            if "==" in line:
                package, version = line.split("==")
                pins[package.strip()] = version.strip()
    assert {"requests", "cryptography", "pytest", "PyYAML"} <= set(pins)
    for package, version in pins.items():
        assert re.search(r"\|\s*%s\s*\|\s*%s\s*\|" % (re.escape(package), re.escape(version)), notices), package


def test_third_party_notices_cover_every_category():
    notices = NOTICES.read_text(encoding="utf-8")
    for heading in (
        "Runtime dependencies",
        "Development and test dependencies",
        "Tools downloaded only by the test workflow",
        "Data referenced by the generated files",
        "Projects whose public source or documentation was read",
        "GitHub Actions used by the workflows",
    ):
        assert heading in notices, heading
    assert "No third-party source code is copied" in notices
    for license_name in ("MPL-2.0", "GPL-3.0", "CC BY-SA 4.0", "Apache-2.0", "MIT"):
        assert license_name in notices, license_name


def test_operational_outputs_never_contain_test_data_or_state_data():
    response = factories.response()
    certificate = response["options"]["outbounds"][3]["tls"]["certificate"]
    markers = [factories.VLESS_UUID, "192.0.2.11", "192.0.2.12", "192.0.2.13", certificate.splitlines()[1]]
    for folder in ("subscription", "state"):
        for path in (ROOT / folder).glob("*"):
            if path.is_file():
                content = path.read_text(encoding="utf-8", errors="replace")
                for marker in markers:
                    assert marker not in content, (path.name, marker)
                assert "PRIVATE KEY" not in content


def test_no_plaintext_state_file_is_present():
    for relative in (".state/state.json", "state/state.json", "state.json", "state/upstream-account.json"):
        assert not (ROOT / relative).exists()
    state_dir = ROOT / "state"
    if state_dir.exists():
        for path in state_dir.glob("*.enc"):
            envelope = json.loads(path.read_text(encoding="utf-8"))
            assert set(envelope) == {"version", "algorithm", "nonce", "ciphertext"}


def test_python_sources_contain_no_comments():
    for folder in ("l_toolkit", "tools", "tests"):
        for path in (ROOT / folder).glob("*.py"):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                assert not line.strip().startswith("#"), (path.name, number)


def test_the_upstream_name_appears_only_in_the_allowed_files():
    pattern = re.compile(r"lantern|getiantem|iantem", re.IGNORECASE)
    offenders = [name for name, text in text_files() if pattern.search(text) and name not in UPSTREAM_NAME_ALLOWED]
    assert offenders == []


def test_the_allowed_files_really_are_the_only_homes_of_the_wire_constants():
    for name in ("l_toolkit/upstream.py", "docs/UPSTREAM.md", "THIRD_PARTY_NOTICES.md", "tests/test_upstream_wire.py"):
        assert re.search(r"lantern", (ROOT / name).read_text(encoding="utf-8"), re.IGNORECASE), name


@pytest.mark.parametrize(
    "forbidden",
    ["imegabiz", "lantern-subscription-exporter", "lantern_exporter", "LANTERN_", "lantern-update", "lantern-project"],
)
def test_no_trace_of_the_previous_repository_or_its_names_remains(forbidden):
    assert [name for name, text in text_files() if forbidden in text] == []


def test_no_secret_looking_strings_are_committed():
    patterns = [
        re.compile(r"ghp_[A-Za-z0-9]{20,}"),
        re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
        re.compile(r"AKIA[0-9A-Z]{16}"),
    ]
    for name, text in text_files():
        for pattern in patterns:
            assert not pattern.search(text), (name, pattern.pattern)


def test_the_license_names_the_owner_and_is_mit():
    text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert text.startswith("MIT License") and "Copyright (c) 2026 4n0nymou3" in text


def test_the_public_identity_is_consistent():
    readme = README.read_text(encoding="utf-8")
    assert readme.startswith("# L — Link Configuration Toolkit\n")
    assert "python -m l_toolkit" in readme
    assert "https://github.com/4n0nymou3/l-link-configuration-toolkit" in readme
    for text in (C.PROFILE_NAME, C.URLTEST_NAME, C.DEFAULT_USER_AGENT, C.DEFAULT_STATE_FILE, C.STATE_KEY_ENV):
        assert not re.search(r"lantern|getiantem|iantem", text, re.IGNORECASE)
    assert C.PROFILE_NAME == "\U0001F47D Anonymous L \U0001F680"
    assert C.URLTEST_NAME == "\U0001F47D Anonymous L \U0001F310"
    assert C.DEFAULT_USER_AGENT.startswith("l-link-configuration-toolkit/")


def test_the_readme_has_the_required_sections_in_order():
    readme = README.read_text(encoding="utf-8")
    headings = re.findall(r"^## (.+)$", readme, flags=re.MULTILINE)
    assert headings == README_SECTIONS


def test_the_readme_ends_with_the_required_sentence():
    lines = README.read_text(encoding="utf-8").rstrip("\n").splitlines()
    assert lines[-1] == "This project is intended for educational and research purposes only."


def test_the_readme_documents_the_key_facts():
    text = README.read_text(encoding="utf-8")
    for fragment in (
        "L_STATE_ENCRYPTION_KEY",
        "AES-256-GCM",
        "26.3.27",
        "1.14.0",
        "pinSHA256",
        "pre_initial_junk",
        "never retried",
        "state/upstream-account.enc",
        "minute 23 (UTC)",
        "L_HYSTERIA2_LINKS",
        "packet encoding",
        "holds only the header",
        "vless_without_security",
        "No output file is ever written empty",
        "profile-update-interval",
        "docs/UPSTREAM.md",
        "THIRD_PARTY_NOTICES.md",
        "tools/cores.lock.json",
    ):
        assert fragment in text, fragment


def test_the_readme_points_at_files_that_exist():
    text = README.read_text(encoding="utf-8")
    for relative in re.findall(r"\]\(((?!http)[^)#]+)\)", text):
        assert (ROOT / relative).exists(), relative


def test_the_readme_tree_lists_every_package_module():
    text = README.read_text(encoding="utf-8")
    for path in (ROOT / "l_toolkit").glob("*.py"):
        if path.name not in {"__init__.py", "__main__.py", "constants.py", "errors.py"}:
            assert path.name in text, path.name


def test_upstream_notes_contain_the_values_the_code_really_sends():
    text = (ROOT / "docs" / "UPSTREAM.md").read_text(encoding="utf-8")
    for value in (
        upstream.ACCOUNT_URL,
        upstream.CONFIG_URL,
        upstream.DEFAULT_APP_VERSION,
        upstream.DEFAULT_SINGBOX_VERSION,
        upstream.APP_NAME,
        upstream.BACKEND,
        upstream.HEADER_CLIENT_COUNTRY,
        upstream.HEADER_USER_ID,
    ):
        assert value in text, value
    for protocol in upstream.ADVERTISED_PROTOCOLS:
        assert protocol in text
    assert "not affiliated" in text


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


def _commit_script():
    step = next(s for s in all_steps(load(UPDATE)) if s.get("name") == "Commit changes")
    return step["run"]


@pytest.fixture
def sandbox(tmp_path):
    remote = tmp_path / "remote.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(work)], check=True)
    _git(work, "config", "user.name", "tester")
    _git(work, "config", "user.email", "tester@example.invalid")
    _git(work, "remote", "add", "origin", str(remote))
    (work / ".gitignore").write_text(".state/\n", encoding="utf-8")
    (work / "README.md").write_text("x\n", encoding="utf-8")
    _git(work, "add", ".")
    _git(work, "commit", "-q", "-m", "init")
    _git(work, "push", "-q", "-u", "origin", "main")
    return work, remote


def _run_commit_step(work):
    return subprocess.run(["bash", "-c", _commit_script()], cwd=work, capture_output=True, text=True)


def _write_outputs(work, state=True, outputs=True):
    if state:
        (work / "state").mkdir(exist_ok=True)
        (work / "state" / "upstream-account.enc").write_text('{"version":1}\n', encoding="utf-8")
    if outputs:
        (work / "subscription").mkdir(exist_ok=True)
        for name in ("sub.txt", "singbox.json", "xray.json"):
            (work / "subscription" / name).write_text("data-" + name + "\n", encoding="utf-8")


def test_commit_step_publishes_exactly_the_four_files_and_never_plaintext_state(sandbox):
    work, remote = sandbox
    _write_outputs(work)
    (work / ".state").mkdir()
    (work / ".state" / "state.json").write_text('{"token":"plain"}', encoding="utf-8")
    (work / "stray.txt").write_text("not allowed\n", encoding="utf-8")
    result = _run_commit_step(work)
    assert result.returncode == 0, result.stdout + result.stderr
    files = _git(remote, "ls-tree", "-r", "--name-only", "main").split()
    assert sorted(files) == [
        ".gitignore",
        "README.md",
        "state/upstream-account.enc",
        "subscription/singbox.json",
        "subscription/sub.txt",
        "subscription/xray.json",
    ]


def test_commit_step_does_nothing_when_nothing_changed(sandbox):
    work, remote = sandbox
    _write_outputs(work)
    assert _run_commit_step(work).returncode == 0
    before = _git(remote, "rev-parse", "main")
    result = _run_commit_step(work)
    assert result.returncode == 0 and "No changes to commit" in result.stdout
    assert _git(remote, "rev-parse", "main") == before


def test_commit_step_refuses_when_something_unexpected_is_already_staged(sandbox):
    work, remote = sandbox
    _write_outputs(work)
    (work / "evil.txt").write_text("secret\n", encoding="utf-8")
    _git(work, "add", "evil.txt")
    before = _git(remote, "rev-parse", "main")
    result = _run_commit_step(work)
    assert result.returncode == 1 and "Unexpected files are staged" in result.stdout
    assert _git(remote, "rev-parse", "main") == before


def test_commit_step_saves_a_new_state_even_when_no_outputs_exist_yet(sandbox):
    work, remote = sandbox
    _write_outputs(work, state=True, outputs=False)
    assert _run_commit_step(work).returncode == 0
    files = _git(remote, "ls-tree", "-r", "--name-only", "main").split()
    assert "state/upstream-account.enc" in files and not any(f.startswith("subscription/") for f in files)


def test_commit_step_with_nothing_at_all_is_harmless(sandbox):
    work, remote = sandbox
    before = _git(remote, "rev-parse", "main")
    result = _run_commit_step(work)
    assert result.returncode == 0 and "No changes to commit" in result.stdout
    assert _git(remote, "rev-parse", "main") == before
