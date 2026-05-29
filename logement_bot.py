#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
import os
import re
import smtplib
import ssl
import sys
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from math import asin, cos, radians, sin, sqrt
from pathlib import Path
from typing import Any
from urllib import error, parse, request


BIENICI_BASE_URL = "https://www.bienici.com"
SUGGEST_URL = f"{BIENICI_BASE_URL}/suggest.json"
ADS_URL = f"{BIENICI_BASE_URL}/realEstateAds.json"
DETAIL_URL = f"{BIENICI_BASE_URL}/realEstateAd.json"
PARUVENDU_BASE_URL = "https://www.paruvendu.fr"
PARUVENDU_SEARCH_URL = f"{PARUVENDU_BASE_URL}/immobilier/recherche/location/appartement/laval-53000/"
FNAIM_BASE_URL = "https://www.fnaim.fr"
FNAIM_SEARCH_URL = f"{FNAIM_BASE_URL}/liste-annonces-immobilieres/18-location-appartement-laval-53000.htm"
ENTREPARTICULIERS_BASE_URL = "https://www.entreparticuliers.com"
ENTREPARTICULIERS_API_URL = "https://api-prod.entreparticuliers.com/api/annonces"
SQUARE_HABITAT_BASE_URL = "https://www.squarehabitat.fr"
SQUARE_HABITAT_SEARCH_URL = (
    f"{SQUARE_HABITAT_BASE_URL}/annonces/location/bien/appartement/immobilier/"
    "pays-de-la-loire/mayenne/laval-53000"
)
DEFAULT_STATE_PATH = Path("state/last_run.json")
DEFAULT_ENV_PATH = Path(".env")
DEFAULT_RECIPIENT = "92mamadousy@gmail.com"
DEFAULT_CITY_QUERY = "laval"
DEFAULT_CITY_POSTAL_CODE = "53000"
DEFAULT_INCLUDE_PARKING = False
DEFAULT_MAX_RESULTS = 50
DEFAULT_TIMEOUT = 30
RESIDENTIAL_PROPERTY_TYPES = {"flat", "house"}
PROPERTY_TYPE_LABELS = {
    "flat": "Appartement",
    "house": "Maison",
    "parking": "Parking",
}
PROPERTY_TYPE_ROUTE_SEGMENTS = {
    "flat": "appartement",
    "house": "maisonvilla",
    "parking": "parking",
}
ESIEA_LAVAL_NAME = "ESIEA Laval"
ESIEA_LAVAL_ADDRESS = "38 Rue des Docteurs Calmette et Guerin, 53000 Laval"
ESIEA_LAVAL_LAT = 48.0878321
ESIEA_LAVAL_LON = -0.7563393
OSRM_BASE_URL = "https://router.project-osrm.org/route/v1"
WALKING_SPEED_KMH = 4.5
CYCLING_SPEED_KMH = 14.0
DRIVING_SPEED_KMH = 25.0


