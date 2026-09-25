"""Publication identity rules for Fog of Time.

A publication is the bibliographic object a claim is traced to, so two records
must only become one when the evidence says they are the same work. These rules
prefer an explicit verdict with a named rule over silent heuristic merging:

    same          one work; the records may be merged
    probable_same very likely one work; reported for review, never auto-merged
    related       linked but distinct works (erratum, reply, preprint, other part
                  or edition); never merged
    conflict      identifiers disagree with each other; never merged, reported
    distinct      different works

Only ``same`` permits a merge. Everything else keeps both records.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Any, Iterable

IDENTITY_RULES_VERSION = "publication-identity/v1"

DOI_PREFIXES = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", re.IGNORECASE)
# Look-alike slashes seen in PBDB DOIs ("10.1111 ⁄ j.1502-...").
SLASH_LOOKALIKES = str.maketrans({"⁄": "/", "∕": "/", "／": "/"})
VALID_DOI = re.compile(r"^10\.\d{4,9}/\S+$")
# Titles that announce a work *about* another work: never the same publication.
RELATED_MARKERS = re.compile(
    r"\b(?:corrigendum|erratum|errata|correction to|retraction|reply to|response to|comment on|"
    r"discussion of|supplementary|supplement to|addendum|preprint)\b",
    re.IGNORECASE,
)


def fold(value: str) -> str:
    return unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().casefold()


def normalize_title(title: str | None) -> str:
    """Letters and digits only, accents and case folded."""
    return re.sub(r"[^a-z0-9]", "", fold(title or ""))


@dataclass(frozen=True)
class DoiNormalization:
    raw: str | None
    normalized: str | None
    # "ok", "repaired" (cosmetic, lossless: whitespace, prefix, look-alike slash)
    # or "invalid" (kept verbatim, never used for matching).
    status: str
    note: str | None = None


def normalize_doi(raw: str | None) -> DoiNormalization:
    """Normalize a DOI without guessing.

    Cosmetic damage (a resolver prefix, stray whitespace, a look-alike slash,
    case) is repaired because it cannot change which work is meant. A DOI that
    is still malformed afterwards is reported as invalid and not used for
    identity, rather than being "fixed" by inventing missing characters.
    """
    if raw is None or not str(raw).strip():
        return DoiNormalization(raw, None, "ok")
    text = str(raw).strip()
    value = DOI_PREFIXES.sub("", text).translate(SLASH_LOOKALIKES)
    value = re.sub(r"\s+", "", value).casefold()
    if not VALID_DOI.match(value):
        return DoiNormalization(raw, None, "invalid", f"not a DOI after cosmetic repair: {text!r}")
    if value == text.casefold():
        return DoiNormalization(raw, value, "ok")
    return DoiNormalization(raw, value, "repaired", f"cosmetic repair of {text!r}")


def first_author_surname(authors: Iterable[str] | None) -> str:
    """The first author's surname, folded; initials ("P. M.") are dropped so
    hyphenated and spaced forms of one surname end the same way."""
    for author in authors or []:
        words = [word for word in re.sub(r"[.,]", " ", author).split() if len(word) > 1 or not word.isalpha()]
        if words:
            return normalize_title(words[-1].split("-")[-1])
    return ""


@dataclass(frozen=True)
class IdentityVerdict:
    verdict: str
    rule: str
    detail: str

    @property
    def may_merge(self) -> bool:
        return self.verdict == "same"


def compare(a: dict[str, Any], b: dict[str, Any]) -> IdentityVerdict:
    """Decide whether two publication records describe the same work.

    Each record needs ``title`` and ``year`` and may carry ``doi`` and
    ``authors``. The first matching rule wins, and the rule name is recorded.
    """
    doi_a, doi_b = normalize_doi(a.get("doi")).normalized, normalize_doi(b.get("doi")).normalized
    title_a, title_b = normalize_title(a.get("title")), normalize_title(b.get("title"))
    same_title = bool(title_a) and title_a == title_b
    related = bool(RELATED_MARKERS.search(a.get("title") or "")) != bool(RELATED_MARKERS.search(b.get("title") or ""))

    if doi_a and doi_b:
        if doi_a != doi_b:
            return IdentityVerdict("distinct", "doi_differs", f"{doi_a} != {doi_b}")
        if related:
            return IdentityVerdict("conflict", "doi_equal_but_one_is_a_related_notice", doi_a)
        if same_title:
            return IdentityVerdict("same", "doi_and_title_equal", doi_a)
        # A shared DOI with different titles is a book DOI on its chapters, or a
        # data-entry error. Either way it is not safe to merge.
        return IdentityVerdict("conflict", "doi_equal_titles_differ", doi_a)

    if related:
        return IdentityVerdict("related", "one_title_is_a_related_notice", "erratum/reply/supplement/preprint marker")
    if not same_title:
        return IdentityVerdict("distinct", "titles_differ", "")
    surname_a, surname_b = first_author_surname(a.get("authors")), first_author_surname(b.get("authors"))
    if a.get("year") != b.get("year"):
        # Same title in different years: editions, annual reports, reprints,
        # or chapters of the same name in different books.
        return IdentityVerdict("distinct", "same_title_different_year", f"{a.get('year')} vs {b.get('year')}")
    # "Pereda-Suberbiola" and "Pereda Suberbiola", "von Huene" and "Huene".
    same_author = bool(surname_a and surname_b) and (surname_a.endswith(surname_b) or surname_b.endswith(surname_a))
    if same_author:
        container_a, container_b = normalize_title(a.get("journal")), normalize_title(b.get("journal"))
        if container_a and container_b and container_a != container_b:
            return IdentityVerdict("probable_same", "title_year_author_equal_container_differs", "")
        return IdentityVerdict("probable_same", "title_year_first_author_equal_no_doi", "")
    # Title-only equality is never identity ("Ceratosauria", "Sauropoda").
    return IdentityVerdict("distinct", "title_only_equal", "")


def audit(publications: list[dict[str, Any]]) -> dict[str, Any]:
    """Every identity issue in a corpus of publication records.

    Returns DOI problems and every pair whose verdict is not ``distinct``.
    Pairs are only formed between records that share a normalized DOI or a
    normalized title, so the audit stays linear in practice.
    """
    doi_issues = []
    buckets: dict[str, list[dict[str, Any]]] = {}
    for publication in publications:
        doi = normalize_doi(publication.get("doi"))
        if doi.status != "ok":
            doi_issues.append({"publication_id": publication["id"], "status": doi.status, "raw": doi.raw, "normalized": doi.normalized})
        keys = {f"title:{normalize_title(publication.get('title'))}"}
        if doi.normalized:
            keys.add(f"doi:{doi.normalized}")
        for key in keys:
            buckets.setdefault(key, []).append(publication)

    pairs: dict[tuple[str, str], dict[str, Any]] = {}
    for members in buckets.values():
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                key = tuple(sorted((a["id"], b["id"])))
                if key in pairs:
                    continue
                verdict = compare(a, b)
                pairs[key] = {"a": key[0], "b": key[1], "verdict": verdict.verdict, "rule": verdict.rule, "detail": verdict.detail}
    return {
        "rules_version": IDENTITY_RULES_VERSION,
        "doi_issues": sorted(doi_issues, key=lambda item: item["publication_id"]),
        "pairs": sorted(pairs.values(), key=lambda item: (item["verdict"], item["a"], item["b"])),
    }
