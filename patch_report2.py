import re

with open('frontend/index.html', 'r') as f:
    content = f.read()

# Fix report variables
content = content.replace("report.total_rounds", "report.rounds_completed || 0")
content = content.replace("report.zopa_size ? formatMoney(report.zopa_size) : 'none'", "report.deal_analysis?.zopa_size ? formatMoney(report.deal_analysis.zopa_size) : 'none'")
content = content.replace("report.leaks_detected", "report.confidence_flags?.leak_failures?.length || 0")
content = content.replace("report.price_inconsistencies", "report.confidence_flags?.price_failures?.length || 0")

with open('frontend/index.html', 'w') as f:
    f.write(content)

