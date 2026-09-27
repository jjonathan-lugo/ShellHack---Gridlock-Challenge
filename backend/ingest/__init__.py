"""Automatic ingest: source PDFs -> project tables -> coordinates -> overlaps.

This automates Parts 1-3 of Sperry Tech's Finding_Real_Locations_Guide:

  extract.py   pull project lists out of the two utility PDFs
  names.py     split a project name into its named sub-points ("A - B 115 kV" -> A, B)
  geocode.py   match sub-points to OpenStreetMap power substations (one bulk
               Overpass query, per the guide), Nominatim as a fallback, with a
               confidence flag on every match (guide Part 2)
  pipeline.py  run it all and write data/processed/auto/*.json plus a report
               comparing against the hand-geocoded spreadsheet
  watch.py     re-run automatically whenever the spreadsheet or PDFs change
"""
