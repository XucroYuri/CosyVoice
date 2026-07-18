from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _load_gate():
    path = ROOT / "tts_more" / "verify-release-asset-set.py"
    assert path.is_file(), "fork release gate is missing"
    spec = importlib.util.spec_from_file_location("verify_release_asset_set", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _expected_names() -> list[str]:
    archive = "CosyVoice-0.2.0-test-windows-x64-cpu-bootstrap.zip"
    return [
        archive,
        f"{archive}.sha256",
        f"{archive}.spdx.json",
        f"{archive}.licenses.json",
        f"{archive}.provenance.json",
        f"{archive}.acceptance.json",
    ]


def _arguments(expected: list[str], tag: str = "v0.2.0-test") -> list[str]:
    return [
        "--repository",
        "XucroYuri/CosyVoice",
        "--tag",
        tag,
        *(argument for name in expected for argument in ("--expected-name", name)),
    ]


def test_release_gate_accepts_exact_six_assets_and_url_encodes_tag() -> None:
    gate = _load_gate()
    expected = _expected_names()
    seen: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        seen.append(command)
        return subprocess.CompletedProcess(
            command, 0, stdout="\n".join(reversed(expected)) + "\n", stderr=""
        )

    assert gate.main(_arguments(expected, tag="v0.2.0/rc1"), run=fake_run) == 0
    assert seen == [
        [
            "gh",
            "api",
            "repos/XucroYuri/CosyVoice/releases/tags/v0.2.0%2Frc1",
            "--jq",
            ".assets[].name",
        ]
    ]


def test_release_gate_rejects_concurrent_seventh_asset() -> None:
    gate = _load_gate()
    expected = _expected_names()

    def fake_run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command, 0, stdout="\n".join([*expected, "foreign-full.zip"]) + "\n", stderr=""
        )

    assert gate.main(_arguments(expected), run=fake_run) != 0


def test_release_gate_rejects_six_assets_when_one_is_replaced(
    capsys: pytest.CaptureFixture[str],
) -> None:
    gate = _load_gate()
    expected = _expected_names()

    def fake_run(command: list[str], **_kwargs) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command, 0, stdout="\n".join([*expected[:-1], "foreign.zip"]) + "\n", stderr=""
        )

    assert gate.main(_arguments(expected), run=fake_run) != 0
    error = capsys.readouterr().err
    assert "mismatch" in error
    assert expected[-1] in error
    assert "foreign.zip" in error


def test_release_workflow_audits_before_and_after_upload() -> None:
    workflow = (ROOT / ".github" / "workflows" / "portable-release.yml").read_text(
        encoding="utf-8"
    )
    publish = workflow.split("- name: Publish bootstrap assets only", 1)[1]
    upload = 'gh release upload "$GITHUB_REF_NAME" "${assets[@]}" --clobber'
    gate_call = '"$build_python" tts_more/verify-release-asset-set.py'

    assert "audit-release-assets --directory" in workflow
    assert "comm -23" in publish
    assert upload in publish
    assert gate_call in publish
    assert publish.index(upload) < publish.index(gate_call)
    assert 'verify_asset_args+=(--expected-name "$asset_name")' in publish
    assert "release delete-asset" not in publish


def test_release_workflow_uses_locked_isolated_build_tools_for_all_audits() -> None:
    workflow = (ROOT / ".github" / "workflows" / "portable-release.yml").read_text(
        encoding="utf-8"
    )
    bootstrap, release = workflow.split("  github-release:", 1)

    assert workflow.count('python-version: "3.11"') == 2
    assert workflow.count("astral-sh/setup-uv@08807647e7069bb48b6ef5acd8ec9567f424441b") == 2
    assert workflow.count("UV_PROJECT_ENVIRONMENT: ${{ runner.temp }}/tts-more-build-tools") == 2
    assert workflow.count("uv sync --locked --project tts_more/build-tools") == 2

    assert '$env:TTS_MORE_BUILD_PYTHON = $buildPython' in bootstrap
    assert '& $buildPython tts_more\\tests\\test_portable_integration.py -v' in bootstrap
    assert bootstrap.count("& $buildPython tts_more\\portable_packages.py") >= 2
    assert 'build_python="$UV_PROJECT_ENVIRONMENT/bin/python"' in release
    assert release.count('"$build_python" tts_more/portable_packages.py') >= 2
    assert '"$build_python" tts_more/verify-release-asset-set.py' in release

    assert "python tts_more" not in workflow
    assert "python -m pip" not in workflow


def test_release_workflow_verifies_full_refusal_by_child_exit_code_and_output() -> None:
    workflow = (ROOT / ".github" / "workflows" / "portable-release.yml").read_text(
        encoding="utf-8"
    )
    build = workflow.split("- name: Build bootstrap and prove full is prohibited", 1)[1]
    build = build.split("- uses: actions/upload-artifact", 1)[0]

    host = "$fullHost = (Get-Process -Id $PID).Path"
    save_preference = "$fullErrorActionPreference = $ErrorActionPreference"
    capture_preference = '$ErrorActionPreference = "Continue"'
    invocation = (
        "$fullOutput = @(& $fullHost -NoProfile -NonInteractive -File "
        ".\\Build-Package.ps1 -Profile Full -Device CPU -Version $version 2>&1)"
    )
    exit_code = "$fullExitCode = $LASTEXITCODE"
    restore_preference = "$ErrorActionPreference = $fullErrorActionPreference"
    decision = (
        '$blocked = $fullExitCode -ne 0 -and '
        '([string]::Join("`n", @($fullOutput)) -match "profile=full")'
    )

    assert host in build
    assert save_preference in build
    assert capture_preference in build
    assert invocation in build
    assert exit_code in build
    assert restore_preference in build
    assert decision in build
    assert build.index(host) < build.index(save_preference) < build.index(capture_preference)
    assert build.index(capture_preference) < build.index(invocation) < build.index(exit_code)
    assert build.index(exit_code) < build.index(restore_preference)
    assert build.index(exit_code) < build.index(decision)
    assert "try { .\\Build-Package.ps1 -Profile Full" not in build


def test_release_workflow_exits_zero_after_expected_full_refusal() -> None:
    workflow = (ROOT / ".github" / "workflows" / "portable-release.yml").read_text(
        encoding="utf-8"
    )
    build = workflow.split("- name: Build bootstrap and prove full is prohibited", 1)[1]
    build = build.split("- uses: actions/upload-artifact", 1)[0]
    rejection = 'if (!$blocked) { throw "full profile was not blocked in GitHub Actions" }'
    executable_lines = [line.strip() for line in build.splitlines() if line.strip()]

    assert rejection in build
    assert executable_lines[-1] == "exit 0"
    assert build.index(rejection) < build.rindex("exit 0")
