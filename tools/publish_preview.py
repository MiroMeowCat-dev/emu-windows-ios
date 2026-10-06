"""Publish the already verified CI preview, without rebuilding or game content."""
import hashlib
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from zipfile import ZipFile

from .common import ROOT

TAG = "v0.2.0-preview"
COMMIT = "356efec09e3ae973f031a981b141cb3b52a721ad"
STARTER_SHA = "71840ee03b91644f04f7021b17ad75af3a112ecdaea20994b4516bbd99bb2a40"
IPA_SHA = "5982c2c76babb4df127dca2336ca688614148e286ba8ac5d46517fa42f1bc0b3"


def publish(path, repository):
    # This helper is intentionally limited to the one preview and owned repo.
    if repository != "MiroMeowCat-dev/emu-windows-ios":
        raise ValueError("This preview publisher is restricted to its original repository.")
    starter = Path(path).read_bytes()
    if hashlib.sha256(starter).hexdigest() != STARTER_SHA:
        raise ValueError("Starter differs from the verified CI artifact.")
    with ZipFile(path) as archive:
        if archive.testzip():
            raise ValueError("Starter CRC check failed.")
        ipa = archive.read("EmuWindows/diagnostic/EmuCheck-unsigned.ipa")
        receipt = json.loads(archive.read("EmuWindows/diagnostic/EmuCheck-unsigned.json"))
        report = json.loads(archive.read("EmuWindows/starter-check.json"))
        if (hashlib.sha256(ipa).hexdigest() != IPA_SHA or receipt.get("diagnostic_only") is not True
                or receipt.get("binaries") or receipt.get("signing_state") != "unsigned"
                or report.get("runtime_source_commit") != COMMIT or report.get("windows_source_commit") != COMMIT):
            raise ValueError("Diagnostic content or build provenance differs.")
    token = os.environ["GITHUB_TOKEN"]

    def request(url, data=None, method="GET", content_type="application/json"):
        if urllib.parse.urlparse(url).netloc not in {"api.github.com", "uploads.github.com"}:
            raise ValueError("Unexpected GitHub API host.")
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": "Bearer " + token, "Accept": "application/vnd.github+json",
            "Content-Type": content_type, "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "emu-preview-publisher"})
        with urllib.request.urlopen(req, timeout=120) as response:
            return json.load(response)

    api = "https://api.github.com/repos/" + repository
    body = (ROOT / "docs/RELEASE-0.2.md").read_text(encoding="utf-8")
    matches = [item for item in request(api + "/releases?per_page=100") if item.get("tag_name") == TAG]
    if len(matches) > 1:
        raise ValueError("Multiple releases use the preview tag; inspect before retrying.")
    if matches:
        release = matches[0]
    else:
        # Draft until every asset has been uploaded and checked.
        release = request(api + "/releases", json.dumps({"tag_name": TAG, "target_commitish": COMMIT,
                          "name": "Emu Windows 0.2 预览版 · 无需自备 Mac", "body": body,
                          "draft": True, "prerelease": True}).encode(), method="POST")
    if release.get("target_commitish") != COMMIT or not release.get("prerelease") or release.get("body") != body:
        raise ValueError("An existing release differs; inspect it before retrying.")
    sums = (STARTER_SHA + "  EmuWindows-starter.zip\n" + IPA_SHA + "  EmuCheck-unsigned.ipa\n").encode()
    assets = {"EmuWindows-starter.zip": starter, "EmuCheck-unsigned.ipa": ipa, "SHA256SUMS.txt": sums}
    uploaded = {asset["name"]: asset for asset in release.get("assets", [])}
    upload_url = release["upload_url"].split("{", 1)[0]
    for name, data in assets.items():
        expected = "sha256:" + hashlib.sha256(data).hexdigest()
        if name in uploaded:
            asset = uploaded[name]
            if asset.get("size") != len(data) or asset.get("digest") != expected:
                raise ValueError("Existing asset differs: " + name)
        else:
            asset = request(upload_url + "?name=" + urllib.parse.quote(name), data, method="POST",
                            content_type="application/octet-stream")
            if asset.get("state") != "uploaded" or asset.get("size") != len(data) or asset.get("digest") != expected:
                raise ValueError("Uploaded asset verification failed: " + name)
        print("Verified release asset: " + name)
    if release.get("draft"):
        release = request(api + "/releases/" + str(release["id"]), b'{"draft":false}', method="PATCH")
    print("Preview published: " + release["html_url"])


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--starter", required=True)
    parser.add_argument("--repository", required=True)
    args = parser.parse_args()
    publish(args.starter, args.repository)
