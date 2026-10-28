"""fe_places.py: a small gazetteer for the map_route object (format_engine). lon, lat of the places a UK short can name. A map_route whose endpoints are not here is refused
(no object without content): the free model may only route between places this table knows, so every pin lands on a real coordinate."""
PLACES = {
    "london": (-0.12, 51.51), "manchester": (-2.24, 53.48), "birmingham": (-1.90, 52.48), "leeds": (-1.55, 53.80), "liverpool": (-2.98, 53.41), "bristol": (-2.59, 51.45),
    "glasgow": (-4.25, 55.86), "edinburgh": (-3.19, 55.95), "cardiff": (-3.18, 51.48), "belfast": (-5.93, 54.60), "sheffield": (-1.47, 53.38), "newcastle": (-1.61, 54.98),
    "norwich": (1.30, 52.63), "norfolk": (1.0, 52.7), "bentonville": (-94.21, 36.37), "arkansas": (-92.4, 34.9), "walmart": (-94.21, 36.37), "asda": (-1.55, 53.80), "milton keynes": (-0.76, 52.04),
    "dublin": (-6.26, 53.35), "paris": (2.35, 48.86), "berlin": (13.40, 52.52), "madrid": (-3.70, 40.42), "rome": (12.50, 41.90), "amsterdam": (4.90, 52.37), "brussels": (4.35, 50.85),
    "frankfurt": (8.68, 50.11), "zurich": (8.54, 47.38), "stockholm": (18.07, 59.33), "oslo": (10.75, 59.91), "copenhagen": (12.57, 55.68), "warsaw": (21.01, 52.23),
    "new york": (-74.0, 40.71), "washington": (-77.04, 38.91), "san francisco": (-122.42, 37.77), "california": (-119.4, 36.8), "silicon valley": (-122.1, 37.4), "seattle": (-122.33, 47.61),
    "boston": (-71.06, 42.36), "chicago": (-87.63, 41.88), "texas": (-99.0, 31.0), "toronto": (-79.38, 43.65), "mexico city": (-99.13, 19.43), "sao paulo": (-46.63, -23.55),
    "beijing": (116.40, 39.90), "shanghai": (121.47, 31.23), "tokyo": (139.69, 35.69), "seoul": (126.98, 37.57), "singapore": (103.82, 1.35), "hong kong": (114.17, 22.32),
    "india": (78.9, 21.0), "mumbai": (72.88, 19.08), "bangalore": (77.59, 12.97), "dubai": (55.27, 25.20), "tel aviv": (34.78, 32.09), "lagos": (3.38, 6.52), "nairobi": (36.82, -1.29),
    "johannesburg": (28.05, -26.20), "cairo": (31.24, 30.04), "sydney": (151.21, -33.87), "melbourne": (144.96, -37.81), "uk": (-2.0, 54.0), "england": (-1.5, 52.8), "scotland": (-4.2, 56.8),
    "wales": (-3.7, 52.3), "europe": (10.0, 50.0), "america": (-98.0, 39.0), "usa": (-98.0, 39.0), "china": (104.0, 35.0), "ireland": (-8.0, 53.2), "france": (2.4, 46.6), "germany": (10.4, 51.1),
}


def find(name):
    k = " ".join((name or "").lower().replace(".", "").split())
    if k.startswith("the "):
        k = k[4:]
    return PLACES.get(k)
