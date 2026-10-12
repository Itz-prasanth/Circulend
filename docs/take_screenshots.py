"""Drives the real running app (Flask + PostgreSQL) in headless Chromium and saves the demo screenshots."""
import os, subprocess, json, urllib.request
from playwright.sync_api import sync_playwright

BASE = "http://localhost:5000"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "shots"); os.makedirs(OUT, exist_ok=True)
n = [0]

def shot(page, name, full=False):
    page.evaluate("const t=document.querySelector('#toast'); while(t && t.children.length>1) t.removeChild(t.firstChild)")
    n[0] += 1; p = f"{OUT}/{n[0]:02d}_{name}.png"; page.wait_for_timeout(450); page.screenshot(path=p, full_page=full); print("saved", p)

def login(page, email):
    page.goto(BASE); page.wait_for_selector("#em"); page.fill("#em", email); page.fill("#pw", "circulend123")

def main():
    members = json.load(urllib.request.urlopen(BASE + "/api/demo-accounts"))
    member = [m for m in members if m["role"] == "member"][0]; staff = [m for m in members if m["role"] == "staff"][0]
    with sync_playwright() as p:
        b = p.chromium.launch(args=["--no-sandbox"])
        # ───────── member session ─────────
        ctx = b.new_context(viewport={"width": 1280, "height": 860}); pg = ctx.new_page()
        pg.goto(BASE); pg.wait_for_selector("#em"); shot(pg, "login")
        login(pg, member["email"]); pg.click("button.btn:text-is('Sign in')"); pg.wait_for_selector("#tools .card")
        shot(pg, "browse_all_tools")
        pg.click(".chip:has-text('Power Tools')"); pg.wait_for_selector("#tools .card"); shot(pg, "browse_category_power_tools")
        pg.locator(".card:has(h3:text-is('Jigsaw')) button:has-text('Reserve')").click(); pg.wait_for_selector("#ru"); shot(pg, "reserve_dialog_next_available")
        pg.click("#go"); pg.wait_for_selector(".t.ok"); shot(pg, "reservation_confirmed")
        pg.click(".chip:has-text('Garden')"); pg.wait_for_selector("#tools .card")
        pg.locator(".card:has(h3:text-is('Pressure Washer')) button:has-text('Join waitlist')").click(); pg.wait_for_selector("#go"); pg.click("#go")
        pg.wait_for_selector(".t.ok:has-text('waitlist')"); shot(pg, "all_units_out_joined_waitlist")
        pg.locator(".card:has(h3:text-is('Pressure Washer')) button:has-text('Units')").click(); shot(pg, "individual_units_view")
        pg.mouse.click(10, 10)
        pg.click("nav >> text=Kits"); pg.wait_for_selector(".g3 .card"); shot(pg, "kits_availability_view")
        pg.click("nav >> text=My account"); pg.wait_for_selector("h2:has-text('My account')"); shot(pg, "member_account", full=True)
        ctx.close()

        # ───────── staff session ─────────
        ctx = b.new_context(viewport={"width": 1280, "height": 860}); pg = ctx.new_page()
        login(pg, staff["email"]); pg.click("button.btn:text-is('Sign in')"); pg.wait_for_selector("h2:has-text('Staff desk')")
        pg.wait_for_selector("table tr td"); shot(pg, "staff_open_loans", full=True)
        # kit checkout blocked (Tile Cutter is out) → atomic rollback
        pg.click("nav >> text=Kits"); pg.wait_for_selector(".g3 .card")
        pg.locator(".card:has(h3:text-is('Home Renovation Kit')) button:has-text('Check out kit')").click(); pg.wait_for_selector("#km"); pg.click("#go")
        pg.wait_for_selector(".t.err"); shot(pg, "kit_checkout_blocked_atomic")
        pg.mouse.click(10, 10)
        pg.locator(".card:has(h3:text-is('Weekend Camping Kit')) button:has-text('Check out kit')").click(); pg.wait_for_selector("#km"); shot(pg, "kit_checkout_dialog")
        pg.click("#go"); pg.wait_for_selector(".t.ok"); shot(pg, "kit_checked_out_all_components")
        # walk-in checkout
        pg.click("nav >> text=Staff desk"); pg.wait_for_selector("h2:has-text('Staff desk')"); pg.click(".tabs >> text=Check-out"); pg.wait_for_selector("#mu option", state="attached")
        pg.select_option("#mt", label="Hand Saw (2 free)") if pg.locator("#mt option:has-text('Hand Saw (2 free)')").count() else None
        pg.select_option("#mm", index=1); shot(pg, "staff_checkout_form"); pg.click("button.btn:text-is('Check out')"); pg.wait_for_selector(".t.ok"); shot(pg, "walk_in_checkout_done")
        # waitlist cascade: return a Pressure Washer
        pg.click(".tabs >> text=Open loans"); pg.wait_for_selector("table tr td")
        pg.locator("tr:has-text('Pressure Washer') >> button:has-text('Return')").first.click(); pg.wait_for_selector("#sv"); shot(pg, "checkin_dialog")
        pg.click("#go"); pg.wait_for_selector(".t.ok"); shot(pg, "return_triggers_waitlist_cascade")
        # damage auto-flag
        pg.locator("tr:has-text('Cordless Drill') >> button:has-text('Return')").first.click(); pg.wait_for_selector("#sv")
        pg.select_option("#sv", "Major"); pg.fill("#nt", "Chuck cracked after drop"); shot(pg, "checkin_with_major_damage")
        pg.click("#go"); pg.wait_for_selector(".t.ok"); shot(pg, "damage_trigger_unit_flagged_repair")
        pg.click(".tabs >> text=Repair bench"); pg.wait_for_selector("table"); shot(pg, "repair_bench")
        pg.click(".tabs >> text=Reservations to collect"); pg.wait_for_selector("table"); shot(pg, "reservations_to_collect", full=True)
        pg.click(".tabs >> text=Deposits"); pg.wait_for_selector("#deps table"); pg.locator("#deps tr:has(td) >> button:has-text('Release')").first.click()
        pg.wait_for_selector(".t"); shot(pg, "deposit_release_guarded")
        pg.click("nav >> text=Dashboard"); pg.wait_for_selector(".kpi"); shot(pg, "dashboard", full=True)
        pg.click("nav >> text=Concurrency lab"); pg.wait_for_selector("text=Run all four"); pg.click("text=Run all four")
        pg.wait_for_function("document.querySelector('#o_unique_constraint').textContent.includes('verdict')", timeout=30000)
        shot(pg, "concurrency_lab_results", full=True)
        ctx.close(); b.close()

if __name__ == "__main__":
    main()
