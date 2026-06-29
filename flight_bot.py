#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib import request

from logement_bot import escape_html, get_setting, load_env_file, send_email


DEFAULT_ENV_PATH = Path(".env")
DEFAULT_RECIPIENT = "92mamadousy@gmail.com"
DEFAULT_TIMEOUT = 30
DEFAULT_TARGETS = "paris,nantes,rennes"
DEFAULT_START_DATE = "2026-08-01"
DEFAULT_END_DATE = "2026-09-10"
DEFAULT_MAX_RESULTS = 15
DEFAULT_LOCALE = "fr"
DEFAULT_GL = "SN"
GOOGLE_FLIGHTS_BASE_URL = "https://www.google.com/travel/flights"


@dataclass(frozen=True)
class TrustedCarrier:
    name: str
    official_url: str
    typical_stops: str
    typical_route: str
    note: str


@dataclass(frozen=True)
class RouteProfile:
    route_slug: str
    airport_label: str
    laval_transfer: str
    practical_note: str
    reliability_note: str
    carriers: tuple[TrustedCarrier, ...]


@dataclass(frozen=True)
class FlightOffer:
    source_name: str
    route_slug: str
    origin_airport: str
    destination_airport: str
    departure_date: str
    airline_name: str
    airline_codes: tuple[str, ...]
    price: int
    stops: int
    duration_hours: int | None
    route_url: str

    @property
    def destination_label(self) -> str:
        return self.route_slug.replace("-", " ").title()


@dataclass(frozen=True)
class MonthlyFareSignal:
    route_slug: str
    month: int
    low_price: int
    high_price: int
    route_url: str

    @property
    def destination_label(self) -> str:
        return self.route_slug.replace("-", " ").title()


@dataclass(frozen=True)
class SmartRecommendation:
    route_slug: str
    destination_label: str
    month: int
    low_price: int
    high_price: int
    airport_label: str
    laval_transfer: str
    practical_note: str
    reliability_note: str
    carriers: tuple[TrustedCarrier, ...]
    route_url: str
    rank_score: int


