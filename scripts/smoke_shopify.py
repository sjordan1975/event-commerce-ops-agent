"""Smoke test for live Shopify API calls.

Run after setting credentials in .env:

    .venv/bin/python scripts/smoke_shopify.py [--basic] [--with-image] [--cleanup]

Without flags both tests run. --cleanup deletes draft products after verifying creation.

--basic   : productCreate only (no image)
--with-image : productCreate + stagedUpload + productCreateMedia (the full execution flow)

Exit code 0 = all tests passed.
"""

import argparse
import os
import sys

from dotenv import load_dotenv

load_dotenv()

try:
    import httpx
except ImportError:
    sys.exit("httpx not installed — run: .venv/bin/pip install -e '.[dev]'")


# ---------------------------------------------------------------------------
# Shopify GraphQL mutations
# ---------------------------------------------------------------------------

_SHOPIFY_API_VERSION = "2026-04"

_PRODUCT_CREATE = """
mutation productCreate($input: ProductInput!) {
  productCreate(input: $input) {
    product { id handle title }
    userErrors { field message }
  }
}
"""

_PRODUCT_DELETE = """
mutation productDelete($input: ProductDeleteInput!) {
  productDelete(input: $input) {
    deletedProductId
    userErrors { field message }
  }
}
"""

_STAGED_UPLOADS_CREATE = """
mutation stagedUploadsCreate($input: [StagedUploadInput!]!) {
  stagedUploadsCreate(input: $input) {
    stagedTargets {
      url
      resourceUrl
      parameters { name value }
    }
    userErrors { field message }
  }
}
"""

