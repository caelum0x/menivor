"""Store catalog import: Shopify / WooCommerce public product feeds -> Ad Studio.

* :mod:`.parsing` - pure normalizers for Shopify ``/products.json`` and the
  WooCommerce Store API (``/wp-json/wc/store/v1/products``) into one product
  record shape (prices in integer minor units, capped images/tags).
* :mod:`.fetching` - store URL -> feed pages through the Ad Studio SSRF guard.
* :mod:`.service` - persist imports (``store_catalog_imports`` /
  ``store_catalog_products``) and turn picked products into Ad Studio projects.
* :mod:`.routes` - HTTP routes under ``/ad-studio/catalog``.

Only public, unauthenticated feeds are read: no store admin token, no app
review. Stores that disable these feeds (password-protected Shopify, Woo with
the Store API blocked) answer with a clear error instead of a partial import.
"""
