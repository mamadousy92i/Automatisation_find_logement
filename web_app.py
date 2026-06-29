#!/usr/bin/env python3
from __future__ import annotations

import errno
import json
import os
import sys
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib import parse

from logement_bot import (
    DEFAULT_CITY_POSTAL_CODE,
    DEFAULT_CITY_QUERY,
    DEFAULT_ENV_PATH,
    DEFAULT_MAX_RESULTS,
    build_search_label,
    build_source_summary,
    escape_html,
    format_area,
    format_availability_date,
    format_bool_fr,
    format_distance_km,
    format_duration_min,
    format_price,
    load_env_file,
    PROPERTY_TYPE_LABELS,
    search_listings,
    suggest_cities,
)


APP_HOST = "127.0.0.1"
APP_PORT = 8080


def html_page(content: str) -> bytes:
    return f"""<!doctype html>
<html lang="fr">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Recherche logement</title>
    <style>
      :root {{
        --bg: #f6f1e8;
        --paper: #fffdf8;
        --ink: #1e2a22;
        --muted: #5d6b61;
        --line: #d8cfbf;
        --accent: #215f4b;
        --accent-soft: #dcebdd;
        --gold: #cda15d;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        font-family: Georgia, "Times New Roman", serif;
        color: var(--ink);
        background:
          radial-gradient(circle at top left, rgba(205,161,93,.18), transparent 32%),
          linear-gradient(180deg, #f3eadc 0%, #f8f4ed 48%, #efe6d7 100%);
      }}
      .shell {{
        max-width: 1180px;
        margin: 0 auto;
        padding: 32px 18px 48px;
      }}
      .hero {{
        display: grid;
        gap: 24px;
        grid-template-columns: 1.1fr .9fr;
        align-items: start;
      }}
      .panel {{
        background: rgba(255,253,248,.92);
        border: 1px solid var(--line);
        border-radius: 24px;
        box-shadow: 0 18px 50px rgba(48, 52, 46, .08);
      }}
      .intro {{
        padding: 28px;
      }}
      .eyebrow {{
        display: inline-block;
        padding: 8px 12px;
        border-radius: 999px;
        background: var(--accent-soft);
        color: var(--accent);
        font-size: 13px;
        letter-spacing: .08em;
        text-transform: uppercase;
      }}
      h1 {{
        margin: 16px 0 10px;
        font-size: clamp(32px, 5vw, 60px);
        line-height: .95;
      }}
      .lead {{
        margin: 0;
        color: var(--muted);
        font-size: 18px;
        line-height: 1.6;
      }}
      .form-card {{
        padding: 24px;
      }}
      form {{
        display: grid;
        gap: 14px;
      }}
      .grid {{
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 14px;
      }}
      label {{
        display: grid;
        gap: 8px;
        font-size: 14px;
        color: var(--muted);
      }}
      input, select {{
        width: 100%;
        border: 1px solid var(--line);
        border-radius: 14px;
        padding: 13px 14px;
        background: white;
        color: var(--ink);
        font: inherit;
      }}
      .checkbox {{
        display: flex;
        align-items: center;
        gap: 10px;
        color: var(--ink);
      }}
      .checkbox input {{
        width: auto;
      }}
      button {{
        border: 0;
        border-radius: 16px;
        padding: 14px 18px;
        background: linear-gradient(135deg, var(--accent) 0%, #2f7b60 100%);
        color: white;
        font-weight: 700;
        font: inherit;
        cursor: pointer;
      }}
      .meta {{
        margin-top: 26px;
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
      }}
      .pill {{
        border: 1px solid var(--line);
        background: rgba(255,255,255,.75);
        border-radius: 999px;
        padding: 8px 12px;
        font-size: 13px;
      }}
      .results {{
        margin-top: 26px;
        display: grid;
        gap: 16px;
      }}
      .listing {{
        padding: 22px;
      }}
      .listing h3 {{
        margin: 0 0 8px;
        font-size: 24px;
      }}
      .price {{
        color: var(--accent);
        font-weight: 700;
        font-size: 22px;
      }}
      .facts {{
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin: 14px 0;
      }}
      .fact {{
        border-radius: 999px;
        background: #f3eee3;
        padding: 7px 12px;
        font-size: 13px;
      }}
      .desc {{
        color: var(--muted);
        line-height: 1.6;
      }}
      .links {{
        display: flex;
        flex-wrap: wrap;
        gap: 14px;
        margin-top: 14px;
      }}
      .link-button {{
        display: inline-flex;
        align-items: center;
        justify-content: center;
        min-height: 46px;
        padding: 12px 16px;
        border-radius: 14px;
        text-decoration: none;
        font-weight: 700;
        transition: transform .18s ease, box-shadow .18s ease, background .18s ease;
      }}
      .link-button:hover {{
        transform: translateY(-2px);
      }}
      .link-primary {{
        background: linear-gradient(135deg, #215f4b 0%, #3c8f6c 100%);
        color: #fffdfa;
        box-shadow: 0 10px 24px rgba(33, 95, 75, .25);
      }}
      .link-secondary {{
        background: linear-gradient(135deg, #efe2c7 0%, #f7f0e2 100%);
        color: #684d23;
        border: 1px solid #dcc8a0;
        box-shadow: 0 10px 20px rgba(120, 96, 42, .12);
      }}
      .notice {{
        margin-top: 18px;
        padding: 14px 16px;
        border-radius: 16px;
        background: #f8f2e3;
        border: 1px solid #e8d8b7;
        color: #6c5421;
      }}
      .autocomplete {{
        position: relative;
      }}
      .suggestions {{
        position: absolute;
        top: calc(100% + 6px);
        left: 0;
        right: 0;
        margin: 0;
        padding: 8px;
        list-style: none;
        border: 1px solid var(--line);
        border-radius: 16px;
        background: rgba(255,253,248,.98);
        box-shadow: 0 18px 40px rgba(48, 52, 46, .12);
        display: none;
        z-index: 10;
      }}
      .suggestions.visible {{
        display: block;
      }}
      .suggestions button {{
        width: 100%;
        border: 0;
        background: transparent;
        color: var(--ink);
        text-align: left;
        padding: 10px 12px;
        border-radius: 12px;
        font-weight: 400;
      }}
      .suggestions button:hover {{
        background: #efe6d7;
      }}
      .loading-overlay {{
        position: fixed;
        inset: 0;
        display: none;
        align-items: center;
        justify-content: center;
        padding: 24px;
        background: rgba(30, 42, 34, .44);
        backdrop-filter: blur(10px);
        z-index: 999;
      }}
      .loading-overlay.visible {{
        display: flex;
      }}
      .loading-card {{
        width: min(420px, 100%);
        padding: 28px;
        border-radius: 28px;
        background: rgba(255, 252, 245, .96);
        border: 1px solid rgba(216, 207, 191, .9);
        box-shadow: 0 24px 70px rgba(0, 0, 0, .18);
        text-align: center;
      }}
      .loading-ring {{
        width: 74px;
        height: 74px;
        margin: 0 auto 18px;
        border-radius: 50%;
        border: 6px solid rgba(33, 95, 75, .14);
        border-top-color: #215f4b;
        animation: spin 1s linear infinite;
      }}
      .loading-dots {{
        display: inline-flex;
        gap: 8px;
        margin-top: 12px;
      }}
      .loading-dots span {{
        width: 10px;
        height: 10px;
        border-radius: 50%;
        background: #cda15d;
        animation: pulse 1.2s infinite ease-in-out;
      }}
      .loading-dots span:nth-child(2) {{
        animation-delay: .15s;
      }}
      .loading-dots span:nth-child(3) {{
        animation-delay: .3s;
      }}
      @keyframes spin {{
        to {{ transform: rotate(360deg); }}
      }}
      @keyframes pulse {{
        0%, 80%, 100% {{ transform: scale(.7); opacity: .45; }}
        40% {{ transform: scale(1); opacity: 1; }}
      }}
      @media (max-width: 860px) {{
        .hero {{
          grid-template-columns: 1fr;
        }}
        .grid {{
          grid-template-columns: 1fr;
        }}
      }}
    </style>
  </head>
  <body>
    <div id="loading-overlay" class="loading-overlay" aria-hidden="true">
      <div class="loading-card">
        <div class="loading-ring"></div>
        <h2 style="margin:0 0 8px;">Recherche en cours</h2>
        <p style="margin:0;color:#5d6b61;line-height:1.6;">
          On collecte les annonces, on trie les resultats et on calcule les proximites.
        </p>
        <div class="loading-dots" aria-hidden="true">
          <span></span>
          <span></span>
          <span></span>
        </div>
      </div>
    </div>
    <div class="shell">
      {content}
    </div>
    <script>
      const cityInput = document.querySelector('[name="city"]');
      const postalInput = document.querySelector('[name="postal_code"]');
      const suggestionBox = document.getElementById('city-suggestions');
      const loadingOverlay = document.getElementById('loading-overlay');
      const searchForm = document.querySelector('.form-card form');
      let activeRequest = 0;

      function hideSuggestions() {{
        suggestionBox.innerHTML = '';
        suggestionBox.classList.remove('visible');
      }}

      async function loadSuggestions() {{
        const query = cityInput.value.trim();
        if (query.length < 2) {{
          hideSuggestions();
          return;
        }}
        const requestId = ++activeRequest;
        const response = await fetch(`/api/city-suggestions?q=${{encodeURIComponent(query)}}`);
        if (!response.ok || requestId !== activeRequest) {{
          return;
        }}
        const items = await response.json();
        if (!Array.isArray(items) || items.length === 0) {{
          hideSuggestions();
          return;
        }}
        suggestionBox.innerHTML = items.map((item) => `
          <li>
            <button type="button" data-city="${{item.city}}" data-postal="${{item.postal_code}}">
              ${{item.label}}
            </button>
          </li>
        `).join('');
        suggestionBox.classList.add('visible');
      }}

      cityInput?.addEventListener('input', () => {{
        loadSuggestions().catch(() => hideSuggestions());
      }});

      suggestionBox?.addEventListener('click', (event) => {{
        const button = event.target.closest('button[data-city]');
        if (!button) return;
        cityInput.value = button.dataset.city || '';
        postalInput.value = button.dataset.postal || '';
        hideSuggestions();
      }});

      document.addEventListener('click', (event) => {{
        if (!suggestionBox.contains(event.target) && event.target !== cityInput) {{
          hideSuggestions();
        }}
      }});

      searchForm?.addEventListener('submit', () => {{
        loadingOverlay?.classList.add('visible');
        loadingOverlay?.setAttribute('aria-hidden', 'false');
      }});

      window.addEventListener('pageshow', () => {{
        loadingOverlay?.classList.remove('visible');
        loadingOverlay?.setAttribute('aria-hidden', 'true');
      }});
    </script>
  </body>
</html>
""".encode("utf-8")


