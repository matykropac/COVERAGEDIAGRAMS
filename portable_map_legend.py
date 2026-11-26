"""Portable Leaflet coverage control embedded in exported HTML."""
import json
from branca.element import MacroElement, Template

class ExportLegend(MacroElement):
    _template = Template("""{% macro script(this, kwargs) %}
(function(){
    const map = {{this._parent.get_name()}};
    const entries = [
    {% for entry in this.entries %}
       {label: {{entry.label}}, color: {{entry.color}}, layer: {{entry.layer}}, hasCoverage: {{entry.has_coverage}}},
    {% endfor %}
    ];
    let opacity = {{this.opacity}};
    const control = L.control({position: 'topright'});
    control.onAdd = function(){
        const panel = L.DomUtil.create('div');
        Object.assign(panel.style, {background:'#fff', color:'#182a3a', padding:'10px',
          borderRadius:'7px', boxShadow:'0 1px 8px #0004', width:'230px', font:'13px Arial,sans-serif'});
        L.DomEvent.disableClickPropagation(panel);
        L.DomEvent.disableScrollPropagation(panel);
        const heading = document.createElement('button');
        heading.type='button'; heading.textContent='COVERAGE · AMSL ▾';
        Object.assign(heading.style,{fontWeight:'bold', width:'100%',textAlign:'left',background:'none',border:'0',cursor:'pointer',padding:'4px'});
        panel.appendChild(heading);
        const body=document.createElement('div'); panel.appendChild(body);
        heading.onclick=()=>{body.hidden=!body.hidden; heading.textContent='COVERAGE · AMSL '+(body.hidden?'▸':'▾');};
        const toolbar=document.createElement('div'); toolbar.style.margin='7px 0'; body.appendChild(toolbar);
        const count=document.createElement('div'); count.style.margin='6px 0'; body.appendChild(count);
        const list=document.createElement('div');
        Object.assign(list.style,{maxHeight:'min(52vh,420px)',overflowY:'auto'});
        body.appendChild(list);
        const checkboxes=[];
        function refresh(){
            let active=0;
            entries.forEach((e,i)=>{checkboxes[i].checked=map.hasLayer(e.layer); if(checkboxes[i].checked) active++;});
            count.textContent=active+' / '+entries.length+' layers visible';
        }
        function applyOpacity(e){e.layer.eachLayer(l=>{if(l.setStyle)l.setStyle({fillOpacity:opacity});});}
        entries.forEach(e=>{
            const row=document.createElement('label');
            Object.assign(row.style,{display:'flex',alignItems:'center',gap:'8px',padding:'5px 1px',cursor:'pointer'});
            const checkbox=document.createElement('input'); checkbox.type='checkbox'; checkbox.checked=false;
            const swatch=document.createElement('span'); Object.assign(swatch.style,{width:'12px',height:'12px',borderRadius:'3px',background:e.color,flexShrink:'0'});
            const title=document.createElement('span');title.textContent=e.label+(e.hasCoverage?'':' · no coverage');
            row.append(checkbox,swatch,title);list.appendChild(row);checkboxes.push(checkbox);
            checkbox.onchange=()=>{if(checkbox.checked){applyOpacity(e);map.addLayer(e.layer);}else{map.removeLayer(e.layer);}refresh();};
        });
        [['All',true],['None',false]].forEach(([label,enabled])=>{
            const b=document.createElement('button');b.type='button';b.textContent=label;b.style.marginRight='6px';
            b.onclick=()=>{entries.forEach(e=>{if(enabled){applyOpacity(e);map.addLayer(e.layer);}else map.removeLayer(e.layer);});refresh();};
            toolbar.appendChild(b);
        });
        const caption=document.createElement('label');caption.style.display='block';caption.style.marginTop='9px';
        const text=document.createElement('span');
        const slider=document.createElement('input');slider.type='range';slider.min='0';slider.max='100';slider.value=Math.round(opacity*100);slider.style.width='100%';
        function updateOpacity(){opacity=Number(slider.value)/100;text.textContent='Coverage opacity: '+slider.value+'%';entries.forEach(applyOpacity);}
        slider.oninput=updateOpacity;caption.append(text,slider);body.appendChild(caption);
        updateOpacity();refresh();map.on('layeradd layerremove',refresh);
        return panel;
    };
    control.addTo(map);
})();
{% endmacro %}""")

    def __init__(self, entries, opacity):
        super().__init__()
        self._name = "ExportLegend"
        self.entries = [
            dict(label=json.dumps(str(label)).replace("<", "\\u003c"),
                 color=json.dumps(str(color)), layer=layer.get_name(),
                 has_coverage="true" if has_coverage else "false")
            for label, color, layer, has_coverage in entries
        ]
        self.opacity = max(0., min(1., float(opacity)))

def add_export_legend(map_obj, entries, opacity=.42):
    ExportLegend(entries, opacity).add_to(map_obj)
