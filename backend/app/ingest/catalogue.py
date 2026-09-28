from __future__ import annotations

from urllib.parse import urlparse
from typing import Any

import httpx


def _value(record: dict[str, Any], *names: str) -> Any:
    for name in names:
        value = record.get(name)
        if value is not None:
            return value
    return None


def _location(record: dict[str, Any]) -> tuple[float, float]:
    location = record.get("location") or record.get("coordinates") or {}
    if isinstance(location, list) and len(location) >= 2:
        longitude, latitude = location[:2]
    elif isinstance(location, dict):
        latitude = _value(location, "latitude", "lat")
        longitude = _value(location, "longitude", "lon", "lng")
    else:
        latitude = longitude = None
    latitude = _value(record, "latitude", "lat") if latitude is None else latitude
    longitude = _value(record, "longitude", "lon", "lng") if longitude is None else longitude
    if latitude is None or longitude is None:
        raise ValueError("Catalogue camera is missing coordinates")
    lat, lon = float(latitude), float(longitude)
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("Catalogue camera has invalid coordinates")
    return lat, lon


def _stream_url(record: dict[str, Any], kind: str) -> str | None:
    urls = record.get("urls") or record.get("streams") or {}
    value = _value(record, f"{kind}_url", kind)
    if value is None and isinstance(urls, dict):
        value = _value(urls, kind, f"{kind}_url")
    if isinstance(value, dict):
        value = _value(value, "url", "uri")
    if value is None:
        return None
    url = str(value)
    schemes = {"rtsp": {"rtsp", "rtsps"}, "hls": {"http", "https"}, "whep": {"http", "https"}}
    parsed = urlparse(url)
    if parsed.scheme not in schemes[kind] or not parsed.hostname:
        raise ValueError(f"Invalid {kind} URL in catalogue")
    return url


def parse_catalogue(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        records = payload
    elif isinstance(payload, dict):
        records = _value(payload, "cameras", "streams", "items", "data")
        if isinstance(records, dict):
            records = _value(records, "cameras", "items", "streams")
    else:
        records = None
    if not isinstance(records, list):
        raise ValueError("Catalogue response must contain a camera array")

    cameras = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Catalogue camera is not an object")
        camera_id = _value(record, "id", "camera_id", "stream_id")
        if camera_id is None or not str(camera_id).strip():
            raise ValueError("Catalogue camera is missing an ID")
        lat, lon = _location(record)
        rtsp = _stream_url(record, "rtsp")
        hls = _stream_url(record, "hls")
        whep = _stream_url(record, "whep")
        if not rtsp and not hls:
            raise ValueError(f"Camera {camera_id} has no inference feed URL")
        properties = record.get("properties") or record.get("stream_properties") or {}
        if not isinstance(properties, dict):
            properties = {}
        live = _value(record, "live", "is_live", "online", "live_status")
        if isinstance(live, str):
            live = live.lower() in {"true", "1", "online", "live", "active"}
        cameras.append(
            {
                "camera_id": str(camera_id),
                "display_name": str(_value(record, "name", "display_name", "label") or f"Camera {camera_id}"),
                "department": str(_value(record, "department", "owner") or "Sentinel"),
                "latitude": lat,
                "longitude": lon,
                "source_type": "rtsp" if rtsp else "hls",
                "source_mode": "government_live",
                "codec": _value(record, "codec") or properties.get("codec"),
                "width": _value(record, "width") or properties.get("width"),
                "height": _value(record, "height") or properties.get("height"),
                "bitrate": _value(record, "bitrate") or properties.get("bitrate"),
                "catalogue_live": None if live is None else bool(live),
                "rtsp_url": rtsp,
                "hls_url": hls,
                "whep_url": whep,
            }
        )
    return cameras


class SentinelCatalogue:
    def __init__(self, base_url: str, authorization: str | None = None,
                 transport: httpx.BaseTransport | None = None):
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Sentinel base URL must be an http(s) origin")
        self.base_url = base_url.rstrip("/")
        self.authorization = authorization
        self.transport = transport

    def fetch(self) -> list[dict[str, Any]]:
        headers = {"Authorization": self.authorization} if self.authorization else {}
        with httpx.Client(timeout=8.0, follow_redirects=False, transport=self.transport) as client:
            response = client.get(f"{self.base_url}/api/ingest", headers=headers)
            response.raise_for_status()
            return parse_catalogue(response.json())
