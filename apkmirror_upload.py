# /// script
# requires-python = ">=3.12"
# dependencies = ["requests>=2.32", "python-dotenv>=1.0"]
# ///
"""Upload APKs to APKMirror the way ML Manager 5.0 does it.

Mirrors s1.f / s1.q / t1.d from the decompiled app:
1. MD5 every file, POST the hashes to /apk_uploadable/ (basic auth baked into the app).
2. Upload only the files whose status is "uploadable" as one multipart POST to /upload/.

Bundles (.apkm, .apks, .xapk) are unpacked first and their inner APKs sent one by one,
since the app never uploads a bundle either.
"""

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import quote_plus

import requests
from dotenv import load_dotenv

BASE_URL = "https://www.apkmirror.com/wp-json/apkm/v1"
VERSION = "0.1.0"
HEADERS = {"User-Agent": f"Fakh APKMirror Uploader/{VERSION}"}

# Basic-auth for the uploadable check. The upload API is not part of ML Manager's
# open-source code, so its credentials are not shipped here: supply both yourself
# via the environment.
CHECK_USER = os.getenv("APKM_CHECK_USER")
CHECK_PASS = os.getenv("APKM_CHECK_PASS")

# Status messages, worded here rather than copied from the app.
MSG_UPLOADING = "Uploading {name}..."
MSG_UPLOADED = "Uploaded {name}"
MSG_UPLOADED_DESC = "APKMirror reviews uploads before they go live. You get an email if it is published."
MSG_ALREADY = "{name} is already on APKMirror"
MSG_ALREADY_DESC = "This build is already available on APKMirror."
MSG_ERROR = "Upload failed"
MSG_OFFLINE = "Could not reach APKMirror"
MSG_OFFLINE_DESC = "No connection, or APKMirror is down. Try again later."


def md5_of(path: Path) -> str:
    """Hash a file in 8 KiB chunks, like u1.a.

    Args:
        path: File to hash.

    Returns:
        Lowercase 32-char hex MD5 digest.
    """
    digest = hashlib.md5()
    with path.open("rb") as f:
        while chunk := f.read(8192):
            digest.update(chunk)
    return digest.hexdigest()


def expand_bundles(paths: list[Path], workdir: Path) -> list[Path]:
    """Replace every .apkm/.apks/.xapk with the APKs inside it.

    Args:
        paths: Input files; plain APKs pass through unchanged.
        workdir: Empty directory to unpack bundles into.

    Returns:
        Plain APK files only, in input order.

    Raises:
        ValueError: A bundle holds no APK.
    """
    apks: list[Path] = []
    for path in paths:
        if path.suffix.lower() not in {".apkm", ".apks", ".xapk"}:
            apks.append(path)
            continue
        dest = workdir / path.stem
        dest.mkdir()
        with zipfile.ZipFile(path) as zf:
            members = [m for m in zf.infolist() if m.filename.lower().endswith(".apk")]
            if not members:
                raise ValueError(f"{path.name} holds no APK")
            for m in members:
                # Basename only, so a crafted member path cannot escape workdir.
                out = dest / Path(m.filename).name
                with zf.open(m) as src, out.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
                apks.append(out)
    return apks


def check_uploadable(files: list[Path]) -> tuple[list[Path], list[dict]]:
    """Ask APKMirror which of the files it does not have yet (API.checkAPK).

    Args:
        files: APK files of one app version (base plus splits).

    Returns:
        The files APKMirror marks "uploadable", and the raw status entries.

    Raises:
        SystemExit: APKM_CHECK_USER or APKM_CHECK_PASS is not set.
    """
    if not (CHECK_USER and CHECK_PASS):
        raise SystemExit("Set APKM_CHECK_USER and APKM_CHECK_PASS for the upload API.")
    by_md5 = {md5_of(f): f for f in files}
    resp = requests.post(
        f"{BASE_URL}/apk_uploadable/",
        json={"md5s": list(by_md5)},
        auth=(CHECK_USER, CHECK_PASS),
        headers=HEADERS,
        timeout=60,
    )
    resp.raise_for_status()
    entries = resp.json()
    return [
        by_md5[e["md5"]] for e in entries if e.get("status") == "uploadable"
    ], entries


