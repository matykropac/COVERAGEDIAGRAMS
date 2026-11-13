"""Antenna Lab: validated numerical pattern imports and safe Python expressions.

Expressions are a deliberately limited subset of Python/NumPy; no exec/eval,
attribute access, files, imports or arbitrary code execution on the server.
"""
import ast
import io
import re
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

MAX_FILE=200*1024*1024
MAX_POINTS=1_000_000
MAX_PLOT_POINTS=5000
FUNCTIONS={
    "sin":np.sin,"cos":np.cos,"tan":np.tan,"exp":np.exp,
    "log10":np.log10,"sqrt":np.sqrt,"abs":np.abs,
    "clip":np.clip,"maximum":np.maximum,"minimum":np.minimum,
    "where":np.where,"deg2rad":np.deg2rad,"rad2deg":np.rad2deg,
}
OPS={ast.Add:np.add,ast.Sub:np.subtract,ast.Mult:np.multiply,
     ast.Div:np.divide,ast.Pow:np.power}
UNARY={ast.USub:np.negative,ast.UAdd:np.positive}

def calculate_expression(expression,angle,gain):
    """Evaluate a restricted array expression with bounded AST complexity."""
    if len(expression)>600:raise ValueError("Výraz je příliš dlouhý (max. 600 znaků).")
    tree=ast.parse(expression,mode="eval")
    nodes=list(ast.walk(tree))
    if len(nodes)>80:raise ValueError("Výraz je příliš složitý.")
    variables={"angle":angle,"gain":gain,"pi":np.pi}
    def visit(node,depth=0):
        if depth>18:raise ValueError("Příliš vnořený výraz.")
        if isinstance(node,ast.Expression):return visit(node.body,depth+1)
        if isinstance(node,ast.Constant) and type(node.value) in (int,float):
            if abs(node.value)>1e7:raise ValueError("Konstanta mimo limit.")
            return float(node.value)
        if isinstance(node,ast.Name) and node.id in variables:return variables[node.id]
        if isinstance(node,ast.BinOp) and type(node.op) in OPS:
            if isinstance(node.op,ast.Pow):
                if not isinstance(node.right,ast.Constant) or type(node.right.value) not in (int,float) or abs(node.right.value)>8:
                    raise ValueError("Mocnina smí mít konstantní exponent od -8 do 8.")
            return OPS[type(node.op)](visit(node.left,depth+1),visit(node.right,depth+1))
        if isinstance(node,ast.UnaryOp) and type(node.op) in UNARY:
            return UNARY[type(node.op)](visit(node.operand,depth+1))
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id in FUNCTIONS and not node.keywords:
            args=[visit(a,depth+1) for a in node.args]
            return FUNCTIONS[node.func.id](*args)
        raise ValueError("Nepovolená konstrukce Python výrazu. Použij pouze angle, gain a povolené NumPy funkce.")
    with np.errstate(all="ignore"):
        value=np.asarray(visit(tree),dtype=float)
    try:value=np.broadcast_to(value,angle.shape).copy()
    except ValueError as exc:raise ValueError("Výsledek musí mít stejnou délku jako úhly.") from exc
    if not np.all(np.isfinite(value)):raise ValueError("Výsledná křivka obsahuje neplatné hodnoty.")
    if np.max(np.abs(value))>200:raise ValueError("Zisk mimo povolený rozsah ±200 dB.")
    return value

def read_pattern(raw):
    if len(raw)>MAX_FILE:raise ValueError("Soubor překračuje 200 MB.")
    # Iterate over text lines instead of allocating source.splitlines() for
    # every line in a potentially 200 MB upload. Large 2D/3D matrices need
    # a different loader and are not silently truncated into this 1D format.
    try:
        raw.decode("utf-8-sig")
        charset="utf-8-sig"
    except UnicodeDecodeError:
        charset="cp1250"
    rows=[]
    with io.TextIOWrapper(io.BytesIO(raw),encoding=charset) as source:
        for line in source:
            line=line.strip()
            if not line or line.startswith(("#","//","%")):continue
            parts=[v for v in re.split(r"[,;\\s]+",line) if v]
            if len(parts)<2:continue
            try:rows.append((float(parts[0]),float(parts[1])))
            except ValueError:continue
            if len(rows)>MAX_POINTS:
                raise ValueError("1D LAB podporuje nejvýše 1 000 000 vzorků; 2D/3D matice vyžadují samostatný importér.")
    if len(rows)<3:raise ValueError("Jsou potřeba alespoň 3 řádky: angle_deg, gain_db.")
    data=np.asarray(rows,dtype=float)
    angle,gain=data[:,0],data[:,1]
    if not np.all(np.isfinite(data)):raise ValueError("Neplatné hodnoty NaN/Inf.")
    order=np.argsort(angle);angle,gain=angle[order],gain[order]
    if len(np.unique(angle))!=len(angle):raise ValueError("Duplicitní úhly nejsou povoleny.")
    if np.min(angle)<-180 or np.max(angle)>180:raise ValueError("Rozsah úhlu musí být -180 až 180°.")
    if np.max(np.abs(gain))>200:raise ValueError("Zisk mimo ±200 dB.")
    return angle,gain

