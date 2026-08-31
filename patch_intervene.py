import re

with open('frontend/index.html', 'r') as f:
    content = f.read()

# 1. Update intervene function
old_intervene = """    const intervene = async (action) => {
      setLoading(true);
      try {
        const res = await fetch(`/session/${session.id}/intervene`, {
          method: 'POST',
          headers: {'Content-Type':'application/json'},
          body: JSON.stringify({side: session.turn, action})
        });"""

new_intervene = """    const intervene = async (action, targetSide = 'buyer') => {
      setLoading(true);
      try {
        const res = await fetch(`/session/${session.id}/intervene`, {
          method: 'POST',
          headers: {'Content-Type':'application/json'},
          body: JSON.stringify({side: targetSide, action})
        });"""
content = content.replace(old_intervene, new_intervene)

# 2. Update Take over as buyer button
old_take_over_btn = """<button className="btn btn-primary" style=${{background:'transparent', color:'#6B7280', border:'1px solid #E5E7EB'}} onClick=${()=>{setAutoPlay(false); intervene('take_over');}} disabled=${loading}>
                        Take over as buyer
                      </button>"""
new_take_over_btn = """<button className="btn btn-primary" style=${{background:'transparent', color:'#6B7280', border:'1px solid #E5E7EB'}} onClick=${()=>intervene('take_over', 'buyer')} disabled=${loading}>
                        Take over as buyer
                      </button>"""
content = content.replace(old_take_over_btn, new_take_over_btn)

with open('frontend/index.html', 'w') as f:
    f.write(content)