def render_listing_card(index: int, listing, reference_label: str | None = None) -> str:
    commute_block = ""
    if listing.distance_to_esiea_km is not None or listing.transit_route_url:
        effective_label = reference_label or "point de reference"
        commute_block = f"""
        <div class="facts">
          <span class="fact">Distance {escape_html(effective_label)}: {escape_html(format_distance_km(listing.distance_to_esiea_km))}</span>
          <span class="fact">A pied: {escape_html(format_duration_min(listing.walk_time_to_esiea_min))}</span>
          <span class="fact">Velo: {escape_html(format_duration_min(listing.bike_time_to_esiea_min))}</span>
          <span class="fact">Voiture: {escape_html(format_duration_min(listing.drive_time_to_esiea_min))}</span>
        </div>
        """
    location = ", ".join(part for part in [listing.district, listing.city, listing.postal_code] if part)
    return f"""
      <article class="panel listing">
        <h3>{index}. {escape_html(listing.display_title)}</h3>
        <div class="price">{escape_html(format_price(listing.price))}</div>
        <div class="facts">
          <span class="fact">Source: {escape_html(listing.source_name)}</span>
          <span class="fact">Type: {escape_html(PROPERTY_TYPE_LABELS.get(listing.property_type, listing.property_type or "Logement"))}</span>
          <span class="fact">Surface: {escape_html(format_area(listing.surface_area))}</span>
          <span class="fact">Pieces: {listing.rooms if listing.rooms is not None else 'NR'}</span>
          <span class="fact">Meuble: {escape_html(format_bool_fr(listing.furnished))}</span>
          <span class="fact">Disponibilite: {escape_html(format_availability_date(listing.availability_date))}</span>
        </div>
        <p><strong>Localisation:</strong> {escape_html(location or "Non renseignee")}</p>
        <p><strong>Agence:</strong> {escape_html(listing.agency_name or "Non renseignee")} | <strong>Telephone:</strong> {escape_html(listing.phone or "Non renseigne")}</p>
        {commute_block}
        <p class="desc">{escape_html((listing.description or "Pas de description.").strip()[:700])}</p>
        <div class="links">
          <a class="link-button link-primary" href="{escape_html(listing.detail_page_url)}" target="_blank" rel="noreferrer">Voir l'annonce</a>
          <a class="link-button link-secondary" href="{escape_html(listing.detail_api_url)}" target="_blank" rel="noreferrer">Source detail</a>
        </div>
      </article>
    """