def upload(files: list[Path], fullname: str, email: str, changes: str) -> dict:
    """Send the files in one multipart request (API.uploadAPK, called from s1.f.r).

    Args:
        files: Files to upload; a single file goes as "file", several as "file[]".
        fullname: Uploader name shown on APKMirror.
        email: Uploader email.
        changes: Release notes ("what's new").

    Returns:
        Parsed JSON body: {"success": bool, "data": str} on 2xx, {"result": str} on error.
    """
    field = "file" if len(files) == 1 else "file[]"
    handles = [f.open("rb") for f in files]
    try:
        resp = requests.post(
            f"{BASE_URL}/upload/",
            data={"fullname": fullname, "email": email, "changes": changes},
            files=[
                (field, (quote_plus(f.name), h, "application/octet-stream"))
                for f, h in zip(files, handles, strict=True)
            ],
            headers=HEADERS,
            timeout=300,
        )
    finally:
        for h in handles:
            h.close()
    try:
        return resp.json()
    except ValueError:
        return {"success": False, "data": resp.text, "status": resp.status_code}


def main() -> int:
    """Parse arguments, then upload the files (checking them first on request).

    Returns:
        Process exit code.
    """
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "apks",
        nargs="+",
        type=Path,
        help="base.apk plus any split_*.apk of one version, or a .apkm/.apks/.xapk",
    )
    parser.add_argument(
        "--name", default=os.getenv("NAME"), help="uploader full name (env: NAME)"
    )
    parser.add_argument(
        "--email", default=os.getenv("EMAIL"), help="uploader email (env: EMAIL)"
    )
    parser.add_argument("--changes", default="", help="what's new in this version")
    parser.add_argument(
        "--check",
        action="store_true",
        help="ask APKMirror first and upload only the new files (needs APKM_CHECK_*)",
    )
    parser.add_argument(
        "--check-only", action="store_true", help="only ask APKMirror, upload nothing"
    )
    args = parser.parse_args()

    with tempfile.TemporaryDirectory() as workdir:
        return run(parser, args, expand_bundles(args.apks, Path(workdir)))


def run(
    parser: argparse.ArgumentParser, args: argparse.Namespace, apks: list[Path]
) -> int:
    """Upload the APKs, optionally asking APKMirror first which ones are new.

    Args:
        parser: Parser, for reporting missing upload arguments.
        args: Parsed command-line arguments.
        apks: Plain APK files of one app version.

    Returns:
        Process exit code.
    """
    name = apks[0].stem
    uploadable = apks
    if args.check or args.check_only:
        uploadable, entries = check_uploadable(apks)
        for e in entries:
            line = f"{e.get('status'):<12} {e.get('md5')}  {e.get('title') or ''} {e.get('link') or ''}"
            print(line.rstrip())
        if not entries:
            # Empty reply is the app's "APKMirror offline" branch.
            print(MSG_OFFLINE)
            print(MSG_OFFLINE_DESC)
            return 1
        if not uploadable:
            print(MSG_ALREADY.format(name=name))
            print(MSG_ALREADY_DESC)
            return 0
        print("Uploadable:", ", ".join(f.name for f in uploadable))
        if args.check_only:
            return 0
    if not (args.name and args.email):
        parser.error("--name and --email are required to upload")

    print(MSG_UPLOADING.format(name=name))
    result = upload(uploadable, args.name, args.email, args.changes)
    if result.get("success"):
        print(MSG_UPLOADED.format(name=name))
        print(MSG_UPLOADED_DESC)
        return 0
    # success=false or an HTTP error: a link in the body means APKMirror already
    # has it (the app's "already uploaded" branch); otherwise it is a real error.
    body = str(result.get("data") or result.get("result") or "")
    if "http" in body:
        print(MSG_ALREADY_DESC)
    else:
        print(MSG_ERROR)
    if body:
        print(body)
    return 1


if __name__ == "__main__":
    sys.exit(main())
