from datetime import date
from typing import Any

_DEFAULT_LICENSES = ["dl-de/by-2-0"]


def envelope(
    results: Any,
    sources_used: list[str] | None = None,
    import_run_ids: list[int] | None = None,
    extra_meta: dict | None = None,
    licenses: list[str] | None = None,
) -> dict:
    """Wrap API results in the standard license envelope."""
    metadata: dict = {
        "sources_used": sources_used or [],
        "licenses": licenses if licenses is not None else _DEFAULT_LICENSES,
        "snapshot_date": date.today().isoformat(),
        "import_run_ids": import_run_ids or [],
    }
    if extra_meta:
        metadata.update(extra_meta)
    return {"results": results, "metadata": metadata}
