#!/usr/bin/env python3
# /// script
# requires-python = ">=3.10"
# dependencies = [
#   "cos-python-sdk-v5>=1.9.37,<2",
#   "requests>=2.31,<3",
# ]
# ///
"""Upload explicitly selected local media to COS and create a cloud production."""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
from pathlib import Path
import sys
import time
from typing import Any
from urllib.parse import urlsplit
import uuid

import requests


API_PREFIX = "/api/rest/mva/out/cloud"
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}
PROFILES = {
    "cloud-video-production-client": {
        "environment": "production",
        "api_key_env": "FIREFLY_MVA_PROD_API_KEY",
        "fixed_base_url": None,
        "id_prefix": "prod-local-media",
    },
    "cloud-video-production-qa-debugger": {
        "environment": "qa",
        "api_key_env": "FIREFLY_MVA_QA_API_KEY",
        "fixed_base_url": "https://medi-qa.fireflyfusion.cn",
        "id_prefix": "qa-local-media",
    },
}


class WorkflowError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Upload selected local images/videos directly to COS and create a cloud video task."
    )
    parser.add_argument(
        "--input",
        action="append",
        required=True,
        dest="inputs",
        metavar="PATH",
        help="Explicitly selected local image or video; repeat for mixed inputs.",
    )
    parser.add_argument("--intent", required=True, help="Production intent sent as user_intent.")
    parser.add_argument(
        "--base-url",
        help="Environment gateway origin. Required by the production Skill; fixed in the QA Skill.",
    )
    parser.add_argument(
        "--outer-request-id",
        help="Stable idempotency identifier. A profile-prefixed value is generated when omitted.",
    )
    parser.add_argument(
        "--output-dir",
        default="outputs",
        help="Directory for the state file and downloaded result (default: ./outputs).",
    )
    parser.add_argument(
        "--wait",
        action="store_true",
        help="Poll to a terminal state, query the final result, and download the video.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=4.0,
        help="Poll interval in seconds, from 3 through 5 (default: 4).",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate and hash inputs without credentials, uploads, or API requests.",
    )
    return parser.parse_args()


def resolve_profile() -> dict[str, Any]:
    skill_name = Path(__file__).resolve().parents[1].name
    profile = PROFILES.get(skill_name)
    if profile is None:
        raise WorkflowError(f"unsupported Skill directory: {skill_name}")
    return profile


def resolve_base_url(value: str | None, profile: dict[str, Any]) -> str:
    fixed = profile["fixed_base_url"]
    candidate = fixed if value is None else value.rstrip("/")
    if candidate is None:
        raise WorkflowError("--base-url is required by the production Skill")
    if fixed is not None and candidate != fixed:
        raise WorkflowError(f"the QA Skill only permits {fixed}")
    parsed = urlsplit(candidate)
    if parsed.scheme != "https" or not parsed.netloc or parsed.path not in ("", "/"):
        raise WorkflowError("--base-url must be an HTTPS origin without a path, query, or fragment")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise WorkflowError("--base-url must not contain credentials, a query, or a fragment")
    return candidate


def resolve_inputs(values: list[str]) -> list[Path]:
    paths: list[Path] = []
    for value in values:
        path = Path(value).expanduser().resolve()
        if not path.is_file():
            raise WorkflowError("one or more selected inputs do not exist or are not regular files")
        paths.append(path)
    return paths


def media_type(path: Path) -> tuple[str, str]:
    content_type = mimetypes.guess_type(path.name)[0]
    if content_type is None:
        raise WorkflowError("an input has an unrecognized media extension")
    if content_type.startswith("image/"):
        return content_type, "image"
    if content_type.startswith("video/"):
        return content_type, "video"
    raise WorkflowError("every input must be an image or video")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def prepare_local_inputs(paths: list[Path]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for index, path in enumerate(paths, start=1):
        content_type, asset_type = media_type(path)
        size = path.stat().st_size
        if size <= 0:
            raise WorkflowError(f"input[{index}] is empty")
        prepared.append(
            {
                "path": path,
                "filename": path.name,
                "size": size,
                "content_type": content_type,
                "asset_type": asset_type,
                "content_sha256": sha256_file(path),
            }
        )
        print(f"input[{index}]: type={asset_type}, size={size}, sha256=verified", flush=True)
    return prepared


def new_request_id(profile: dict[str, Any], operation: str) -> str:
    return f"{profile['id_prefix']}-{operation}-{uuid.uuid4().hex}"


def sanitized_errors(body: dict[str, Any]) -> list[dict[str, Any]]:
    data = body.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("errors"), list):
        return []
    allowed = {"field", "reason", "asset_id", "http_status"}
    return [
        {key: value for key, value in item.items() if key in allowed}
        for item in data["errors"]
        if isinstance(item, dict)
    ]


