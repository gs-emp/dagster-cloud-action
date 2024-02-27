#!/usr/bin/env python

# Switches PEX deploy behavior based on github runner's ubuntu version
# - ubuntu-20.04 can always build pexes that work on our target platform
# - ubuntu-22.04 can only build pexes if there are no sdists (source only packages)

# On ubuntu-20.04: forward args to `dagster-cloud --build-method=local`
# On ubuntu-22.04: forward args to `dagster-cloud --build-method=docker`
# - Sometimes 22.04 may try to build sdists but build the wrong version (since we are not yet
#   using --complete-platform for pex). To avoid this situation, we always build dependencies in the
#   right docker environment on 22.04. Note if dependencies are not being built, docker will not
#   be used. The source.pex is always built using the local environment.

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

import yaml

DAGSTER_CLOUD_PEX_PATH = (
    Path(__file__).parent.parent / "generated/gha/dagster-cloud.pex"
)
UPDATE_COMMENT_SCRIPT_PATH = Path(__file__).parent / "create_or_update_comment.py"


def main():
    args = sys.argv[1:]

    if os.getenv("GITHUB_EVENT_NAME") == "pull_request":
        print("Running in a pull request - going to do a branch deployment", flush=True)
        dagster_cloud_yaml = args[0]
        project_dir = os.path.dirname(dagster_cloud_yaml)
        deployment_name = get_branch_deployment_name(project_dir)
    else:
        # INPUT_DEPLOYMENT is to the `deployment:` input value in action.yml
        deployment_name = os.getenv("INPUT_DEPLOYMENT", "prod")
        print(f"Deploying to a full deployment: {deployment_name}", flush=True)

    ubuntu_version = get_runner_ubuntu_version()
    print("Running on Ubuntu", ubuntu_version, flush=True)
    if ubuntu_version == "20.04":
        returncode, output = deploy_pex(args, deployment_name, build_method="local")
    else:
        returncode, output = deploy_pex(args, deployment_name, build_method="docker")
    if returncode:
        print(
            "::error Title=Deploy failed::Failed to deploy Python Executable. "
            "Try disabling fast deploys by setting `ENABLE_FAST_DEPLOYS: 'false'` in your .github/workflows/*yml."
        )
        # TODO: fallback to docker deploy here
        sys.exit(1)


def get_runner_ubuntu_version():
    release_info = open("/etc/lsb-release", encoding="utf-8").read()
    # Example:
    # DISTRIB_ID=Ubuntu
    # DISTRIB_RELEASE=22.04
    # DISTRIB_CODENAME=jammy
    # DISTRIB_DESCRIPTION="Ubuntu 22.04.1 LTS"
    for line in release_info.splitlines(keepends=False):
        if line.startswith("DISTRIB_RELEASE="):
            return line.split("=", 1)[1]
    return "22.04"  # fallback to safer behavior


def get_locations(dagster_cloud_file) -> List[str]:
    with open(dagster_cloud_file) as f:
        workspace_contents = f.read()
    workspace_contents_yaml = yaml.safe_load(workspace_contents)

    return [
        location["location_name"] for location in workspace_contents_yaml["locations"]
    ]


def run(args):
    # Prints streaming output and also captures and returns it
    print("Running", args, flush=True)
    popen = subprocess.Popen(
        args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8"
    )
    output = []
    for line in iter(popen.stdout.readline, ""):
        print(line, end="", flush=True)
        output.append(line)
    popen.stdout.close()
    returncode = popen.wait()
    return returncode, output


def get_branch_deployment_name(project_dir):
    returncode, output = run(
        [
            str(DAGSTER_CLOUD_PEX_PATH),
            "-m",
            "dagster_cloud_cli.entrypoint",
            "ci",
            "branch-deployment",
            project_dir,
        ]
    )
    if returncode:
        print("Could not determine branch deployment", flush=True)
        sys.exit(1)
    name = "".join(output).strip()
    print("Deploying to branch deployment:", name, flush=True)
    return name


def deploy_pex(args, branch_deployment_name: Optional[str], build_method: str):
    dagster_cloud_yaml = args.pop(0)
    args.insert(0, os.path.dirname(dagster_cloud_yaml))
    args = args + [f"--build-method={build_method}"]
    commit_hash = os.getenv("GITHUB_SHA")
    git_url = f"{os.getenv('GITHUB_SERVER_URL')}/{os.getenv('GITHUB_REPOSITORY')}/tree/{commit_hash}"
    deployment_name = branch_deployment_name if branch_deployment_name else "prod"
    deployment_flag = f"--url={os.getenv('DAGSTER_CLOUD_URL')}/{deployment_name}"
    locations = get_locations(dagster_cloud_yaml)
    timeout_args = [
        "--location-load-timeout=3600",
        "--agent-heartbeat-timeout=600",
    ]
    notify(branch_deployment_name, locations, "pending")

    returncode, output = run(
        [
            str(DAGSTER_CLOUD_PEX_PATH),
            "-m",
            "dagster_cloud_cli.entrypoint",
            "serverless",
            "deploy-python-executable",
            *args,
            "--location-name=*",
            f"--location-file={dagster_cloud_yaml}",
            f"--git-url={git_url}",
            f"--commit-hash={commit_hash}",
            deployment_flag,
            *timeout_args,
        ]
    )
    # TODO: status update should be per location, but this is not reported by the deploy command yet
    if returncode:
        notify(branch_deployment_name, locations, "failed")
    else:
        notify(branch_deployment_name, locations, "success")
    return returncode, output


def notify(deployment_name: Optional[str], locations: List[str], action: str):
    if deployment_name is None:
        return
    for location_name in locations:
        update_pr_comment(deployment_name, location_name, action)


def update_pr_comment(deployment_name: str, location_name: str, action: str):
    # action is one of "pending", "success", "failed"
    pr_id = get_pr_number()
    if not pr_id:
        print("Not in a pull request, will not post PR comment", flush=True)
        return

    if not UPDATE_COMMENT_SCRIPT_PATH.exists:
        print("Could not find script_path, will not post PR comment", flush=True)
        return

    env = dict(os.environ)
    github_run_url = f'{os.environ["GITHUB_SERVER_URL"]}/{os.environ["GITHUB_REPOSITORY"]}/actions/runs/{os.environ["GITHUB_RUN_ID"]}'
    env.update(
        {
            "INPUT_PR": str(pr_id),
            "INPUT_ACTION": action,
            "INPUT_DEPLOYMENT": deployment_name,
            "INPUT_LOCATION_NAME": location_name,
            "GITHUB_RUN_URL": github_run_url,
        }
    )
    env = {name: value for name, value in env.items() if value is not None}
    proc = subprocess.run(
        [str(DAGSTER_CLOUD_PEX_PATH), str(UPDATE_COMMENT_SCRIPT_PATH)],
        env=env,
        check=False,
    )

    if proc.returncode:
        print(
            f"Ignoring failure to update PR comment: {proc.stdout}\n{proc.stderr}",
            flush=True,
        )


def get_pr_number():
    # Extract pull request number from GITHUB_REF
    # https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#pull-request-event-pull_request
    github_ref = os.getenv("GITHUB_REF", "")
    mo = re.match(r"refs/pull/(\d+)", github_ref)
    if not mo:
        return None
    return mo.group(1)


if __name__ == "__main__":
    main()
