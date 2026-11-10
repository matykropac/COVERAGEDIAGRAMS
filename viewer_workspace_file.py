"""Portable visual workspace preset for COVERAGEDIAGRAMS VIEWER.

Contains vector features and presentation preferences, never executable code
or API credentials. DEM itself remains in the corresponding CDPROJ / DEM cache.
"""
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED, BadZipFile
import json

FORMAT="COVERAGEDIAGRAMS_VIEWER"
MAX_ARCHIVE=50*1024*1024
MAX_JSON=150*1024*1024


def make_workspace(layers,styles,settings):
    payload={"format":FORMAT,"version":1,"layers":layers,"styles":styles,
             "settings":settings}
    data=json.dumps(payload,ensure_ascii=False,allow_nan=False,
                    separators=(",",":")).encode("utf-8")
    if len(data)>MAX_JSON:
        raise ValueError("Projekt VIEWERU překračuje limit 150 MB.")
    output=BytesIO()
    with ZipFile(output,"w",ZIP_DEFLATED,compresslevel=6) as archive:
        archive.writestr("viewer.json",data)
    if output.tell()>MAX_ARCHIVE:
        raise ValueError("Projekt VIEWERU překračuje limit 50 MB.")
    return output.getvalue()


def load_workspace(data):
    if len(data)>MAX_ARCHIVE:
        raise ValueError("Projekt VIEWERU je příliš velký.")
    try:
        with ZipFile(BytesIO(data),"r") as archive:
            if archive.namelist()!=["viewer.json"]:
                raise ValueError("Projekt VIEWERU obsahuje nepovolené soubory.")
            member=archive.getinfo("viewer.json")
            if member.file_size>MAX_JSON:
                raise ValueError("Rozbalená data jsou příliš velká.")
            raw=archive.read(member)
        obj=json.loads(raw)
    except (BadZipFile,KeyError,ValueError,TypeError,UnicodeDecodeError) as exc:
        raise ValueError("Neplatný VIEWER projekt: "+str(exc)) from exc
    if not isinstance(obj,dict) or obj.get("format")!=FORMAT or obj.get("version")!=1:
        raise ValueError("Nepodporovaná verze VIEWER projektu.")
    layers=obj.get("layers")
    styles=obj.get("styles")
    settings=obj.get("settings")
    if not isinstance(layers,dict) or not isinstance(styles,dict) or not isinstance(settings,dict):
        raise ValueError("Projekt VIEWERU nemá správnou strukturu.")
    if len(layers)>300:
        raise ValueError("Projekt obsahuje příliš mnoho vrstev.")
    for key,features in layers.items():
        if not isinstance(key,str) or not isinstance(features,list) or len(features)>100000:
            raise ValueError("Neplatný seznam vrstev.")
        if any(not isinstance(f,dict) or f.get("type")!="Feature"
               or not isinstance(f.get("geometry"),dict) for f in features):
            raise ValueError("Neplatný vektorový objekt.")
    return layers,styles,settings
