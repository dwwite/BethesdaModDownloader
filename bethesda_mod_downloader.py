#!/usr/bin/env python3
"""Dwwite downloader for Bethesda.net and Creations links."""

from __future__ import annotations

import argparse
import json
import os
import queue
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Any, Callable


CORE_CONFIG_URL = "https://cdn.bethesda.net/data/core"
DEFAULT_OUTPUT_DIR = "downloads"
HTTP_TIMEOUT_SECONDS = 30
USER_AGENT = "DwwiteDownloader/1.0"


PRODUCT_ALIASES = {
    "fallout4": "fallout4",
    "fallout 4": "fallout4",
    "fo4": "fallout4",
    "skyrim": "skyrim",
    "skyrimse": "skyrim",
    "skyrim special edition": "skyrim",
    "sse": "skyrim",
    "starfield": "starfield",
}

PLATFORM_ALIASES = {
    "PC": "WINDOWS",
    "WINDOWS": "WINDOWS",
    "WIN": "WINDOWS",
    "XB1": "XB1",
    "XBOXONE": "XB1",
    "XBOX1": "XB1",
    "XBOX": "XB1",
    "XBOXSERIESX": "XBOXSERIESX",
    "SERIESX": "XBOXSERIESX",
    "SERIESS": "XBOXSERIESX",
    "PS4": "PS4",
    "PLAYSTATION4": "PS4",
    "PLAYSTATION": "PS4",
    "PS5": "PLAYSTATION5",
    "PLAYSTATION5": "PLAYSTATION5",
}


class DownloaderError(RuntimeError):
    """Raised when the downloader cannot resolve or fetch a mod."""


@dataclass
class ResolvedIdentifier:
    product: str
    content_id: str
    detail: dict[str, Any]
    resolution_note: str


def normalize_product(value: str | None) -> str:
    if not value:
        return "fallout4"
    cleaned = value.strip().lower()
    if cleaned in PRODUCT_ALIASES:
        return PRODUCT_ALIASES[cleaned]
    raise DownloaderError(
        f"Unsupported product '{value}'. Supported products: fallout4, skyrim, starfield."
    )


def normalize_platform(value: str | None) -> str:
    if not value:
        return "WINDOWS"
    cleaned = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    return PLATFORM_ALIASES.get(cleaned, cleaned)


def sanitize_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    cleaned = cleaned.strip("._-")
    return cleaned or "file"


def slugify_for_search(value: str) -> str:
    return re.sub(r"[_\W]+", " ", value).strip().lower()


