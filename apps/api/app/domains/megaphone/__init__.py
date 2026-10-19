"""Megaphone: Menivor markets our own products with Menivor.

Every week a box timer renders short videos for Bidstage, Scribase Mail
Studio, Oxhan Atelier and Menivor itself through Menivor's PUBLIC API (the
same capture -> reel -> dub path a customer uses, free voices only), then
publishes them to ``media.menivor.com/megaphone/`` with a JSON manifest that
each product site embeds (video + VideoObject structured data + video
sitemap). Each video ends on a "Made with Menivor" card.

Run on the box: ``deploy/megaphone/run-weekly.sh`` (systemd timer).
"""