def render_home(
    city_query: str,
    postal_code: str,
    max_results: int,
    include_parking: bool,
    reference_name: str,
    reference_address: str,
    results_html: str = "",
    notice: str = "",
) -> bytes:
    notice_block = f'<div class="notice">{escape_html(notice)}</div>' if notice else ""
    content = f"""
      <section class="hero">
        <div class="panel intro">
          <span class="eyebrow">Recherche logement</span>
          <h1>Trouver un logement par ville, sans bricolage.</h1>
          <p class="lead">
            Cette interface permet de lancer une recherche en changeant la ville et le code postal.
            Pour Laval, on garde les sources supplementaires deja integrees. Pour les autres villes,
            la recherche passe d'abord par Bien'ici afin d'ouvrir l'usage a plus de monde.
          </p>
          <div class="meta">
            <span class="pill">Tri du moins cher au plus cher</span>
            <span class="pill">Interface locale sans dependance externe</span>
            <span class="pill">Branche dediee: lucifer_dev</span>
          </div>
          {notice_block}
        </div>
        <div class="panel form-card">
          <form method="get" action="/">
            <div class="grid">
              <label class="autocomplete">Ville
                <input name="city" value="{escape_html(city_query)}" placeholder="ex: Laval" autocomplete="off">
                <ul id="city-suggestions" class="suggestions"></ul>
              </label>
              <label>Code postal
                <input name="postal_code" value="{escape_html(postal_code)}" placeholder="ex: 53000">
              </label>
            </div>
            <div class="grid">
              <label>Nombre maximum de resultats
                <input type="number" min="1" max="100" name="max_results" value="{max_results}">
              </label>
              <label>Inclure les parkings
                <select name="include_parking">
                  <option value="false" {"selected" if not include_parking else ""}>Non</option>
                  <option value="true" {"selected" if include_parking else ""}>Oui</option>
                </select>
              </label>
            </div>
            <div class="grid">
              <label>Nom du point de reference
                <input name="reference_name" value="{escape_html(reference_name)}" placeholder="ex: Travail, Maison, Gare">
              </label>
              <label>Adresse ou lieu a proximite
                <input name="reference_address" value="{escape_html(reference_address)}" placeholder="ex: Gare de Rennes, 19 rue de Paris Rennes">
              </label>
            </div>
            <button type="submit">Lancer la recherche</button>
          </form>
        </div>
      </section>
      {results_html}
    """
    return html_page(content)


class HousingHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = parse.urlparse(self.path)
        if parsed.path == "/api/city-suggestions":
            self.handle_city_suggestions(parsed.query)
            return
        params = parse.parse_qs(parsed.query)
        city_query = params.get("city", [DEFAULT_CITY_QUERY])[0].strip() or DEFAULT_CITY_QUERY
        postal_code = params.get("postal_code", [DEFAULT_CITY_POSTAL_CODE])[0].strip() or DEFAULT_CITY_POSTAL_CODE
        max_results_raw = params.get("max_results", [str(DEFAULT_MAX_RESULTS)])[0].strip() or str(DEFAULT_MAX_RESULTS)
        include_parking = params.get("include_parking", ["false"])[0].lower() in {"1", "true", "yes", "oui"}
        reference_name = params.get("reference_name", [""])[0].strip()
        reference_address = params.get("reference_address", [""])[0].strip()

        try:
            max_results = max(1, min(100, int(max_results_raw)))
        except ValueError:
            max_results = DEFAULT_MAX_RESULTS

        if parsed.path != "/":
            self.send_error(HTTPStatus.NOT_FOUND, "Page introuvable")
            return

        if not params:
            self._send_ok(
                render_home(
                    city_query=city_query,
                    postal_code=postal_code,
                    max_results=max_results,
                    include_parking=include_parking,
                    reference_name=reference_name,
                    reference_address=reference_address,
                )
            )
            return

        try:
            _, search_label, listings, reference_point = search_listings(
                city_query=city_query,
                postal_code=postal_code,
                include_parking=include_parking,
                max_results=max_results,
                reference_name=reference_name or None,
                reference_address=reference_address or None,
            )
            reference_label = reference_point.name if reference_point is not None else None
            cards = "".join(
                render_listing_card(index, listing, reference_label=reference_label)
                for index, listing in enumerate(listings, start=1)
            )
            results_html = f"""
              <section class="results">
                <div class="meta">
                  <span class="pill">{escape_html(search_label)}</span>
                  <span class="pill">{len(listings)} offre(s)</span>
                  <span class="pill">Sources: {escape_html(build_source_summary(listings) or 'Aucune')}</span>
                  <span class="pill">Genere a {escape_html(datetime.now().strftime('%Y-%m-%d %H:%M'))}</span>
                  {"<span class=\"pill\">Proche de: " + escape_html(reference_label) + "</span>" if reference_label else ""}
                </div>
                {cards or '<div class="panel listing"><p>Aucune annonce trouvee pour cette recherche.</p></div>'}
              </section>
            """
            notice = ""
            if search_label != build_search_label(DEFAULT_CITY_QUERY, DEFAULT_CITY_POSTAL_CODE):
                notice = (
                    "Pour les villes autres que Laval, la recherche multi-source n'est pas encore generalisee. "
                    "Le moteur priorise Bien'ici pour garder une recherche fiable."
                )
            self._send_ok(
                render_home(
                    city_query=city_query,
                    postal_code=postal_code,
                    max_results=max_results,
                    include_parking=include_parking,
                    reference_name=reference_name,
                    reference_address=reference_address,
                    results_html=results_html,
                    notice=notice,
                )
            )
        except Exception as exc:
            self._send_ok(
                render_home(
                    city_query=city_query,
                    postal_code=postal_code,
                    max_results=max_results,
                    include_parking=include_parking,
                    reference_name=reference_name,
                    reference_address=reference_address,
                    notice=f"Erreur de recherche: {exc}",
                )
            )

    def log_message(self, format: str, *args) -> None:
        return

    def handle_city_suggestions(self, query_string: str) -> None:
        params = parse.parse_qs(query_string)
        query = params.get("q", [""])[0]
        try:
            payload = suggest_cities(query)
        except Exception:
            payload = []
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_ok(self, body: bytes) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    env_path = Path(os.environ.get("LOGEMENT_ENV_FILE", str(DEFAULT_ENV_PATH)))
    if env_path.exists():
        env_values = load_env_file(env_path)
        for key, value in env_values.items():
            os.environ.setdefault(key, value)
    host = os.environ.get("LOGEMENT_WEB_HOST", APP_HOST)
    port = int(os.environ.get("LOGEMENT_WEB_PORT", str(APP_PORT)))
    try:
        server = ThreadingHTTPServer((host, port), HousingHandler)
    except OSError as exc:
        if exc.errno == errno.EADDRINUSE:
            print(
                f"Port deja utilise: {host}:{port}. "
                f"Lance par exemple `LOGEMENT_WEB_PORT=8081 python3 web_app.py` "
                f"ou ferme le process qui ecoute deja sur ce port.",
                file=sys.stderr,
            )
            return 1
        raise
    print(f"Interface disponible sur http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
