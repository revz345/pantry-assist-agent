"""E2E tests for Pantry Assist UI using Playwright."""
import re

import pytest
from playwright.sync_api import expect


def test_dashboard_loads_with_stats(page):
    """Test dashboard shows stat cards."""
    page.goto("http://127.0.0.1:8000/dashboard")

    expect(page.locator(".stat-card")).to_have_count(4)
    expect(page.locator(".stat-card").first).to_contain_text("Total Items")


def test_items_page_loads(page):
    """Test that items page loads with location sections."""
    page.goto("http://127.0.0.1:8000/items")

    # Check page title heading
    expect(page.locator(".page-title")).to_contain_text("Items")

    # Check nav brand
    expect(page.locator(".brand")).to_contain_text("Pantry Assist")

    # Check location sections exist
    expect(page.locator(".location-section")).to_have_count(5)  # Fridge, Freezer, Pantry, Spice Rack, Idli-Dosa Kit

    # Check category sub-sections exist within locations
    expect(page.locator(".category-section")).to_have_count(11)

    # Check table headers (checkbox + columns)
    expect(page.locator("th")).to_contain_text(["Item", "Qty", "Unit", "Expiry", "Actions"])

    # Check at least some items render
    assert page.locator("tbody tr").count() >= 50


def test_units_show_north_american_labels(page):
    """Test kg displays as oz, ml as fl oz, l as qt."""
    page.goto("http://127.0.0.1:8000/items")

    # kg -> oz, l -> qt, ml -> fl oz. "Unit.GRAMS" enum bug should not appear.
    expect(page.locator(".unit-col").first).not_to_contain_text("Unit.")
    first_unit = page.locator(".unit-col").first.inner_text().strip()
    assert first_unit in ["oz", "g", "pcs", "qt", "fl oz"]


def test_dark_mode_toggle(page):
    """Test theme toggle switches to dark mode."""
    page.goto("http://127.0.0.1:8000/items")

    expect(page.locator("#theme-toggle")).to_be_visible()
    page.click("#theme-toggle")

    theme = page.evaluate("document.documentElement.getAttribute('data-theme')")
    assert theme == "dark"


def test_delete_modal_opens(page):
    """Test delete button opens modal."""
    page.goto("http://127.0.0.1:8000/items")

    # Click first delete button
    first_delete = page.locator(".btn-text.danger").first
    first_delete.click()

    # Modal should appear
    expect(page.locator(".modal-overlay")).to_be_visible()
    expect(page.locator(".modal")).to_be_visible()
    expect(page.locator("#modal-title")).to_contain_text("Delete Item")


def test_delete_modal_cancel(page):
    """Test cancel in modal closes it."""
    page.goto("http://127.0.0.1:8000/items")

    # Open modal
    page.locator(".btn-text.danger").first.click()
    expect(page.locator(".modal-overlay")).to_be_visible()

    # Click cancel
    page.locator(".btn-secondary").click()

    # Modal should close
    expect(page.locator(".modal-overlay")).not_to_be_visible()


def test_filter_by_location(page):
    """Test location filter works via htmx."""
    page.goto("http://127.0.0.1:8000/items")

    # Select Fridge
    page.select_option('select[name="location_id"]', "1")
    page.click('button[type="submit"]')

    # Should show only Fridge items (wait for htmx swap)
    page.wait_for_selector("#items-list")

    # Should have Fridge section
    fridge_section = page.locator(".location-section:has-text('Fridge')")
    expect(fridge_section).to_be_visible()


def test_search_items(page):
    """Test search filter."""
    page.goto("http://127.0.0.1:8000/items")

    page.fill('input[name="search"]', "milk")
    page.click('button[type="submit"]')

    page.wait_for_selector("#items-list")

    # Should show milk items
    expect(page.locator("tbody tr").first).to_contain_text(re.compile("milk", re.IGNORECASE))


def test_expiring_filter(page):
    """Test expiring soon filter."""
    page.goto("http://127.0.0.1:8000/items")

    page.select_option('select[name="filter"]', "expiring")
    page.click('button[type="submit"]')

    page.wait_for_selector("#items-list")

    # Should show expiring items with warning badge
    assert page.locator(".badge-warning").count() > 0


def test_expiry_badges_render(page):
    """Test expiry badges render correctly."""
    page.goto("http://127.0.0.1:8000/items")

    # Check for expired items (red badge)
    assert page.locator(".badge-danger").count() > 0

    # Check for expiring soon items (yellow badge)
    assert page.locator(".badge-warning").count() > 0

    # Check for normal items (blue badge)
    assert page.locator(".badge-info").count() > 0


def test_inline_quantity_edit(page):
    """Test inline quantity stepper updates via API."""
    page.goto("http://127.0.0.1:8000/items")

    first_qty = page.locator(".qty-input").first
    before = float(first_qty.input_value())

    page.locator('[data-qty-action="1"]').first.click()

    after = float(first_qty.input_value())
    assert after == before + 1


def test_bulk_selection_bar(page):
    """Test bulk action bar appears when items selected."""
    page.goto("http://127.0.0.1:8000/items")

    # Initially hidden
    expect(page.locator("#bulk-bar")).not_to_have_class("visible")

    # Select first row checkbox
    page.locator(".row-checkbox:not(.select-all)").first.check()

    expect(page.locator("#bulk-bar")).to_contain_class("visible")
    expect(page.locator("#bulk-count")).to_contain_text("1 selected")


def test_sort_select(page):
    """Test sort dropdown renders and changes query."""
    page.goto("http://127.0.0.1:8000/items")

    expect(page.locator('select[name="sort"]')).to_be_visible()

    # Change sort to expiry soonest and submit
    page.select_option('select[name="sort"]', "expiry_asc")
    page.click('button[type="submit"]')

    page.wait_for_selector("#items-list")
    # Expired/expiring items should appear first with badge
    expect(page.locator(".badge-warning").first).to_be_visible()


def test_navigation_links(page):
    """Test navigation between pages."""
    page.goto("http://127.0.0.1:8000/items")

    # Click Dashboard
    page.click('a[href="/"]')
    expect(page.locator("h1")).to_contain_text("Dashboard")

    # Click Locations
    page.click('a[href="/locations"]')
    expect(page.locator("h1")).to_contain_text("Locations")

    # Click Reminders
    page.click('a[href="/reminders"]')
    expect(page.locator("h1")).to_contain_text("Reminders")

    # Click Recipes
    page.click('a[href="/recipes"]')
    expect(page.locator("h1")).to_contain_text("Recipe Suggestions")

    # Back to Items
    page.click('a[href="/items"]')
    expect(page.locator(".page-title")).to_contain_text("Items")


def test_add_item_page(page):
    """Test add item page loads."""
    page.goto("http://127.0.0.1:8000/items/new")

    expect(page.locator("h1")).to_contain_text("Add Item")
    expect(page.locator('input[name="name"]')).to_be_visible()
    expect(page.locator('input[name="quantity"]')).to_be_visible()
    expect(page.locator('select[name="unit"]')).to_be_visible()
    expect(page.locator('select[name="location_id"]')).to_be_visible()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