_PRODUCT_CREATE_MEDIA = """
mutation productCreateMedia($productId: ID!, $media: [CreateMediaInput!]!) {
  productCreateMedia(productId: $productId, media: $media) {
    media { id status mediaContentType }
    mediaUserErrors { field message code }
  }
}
"""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _fetch_token(store_url: str) -> str:
    resp = httpx.post(
        f"{store_url}/admin/oauth/access_token",
        json={
            "client_id": os.environ["SHOPIFY_CLIENT_ID"],
            "client_secret": os.environ["SHOPIFY_CLIENT_SECRET"],
            "grant_type": "client_credentials",
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _check_creds() -> tuple[str, str] | None:
    """Return (store_url, token) or None if creds missing."""
    store_url = os.environ.get("SHOPIFY_STORE_URL", "").rstrip("/")
    if not store_url or not os.environ.get("SHOPIFY_CLIENT_ID") or not os.environ.get("SHOPIFY_CLIENT_SECRET"):
        return None
    try:
        token = _fetch_token(store_url)
        print(f"[shopify] Token acquired (prefix: {token[:8]}...)")
        return store_url, token
    except Exception as e:
        print(f"[shopify] FAIL — could not fetch token: {e}")
        return None


def _delete_product(endpoint: str, headers: dict, product_id: str) -> None:
    resp = httpx.post(endpoint, json={
        "query": _PRODUCT_DELETE,
        "variables": {"input": {"id": product_id}},
    }, headers=headers, timeout=30)
    resp.raise_for_status()
    errors = resp.json().get("data", {}).get("productDelete", {}).get("userErrors", [])
    if errors:
        print(f"[shopify] cleanup WARN — {errors}")
    else:
        print(f"[shopify] Cleaned up.")


# ---------------------------------------------------------------------------
# Test: basic product create
# ---------------------------------------------------------------------------

def smoke_basic(cleanup: bool) -> bool:
    creds = _check_creds()
    if creds is None:
        print("[shopify/basic] SKIP — SHOPIFY_STORE_URL, SHOPIFY_CLIENT_ID, or SHOPIFY_CLIENT_SECRET not set")
        return True
    store_url, token = creds
    endpoint = f"{store_url}/admin/api/{_SHOPIFY_API_VERSION}/graphql.json"
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}

    print(f"[shopify/basic] Creating draft product ...")
    resp = httpx.post(endpoint, json={
        "query": _PRODUCT_CREATE,
        "variables": {"input": {
            "title": "Smoke Test — Basic (safe to delete)",
            "descriptionHtml": "<p>Created by smoke_shopify.py</p>",
            "status": "DRAFT",
        }},
    }, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    errors = data.get("data", {}).get("productCreate", {}).get("userErrors", [])
    if errors:
        print(f"[shopify/basic] FAIL — {errors}")
        return False

    product_id = data["data"]["productCreate"]["product"]["id"]
    numeric_id = product_id.split("/")[-1]
    print(f"[shopify/basic] OK — {store_url}/admin/products/{numeric_id}")

    if cleanup:
        _delete_product(endpoint, headers, product_id)
    return True


# ---------------------------------------------------------------------------
# Test: product create with image (full execution flow)
# ---------------------------------------------------------------------------

def smoke_with_image(cleanup: bool) -> bool:
    creds = _check_creds()
    if creds is None:
        print("[shopify/with-image] SKIP — Shopify creds not set")
        return True
    store_url, token = creds
    endpoint = f"{store_url}/admin/api/{_SHOPIFY_API_VERSION}/graphql.json"
    headers = {"X-Shopify-Access-Token": token, "Content-Type": "application/json"}

    # Download test image
    print(f"[shopify/with-image] Downloading test image ...")
    img_resp = httpx.get("https://picsum.photos/1800/1800", follow_redirects=True, timeout=30)
    img_resp.raise_for_status()
    img_bytes = img_resp.content
    print(f"[shopify/with-image] Image: {len(img_bytes):,} bytes")

    # Create product
    print(f"[shopify/with-image] Creating draft product ...")
    resp = httpx.post(endpoint, json={
        "query": _PRODUCT_CREATE,
        "variables": {"input": {
            "title": "Smoke Test — With Image (safe to delete)",
            "descriptionHtml": "<p>Created by smoke_shopify.py</p>",
            "status": "DRAFT",
        }},
    }, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    errors = data.get("data", {}).get("productCreate", {}).get("userErrors", [])
    if errors:
        print(f"[shopify/with-image] FAIL — productCreate: {errors}")
        return False
    product_id = data["data"]["productCreate"]["product"]["id"]
    numeric_id = product_id.split("/")[-1]
    print(f"[shopify/with-image] Product created — {store_url}/admin/products/{numeric_id}")

    # Staged upload
    print(f"[shopify/with-image] Requesting staged upload target ...")
    resp = httpx.post(endpoint, json={
        "query": _STAGED_UPLOADS_CREATE,
        "variables": {"input": [{
            "filename": "mockup.jpg",
            "mimeType": "image/jpeg",
            "resource": "PRODUCT_IMAGE",
            "httpMethod": "POST",
        }]},
    }, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    errors = data.get("data", {}).get("stagedUploadsCreate", {}).get("userErrors", [])
    if errors:
        print(f"[shopify/with-image] FAIL — stagedUploadsCreate: {errors}")
        return False
    target = data["data"]["stagedUploadsCreate"]["stagedTargets"][0]
    resource_url = target["resourceUrl"]
    params = {p["name"]: p["value"] for p in target["parameters"]}

    print(f"[shopify/with-image] Uploading image ...")
    form_fields = [(k, (None, v)) for k, v in params.items()]
    form_fields.append(("file", ("mockup.jpg", img_bytes, "image/jpeg")))
    upload_resp = httpx.post(target["url"], files=form_fields, timeout=60)
    if upload_resp.status_code >= 400:
        print(f"[shopify/with-image] FAIL — upload HTTP {upload_resp.status_code}: {upload_resp.text[:200]}")
        return False
    print(f"[shopify/with-image] Upload OK (HTTP {upload_resp.status_code})")

    # Attach image
    print(f"[shopify/with-image] Attaching image to product ...")
    resp = httpx.post(endpoint, json={
        "query": _PRODUCT_CREATE_MEDIA,
        "variables": {
            "productId": product_id,
            "media": [{"originalSource": resource_url, "mediaContentType": "IMAGE"}],
        },
    }, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    media_errors = data.get("data", {}).get("productCreateMedia", {}).get("mediaUserErrors", [])
    if media_errors:
        print(f"[shopify/with-image] FAIL — productCreateMedia: {media_errors}")
        return False
    media = data["data"]["productCreateMedia"]["media"]
    print(f"[shopify/with-image] OK — image attached, status={media[0]['status'] if media else 'unknown'}")
    print(f"[shopify/with-image]      View: {store_url}/admin/products/{numeric_id}")

    if cleanup:
        _delete_product(endpoint, headers, product_id)
    return True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test live Shopify API integration")
    parser.add_argument("--basic", action="store_true", help="Test productCreate only")
    parser.add_argument("--with-image", action="store_true", help="Test productCreate + staged upload + productCreateMedia")
    parser.add_argument("--cleanup", action="store_true", help="Delete draft products after verifying")
    args = parser.parse_args()

    any_explicit = args.basic or args.with_image
    run_basic = args.basic or not any_explicit
    run_with_image = args.with_image or not any_explicit

    results: list[bool] = []
    if run_basic:
        results.append(smoke_basic(cleanup=args.cleanup))
    if run_with_image:
        results.append(smoke_with_image(cleanup=args.cleanup))

    if all(results):
        print("\nAll tests passed.")
        sys.exit(0)
    else:
        print("\nOne or more tests failed — see output above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
