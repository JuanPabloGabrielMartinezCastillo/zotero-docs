#!/usr/bin/env python3
"""Search and export scientific references relevant to tomato rootstock stress."""

from __future__ import annotations

import csv
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests

OUTPUT_DIR = Path(__file__).resolve().parent / "output"
USER_AGENT = "zotero-literature-search/1.0 (+https://github.com/JuanPabloGabrielMartinezCastillo/zotero-docs)"


def safe_get(url: str, params: Optional[Dict[str, Any]] = None, timeout: int = 30) -> requests.Response:
    response = requests.get(
        url,
        params=params,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response


def slugify(value: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return value or "item"


def build_queries(stress_label: str) -> List[str]:
    base = "tomato rootstocks"
    if stress_label == "salinity":
        return [
            f"{base} salinity",
            f"{base} sodium chloride stress",
            f"{base} NaCl tolerance",
            f"{base} soil salinity rootstock",
        ]
    if stress_label == "drought":
        return [
            f"{base} drought",
            f"{base} water deficit",
            f"{base} osmotic stress",
            f"{base} deficit irrigation rootstock",
        ]
    if stress_label == "heat":
        return [
            f"{base} heat stress",
            f"{base} high temperature",
            f"{base} thermal stress rootstock",
            f"{base} tomato rootstock heat tolerance",
        ]
    if stress_label == "cold":
        return [
            f"{base} cold stress",
            f"{base} chilling tolerance",
            f"{base} low temperature rootstock",
            f"{base} frost tolerance tomato rootstock",
        ]
    if stress_label == "disease":
        return [
            f"{base} disease resistance",
            f"{base} fusarium rootstock",
            f"{base} verticillium rootstock",
            f"{base} bacterial wilt rootstock",
            f"{base} tomato rootstock pathogen resistance",
        ]
    return [
        f"{base} abiotic stress",
        f"{base} stress tolerance",
        f"{base} tomato rootstock physiology",
        f"{base} rootstock performance",
    ]


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(str(v) for v in value if v)
    if isinstance(value, dict):
        return " ".join(str(v) for v in value.values() if v)
    return str(value)


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", title or "").strip().lower()


def extract_year(record: Dict[str, Any]) -> Optional[int]:
    for key in ("year", "publication_year", "published-print", "published-online"):
        if key in record and record.get(key):
            if isinstance(record[key], dict):
                value = record[key].get("date-parts", [[None]])[0][0]
                if value:
                    return int(value)
            elif isinstance(record[key], int):
                return record[key]
            elif isinstance(record[key], str) and record[key].isdigit():
                return int(record[key])
    if "published" in record and isinstance(record["published"], dict):
        parts = record["published"].get("date-parts", [[None]])
        if parts and parts[0]:
            first = parts[0][0]
            if first:
                return int(first)
    return None


def build_record(title: str, authors: Iterable[str], year: Optional[int], journal: str, abstract: str, source: str, url: str) -> Dict[str, Any]:
    authors_list = [a.strip() for a in authors if a and a.strip()]
    return {
        "title": title.strip(),
        "authors": authors_list,
        "year": year,
        "journal": journal.strip(),
        "abstract": abstract.strip(),
        "source": source,
        "url": url,
        "relevance_score": 0.0,
        "stress_tags": [],
    }


def classify_record(record: Dict[str, Any], stress_label: str) -> Dict[str, Any]:
    text = " ".join(
        [
            record.get("title", ""),
            record.get("abstract", ""),
            record.get("journal", ""),
            " ".join(record.get("authors", [])),
        ]
    ).lower()
    if not text:
        return record

    stress_terms = {
        "salinity": ["salinity", "salt", "sodium", "nacl", "chloride", "osmotic stress"],
        "drought": ["drought", "water deficit", "water stress", "soil water", "dryness", "osmotic stress"],
        "heat": ["heat", "high temperature", "thermal", "warming", "heat stress"],
        "cold": ["cold", "chilling", "low temperature", "frost", "cold stress"],
        "disease": ["disease", "resistance", "pathogen", "fusarium", "verticillium", "bacterial wilt", "gray mold"],
    }

    tags = []
    for key, terms in stress_terms.items():
        if any(term in text for term in terms):
            tags.append(key)

    record["stress_tags"] = tags or [stress_label]
    score = 0.0
    for term in stress_terms.get(stress_label, [stress_label]):
        if term.lower() in text:
            score += 1.0
    if record.get("title"):
        score += 1.0
    if record.get("abstract"):
        score += 0.5
    record["relevance_score"] = round(score, 2)
    return record


def search_pubmed(query: str, max_results: int = 8) -> List[Dict[str, Any]]:
    try:
        search = safe_get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
            {
                "db": "pubmed",
                "term": query,
                "retmode": "json",
                "retmax": max_results,
                "sort": "relevance",
            },
        )
        data = search.json()
        ids = data.get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []

        summary = safe_get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi",
            {
                "db": "pubmed",
                "id": ",".join(ids),
                "retmode": "json",
            },
        )
        docs = summary.json().get("result", {}).get("uids", [])
        articles: List[Dict[str, Any]] = []
        for uid in docs:
            item = summary.json()["result"].get(uid, {})
            title = clean_text(item.get("title"))
            authors = []
            for author in item.get("authors", []):
                name = author.get("name")
                if name:
                    authors.append(name)
            year = item.get("pubdate", "")
            if year and len(year) >= 4 and year[:4].isdigit():
                year_value = int(year[:4])
            else:
                year_value = None
            journal = clean_text(item.get("fulljournalname") or item.get("source"))
            abstract = ""
            article_url = f"https://pubmed.ncbi.nlm.nih.gov/{uid}/"
            articles.append(
                build_record(
                    title=title,
                    authors=authors,
                    year=year_value,
                    journal=journal,
                    abstract=abstract,
                    source="PubMed",
                    url=article_url,
                )
            )
        return articles
    except Exception:
        return []


