"""Shared response metadata for SQL-paginated collection endpoints."""
from fastapi import Response


def apply_pagination_headers(response: Response, *, total: int, page: int, limit: int) -> None:
    response.headers["X-Total-Count"] = str(total)
    response.headers["X-Page"] = str(page)
    response.headers["X-Page-Size"] = str(limit)
    response.headers["X-Total-Pages"] = str((total + limit - 1) // limit)
