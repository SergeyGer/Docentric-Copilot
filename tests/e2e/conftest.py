"""Playwright browser fixtures for the v0.12 Reference Inspector E2E suite.

The suite starts the real FastAPI app and the built Next.js app on free ports,
then drives Chromium with deterministic local fixtures. It never calls an LLM
provider, needs no API key and never touches the private D365 corpus.

Local run::

    npm --prefix apps/web ci          # once
    .venv/bin/pytest tests/e2e --e2e -q

If ``apps/web/.next`` is missing the fixture builds it. Browser binaries are
taken from ``PLAYWRIGHT_BROWSERS_PATH`` when set, otherwise from the developer's
Playwright cache; the repository-local ``.tools/pw-browsers`` cache is detected
automatically. CI installs Chromium with ``python -m playwright install``.

Failures always leave a full-page screenshot and a Playwright trace under
``test-results/e2e/<test>/``. The optional artifact probe in
``test_artifact_probe.py`` proves that mechanism on purpose.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
WEB_DIR = ROOT / "apps" / "web"
ARTIFACTS = ROOT / "test-results" / "e2e"
E2E_TIMEOUT = float(os.environ.get("DC_E2E_TIMEOUT", "180"))
API_PORT = int(os.environ.get("DC_E2E_API_PORT", "8100"))
WEB_PORT = int(os.environ.get("DC_E2E_WEB_PORT", "3100"))
MAX_TEST_UPLOAD = 65_536


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for(url: str, *, deadline: float, process: subprocess.Popen[bytes] | None = None) -> None:
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError(f"process exited before {url} was ready (exit {process.returncode})")
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            last_error = exc
        time.sleep(0.4)
    raise TimeoutError(f"timed out waiting for {url}: {last_error}")


def _tail(path: Path, limit: int = 40) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-limit:])


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("127.0.0.1", port))
        except OSError:
            return False
    return True


def _ensure_web_build(env: dict[str, str], log_path: Path, api_url: str) -> None:
    """Build once per API target; Next.js compiles the proxy rewrites at build time."""
    build_id = WEB_DIR / ".next" / "BUILD_ID"
    marker = WEB_DIR / ".next" / "e2e-api-target"
    target_matches = marker.is_file() and marker.read_text(encoding="utf-8").strip() == api_url
    if build_id.is_file() and target_matches and not os.environ.get("DC_E2E_FORCE_BUILD"):
        return
    if not (WEB_DIR / "node_modules").is_dir():
        with log_path.open("w", encoding="utf-8") as log:
            subprocess.run(
                ["npm", "ci", "--no-audit", "--no-fund"],
                cwd=WEB_DIR,
                env=env,
                check=True,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
    with log_path.open("w", encoding="utf-8") as log:
        subprocess.run(
            ["npm", "run", "build"],
            cwd=WEB_DIR,
            env=env,
            check=True,
            stdout=log,
            stderr=subprocess.STDOUT,
            timeout=600,
        )
    marker.write_text(api_url, encoding="utf-8")


@dataclass(frozen=True)
class E2EServers:
    api_url: str
    web_url: str


def _start_process(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    log_path: Path,
) -> subprocess.Popen[bytes]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("wb")
    return subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    """Stop the whole process group so npm does not leave next-server behind."""
    if process.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        process.terminate()
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            process.kill()
        process.wait(timeout=5)


@pytest.fixture(scope="session")
def e2e_servers() -> Iterator[E2EServers]:
    external = os.environ.get("DC_E2E_BASE_URL")
    if external:
        yield E2EServers(api_url=os.environ.get("DC_E2E_API_URL", ""), web_url=external.rstrip("/"))
        return
    if shutil.which("npm") is None:
        pytest.skip("npm is required for the Next.js E2E app")
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    if not _port_available(API_PORT) or not _port_available(WEB_PORT):
        raise RuntimeError(
            f"E2E ports {API_PORT}/{WEB_PORT} are in use; set DC_E2E_API_PORT and "
            "DC_E2E_WEB_PORT to free ports"
        )
    api_port = API_PORT
    web_port = WEB_PORT
    api_url = f"http://127.0.0.1:{api_port}"
    web_url = f"http://127.0.0.1:{web_port}"
    data_dir = ARTIFACTS / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    shared_env = os.environ.copy()
    shared_env.update(
        {
            "DC_ENV": "test",
            "DC_LOG_LEVEL": "CRITICAL",
            "NEXT_TELEMETRY_DISABLED": "1",
            "API_PROXY_TARGET": api_url,
            # No provider credentials: the reference inspector is deterministic.
            "OPENAI_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
            "GEMINI_API_KEY": "",
            "GOOGLE_API_KEY": "",
        }
    )
    api_env = {
        **shared_env,
        "DC_DATA_DIR": str(data_dir),
        "DC_MAX_DDSP_BYTES": str(MAX_TEST_UPLOAD),
        "DC_MAX_UNCOMPRESSED_BYTES": str(8 * 1024 * 1024),
        "DC_ARTIFACT_TTL_SECONDS": "86400",
        "DC_ENABLE_AX_ADAPTER": "false",
    }
    build_log = ARTIFACTS / "server-build.log"
    _ensure_web_build(shared_env, build_log, api_url)
    api_log = ARTIFACTS / "server-api.log"
    web_log = ARTIFACTS / "server-web.log"
    api = _start_process(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "docentric_copilot.api.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(api_port),
        ],
        cwd=ROOT,
        env=api_env,
        log_path=api_log,
    )
    web = _start_process(
        ["npm", "run", "start", "--", "-p", str(web_port)],
        cwd=WEB_DIR,
        env=shared_env,
        log_path=web_log,
    )
    deadline = time.monotonic() + E2E_TIMEOUT
    try:
        try:
            _wait_for(f"{api_url}/health", deadline=deadline, process=api)
        except Exception as exc:  # pragma: no cover - environment failure
            raise RuntimeError(f"API did not start: {exc}\n{_tail(api_log)}") from exc
        try:
            _wait_for(f"{web_url}/reference", deadline=time.monotonic() + 90, process=web)
        except Exception as exc:  # pragma: no cover - environment failure
            raise RuntimeError(
                f"web app did not start: {exc}\nbuild:\n{_tail(build_log)}\nweb:\n{_tail(web_log)}"
            ) from exc
        (ARTIFACTS / "servers.json").write_text(
            json.dumps({"api_url": api_url, "web_url": web_url}, indent=2), encoding="utf-8"
        )
        yield E2EServers(api_url=api_url, web_url=web_url)
    finally:
        _stop_process(web)
        _stop_process(api)


@pytest.fixture(scope="session")
def browser() -> Iterator[object]:
    local_browsers = ROOT / ".tools" / "pw-browsers"
    if local_browsers.is_dir() and not os.environ.get("PLAYWRIGHT_BROWSERS_PATH"):
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(local_browsers)
    from playwright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        headed = os.environ.get("DC_E2E_HEADED") == "1"
        instance = playwright.chromium.launch(headless=not headed)
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        (ARTIFACTS / "browser-version.txt").write_text(instance.version, encoding="utf-8")
        try:
            yield instance
        finally:
            instance.close()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]):
    outcome = yield
    report = outcome.get_result()
    setattr(item, f"rep_{report.when}", report)


def _artifact_dir(item: pytest.Item) -> Path:
    name = re.sub(r"[^a-zA-Z0-9_.-]+", "-", item.nodeid).strip("-")
    return ARTIFACTS / (name[:120] or "test")


@pytest.fixture
def page_errors() -> list[str]:
    return []


@pytest.fixture
def page(browser: object, page_errors: list[str], request: pytest.FixtureRequest):
    context = browser.new_context(  # type: ignore[attr-defined]
        viewport={"width": 1280, "height": 900},
        accept_downloads=True,
        locale="en-US",
    )
    context.tracing.start(screenshots=True, snapshots=True, sources=True)
    page = context.new_page()
    page.on("pageerror", lambda error: page_errors.append(str(error)))
    try:
        yield page
    finally:
        report = getattr(request.node, "rep_call", None)
        failed = bool(report is not None and report.failed)
        if failed:
            directory = _artifact_dir(request.node)
            directory.mkdir(parents=True, exist_ok=True)
            with contextlib.suppress(Exception):  # page may already be closed
                page.screenshot(path=str(directory / "failure.png"), full_page=True)
            with contextlib.suppress(Exception):  # tracing may already be stopped
                context.tracing.stop(path=str(directory / "trace.zip"))
            (directory / "page-errors.txt").write_text("\n".join(page_errors), encoding="utf-8")
        else:
            context.tracing.stop()
        context.close()


@pytest.fixture
def base_url(e2e_servers: E2EServers) -> str:
    return e2e_servers.web_url


def wait_for_saved_report(page, timeout: int = 60_000) -> str:
    """Wait for the saved-report badge and return the report id."""
    badge = page.get_by_test_id("reference-saved-report")
    badge.wait_for(state="visible", timeout=timeout)
    match = re.search(r"Saved report\s+([A-Za-z0-9_.:-]+)", badge.inner_text())
    if match is None:
        raise AssertionError(f"could not read the report id from: {badge.inner_text()!r}")
    return match.group(1)
