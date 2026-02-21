import argparse
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit

from dotenv import load_dotenv
from langchain_nvidia_ai_endpoints import NVIDIAEmbeddings
from qdrant_client import QdrantClient, models


@dataclass(frozen=True)
class CityConfig:
    key: str
    display: str
    center_lat: float
    center_lon: float
    neighborhoods: list[str]
    hotel_themes: list[str]
    restaurant_themes: list[str]
    attraction_themes: list[str]


CITY_CONFIGS = {
    "nyc": CityConfig(
        key="nyc",
        display="New York City",
        center_lat=40.7580,
        center_lon=-73.9855,
        neighborhoods=[
            "Midtown",
            "SoHo",
            "Tribeca",
            "Chelsea",
            "Upper East Side",
            "Upper West Side",
            "Greenwich Village",
            "Williamsburg",
            "DUMBO",
            "Financial District",
        ],
        hotel_themes=[
            "Grand",
            "Harbor",
            "Skyline",
            "Metropolitan",
            "Gallery",
            "Boutique",
            "Plaza",
            "Landmark",
            "Beacon",
            "Parkside",
        ],
        restaurant_themes=[
            "Bistro",
            "Kitchen",
            "Table",
            "Osteria",
            "Grill",
            "Brasserie",
            "Atelier",
            "Canteen",
            "Taverna",
            "Supper Club",
        ],
        attraction_themes=[
            "Museum",
            "Gallery",
            "Garden",
            "Observation Deck",
            "Cultural Center",
            "Waterfront Walk",
            "Historic Hall",
            "Art House",
            "Park Experience",
            "Science Studio",
        ],
    ),
    "paris": CityConfig(
        key="paris",
        display="Paris",
        center_lat=48.8566,
        center_lon=2.3522,
        neighborhoods=[
            "Le Marais",
            "Saint-Germain",
            "Montmartre",
            "Latin Quarter",
            "Bastille",
            "Canal Saint-Martin",
            "Champs-Elysees",
            "Belleville",
            "Batignolles",
            "Opera",
        ],
        hotel_themes=[
            "Maison",
            "Palais",
            "Rive",
            "Lumiere",
            "Jardin",
            "Rooftop",
            "Boutique",
            "Courtyard",
            "Heritage",
            "Belle Epoque",
        ],
        restaurant_themes=[
            "Bistrot",
            "Brasserie",
            "Cuisine",
            "Atelier",
            "Comptoir",
            "Table",
            "Salon",
            "Rotisserie",
            "Epicerie",
            "Cafe",
        ],
        attraction_themes=[
            "Museum",
            "Gallery",
            "Garden",
            "Viewpoint",
            "Passage",
            "Historic Site",
            "Cultural Space",
            "Art Pavilion",
            "River Walk",
            "Design Center",
        ],
    ),
}


DESTINATION_ALIASES = {
    "nyc": "New York City",
    "new york": "New York City",
    "new york city": "New York City",
    "paris": "Paris",
}


def slugify(value: str) -> str:
    chars = []
    for ch in value.lower():
        if ch.isalnum():
            chars.append(ch)
        elif ch in {" ", "-", "_"}:
            chars.append("-")
    slug = "".join(chars)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")


def canonicalize_destination(value: str) -> str:
    normalized = " ".join(value.strip().lower().split())
    return DESTINATION_ALIASES.get(normalized, value.strip())


def normalize_link(value: str) -> str:
    if not value:
        return ""

    url = value.strip()
    split = urlsplit(url)
    scheme = (split.scheme or "https").lower()
    netloc = split.netloc.lower()
    path = split.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, "", ""))


def dedupe_key(payload: dict) -> str:
    normalized_link = normalize_link(str(payload.get("link", "")))
    if normalized_link:
        return f"link::{normalized_link}"

    destination = canonicalize_destination(str(payload.get("destination", "")))
    item_type = str(payload.get("type", "")).strip().lower()
    slug = slugify(str(payload.get("slug", "")))
    return f"fallback::{destination.lower()}::{item_type}::{slug}"


def canonicalize_payload(payload: dict) -> dict:
    p = dict(payload)
    p["destination"] = canonicalize_destination(str(p.get("destination", "")))
    p["type"] = str(p.get("type", "")).strip().lower()
    p["slug"] = slugify(str(p.get("slug", "")))
    p["link"] = normalize_link(str(p.get("link", "")))

    keywords = p.get("keywords", [])
    normalized_keywords = sorted({slugify(str(k)) for k in keywords if str(k).strip()})
    p["keywords"] = normalized_keywords
    return p


def dedupe_payloads(payloads: list[dict]) -> tuple[list[dict], int]:
    unique: dict[str, dict] = {}
    duplicate_count = 0

    for payload in payloads:
        canonical = canonicalize_payload(payload)
        key = dedupe_key(canonical)

        if key not in unique:
            unique[key] = canonical
            continue

        duplicate_count += 1
        existing = unique[key]
        existing_keywords = set(existing.get("keywords", []))
        incoming_keywords = set(canonical.get("keywords", []))
        existing["keywords"] = sorted(existing_keywords | incoming_keywords)

        if int(canonical.get("popularity_score", 0)) > int(
            existing.get("popularity_score", 0)
        ):
            existing["popularity_score"] = canonical["popularity_score"]

    return list(unique.values()), duplicate_count