def coalesce(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


class BethesdaModDownloader:
    def __init__(self) -> None:
        self._core_config: dict[str, Any] | None = None

    def get_core_config(self) -> dict[str, Any]:
        if self._core_config is None:
            self._core_config = self._request_json(CORE_CONFIG_URL)
        return self._core_config

    def get_base_api(self) -> str:
        config = self.get_core_config()
        base_api = (
            config.get("baseUri", {}).get("baseapi")
            or "https://api.bethesda.net"
        )
        return str(base_api).rstrip("/")

    def get_bnet_key(self) -> str:
        config = self.get_core_config()
        bnet_key = config.get("ugc", {}).get("bnetKey")
        if not bnet_key:
            raise DownloaderError("Could not retrieve Bethesda UGC API key from core config.")
        return str(bnet_key)

    def api_headers(self, product: str) -> dict[str, str]:
        return {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "Content-Type": "application/json",
            "x-bnet-product": product,
            "x-bnet-key": self.get_bnet_key(),
        }

    def _request_json(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        method: str = "GET",
        data: bytes | None = None,
    ) -> dict[str, Any]:
        request = urllib.request.Request(
            url=url,
            headers=headers or {"User-Agent": USER_AGENT, "Accept": "application/json"},
            method=method,
            data=data,
        )
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            try:
                payload = json.loads(body)
                platform = payload.get("platform", {})
                message = platform.get("message") or payload.get("message") or body
            except json.JSONDecodeError:
                message = body or exc.reason
            raise DownloaderError(f"HTTP {exc.code}: {message}") from exc
        except urllib.error.URLError as exc:
            raise DownloaderError(f"Network error while requesting {url}: {exc}") from exc

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise DownloaderError(f"Expected JSON from {url}, got invalid response.") from exc

    def search_mods(
        self,
        *,
        product: str,
        text: str | None = None,
        legacy_id: int | None = None,
        content_ids: list[str] | None = None,
        size: int = 100,
        page: int = 1,
    ) -> list[dict[str, Any]]:
        params: dict[str, str] = {
            "product": product,
            "size": str(size),
            "page": str(page),
        }
        if text:
            params["text"] = text
        if legacy_id is not None:
            params["legacy_content_ids"] = str(legacy_id)
        if content_ids:
            params["content_ids"] = ",".join(content_ids)

        url = f"{self.get_base_api()}/ugcmods/v1/content?{urllib.parse.urlencode(params)}"
        payload = self._request_json(url, headers=self.api_headers(product))
        response = payload.get("platform", {}).get("response", {})
        return list(response.get("data") or [])

    def get_mod_detail(
        self,
        *,
        product: str,
        content_id: str,
    ) -> dict[str, Any]:
        url = f"{self.get_base_api()}/ugcmods/v1/content/{urllib.parse.quote(content_id)}"
        payload = self._request_json(url, headers=self.api_headers(product))
        response = payload.get("platform", {}).get("response")
        if not isinstance(response, dict):
            raise DownloaderError("Bethesda API returned an unexpected mod detail payload.")
        return response

    def resolve_identifier(
        self,
        raw_identifier: str,
        *,
        product: str,
        max_search_results: int = 100,
    ) -> ResolvedIdentifier:
        identifier = raw_identifier.strip()
        if not identifier:
            raise DownloaderError("Please provide a mod URL, ID, or search text.")

        url_product, parsed = self._parse_url_identifier(identifier)
        product_slug = normalize_product(url_product or product)

        if parsed and parsed.get("content_id"):
            content_id = parsed["content_id"]
            detail = self.get_mod_detail(product=product_slug, content_id=content_id)
            return ResolvedIdentifier(
                product=product_slug,
                content_id=content_id,
                detail=detail,
                resolution_note=f"Resolved direct content ID {content_id}.",
            )

        if parsed and parsed.get("legacy_id"):
            legacy_id = int(parsed["legacy_id"])
            matches = self.search_mods(
                product=product_slug,
                legacy_id=legacy_id,
                size=max_search_results,
            )
            if not matches:
                raise DownloaderError(f"No mod found for legacy ID {legacy_id}.")
            chosen = matches[0]
            content_id = str(chosen["content_id"])
            detail = self.get_mod_detail(product=product_slug, content_id=content_id)
            return ResolvedIdentifier(
                product=product_slug,
                content_id=content_id,
                detail=detail,
                resolution_note=f"Resolved legacy ID {legacy_id} to content ID {content_id}.",
            )

        if parsed and parsed.get("content_uuid") and parsed.get("slug_text"):
            content_uuid = parsed["content_uuid"].lower()
            matches = self.search_mods(
                product=product_slug,
                text=parsed["slug_text"],
                size=max_search_results,
            )
            chosen = next(
                (
                    item
                    for item in matches
                    if str(item.get("content_uuid", "")).lower() == content_uuid
                ),
                None,
            )
            if chosen is None:
                raise DownloaderError(
                    "Could not resolve the Creations URL to a content ID. "
                    "Try a legacy Bethesda.net URL or a text search."
                )
            content_id = str(chosen["content_id"])
            detail = self.get_mod_detail(product=product_slug, content_id=content_id)
            return ResolvedIdentifier(
                product=product_slug,
                content_id=content_id,
                detail=detail,
                resolution_note=f"Resolved content UUID {content_uuid} to content ID {content_id}.",
            )

        if identifier.isdigit():
            numeric = identifier
            try:
                detail = self.get_mod_detail(product=product_slug, content_id=numeric)
                return ResolvedIdentifier(
                    product=product_slug,
                    content_id=numeric,
                    detail=detail,
                    resolution_note=f"Resolved numeric input {numeric} as a content ID.",
                )
            except DownloaderError:
                matches = self.search_mods(
                    product=product_slug,
                    legacy_id=int(numeric),
                    size=max_search_results,
                )
                if not matches:
                    raise DownloaderError(
                        f"Numeric input {numeric} did not resolve as a content ID or legacy ID."
                    )
                chosen = matches[0]
                content_id = str(chosen["content_id"])
                detail = self.get_mod_detail(product=product_slug, content_id=content_id)
                return ResolvedIdentifier(
                    product=product_slug,
                    content_id=content_id,
                    detail=detail,
                    resolution_note=(
                        f"Resolved numeric input {numeric} as legacy ID to content ID {content_id}."
                    ),
                )

        if re.fullmatch(r"[0-9a-fA-F-]{36}", identifier):
            raise DownloaderError(
                "A bare content UUID is not enough on its own. "
                "Use the full Creations URL or a searchable title."
            )

        matches = self.search_mods(
            product=product_slug,
            text=identifier,
            size=max_search_results,
        )
        if not matches:
            raise DownloaderError(f"No public mods found for search '{identifier}'.")

        chosen = self._pick_best_search_result(identifier, matches)
        content_id = str(chosen["content_id"])
        detail = self.get_mod_detail(product=product_slug, content_id=content_id)
        return ResolvedIdentifier(
            product=product_slug,
            content_id=content_id,
            detail=detail,
            resolution_note=f"Resolved search '{identifier}' to content ID {content_id}.",
        )

    def _parse_url_identifier(self, value: str) -> tuple[str | None, dict[str, str] | None]:
        if not re.match(r"^https?://", value, flags=re.IGNORECASE):
            return None, None

        parsed_url = urllib.parse.urlparse(value)
        path = parsed_url.path or ""
        lowered = value.lower()

        product = None
        product_match = re.search(r"/(fallout4|skyrim|starfield)(?:/|$)", lowered)
        if product_match:
            product = product_match.group(1)

        legacy_match = re.search(r"/mod-detail/(\d+)", lowered)
        if legacy_match:
            return product, {"legacy_id": legacy_match.group(1)}

        details_match = re.search(
            r"/details/([0-9a-fA-F-]{36}|[0-9]+)/?([^/?#]+)?",
            path,
            flags=re.IGNORECASE,
        )
        if details_match:
            first = details_match.group(1)
            second = details_match.group(2) or ""
            if first.isdigit():
                return product, {"content_id": first}
            return product, {
                "content_uuid": first,
                "slug_text": slugify_for_search(second),
            }

        content_match = re.search(r"/content/(\d+)", lowered)
        if content_match:
            return product, {"content_id": content_match.group(1)}

        return product, None

    def _pick_best_search_result(
        self, query: str, matches: list[dict[str, Any]]
    ) -> dict[str, Any]:
        query_norm = slugify_for_search(query)
        query_slug = sanitize_filename(query).lower()

        def score(item: dict[str, Any]) -> tuple[int, int]:
            title = str(item.get("title", ""))
            title_norm = slugify_for_search(title)
            title_slug = sanitize_filename(title).lower()

            rank = 0
            if title_norm == query_norm:
                rank += 1000
            if title_slug == query_slug:
                rank += 900
            if title_norm.startswith(query_norm):
                rank += 700
            if query_norm in title_norm:
                rank += 500
            if str(item.get("legacy_content_id", "")) == query.strip():
                rank += 1200
            if str(item.get("content_id", "")) == query.strip():
                rank += 1300

            popularity = int(
                coalesce(
                    item.get("stats", {}).get("totals", {}).get("downloads"),
                    item.get("stats", {}).get("totals", {}).get("subscribes"),
                    0,
                )
            )
            return (rank, popularity)

        return max(matches, key=score)

    def build_download_entries(
        self,
        detail: dict[str, Any],
        *,
        platform: str,
        side: str,
    ) -> list[dict[str, Any]]:
        requested_platform = normalize_platform(platform)
        requested_side = side.lower()
        if requested_side not in {"all", "client", "server"}:
            raise DownloaderError("side must be one of: all, client, server")

        entries: list[dict[str, Any]] = []
        all_groups = detail.get("download") or []

        for group in all_groups:
            hardware_platform = str(group.get("hardware_platform", ""))
            if normalize_platform(hardware_platform) != requested_platform:
                continue

            published_versions = list(group.get("published") or [])
            if not published_versions:
                continue

            latest = max(published_versions, key=lambda item: int(item.get("ctime", 0)))
            for side_name in ("client", "server"):
                if requested_side not in {"all", side_name}:
                    continue
                files = latest.get(side_name) or {}
                for entry_key, file_meta in files.items():
                    url = file_meta.get("download_url")
                    if not url:
                        continue
                    suffix = Path(urllib.parse.urlparse(url).path).suffix or ".bin"
                    filename = (
                        f"{hardware_platform.lower()}__v{latest.get('version_name', 'unknown')}"
                        f"__{side_name}__{sanitize_filename(entry_key)}{suffix}"
                    )
                    entries.append(
                        {
                            "hardware_platform": hardware_platform,
                            "side": side_name,
                            "version": str(latest.get("version_name", "")),
                            "note_id": str(latest.get("note_id", "")),
                            "entry_key": entry_key,
                            "url": url,
                            "etag": file_meta.get("etag"),
                            "size": int(file_meta.get("size", 0)),
                            "filename": filename,
                        }
                    )

        return entries

    def count_locked_download_entries(
        self,
        detail: dict[str, Any],
        *,
        platform: str,
        side: str,
    ) -> int:
        requested_platform = normalize_platform(platform)
        requested_side = side.lower()
        if requested_side not in {"all", "client", "server"}:
            raise DownloaderError("side must be one of: all, client, server")

        locked_count = 0
        all_groups = detail.get("download") or []

        for group in all_groups:
            hardware_platform = str(group.get("hardware_platform", ""))
            if normalize_platform(hardware_platform) != requested_platform:
                continue

            published_versions = list(group.get("published") or [])
            if not published_versions:
                continue

            latest = max(published_versions, key=lambda item: int(item.get("ctime", 0)))
            for side_name in ("client", "server"):
                if requested_side not in {"all", side_name}:
                    continue
                files = latest.get(side_name) or {}
                for file_meta in files.values():
                    if not file_meta.get("download_url"):
                        locked_count += 1

        return locked_count

    def summarize_side_availability(
        self,
        detail: dict[str, Any],
        *,
        platform: str,
    ) -> dict[str, dict[str, int]]:
        requested_platform = normalize_platform(platform)
        summary = {
            "client": {"downloadable": 0, "locked": 0},
            "server": {"downloadable": 0, "locked": 0},
        }
        all_groups = detail.get("download") or []

        for group in all_groups:
            hardware_platform = str(group.get("hardware_platform", ""))
            if normalize_platform(hardware_platform) != requested_platform:
                continue

            published_versions = list(group.get("published") or [])
            if not published_versions:
                continue

            latest = max(published_versions, key=lambda item: int(item.get("ctime", 0)))
            for side_name in ("client", "server"):
                files = latest.get(side_name) or {}
                for file_meta in files.values():
                    if file_meta.get("download_url"):
                        summary[side_name]["downloadable"] += 1
                    else:
                        summary[side_name]["locked"] += 1

        return summary

    def missing_download_message(
        self,
        detail: dict[str, Any],
        *,
        platform: str,
        side: str,
    ) -> str:
        requested_platform = normalize_platform(platform)
        requested_side = side.lower()
        locked_count = self.count_locked_download_entries(
            detail,
            platform=requested_platform,
            side=side,
        )
        side_summary = self.summarize_side_availability(detail, platform=requested_platform)

        if requested_side in {"client", "server"}:
            requested_summary = side_summary[requested_side]
            other_side = "server" if requested_side == "client" else "client"
            other_summary = side_summary[other_side]

            if requested_summary["locked"]:
                return (
                    f"Bethesda returned {requested_summary['locked']} published {requested_side} "
                    f"file slot(s) for platform {requested_platform}, but did not provide a "
                    "download URL. Install this one from the in-game Creations menu."
                )

            if other_summary["downloadable"]:
                return (
                    f"No published {requested_side} download entries were found for platform "
                    f"{requested_platform}. This creation only exposes {other_side} files for the "
                    "latest published build."
                )

        if locked_count:
            return (
                f"Bethesda returned {locked_count} published file slot(s) for platform "
                f"{requested_platform}, but did not provide a download URL. "
                "Install this one from the in-game Creations menu."
            )
        if requested_side in {"client", "server"}:
            return (
                f"No published {requested_side} download entries were found for platform "
                f"{requested_platform}."
            )
        return f"No published download entries were found for platform {requested_platform}."

    def download_latest(
        self,
        resolved: ResolvedIdentifier,
        *,
        output_dir: str,
        platform: str,
        side: str = "all",
        progress: Callable[[str], None] | None = None,
    ) -> tuple[Path, list[Path], list[dict[str, Any]]]:
        detail = resolved.detail
        entries = self.build_download_entries(detail, platform=platform, side=side)
        if not entries:
            raise DownloaderError(
                self.missing_download_message(detail, platform=platform, side=side)
            )

        mod_folder_name = sanitize_filename(
            f"{detail.get('title', 'mod')}__{coalesce(detail.get('legacy_content_id'), detail.get('content_id'))}"
        )
        target_dir = Path(output_dir).expanduser().resolve() / mod_folder_name
        target_dir.mkdir(parents=True, exist_ok=True)

        downloaded_paths: list[Path] = []
        manifest_files: list[dict[str, Any]] = []
        for entry in entries:
            destination = target_dir / entry["filename"]
            if destination.exists() and destination.stat().st_size == entry["size"]:
                if progress:
                    progress(f"Skipping existing file: {destination.name}")
            else:
                if progress:
                    progress(f"Downloading {destination.name}")
                self._download_file(entry["url"], destination, entry["size"], progress)

            output_paths = self._finalize_downloaded_artifact(destination, progress)
            downloaded_paths.extend(output_paths)
            manifest_files.append(
                {
                    **entry,
                    "downloaded_path": str(destination.resolve()),
                    "output_paths": [str(path.resolve()) for path in output_paths],
                }
            )

        manifest_path = target_dir / "manifest.json"
        manifest = {
            "generated_at": int(time.time()),
            "resolution_note": resolved.resolution_note,
            "product": resolved.product,
            "content_id": detail.get("content_id"),
            "content_uuid": detail.get("content_uuid"),
            "legacy_content_id": detail.get("legacy_content_id"),
            "title": detail.get("title"),
            "author": detail.get("author_displayname"),
            "platform": normalize_platform(platform),
            "side": side,
            "files": manifest_files,
        }
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest_path, downloaded_paths, entries

    def _finalize_downloaded_artifact(
        self,
        downloaded_file: Path,
        progress: Callable[[str], None] | None,
    ) -> list[Path]:
        if downloaded_file.suffix.lower() != ".ckm":
            return [downloaded_file]

        try:
            return self._extract_ckm_container(downloaded_file, progress)
        except DownloaderError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise DownloaderError(
                f"Downloaded CKM file {downloaded_file.name}, but extraction failed: {exc}"
            ) from exc

    def _normalize_ckm_member_path(self, raw_path: str) -> Path:
        member_path = PureWindowsPath(raw_path)
        if member_path.is_absolute() or member_path.drive:
            raise DownloaderError(f"Blocked absolute CKM path: {raw_path}")

        parts = [part for part in member_path.parts if part not in ("\\", "/")]
        if not parts or any(part in ("", ".", "..") for part in parts):
            raise DownloaderError(f"Blocked unsafe CKM path: {raw_path}")

        return Path(*parts)

    def _extract_ckm_container(
        self,
        ckm_path: Path,
        progress: Callable[[str], None] | None,
    ) -> list[Path]:
        data = ckm_path.read_bytes()
        if len(data) < 8 or data[:4] != b"BTAR":
            return [ckm_path]

        version = int.from_bytes(data[4:6], "little")
        entry_count = int.from_bytes(data[6:8], "little")
        if version != 1:
            raise DownloaderError(
                f"Unsupported CKM container version {version} in {ckm_path.name}."
            )

        offset = 8
        extracted_paths: list[Path] = []
        for _ in range(entry_count):
            if offset + 2 > len(data):
                raise DownloaderError(f"CKM header ended unexpectedly in {ckm_path.name}.")

            path_length = int.from_bytes(data[offset : offset + 2], "little")
            offset += 2
            if offset + path_length + 8 > len(data):
                raise DownloaderError(f"CKM entry metadata is truncated in {ckm_path.name}.")

            raw_path = data[offset : offset + path_length].decode("utf-8", errors="replace")
            offset += path_length
            file_size = int.from_bytes(data[offset : offset + 8], "little")
            offset += 8

            end_offset = offset + file_size
            if end_offset > len(data):
                raise DownloaderError(f"CKM entry data is truncated in {ckm_path.name}.")

            destination = ckm_path.parent / self._normalize_ckm_member_path(raw_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("wb") as handle:
                handle.write(data[offset:end_offset])
            extracted_paths.append(destination)
            if progress:
                relative_name = destination.relative_to(ckm_path.parent)
                progress(f"  Extracted {relative_name}")
            offset = end_offset

        if offset != len(data):
            raise DownloaderError(
                f"CKM container {ckm_path.name} has unexpected trailing data and was not extracted."
            )

        ckm_path.unlink()
        if progress:
            progress(f"Unpacked {ckm_path.name}")

        return extracted_paths

    def _download_file(
        self,
        url: str,
        destination: Path,
        expected_size: int,
        progress: Callable[[str], None] | None,
    ) -> None:
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
                destination.parent.mkdir(parents=True, exist_ok=True)
                total = int(response.headers.get("Content-Length", "0") or 0)
                size_hint = total or expected_size
                written = 0
                with destination.open("wb") as handle:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        handle.write(chunk)
                        written += len(chunk)
                        if progress and size_hint:
                            percent = written * 100 / size_hint
                            progress(
                                f"  {destination.name}: {written}/{size_hint} bytes ({percent:.1f}%)"
                            )
        except urllib.error.HTTPError as exc:
            raise DownloaderError(f"Download failed for {url}: HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise DownloaderError(f"Download failed for {url}: {exc}") from exc


def format_mod_summary(
    detail: dict[str, Any],
    platform: str,
    entries: list[dict[str, Any]],
    locked_entries: int,
) -> str:
    latest_releases = detail.get("release_notes") or []
    lines = [
        f"Title: {detail.get('title', 'Unknown')}",
        f"Author: {detail.get('author_displayname', 'Unknown')}",
        f"Product: {detail.get('product', 'Unknown')}",
        f"Content ID: {detail.get('content_id', 'Unknown')}",
        f"Legacy ID: {coalesce(detail.get('legacy_content_id'), 'n/a')}",
        f"Platform requested: {normalize_platform(platform)}",
        f"Available download entries: {len(entries)}",
        f"Locked / empty download slots: {locked_entries}",
    ]

    for release_group in latest_releases:
        if normalize_platform(str(release_group.get("hardware_platform", ""))) != normalize_platform(platform):
            continue
        notes = list(release_group.get("release_notes") or [])
        if notes:
            newest = max(notes, key=lambda item: int(item.get("ctime", 0)))
            lines.append(
                f"Latest release note version on {release_group.get('hardware_platform')}: "
                f"{newest.get('version_name', 'unknown')}"
            )

    for entry in entries:
        lines.append(
            f"  - {entry['filename']} | {entry['side']} | {entry['size']} bytes | {entry['url']}"
        )
    return "\n".join(lines)


def run_cli(args: argparse.Namespace) -> int:
    downloader = BethesdaModDownloader()
    product = normalize_product(args.product)
    platform = normalize_platform(args.platform)

    resolved = downloader.resolve_identifier(
        args.identifier,
        product=product,
        max_search_results=args.max_search_results,
    )
    entries = downloader.build_download_entries(
        resolved.detail,
        platform=platform,
        side=args.side,
    )
    locked_entries = downloader.count_locked_download_entries(
        resolved.detail,
        platform=platform,
        side=args.side,
    )

    print(resolved.resolution_note)
    print(format_mod_summary(resolved.detail, platform, entries, locked_entries))

    if args.list_only:
        return 0

    manifest_path, downloaded_paths, _ = downloader.download_latest(
        resolved,
        output_dir=args.output,
        platform=platform,
        side=args.side,
        progress=lambda message: print(message),
    )
    print(f"Manifest: {manifest_path}")
    for path in downloaded_paths:
        print(f"Saved: {path}")
    return 0


class DownloaderGuiApp:
    def __init__(self) -> None:
        import tkinter as tk
        from tkinter import filedialog, ttk

        self.tk = tk
        self.ttk = ttk
        self.filedialog = filedialog
        self.root = tk.Tk()
        self.root.title("Dwwite Downloader")
        self.root.geometry("940x640")
        self.root.minsize(900, 600)

        self.downloader = BethesdaModDownloader()
        self.message_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self.resolved: ResolvedIdentifier | None = None
        self.worker_running = False

        self.identifier_var = tk.StringVar()
        self.product_var = tk.StringVar(value="fallout4")
        self.platform_var = tk.StringVar(value="WINDOWS")
        self.side_var = tk.StringVar(value="all")
        self.output_var = tk.StringVar(
            value=str((Path.cwd() / DEFAULT_OUTPUT_DIR).resolve())
        )
        self.status_var = tk.StringVar(value="Ready")

        self._build_ui()
        self.root.after(100, self._poll_queue)

    def _build_ui(self) -> None:
        tk = self.tk
        ttk = self.ttk

        frame = ttk.Frame(self.root, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        frame.columnconfigure(1, weight=1)
        frame.columnconfigure(2, weight=1)
        frame.rowconfigure(5, weight=1)

        ttk.Label(frame, text="Paste a Bethesda or Creations link, ID, or search").grid(
            row=0, column=0, sticky="w"
        )
        identifier_entry = ttk.Entry(frame, textvariable=self.identifier_var)
        identifier_entry.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(8, 0))
        identifier_entry.bind("<Return>", lambda _event: self._resolve_clicked())
        ttk.Button(frame, text="Paste", command=self._paste_identifier).grid(
            row=0, column=3, sticky="w", padx=(8, 0)
        )
        ttk.Label(
            frame,
            text=(
                "Examples: old bethesda.net mod-detail links, new creations.bethesda.net "
                "details links, a numeric mod ID, or a mod title."
            ),
            wraplength=820,
        ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))

        ttk.Label(frame, text="Product").grid(row=2, column=0, sticky="w", pady=(10, 0))
        ttk.Combobox(
            frame,
            textvariable=self.product_var,
            values=["fallout4", "skyrim", "starfield"],
            state="readonly",
        ).grid(row=2, column=1, sticky="w", padx=(8, 0), pady=(10, 0))

        ttk.Label(frame, text="Platform").grid(row=2, column=2, sticky="w", padx=(16, 0), pady=(10, 0))
        ttk.Combobox(
            frame,
            textvariable=self.platform_var,
            values=["WINDOWS", "XB1", "PS4", "XBOXSERIESX", "PLAYSTATION5"],
            state="readonly",
        ).grid(row=2, column=3, sticky="w", padx=(8, 0), pady=(10, 0))

        ttk.Label(frame, text="Side").grid(row=3, column=0, sticky="w", pady=(10, 0))
        ttk.Combobox(
            frame,
            textvariable=self.side_var,
            values=["all", "client", "server"],
            state="readonly",
        ).grid(row=3, column=1, sticky="w", padx=(8, 0), pady=(10, 0))

        ttk.Label(frame, text="Output Folder").grid(row=4, column=0, sticky="w", pady=(10, 0))
        ttk.Entry(frame, textvariable=self.output_var).grid(
            row=4, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=(10, 0)
        )
        ttk.Button(frame, text="Browse", command=self._choose_output).grid(
            row=4, column=3, sticky="w", padx=(8, 0), pady=(10, 0)
        )

        button_row = ttk.Frame(frame)
        button_row.grid(row=5, column=0, columnspan=4, sticky="w", pady=(14, 10))
        ttk.Button(button_row, text="Resolve", command=self._resolve_clicked).pack(side=tk.LEFT)
        ttk.Button(button_row, text="Download Latest", command=self._download_clicked).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        ttk.Button(button_row, text="Clear Log", command=self._clear_log).pack(
            side=tk.LEFT, padx=(8, 0)
        )

        self.log_widget = tk.Text(frame, wrap="word")
        self.log_widget.grid(row=6, column=0, columnspan=4, sticky="nsew")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.log_widget.yview)
        scrollbar.grid(row=6, column=4, sticky="ns")
        self.log_widget.configure(yscrollcommand=scrollbar.set)

        ttk.Label(frame, textvariable=self.status_var).grid(
            row=7, column=0, columnspan=4, sticky="w", pady=(10, 0)
        )

    def _paste_identifier(self) -> None:
        try:
            clipboard_text = self.root.clipboard_get()
        except self.tk.TclError:
            self._append_log("Clipboard is empty.")
            return
        self.identifier_var.set(clipboard_text.strip())

    def _choose_output(self) -> None:
        selected = self.filedialog.askdirectory(initialdir=self.output_var.get() or None)
        if selected:
            self.output_var.set(selected)

    def _clear_log(self) -> None:
        self.log_widget.delete("1.0", self.tk.END)

    def _set_busy(self, busy: bool, status: str) -> None:
        self.worker_running = busy
        self.status_var.set(status)

    def _append_log(self, message: str) -> None:
        self.log_widget.insert(self.tk.END, message + "\n")
        self.log_widget.see(self.tk.END)

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.message_queue.get_nowait()
                if kind == "log":
                    self._append_log(str(payload))
                elif kind == "status":
                    self.status_var.set(str(payload))
                elif kind == "resolved":
                    self.resolved = payload
                elif kind == "done":
                    self._set_busy(False, str(payload))
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _run_worker(self, func: Callable[[], None], busy_message: str) -> None:
        if self.worker_running:
            self._append_log("A task is already running.")
            return

        self._set_busy(True, busy_message)

        def target() -> None:
            try:
                func()
            except Exception as exc:  # noqa: BLE001
                self.message_queue.put(("log", f"Error: {exc}"))
                self.message_queue.put(("done", "Ready"))
            else:
                self.message_queue.put(("done", "Ready"))

        threading.Thread(target=target, daemon=True).start()

    def _resolve_clicked(self) -> None:
        def worker() -> None:
            identifier = self.identifier_var.get().strip()
            product = self.product_var.get().strip()
            platform = self.platform_var.get().strip()
            side = self.side_var.get().strip()

            resolved = self.downloader.resolve_identifier(identifier, product=product)
            entries = self.downloader.build_download_entries(
                resolved.detail,
                platform=platform,
                side=side,
            )
            locked_entries = self.downloader.count_locked_download_entries(
                resolved.detail,
                platform=platform,
                side=side,
            )
            summary = format_mod_summary(
                resolved.detail,
                platform,
                entries,
                locked_entries,
            )
            self.message_queue.put(("resolved", resolved))
            self.message_queue.put(("log", resolved.resolution_note))
            self.message_queue.put(("log", summary))

        self._run_worker(worker, "Resolving mod...")

    def _download_clicked(self) -> None:
        def worker() -> None:
            resolved = self.resolved
            identifier = self.identifier_var.get().strip()
            product = self.product_var.get().strip()
            platform = self.platform_var.get().strip()
            side = self.side_var.get().strip()
            output_dir = self.output_var.get().strip() or DEFAULT_OUTPUT_DIR

            if resolved is None:
                resolved = self.downloader.resolve_identifier(identifier, product=product)
                self.message_queue.put(("resolved", resolved))
                self.message_queue.put(("log", resolved.resolution_note))

            manifest_path, paths, _ = self.downloader.download_latest(
                resolved,
                output_dir=output_dir,
                platform=platform,
                side=side,
                progress=lambda msg: self.message_queue.put(("log", msg)),
            )
            self.message_queue.put(("log", f"Manifest: {manifest_path}"))
            for path in paths:
                self.message_queue.put(("log", f"Saved: {path}"))

        self._run_worker(worker, "Downloading latest release...")
    def run(self) -> None:
        self.root.mainloop()


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Dwwite downloader for public Bethesda.net / Creations mods."
    )
    parser.add_argument(
        "identifier",
        nargs="?",
        help="Mod URL, numeric legacy ID, numeric content ID, or text search.",
    )
    parser.add_argument(
        "--product",
        default="fallout4",
        help="Product slug: fallout4, skyrim, or starfield.",
    )
    parser.add_argument(
        "--platform",
        default="WINDOWS",
        help="Platform to download: WINDOWS, XB1, PS4, XBOXSERIESX, PLAYSTATION5.",
    )
    parser.add_argument(
        "--side",
        default="all",
        choices=["all", "client", "server"],
        help="Which asset side to download.",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT_DIR,
        help="Output directory for downloaded files.",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Resolve the mod and print available download entries without downloading.",
    )
    parser.add_argument(
        "--max-search-results",
        type=int,
        default=100,
        help="Maximum number of Bethesda search results to consider when resolving text or UUID URLs.",
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Launch the desktop GUI instead of the CLI.",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    if args.gui or not args.identifier:
        app = DownloaderGuiApp()
        app.run()
        return 0

    try:
        return run_cli(args)
    except DownloaderError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