TRUSTED_ROUTE_PROFILES: dict[str, RouteProfile] = {
    "paris": RouteProfile(
        route_slug="paris",
        airport_label="Paris CDG / ORY",
        laval_transfer="Train vers Laval via Paris-Montparnasse, souvent autour de 1h15 a 1h40 apres le transfert aeroport -> gare.",
        practical_note="Souvent le meilleur prix et le plus de choix; il faut juste gerer le transfert dans Paris.",
        reliability_note="Tres bonne option si le prix est nettement moins cher que Nantes/Rennes.",
        carriers=(
            TrustedCarrier(
                name="Air Senegal",
                official_url="https://www.flyairsenegal.com/",
                typical_stops="direct",
                typical_route="DSS -> CDG",
                note="Compagnie nationale, route Dakar-Paris a verifier en premier pour un aller simple direct.",
            ),
            TrustedCarrier(
                name="Air France",
                official_url="https://wwws.airfrance.sn/",
                typical_stops="direct",
                typical_route="DSS -> CDG",
                note="Compagnie solide pour Paris, souvent plus chere mais directe.",
            ),
            TrustedCarrier(
                name="Royal Air Maroc",
                official_url="https://www.royalairmaroc.com/",
                typical_stops="1 escale",
                typical_route="DSS -> Casablanca -> Paris",
                note="Souvent competitive si l'escale a Casablanca reste raisonnable.",
            ),
            TrustedCarrier(
                name="TAP Air Portugal",
                official_url="https://www.flytap.com/",
                typical_stops="1 escale",
                typical_route="DSS -> Lisbonne -> Paris",
                note="Bonne alternative si le prix baisse sur ORY/CDG.",
            ),
        ),
    ),
    "nantes": RouteProfile(
        route_slug="nantes",
        airport_label="Nantes Atlantique (NTE)",
        laval_transfer="Nantes -> Laval en train ou train + correspondance, souvent autour de 1h30 a 2h30 selon l'horaire.",
        practical_note="Tres interessant pour Laval si le prix reste proche de Paris, car l'arrivee est plus simple.",
        reliability_note="Bon compromis prix/praticite quand il y a une offre correcte.",
        carriers=(
            TrustedCarrier(
                name="Transavia",
                official_url="https://www.transavia.com/",
                typical_stops="souvent direct selon saison",
                typical_route="DSS -> NTE",
                note="A verifier en priorite pour Nantes quand Google signale un tarif bas.",
            ),
            TrustedCarrier(
                name="Royal Air Maroc",
                official_url="https://www.royalairmaroc.com/",
                typical_stops="1 escale",
                typical_route="DSS -> Casablanca -> Nantes",
                note="Alternative fiable si le direct n'est pas disponible.",
            ),
            TrustedCarrier(
                name="Air France",
                official_url="https://wwws.airfrance.sn/",
                typical_stops="1 escale",
                typical_route="DSS -> Paris -> Nantes",
                note="Fiable, mais a comparer car le trajet peut revenir plus cher.",
            ),
        ),
    ),
    "rennes": RouteProfile(
        route_slug="rennes",
        airport_label="Rennes Bretagne (RNS)",
        laval_transfer="Rennes -> Laval est court en train ou voiture, souvent autour de 1h a 1h30.",
        practical_note="Tres pratique pour Laval, mais les vols Dakar-Rennes sont souvent plus rares et plus chers.",
        reliability_note="A garder comme option confort si l'ecart de prix avec Paris/Nantes est faible.",
        carriers=(
            TrustedCarrier(
                name="Air France",
                official_url="https://wwws.airfrance.sn/",
                typical_stops="1 escale",
                typical_route="DSS -> Paris -> Rennes",
                note="Option la plus logique si Rennes apparait a un prix acceptable.",
            ),
            TrustedCarrier(
                name="Royal Air Maroc",
                official_url="https://www.royalairmaroc.com/",
                typical_stops="1 a 2 escales",
                typical_route="DSS -> Casablanca -> France -> Rennes",
                note="A verifier seulement si le prix est vraiment interessant.",
            ),
        ),
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Recupere les billets Dakar -> France les moins chers via Google Flights et les envoie par email."
    )
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_PATH))
    parser.add_argument("--recipient", default=None)
    parser.add_argument("--targets", default=None)
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--max-results", type=int, default=None)
    parser.add_argument("--locale", default=None)
    parser.add_argument("--gl", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def fetch_html(url: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    curl_path = shutil.which("curl")
    if curl_path:
        completed = subprocess.run(
            [curl_path, "-sS", "-L", url],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
        return completed.stdout

    req = request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
            ),
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
        },
    )
    with request.urlopen(req, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def build_route_url(route_slug: str, locale: str, gl: str) -> str:
    return f"{GOOGLE_FLIGHTS_BASE_URL}/flights-from-dakar-to-{route_slug}.html?hl={locale}&gl={gl}"


def parse_airline_values(raw: str) -> tuple[str, ...]:
    return tuple(value for value in re.findall(r'"([^"]+)"', raw) if value)


def extract_one_way_offers(text: str, route_slug: str, route_url: str) -> list[FlightOffer]:
    pattern = re.compile(
        r"""
        \[\[\s*null\s*,\s*(?P<price>\d+)\s*\]\s*,\s*"[^"]*"\s*\]
        \s*,\s*null
        \s*,\s*"(?P<departure>\d{4}-\d{2}-\d{2})"
        \s*,\s*null
        \s*,\s*"(?P<origin>[A-Z]{3})"
        \s*,\s*"(?P<destination>[A-Z]{3})"
        \s*,\s*(?P<duration>\d+|null)
        \s*,\s*null
        \s*,\s*(?P<stops>\d+)
        \s*,\s*\[(?P<airline_codes>[^\]]*)\]
        \s*,\s*\[(?P<airline_names>[^\]]*)\]
        """,
        re.VERBOSE,
    )

    offers: list[FlightOffer] = []
    seen: set[tuple[str, str, str, int, int]] = set()
    for match in pattern.finditer(text):
        airline_names = parse_airline_values(match.group("airline_names"))
        airline_codes = parse_airline_values(match.group("airline_codes"))
        airline_name = airline_names[0] if airline_names else "Compagnie non identifiee"
        offer = FlightOffer(
            source_name="Google Flights",
            route_slug=route_slug,
            origin_airport=match.group("origin"),
            destination_airport=match.group("destination"),
            departure_date=match.group("departure"),
            airline_name=airline_name,
            airline_codes=airline_codes,
            price=int(match.group("price")),
            stops=int(match.group("stops")),
            duration_hours=None if match.group("duration") == "null" else int(match.group("duration")),
            route_url=route_url,
        )
        dedupe_key = (
            offer.departure_date,
            offer.origin_airport,
            offer.destination_airport,
            offer.price,
            offer.stops,
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        offers.append(offer)
    return offers


def extract_monthly_signals(text: str, route_slug: str, route_url: str) -> list[MonthlyFareSignal]:
    pattern = re.compile(r"\[(\d{1,2}),\[\[null,(\d+)\]\],\[\[null,(\d+)\]\]\]")
    seen: set[tuple[int, int, int]] = set()
    signals: list[MonthlyFareSignal] = []
    for month_raw, low_raw, high_raw in pattern.findall(text):
        month = int(month_raw)
        low_price = int(low_raw)
        high_price = int(high_raw)
        dedupe_key = (month, low_price, high_price)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        signals.append(
            MonthlyFareSignal(
                route_slug=route_slug,
                month=month,
                low_price=low_price,
                high_price=high_price,
                route_url=route_url,
            )
        )
    return signals


def filter_offers(
    offers: list[FlightOffer],
    start_date: str,
    end_date: str,
    max_results: int,
) -> list[FlightOffer]:
    start_value = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_value = datetime.strptime(end_date, "%Y-%m-%d").date()
    filtered = [
        offer
        for offer in offers
        if start_value <= datetime.strptime(offer.departure_date, "%Y-%m-%d").date() <= end_value
    ]
    filtered.sort(key=lambda item: (item.price, item.departure_date, item.destination_airport, item.airline_name))
    return filtered[:max_results]


def filter_monthly_signals(
    signals: list[MonthlyFareSignal],
    start_date: str,
    end_date: str,
) -> list[MonthlyFareSignal]:
    start_value = datetime.strptime(start_date, "%Y-%m-%d").date()
    end_value = datetime.strptime(end_date, "%Y-%m-%d").date()
    months_in_scope = build_month_scope(start_value, end_value)
    filtered = [signal for signal in signals if signal.month in months_in_scope]
    filtered.sort(key=lambda item: (item.low_price, item.month, item.destination_label))
    return filtered


def build_smart_recommendations(monthly_signals: list[MonthlyFareSignal]) -> list[SmartRecommendation]:
    best_by_route_month: dict[tuple[str, int], MonthlyFareSignal] = {}
    for signal in monthly_signals:
        key = (signal.route_slug, signal.month)
        current = best_by_route_month.get(key)
        if current is None or signal.low_price < current.low_price:
            best_by_route_month[key] = signal

    route_penalties = {"nantes": 0, "paris": 15000, "rennes": 25000}
    recommendations: list[SmartRecommendation] = []
    for signal in best_by_route_month.values():
        profile = TRUSTED_ROUTE_PROFILES.get(signal.route_slug)
        if profile is None:
            continue
        recommendations.append(
            SmartRecommendation(
                route_slug=signal.route_slug,
                destination_label=signal.destination_label,
                month=signal.month,
                low_price=signal.low_price,
                high_price=signal.high_price,
                airport_label=profile.airport_label,
                laval_transfer=profile.laval_transfer,
                practical_note=profile.practical_note,
                reliability_note=profile.reliability_note,
                carriers=profile.carriers,
                route_url=signal.route_url,
                rank_score=signal.low_price + route_penalties.get(signal.route_slug, 30000),
            )
        )
    recommendations.sort(key=lambda item: (item.rank_score, item.low_price, item.month))
    return recommendations


def build_month_scope(start_value: date, end_value: date) -> set[int]:
    months: set[int] = set()
    cursor = date(start_value.year, start_value.month, 1)
    last = date(end_value.year, end_value.month, 1)
    while cursor <= last:
        months.add(cursor.month)
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
    return months


def format_price(value: int) -> str:
    return f"{value:,}".replace(",", " ") + " FCFA"


def format_stops(value: int) -> str:
    if value == 0:
        return "direct"
    if value == 1:
        return "1 escale"
    return f"{value} escales"


def format_duration(hours: int | None) -> str:
    if hours is None:
        return "non precise"
    return f"{hours} h"


def format_month_label(month: int) -> str:
    labels = {
        1: "janvier",
        2: "fevrier",
        3: "mars",
        4: "avril",
        5: "mai",
        6: "juin",
        7: "juillet",
        8: "aout",
        9: "septembre",
        10: "octobre",
        11: "novembre",
        12: "decembre",
    }
    return labels.get(month, str(month))


def build_text_report(
    offers: list[FlightOffer],
    monthly_signals: list[MonthlyFareSignal],
    recommendations: list[SmartRecommendation],
    generated_at: datetime,
    start_date: str,
    end_date: str,
) -> str:
    lines = [
        "Billets Dakar -> France",
        f"Generation: {generated_at.strftime('%Y-%m-%d %H:%M')}",
        f"Periode cible: {start_date} -> {end_date}",
        f"Offres retenues: {len(offers)}",
        f"Reperes mensuels: {len(monthly_signals)}",
        "",
    ]

    if recommendations:
        best = recommendations[0]
        lines.extend(
            [
                "Conclusion rapide:",
                (
                    f"- Option la plus interessante detectee: {best.destination_label} en "
                    f"{format_month_label(best.month)} a partir de {format_price(best.low_price)} "
                    f"(plage haute observee {format_price(best.high_price)})."
                ),
                f"- Arrivee: {best.airport_label}.",
                f"- Pour Laval: {best.laval_transfer}",
                f"- A verifier d'abord chez: {', '.join(carrier.name for carrier in best.carriers[:3])}.",
                "",
                "Options fiables a verifier:",
            ]
        )
        for index, recommendation in enumerate(recommendations, start=1):
            lines.extend(
                [
                    (
                        f"{index}. {recommendation.destination_label} | {format_month_label(recommendation.month)} | "
                        f"prix repere {format_price(recommendation.low_price)} a {format_price(recommendation.high_price)}"
                    ),
                    f"   Arrivee: {recommendation.airport_label}",
                    f"   Pour Laval: {recommendation.laval_transfer}",
                    f"   Lecture: {recommendation.practical_note}",
                    f"   Source prix: {recommendation.route_url}",
                    "   Compagnies fiables:",
                ]
            )
            for carrier in recommendation.carriers:
                lines.extend(
                    [
                        f"   - {carrier.name}: {carrier.typical_route} | {carrier.typical_stops}",
                        f"     Site officiel: {carrier.official_url}",
                        f"     Note: {carrier.note}",
                    ]
                )
            lines.append("")

    if monthly_signals:
        lines.append("Reperes mensuels Google Flights sur ta plage:")
        for signal in monthly_signals:
            lines.append(
                f"- {signal.destination_label} | {format_month_label(signal.month)} | "
                f"mini repere {format_price(signal.low_price)} | plage haute {format_price(signal.high_price)}"
            )
            lines.append(f"  Lien: {signal.route_url}")
        lines.append("")

    if not offers:
        lines.append("Aucune offre aller simple exacte n'a ete exposee aujourd'hui sur la periode demandee.")
        lines.append("Source: Google Flights")
        return "\n".join(lines)

    for index, offer in enumerate(offers, start=1):
        lines.extend(
            [
                f"{index}. {offer.airline_name} | {offer.destination_label} ({offer.destination_airport})",
                f"   Prix: {format_price(offer.price)}",
                f"   Depart: {offer.departure_date}",
                f"   Trajet: {offer.origin_airport} -> {offer.destination_airport}",
                f"   Escales: {format_stops(offer.stops)}",
                f"   Duree estimee: {format_duration(offer.duration_hours)}",
                f"   Source: {offer.source_name}",
                f"   Lien: {offer.route_url}",
                "",
            ]
        )
    return "\n".join(lines).strip()


def build_html_report(
    offers: list[FlightOffer],
    monthly_signals: list[MonthlyFareSignal],
    recommendations: list[SmartRecommendation],
    generated_at: datetime,
    start_date: str,
    end_date: str,
) -> str:
    recommendation_cards: list[str] = []
    for index, recommendation in enumerate(recommendations, start=1):
        carrier_rows = []
        for carrier in recommendation.carriers:
            carrier_rows.append(
                f"""
                <li style="margin:8px 0;">
                  <strong>{escape_html(carrier.name)}</strong> - {escape_html(carrier.typical_route)}
                  <br><span>{escape_html(carrier.typical_stops)} | {escape_html(carrier.note)}</span>
                  <br><a href="{escape_html(carrier.official_url)}">Site officiel</a>
                </li>
                """.strip()
            )
        recommendation_cards.append(
            f"""
            <div style="border:2px solid #1f6feb;border-radius:12px;padding:16px;margin:0 0 16px 0;background:#f6fbff;">
              <h3 style="margin:0 0 8px 0;">{index}. {escape_html(recommendation.destination_label)} - {escape_html(format_month_label(recommendation.month))}</h3>
              <p style="margin:4px 0;"><strong>Prix repere:</strong> {escape_html(format_price(recommendation.low_price))} a {escape_html(format_price(recommendation.high_price))}</p>
              <p style="margin:4px 0;"><strong>Arrivee:</strong> {escape_html(recommendation.airport_label)}</p>
              <p style="margin:4px 0;"><strong>Pour Laval:</strong> {escape_html(recommendation.laval_transfer)}</p>
              <p style="margin:4px 0;"><strong>Lecture:</strong> {escape_html(recommendation.practical_note)}</p>
              <p style="margin:10px 0;"><a href="{escape_html(recommendation.route_url)}">Comparer sur Google Flights</a></p>
              <ul style="padding-left:18px;margin:8px 0 0 0;">{''.join(carrier_rows)}</ul>
            </div>
            """.strip()
        )

    signal_cards: list[str] = []
    for signal in monthly_signals:
        signal_cards.append(
            f"""
            <div style="border:1px solid #e6e6e6;border-radius:12px;padding:14px;margin:0 0 12px 0;background:#fafafa;">
              <h3 style="margin:0 0 8px 0;">{escape_html(signal.destination_label)} | {escape_html(format_month_label(signal.month))}</h3>
              <p style="margin:4px 0;"><strong>Mini repere:</strong> {escape_html(format_price(signal.low_price))}</p>
              <p style="margin:4px 0;"><strong>Plage haute:</strong> {escape_html(format_price(signal.high_price))}</p>
              <p style="margin:10px 0 0 0;"><a href="{escape_html(signal.route_url)}">Voir la route sur Google Flights</a></p>
            </div>
            """.strip()
        )

    cards: list[str] = []
    for offer in offers:
        cards.append(
            f"""
            <div style="border:1px solid #ddd;border-radius:12px;padding:16px;margin:0 0 16px 0;">
              <h3 style="margin:0 0 8px 0;">{escape_html(offer.airline_name)} | {escape_html(offer.destination_label)} ({escape_html(offer.destination_airport)})</h3>
              <p style="margin:4px 0;"><strong>Prix:</strong> {escape_html(format_price(offer.price))}</p>
              <p style="margin:4px 0;"><strong>Depart:</strong> {escape_html(offer.departure_date)}</p>
              <p style="margin:4px 0;"><strong>Trajet:</strong> {escape_html(offer.origin_airport)} -&gt; {escape_html(offer.destination_airport)}</p>
              <p style="margin:4px 0;"><strong>Escales:</strong> {escape_html(format_stops(offer.stops))}</p>
              <p style="margin:4px 0;"><strong>Duree estimee:</strong> {escape_html(format_duration(offer.duration_hours))}</p>
              <p style="margin:10px 0 0 0;"><a href="{escape_html(offer.route_url)}">Voir la route sur Google Flights</a></p>
            </div>
            """.strip()
        )

    if not cards:
        cards = [
            "<p>Aucune offre exploitable n'a ete extraite aujourd'hui sur la periode demandee.</p>"
        ]

    return f"""
    <html>
      <body style="font-family:Arial,sans-serif;line-height:1.5;color:#222;">
        <h2>Billets Dakar - France</h2>
        <p><strong>Generation:</strong> {escape_html(generated_at.strftime('%Y-%m-%d %H:%M'))}</p>
        <p><strong>Periode cible:</strong> {escape_html(start_date)} -&gt; {escape_html(end_date)}</p>
        <p><strong>Source:</strong> Google Flights (web scraping)</p>
        <p><strong>Offres retenues:</strong> {len(offers)}</p>
        <p><strong>Reperes mensuels:</strong> {len(monthly_signals)}</p>
        {''.join(recommendation_cards)}
        {''.join(signal_cards)}
        {''.join(cards)}
      </body>
    </html>
    """.strip()


def collect_route_data(
    targets: list[str],
    locale: str,
    gl: str,
) -> tuple[list[FlightOffer], list[MonthlyFareSignal]]:
    offers: list[FlightOffer] = []
    monthly_signals: list[MonthlyFareSignal] = []
    for route_slug in targets:
        route_url = build_route_url(route_slug, locale=locale, gl=gl)
        html = fetch_html(route_url)
        offers.extend(extract_one_way_offers(html, route_slug=route_slug, route_url=route_url))
        monthly_signals.extend(extract_monthly_signals(html, route_slug=route_slug, route_url=route_url))
    return offers, monthly_signals


def main() -> int:
    args = parse_args()
    env_values = load_env_file(Path(args.env_file))

    recipient = get_setting(args.recipient, env_values, "FLIGHT_RECIPIENT_EMAIL", None)
    recipient = recipient or get_setting(None, env_values, "RECIPIENT_EMAIL", DEFAULT_RECIPIENT)
    targets_raw = get_setting(args.targets, env_values, "FLIGHT_TARGETS", DEFAULT_TARGETS)
    start_date = get_setting(args.start_date, env_values, "FLIGHT_START_DATE", DEFAULT_START_DATE)
    end_date = get_setting(args.end_date, env_values, "FLIGHT_END_DATE", DEFAULT_END_DATE)
    max_results = int(get_setting(args.max_results, env_values, "FLIGHT_MAX_RESULTS", DEFAULT_MAX_RESULTS))
    locale = get_setting(args.locale, env_values, "FLIGHT_LOCALE", DEFAULT_LOCALE)
    gl = get_setting(args.gl, env_values, "FLIGHT_GL", DEFAULT_GL)
    targets = [item.strip().lower() for item in str(targets_raw).split(",") if item.strip()]

    try:
        offers, monthly_signals = collect_route_data(targets=targets, locale=locale, gl=gl)
        offers = filter_offers(offers, start_date=start_date, end_date=end_date, max_results=max_results)
        monthly_signals = filter_monthly_signals(monthly_signals, start_date=start_date, end_date=end_date)
        recommendations = build_smart_recommendations(monthly_signals)
    except Exception as exc:
        print(f"ERREUR collecte vols: {exc}", file=sys.stderr)
        return 1

    generated_at = datetime.now()
    text_report = build_text_report(offers, monthly_signals, recommendations, generated_at, start_date, end_date)
    html_report = build_html_report(offers, monthly_signals, recommendations, generated_at, start_date, end_date)

    if args.json:
        payload = {
            "recipient": recipient,
            "count": len(offers),
            "recommendations": [
                {
                    "route_slug": recommendation.route_slug,
                    "destination_label": recommendation.destination_label,
                    "month": recommendation.month,
                    "low_price": recommendation.low_price,
                    "high_price": recommendation.high_price,
                    "airport_label": recommendation.airport_label,
                    "laval_transfer": recommendation.laval_transfer,
                    "carriers": [
                        {
                            "name": carrier.name,
                            "official_url": carrier.official_url,
                            "typical_stops": carrier.typical_stops,
                            "typical_route": carrier.typical_route,
                            "note": carrier.note,
                        }
                        for carrier in recommendation.carriers
                    ],
                    "route_url": recommendation.route_url,
                }
                for recommendation in recommendations
            ],
            "monthly_signals": [
                {
                    "route_slug": signal.route_slug,
                    "month": signal.month,
                    "low_price": signal.low_price,
                    "high_price": signal.high_price,
                    "route_url": signal.route_url,
                }
                for signal in monthly_signals
            ],
            "offers": [
                {
                    "source_name": offer.source_name,
                    "route_slug": offer.route_slug,
                    "origin_airport": offer.origin_airport,
                    "destination_airport": offer.destination_airport,
                    "departure_date": offer.departure_date,
                    "airline_name": offer.airline_name,
                    "airline_codes": list(offer.airline_codes),
                    "price": offer.price,
                    "stops": offer.stops,
                    "duration_hours": offer.duration_hours,
                    "route_url": offer.route_url,
                }
                for offer in offers
            ],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(text_report)

    if args.dry_run:
        return 0

    smtp_host = get_setting(None, env_values, "SMTP_HOST", "smtp.gmail.com")
    smtp_port = int(get_setting(None, env_values, "SMTP_PORT", "587"))
    smtp_username = get_setting(None, env_values, "SMTP_USERNAME", recipient)
    smtp_password = get_setting(None, env_values, "SMTP_PASSWORD", "")

    if not smtp_password:
        print("ERREUR envoi: SMTP_PASSWORD manquant.", file=sys.stderr)
        return 2

    subject = f"Billets Dakar -> France - {generated_at.strftime('%Y-%m-%d')}"
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
    except Exception as exc:
        print(f"ERREUR envoi email: {exc}", file=sys.stderr)
        return 3

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