def stable_geo(city: CityConfig, idx: int) -> dict:
    lat_offset = ((idx % 10) - 5) * 0.0037
    lon_offset = ((idx // 10) - 5) * 0.0041
    return {
        "lat": round(city.center_lat + lat_offset, 6),
        "lon": round(city.center_lon + lon_offset, 6),
    }


def make_items(city: CityConfig, item_type: str, count: int) -> list[dict]:
    if item_type == "hotel":
        themes = city.hotel_themes
        desc_template = (
            "{name} is a {style} stay in {area}, ideal for travelers wanting "
            "walkable access to highlights in {city}."
        )
    elif item_type == "restaurant":
        themes = city.restaurant_themes
        desc_template = (
            "{name} is a {style} spot in {area} known for local flavor, "
            "date-night energy, and easy access from central {city}."
        )
    else:
        themes = city.attraction_themes
        desc_template = (
            "{name} in {area} is a {style} experience that consistently ranks "
            "among top activities in {city}."
        )

    items = []
    for i in range(count):
        area = city.neighborhoods[i % len(city.neighborhoods)]
        style = themes[i % len(themes)]
        rank = i + 1
        name = f"{area} {style} {item_type.title()} {rank}"
        slug = slugify(f"{city.key}-{item_type}-{area}-{style}-{rank}")

        if item_type == "attraction":
            price_level = (i % 3) + 1
        else:
            price_level = (i % 4) + 1

        payload = {
            "destination": canonicalize_destination(city.display),
            "slug": slug,
            "type": item_type,
            "link": f"https://travel.seed.local/{city.key}/{item_type}/{slug}",
            "keywords": [
                city.key,
                item_type,
                slugify(area),
                slugify(style),
            ],
            "popularity_score": 100 - i,
            "price_level": price_level,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "geo": stable_geo(city, i),
            "name": name,
            "neighborhood": area,
            "description": desc_template.format(
                name=name,
                style=style.lower(),
                area=area,
                city=city.display,
            ),
            "source": "seed-script",
        }
        items.append(payload)

    return items


def build_seed(city: CityConfig) -> list[dict]:
    items = []
    items.extend(make_items(city, "hotel", 20))
    items.extend(make_items(city, "restaurant", 30))
    items.extend(make_items(city, "attraction", 30))
    return items


def embed_text(payload: dict) -> str:
    keywords = ", ".join(payload["keywords"])
    return (
        f"Name: {payload['name']}\n"
        f"City: {payload['destination']}\n"
        f"Type: {payload['type']}\n"
        f"Neighborhood: {payload['neighborhood']}\n"
        f"Description: {payload['description']}\n"
        f"Keywords: {keywords}"
    )


def point_id(payload: dict) -> str:
    seed = dedupe_key(payload)
    return str(uuid.uuid5(uuid.NAMESPACE_URL, seed))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed Qdrant travel_items with NYC and Paris starter data"
    )
    parser.add_argument(
        "--cities",
        nargs="+",
        default=["nyc", "paris"],
        help="Cities to seed: nyc paris",
    )
    parser.add_argument(
        "--collection",
        default="travel_items",
        help="Qdrant collection name",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Upsert batch size",
    )
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()

    qdrant_url = os.getenv("QDRANT_URL")
    qdrant_api_key = os.getenv("QDRANT_API_KEY")
    nvidia_api_key = os.getenv("NVIDIA_API_KEY")
    nvidia_model = os.getenv(
        "NVIDIA_EMBED_MODEL", "nvidia/llama-nemotron-embed-vl-1b-v2"
    )

    if not qdrant_url or not qdrant_api_key:
        raise RuntimeError("Missing QDRANT_URL or QDRANT_API_KEY in environment/.env")
    if not nvidia_api_key:
        raise RuntimeError("Missing NVIDIA_API_KEY in environment/.env")

    city_keys = [c.lower() for c in args.cities]
    invalid = [c for c in city_keys if c not in CITY_CONFIGS]
    if invalid:
        raise RuntimeError(f"Unsupported city keys: {', '.join(invalid)}")

    all_payloads = []
    for city_key in city_keys:
        all_payloads.extend(build_seed(CITY_CONFIGS[city_key]))

    canonical_payloads, dropped = dedupe_payloads(all_payloads)
    print(
        f"Canonicalized {len(all_payloads)} items; removed {dropped} duplicates; "
        f"{len(canonical_payloads)} items remain."
    )

    print(f"Building embeddings for {len(canonical_payloads)} items...")
    embedder = NVIDIAEmbeddings(
        model=nvidia_model,
        api_key=nvidia_api_key,
        truncate="NONE",
    )

    docs = [embed_text(p) for p in canonical_payloads]
    vectors = embedder.embed_documents(docs)
    vector_dim = len(vectors[0]) if vectors else 0

    qdrant = QdrantClient(url=qdrant_url, api_key=qdrant_api_key)
    if not qdrant.collection_exists(args.collection):
        raise RuntimeError(
            f"Collection '{args.collection}' does not exist. Run qdrant_setup.sh first."
        )

    points = [
        models.PointStruct(id=point_id(payload), vector=vector, payload=payload)
        for payload, vector in zip(canonical_payloads, vectors)
    ]

    print(
        f"Upserting {len(points)} points into '{args.collection}' "
        f"(vector_dim={vector_dim})..."
    )
    for i in range(0, len(points), args.batch_size):
        batch = points[i : i + args.batch_size]
        qdrant.upsert(collection_name=args.collection, points=batch, wait=True)
        print(f"  - Upserted {i + len(batch)}/{len(points)}")

    print("Seed complete.")


if __name__ == "__main__":
    main()
