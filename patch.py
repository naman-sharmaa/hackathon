import re

with open('frontend/index.html', 'r') as f:
    content = f.read()

# 1. Add CSS for typing indicator
css_to_add = """
  .typing-indicator {
    display: flex;
    align-items: center;
    gap: 4px;
    padding: 0.2rem 0.5rem;
    height: 24px;
  }
  .typing-indicator span {
    width: 6px;
    height: 6px;
    background-color: #9CA3AF;
    border-radius: 50%;
    animation: typing 1.4s infinite ease-in-out both;
  }
  .typing-indicator span:nth-child(1) { animation-delay: -0.32s; }
  .typing-indicator span:nth-child(2) { animation-delay: -0.16s; }
  @keyframes typing {
    0%, 80%, 100% { transform: scale(0); }
    40% { transform: scale(1); }
  }
</style>
"""
content = content.replace('</style>', css_to_add)

# 2. Replace the 'Thinking...' block
# Find the block and replace it
old_thinking = """<div className="bubble" style=${{background: 'transparent', fontStyle: 'italic', color: '#9CA3AF', padding: '0.5rem'}}>Thinking...</div>"""
new_thinking = """<div className="bubble" style=${{background: 'transparent', padding: '0.5rem'}}>
                         <div className="typing-indicator"><span></span><span></span><span></span></div>
                       </div>"""

content = content.replace(old_thinking, new_thinking)

with open('frontend/index.html', 'w') as f:
    f.write(content)

