"""Portable, versioned COVERAGEDIAGRAMS project archive (.cdproj).

Only JSON and NumPy numeric arrays are loaded; pickle and executable content are
never accepted. The embedded raw DEM matrix enables reproducible coverage recovery.
"""
from dataclasses import asdict
from io import BytesIO
import json
from zipfile import ZipFile, ZIP_DEFLATED, BadZipFile
import numpy as np
import radar_core as core
from antenna_snapshot import pack as pack_antenna, unpack as unpack_antenna
from obstacles import obstacle_signature, validate_obstacle

FORMAT = 'COVERAGEDIAGRAMS'
VERSION = 1
ARRAYS = ('az', 'distance', 'terrain', 'lower', 'upper', 'status', 'target', 'horizon', 'known')
MAX_ARCHIVE = 100 * 1024 * 1024
MAX_UNPACKED = 220 * 1024 * 1024


def save_project(result, *, levels, obstacles, display=None, source_ui=None):
    """Return compressed bytes for a self-contained, read-only result snapshot."""
    if (not isinstance(levels,(tuple,list)) or len(levels)>core.PAR_CUSTOM_MAX_COUNT or
            any(not core.valid_flight_level(result['config'].radar_mode,ft) for ft in levels)):
        raise ValueError('Neplatný výběr výškových hladin pro projekt.')
    meta = dict(format=FORMAT, version=VERSION, config=asdict(result['config']),
                levels=list(levels), obstacles=list(obstacles),
                display=display or {}, source_ui=source_ui or {},
                source=result.get('source', ''), completed_at=result.get('completed_at', ''),
                duration_s=result.get('duration_s', 0), antenna=float(result['antenna']),
                site_height=float(result['site_height']))
    pattern_meta, pattern_arrays = pack_antenna(result.get('antenna_pattern'))
    meta['antenna_pattern'] = pattern_meta
    buf = BytesIO()
    with ZipFile(buf, 'w', ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr('project.json', json.dumps(meta, ensure_ascii=False, allow_nan=False))
        arrays = BytesIO()
        data_arrays = {key: np.asarray(result[key]) for key in ARRAYS}
        data_arrays.update(pattern_arrays)
        np.savez_compressed(arrays, **data_arrays)
        archive.writestr('calculation.npz', arrays.getvalue())
    return buf.getvalue()


def load_project(blob, antenna_pattern=None):
    """Validate archive, restore computed matrices and associated UI metadata."""
    if len(blob) > MAX_ARCHIVE:
        raise ValueError('Projekt přesahuje povolenou velikost 100 MB.')
    try:
        with ZipFile(BytesIO(blob), 'r') as archive:
            names = set(archive.namelist())
            if names != {'project.json', 'calculation.npz'}:
                raise ValueError('Projekt obsahuje neočekávané soubory.')
            if sum(item.file_size for item in archive.infolist()) > MAX_UNPACKED:
                raise ValueError('Rozbalená data projektu jsou příliš velká.')
            meta = json.loads(archive.read('project.json'))
            if not isinstance(meta, dict) or meta.get('format') != FORMAT or meta.get('version') != VERSION:
                raise ValueError('Nepodporovaná verze projektového souboru.')
            config_data = meta['config']
            if set(config_data) != set(core.Config.__dataclass_fields__):
                raise ValueError('Nekompatibilní parametry radarového modelu.')
            config = core.Config(**config_data)
            config.validate()
            with np.load(BytesIO(archive.read('calculation.npz')), allow_pickle=False) as pack:
                expected = set(ARRAYS)
                if not expected.issubset(pack.files):
                    raise ValueError('V projektu chybí výpočetní matice.')
                extra = set(pack.files) - expected
                pattern_meta = meta.get('antenna_pattern')
                if pattern_meta is None and extra:
                    raise ValueError('Neočekávaná anténní data ve starším projektu.')
                if pattern_meta is None:
                    if set(pack.files) != expected:
                        raise ValueError('Nekompatibilní starší projekt.')
                    restored_pattern = antenna_pattern
                else:
                    pattern_arrays = {key: pack[key] for key in extra}
                    restored_pattern = unpack_antenna(pattern_meta, pattern_arrays)
                    if antenna_pattern is not None:
                        # Caller-supplied override is explicit; otherwise use exact
                        # stored model to prevent recalculation with a wrong default.
                        restored_pattern = antenna_pattern
                data = {key: pack[key] for key in ARRAYS}
    except (BadZipFile, KeyError, TypeError, UnicodeError, ValueError) as exc:
        raise ValueError('Nelze načíst projekt: ' + str(exc)) from exc
    az, dist = core.axes(config)
    shape = (len(az), len(dist))
    if data['az'].shape != az.shape or data['distance'].shape != dist.shape:
        raise ValueError('Projekt neodpovídá síti aktuálního výpočtu.')
    if not np.allclose(data['az'], az) or not np.allclose(data['distance'], dist):
        raise ValueError('Síť projektu neodpovídá nastavení radaru.')
    for key in ARRAYS:
        expected = az.shape if key == 'az' else dist.shape if key == 'distance' else shape
        if data[key].shape != expected or data[key].dtype.kind not in 'biuf':
            raise ValueError('Neplatná data matice ' + key)
    obstacles = meta.get('obstacles', [])
    if not isinstance(obstacles, list) or len(obstacles) > 1000:
        raise ValueError('Neplatný seznam překážek.')
    for item in obstacles:
        if not isinstance(item, dict):
            raise ValueError('Neplatný záznam překážky v projektu.')
        try:
            validate_obstacle(item, config.lat, config.lon,
                                  enforce_point_range=False)
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise ValueError('Neplatná překážka v projektu: ' + str(exc)) from exc
    levels = meta.get('levels', [])
    if (not isinstance(levels,list) or len(levels)>core.PAR_CUSTOM_MAX_COUNT or
            any(not core.valid_flight_level(config.radar_mode,l) for l in levels)):
        raise ValueError('Neplatný výběr výškových hladin.')
    result = dict(data, config=config, antenna=meta['antenna'], site_height=meta['site_height'],
                  antenna_pattern=restored_pattern, obstacles=obstacles,
                  obstacles_signature=obstacle_signature(obstacles),
                  source=meta.get('source', 'PROJECT'), completed_at=meta.get('completed_at', ''),
                  duration_s=meta.get('duration_s', 0))
    return result, meta
