# Copyright (c) 2026 A2A Sales Catalog Authors. All Rights Reserved.
# Proprietary and confidential. See LICENSE for terms.

"""Example: Consumer agent querying the A2A Sales Catalog."""

from src.client.catalog_client import CatalogClient


def main():
    # Connect to the catalog
    client = CatalogClient("http://localhost:8000")

    # 1. Discover what the server can do
    card = client.agent_card()
    print(f"Connected to: {card['name']} v{card['version']}")
    print(f"Skills: {[s['id'] for s in card['skills']]}\n")

    # 2. Search for wireless earbuds
    print("=== Search: wireless earbuds ===")
    result = client.search("wireless earbuds", max_results=5)
    items = CatalogClient.tuples_to_dicts(result["fields"], result["items"])
    for item in items:
        sponsored = " [SPONSORED]" if item["sponsored"] else ""
        print(f"  {item['id']} | {item['name']} | ${item['price_cents']/100:.2f} | ★{item['rating']}{sponsored}")

    # 3. Lookup full details
    if items:
        first_id = items[0]["id"]
        print(f"\n=== Lookup: {first_id} ===")
        detail = client.lookup(first_id)
        print(f"  {detail['name']} — {detail['desc']}")
        print(f"  Price: ${detail['price_cents']/100:.2f} {detail['currency']}")
        print(f"  Vendor: {detail['vendor']}")
        print(f"  Attrs: {detail['attrs']}")

    # 4. Compare top results
    if len(items) >= 2:
        ids = [i["id"] for i in items[:3]]
        print(f"\n=== Compare: {ids} ===")
        comp = client.compare(ids)
        print(f"  Fields: {comp['fields']}")
        for row in comp["rows"]:
            print(f"  {row}")

    # 5. Browse categories
    print("\n=== Categories ===")
    cats = client.categories()
    for cat in CatalogClient.tuples_to_dicts(cats["fields"], cats["cats"]):
        print(f"  {cat['id']}: {cat['label']} ({cat['item_count']} items)")


if __name__ == "__main__":
    main()