def render_lab(original=None):
    st.caption("ANTENNA LAB · numerická experimentální laboratoř, oddělená od certifikovaného RF modelu.")
    st.caption("Import do 200 MB na soubor; tento editor podporuje 1D charakteristiku, maximálně 1 000 000 úhlových vzorků.")
    uploaded=st.file_uploader("Import skutečné charakteristiky · CSV / TXT",
                              type=["csv","txt"],key="lab_pattern_upload")
    if uploaded is not None:
        try:
            angle,gain=read_pattern(uploaded.getvalue())
            st.session_state["lab_source"]={"angle":angle.tolist(),"gain":gain.tolist(),
                                             "name":uploaded.name}
        except (ValueError,UnicodeDecodeError) as exc:
            st.error(str(exc))
    if "lab_source" not in st.session_state and original is not None:
        try:
            angles=np.asarray(original.angles_deg,dtype=float)
            gains=np.asarray(original.gain_db(np.deg2rad(angles)),dtype=float)
            if angles.ndim==1 and gains.shape==angles.shape and len(angles)>2:
                st.session_state["lab_source"]={"angle":angles.tolist(),
                                                "gain":gains.tolist(),
                                                "name":getattr(original,"name","Model")}
        except (TypeError,AttributeError,ValueError):
            pass
    source=st.session_state.get("lab_source")
    if not source:
        st.info("Nahraj CSV/TXT obsahující dvojice úhel [°] a relativní zisk [dB].")
        return
    angles=np.asarray(source["angle"],dtype=float)
    gains=np.asarray(source["gain"],dtype=float)
    st.caption("Původ: "+str(source.get("name","Data"))+
               " · "+str(len(angles))+" vzorků. Neznámá kalibrace je vždy označena jako relativní.")
    st.markdown("**PYTHON EXPRESSION · omezený NumPy režim**")
    code=st.text_area("Uprav pole gain pomocí angle [°] a gain [dB]",
                      value="gain",height=105,key="lab_code",
                      help="Např. gain - 3, gain + 2*cos(deg2rad(angle)), clip(gain,-45,0). Nejde o plný Python runtime.")
    st.caption("Povolené: sin, cos, tan, exp, log10, sqrt, abs, clip, minimum, maximum, where, deg2rad, rad2deg. Žádné exec, importy ani přístup k souborům.")
    try:edited=calculate_expression(code,angles,gains)
    except (ValueError,TypeError,SyntaxError,OverflowError) as exc:
        st.error("Výraz: "+str(exc));return
    fig=go.Figure()
    plot_step=max(1,int(np.ceil(len(angles)/MAX_PLOT_POINTS)))
    fig.add_scatter(x=angles[::plot_step],y=gains[::plot_step],name="Původní",mode="lines")
    fig.add_scatter(x=angles[::plot_step],y=edited[::plot_step],name="Upravený · LAB",mode="lines")
    fig.update_layout(height=360,margin=dict(l=12,r=10,t=16,b=20),
                      xaxis_title="Elevace [°]",yaxis_title="Relativní zisk [dB]",
                      template="plotly_white")
    st.plotly_chart(fig,use_container_width=True,key="lab_comparison")
    c1,c2,c3=st.columns(3)
    c1.metric("Vzorky",len(angles))
    c2.metric("Maximum",f"{np.max(edited):.2f} dB")
    c3.metric("Max. změna",f"{np.max(np.abs(edited-gains)):.2f} dB")
    if st.button("POUŽÍT UPRAVENÝ DIAGRAM PRO MAPOVÝ NÁHLED",type="primary",
                 key="lab_apply_preview",use_container_width=True):
        st.session_state["lab_preview"]={"angle":angles.tolist(),"gain":edited.tolist(),
                                          "source":source["name"],"code":code}
        st.success("Model uložen pro nezávislou mapovou projekci. Výpočetní solver se nezměnil.")
    if st.session_state.get("lab_preview"):
        st.info("Aktivní experimentální model: mapový náhled. Výpočet radarového krytí stále používá původní model.")