def search_crossref(query: str, rows: int = 8) -> List[Dict[str, Any]]:
    try:
        response = safe_get(
            "https://api.crossref.org/works",
            {
                "query.title": query,
                "rows": rows,
                "select": "title,author,issued,publisher,container-title,URL,abstract",
            },
        )
        items = response.json().get("message", {}).get("items", [])
        records: List[Dict[str, Any]] = []
        for item in items:
            title = clean_text(item.get("title", [""])[0])
            if not title:
                continue
            authors = []
            for author in item.get("author", []):
                if author.get("family"):
                    if author.get("given"):
                        authors.append(f"{author['given']} {author['family']}")
                    else:
                        authors.append(author["family"])
            issued = item.get("issued", {})
            year_value = extract_year(item)
            journal = clean_text(item.get("container-title", [""]))
            abstract = ""
            if isinstance(item.get("abstract"), str):
                abstract = item["abstract"]
            url = item.get("URL", "")
            records.append(
                build_record(
                    title=title,
                    authors=authors,
                    year=year_value,
                    journal=journal,
                    abstract=abstract,
                    source="Crossref",
                    url=url,
                )
            )
        return records
    except Exception:
        return []


def deduplicate(records: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = {}
    for record in records:
        title = normalize_title(record.get("title") or "")
        if not title:
            continue
        key = (title, record.get("year") or 0)
        if key not in seen:
            seen[key] = record
        else:
            current = seen[key]
            current["relevance_score"] = max(float(current.get("relevance_score", 0.0)), float(record.get("relevance_score", 0.0)))
            if not current.get("source"):
                current["source"] = record.get("source")
            if not current.get("url"):
                current["url"] = record.get("url")
            if not current.get("authors"):
                current["authors"] = record.get("authors")
    return sorted(seen.values(), key=lambda r: r.get("relevance_score", 0), reverse=True)


def export_csv_json(records: List[Dict[str, Any]], stress_label: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    csv_path = OUTPUT_DIR / f"tomato_rootstocks_{stress_label}_references.csv"
    json_path = OUTPUT_DIR / f"tomato_rootstocks_{stress_label}_references.json"

    fieldnames = ["title", "authors", "year", "journal", "source", "url", "relevance_score", "stress_tags"]
    with csv_path.open("w", newline="", encoding="utf-8") as fp:
        writer = csv.DictWriter(fp, fieldnames=fieldnames)
        writer.writeheader()
        for record in records:
            writer.writerow({
                "title": record.get("title", ""),
                "authors": "; ".join(record.get("authors", [])),
                "year": record.get("year"),
                "journal": record.get("journal", ""),
                "source": record.get("source", ""),
                "url": record.get("url", ""),
                "relevance_score": record.get("relevance_score", 0),
                "stress_tags": "; ".join(record.get("stress_tags", [])),
            })

    with json_path.open("w", encoding="utf-8") as fp:
        json.dump(records, fp, ensure_ascii=False, indent=2)


def export_ris(records: List[Dict[str, Any]], stress_label: str) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ris_path = OUTPUT_DIR / f"tomato_rootstocks_{stress_label}_zotero.ris"

    lines: List[str] = []
    for record in records:
        lines.append("TY  - JOUR")
        title = record.get("title", "")
        if title:
            lines.append(f"TI  - {title}")
        for author in record.get("authors", []):
            lines.append(f"AU  - {author}")
        if record.get("journal"):
            lines.append(f"JO  - {record.get('journal', '')}")
        if record.get("year"):
            lines.append(f"PY  - {record.get('year')}")
        if record.get("url"):
            lines.append(f"UR  - {record.get('url')}")
        if record.get("abstract"):
            lines.append(f"AB  - {record.get('abstract', '')}")
        lines.append("ER  - ")
        lines.append("")

    ris_path.write_text("\n".join(lines), encoding="utf-8")


def run_search_for_stress(stress_label: str) -> List[Dict[str, Any]]:
    all_records: List[Dict[str, Any]] = []
    print(f"\nBuscando literatura para: {stress_label}")
    for query in build_queries(stress_label):
        print(f"  - {query}")
        pubmed_records = search_pubmed(query, max_results=8)
        crossref_records = search_crossref(query, rows=8)
        for record in pubmed_records + crossref_records:
            if not record.get("title"):
                continue
            record = classify_record(record, stress_label)
            all_records.append(record)

    unique = deduplicate(all_records)
    unique = sorted(unique, key=lambda r: r.get("relevance_score", 0), reverse=True)

    print(f"\nTotal de referencias únicas: {len(unique)}")
    for i, record in enumerate(unique[:10], start=1):
        print(f"{i}. {record.get('title', '')} | score={record.get('relevance_score', '')} | stress={record.get('stress_tags', [])}")

    export_csv_json(unique, stress_label)
    export_ris(unique, stress_label)

    print("\nIMPORTANTE: para Zotero importa el archivo que termina en '_zotero.ris'")
    print(f"Archivo recomendado: {OUTPUT_DIR / f'tomato_rootstocks_{stress_label}_zotero.ris'}")
    return unique


def show_menu() -> str:
    print("\n=== Búsqueda de literatura para tomate y portainjertos ===")
    print("1. Salinity")
    print("2. Drought")
    print("3. Heat")
    print("4. Cold")
    print("5. Disease")
    print("6. General")
    print("7. Salir")
    return input("Selecciona una opción: ").strip()


def main() -> None:
    while True:
        try:
            choice = show_menu()
            if choice == "7":
                print("Saliendo...")
                break

            stress_label = {
                "1": "salinity",
                "2": "drought",
                "3": "heat",
                "4": "cold",
                "5": "disease",
                "6": "general",
            }.get(choice)

            if stress_label is None:
                print("Opción no válida. Intenta de nuevo.")
                continue

            run_search_for_stress(stress_label)
            print("\nPresiona Enter para continuar...")
            input()

        except KeyboardInterrupt:
            print("\nPrograma interrumpido por el usuario.")
            break
        except SystemExit:
            break
        except Exception as exc:  # pragma: no cover - user-friendly top-level guard
            print(f"Error general: {exc}")


if __name__ == "__main__":
    main()
