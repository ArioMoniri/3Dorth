"""3Dorth core — framework-agnostic analysis library (single source of truth).

All analysis logic lives here and returns data (arrays, meshes, stats, figures),
never UI. Both frontends (app_trame, app_react) consume this package; app_react
does so through the FastAPI layer in ``api/``.
"""

__version__ = "0.0.1"
