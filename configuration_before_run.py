#!/usr/bin/env python3
"""
Example user script: customize paths and options, then run gtfs2gmns.
After installing gtfs2gmns (pip install gtfs2gmns), copy this file, edit the values below, and run: python configuration_before_run.py
"""
import gtfs2gmns

# ---------- Customize these to your project ----------
INPUT_PATH = "./GTFS/BART"
OUTPUT_PATH = "./GMNS/BART"
TIME_PERIOD = "0700_0800"  # HHMM_HHMM, e.g. 0700_0800 for 7:00–8:00
MAX_BOARDING_WAIT_MINUTES = 10
GENERATE_TRANSFERRING_LINKS = True
TRANSFER_BBOX_DEG = 0.003
TRANSFER_MIN_M = 1.0
TRANSFER_MAX_M = 321.869
# -----------------------------------------------------

if __name__ == "__main__":
    gtfs2gmns.gtfs2gmns(
        INPUT_PATH,
        OUTPUT_PATH,
        time_period=TIME_PERIOD,
        max_boarding_wait_minutes=MAX_BOARDING_WAIT_MINUTES,
        generate_transferring_links=GENERATE_TRANSFERRING_LINKS,
        transfer_bbox_deg=TRANSFER_BBOX_DEG,
        transfer_min_m=TRANSFER_MIN_M,
        transfer_max_m=TRANSFER_MAX_M,
    )
