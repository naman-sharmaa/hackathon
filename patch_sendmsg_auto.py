import re

with open('frontend/index.html', 'r') as f:
    content = f.read()

old_sendMsg = """    const sendMsg = async () => {
      if (!humanMsg.trim()) return;
      setLoading(true);
      try {
        const res = await fetch(`/session/${session.id}/message`, {
          method: 'POST',
          headers: {'Content-Type':'application/json'},
          body: JSON.stringify({message: humanMsg})
        });
        const data = await res.json();
        if (data.error) {
           alert("Out of Scope: " + data.error);
        } else {
           setSession(data.session);
           setHumanMsg('');
           if(data.session.status !== 'active') fetchReport(data.session.id);
        }
      } catch(err) {}
      setLoading(false);
    };"""

new_sendMsg = """    const sendMsg = async () => {
      if (!humanMsg.trim()) return;
      setLoading(true);
      try {
        const res = await fetch(`/session/${session.id}/message`, {
          method: 'POST',
          headers: {'Content-Type':'application/json'},
          body: JSON.stringify({message: humanMsg})
        });
        const data = await res.json();
        if (data.error) {
           alert("Out of Scope: " + data.error);
           setLoading(false);
        } else {
           setSession(data.session);
           setHumanMsg('');
           if(data.session.status !== 'active') {
               fetchReport(data.session.id);
               setLoading(false);
           } else {
               await intervene('return_to_ai');
               // intervene handles setLoading(false)
           }
        }
      } catch(err) {
         setLoading(false);
      }
    };"""

content = content.replace(old_sendMsg, new_sendMsg)

with open('frontend/index.html', 'w') as f:
    f.write(content)

