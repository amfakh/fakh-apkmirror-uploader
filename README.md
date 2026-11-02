# Fakh APKMirror Uploader

Upload APKs to APKMirror from your desktop. A single-file Python script that reproduces the
"Upload to APKMirror" flow from ML Manager 5.0, so you don't need the Android app.

By default it sends the files straight to APKMirror as one multipart `POST /upload/`.
Optionally it first asks APKMirror which files it does not already have:

1. MD5 every APK file (base plus any split configs).
2. `POST /apk_uploadable/` with those hashes.
3. Upload only the files APKMirror marks `uploadable`.

## Requirements

Only [`uv`](https://docs.astral.sh/uv/). Dependencies are declared inline in the script,
so `uv run` installs them on the fly, with no virtualenv to manage.

## Usage

Upload a version:

```bash
uv run apkmirror_upload.py --changes "What's new in this version" \
  base.apk split_config.en.apk split_config.xxhdpi.apk
```

Pass the base APK and every split for one version together. A single file is sent as the
`file` part; several are sent as `file[]`. If APKMirror already has the build it rejects
the upload and points to the existing listing, so a duplicate costs only the bandwidth.

Ask APKMirror first and upload only the new files (`--check`), or just look without
uploading (`--check-only`). Both need the check credentials below:

```bash
uv run apkmirror_upload.py --check-only base.apk split_config.en.apk split_config.xxhdpi.apk
```

Each line is one file's status (`uploadable`, `dupe`, `similar`, ...) with its MD5 and,
when known, the existing APKMirror listing.

A `.apkm`, `.apks`, or `.xapk` bundle works too. The script unpacks it and sends the APKs
inside, since APKMirror's upload endpoint takes plain APKs, not bundles:

```bash
uv run apkmirror_upload.py --check-only "Some App_1.2.3.xapk"
```

## Configuration

Settings come from the environment, so keep them in a `.env` file:

```ini
NAME=Your Name
EMAIL=you@example.com

# Optional: only needed for --check and --check-only
APKM_CHECK_USER=...
APKM_CHECK_PASS=...
```

| Variable | Required | Purpose |
|---|---|---|
| `NAME` | to upload | Uploader name sent with the upload |
| `EMAIL` | to upload | Uploader email sent with the upload |
| `APKM_CHECK_USER` | for checks | Basic-auth user for the uploadable check |
| `APKM_CHECK_PASS` | for checks | Basic-auth password for the uploadable check |

`--name` and `--email` override `NAME` and `EMAIL` when passed.

A plain upload needs just `NAME` and `EMAIL`, because the upload endpoint takes no auth.
Only the uploadable check does, so leave the `APKM_CHECK_*` variables out unless you run
`--check` or `--check-only`. `--check-only` does not need the name or email. The check
credentials are not part of ML Manager's open-source code and are not bundled here, so you
supply them yourself.

## Notes

- Uploading publishes the APK to APKMirror, where it is public and gets indexed. The name
  and email you set are sent with the upload and the submission is bound to them.
- With `--check`, a `similar` or `dupe` status for every file means APKMirror already has
  that build, so nothing is uploaded.
- This is an unofficial tool, not affiliated with or endorsed by ML Manager or APKMirror.

## License

[MIT](LICENSE)
