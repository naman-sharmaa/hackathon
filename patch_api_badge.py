import re

with open('frontend/index.html', 'r') as f:
    content = f.read()

# 1. Add apiStatus state and useEffect
api_state_code = """    const [isTyping, setIsTyping] = useState(false);
    const [apiStatus, setApiStatus] = useState('Checking API...');

    useEffect(() => {
      fetch('/api/diagnose?probe=true')
        .then(res => res.json())
        .then(data => {
           if (data.verdict === 'live') {
               setApiStatus('Live API ready');
           } else {
               setApiStatus('Offline Narrator');
           }
        })
        .catch(err => setApiStatus('Offline Narrator'));
    }, []);
"""
content = content.replace("    const [isTyping, setIsTyping] = useState(false);", api_state_code)

# 2. Replace the static text in list view
list_badge = """<div className="badge-api">Live API ready</div>"""
new_list_badge = """<div className="badge-api">
              <span style=${{width:'8px', height:'8px', borderRadius:'50%', display:'inline-block', background: apiStatus === 'Live API ready' ? '#10B981' : (apiStatus === 'Checking API...' ? '#F59E0B' : '#9CA3AF')}}></span>
              ${apiStatus}
            </div>"""

content = content.replace(list_badge, new_list_badge) # This will replace in list and detail view

# 3. Replace the dynamic text in neg view
neg_badge = """<div className="badge-api">${session.live_llm ? 'Live OpenRouter' : 'Offline Narrator'}</div>"""
new_neg_badge = """<div className="badge-api">
              <span style=${{width:'8px', height:'8px', borderRadius:'50%', display:'inline-block', background: session.live_llm ? '#10B981' : '#9CA3AF'}}></span>
              ${session.live_llm ? 'Live OpenRouter' : 'Offline Narrator'}
            </div>"""
content = content.replace(neg_badge, new_neg_badge)

# 4. Remove pseudo-element from CSS
css_old = """.badge-api::before { content:''; width:8px; height:8px; background:#10B981; border-radius:50%; }"""
css_new = """.badge-api-old::before {}"""
content = content.replace(css_old, css_new)

with open('frontend/index.html', 'w') as f:
    f.write(content)
