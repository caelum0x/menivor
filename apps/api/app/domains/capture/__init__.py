"""Capture: turn a website, web game or store listing into a promo video.

A capture job records a source URL (website, playable web game, App Store or
Play Store listing), drives a headless browser / store-listing fetch in a
worker, and stores the resulting video key, screenshots and listing metadata.
Built first to market our own apps, games and sites; the same path serves
customers. Table from migration ``a7d3e9c1f2b4``.
"""
