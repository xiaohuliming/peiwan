#!/usr/bin/env python3
"""Fetch a compact VALORANT reference dataset from Valorant Wiki.

The script uses Fandom's MediaWiki API and extracts structured infobox facts
instead of mirroring whole article bodies. That keeps the output useful for LLM
reference prompts while preserving source attribution and links back to the wiki.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup, Tag


API_URL = "https://valorant.fandom.com/api.php"
WIKI_BASE = "https://valorant.fandom.com/wiki/"
DEFAULT_OUTPUT_JSON = Path("data/valorant_reference.json")
DEFAULT_OUTPUT_MD = Path("data/valorant_reference.md")
REQUEST_DELAY_SECONDS = 0.25

DATASETS = {
    "agents": {
        "category": "Agents",
        "exclude": {"Agents"},
        "fields": [
            "realname",
            "pronouns",
            "origin",
            "race",
            "affiliations",
            "number",
            "role",
            "passive",
            "basic",
            "signature",
            "ultimate",
        ],
    },
    "weapons": {
        "category": "Weapons",
        "exclude": {"Weapons", "Weapon Skins"},
        "fields": [
            "type",
            "credits",
            "penetration",
            "creator",
            "mode",
            "rate",
            "run",
            "equip",
            "reload",
            "magazine",
            "reserve",
            "function",
            "zoom",
            "altrate",
            "move",
            "notes",
        ],
    },
    "maps": {
        "category": "Maps",
        "exclude": {"Maps"},
        "fields": [
            "location",
            "coordinates",
            "sites",
            "elements",
            "added",
            "rotation",
            "codename",
            "pages",
        ],
    },
}


@dataclass(frozen=True)
class WikiPage:
    title: str
    page_id: int | None
    html: str


class ValorantWikiClient:
    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "CodexValorantReferenceFetcher/1.0 "
                    "(https://openai.com; educational reference extraction)"
                )
            }
        )

    def get(self, **params: Any) -> dict[str, Any]:
        response = self.session.get(API_URL, params=params, timeout=30)
        response.raise_for_status()
        return response.json()

    def category_titles(self, category: str) -> list[str]:
        titles: list[str] = []
        continuation: dict[str, str] = {}

        while True:
            data = self.get(
                action="query",
                format="json",
                list="categorymembers",
                cmtitle=f"Category:{category}",
                cmlimit="max",
                cmnamespace=0,
                **continuation,
            )
            titles.extend(member["title"] for member in data["query"]["categorymembers"])
            if "continue" not in data:
                break
            continuation = data["continue"]
            time.sleep(REQUEST_DELAY_SECONDS)

        return sorted(set(titles), key=str.casefold)

    def parse_page(self, title: str) -> WikiPage:
        data = self.get(
            action="parse",
            format="json",
            page=title,
            prop="text",
            redirects=1,
            disablelimitreport=1,
        )
        parsed = data["parse"]
        return WikiPage(
            title=parsed["title"],
            page_id=parsed.get("pageid"),
            html=parsed["text"]["*"],
        )


def compact_spaces(text: str) -> str:
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip(" \n")


def clean_text(node: Tag | None, separator: str = " | ") -> str:
    if node is None:
        return ""

    clone = BeautifulSoup(str(node), "html.parser")
    for removable in clone.select("script, style, sup.reference, .mw-editsection, img, audio"):
        removable.decompose()

    for br in clone.find_all("br"):
        br.replace_with("\n")

    text = clone.get_text(separator=separator)
    lines = [compact_spaces(line) for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def field_key(raw: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", raw.lower()).strip("_")


def nearest_group_name(node: Tag, aside: Tag | None) -> str | None:
    for parent in node.parents:
        if parent is aside:
            break
        if not isinstance(parent, Tag):
            continue
        classes = parent.get("class", [])
        if "pi-group" not in classes:
            continue
        header = parent.find("h2", class_="pi-header", recursive=False)
        if header:
            return clean_text(header)
    return None


def unique_values(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        normalized = compact_spaces(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def split_multi_value(value: str) -> list[str]:
    parts: list[str] = []
    for line in value.splitlines():
        line = compact_spaces(line)
        if not line:
            continue
        if " | " in line:
            parts.extend(part.strip() for part in line.split(" | "))
        else:
            parts.append(line)
    return unique_values(parts)


def source_url(title: str) -> str:
    return WIKI_BASE + quote(title.replace(" ", "_"), safe="/_")


def parse_images(aside: Tag | None) -> list[dict[str, str]]:
    if aside is None:
        return []

    images: list[dict[str, str]] = []
    seen: set[str] = set()
    for img in aside.find_all("img"):
        src = img.get("data-src") or img.get("src") or ""
        if not src or src.startswith("data:image"):
            continue
        if src in seen:
            continue
        seen.add(src)
        images.append(
            {
                "alt": compact_spaces(img.get("alt") or ""),
                "name": compact_spaces(img.get("data-image-name") or ""),
                "url": src,
            }
        )
    return images


def parse_infobox(soup: BeautifulSoup) -> tuple[list[dict[str, str]], dict[str, Any], list[dict[str, str]]]:
    aside = soup.find("aside", class_="portable-infobox")
    if aside is None:
        return [], {}, []

    fields: list[dict[str, str]] = []
    keyed: dict[str, Any] = {}

    for item in aside.select(".pi-data[data-source], .pi-horizontal-group-item[data-source]"):
        if not isinstance(item, Tag):
            continue
        source = compact_spaces(item.get("data-source") or "")
        label_node = item.find(["h3", "h2"], class_=re.compile(r"pi-.*label|pi-header"))
        value_node = item.find(class_="pi-data-value")
        label = clean_text(label_node) if label_node else source
        value = clean_text(value_node or item)
        if not value:
            continue

        key = field_key(source or label)
        field = {
            "group": nearest_group_name(item, aside) or "",
            "source": source,
            "label": label,
            "value": value,
        }
        fields.append(field)

        if key:
            keyed[key] = split_multi_value(value)

    for smart_group in aside.select(".pi-smart-group"):
        if not isinstance(smart_group, Tag):
            continue
        label = clean_text(smart_group.find(class_="pi-smart-data-label"))
        value = clean_text(smart_group.find(class_="pi-smart-data-value"))
        if not label or not value:
            continue
        key = field_key(label)
        fields.append(
            {
                "group": nearest_group_name(smart_group, aside) or "",
                "source": key,
                "label": label,
                "value": value,
            }
        )
        keyed[key] = split_multi_value(value)

    return fields, keyed, parse_images(aside)


def parse_display_title(soup: BeautifulSoup, fallback: str) -> str:
    title = soup.select_one('aside.portable-infobox [data-source="title"]')
    if title:
        text = clean_text(title, separator=" ")
        if text:
            return text
    heading = soup.find("h1")
    if heading:
        text = clean_text(heading, separator=" ")
        if text:
            return text
    return fallback


def parse_lead(soup: BeautifulSoup, display_title: str) -> str:
    content = soup.select_one(".mw-parser-output")
    if not content:
        return ""

    for paragraph in content.find_all("p", recursive=False):
        text = clean_text(paragraph, separator=" ")
        if not text:
            continue
        if len(text) < 20:
            continue
        if display_title.lower() not in text.lower() and "VALORANT" not in text:
            continue
        return text
    return ""


def parse_headings(soup: BeautifulSoup) -> list[str]:
    headings: list[str] = []
    for heading in soup.select(".mw-parser-output h2 .mw-headline"):
        text = clean_text(heading, separator=" ")
        if text and text not in {"Navigation"}:
            headings.append(text)
    return unique_values(headings)


def selected_facts(keyed: dict[str, Any], field_names: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in field_names:
        if name in keyed:
            result[name] = keyed[name]
    return result


def parse_reference_page(page: WikiPage, dataset_name: str, field_names: list[str]) -> dict[str, Any]:
    soup = BeautifulSoup(page.html, "html.parser")
    display_title = parse_display_title(soup, page.title)
    fields, keyed, images = parse_infobox(soup)

    return {
        "title": display_title,
        "page_title": page.title,
        "page_id": page.page_id,
        "dataset": dataset_name,
        "source_url": source_url(page.title),
        "lead": parse_lead(soup, display_title),
        "facts": selected_facts(keyed, field_names),
        "all_infobox_fields": fields,
        "section_headings": parse_headings(soup),
        "images": images,
    }


def fetch_dataset(client: ValorantWikiClient) -> dict[str, Any]:
    output: dict[str, Any] = {
        "metadata": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "Valorant Wiki on Fandom",
            "source_home": "https://valorant.fandom.com/wiki/VALORANT_Wiki",
            "api": API_URL,
            "license_note": (
                "This dataset is a compact factual index with source URLs. "
                "Check the linked wiki pages and Fandom/Riot terms before reuse."
            ),
        }
    }

    for dataset_name, config in DATASETS.items():
        category = config["category"]
        titles = [
            title
            for title in client.category_titles(category)
            if title not in config["exclude"]
        ]

        pages: list[dict[str, Any]] = []
        for index, title in enumerate(titles, 1):
            print(f"[{dataset_name} {index:02d}/{len(titles):02d}] {title}")
            page = client.parse_page(title)
            pages.append(parse_reference_page(page, dataset_name, config["fields"]))
            time.sleep(REQUEST_DELAY_SECONDS)

        output[dataset_name] = sorted(pages, key=lambda item: item["title"].casefold())

    return output


def first_value(facts: dict[str, Any], key: str) -> str:
    value = facts.get(key)
    if isinstance(value, list):
        return ", ".join(value)
    return str(value or "")


def render_markdown(data: dict[str, Any]) -> str:
    metadata = data["metadata"]
    lines = [
        "# VALORANT Reference Snapshot",
        "",
        f"- Generated: `{metadata['generated_at']}`",
        f"- Source: [{metadata['source_home']}]({metadata['source_home']})",
        f"- API: `{metadata['api']}`",
        "- Scope: Agents, weapons, and maps. Facts are extracted from infoboxes and short lead text; use source links for full context.",
        "",
        "## Agents",
    ]

    for agent in data.get("agents", []):
        facts = agent["facts"]
        ability_bits = [
            f"Passive: {first_value(facts, 'passive')}",
            f"Basic: {first_value(facts, 'basic')}",
            f"Signature: {first_value(facts, 'signature')}",
            f"Ultimate: {first_value(facts, 'ultimate')}",
        ]
        lines.extend(
            [
                f"### {agent['title']}",
                f"- Source: [{agent['page_title']}]({agent['source_url']})",
                f"- Role: {first_value(facts, 'role')}",
                f"- Real name: {first_value(facts, 'realname')}",
                f"- Origin: {first_value(facts, 'origin')}",
                f"- Race: {first_value(facts, 'race')}",
                f"- Affiliations: {first_value(facts, 'affiliations')}",
                f"- Abilities: {'; '.join(bit for bit in ability_bits if not bit.endswith(': '))}",
            ]
        )
        if agent.get("lead"):
            lines.append(f"- Lead: {agent['lead']}")
        lines.append("")

    lines.append("## Weapons")
    for weapon in data.get("weapons", []):
        facts = weapon["facts"]
        lines.extend(
            [
                f"### {weapon['title']}",
                f"- Source: [{weapon['page_title']}]({weapon['source_url']})",
                f"- Type: {first_value(facts, 'type')}",
                f"- Credits: {first_value(facts, 'credits')}",
                f"- Wall penetration: {first_value(facts, 'penetration')}",
                f"- Primary fire: {first_value(facts, 'mode')} / {first_value(facts, 'rate')}",
                f"- Magazine: {first_value(facts, 'magazine')} / Reserve: {first_value(facts, 'reserve')}",
            ]
        )
        if "0_50m" in facts:
            lines.append(f"- Damage 0-50m: {first_value(facts, '0_50m')}")
        if weapon.get("lead"):
            lines.append(f"- Lead: {weapon['lead']}")
        lines.append("")

    lines.append("## Maps")
    for game_map in data.get("maps", []):
        facts = game_map["facts"]
        lines.extend(
            [
                f"### {game_map['title']}",
                f"- Source: [{game_map['page_title']}]({game_map['source_url']})",
                f"- Location: {first_value(facts, 'location')}",
                f"- Coordinates: {first_value(facts, 'coordinates')}",
                f"- Spike sites: {first_value(facts, 'sites')}",
                f"- Map features: {first_value(facts, 'elements')}",
                f"- Rotation: {first_value(facts, 'rotation')}",
                f"- Codename: {first_value(facts, 'codename')}",
            ]
        )
        if game_map.get("lead"):
            lines.append(f"- Lead: {game_map['lead']}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_outputs(data: dict[str, Any], json_path: Path, md_path: Path) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(data), encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch compact VALORANT agent, weapon, and map reference data from Fandom."
    )
    parser.add_argument("--json", type=Path, default=DEFAULT_OUTPUT_JSON, help="JSON output path.")
    parser.add_argument("--md", type=Path, default=DEFAULT_OUTPUT_MD, help="Markdown output path.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    client = ValorantWikiClient()
    data = fetch_dataset(client)
    write_outputs(data, args.json, args.md)
    print(f"Wrote {args.json}")
    print(f"Wrote {args.md}")


if __name__ == "__main__":
    main()