@dataclass
class Listing:
    listing_id: str
    source_name: str
    title: str
    generated_title: str
    city: str
    postal_code: str
    district: str
    property_type: str
    price: float | None
    charges: float | None
    surface_area: float | None
    rooms: int | None
    bedrooms: int | None
    furnished: bool | None
    energy_class: str | None
    greenhouse_gas_class: str | None
    description: str
    modification_date: str | None
    availability_date: str | None
    phone: str | None
    agency_name: str | None
    detail_api_url: str
    detail_page_url: str
    latitude: float | None
    longitude: float | None
    distance_to_esiea_km: float | None
    walk_time_to_esiea_min: int | None
    bike_time_to_esiea_min: int | None
    drive_time_to_esiea_min: int | None
    transit_route_url: str
    walking_route_url: str
    biking_route_url: str
    driving_route_url: str

    @property
    def display_title(self) -> str:
        return self.generated_title or self.title or "Annonce sans titre"

    @property
    def total_label(self) -> str:
        return format_price(self.price)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recupere des offres de logement a Laval et les envoie par email."
    )
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_PATH))
    parser.add_argument("--state-file", default=str(DEFAULT_STATE_PATH))
    parser.add_argument("--recipient", default=None)
    parser.add_argument("--city-query", default=None)
    parser.add_argument("--postal-code", default=None)
    parser.add_argument("--max-results", type=int, default=None)
    parser.add_argument("--include-parking", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'")
        values[key.strip()] = value
    return values


def get_setting(
    cli_value: Any,
    env_values: dict[str, str],
    env_key: str,
    default: Any,
) -> Any:
    if cli_value not in (None, ""):
        return cli_value
    if env_key in os.environ:
        return os.environ[env_key]
    if env_key in env_values:
        return env_values[env_key]
    return default


def http_get_json(url: str, params: dict[str, Any], timeout: int = DEFAULT_TIMEOUT) -> Any:
    query = parse.urlencode(params)
    full_url = f"{url}?{query}"
    req = request.Request(
        full_url,
        headers={
            "User-Agent": "logement-bot/1.0",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def http_get_json_direct(url: str, timeout: int = DEFAULT_TIMEOUT) -> Any:
    req = request.Request(
        url,
        headers={
            "User-Agent": "logement-bot/1.0",
            "Accept": "application/json,text/plain,*/*",
        },
    )
    with request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def http_get_text(
    url: str,
    timeout: int = DEFAULT_TIMEOUT,
    encoding: str | None = "utf-8",
) -> str:
    req = request.Request(
        url,
        headers={
            "User-Agent": "logement-bot/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with request.urlopen(req, timeout=timeout) as response:
        raw = response.read()
        if encoding:
            return raw.decode(encoding, errors="replace")
        content_type = response.headers.get_content_charset() or "utf-8"
        return raw.decode(content_type, errors="replace")


def slugify(value: str) -> str:
    text = value.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def strip_html(value: str) -> str:
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"</p>", "\n", value, flags=re.IGNORECASE)
    value = re.sub(r"<[^>]+>", "", value)
    value = html.unescape(value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def format_price(value: float | None) -> str:
    if value is None:
        return "Prix non renseigne"
    return f"{value:,.0f} EUR/mois".replace(",", " ")


def format_area(value: float | None) -> str:
    if value is None:
        return "Surface non renseignee"
    rounded = int(value) if float(value).is_integer() else round(value, 1)
    return f"{rounded} m2"


def first_non_empty(*values: str | None) -> str:
    for value in values:
        if value:
            return value
    return ""


def collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def format_availability_date(value: str | None) -> str:
    if not value:
        return "Non renseignee"
    text = value.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return text[:10] if len(text) >= 10 else text


def build_source_summary(listings: list["Listing"]) -> str:
    counts: dict[str, int] = {}
    for listing in listings:
        counts[listing.source_name] = counts.get(listing.source_name, 0) + 1
    return " | ".join(f"{source}: {count}" for source, count in sorted(counts.items()))


def extract_script_contents(html_text: str) -> list[str]:
    return re.findall(r"<script[^>]*>(.*?)</script>", html_text, flags=re.IGNORECASE | re.DOTALL)


def looks_like_sale_listing(*values: str | None) -> bool:
    haystack = " ".join(value or "" for value in values).lower()
    sale_markers = (
        "à vendre",
        "a vendre",
        "vente",
        "vendre",
        "prix net vendeur",
        "frais d'agence",
    )
    return any(marker in haystack for marker in sale_markers)


def build_bienici_detail_url(ad: dict[str, Any]) -> str:
    city_slug = slugify(ad.get("city", "laval"))
    property_segment = PROPERTY_TYPE_ROUTE_SEGMENTS.get(ad.get("propertyType"), "logement")
    rooms = ad.get("roomsQuantity")
    if isinstance(rooms, int) and rooms > 0:
        rooms_segment = f"{rooms}pieces"
        return f"{BIENICI_BASE_URL}/annonce/location/{city_slug}/{property_segment}/{rooms_segment}/{ad['id']}"
    return f"{BIENICI_BASE_URL}/annonce/location/{city_slug}/{property_segment}/{ad['id']}"


def build_google_maps_directions_url(
    origin_lat: float | None,
    origin_lon: float | None,
    travelmode: str,
) -> str:
    params = {
        "api": "1",
        "destination": f"{ESIEA_LAVAL_LAT},{ESIEA_LAVAL_LON}",
        "travelmode": travelmode,
    }
    if origin_lat is not None and origin_lon is not None:
        params["origin"] = f"{origin_lat},{origin_lon}"
    return "https://www.google.com/maps/dir/?" + parse.urlencode(params)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_km = 6371.0
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = (
        sin(d_lat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    )
    c = 2 * asin(sqrt(a))
    return earth_radius_km * c


def get_osrm_route_distance_km(
    origin_lat: float | None,
    origin_lon: float | None,
) -> float | None:
    if origin_lat is None or origin_lon is None:
        return None
    url = (
        f"{OSRM_BASE_URL}/driving/"
        f"{origin_lon},{origin_lat};{ESIEA_LAVAL_LON},{ESIEA_LAVAL_LAT}"
        "?overview=false"
    )
    try:
        payload = http_get_json_direct(url)
        routes = payload.get("routes") or []
        if not routes:
            return None
        distance_meters = routes[0].get("distance")
        if distance_meters in (None, ""):
            return None
        return float(distance_meters) / 1000.0
    except Exception:
        return None


def estimate_duration_minutes(distance_km: float | None, speed_kmh: float) -> int | None:
    if distance_km is None or speed_kmh <= 0:
        return None
    return max(1, round((distance_km / speed_kmh) * 60))


def resolve_laval_zone_id(city_query: str, postal_code: str) -> str:
    suggestions = http_get_json(
        SUGGEST_URL,
        {"q": city_query, "type": "city,postalCode,address"},
    )
    for item in suggestions:
        if item.get("type") != "city":
            continue
        postal_codes = item.get("postalCodes") or []
        if item.get("name", "").lower() == "laval" and postal_code in postal_codes:
            zone_ids = item.get("zoneIds") or []
            if zone_ids:
                return zone_ids[0]
    raise RuntimeError("Impossible de trouver la zone Laval (53000) sur Bien'ici.")


def fetch_bienici_listings(zone_id: str, include_parking: bool, max_results: int) -> list[Listing]:
    filters = {
        "size": max_results,
        "from": 0,
        "filterType": "rent",
        "zoneIdsByTypes": {"zoneIds": [zone_id]},
        "onTheMarket": [True],
    }
    if include_parking:
        filters["propertyType"] = ["house", "flat", "parking"]
    else:
        filters["propertyType"] = ["house", "flat"]

    payload = http_get_json(ADS_URL, {"filters": json.dumps(filters, separators=(",", ":"))})
    ads = payload.get("realEstateAds") or []
    listings: list[Listing] = []
    seen_ids: set[str] = set()

    for ad in ads:
        listing_id = ad.get("id")
        property_type = ad.get("propertyType")
        if not listing_id or listing_id in seen_ids:
            continue
        if not include_parking and property_type not in RESIDENTIAL_PROPERTY_TYPES:
            continue
        seen_ids.add(listing_id)
        district = ((ad.get("district") or {}).get("libelle") or "").strip()
        contact = ad.get("contactRelativeData") or {}
        blur_position = ((ad.get("blurInfo") or {}).get("position") or {})
        listing = Listing(
            listing_id=listing_id,
            source_name="Bien'ici",
            title=first_non_empty(ad.get("title")),
            generated_title=first_non_empty(ad.get("generatedTitle")),
            city=first_non_empty(ad.get("city")),
            postal_code=first_non_empty(ad.get("postalCode")),
            district=district,
            property_type=first_non_empty(property_type),
            price=to_float(ad.get("price")),
            charges=to_float(ad.get("charges")),
            surface_area=to_float(ad.get("surfaceArea")),
            rooms=to_int(ad.get("roomsQuantity")),
            bedrooms=to_int(ad.get("bedroomsQuantity")),
            furnished=to_bool(ad.get("isFurnished")),
            energy_class=first_non_empty(ad.get("energyClassification")),
            greenhouse_gas_class=first_non_empty(ad.get("greenhouseGazClassification")),
            description=strip_html(first_non_empty(ad.get("description"))),
            modification_date=first_non_empty(ad.get("modificationDate")),
            availability_date=first_non_empty(ad.get("availableDate")),
            phone=first_non_empty(contact.get("phoneToDisplay")),
            agency_name=first_non_empty(contact.get("agencyNameToDisplay"), ad.get("accountDisplayName")),
            detail_api_url=f"{DETAIL_URL}?{parse.urlencode({'id': listing_id})}",
            detail_page_url=build_bienici_detail_url(ad),
            latitude=to_float(blur_position.get("lat")),
            longitude=to_float(blur_position.get("lon")),
            distance_to_esiea_km=None,
            walk_time_to_esiea_min=None,
            bike_time_to_esiea_min=None,
            drive_time_to_esiea_min=None,
            transit_route_url="",
            walking_route_url="",
            biking_route_url="",
            driving_route_url="",
        )
        detailed_listing = enrich_listing_with_detail(listing)
        listings.append(enrich_listing_with_esiea_commute(detailed_listing))

    listings.sort(key=lambda item: (item.price is None, item.price or float("inf"), item.surface_area or float("inf")))
    return listings


def enrich_listing_with_detail(listing: Listing) -> Listing:
    try:
        details = http_get_json(DETAIL_URL, {"id": listing.listing_id})
    except Exception:
        return listing

    contact = details.get("contactRelativeData") or {}
    district = ((details.get("district") or {}).get("libelle") or listing.district).strip()
    blur_position = ((details.get("blurInfo") or {}).get("position") or {})
    return Listing(
        listing_id=listing.listing_id,
        source_name=listing.source_name,
        title=first_non_empty(details.get("title"), listing.title),
        generated_title=first_non_empty(details.get("generatedTitle"), listing.generated_title),
        city=first_non_empty(details.get("city"), listing.city),
        postal_code=first_non_empty(details.get("postalCode"), listing.postal_code),
        district=district,
        property_type=first_non_empty(details.get("propertyType"), listing.property_type),
        price=to_float(details.get("price")) if details.get("price") is not None else listing.price,
        charges=to_float(details.get("charges")) if details.get("charges") is not None else listing.charges,
        surface_area=to_float(details.get("surfaceArea")) if details.get("surfaceArea") is not None else listing.surface_area,
        rooms=to_int(details.get("roomsQuantity")) if details.get("roomsQuantity") is not None else listing.rooms,
        bedrooms=to_int(details.get("bedroomsQuantity")) if details.get("bedroomsQuantity") is not None else listing.bedrooms,
        furnished=to_bool(details.get("isFurnished")) if details.get("isFurnished") is not None else listing.furnished,
        energy_class=first_non_empty(details.get("energyClassification"), listing.energy_class),
        greenhouse_gas_class=first_non_empty(details.get("greenhouseGazClassification"), listing.greenhouse_gas_class),
        description=strip_html(first_non_empty(details.get("description"), listing.description)),
        modification_date=first_non_empty(details.get("modificationDate"), listing.modification_date),
        availability_date=first_non_empty(details.get("availableDate"), listing.availability_date),
        phone=first_non_empty(contact.get("phoneToDisplay"), listing.phone),
        agency_name=first_non_empty(contact.get("agencyNameToDisplay"), details.get("accountDisplayName"), listing.agency_name),
        detail_api_url=listing.detail_api_url,
        detail_page_url=build_bienici_detail_url(details),
        latitude=to_float(blur_position.get("lat")) if blur_position else listing.latitude,
        longitude=to_float(blur_position.get("lon")) if blur_position else listing.longitude,
        distance_to_esiea_km=listing.distance_to_esiea_km,
        walk_time_to_esiea_min=listing.walk_time_to_esiea_min,
        bike_time_to_esiea_min=listing.bike_time_to_esiea_min,
        drive_time_to_esiea_min=listing.drive_time_to_esiea_min,
        transit_route_url=listing.transit_route_url,
        walking_route_url=listing.walking_route_url,
        biking_route_url=listing.biking_route_url,
        driving_route_url=listing.driving_route_url,
    )


def enrich_listing_with_esiea_commute(listing: Listing) -> Listing:
    if (
        listing.distance_to_esiea_km is not None
        and listing.transit_route_url
        and listing.walking_route_url
        and listing.biking_route_url
        and listing.driving_route_url
    ):
        return listing

    straight_line_distance_km = None
    if listing.latitude is not None and listing.longitude is not None:
        straight_line_distance_km = haversine_km(
            listing.latitude,
            listing.longitude,
            ESIEA_LAVAL_LAT,
            ESIEA_LAVAL_LON,
        )

    route_distance_km = get_osrm_route_distance_km(listing.latitude, listing.longitude)
    effective_distance_km = route_distance_km or straight_line_distance_km
    walk_time = estimate_duration_minutes(effective_distance_km, WALKING_SPEED_KMH)
    bike_time = estimate_duration_minutes(effective_distance_km, CYCLING_SPEED_KMH)
    drive_time = estimate_duration_minutes(effective_distance_km, DRIVING_SPEED_KMH)

    return Listing(
        listing_id=listing.listing_id,
        source_name=listing.source_name,
        title=listing.title,
        generated_title=listing.generated_title,
        city=listing.city,
        postal_code=listing.postal_code,
        district=listing.district,
        property_type=listing.property_type,
        price=listing.price,
        charges=listing.charges,
        surface_area=listing.surface_area,
        rooms=listing.rooms,
        bedrooms=listing.bedrooms,
        furnished=listing.furnished,
        energy_class=listing.energy_class,
        greenhouse_gas_class=listing.greenhouse_gas_class,
        description=listing.description,
        modification_date=listing.modification_date,
        availability_date=listing.availability_date,
        phone=listing.phone,
        agency_name=listing.agency_name,
        detail_api_url=listing.detail_api_url,
        detail_page_url=listing.detail_page_url,
        latitude=listing.latitude,
        longitude=listing.longitude,
        distance_to_esiea_km=effective_distance_km,
        walk_time_to_esiea_min=walk_time,
        bike_time_to_esiea_min=bike_time,
        drive_time_to_esiea_min=drive_time,
        transit_route_url=build_google_maps_directions_url(
            listing.latitude,
            listing.longitude,
            "transit",
        ),
        walking_route_url=build_google_maps_directions_url(
            listing.latitude,
            listing.longitude,
            "walking",
        ),
        biking_route_url=build_google_maps_directions_url(
            listing.latitude,
            listing.longitude,
            "bicycling",
        ),
        driving_route_url=build_google_maps_directions_url(
            listing.latitude,
            listing.longitude,
            "driving",
        ),
    )


def parse_paruvendu_search_links(html_text: str, max_results: int) -> list[str]:
    matches = re.findall(
        r'href="(/immobilier/location/appartement/\d+A1KILHAP000)"',
        html_text,
        flags=re.IGNORECASE,
    )
    links: list[str] = []
    seen: set[str] = set()
    for path in matches:
        full_url = parse.urljoin(PARUVENDU_BASE_URL, path)
        if full_url in seen:
            continue
        seen.add(full_url)
        links.append(full_url)
        if len(links) >= max_results:
            break
    return links


def extract_first_group(pattern: str, text: str, flags: int = 0) -> str | None:
    match = re.search(pattern, text, flags)
    if not match:
        return None
    return match.group(1)


def parse_paruvendu_detail_page(detail_url: str) -> Listing | None:
    try:
        html_text = http_get_text(detail_url, encoding="windows-1252")
    except Exception:
        return None

    title_block = extract_first_group(
        r'<span id="detail_h1"[^>]*>(.*?)</span>',
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    title_text = collapse_whitespace(strip_html(title_block or ""))
    location_block = extract_first_group(
        r'<span id="detail_loc"[^>]*>(.*?)</span>',
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    location_text = collapse_whitespace(strip_html(location_block or ""))
    description_block = extract_first_group(
        r"Description[^<]*</h2>\s*<p[^>]*>(.*?)</p>",
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    description_text = collapse_whitespace(strip_html(description_block or ""))
    listing_id = extract_first_group(r"/(\d+A1KILHAP000)", detail_url) or detail_url.rstrip("/").split("/")[-1]
    price_text = extract_first_group(r"'gtm_var_prix':'([0-9]+)'", html_text)
    surface_text = extract_first_group(r"(\d+(?:[.,]\d+)?)\s*m²", title_text)
    rooms_text = extract_first_group(r"(\d+)\s*pièce", title_text)
    dpe_matches = re.findall(
        r'<span class="NoteEnerg_([A-Z]+)">([A-Z]+)</span>',
        html_text,
        flags=re.IGNORECASE,
    )
    energy_class = dpe_matches[0][1] if len(dpe_matches) >= 1 else ""
    greenhouse_class = dpe_matches[1][1] if len(dpe_matches) >= 2 else ""
    phone_text = extract_first_group(r'href="tel:([^"]+)"', html_text, flags=re.IGNORECASE)
    coords_match = re.search(
        r"myLngLat\s*=\s*\[\s*([-0-9.]+)\s*,\s*([-0-9.]+)\s*\]",
        html_text,
        flags=re.IGNORECASE,
    )
    lon = float(coords_match.group(1)) if coords_match else None
    lat = float(coords_match.group(2)) if coords_match else None
    postal_code = extract_first_group(r"\((\d{5})\)", location_text or "")
    city = "Laval" if "Laval" in location_text else ""
    agency_name = "Particulier" if "proposée par un particulier" in html_text.lower() else "ParuVendu"

    listing = Listing(
        listing_id=listing_id,
        source_name="ParuVendu",
        title=title_text,
        generated_title=title_text,
        city=city,
        postal_code=postal_code or "",
        district="",
        property_type="flat",
        price=to_float(price_text),
        charges=None,
        surface_area=to_float(surface_text.replace(",", ".")) if surface_text else None,
        rooms=to_int(rooms_text),
        bedrooms=None,
        furnished=True if "meubl" in description_text.lower() else None,
        energy_class=energy_class,
        greenhouse_gas_class=greenhouse_class,
        description=description_text,
        modification_date=None,
        availability_date=None,
        phone=phone_text,
        agency_name=agency_name,
        detail_api_url=detail_url,
        detail_page_url=detail_url,
        latitude=lat,
        longitude=lon,
        distance_to_esiea_km=None,
        walk_time_to_esiea_min=None,
        bike_time_to_esiea_min=None,
        drive_time_to_esiea_min=None,
        transit_route_url="",
        walking_route_url="",
        biking_route_url="",
        driving_route_url="",
    )
    return enrich_listing_with_esiea_commute(listing)


def fetch_paruvendu_listings(max_results: int) -> list[Listing]:
    try:
        search_html = http_get_text(PARUVENDU_SEARCH_URL, encoding="windows-1252")
    except Exception:
        return []

    detail_urls = parse_paruvendu_search_links(search_html, max_results)
    listings: list[Listing] = []
    for detail_url in detail_urls:
        listing = parse_paruvendu_detail_page(detail_url)
        if listing is not None:
            listings.append(listing)
    return listings


def fetch_fnaim_listings(max_results: int) -> list[Listing]:
    try:
        html_text = http_get_text(FNAIM_SEARCH_URL)
    except Exception:
        return []

    blocks = re.findall(
        r'<li class="item"><div class="itemInfo".*?</li>',
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    listings: list[Listing] = []
    for block in blocks:
        relative_url = extract_first_group(
            r'href="(/annonce-immobiliere/\d+/18-location-appartement-laval-53000\.htm)"',
            block,
            flags=re.IGNORECASE,
        )
        if not relative_url:
            continue
        detail_url = parse.urljoin(FNAIM_BASE_URL, relative_url)
        listing_id = extract_first_group(r"/annonce-immobiliere/(\d+)/", detail_url) or detail_url
        title = collapse_whitespace(
            strip_html(
                extract_first_group(
                    r"<h3>\s*<a[^>]*>(.*?)</a>",
                    block,
                    flags=re.IGNORECASE | re.DOTALL,
                )
                or ""
            )
        )
        price_text = collapse_whitespace(
            strip_html(
                extract_first_group(
                    r'<p class="price">\s*(.*?)</p>',
                    block,
                    flags=re.IGNORECASE | re.DOTALL,
                )
                or ""
            )
        )
        description = collapse_whitespace(
            strip_html(
                extract_first_group(
                    r'<p class="description">\s*(.*?)</p>',
                    block,
                    flags=re.IGNORECASE | re.DOTALL,
                )
                or ""
            )
        )
        agency_name = collapse_whitespace(
            strip_html(
                extract_first_group(
                    r'<div class="nom">\s*<a[^>]*><b>(.*?)</b></a>',
                    block,
                    flags=re.IGNORECASE | re.DOTALL,
                )
                or ""
            )
        )
        phone = extract_first_group(
            r'<span class="telNumber"[^>]*>(.*?)</span>',
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )
        surface_text = extract_first_group(r"(\d+(?:[.,]\d+)?)m²", title)
        rooms_text = extract_first_group(r"(\d+)\s*pièce", title, flags=re.IGNORECASE)
        furnished = True if "meubl" in description.lower() else None

        listing = Listing(
            listing_id=listing_id,
            source_name="FNAIM",
            title=title,
            generated_title=title,
            city="Laval",
            postal_code="53000",
            district="",
            property_type="flat",
            price=to_float(re.sub(r"[^\d]", "", price_text)),
            charges=None,
            surface_area=to_float(surface_text.replace(",", ".")) if surface_text else None,
            rooms=to_int(rooms_text),
            bedrooms=None,
            furnished=furnished,
            energy_class="",
            greenhouse_gas_class="",
            description=description,
            modification_date=None,
            availability_date=None,
            phone=collapse_whitespace(strip_html(phone or "")) or None,
            agency_name=agency_name or "FNAIM",
            detail_api_url=detail_url,
            detail_page_url=detail_url,
            latitude=None,
            longitude=None,
            distance_to_esiea_km=None,
            walk_time_to_esiea_min=None,
            bike_time_to_esiea_min=None,
            drive_time_to_esiea_min=None,
            transit_route_url="",
            walking_route_url="",
            biking_route_url="",
            driving_route_url="",
        )
        listings.append(listing)
        if len(listings) >= max_results:
            break
    return listings


def fetch_entreparticuliers_listings(max_results: int) -> list[Listing]:
    params = {
        "pagination": "true",
        "itemsPerPage": str(max_results),
        "page": "1",
        "partial": "true",
        "rubrique.slug": "location",
        "bienType.slug": "appartement",
        "commune.slug": "laval-53000",
        "estActive": "true",
    }
    try:
        payload = http_get_json(ENTREPARTICULIERS_API_URL, params)
    except Exception:
        return []

    listings: list[Listing] = []
    for ad in payload.get("hydra:member") or []:
        detail = ad.get("detail") or {}
        commune = ad.get("commune") or {}
        utilisateur = ad.get("utilisateur") or {}
        rubrique_slug = ((ad.get("rubrique") or {}).get("slug") or "").strip().lower()
        title = collapse_whitespace(first_non_empty(ad.get("titre")))
        description = collapse_whitespace(strip_html(first_non_empty(detail.get("description"))))
        if rubrique_slug != "location":
            continue
        if looks_like_sale_listing(title, description):
            continue
        if to_float(ad.get("prix")) and float(ad.get("prix")) > 5000:
            continue

        url_slug = slugify(title or f"annonce-{ad.get('id')}")
        detail_url = (
            f"{ENTREPARTICULIERS_BASE_URL}/annonces-immobilieres/appartement/location/"
            f"laval-53000/{url_slug}/ref-{ad.get('id')}"
        )
        source_label = ((ad.get("source") or {}).get("label") or "").strip()
        detail_source_url = first_non_empty(detail.get("urlsource"), detail_url)
        if looks_like_sale_listing(detail_source_url):
            detail_source_url = detail_url

        listing = Listing(
            listing_id=str(ad.get("id") or detail_url),
            source_name="Entreparticuliers",
            title=title,
            generated_title=title,
            city=first_non_empty(commune.get("label"), "Laval"),
            postal_code=first_non_empty(commune.get("codePostal"), "53000"),
            district="",
            property_type="flat",
            price=to_float(ad.get("prix")),
            charges=None,
            surface_area=to_float(ad.get("surface")),
            rooms=to_int(ad.get("piecesnb")),
            bedrooms=None,
            furnished=to_bool(detail.get("estMeuble")) if detail.get("estMeuble") is not None else None,
            energy_class=first_non_empty(detail.get("dpe")),
            greenhouse_gas_class=first_non_empty(detail.get("ges")),
            description=description,
            modification_date=first_non_empty(ad.get("date")),
            availability_date=None,
            phone=first_non_empty(utilisateur.get("telephone")) if detail.get("afficheTelephone") else None,
            agency_name=source_label or "Entreparticuliers",
            detail_api_url=detail_source_url,
            detail_page_url=detail_url,
            latitude=to_float(ad.get("latitude")),
            longitude=to_float(ad.get("longitude")),
            distance_to_esiea_km=None,
            walk_time_to_esiea_min=None,
            bike_time_to_esiea_min=None,
            drive_time_to_esiea_min=None,
            transit_route_url="",
            walking_route_url="",
            biking_route_url="",
            driving_route_url="",
        )
        listings.append(listing)
    return listings


def fetch_square_habitat_listings(max_results: int) -> list[Listing]:
    try:
        html_text = http_get_text(SQUARE_HABITAT_SEARCH_URL)
    except Exception:
        return []

    item_list_payload: dict[str, Any] | None = None
    for script_content in extract_script_contents(html_text):
        if '"@type": "ItemList"' in script_content and "Appartement à louer - LAVAL" in script_content:
            try:
                item_list_payload = json.loads(script_content)
            except json.JSONDecodeError:
                item_list_payload = None
            break
    if not item_list_payload:
        return []

    listings: list[Listing] = []
    for item in item_list_payload.get("itemListElement") or []:
        product = item.get("item") or {}
        offers = product.get("offers") or {}
        title = collapse_whitespace(first_non_empty(product.get("name")))
        rooms_text = extract_first_group(r"(\d+)\s*pi[eè]ce", title, flags=re.IGNORECASE)
        detail_url = first_non_empty(product.get("url"), SQUARE_HABITAT_SEARCH_URL)

        listing = Listing(
            listing_id=str(item.get("position") or detail_url),
            source_name="Square Habitat",
            title=title,
            generated_title=title,
            city="Laval",
            postal_code="53000",
            district="",
            property_type="flat",
            price=to_float(offers.get("price")),
            charges=None,
            surface_area=None,
            rooms=to_int(rooms_text),
            bedrooms=None,
            furnished=None,
            energy_class="",
            greenhouse_gas_class="",
            description="Annonce Square Habitat disponible sur le lien source.",
            modification_date=None,
            availability_date=None,
            phone=None,
            agency_name="Square Habitat Laval",
            detail_api_url=detail_url,
            detail_page_url=detail_url,
            latitude=None,
            longitude=None,
            distance_to_esiea_km=None,
            walk_time_to_esiea_min=None,
            bike_time_to_esiea_min=None,
            drive_time_to_esiea_min=None,
            transit_route_url="",
            walking_route_url="",
            biking_route_url="",
            driving_route_url="",
        )
        listings.append(listing)
        if len(listings) >= max_results:
            break
    return listings


def listing_quality_score(listing: Listing) -> tuple[int, int, int, int, int, int]:
    return (
        1 if listing.latitude is not None and listing.longitude is not None else 0,
        1 if listing.phone else 0,
        1 if listing.charges is not None else 0,
        1 if listing.availability_date else 0,
        1 if listing.surface_area is not None else 0,
        len(listing.description or ""),
    )


def dedupe_listings(listings: list[Listing]) -> list[Listing]:
    deduped: list[Listing] = []
    key_to_index: dict[tuple[str, ...], int] = {}
    for listing in listings:
        surface_key = ""
        if listing.surface_area is not None:
            surface_key = str(int(float(listing.surface_area)))
        title_key = (
            listing.city.lower().strip(),
            str(int(listing.price)) if listing.price is not None else "",
            surface_key,
            slugify(listing.display_title)[:80],
        )
        phone_digits = re.sub(r"\D", "", listing.phone or "")
        contact_key = (
            "contact",
            listing.city.lower().strip(),
            phone_digits,
            str(int(listing.price)) if listing.price is not None else "",
            surface_key,
            str(listing.rooms or ""),
        )
        candidate_keys = [title_key]
        if phone_digits and listing.price is not None and listing.surface_area is not None:
            candidate_keys.append(contact_key)
        if listing.display_title.startswith("Appartement à louer - LAVAL") and listing.price is not None:
            candidate_keys.append(
                (
                    "generic-price-room",
                    listing.city.lower().strip(),
                    str(int(listing.price)),
                    str(listing.rooms or ""),
                )
            )

        existing_index = None
        for candidate_key in candidate_keys:
            if candidate_key in key_to_index:
                existing_index = key_to_index[candidate_key]
                break

        if existing_index is None:
            deduped.append(listing)
            new_index = len(deduped) - 1
            for candidate_key in candidate_keys:
                key_to_index[candidate_key] = new_index
            continue

        if listing_quality_score(listing) > listing_quality_score(deduped[existing_index]):
            deduped[existing_index] = listing
        for candidate_key in candidate_keys:
            key_to_index[candidate_key] = existing_index
    return deduped


def fetch_listings(zone_id: str, include_parking: bool, max_results: int) -> list[Listing]:
    bienici_limit = min(max_results, 20)
    medium_source_limit = min(max_results, 10)
    small_source_limit = min(max_results, 8)
    listings = fetch_bienici_listings(zone_id, include_parking=include_parking, max_results=bienici_limit)
    listings.extend(fetch_paruvendu_listings(max_results=small_source_limit))
    listings.extend(fetch_fnaim_listings(max_results=medium_source_limit))
    listings.extend(fetch_entreparticuliers_listings(max_results=medium_source_limit))
    listings.extend(fetch_square_habitat_listings(max_results=small_source_limit))
    listings = dedupe_listings(listings)
    listings.sort(key=lambda item: (item.price is None, item.price or float("inf"), item.surface_area or float("inf")))
    top_listings = listings[:max_results]
    return [enrich_listing_with_esiea_commute(item) for item in top_listings]


def to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def to_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def build_text_report(listings: list[Listing], generated_at: datetime) -> str:
    source_summary = build_source_summary(listings)
    lines = [
        f"Offres de logement a Laval (53000) - {generated_at.strftime('%Y-%m-%d %H:%M')}",
        "",
        f"{len(listings)} offre(s) recuperee(s), triee(s) du moins cher au plus cher.",
        f"Sources: {source_summary or 'Aucune'}",
        "",
    ]

    for index, listing in enumerate(listings, start=1):
        lines.extend(format_listing_text(index, listing))
        lines.append("")

    if not listings:
        lines.append("Aucune offre residentielle en location n'a ete trouvee aujourd'hui.")
    return "\n".join(lines).strip() + "\n"


def format_listing_text(index: int, listing: Listing) -> list[str]:
    property_label = PROPERTY_TYPE_LABELS.get(listing.property_type, listing.property_type or "Logement")
    parts = [
        f"{index}. {listing.display_title}",
        f"   Source: {listing.source_name}",
        f"   Prix: {format_price(listing.price)}",
        f"   Type: {property_label}",
        f"   Surface: {format_area(listing.surface_area)}",
        f"   Pieces: {listing.rooms if listing.rooms is not None else 'Non renseigne'}",
        f"   Chambres: {listing.bedrooms if listing.bedrooms is not None else 'Non renseigne'}",
        f"   Meuble: {format_bool_fr(listing.furnished)}",
        f"   Localisation: {', '.join(part for part in [listing.district, listing.city, listing.postal_code] if part)}",
        f"   Charges: {format_price(listing.charges) if listing.charges is not None else 'Non renseignees'}",
        f"   DPE / GES: {first_non_empty(listing.energy_class, '?')} / {first_non_empty(listing.greenhouse_gas_class, '?')}",
        f"   Agence: {listing.agency_name or 'Non renseignee'}",
        f"   Telephone: {listing.phone or 'Non renseigne'}",
        f"   Disponibilite: {format_availability_date(listing.availability_date)}",
        f"   Distance jusqu'a {ESIEA_LAVAL_NAME}: {format_distance_km(listing.distance_to_esiea_km)}",
        f"   Temps estimes vers {ESIEA_LAVAL_NAME}: a pied {format_duration_min(listing.walk_time_to_esiea_min)} | velo {format_duration_min(listing.bike_time_to_esiea_min)} | voiture {format_duration_min(listing.drive_time_to_esiea_min)}",
        f"   Transport en commun: {listing.transit_route_url}",
        f"   Itineraire a pied: {listing.walking_route_url}",
        f"   Lien annonce: {listing.detail_page_url}",
        f"   Lien detail API: {listing.detail_api_url}",
        f"   Resume: {truncate(listing.description, 420)}",
    ]
    return parts


def format_bool_fr(value: bool | None) -> str:
    if value is None:
        return "Non renseigne"
    return "Oui" if value else "Non"


def format_distance_km(value: float | None) -> str:
    if value is None:
        return "Non disponible"
    return f"{value:.1f} km".replace(".", ",")


def format_duration_min(value: int | None) -> str:
    if value is None:
        return "Non disponible"
    if value < 60:
        return f"{value} min"
    hours, minutes = divmod(value, 60)
    if minutes == 0:
        return f"{hours} h"
    return f"{hours} h {minutes} min"


def truncate(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value
    return value[: max_length - 3].rstrip() + "..."


def build_html_report(listings: list[Listing], generated_at: datetime) -> str:
    source_summary = build_source_summary(listings)
    cards = []
    for index, listing in enumerate(listings, start=1):
        cards.append(
            f"""
            <div style="border:1px solid #ddd;border-radius:10px;padding:16px;margin:0 0 16px 0;">
              <h3 style="margin:0 0 10px 0;">{index}. {escape_html(listing.display_title)}</h3>
              <p style="margin:4px 0;"><strong>Source:</strong> {escape_html(listing.source_name)}</p>
              <p style="margin:4px 0;"><strong>Prix:</strong> {escape_html(format_price(listing.price))}</p>
              <p style="margin:4px 0;"><strong>Type:</strong> {escape_html(PROPERTY_TYPE_LABELS.get(listing.property_type, listing.property_type or "Logement"))}</p>
              <p style="margin:4px 0;"><strong>Surface:</strong> {escape_html(format_area(listing.surface_area))}</p>
              <p style="margin:4px 0;"><strong>Pieces:</strong> {listing.rooms if listing.rooms is not None else 'Non renseigne'}</p>
              <p style="margin:4px 0;"><strong>Chambres:</strong> {listing.bedrooms if listing.bedrooms is not None else 'Non renseigne'}</p>
              <p style="margin:4px 0;"><strong>Meuble:</strong> {escape_html(format_bool_fr(listing.furnished))}</p>
              <p style="margin:4px 0;"><strong>Localisation:</strong> {escape_html(', '.join(part for part in [listing.district, listing.city, listing.postal_code] if part))}</p>
              <p style="margin:4px 0;"><strong>Charges:</strong> {escape_html(format_price(listing.charges) if listing.charges is not None else 'Non renseignees')}</p>
              <p style="margin:4px 0;"><strong>DPE / GES:</strong> {escape_html(first_non_empty(listing.energy_class, '?'))} / {escape_html(first_non_empty(listing.greenhouse_gas_class, '?'))}</p>
              <p style="margin:4px 0;"><strong>Agence:</strong> {escape_html(listing.agency_name or 'Non renseignee')}</p>
              <p style="margin:4px 0;"><strong>Telephone:</strong> {escape_html(listing.phone or 'Non renseigne')}</p>
              <p style="margin:4px 0;"><strong>Disponibilite:</strong> {escape_html(format_availability_date(listing.availability_date))}</p>
              <p style="margin:4px 0;"><strong>Distance jusqu'a {escape_html(ESIEA_LAVAL_NAME)}:</strong> {escape_html(format_distance_km(listing.distance_to_esiea_km))}</p>
              <p style="margin:4px 0;"><strong>Temps estimes:</strong> a pied {escape_html(format_duration_min(listing.walk_time_to_esiea_min))} | velo {escape_html(format_duration_min(listing.bike_time_to_esiea_min))} | voiture {escape_html(format_duration_min(listing.drive_time_to_esiea_min))}</p>
              <p style="margin:8px 0 0 0;"><strong>Resume:</strong> {escape_html(truncate(listing.description, 650))}</p>
              <p style="margin:12px 0 0 0;">
                <a href="{escape_html(listing.transit_route_url)}">Transport en commun vers ESIEA</a>
                &nbsp;|&nbsp;
                <a href="{escape_html(listing.walking_route_url)}">A pied</a>
                &nbsp;|&nbsp;
                <a href="{escape_html(listing.biking_route_url)}">Velo</a>
                &nbsp;|&nbsp;
                <a href="{escape_html(listing.driving_route_url)}">Voiture</a>
                &nbsp;|&nbsp;
                <a href="{escape_html(listing.detail_page_url)}">Voir l'annonce</a>
                &nbsp;|&nbsp;
                <a href="{escape_html(listing.detail_api_url)}">Voir la source detail</a>
              </p>
            </div>
            """
        )

    if not cards:
        cards = ["<p>Aucune offre residentielle en location n'a ete trouvee aujourd'hui.</p>"]

    return f"""
    <html>
      <body style="font-family:Arial,sans-serif;line-height:1.5;color:#222;">
        <h2>Offres de logement a Laval (53000)</h2>
        <p>Generation: {escape_html(generated_at.strftime('%Y-%m-%d %H:%M'))}</p>
        <p>{len(listings)} offre(s) recuperee(s), triee(s) du moins cher au plus cher.</p>
        <p><strong>Sources:</strong> {escape_html(source_summary or 'Aucune')}</p>
        {''.join(cards)}
      </body>
    </html>
    """.strip()


def escape_html(value: str) -> str:
    return html.escape(value, quote=True)


def send_email(
    smtp_host: str,
    smtp_port: int,
    smtp_username: str,
    smtp_password: str,
    recipient: str,
    subject: str,
    text_body: str,
    html_body: str,
) -> None:
    msg = EmailMessage()
    msg["From"] = smtp_username
    msg["To"] = recipient
    msg["Subject"] = subject
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")

    context = ssl.create_default_context()
    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        server.starttls(context=context)
        server.login(smtp_username, smtp_password)
        server.send_message(msg)


def save_state(path: Path, recipient: str, listings: list[Listing], generated_at: datetime) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": generated_at.isoformat(),
        "recipient": recipient,
        "count": len(listings),
        "listing_ids": [item.listing_id for item in listings],
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def main() -> int:
    args = parse_args()
    env_path = Path(args.env_file)
    state_path = Path(args.state_file)
    env_values = load_env_file(env_path)

    recipient = get_setting(args.recipient, env_values, "RECIPIENT_EMAIL", DEFAULT_RECIPIENT)
    city_query = get_setting(args.city_query, env_values, "CITY_QUERY", DEFAULT_CITY_QUERY)
    postal_code = get_setting(args.postal_code, env_values, "CITY_POSTAL_CODE", DEFAULT_CITY_POSTAL_CODE)
    max_results = int(get_setting(args.max_results, env_values, "MAX_RESULTS", DEFAULT_MAX_RESULTS))
    include_parking_value = get_setting(
        "true" if args.include_parking else None,
        env_values,
        "INCLUDE_PARKING",
        str(DEFAULT_INCLUDE_PARKING).lower(),
    )
    include_parking = str(include_parking_value).lower() in {"1", "true", "yes", "oui"}

    try:
        zone_id = resolve_laval_zone_id(city_query, postal_code)
        listings = fetch_listings(zone_id, include_parking=include_parking, max_results=max_results)
    except Exception as exc:
        print(f"ERREUR collecte: {exc}", file=sys.stderr)
        return 1

    generated_at = datetime.now()
    text_report = build_text_report(listings, generated_at)
    html_report = build_html_report(listings, generated_at)

    if args.json:
        print(
            json.dumps(
                {
                    "recipient": recipient,
                    "zone_id": zone_id,
                    "count": len(listings),
                    "listings": [listing.__dict__ for listing in listings],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(text_report)

    if args.dry_run:
        save_state(state_path, recipient, listings, generated_at)
        return 0

    smtp_host = get_setting(None, env_values, "SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(get_setting(None, env_values, "SMTP_PORT", "587"))
    smtp_username = get_setting(None, env_values, "SMTP_USERNAME", recipient)
    smtp_password = get_setting(None, env_values, "SMTP_PASSWORD", "")

    if not smtp_password:
        print(
            "ERREUR envoi: SMTP_PASSWORD manquant. Ajoute un mot de passe d'application dans .env.",
            file=sys.stderr,
        )
        return 2

    subject = f"Logements Laval - {generated_at.strftime('%Y-%m-%d')}"
    try:
        send_email(
            smtp_host=smtp_host,
            smtp_port=smtp_port,
            smtp_username=smtp_username,
            smtp_password=smtp_password,
            recipient=recipient,
            subject=subject,
            text_body=text_report,
            html_body=html_report,
        )
        save_state(state_path, recipient, listings, generated_at)
    except Exception as exc:
        print(f"ERREUR envoi email: {exc}", file=sys.stderr)
        return 3

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