def api_post(
    session: requests.Session,
    base_url: str,
    api_key: str,
    profile: dict[str, Any],
    endpoint: str,
    payload: dict[str, Any],
    timeout: float = 60,
) -> tuple[int, dict[str, Any], str, str | None]:
    operation = endpoint.strip("/").replace("/", "-")
    trace_id = new_request_id(profile, operation)
    response = session.post(
        f"{base_url}{API_PREFIX}{endpoint}",
        json=payload,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": api_key,
            "X-Request-ID": trace_id,
        },
        timeout=timeout,
    )
    try:
        body = response.json()
    except ValueError as exc:
        raise WorkflowError(f"{endpoint} returned non-JSON HTTP {response.status_code}") from exc
    return response.status_code, body, trace_id, response.headers.get("Retry-After")


def require_success(endpoint: str, status: int, body: dict[str, Any]) -> dict[str, Any]:
    if status < 200 or status >= 300 or body.get("code") != 200 or not body.get("success"):
        raise WorkflowError(
            f"{endpoint} failed: HTTP={status}, code={body.get('code')}, "
            f"errors={sanitized_errors(body)}"
        )
    data = body.get("data")
    if not isinstance(data, dict):
        raise WorkflowError(f"{endpoint} returned no data object")
    return data


def sdk_upload(init_data: dict[str, Any], item: dict[str, Any]) -> None:
    try:
        from qcloud_cos import CosConfig, CosS3Client
    except ImportError as exc:
        raise WorkflowError("Tencent COS SDK is missing; run this file with `uv run --script`") from exc

    credentials = init_data.get("credentials")
    required_headers = init_data.get("required_headers")
    if not isinstance(credentials, dict) or not isinstance(required_headers, dict):
        raise WorkflowError("/upload/init returned incomplete COS control data")

    metadata: dict[str, str] = {}
    upload_kwargs: dict[str, Any] = {}
    for name, value in required_headers.items():
        lower_name = name.lower()
        if lower_name == "content-type":
            upload_kwargs["ContentType"] = value
        elif lower_name.startswith("x-cos-meta-"):
            metadata[name] = value
        else:
            raise WorkflowError(f"unsupported required COS header: {name}")
    if metadata:
        upload_kwargs["Metadata"] = metadata

    try:
        config = CosConfig(
            Region=init_data["region"],
            SecretId=credentials["tmp_secret_id"],
            SecretKey=credentials["tmp_secret_key"],
            Token=credentials["session_token"],
        )
        client = CosS3Client(config)
        client.upload_file(
            Bucket=init_data["bucket"],
            Key=init_data["object_key"],
            LocalFilePath=str(item["path"]),
            PartSize=int(init_data.get("part_size_mb", 16)),
            MAXThread=5,
            EnableMD5=False,
            **upload_kwargs,
        )
    finally:
        credentials.clear()
        init_data.pop("credentials", None)


