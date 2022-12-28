#!/usr/bin/env python
from pathlib import Path
import subprocess
import sys

BUILDER_PEX_PATH = Path(__file__).parent.parent / "generated/gha/builder.pex"
DOCKER_PATH = "/usr/bin/docker"
DOCKER_IMAGE = "ghcr.io/dagster-io/dagster-manylinux-builder:dev"


def main():
    args = sys.argv[1:]
    returncode, output = deploy_from_current_environment(args)
    if returncode:
        dep_failures = dependency_failure_lines(output)
        if dep_failures:
            print("Failed to find binary packages for the following:")
            for line in dep_failures:
                print(f"- {line}")
            print(
                "Will rebuild the Python Executable within Docker to build source only packages (sdists)."
            )
            deploy_from_docker(args)


def run(args):
    # Prints streaming output and also captures and returns it
    popen = subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8"
    )
    output = []
    for line in iter(popen.stdout.readline, ""):
        print(line, end="")
        output.append(line)
    popen.stdout.close()
    returncode = popen.wait()
    return returncode, output


def dependency_failure_lines(lines):
    return [line for line in lines if "No matching distribution" in line]


def deploy_from_current_environment(args):
    return run(
        [
            BUILDER_PEX_PATH,
            *args,
        ]
    )


def deploy_from_docker(args):
    github_docker_envs = [
        "DAGSTER_CLOUD_URL",
        "DAGSTER_CLOUD_API_TOKEN",
        "ENABLE_FAST_DEPLOYS",
        "ACTION_REPO",
        "FLAG_DEPS_CACHE_FROM",
        "FLAG_DEPS_CACHE_TO",
        "pythonLocation",
        "LD_LIBRARY_PATH",
        "GITHUB_TOKEN",
        "INPUT_ENTRYPOINT",
        "INPUT_ARGS",
        "HOME=/github/home",
        "GITHUB_JOB",
        "GITHUB_REF",
        "GITHUB_SHA",
        "GITHUB_REPOSITORY",
        "GITHUB_REPOSITORY_OWNER",
        "GITHUB_RUN_ID",
        "GITHUB_RUN_NUMBER",
        "GITHUB_RETENTION_DAYS",
        "GITHUB_RUN_ATTEMPT",
        "GITHUB_ACTOR",
        "GITHUB_TRIGGERING_ACTOR",
        "GITHUB_WORKFLOW=/github/workflow",
        "GITHUB_HEAD_REF",
        "GITHUB_BASE_REF",
        "GITHUB_EVENT_NAME",
        "GITHUB_SERVER_URL",
        "GITHUB_API_URL",
        "GITHUB_GRAPHQL_URL",
        "GITHUB_REF_NAME",
        "GITHUB_REF_PROTECTED",
        "GITHUB_REF_TYPE",
        "GITHUB_WORKSPACE=/github/workspace",
        "GITHUB_ACTION",
        "GITHUB_EVENT_PATH=/github/workflow/event.json",
        "GITHUB_ACTION_REPOSITORY",
        "GITHUB_ACTION_REF",
        "GITHUB_PATH",
        "GITHUB_ENV",
        "GITHUB_STEP_SUMMARY",
        "GITHUB_STATE",
        "GITHUB_OUTPUT",
        "GITHUB_ACTION_PATH",
        "RUNNER_OS",
        "RUNNER_ARCH",
        "RUNNER_NAME",
        "RUNNER_TOOL_CACHE",
        "RUNNER_TEMP",
        "RUNNER_WORKSPACE",
        "ACTIONS_RUNTIME_URL",
        "ACTIONS_RUNTIME_TOKEN",
        "ACTIONS_CACHE_URL",
        "GITHUB_ACTIONS=true",
        "CI=true",
    ]
    github_docker_mounts = [
        "/var/run/docker.sock:/var/run/docker.sock",
        "/home/runner/work/_temp/_github_home:/github/home",
        "/home/runner/work/_temp/_github_workflow:/github/workflow",
        "/home/runner/work/_temp/_runner_file_commands:/github/file_commands",
        "/home/runner/work/demo-1/demo-1:/github/workspace",
    ]

    github_args = [
        "--workdir",
        "/github/workspace",
        "--rm",
        "--entrypoint",
        "/usr/bin/bash",
    ]
    for env in github_docker_envs:
        github_args.extend(["-e", env])
    for mnt in github_docker_mounts:
        github_args.extend(["-v", mnt])
    builder_pex_args = " ".join(args) + " --build-sdists"
    github_args.extend(
        [
            "ghcr.io/dagster-io/dagster-manylinux-builder:dev" "-c",
            f"git config --global --add safe.directory /github/workspace/project-repo; /builder.pex {builder_pex_args}",
        ]
    )
    return run(["/usr/bin/docker", *github_args])


if __name__ == "__main__":
    main()
