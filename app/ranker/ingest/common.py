"""Shared helpers for the ingest steps."""
import os
import re

import httpx


def normalize_county(name: str) -> str:
    """Lowercase county name with suffixes and punctuation removed, so sources can be joined.

    Example: "St. Louis County" and "Saint Louis" both become "st louis".
    """
    text = (name or "").lower().strip()
    text = re.sub(r"\b(county|parish|borough|census area|municipality)\b", " ", text)
    text = text.replace("saint ", "st ").replace("sainte ", "ste ")
    text = re.sub(r"[^a-z0-9 ]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def download_first_available(urls, destination: str) -> str:
    """Download the first URL that works to `destination`, reusing a cached copy if present."""
    if os.path.exists(destination) and os.path.getsize(destination) > 0:
        print(f"Using cached file {destination}")
        return destination
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    errors = []
    for url in urls:
        try:
            print(f"Downloading {url}")
            with httpx.stream("GET", url, follow_redirects=True, timeout=120) as response:
                response.raise_for_status()
                with open(destination, "wb") as handle:
                    for chunk in response.iter_bytes():
                        handle.write(chunk)
            return destination
        except httpx.HTTPError as error:
            errors.append(f"{url}: {error}")
    raise RuntimeError(
        "Could not download the file. Download it by hand, save it as "
        f"{destination}, and run the step again.\n" + "\n".join(errors)
    )
