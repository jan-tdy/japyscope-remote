"""SmartSearch across local catalogs and CDS Sesame.

Sesame is deliberately optional.  A failed or slow network request returns
the local matches immediately and records SEARCH-001 instead of making the
controller unusable away from Wi-Fi.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Iterable, Optional
from urllib.parse import quote
from xml.etree.ElementTree import ParseError

import requests
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

logger = logging.getLogger(__name__)

SESAME_URL = "https://cds.unistra.fr/cgi-bin/nph-sesame/-oxp/SNV?{query}"


@dataclass(frozen=True)
class SearchResult:
    name: str
    ra: str = ""
    dec: str = ""
    type: str = ""
    source: str = "local"
    alt: Optional[float] = None


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


class SmartSearch:
    def __init__(self, timeout: float = 3.0, session: Optional[requests.Session] = None):
        self.timeout = timeout
        self.session = session or requests.Session()

    def search(
        self, query: str, local_objects: Iterable[SearchResult]
    ) -> tuple[list[SearchResult], bool]:
        """Return `(results, online_available)` with local matches first."""
        needle = _normalise(query)
        local = [item for item in local_objects if needle in _normalise(item.name)]
        try:
            online = self.resolve_online(query)
        except (requests.RequestException, ParseError, DefusedXmlException, ValueError) as exc:
            logger.warning("SEARCH-001 online lookup failed; local results only: %s", exc)
            return local, False
        if online and all(_normalise(item.name) != _normalise(online.name) for item in local):
            local.append(online)
        return local, True

    def resolve_online(self, query: str) -> Optional[SearchResult]:
        response = self.session.get(
            SESAME_URL.format(query=quote(query.strip(), safe="")), timeout=self.timeout
        )
        response.raise_for_status()
        root = ElementTree.fromstring(response.text)
        resolver = root.find(".//Resolver")
        if resolver is None:
            return None
        name = resolver.findtext("oname") or query.strip()
        ra = resolver.findtext("jradeg") or ""
        dec = resolver.findtext("jdedeg") or ""
        if not ra or not dec:
            return None
        return SearchResult(name=name, ra=ra, dec=dec, source="sesame")
