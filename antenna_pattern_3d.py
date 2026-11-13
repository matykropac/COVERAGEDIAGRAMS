"""CSV long-form 3D antenna AZ/EL pattern import, validation and slice analysis.

Format: az_deg,el_deg,gain_db (one sample per row). No guessing unit axes.
No user Python code execution. Preview is explicitly separate from radar solver.
"""
from dataclasses import dataclass
from io import BytesIO, TextIOWrapper
import csv
import hashlib
import numpy as np

MAX_UPLOAD_BYTES = 200 * 1024 * 1024
MAX_SAMPLES = 1_000_000
MAX_GRID_CELLS = 1_000_000


@dataclass(frozen=True)
class PatternGrid3D:
    az_deg: np.ndarray
    el_deg: np.ndarray
    gain_db: np.ndarray
    source_sha256: str
    origin: str
    source_name: str

    def az_cut(self, elevation_deg):
        j=int(np.argmin(abs(self.el_deg-float(elevation_deg))))
        return self.az_deg, self.gain_db[:,j], float(self.el_deg[j])

    def el_cut(self, azimuth_deg):
        delta=((self.az_deg-float(azimuth_deg)+180)%360)-180
        i=int(np.argmin(abs(delta)))
        return self.el_deg, self.gain_db[i,:], float(self.az_deg[i])

    @property
    def peak_db(self):
        return float(np.max(self.gain_db))


def read_3d_csv(data, *, source_name="antenna.csv", origin="UNKNOWN"):
    """Parse a regular complete 3D angular grid, preserving original samples.

    CSV header must have exactly az_deg,el_deg,gain_db (additional columns
    rejected). Decimal dot and UTF-8 are required. Az angles wrap at 360;
    -180 and +180 therefore represent the same direction and are rejected
    as duplicates. Input is bounded by number of points as well as bytes.
    """
    if not isinstance(data, bytes):
        raise TypeError("3D import expects bytes")
    if len(data)>MAX_UPLOAD_BYTES:
        raise ValueError("Soubor překračuje 200 MB.")
    if origin not in ("MEASURED","SIMULATED","DERIVED","UNKNOWN"):
        raise ValueError("Unknown provenance classification")
    if not source_name or len(source_name)>220:
        raise ValueError("Invalid source filename")
    rows=[]
    try:
        with TextIOWrapper(BytesIO(data),encoding="utf-8-sig",newline="") as stream:
            reader=csv.DictReader(stream,skipinitialspace=True)
            if reader.fieldnames is None or [v.strip() for v in reader.fieldnames]!=["az_deg","el_deg","gain_db"]:
                raise ValueError("CSV musí mít hlavičku: az_deg,el_deg,gain_db")
            for record in reader:
                if set(record)!=set(reader.fieldnames) or any(v is None or v=="" for v in record.values()):
                    raise ValueError("Nekompletní záznam nebo nesprávný počet sloupců")
                try:
                    a,e,g=(float(record[name]) for name in reader.fieldnames)
                except (TypeError,ValueError) as exc:
                    raise ValueError("Nečíselná hodnota anténního diagramu") from exc
                if not all(np.isfinite((a,e,g))):
                    raise ValueError("NaN/Inf nejsou povolené")
                if not (0<=a<360 and -90<=e<=90 and -200<=g<=200):
                    raise ValueError("AZ musí být 0 až <360°, EL -90 až 90°, zisk -200 až 200 dB")
                rows.append((a,e,g))
                if len(rows)>MAX_SAMPLES:
                    raise ValueError("Maximum 1 000 000 záznamů v jednom 3D diagramu")
    except UnicodeDecodeError as exc:
        raise ValueError("3D CSV musí být UTF-8") from exc
    if len(rows)<9:
        raise ValueError("3D charakteristika vyžaduje alespoň 3×3 vzorky")
    values=np.asarray(rows,dtype=np.float64)
    az,azidx=np.unique(values[:,0],return_inverse=True)
    el,elidx=np.unique(values[:,1],return_inverse=True)
    if az.size<3 or el.size<3 or az.size*el.size>MAX_GRID_CELLS:
        raise ValueError("Neplatná nebo příliš velká AZ/EL mřížka")
    if az.size*el.size!=len(rows):
        raise ValueError("3D AZ/EL mřížka není kompletní nebo obsahuje duplicitní body")
    linear=azidx*el.size+elidx
    if len(np.unique(linear))!=len(rows):
        raise ValueError("Duplicitní kombinace AZ/EL")
    grid=np.empty((len(az),len(el)),dtype=np.float32)
    grid[azidx,elidx]=values[:,2].astype(np.float32)
    return PatternGrid3D(
        az_deg=az,el_deg=el,gain_db=grid,
        source_sha256=hashlib.sha256(data).hexdigest(),
        origin=origin,source_name=source_name,
    )


def half_power_beamwidth(angles_deg,gains_db):
    """3 dB angular width around main-peak; None if crossings are not sampled."""
    angles=np.asarray(angles_deg,dtype=float)
    gain=np.asarray(gains_db,dtype=float)
    if angles.ndim!=1 or gain.shape!=angles.shape or len(angles)<3:
        raise ValueError("Invalid one-dimensional cut")
    if np.any(np.diff(angles)<=0) or not np.isfinite(gain).all():
        raise ValueError("Cut axis must be strictly increasing with finite gain")
    peak=int(np.argmax(gain));threshold=gain[peak]-3.01029995664
    left=peak
    while left>0 and gain[left]>=threshold:left-=1
    right=peak
    while right<len(gain)-1 and gain[right]>=threshold:right+=1
    if left==0 and gain[left]>=threshold:return None
    if right==len(gain)-1 and gain[right]>=threshold:return None
    def crossing(i,j):
        d=gain[j]-gain[i]
        if abs(d)<1e-12:return float(angles[i])
        return float(angles[i]+(threshold-gain[i])*(angles[j]-angles[i])/d)
    return crossing(right-1,right)-crossing(left,left+1)
