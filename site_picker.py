"""Helpers for selecting a WGS84 radar site by clicking an interactive map."""
import math


def coordinates_from_map_click(click):
    """Validate Leaflet click coordinates and match six-decimal UI precision.

    Coordinates are latitude/longitude WGS84 in degrees, not map pixel positions.
    The latitude limits match the radar model and existing number inputs.
    """
    if not isinstance(click, dict) or 'lat' not in click or 'lng' not in click:
        raise ValueError('Klikni na požadované místo v mapě.')
    try:
        lat, lon = float(click['lat']), float(click['lng'])
    except (TypeError, ValueError) as exc:
        raise ValueError('Mapa nevrátila platné zeměpisné souřadnice.') from exc
    if not (math.isfinite(lat) and math.isfinite(lon)):
        raise ValueError('Souřadnice musí být konečná čísla.')
    if not (-80 <= lat <= 80 and -180 <= lon <= 180):
        raise ValueError('Poloha leží mimo podporovaný rozsah radaru.')
    return round(lat, 6), round(lon, 6)
