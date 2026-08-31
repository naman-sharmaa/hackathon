import re

with open('frontend/index.html', 'r') as f:
    content = f.read()

# Fix formatMoney
old_format_money = """function formatMoney(n) {
    return "$" + n.toLocaleString();
  }"""
new_format_money = """function formatMoney(n) {
    return "$" + Math.round(n).toLocaleString('en-US');
  }"""
content = content.replace(old_format_money, new_format_money)

# Fix report variables
old_report_html = """<div className="r-box"><h5>Final Price</h5><div style=${{fontSize:'1.8rem', fontWeight:700}}>${report.final_price ? formatMoney(report.final_price) : '—'}</div></div>
                  <div className="r-box"><h5>Rounds</h5><div style=${{fontSize:'1.8rem', fontWeight:700}}">${report.total_rounds}</div></div>
                  <div className="r-box"><h5>ZOPA Width</h5><div style=${{fontSize:'1.8rem', fontWeight:700}}">${report.zopa_size ? formatMoney(report.zopa_size) : 'none'}</div></div>
                  <div className="r-box"><h5>Integrity & Provenance</h5>
                    <ul style=${{margin:0, paddingLeft:'1.2rem', color:'#4B5563', fontSize:'0.9rem'}}>
                      <li>Leaks: ${report.leaks_detected}</li>
                      <li>Inconsistencies: ${report.price_inconsistencies}</li>
                      <li>Clean run: ${report.clean ? 'Yes' : 'No'}</li>
                    </ul>
                  </div>"""

new_report_html = """<div className="r-box"><h5>Final Price</h5><div style=${{fontSize:'1.8rem', fontWeight:700}}>${report.final_price ? formatMoney(report.final_price) : '—'}</div></div>
                  <div className="r-box"><h5>Rounds</h5><div style=${{fontSize:'1.8rem', fontWeight:700}}">${report.rounds_completed || 0}</div></div>
                  <div className="r-box"><h5>ZOPA Width</h5><div style=${{fontSize:'1.8rem', fontWeight:700}}">${report.deal_analysis?.zopa_size ? formatMoney(report.deal_analysis.zopa_size) : 'none'}</div></div>
                  <div className="r-box"><h5>Integrity & Provenance</h5>
                    <ul style=${{margin:0, paddingLeft:'1.2rem', color:'#4B5563', fontSize:'0.9rem'}}>
                      <li>Leaks: ${report.confidence_flags?.leak_failures?.length || 0}</li>
                      <li>Inconsistencies: ${report.confidence_flags?.price_failures?.length || 0}</li>
                      <li>Clean run: ${report.clean ? 'Yes' : 'No'}</li>
                    </ul>
                  </div>"""

if old_report_html in content:
    content = content.replace(old_report_html, new_report_html)
else:
    print("WARNING: Could not find old report html directly, doing regex replace.")

with open('frontend/index.html', 'w') as f:
    f.write(content)