def upload_item(
    session: requests.Session,
    base_url: str,
    api_key: str,
    profile: dict[str, Any],
    item: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    status, body, trace_id, _ = api_post(
        session,
        base_url,
        api_key,
        profile,
        "/upload/init",
        {
            "filename": item["filename"],
            "size": item["size"],
            "content_type": item["content_type"],
            "content_sha256": item["content_sha256"],
        },
    )
    init_data = require_success("/upload/init", status, body)
    upload_id = init_data.get("upload_id")
    if not isinstance(upload_id, str) or not upload_id:
        raise WorkflowError("/upload/init returned no upload_id")
    print(
        f"upload/init[{index}]: request_id={trace_id}, HTTP={status}, code={body.get('code')}",
        flush=True,
    )

    sdk_upload(init_data, item)
    print(f"cos/upload[{index}]: completed", flush=True)

    for attempt in range(1, 4):
        try:
            status, body, trace_id, retry_after = api_post(
                session,
                base_url,
                api_key,
                profile,
                "/upload/complete",
                {"upload_id": upload_id},
            )
        except requests.RequestException:
            if attempt == 3:
                raise
            time.sleep(2 ** (attempt - 1))
            continue
        if body.get("code") not in (500100, 503101) or attempt == 3:
            break
        delay = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** (attempt - 1)
        time.sleep(min(delay, 30))
    complete_data = require_success("/upload/complete", status, body)
    files = complete_data.get("files")
    if not isinstance(files, list) or len(files) != 1 or not isinstance(files[0], dict):
        raise WorkflowError(f"/upload/complete returned no descriptor for input[{index}]")
    descriptor = files[0]
    if not descriptor.get("url") or descriptor.get("error"):
        raise WorkflowError(f"/upload/complete returned an unusable descriptor for input[{index}]")
    descriptor_type = descriptor.get("type")
    if descriptor_type not in {"image", "video"}:
        raise WorkflowError(f"/upload/complete returned an invalid media type for input[{index}]")
    print(
        f"upload/complete[{index}]: request_id={trace_id}, HTTP={status}, code={body.get('code')}",
        flush=True,
    )
    return {
        "asset_id": f"{profile['id_prefix']}-asset-{index:03d}",
        "asset_type": descriptor_type,
        "asset_url": descriptor["url"],
        "content_sha256": descriptor.get("content_sha256") or item["content_sha256"],
    }


def write_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def create_task(
    session: requests.Session,
    base_url: str,
    api_key: str,
    profile: dict[str, Any],
    payload: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            status, body, trace_id, retry_after = api_post(
                session, base_url, api_key, profile, "/make", payload, timeout=120
            )
        except requests.RequestException as exc:
            last_error = exc
            if attempt == 3:
                break
            time.sleep(2 ** (attempt - 1))
            continue
        code = body.get("code")
        if code in (200, 409102):
            data = body.get("data")
            if not isinstance(data, dict) or not data.get("conversation_id"):
                raise WorkflowError("/make returned no conversation_id")
            print(
                f"make: request_id={trace_id}, HTTP={status}, code={code}, status={data.get('status')}",
                flush=True,
            )
            return data, trace_id
        if code not in (429100, 503100, 503101) or attempt == 3:
            raise WorkflowError(
                f"/make failed: HTTP={status}, code={code}, errors={sanitized_errors(body)}"
            )
        delay = float(retry_after) if retry_after and retry_after.isdigit() else 2 ** (attempt - 1)
        time.sleep(min(delay, 30))
    raise WorkflowError(f"/make failed after bounded retries: {type(last_error).__name__}")


def poll_to_terminal(
    session: requests.Session,
    base_url: str,
    api_key: str,
    profile: dict[str, Any],
    conversation_id: str,
    interval: float,
    state_path: Path,
    state: dict[str, Any],
) -> dict[str, Any]:
    last_snapshot: tuple[Any, Any, Any] | None = None
    while True:
        status, body, trace_id, _ = api_post(
            session,
            base_url,
            api_key,
            profile,
            "/poll",
            {"conversation_id": conversation_id},
        )
        data = body.get("data") if isinstance(body.get("data"), dict) else {}
        snapshot = (data.get("status"), data.get("current_node"), data.get("current_node_description"))
        if snapshot != last_snapshot:
            print(
                f"poll: request_id={trace_id}, HTTP={status}, code={body.get('code')}, "
                f"status={snapshot[0]}, node={snapshot[1]}, description={snapshot[2]}",
                flush=True,
            )
            last_snapshot = snapshot
        state.update({"status": snapshot[0], "current_node": snapshot[1], "request_id": trace_id})
        write_state(state_path, state)
        if snapshot[0] in TERMINAL_STATUSES:
            return data
        if status < 200 or status >= 300 or body.get("code") != 200:
            raise WorkflowError(f"/poll failed: HTTP={status}, code={body.get('code')}")
        time.sleep(interval)


def query_and_download(
    session: requests.Session,
    base_url: str,
    api_key: str,
    profile: dict[str, Any],
    conversation_id: str,
    poll_data: dict[str, Any],
    output_dir: Path,
) -> tuple[Path, str]:
    status, body, trace_id, _ = api_post(
        session,
        base_url,
        api_key,
        profile,
        "/queryResult",
        {"conversation_id": conversation_id},
    )
    data = require_success("/queryResult", status, body)
    final_result = data.get("final_video_result")
    if not isinstance(final_result, dict):
        final_result = {}
    video_url = data.get("video_url") or final_result.get("video_url") or poll_data.get("video_url")
    if not isinstance(video_url, str) or not video_url:
        raise WorkflowError("the completed task returned no video_url")
    print(
        f"queryResult: request_id={trace_id}, HTTP={status}, code={body.get('code')}",
        flush=True,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"cloud-video-{conversation_id}.mp4"
    with session.get(video_url, stream=True, timeout=(30, 300)) as response:
        response.raise_for_status()
        with output_file.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    return output_file, trace_id


def main() -> int:
    args = parse_args()
    profile = resolve_profile()
    base_url = resolve_base_url(args.base_url, profile)
    if not 3 <= args.poll_interval <= 5:
        raise WorkflowError("--poll-interval must be between 3 and 5 seconds")
    paths = resolve_inputs(args.inputs)
    prepared = prepare_local_inputs(paths)
    if args.validate_only:
        counts = {kind: sum(item["asset_type"] == kind for item in prepared) for kind in ("image", "video")}
        print(
            f"validation: environment={profile['environment']}, images={counts['image']}, "
            f"videos={counts['video']}, API_requests=0",
            flush=True,
        )
        return 0

    api_key = os.environ.get(profile["api_key_env"])
    if not api_key:
        raise WorkflowError(f"{profile['api_key_env']} is not configured")

    outer_request_id = args.outer_request_id or f"{profile['id_prefix']}-{uuid.uuid4().hex}"
    output_dir = Path(args.output_dir).expanduser().resolve()
    state_hash = hashlib.sha256(outer_request_id.encode("utf-8")).hexdigest()[:16]
    state_path = output_dir / f"cloud-video-state-{state_hash}.json"
    state: dict[str, Any] = {
        "environment": profile["environment"],
        "outer_request_id": outer_request_id,
        "conversation_id": None,
        "request_id": None,
        "status": "uploading",
        "current_node": None,
    }
    write_state(state_path, state)
    print(
        f"workflow: environment={profile['environment']}, outer_request_id={outer_request_id}, "
        f"state_file={state_path.name}",
        flush=True,
    )

    session = requests.Session()
    health_trace_id = new_request_id(profile, "health")
    health = session.get(
        f"{base_url}/api/rest/mva/health",
        headers={"X-Request-ID": health_trace_id},
        timeout=20,
    )
    print(f"health: request_id={health_trace_id}, HTTP={health.status_code}", flush=True)
    if health.status_code < 200 or health.status_code >= 300:
        raise WorkflowError(f"health check failed: HTTP={health.status_code}")

    assets = [
        upload_item(session, base_url, api_key, profile, item, index)
        for index, item in enumerate(prepared, start=1)
    ]
    make_data, make_trace_id = create_task(
        session,
        base_url,
        api_key,
        profile,
        {"user_intent": args.intent, "assets": assets, "outer_request_id": outer_request_id},
    )
    conversation_id = make_data["conversation_id"]
    state.update(
        {
            "conversation_id": conversation_id,
            "request_id": make_trace_id,
            "status": make_data.get("status"),
        }
    )
    write_state(state_path, state)
    print(f"task: conversation_id={conversation_id}", flush=True)
    if not args.wait:
        print("result: task created; rerun the Skill with the persisted conversation_id to track it", flush=True)
        return 0

    poll_data = poll_to_terminal(
        session,
        base_url,
        api_key,
        profile,
        conversation_id,
        args.poll_interval,
        state_path,
        state,
    )
    if poll_data.get("status") != "completed":
        errors = poll_data.get("error_messages") if isinstance(poll_data.get("error_messages"), list) else []
        raise WorkflowError(f"task ended with status={poll_data.get('status')}, errors_count={len(errors)}")

    output_file, query_trace_id = query_and_download(
        session, base_url, api_key, profile, conversation_id, poll_data, output_dir
    )
    state.update({"status": "completed", "current_node": "completed", "request_id": query_trace_id})
    write_state(state_path, state)
    print(f"result: filename={output_file.name}, size={output_file.stat().st_size}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (WorkflowError, requests.RequestException, OSError, KeyError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
