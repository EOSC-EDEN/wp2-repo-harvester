#!/usr/bin/env python3
"""Detect an identifier with idutils and return an actionable IRI."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from typing import Iterable, Optional
from urllib.parse import quote

import idutils


@dataclass(frozen=True)
class IdentifierResolution:
    original: str
    scheme: str
    normalized: str
    iri: str


SCHEME_PRIORITY = (
    "doi",
    "handle",
    "orcid",
    "ror",
    "ark",
    "pmid",
    "pmcid",
    "arxiv",
    "isbn",
    "issn",
    "url",
    "urn",
    "re3data",
)


def resolve_identifier(value: str, preferred_scheme: str | None = None) -> IdentifierResolution:
    """Return the detected identifier scheme and an actionable IRI.
    Raises ValueError when idutils cannot detect a supported identifier scheme.
    """

    identifier = _clean_identifier(value)
    actionable_pid_url = get_actionable_pid_url(identifier)
    if actionable_pid_url:
        normalized = _normalize_identifier(identifier, "url")
        return IdentifierResolution(
            original=value,
            scheme="url",
            normalized=normalized,
            iri=actionable_pid_url,
        )
    schemes = _detect_schemes(identifier)

    if preferred_scheme:
        preferred_scheme = preferred_scheme.lower()
        if preferred_scheme not in schemes:
            raise ValueError(
                f"{identifier!r} was detected as {schemes}, not {preferred_scheme!r}."
            )
        scheme = preferred_scheme
    else:
        scheme = _best_scheme(schemes)

    normalized = _normalize_identifier(identifier, scheme)
    iri = _to_actionable_iri(normalized, scheme)
    return IdentifierResolution(
        original=value,
        scheme=scheme,
        normalized=normalized,
        iri=iri,
    )


def _clean_identifier(value: str) -> str:
    return value.strip().strip("<>").strip().strip('"').strip("'")


def _detect_schemes(identifier: str) -> list[str]:
    schemes = [scheme.lower() for scheme in idutils.detect_identifier_schemes(identifier)]
    if not schemes:
        re3data_scheme = detect_re3data_identifier(identifier)
        if re3data_scheme:
            schemes.append(re3data_scheme)
    supported_schemes = [scheme for scheme in schemes if scheme in SCHEME_PRIORITY]
    if not supported_schemes:
        raise ValueError(f"Could not detect a supported identifier scheme for {identifier!r}.")
    return supported_schemes

def detect_re3data_identifier(identifier: str) -> Optional[str]:
    """Return 're3data' for a repository URL, prefixed ID, or bare r3d ID."""
    pattern = r"(?:https://www\.re3data\.org/repository/|re3data:)?r3d[0-9]+"
    if re.fullmatch(pattern, identifier):
        return "re3data"
    return None


def _best_scheme(schemes: Iterable[str]) -> str:
    detected = set(schemes)
    for scheme in SCHEME_PRIORITY:
        if scheme in detected:
            return scheme
    raise ValueError(f"No supported identifier scheme found in {sorted(detected)!r}.")

def get_actionable_pid_url(pid: str) -> Optional[str]:
    id_scheme = idutils.detect_identifier_schemes(pid)
    if not id_scheme:
        return None
    pidx = idutils.to_url(pid, id_scheme[0])
    if pidx.lower().startswith("http:"):
        pidx = pidx.lower().replace("http:", "https:")
    return pidx

def _normalize_identifier(identifier: str, scheme: str) -> str:
    normalizer = getattr(idutils, f"normalize_{scheme}", None)
    if normalizer is not None:
        return normalizer(identifier)

    normalize_pid = getattr(idutils, "normalize_pid", None)
    if normalize_pid is not None:
        for args in ((identifier, scheme), (scheme, identifier)):
            try:
                return normalize_pid(*args)
            except TypeError:
                continue

    return identifier


def _to_actionable_iri(normalized: str, scheme: str) -> str:
    if scheme == "doi":
        doi = _strip_any_prefix(normalized, "doi:", "https://doi.org/", "http://doi.org/")
        return f"https://doi.org/{_quote_identifier_path(doi)}"
    if scheme == "handle":
        handle = _strip_any_prefix(normalized, "hdl:", "https://hdl.handle.net/", "http://hdl.handle.net/")
        return f"https://hdl.handle.net/{_quote_identifier_path(handle)}"
    if scheme == "orcid":
        orcid = _strip_any_prefix(normalized, "https://orcid.org/", "http://orcid.org/")
        return f"https://orcid.org/{orcid}"
    if scheme == "ror":
        ror = _strip_any_prefix(normalized, "https://ror.org/", "http://ror.org/")
        return f"https://ror.org/{ror}"
    if scheme == "ark":
        ark = _strip_any_prefix(normalized, "https://n2t.net/", "http://n2t.net/")
        return f"https://n2t.net/{_quote_identifier_path(ark)}"
    if scheme == "pmid":
        pmid = _strip_any_prefix(normalized, "pmid:")
        return f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
    if scheme == "pmcid":
        pmcid = _strip_any_prefix(normalized, "pmcid:")
        return f"https://www.ncbi.nlm.nih.gov/pmc/articles/{pmcid}/"
    if scheme == "arxiv":
        arxiv_id = _strip_any_prefix(normalized, "arxiv:", "https://arxiv.org/abs/", "http://arxiv.org/abs/")
        return f"https://arxiv.org/abs/{_quote_identifier_path(arxiv_id)}"
    if scheme == "isbn":
        isbn = _strip_any_prefix(normalized, "isbn:", "urn:isbn:")
        return f"urn:isbn:{isbn}"
    if scheme == "issn":
        issn = _strip_any_prefix(normalized, "issn:", "urn:issn:")
        return f"urn:issn:{issn}"
    if scheme == "re3data":
        r3d_id = _strip_any_prefix(normalized, "re3data:", "https://www.re3data.org/repository/", "http://www.re3data.org/repository/")
        return f"https://www.re3data.org/repository/{r3d_id}"
    if scheme in {"url", "urn"}:
        return normalized
    raise ValueError(f"Cannot build an actionable IRI for scheme {scheme!r}.")


def _strip_any_prefix(value: str, *prefixes: str) -> str:
    lower_value = value.lower()
    for prefix in prefixes:
        if lower_value.startswith(prefix.lower()):
            return value[len(prefix):]
    return value


def _quote_identifier_path(value: str) -> str:
    return quote(value, safe="/:;()[]@!$&'()*+,=._~-")


def main() -> None:

    dc_identifiers = ["urn:uuid:b3391b53-23c2-473a-9d2e-72674f2b42bd" , "https://pangaea.de/" , "10.25504/FAIRsharing.6yw6cp" , "https://doi.org/10.1594/PANGAEA" , "https://www.pangaea.de/" , "r3d100010134" , "https://doi.org/10.17616/R3XS37" , "https://www.re3data.org/repository/r3d100010134"]
    pidset = set()
    for dc_id in dc_identifiers:
        try:
            resolution = resolve_identifier(dc_id)
            pidset.add(resolution.iri)
        except ValueError as e:
            print(f"Error resolving identifier {dc_id}: {e}")
    print(json.dumps(list(pidset), indent=2))


if __name__ == "__main__":
    main()